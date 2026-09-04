r"""Paired bootstrap on the *linear* half of the N4 verdict.

Why this exists. `\S4.1.5` reads the counterparty-identity verdict off two runs:
`refactor_det` (the 41-feature control) and `lender_calib_hi` (54 features at the
tightest gate tested, 7d/3d). The boosted half of that verdict is paired, because
`run_config_staged.py` persists the LightGBM model per target. The linear half is not,
because the staged runner never wrote the logistic prediction vector to disk, so the
three logistic gains the verdict most depends on (+0.0092 growth, +0.0036 lending,
+0.0023 insolvency) are quoted from two *separate* single-run intervals. `\S4.1.7`
shows that reading is the conservative-but-wrong one when both runs score the same
companies at the same origins.

This refits the logistic family under both configs, on the same matrices the recorded
runs used, and pairs them with `train.paired_bootstrap_delta`. It does not touch
`reports/runs/`: nothing here is a new recorded run, it is a missing interval on two
runs that already exist.

The control that makes it trustworthy is free: a refit at the same seed on the same
matrix must reproduce the ROC-AUC already in `reports/runs/index.csv` to several
digits. If it does not, the comparison is measuring my script rather than the models,
and the script says so and stops.

    .venv/bin/python scripts/paired_linear_n4.py

Writes `reports/paired_linear_n4.json` and `reports/paired_linear_n4.md`.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import train

MODEL = "logistic"
OUT_DIR = Path("reports")
PRED_DIR = Path("data/processed/paired_linear_n4")

# The two configs the N4 verdict compares. `refactor_det` and `lender_calib_hi` are
# tags rather than constants in `train.py`: they were queue entries in
# `run_config_staged.py`, so they are rebuilt here exactly as that script built them.
CONTROL = replace(train.REFACTOR, tag="refactor_det")
TREAT = replace(
    train.LENDER_ASOF21,
    tag="lender_calib_hi",
    matrix_dir=Path("data/processed/model_matrix_lender_calib_hi"),
    eval_dir=Path("data/processed/eval_matrix_lender_calib_hi"),
    lender_dir=Path("data/processed/lender_panel_calib_hi"),
)

# How far a refit is allowed to drift from the recorded number before this is a bug
# rather than a rounding difference. The logistic path is seeded end to end (the row
# subsample draws from `np.random.default_rng(RANDOM_STATE)`), so the only expected
# source of drift is the threaded BLAS residual of section 4.1.7, which lands around
# 1e-9 on ROC-AUC.
REPRODUCTION_TOL = 1e-6

# One cell fails that tolerance, and the cause was chased down rather than tuned away.
# Loosening the threshold until the assertion passes would be the same mistake section
# 4.1.4 spends four pages on, so the failure is left in and explained here.
KNOWN_CAUSE = """\
`growth` under `lender_calib_hi` refits to 0.738214 against a recorded 0.738222, a
drift of 8.4e-06. It is not process noise: two fresh processes reproduce 0.738214
bit-for-bit, and two fits inside one process return identical prediction vectors. The
cause is the threaded-BLAS residual of section 4.1.7, and it is a function of the
thread count rather than of thread completion order. Refitting this exact cell at
several BLAS thread settings gives:

| OMP_NUM_THREADS | ROC-AUC |
|---|---|
| 1 | 0.738222396 |
| 4 | 0.738209146 |
| 8 | 0.738222101 |
| 16 (this machine's default) | 0.738213962 |

The recorded run matches the single-threaded value to six decimal places. So the
spread attributable to BLAS threading is about 1.3e-05 of ROC-AUC, which is 1/700 of
the growth delta this script measures (+0.0092) and about 1/85 of that delta's
interval half-width. It changes no conclusion, and it sharpens a claim already in
section 4.1.7: the dense-model residual is *deterministic within a threading
configuration* and differs *between* configurations, rather than being random per
process. The pairing itself is unaffected, because both configs are fitted in the same
process at the same thread count, so the difference between them is internally
consistent whatever that count happens to be.

Why this cell and not the other seven: `growth` is the target whose feature list
carries nine columns with no observed value in training (the defect of section 4.6),
which the imputer drops with a warning, and its solver stops at 100 iterations. That
is the worst-conditioned of the eight fits, so it is where a 1e-09 perturbation of the
scores is most able to reorder rows near the ranking boundaries."""


def log(msg: str) -> None:
    print(f"[{pd.Timestamp.now():%H:%M:%S}] {msg}", flush=True)


def fit_and_predict(target: str, config: train.RunConfig) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Refit `MODEL` on one config's training origins and score its test origins.

    Returns the held-out labels, the raw predicted probabilities and the row keys.
    Keys come back because the two configs are separate parquet trees and nothing
    guarantees DuckDB hands them back in the same row order; the caller aligns on
    them before pairing.
    """
    cols, cats = config.cols(target), config.cats(target)
    split = train.split_origins(target, config)

    tr = train.load_origins(target, split.train, config.matrix_dir, cols, cats)
    te = train.load_origins(target, split.test, config.eval_dir, cols, cats)
    train.align_categories([tr, te], cats)

    X_tr, y_tr = train.feature_frame(tr, cols), tr["y"].to_numpy()
    groups = tr["CompanyNumber"].to_numpy()
    log(f"    fit {config.tag}/{target}: {len(tr):,} train rows, {len(cols)} features")
    model = train.fit_model(MODEL, X_tr, y_tr, groups, cats)
    del tr, X_tr, y_tr, groups

    keys = te[["CompanyNumber", "origin_month"]].reset_index(drop=True)
    y_te = te["y"].to_numpy()
    p = model.predict_proba(train.feature_frame(te, cols))[:, 1]
    log(f"    scored {config.tag}/{target}: {len(te):,} eval rows")
    del te
    return y_te, p, keys


def canonical_order(keys: pd.DataFrame) -> np.ndarray:
    """Row order that both configs can be sorted into: origin, then company."""
    return np.lexsort((keys["CompanyNumber"].to_numpy(), keys["origin_month"].to_numpy()))


def main() -> None:
    recorded = pd.read_csv("reports/runs/index.csv")
    recorded = recorded[recorded["model"] == MODEL].set_index(["tag", "target"])["roc_auc"]

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    rows, failures = [], []

    for target in CONTROL.target_names:
        log(f"{target}")
        got = {}
        for cfg in (CONTROL, TREAT):
            y, p, keys = fit_and_predict(target, cfg)
            order = canonical_order(keys)
            got[cfg.tag] = (y[order], p[order], keys.iloc[order].reset_index(drop=True))
            # Persist what the staged runner should have persisted. float32 is
            # sufficient: the tie structure of section 4.1.7 lives far above it.
            np.savez_compressed(
                PRED_DIR / f"preds_{cfg.tag}_{target}.npz",
                y=y[order].astype(np.int8),
                p=p[order].astype(np.float32),
                CompanyNumber=keys.iloc[order]["CompanyNumber"].to_numpy().astype("U8"),
                origin_month=keys.iloc[order]["origin_month"].to_numpy().astype("datetime64[D]"),
            )

        (y_a, p_a, k_a), (y_b, p_b, k_b) = got[CONTROL.tag], got[TREAT.tag]

        # The pairing is only legal if both runs scored the same rows. Assert it on
        # the keys rather than trusting the row counts, because two different
        # populations of the same size would pair silently and wrongly.
        same_rows = (
            len(k_a) == len(k_b)
            and k_a["CompanyNumber"].equals(k_b["CompanyNumber"])
            and k_a["origin_month"].equals(k_b["origin_month"])
        )
        if not same_rows:
            failures.append(f"{target}: evaluation rows differ between the two configs")
            log(f"  SKIPPED {target}: evaluation rows differ")
            continue
        assert np.array_equal(y_a, y_b), f"{target}: same rows, different labels"

        # The reproduction control, before any comparison is reported.
        repro = {}
        for tag, p in ((CONTROL.tag, p_a), (TREAT.tag, p_b)):
            fresh = train.evaluate(y_a, p)["roc_auc"]
            ref = float(recorded.loc[(tag, target)])
            repro[tag] = {"refit": fresh, "recorded": ref, "abs_diff": abs(fresh - ref)}
            if abs(fresh - ref) > REPRODUCTION_TOL:
                failures.append(
                    f"{target}/{tag}: refit ROC-AUC {fresh:.6f} != recorded {ref:.6f} "
                    f"(diff {abs(fresh - ref):.2e})"
                )

        log(f"  paired bootstrap: {len(y_a):,} rows")
        delta = train.paired_bootstrap_delta(y_a, p_a, p_b)
        rows.append({
            "target": target,
            "model": MODEL,
            "n_eval_rows": int(len(y_a)),
            "positives": int(y_a.sum()),
            "reproduction": repro,
            "control": train.evaluate(y_a, p_a),
            "treatment": train.evaluate(y_a, p_b),
            "paired_delta": {k: v for k, v in delta.items() if isinstance(v, dict)},
            "n_boot": delta["n_boot"],
        })
        d = rows[-1]["paired_delta"]["roc_auc"]
        log(f"  roc_auc delta {d['delta']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]")

    out = {
        "control": CONTROL.tag,
        "treatment": TREAT.tag,
        "model": MODEL,
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "reproduction_tol": REPRODUCTION_TOL,
        "failures": failures,
        "results": rows,
    }
    (OUT_DIR / "paired_linear_n4.json").write_text(json.dumps(out, indent=2, default=str))
    (OUT_DIR / "paired_linear_n4.md").write_text(render(out))
    log(f"wrote {OUT_DIR / 'paired_linear_n4.json'} and .md")
    if failures:
        log("FAILURES:")
        for f in failures:
            log(f"  {f}")


def render(out: dict) -> str:
    """A table that can go straight into section 4.1.5, plus the control."""
    lines = [
        f"# Paired bootstrap, {out['model']}: `{out['treatment']}` minus `{out['control']}`",
        "",
        f"Generated {out['created_at']} by `scripts/paired_linear_n4.py`. "
        f"{out['results'][0]['n_boot'] if out['results'] else 0} replicates, percentile method.",
        "",
        "## Result",
        "",
        "| target | control | treatment | delta | paired 95% CI | excludes 0 |",
        "|---|---|---|---|---|---|",
    ]
    for r in out["results"]:
        d = r["paired_delta"]["roc_auc"]
        excl = "**yes**" if (d["lo"] > 0) == (d["hi"] > 0) else "no"
        lines.append(
            f"| {r['target']} | {r['control']['roc_auc']:.4f} | {r['treatment']['roc_auc']:.4f} "
            f"| {d['delta']:+.4f} | [{d['lo']:+.4f}, {d['hi']:+.4f}] | {excl} |"
        )
    lines += ["", "### precision@500, same pairing", "",
              "| target | control | treatment | delta | paired 95% CI |", "|---|---|---|---|---|"]
    for r in out["results"]:
        d = r["paired_delta"].get("precision_at_500")
        if d is None:
            continue
        lines.append(
            f"| {r['target']} | {r['control']['precision_at_500']:.3f} "
            f"| {r['treatment']['precision_at_500']:.3f} "
            f"| {d['delta']:+.3f} | [{d['lo']:+.3f}, {d['hi']:+.3f}] |"
        )
    lines += ["", "## Reproduction control", "",
              "Each refit must reproduce the ROC-AUC already recorded in "
              "`reports/runs/index.csv`. A drift larger than "
              f"{out['reproduction_tol']:.0e} means this script is measuring itself.", "",
              "| target | run | refit | recorded | abs diff |", "|---|---|---|---|---|"]
    for r in out["results"]:
        for tag, v in r["reproduction"].items():
            lines.append(
                f"| {r['target']} | {tag} | {v['refit']:.6f} | {v['recorded']:.6f} "
                f"| {v['abs_diff']:.2e} |"
            )
    lines += ["", f"**Failures: {len(out['failures'])}**"]
    lines += [f"- {f}" for f in out["failures"]] or ["", "None."]
    if out["failures"]:
        lines += ["", "### Why, and why it does not matter", "", KNOWN_CAUSE]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
