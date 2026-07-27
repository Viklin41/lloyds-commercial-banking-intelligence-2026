"""Step 6: models over the step-5 labels, plus SHAP.

Step 5 decided what "good" means. This module tries to predict it, honestly.

Everything here is driven off ``targets`` rather than off literals. That is
deliberate and it is the main design constraint:

- the feature list is ``targets.FEATURE_COLS``, never a copy of it;
- the target list is ``targets.TARGETS``, never four hard-coded names;
- the categoricals are ``targets.CATEGORICAL_COLS``;
- the origin grid per target is read **off disk**, from that target's own matrix
  partitions, not from a shared assumption about which months exist.

The reason is the lender harvest running against the Charges API. When it lands it
adds feature columns (including at least one new categorical, the lender group) and
probably a fifth switching target on a *different* base population: "has an
outstanding Lloyds charge at t", not "Active at t". If step 6 reads the constants,
all of that is a zero-line change here. If it hard-codes anything, it is a hunt.

Which is also why this module trains now, on the features we already have, rather
than waiting. The out-of-time AUC recorded today is the only thing that can later
say whether 24 hours of harvesting bought anything. Same A/B design as the strict
vs extended contract comparison.

**No hyperparameter tuning.** Fixed, sensible LightGBM settings. Tuning against a
feature set that is about to gain columns is wasted work; tune once, at the end, on
the final matrix.

Three things that are easy to get wrong and are handled explicitly:

1. **The split is out-of-time with an embargo.** Train on early origins, test on
   late ones, and drop the origins in between whose label windows would resolve
   inside the test period. A random split leaks twice over: the same company
   appears in up to 33 monthly rows, and the future gets mixed into the past.
2. **precision@N is computed on the unsampled population.** The training matrix
   downsamples negatives ~10x, which inflates precision@N and PR-AUC by roughly
   that factor. ROC-AUC survives negative downsampling; those two do not. So the
   test origins are rebuilt without downsampling and scored there.
3. **Predicted probabilities are recalibrated** back to the true base rate with the
   per-row ``neg_keep_rate`` step 5 carried along. Ranking survives downsampling;
   the numbers do not, and "12% chance of insolvency" is a lie until corrected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ..features import contracts, panel
from . import targets

EVAL_MATRIX_DIR = Path("data/processed/eval_matrix")
SCORE_DIR = Path("data/processed/scores")
RESULTS_PATH = Path("reports/step6_model_results.json")

# Number of trailing origins held out as the out-of-time test period.
N_TEST_ORIGINS = 2

# Below this many training origins we would rather drop `targets.FIRST_FULL_ORIGIN`
# than train on almost nothing. See `split_origins`.
MIN_TRAIN_ORIGINS = 3

# Call-list sizes a relationship manager could actually work through.
TOP_N = (100, 500, 1000)

# Fixed, untuned, and chosen to be unremarkable. The point of this run is a
# baseline to measure the lender features against, not a leaderboard score.
LGB_PARAMS = dict(
    objective="binary",
    n_estimators=1500,
    learning_rate=0.05,
    num_leaves=63,
    min_child_samples=200,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    n_jobs=6,
    verbose=-1,
)

# Not a tuning knob, a workaround, and worth writing down because it cost an hour.
# `n_jobs=-1` reads 22 logical cores under WSL2 and then spends all its time in
# thread contention: 50 boosting rounds on the 165k-row insolvency matrix took
# **98 seconds** at n_jobs=-1 and **0.9 seconds** at n_jobs=8. Two orders of
# magnitude, same result. Anything in the 4-8 range is fine; -1 is not.

# Early stopping needs a validation set, and it must not be the test set (that is
# tuning on the exam). We carve one out of the training rows grouped by company, so
# no company straddles the boundary.
EARLY_STOPPING_ROUNDS = 100
VALID_FRACTION = 0.15

# The logistic floor is a sanity check, not a production model, and lbfgs on
# several million dense rows costs minutes for no extra information. Cap it.
LOGIT_MAX_ROWS = 500_000

# TreeExplainer is exact for trees, but exact still costs time per row. 100k
# stratified rows is plenty for a stable summary plot.
SHAP_SAMPLE = 100_000

RANDOM_STATE = 42


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #

@dataclass
class Split:
    """The out-of-time split for one target, and why it looks the way it does."""

    target: str
    horizon_m: int
    train: list[pd.Timestamp]
    embargo: list[pd.Timestamp]
    test: list[pd.Timestamp]
    dropped_early: list[pd.Timestamp] = field(default_factory=list)
    first_full_origin_applied: bool = True

    def describe(self) -> str:
        fmt = lambda ms: ", ".join(m.strftime("%Y-%m") for m in ms) or "-"
        return (
            f"{self.target} (H={self.horizon_m}m)\n"
            f"  train   : {fmt(self.train)}\n"
            f"  embargo : {fmt(self.embargo)}  (dropped, labels resolve inside test)\n"
            f"  test    : {fmt(self.test)}\n"
            f"  early-origin filter applied: {self.first_full_origin_applied}"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("train", "embargo", "test", "dropped_early"):
            d[k] = [m.strftime("%Y-%m-%d") for m in d[k]]
        return d


def matrix_origins(target: str, matrix_dir: Path = targets.MATRIX_DIR) -> list[pd.Timestamp]:
    """Origin months actually present on disk for this target.

    Read from the partition directories rather than recomputed, because a target
    need not span the same months as the others: the horizons differ today, and a
    target on a different base population (a switching label needs an outstanding
    charge at ``t``) will differ by more than that tomorrow.
    """
    root = matrix_dir / target
    months = sorted(
        pd.Timestamp(p.name.split("=", 1)[1])
        for p in root.iterdir()
        if p.is_dir() and p.name.startswith("origin_month=")
    )
    if not months:
        raise FileNotFoundError(f"no origin partitions under {root}")
    return months


def split_origins(
    target: str,
    matrix_dir: Path = targets.MATRIX_DIR,
    n_test: int = N_TEST_ORIGINS,
    min_train_origins: int = MIN_TRAIN_ORIGINS,
) -> Split:
    """Out-of-time split with an embargo gap of at least the horizon.

    A training row at origin ``t`` carries a label that resolves over
    ``t+1 ... t+H``. If the first test origin sits inside that window the model was
    trained on the answer to its own exam, so every origin with
    ``first_test - t < H`` months is dropped rather than trained on. At the
    boundary (``first_test - t == H``) the training label resolves in the test
    origin's *feature* month, which is data the model is given anyway, and the test
    labels only start at ``first_test + 1``. That is clean, so the gap is ``>= H``.

    ``targets.FIRST_FULL_ORIGIN`` is applied first, because before it the 12-month
    deltas are NULL for calendar reasons and that missingness pattern lands entirely
    in train and never in test, which is exactly the kind of artefact a tree will
    split on. It is dropped again if honouring it would leave fewer than
    ``min_train_origins`` training origins, which is the trade `targets` flags for
    the 12-month growth label.
    """
    _, horizon = targets.TARGETS[target]
    all_months = matrix_origins(target, matrix_dir)

    def build(months: list[pd.Timestamp], applied: bool) -> Split:
        test = months[-n_test:]
        first_test = test[0]
        head = months[:-n_test]
        embargo = [m for m in head if (first_test.year - m.year) * 12 + first_test.month - m.month < horizon]
        train = [m for m in head if m not in embargo]
        return Split(
            target=target,
            horizon_m=horizon,
            train=train,
            embargo=embargo,
            test=test,
            dropped_early=[m for m in all_months if m not in months],
            first_full_origin_applied=applied,
        )

    kept = [m for m in all_months if m >= targets.FIRST_FULL_ORIGIN]
    split = build(kept, True) if len(kept) > n_test else build(all_months, False)
    if len(split.train) < min_train_origins:
        split = build(all_months, False)
    if not split.train:
        raise ValueError(f"{target}: no training origins survive the embargo")
    return split


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def load_origins(
    target: str,
    origins: list[pd.Timestamp],
    matrix_dir: Path = targets.MATRIX_DIR,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Read the given origin partitions of a target's matrix.

    Only the partitions asked for are touched, so the out-of-time split never has
    the test months in memory while training.
    """
    cols = columns or targets.FEATURE_COLS
    select = ", ".join(f'"{c}"' for c in ["CompanyNumber", "origin_month", "y", "neg_keep_rate", *cols])
    paths = ", ".join(
        f"'{(matrix_dir / target / f'origin_month={m:%Y-%m-%d}' / '*.parquet').as_posix()}'"
        for m in origins
    )
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    df = con.execute(
        f"SELECT {select} FROM read_parquet([{paths}], union_by_name=true, "
        "hive_partitioning=true)"
    ).df()
    con.close()
    return cast_features(df)


ID_COLS = ("CompanyNumber", "CompanyName", "origin_month")


def cast_features(
    df: pd.DataFrame,
    categorical: list[str] | None = None,
    skip: tuple[str, ...] = ID_COLS,
) -> pd.DataFrame:
    """Numeric features to float32, categoricals to pandas ``category``.

    Driven off ``targets.CATEGORICAL_COLS``, so a lender-group column added there
    is handled here without touching this function. float32 halves the footprint
    and preserves NaN, which matters: a NULL delta around the June 2025 hole means
    "cannot say" and LightGBM handles that natively.
    """
    cats = categorical if categorical is not None else targets.CATEGORICAL_COLS
    for col in df.columns:
        if col in skip:
            continue
        if col in cats:
            df[col] = df[col].astype("category")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    return df


def align_categories(frames: list[pd.DataFrame], categorical: list[str] | None = None) -> None:
    """Give every frame the same category levels, in place.

    Without this a level that appears only in test becomes NaN, or worse, two
    frames encode the same string to different integer codes and the model reads
    "Manufacturing" as "Tech".
    """
    cats = categorical if categorical is not None else targets.CATEGORICAL_COLS
    for col in cats:
        present = [f for f in frames if col in f.columns]
        if not present:
            continue
        levels = pd.Index(sorted(set().union(*(set(f[col].dropna().unique()) for f in present))))
        for f in present:
            f[col] = pd.Categorical(f[col], categories=levels)


def apply_categories(
    df: pd.DataFrame,
    reference: pd.DataFrame,
    categorical: list[str] | None = None,
) -> pd.DataFrame:
    """Force ``df``'s categoricals onto ``reference``'s exact levels, in place.

    LightGBM does carry its training category lists on the booster and re-applies
    them at predict time, so this is belt and braces for the boosted models. It is
    not optional for anything else, and a silent code mismatch (the model reading
    "Manufacturing" where the row says "Tech") is the kind of bug that produces a
    plausible-looking ranked list and no error at all.
    """
    cats = categorical if categorical is not None else targets.CATEGORICAL_COLS
    for col in cats:
        if col in df.columns and col in reference.columns:
            df[col] = pd.Categorical(df[col], categories=reference[col].cat.categories)
    return df


def feature_frame(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """The X matrix: ``targets.FEATURE_COLS`` and nothing else."""
    return df[columns or targets.FEATURE_COLS]


# --------------------------------------------------------------------------- #
# The unsampled evaluation population
# --------------------------------------------------------------------------- #

def build_eval_matrix(
    target: str,
    origins: list[pd.Timestamp],
    contracts_dir: Path = contracts.ASOF_DIR,
    out_dir: Path = EVAL_MATRIX_DIR,
    **kwargs,
) -> pd.DataFrame:
    """Rebuild the given origins with **no** negative downsampling.

    ``targets.build_matrix`` caps the keep rate at 1.0, so a large enough
    ``neg_ratio`` simply keeps everything. This is the population the model would
    really be ranking, and it is the only place precision@N means what it says.
    """
    return targets.build_matrix(
        target,
        contracts_dir=contracts_dir,
        out_dir=out_dir,
        neg_ratio=10**9,
        origins=origins,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

def fit_lightgbm(
    X: pd.DataFrame,
    y: np.ndarray,
    groups: np.ndarray,
    params: dict | None = None,
    random_state: int = RANDOM_STATE,
) -> lgb.LGBMClassifier:
    """LightGBM with early stopping on a company-grouped slice of the training rows.

    Grouped, not random: a company contributes several origin rows, and letting the
    same company sit on both sides of the validation boundary makes early stopping
    stop late.
    """
    gss = GroupShuffleSplit(n_splits=1, test_size=VALID_FRACTION, random_state=random_state)
    tr, va = next(gss.split(X, y, groups))
    model = lgb.LGBMClassifier(random_state=random_state, **(params or LGB_PARAMS))
    model.fit(
        X.iloc[tr], y[tr],
        eval_set=[(X.iloc[va], y[va])],
        eval_metric="auc",
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    return model


def fit_logistic(
    X: pd.DataFrame,
    y: np.ndarray,
    categorical: list[str] | None = None,
    max_rows: int = LOGIT_MAX_ROWS,
    random_state: int = RANDOM_STATE,
) -> Pipeline:
    """Regularised logistic regression as an interpretable floor.

    Worth the twenty minutes for two reasons. It is a floor: if LightGBM cannot
    clearly beat a linear model on the same features, the boosting is not earning
    its complexity and I should say so. And its signed coefficients are an
    independent check on the SHAP directions, so if SHAP says more charges means
    more distress and the coefficient says the opposite, one of them is wrong.

    Unlike LightGBM this cannot eat NaN or raw strings, hence the impute / scale /
    one-hot pipeline. Missingness is flagged rather than silently filled, because a
    NULL delta at the June 2025 hole is information.
    """
    cats = categorical if categorical is not None else targets.CATEGORICAL_COLS
    cats = [c for c in cats if c in X.columns]
    nums = [c for c in X.columns if c not in cats]

    if len(X) > max_rows:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(len(X), max_rows, replace=False)
        X, y = X.iloc[idx], y[idx]

    pre = ColumnTransformer([
        ("num", Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
        ]), nums),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=0.001), cats),
    ])
    pipe = Pipeline([
        ("pre", pre),
        ("clf", LogisticRegression(max_iter=1000, C=1.0, random_state=random_state)),
    ])
    pipe.fit(X, y)
    return pipe


# --------------------------------------------------------------------------- #
# Calibration and metrics
# --------------------------------------------------------------------------- #

def recalibrate(p: np.ndarray, neg_keep_rate: np.ndarray | float) -> np.ndarray:
    """Undo negative downsampling on predicted probabilities.

    Keeping every positive and a fraction ``r`` of negatives multiplies the odds by
    ``1/r``, so the correction is ``odds_true = odds_sampled * r``. Ranking is
    untouched (it is a monotone transform); the numbers become true again, which is
    what any threshold or stated probability depends on.
    """
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    odds = p / (1 - p) * np.asarray(neg_keep_rate, dtype=float)
    return odds / (1 + odds)


def precision_at_n(y: np.ndarray, p: np.ndarray, n: int) -> float:
    """Share of the top ``n`` ranked companies that were actually positives.

    Absolute N rather than a percentage, because a relationship manager works a
    finite call list. "Of our top 500 picks, how many were right" is the question;
    AUC over 1.4M companies is not an answer to it.
    """
    if n > len(y):
        return float("nan")
    top = np.argpartition(-p, n - 1)[:n]
    return float(np.mean(y[top]))


def evaluate(y: np.ndarray, p: np.ndarray, top_n=TOP_N) -> dict:
    """ROC-AUC, PR-AUC, lift and precision@N, with the base rate alongside.

    The base rate belongs next to them: PR-AUC and precision@N are only readable
    against it, and lift (precision@N over base rate) is the number that says
    whether the call list beats calling at random.
    """
    y = np.asarray(y)
    base = float(np.mean(y))
    out = {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "base_rate": base,
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
    }
    for n in top_n:
        prec = precision_at_n(y, p, n)
        out[f"precision_at_{n}"] = prec
        out[f"lift_at_{n}"] = prec / base if base else float("nan")
    return out


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #

def run_target(
    target: str,
    matrix_dir: Path = targets.MATRIX_DIR,
    eval_dir: Path = EVAL_MATRIX_DIR,
    columns: list[str] | None = None,
    n_test: int = N_TEST_ORIGINS,
    fit_floor: bool = True,
) -> dict:
    """Train, evaluate out-of-time, and return everything worth recording.

    Returns the models and the held-out frames alongside the metrics, so the
    notebook can run SHAP without paying to load anything twice.
    """
    cols = columns or targets.FEATURE_COLS
    split = split_origins(target, matrix_dir, n_test=n_test)

    train = load_origins(target, split.train, matrix_dir, cols)
    test = load_origins(target, split.test, eval_dir, cols)  # unsampled
    align_categories([train, test], [c for c in targets.CATEGORICAL_COLS if c in cols])

    X_tr, y_tr = feature_frame(train, cols), train["y"].to_numpy()
    X_te, y_te = feature_frame(test, cols), test["y"].to_numpy()

    models, metrics = {}, {}
    gbm = fit_lightgbm(X_tr, y_tr, train["CompanyNumber"].to_numpy())
    models["lightgbm"] = gbm
    p_raw = gbm.predict_proba(X_te)[:, 1]
    metrics["lightgbm"] = evaluate(y_te, p_raw)

    if fit_floor:
        logit = fit_logistic(X_tr, y_tr, [c for c in targets.CATEGORICAL_COLS if c in cols])
        models["logistic"] = logit
        metrics["logistic"] = evaluate(y_te, logit.predict_proba(X_te)[:, 1])

    # Calibration is checked on the *sampled* test rows, because those are the ones
    # carrying a neg_keep_rate. The eval population is already unsampled, so its
    # mean prediction should match its base rate once the correction is applied to
    # the training-time sampling rate.
    keep = float(train["neg_keep_rate"].mean())
    calibration = {
        "train_neg_keep_rate": keep,
        "mean_pred_raw": float(p_raw.mean()),
        "mean_pred_recalibrated": float(recalibrate(p_raw, keep).mean()),
        "test_base_rate": float(y_te.mean()),
    }

    return {
        "target": target,
        "horizon_m": split.horizon_m,
        "n_features": len(cols),
        "split": split.to_dict(),
        "train_rows": int(len(train)),
        "train_positives": int(y_tr.sum()),
        "best_iteration": int(getattr(gbm, "best_iteration_", 0) or 0),
        "metrics": metrics,
        "calibration": calibration,
        "_models": models,
        "_X_test": X_te,
        "_y_test": y_te,
        "_p_test": p_raw,
        "_test_keys": test[["CompanyNumber", "origin_month"]],
    }


def grouped_cv_auc(
    target: str,
    matrix_dir: Path = targets.MATRIX_DIR,
    columns: list[str] | None = None,
    n_splits: int = 3,
    max_rows: int = 2_000_000,
    random_state: int = RANDOM_STATE,
) -> dict:
    """Secondary check: GroupKFold by CompanyNumber across all origins.

    This ignores time on purpose. Compared against the out-of-time number it tells
    you *which* kind of overfitting you have: if grouped CV is much the better of
    the two, the model has learned something about this particular period that will
    not survive into the next one. If they agree, it generalises.

    Row-capped because the point is a comparison, not a better estimate, and the
    voluntary-exit matrix is twelve million rows.
    """
    cols = columns or targets.FEATURE_COLS
    df = load_origins(target, matrix_origins(target, matrix_dir), matrix_dir, cols)
    if len(df) > max_rows:
        df = df.sample(max_rows, random_state=random_state).reset_index(drop=True)
    align_categories([df], [c for c in targets.CATEGORICAL_COLS if c in cols])

    X, y = feature_frame(df, cols), df["y"].to_numpy()
    groups = df["CompanyNumber"].to_numpy()
    aucs = []
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y, groups):
        m = fit_lightgbm(X.iloc[tr], y[tr], groups[tr])
        aucs.append(float(roc_auc_score(y[te], m.predict_proba(X.iloc[te])[:, 1])))
    return {"target": target, "n_splits": n_splits, "rows": int(len(df)),
            "fold_roc_auc": aucs, "mean_roc_auc": float(np.mean(aucs))}


# --------------------------------------------------------------------------- #
# SHAP
# --------------------------------------------------------------------------- #

def shap_sample(
    X: pd.DataFrame,
    y: np.ndarray,
    n: int = SHAP_SAMPLE,
    random_state: int = RANDOM_STATE,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Stratified subsample for TreeExplainer.

    Stratified because these labels are rare: a plain 100k draw from a 0.3% base
    rate holds ~300 positives, and the summary plot would be describing the
    negatives almost exclusively.
    """
    if len(X) <= n:
        return X, y
    rng = np.random.default_rng(random_state)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    n_pos = min(len(pos), n // 2)
    n_neg = min(len(neg), n - n_pos)
    idx = np.sort(np.concatenate([
        rng.choice(pos, n_pos, replace=False),
        rng.choice(neg, n_neg, replace=False),
    ]))
    return X.iloc[idx], y[idx]


def shap_importance(shap_values: np.ndarray, X: pd.DataFrame) -> pd.DataFrame:
    """Mean |SHAP| per feature, with the mean signed value for direction."""
    return (
        pd.DataFrame({
            "feature": X.columns,
            "mean_abs_shap": np.abs(shap_values).mean(axis=0),
            "mean_shap": shap_values.mean(axis=0),
        })
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------- #
# Scoring the live month
# --------------------------------------------------------------------------- #

SCORE_SQL = """
SELECT f."CompanyNumber", f."CompanyName", f.snapshot_date AS origin_month,
       {feature_select}
FROM read_parquet('{delta_glob}') f
LEFT JOIN read_parquet('{contracts_glob}') c
  ON c."CompanyNumber" = f."CompanyNumber" AND c.snapshot_date = f.snapshot_date
WHERE f.snapshot_date = DATE '{month}' AND f.is_active
"""


def load_scoring_frame(
    month: str = panel.LAST_MONTH,
    delta_dir: Path = panel.DELTA_DIR,
    contracts_dir: Path = contracts.ASOF_DIR,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Features for every active company in the latest month, with no label.

    The label table stops where a forward window would run off the register, so the
    live month is not in it and this reads the panel directly. It reuses
    ``targets._feature_select`` so the column set and the contract coalescing are
    literally the same code the training matrix used.

    Note the contract features here are past
    ``contracts.harvest_watermark()``: fine to score on, not fine to train on.
    """
    sql = SCORE_SQL.format(
        month=pd.Timestamp(month).date(),
        feature_select=targets._feature_select(),
        delta_glob=(delta_dir / "**" / "*.parquet").as_posix(),
        contracts_glob=(contracts_dir / "**" / "*.parquet").as_posix(),
    )
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    df = con.execute(sql).df()
    con.close()
    return cast_features(df)


def score_frame(model, df: pd.DataFrame, neg_keep_rate: float, columns: list[str] | None = None) -> pd.Series:
    """Recalibrated probability per row, ready to rank."""
    cols = columns or targets.FEATURE_COLS
    return pd.Series(
        recalibrate(model.predict_proba(df[cols])[:, 1], neg_keep_rate),
        index=df.index,
    )


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

def save_results(
    results: list[dict],
    path: Path = RESULTS_PATH,
    tag: str = "baseline",
    **extra,
) -> Path:
    """Write the metrics to JSON so the lender-feature re-run is a diff, not a memory.

    Private keys (models, held-out frames) are stripped. The whole reason for
    training before the Charges API harvest finishes is to have this file to compare
    against; without it the harvest is an act of faith.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if path.exists():
        payload = json.loads(path.read_text())
    payload[tag] = {
        "feature_cols": list(targets.FEATURE_COLS),
        "categorical_cols": list(targets.CATEGORICAL_COLS),
        "lgb_params": dict(LGB_PARAMS),
        "targets": {
            r["target"]: {k: v for k, v in r.items() if not k.startswith("_")}
            for r in results
        },
        **extra,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path
