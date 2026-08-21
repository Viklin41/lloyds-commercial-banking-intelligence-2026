"""The zero-SHAP receipt for counterparty identity, with the check that makes it mean something.

§4.1.5 answers "does knowing who banks with us help?" from the gate ladder against the
deterministic control, which is an argument about metrics. This is the model-internal
version of the same answer, and it is harder to argue with: in `lender_fixed`, which was
handed all 13 lender columns, `is_lbg_client` has a mean|SHAP| of exactly 0.000000 on every
one of the four targets. Exactly zero means LightGBM never took a single split on the
column. The model was given counterparty identity and declined to use it.

Same technique as the growth receipt in `notebooks/18_growth_defect.ipynb`, so it reads as
a method the project already established rather than as a one-off.

**The check that has to come first, and it changes the answer for one of the features.** A
column that is absent, constant, or too rare to split also scores exactly zero, and that
would mean something entirely different. So this counts each feature in the training matrix
and compares it against `min_child_samples`, which is 200. A binary flag with fewer than 200
positives cannot produce a legal leaf, so LightGBM is not declining to use it, it is unable
to. `competitor_entered_12m` fails that test on every target (87 to 1,586 positives) and its
zero is therefore a capacity artefact, not a verdict. `is_lbg_client` and `ever_lbg_client`
pass it comfortably, which is what licenses the claim.

    ./.venv/bin/python scripts/make_shap_identity_receipt.py
"""
import json
from pathlib import Path

import duckdb
import pandas as pd

from src.models import report

TAG = "lender_fixed"
TARGETS = ("lending", "insolvency", "growth", "voluntary_exit")
MATRIX = Path("data/processed/model_matrix_lender_fixed")
IDENTITY = ["is_lbg_client", "ever_lbg_client", "lbg_charge_satisfied_6m",
            "competitor_entered_12m"]


def manifest() -> dict:
    return json.loads(Path(f"reports/runs/{TAG}/manifest.json").read_text())


def support(target: str) -> pd.Series:
    """Non-null count and positive count per identity feature, in the training matrix."""
    glob = (MATRIX / target / "origin_month=*" / "*.parquet").as_posix()
    sel = ", ".join(f'count("{f}") AS "{f}__nn", '
                    f'count(*) FILTER (WHERE "{f}" = 1) AS "{f}__pos"' for f in IDENTITY)
    return duckdb.sql(
        f"SELECT count(*) AS n_rows, {sel} FROM read_parquet('{glob}', union_by_name=true)"
    ).df().iloc[0]


def main() -> None:
    man = manifest()
    min_child = man["lgb_params"]["min_child_samples"]
    present = {f: f in man["feature_cols"] for f in IDENTITY}
    assert all(present.values()), f"not in the recorded feature list: {present}"

    rows = []
    for target in TARGETS:
        imp = pd.read_csv(f"reports/runs/{TAG}/shap_importance_{target}.csv")
        imp["rank"] = imp.index + 1
        sup = support(target)
        for f in IDENTITY:
            r = imp[imp.feature == f].iloc[0]
            pos = int(sup[f"{f}__pos"])
            rows.append({
                "feature": f,
                "target": target,
                "mean_abs_shap": float(r.mean_abs_shap),
                "rank": int(r["rank"]),
                "n_features": len(imp),
                "train_rows": int(sup.n_rows),
                "n_nonnull": int(sup[f"{f}__nn"]),
                "n_positive": pos,
                # Could LightGBM have split on it at all? A binary flag needs at least
                # `min_child_samples` positives to put a legal leaf on the "1" side.
                "splittable": pos >= min_child,
            })
    tbl = pd.DataFrame(rows)

    out = tbl.round({"mean_abs_shap": 6})
    print(report.save_table(
        out, "shap_lender_identity_receipt",
        caption=f"Counterparty-identity features in the {TAG} run: mean|SHAP| and rank per "
                f"target, with the training support that says whether a zero is a refusal "
                f"or an inability. min_child_samples = {min_child}."))

    pd.set_option("display.width", 200)
    print(f"\nmin_child_samples = {min_child}\n")
    print(tbl.pivot(index="feature", columns="target", values="mean_abs_shap")
             .reindex(IDENTITY).to_string())
    print()
    print(tbl.pivot(index="feature", columns="target", values="n_positive")
             .reindex(IDENTITY).to_string())
    print()
    print(tbl.pivot(index="feature", columns="target", values="rank")
             .reindex(IDENTITY).to_string())
    print()
    for f in IDENTITY:
        sub = tbl[tbl.feature == f]
        n_zero = int((sub.mean_abs_shap == 0).sum())
        n_split = int(sub.splittable.sum())
        if n_split < len(TARGETS):
            verdict = (f"zero on {n_zero}/4, but splittable on only {n_split}/4 "
                       f"({sub.n_positive.min():,} to {sub.n_positive.max():,} positives). "
                       "Not admissible as a refusal.")
        elif n_zero == len(TARGETS):
            verdict = (f"exactly zero on 4/4 and splittable on 4/4 "
                       f"({sub.n_positive.min():,} to {sub.n_positive.max():,} positives). "
                       "The model could have used it and did not.")
        else:
            verdict = (f"zero on {n_zero}/4, otherwise nonzero but negligible "
                       f"(max {sub.mean_abs_shap.max():.2e}). Used, not usefully.")
        print(f"  {f:26s} {verdict}")


if __name__ == "__main__":
    main()
