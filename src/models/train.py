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

**Refactored 27 Jul 2026 after the supervisor call.** Fernando asked for a reusable
scikit-learn pipeline where adding a model type is one line, where hyperparameters get
validated when a model has them, and where the dissertation can argue the
interpretability/accuracy trade-off between a simple model and a complex one. What
changed here, and nothing else did:

- ``MODELS`` is a registry of ``ModelSpec``. ``run_target`` loops over it instead of
  naming ``fit_lightgbm`` and ``fit_logistic``, which no longer exist. Adding a model
  family is one dict entry.
- ``dense_preprocessor`` was lifted out of the old ``fit_logistic`` so every non-tree
  model shares identical preprocessing. Otherwise a model comparison is confounded by
  how the features were prepared rather than by the model.
- ``mlp`` (``MLPClassifier``) joins the registry as the complex end of that trade-off.
- ``tune_model`` and ``OriginEmbargoSplit`` do hyperparameter validation *in time*.
  A default ``KFold`` inside a search would reintroduce exactly the two leaks the
  primary split exists to prevent.
- ``explain`` dispatches to the right SHAP explainer per family, which is where the
  cost of explaining a complex model becomes visible and measurable.

The split, the unsampled evaluation population and the recalibration are byte-for-byte
the same, so the ``baseline`` tag already in ``reports/step6/model_results.json``
stays a valid reference to compare against.

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

# Everything step 6 emits lives together under one directory. It is a set of
# artefacts that only mean anything as a set (the metrics reference the feature
# list, the SHAP tables reference the models the metrics describe), and they will
# be joined by a second run's worth once the lender features land.
STEP6_DIR = Path("reports/step6")
RESULTS_PATH = STEP6_DIR / "model_results.json"


def shap_importance_path(target: str, tag: str = "baseline", dir: Path = STEP6_DIR) -> Path:
    """Where one target's SHAP importance table goes."""
    return dir / f"shap_importance_{tag}_{target}.csv"

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

# The neural network is a comparison model, and backprop over a dense one-hot matrix
# is the slowest thing in this module by a wide margin. Capped harder than the
# logistic floor for the same reason: the number we want from it is a fair
# out-of-time comparison, not the best MLP obtainable.
MLP_MAX_ROWS = 300_000

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
# Models: the registry
# --------------------------------------------------------------------------- #
#
# ### WHY THIS IS A REGISTRY AND NOT TWO FUNCTIONS (refactor, 27 Jul 2026)
#
# Until today this module had two hard-coded functions, `fit_lightgbm` and
# `fit_logistic`, called by name inside `run_target`. Everything about that was
# statistically correct, but adding a third model meant editing `run_target`, and
# the impute/scale/one-hot preprocessing lived *inside* `fit_logistic` where nothing
# else could reach it.
#
# Fernando (supervisor call, 27 Jul 2026) asked for three things:
#
#   1. a reusable scikit-learn pipeline for training;
#   2. adding a new model type should be effectively **one line of code**, so the
#      comparison across model families is cheap;
#   3. where a model has hyperparameters, validate them properly.
#
# `MODELS` below is (1) and (2): every entry is a `ModelSpec` whose `build` returns
# a fully-formed scikit-learn estimator, preprocessing included, and `run_target`
# loops over the registry instead of naming models. Adding an SVM, a random forest
# or a second neural net is literally one dict entry. `tune_model` is (3).
#
# Nothing about the split, the evaluation population or the recalibration changed,
# so the `baseline` numbers already in `reports/step6/model_results.json` remain
# valid and comparable. That was the constraint on the refactor: it had to be a
# reorganisation, not a re-specification.
#
# The one genuine design tension: LightGBM consumes `pandas.Categorical` and NaN
# natively, and every scikit-learn estimator does not. So the registry cannot be a
# flat `{name: Estimator()}` map. Each spec declares whether its model needs the
# dense preprocessing, and `dense_preprocessor` is shared by everything that does.


def dense_preprocessor(
    columns: list[str],
    categorical: list[str] | None = None,
) -> ColumnTransformer:
    """Impute, scale and one-hot: what every non-tree model here needs.

    Pulled out of the old `fit_logistic` so the neural network uses the *same*
    preprocessing as the linear floor. If the two models saw differently prepared
    features, the trade-off comparison Fernando wants in the dissertation (simple
    and interpretable versus complex and accurate) would be confounded by the
    preprocessing rather than the model family.

    Missingness is flagged (`add_indicator=True`) rather than silently filled,
    because a NULL delta around the June 2025 panel hole means "cannot say" and
    that is information. Trees get to express that natively; dense models need the
    indicator column to say it at all.
    """
    cats = [c for c in (categorical if categorical is not None else targets.CATEGORICAL_COLS)
            if c in columns]
    nums = [c for c in columns if c not in cats]
    return ColumnTransformer([
        ("num", Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
        ]), nums),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=0.001), cats),
    ])


def _build_lightgbm(columns, categorical, params, random_state):
    """Gradient boosting: the real model. No preprocessing, it eats the frame as-is."""
    return lgb.LGBMClassifier(random_state=random_state, **{**LGB_PARAMS, **params})


def _build_logistic(columns, categorical, params, random_state):
    """Regularised logistic regression: the interpretable floor.

    Two jobs, neither of which is winning. It is a floor: if LightGBM cannot clearly
    beat a linear model on the same features then the boosting is not earning its
    complexity. And its signed coefficients are an independent check on the SHAP
    directions, which is the check `notebooks/16_shap_models.ipynb` runs.
    """
    return Pipeline([
        ("pre", dense_preprocessor(columns, categorical)),
        ("clf", LogisticRegression(**{
            "max_iter": 1000, "C": 1.0, "random_state": random_state, **params})),
    ])


def _build_mlp(columns, categorical, params, random_state):
    """A small feed-forward neural network: the complex end of the trade-off.

    Added for Fernando's point (3): the dissertation argument is about the
    interpretability/accuracy trade-off, and that argument needs a model at the
    complex end that is *not* a tree. LightGBM occupies an awkward middle, because
    `TreeExplainer` gives it exact SHAP values cheaply; an MLP has no such shortcut,
    which is precisely what makes it the honest illustration of why post-hoc
    explanation exists at all.

    `MLPClassifier` rather than torch/keras deliberately. It is in scikit-learn, so
    it drops into the same `Pipeline` and the same `predict_proba` contract as
    everything else and costs no new dependency. For ~60 tabular features on a few
    hundred thousand rows it is also the right size of tool; a deeper network would
    be a claim about the data we have no evidence for.

    **Known limitation, stated rather than hidden.** `early_stopping=True` carves
    its validation slice at *random*, not grouped by company, so a company can sit
    on both sides of it and stopping may run slightly late. It affects only when
    training halts, never the out-of-time evaluation, which is still built from
    held-out later origins. scikit-learn does not expose a custom validation set on
    `MLPClassifier`; taking one would mean writing our own training loop, which is
    not worth it for a comparison model.
    """
    from sklearn.neural_network import MLPClassifier

    return Pipeline([
        ("pre", dense_preprocessor(columns, categorical)),
        ("clf", MLPClassifier(**{
            "hidden_layer_sizes": (64, 32),
            "alpha": 1e-4,
            "batch_size": 1024,
            "learning_rate_init": 1e-3,
            "max_iter": 60,
            "early_stopping": True,
            "n_iter_no_change": 5,
            "random_state": random_state,
            **params,
        })),
    ])


@dataclass(frozen=True)
class ModelSpec:
    """One entry in the registry: how to build a model and how to handle it.

    Everything `run_target` needs to know about a model family lives here, which is
    what keeps `run_target` free of `if name == "lightgbm"` branches.
    """

    name: str
    build: object                      # (columns, categorical, params, random_state) -> estimator
    params: dict = field(default_factory=dict)
    # Row cap for training. Dense models on several million rows cost minutes for no
    # extra information; LightGBM is happy with everything and caps at None.
    max_rows: int | None = None
    # LightGBM only: hold out a company-grouped slice of the training rows and stop
    # boosting on it. Never the test set, which would be tuning on the exam.
    early_stopping: bool = False
    # Which SHAP explainer applies. "tree" is exact and fast; "kernel" is a sampled
    # approximation and is why SHAP on a neural network costs what it costs.
    explainer: str = "kernel"
    # Grid for `tune_model`. None means "nothing worth validating", which is the
    # honest answer for a fixed-parameter baseline.
    search_space: dict | None = None


MODELS: dict[str, ModelSpec] = {
    "lightgbm": ModelSpec(
        "lightgbm", _build_lightgbm, early_stopping=True, explainer="tree",
        search_space={"num_leaves": [31, 63, 127], "learning_rate": [0.03, 0.05, 0.1],
                      "min_child_samples": [100, 200, 500]},
    ),
    "logistic": ModelSpec(
        "logistic", _build_logistic, max_rows=LOGIT_MAX_ROWS, explainer="linear",
        search_space={"clf__C": [0.01, 0.1, 1.0, 10.0]},
    ),
    "mlp": ModelSpec(
        "mlp", _build_mlp, max_rows=MLP_MAX_ROWS, explainer="kernel",
        search_space={"clf__hidden_layer_sizes": [(32,), (64, 32), (128, 64)],
                      "clf__alpha": [1e-5, 1e-4, 1e-3]},
    ),
}

# Which models `run_target` fits when not told otherwise. Every registered model, so
# that adding a dict entry above really is the whole change.
DEFAULT_MODELS = tuple(MODELS)


def build_model(
    name: str,
    columns: list[str] | None = None,
    categorical: list[str] | None = None,
    params: dict | None = None,
    random_state: int = RANDOM_STATE,
):
    """An unfitted estimator from the registry. The one entry point for model choice."""
    spec = MODELS[name]
    cols = columns or targets.FEATURE_COLS
    cats = categorical if categorical is not None else targets.CATEGORICAL_COLS
    return spec.build(cols, cats, {**spec.params, **(params or {})}, random_state)


def fit_model(
    name: str,
    X: pd.DataFrame,
    y: np.ndarray,
    groups: np.ndarray | None = None,
    categorical: list[str] | None = None,
    params: dict | None = None,
    random_state: int = RANDOM_STATE,
):
    """Build and fit one registered model. Replaces `fit_lightgbm` / `fit_logistic`.

    The two things that used to be buried inside those functions and are now driven
    off the spec:

    **Row capping.** Dense models get `spec.max_rows` rows, drawn with a fixed seed
    so the subsample is reproducible. The draw is deliberately unchanged from the old
    `fit_logistic` so the logistic numbers still reproduce the `baseline` tag.

    **Grouped early stopping.** LightGBM stops on a slice of the *training* rows held
    out by company, never on the test set. Grouped rather than random because a
    company contributes a row at every origin, and letting it straddle the boundary
    makes early stopping stop late.
    """
    spec = MODELS[name]
    model = build_model(name, list(X.columns), categorical, params, random_state)

    if spec.max_rows is not None and len(X) > spec.max_rows:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(len(X), spec.max_rows, replace=False)
        X, y = X.iloc[idx], y[idx]
        groups = None if groups is None else groups[idx]

    if spec.early_stopping:
        if groups is None:
            raise ValueError(f"{name} needs groups for its company-grouped early stopping")
        gss = GroupShuffleSplit(n_splits=1, test_size=VALID_FRACTION, random_state=random_state)
        tr, va = next(gss.split(X, y, groups))
        model.fit(
            X.iloc[tr], y[tr],
            eval_set=[(X.iloc[va], y[va])],
            eval_metric="auc",
            callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
        )
    else:
        model.fit(X, y)
    return model


# --------------------------------------------------------------------------- #
# Hyperparameter validation
# --------------------------------------------------------------------------- #
#
# Fernando's third point: where a model has hyperparameters, validate them properly.
# The trap is that "properly" here does **not** mean `GridSearchCV(cv=5)`. The
# default `KFold` shuffles time and companies together, which is the same double
# leak `split_origins` exists to avoid; a search validated that way would pick
# parameters that look good only because they memorised companies.
#
# So the search gets its own time-aware splitter, built on the same embargo rule as
# the primary split, and applied *inside the training origins only*. The out-of-time
# test origins are never touched by tuning.


class OriginEmbargoSplit:
    """Expanding-window CV over origin months, with an embargo of ``horizon`` months.

    A scikit-learn compatible splitter: pass the row's origin month as ``groups``.
    Fold *k* trains on every origin at least ``horizon`` months before validation
    origin *k*, and validates on that origin alone. That is the primary split's rule
    applied recursively, so a parameter chosen here was chosen under the same
    constraint it will be judged under.

    ``n_splits`` is a **maximum**, not a promise, and the honest number is often
    smaller. Insolvency has three training origins and a six-month horizon, so only
    one validation origin has anything legal left to train on: exactly one fold. That
    is not a bug in the splitter, it is the real amount of independent evidence a
    33-month panel with quarterly origins can offer for tuning a six-month label.
    Worth saying out loud rather than papering over with a `KFold` that would happily
    invent five folds by leaking.
    """

    def __init__(self, horizon_m: int, n_splits: int = 3):
        self.horizon_m = horizon_m
        self.n_splits = n_splits

    def _folds(self, groups) -> list[tuple[np.ndarray, np.ndarray]]:
        if groups is None:
            raise ValueError("OriginEmbargoSplit needs origin months passed as `groups`")
        months = pd.Series(pd.to_datetime(groups))
        uniq = sorted(months.unique())
        folds = []
        for v in uniq[1:][-self.n_splits:]:
            v = pd.Timestamp(v)
            gap = (v.year - months.dt.year) * 12 + (v.month - months.dt.month)
            tr = np.flatnonzero((gap >= self.horizon_m).to_numpy())
            va = np.flatnonzero((months == v).to_numpy())
            if len(tr) and len(va):
                folds.append((tr, va))
        return folds

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return len(self._folds(groups)) if groups is not None else self.n_splits

    def split(self, X, y=None, groups=None):
        yield from self._folds(groups)


def tune_model(
    name: str,
    target: str,
    matrix_dir: Path = targets.MATRIX_DIR,
    columns: list[str] | None = None,
    n_iter: int = 12,
    max_rows: int = 300_000,
    n_splits: int = 3,
    random_state: int = RANDOM_STATE,
) -> dict:
    """Randomised search over a registered model's ``search_space``, validated in time.

    Uses only the **training** origins of the target's out-of-time split, cross
    validated with `OriginEmbargoSplit`, and scored on ROC-AUC because it is the one
    headline metric that survives the negative downsampling in the training matrix
    (precision@N and PR-AUC do not, which is why they are computed on the rebuilt
    unsampled population instead).

    Returns the best parameters and the search table. Feed the parameters back
    through ``run_target(model_params={name: best})``: the point of separating tuning
    from fitting is that the recorded baseline stays a fixed reference while tuning
    runs are a diff against it.
    """
    from sklearn.model_selection import RandomizedSearchCV

    spec = MODELS[name]
    if not spec.search_space:
        raise ValueError(f"{name} has no search_space; nothing to validate")

    cols = columns or targets.FEATURE_COLS
    split = split_origins(target, matrix_dir)
    df = load_origins(target, split.train, matrix_dir, cols)
    if len(df) > max_rows:
        df = df.sample(max_rows, random_state=random_state).reset_index(drop=True)
    align_categories([df], [c for c in targets.CATEGORICAL_COLS if c in cols])

    X, y = feature_frame(df, cols), df["y"].to_numpy()
    origins = df["origin_month"].to_numpy()
    cv = OriginEmbargoSplit(split.horizon_m, n_splits)
    n_folds = cv.get_n_splits(groups=origins)
    if n_folds == 0:
        raise ValueError(
            f"{target}: no legal validation fold survives a {split.horizon_m}m embargo "
            f"across training origins {[m.strftime('%Y-%m') for m in split.train]}. "
            "Tuning this target needs more origins, not a looser splitter."
        )

    # Early stopping needs an eval_set the search cannot supply, so tuning runs the
    # estimator at its fixed n_estimators. Boosting rounds are themselves one of the
    # things a search over learning_rate is trading against, so this is not a loss.
    est = build_model(name, cols, random_state=random_state)
    search = RandomizedSearchCV(
        est,
        spec.search_space,
        n_iter=n_iter,
        scoring="roc_auc",
        cv=cv,
        random_state=random_state,
        refit=False,
        n_jobs=1,  # the estimators already thread; nesting them is the WSL2 trap again
    )
    search.fit(X, y, groups=origins)
    return {
        "target": target,
        "model": name,
        "n_folds": n_folds,
        "best_params": search.best_params_,
        "best_cv_roc_auc": float(search.best_score_),
        "cv_results": pd.DataFrame(search.cv_results_)[
            ["params", "mean_test_score", "std_test_score", "rank_test_score"]
        ].sort_values("rank_test_score").to_dict("records"),
    }


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
    models: tuple[str, ...] | list[str] = DEFAULT_MODELS,
    model_params: dict[str, dict] | None = None,
) -> dict:
    """Train every requested model on one target, evaluate out-of-time, record it all.

    Returns the fitted models and the held-out frames alongside the metrics, so the
    notebook can run SHAP without paying to load anything twice.

    **Refactored 27 Jul 2026 (Fernando's point 1 and 2).** This used to fit LightGBM
    and, behind a `fit_floor` flag, a logistic regression, both named in the body.
    It now loops over `models`, which defaults to every entry in the `MODELS`
    registry, so comparing a new model family means adding one dict entry and
    nothing here changes. `fit_floor` is gone; pass `models=("lightgbm",)` for the
    same effect.

    Everything downstream of the fit is deliberately untouched: the same out-of-time
    split, the same unsampled evaluation population, the same odds recalibration.
    That is what makes the new numbers directly comparable to the `baseline` tag in
    `reports/step6/model_results.json`.
    """
    cols = columns or targets.FEATURE_COLS
    cats = [c for c in targets.CATEGORICAL_COLS if c in cols]
    params = model_params or {}
    split = split_origins(target, matrix_dir, n_test=n_test)

    train = load_origins(target, split.train, matrix_dir, cols)
    test = load_origins(target, split.test, eval_dir, cols)  # unsampled
    align_categories([train, test], cats)

    X_tr, y_tr = feature_frame(train, cols), train["y"].to_numpy()
    X_te, y_te = feature_frame(test, cols), test["y"].to_numpy()
    groups = train["CompanyNumber"].to_numpy()

    # Downsampling negatives at rate r multiplies the odds by 1/r. Every model in the
    # registry trained on the same sampled matrix, so every model needs the same
    # correction, and the mean recalibrated prediction of each should land on the
    # true base rate of the unsampled test population. Getting the correction the
    # wrong way round would be easy to miss, because the ranking is identical either
    # way; this per-model check is what catches it.
    keep = float(train["neg_keep_rate"].mean())

    fitted, metrics, preds, calibration = {}, {}, {}, {}
    for name in models:
        model = fit_model(name, X_tr, y_tr, groups, cats, params.get(name))
        p_raw = model.predict_proba(X_te)[:, 1]
        fitted[name] = model
        preds[name] = p_raw
        metrics[name] = evaluate(y_te, p_raw)
        calibration[name] = {
            "mean_pred_raw": float(p_raw.mean()),
            "mean_pred_recalibrated": float(recalibrate(p_raw, keep).mean()),
        }

    gbm = fitted.get("lightgbm")
    return {
        "target": target,
        "horizon_m": split.horizon_m,
        "n_features": len(cols),
        "models": list(fitted),
        "split": split.to_dict(),
        "train_rows": int(len(train)),
        "train_positives": int(y_tr.sum()),
        "best_iteration": int(getattr(gbm, "best_iteration_", 0) or 0) if gbm else 0,
        "metrics": metrics,
        "calibration": {
            "train_neg_keep_rate": keep,
            "test_base_rate": float(y_te.mean()),
            "models": calibration,
        },
        "_models": fitted,
        "_X_test": X_te,
        "_y_test": y_te,
        "_p_test": preds,
        "_test_keys": test[["CompanyNumber", "origin_month"]],
    }


def grouped_cv_auc(
    target: str,
    matrix_dir: Path = targets.MATRIX_DIR,
    columns: list[str] | None = None,
    n_splits: int = 3,
    max_rows: int = 2_000_000,
    model: str = "lightgbm",
    random_state: int = RANDOM_STATE,
) -> dict:
    """Secondary check: GroupKFold by CompanyNumber across all origins.

    This ignores time on purpose. Compared against the out-of-time number it tells
    you *which* kind of overfitting you have: if grouped CV is much the better of
    the two, the model has learned something about this particular period that will
    not survive into the next one. If they agree, it generalises.

    Row-capped because the point is a comparison, not a better estimate, and the
    voluntary-exit matrix is twelve million rows.

    ``model`` takes any registry name; it defaults to LightGBM because the check is
    about the *data*, not the estimator, and repeating it per model buys nothing.
    """
    cols = columns or targets.FEATURE_COLS
    cats = [c for c in targets.CATEGORICAL_COLS if c in cols]
    df = load_origins(target, matrix_origins(target, matrix_dir), matrix_dir, cols)
    if len(df) > max_rows:
        df = df.sample(max_rows, random_state=random_state).reset_index(drop=True)
    align_categories([df], cats)

    X, y = feature_frame(df, cols), df["y"].to_numpy()
    groups = df["CompanyNumber"].to_numpy()
    aucs = []
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y, groups):
        m = fit_model(model, X.iloc[tr], y[tr], groups[tr], cats, random_state=random_state)
        aucs.append(float(roc_auc_score(y[te], m.predict_proba(X.iloc[te])[:, 1])))
    return {"target": target, "model": model, "n_splits": n_splits, "rows": int(len(df)),
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


def explain(
    model_name: str,
    model,
    X: pd.DataFrame,
    background: pd.DataFrame | None = None,
    nsamples: int = 200,
) -> np.ndarray:
    """SHAP values for any registered model, using the right explainer for its family.

    **Added 27 Jul 2026, and it is the part of the refactor that carries an argument
    rather than just tidying code.** Fernando's point was that SHAP earns its keep on
    complex models, because a linear model already tells you its directions through
    its coefficients. This function is where that stops being a remark and becomes a
    cost you can measure:

    - ``tree``   : `TreeExplainer`, **exact** and fast. Seconds for 100k rows. This is
                   the LightGBM path and the one the baseline used.
    - ``linear`` : `LinearExplainer`. Available, and almost pointless: for a linear
                   model the SHAP value of feature *j* is just `coef_j * (x_j - E[x_j])`,
                   so it is a rescaling of the coefficient we can already read. We fit
                   the logistic floor to read its coefficients directly, which is what
                   `notebooks/16_shap_models.ipynb` does.
    - ``kernel`` : model-agnostic sampling. This is the MLP path, it is an
                   **approximation**, and it is orders of magnitude slower. Hence the
                   small `nsamples` and the expectation of a few hundred rows, not
                   100k.

    That spread is itself a dissertation result: the interpretability cost of the
    complex model is not only that its parameters mean nothing, it is that recovering
    an explanation afterwards is expensive and approximate.
    """
    import shap

    spec = MODELS[model_name]
    if spec.explainer == "tree":
        sv = shap.TreeExplainer(model).shap_values(X)
        # LightGBM binary returns either a list of two arrays or a 3-d array
        # depending on version; both mean the same thing and we want the positive class.
        if isinstance(sv, list):
            sv = sv[1]
        elif getattr(sv, "ndim", 2) == 3:
            sv = sv[:, :, 1]
        return sv

    # KernelExplainer hands the model a bare numpy array, which loses the column
    # names and the category dtypes the pipeline needs. Rebuild the frame against the
    # original schema on every call. This is part of why the kernel path is slow.
    dtypes = X.dtypes.to_dict()

    def predict(d):
        frame = pd.DataFrame(d, columns=X.columns).astype(dtypes)
        return model.predict_proba(frame)[:, 1]

    bg = shap.sample(background if background is not None else X, 100, random_state=RANDOM_STATE)
    return shap.KernelExplainer(predict, bg).shap_values(X, nsamples=nsamples)


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
        # Which models the registry held at run time, so a later tag that added a
        # model family is self-describing rather than requiring the git history.
        "registry": {
            name: {"explainer": s.explainer, "max_rows": s.max_rows,
                   "early_stopping": s.early_stopping}
            for name, s in MODELS.items()
        },
        "targets": {
            r["target"]: {k: v for k, v in r.items() if not k.startswith("_")}
            for r in results
        },
        **extra,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path
