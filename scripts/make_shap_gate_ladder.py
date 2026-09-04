"""The gate ladder, told through SHAP importance instead of through precision@N.

§4.1.4 currently makes the leakage case with `precision@100 = 1.000` and the margin sweep.
This is a second witness for the same claim, and it is completely independent of the
metrics: it comes from inside the model rather than from its scores. When the as-of gate
admits a charge on `created_on`, `n_charges_outstanding` climbs to rank 1 by mean|SHAP| on
lending. Move the gate to `delivered_on` and it drops; add the 21-day margin and it falls
out of the top of the table altogether. The model is telling us which feature it was
reading the label off, and it agrees with the metric.

Pure plotting. Nothing is retrained and nothing is re-explained; every number here is read
off the `shap_importance_lending.csv` each run already recorded.

    ./.venv/bin/python scripts/make_shap_gate_ladder.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.models import report, targets

# The three rungs, loosest gate first. This is the order §4.1.4 tells the story in:
# the bug, the obvious fix that was not enough, and the calibrated gate.
LADDER = [
    ("lender", "created_on\n(the bug)"),
    ("lender_fixed", "delivered_on\n(half the fix)"),
    ("lender_asof21", "delivered_on + 21d\n(calibrated)"),
]
TARGET = "lending"
TOP_K = 8


def lender_family() -> list[str]:
    """The 13 columns the lender runs add on top of the 41-feature base set."""
    base = set(targets.FEATURE_COLS)
    cols = json.loads(Path("reports/runs/lender_fixed/manifest.json").read_text())["feature_cols"]
    return [c for c in cols if c not in base]


def ladder_table(family: list[str]) -> pd.DataFrame:
    rows = []
    for tag, _ in LADDER:
        imp = pd.read_csv(f"reports/runs/{tag}/shap_importance_{TARGET}.csv")
        imp["rank"] = imp.index + 1
        for _, r in imp[imp.feature.isin(family)].iterrows():
            rows.append({"tag": tag, "feature": r.feature,
                         "mean_abs_shap": r.mean_abs_shap, "rank": int(r["rank"]),
                         "n_features": len(imp)})
    return pd.DataFrame(rows)


def main() -> None:
    family = lender_family()
    tbl = ladder_table(family)

    # Only the lender features that ever get near the top are worth drawing; the rest
    # are flat at zero on every rung and would be twelve indistinguishable lines.
    best = tbl.groupby("feature").mean_abs_shap.max().sort_values(ascending=False)
    shown = list(best.head(TOP_K).index)

    wide = (tbl.pivot(index="feature", columns="tag", values="mean_abs_shap")
               .reindex(shown)[[t for t, _ in LADDER]])
    ranks = (tbl.pivot(index="feature", columns="tag", values="rank")
                .reindex(shown)[[t for t, _ in LADDER]])

    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = range(len(LADDER))
    for feat in shown:
        y = wide.loc[feat].to_numpy()
        lead = feat == "n_charges_outstanding"
        ax.plot(x, y, marker="o", lw=2.6 if lead else 1.2,
                color="#c1121f" if lead else "#9aa0a6",
                zorder=3 if lead else 2, label=feat if lead else None)
        for i, v in enumerate(y):
            r = ranks.loc[feat].iloc[i]
            if lead or v > 0.05:
                ax.annotate(f"{feat if i == 0 else ''}  #{int(r)}",
                            (i, v), textcoords="offset points", xytext=(6, 6),
                            fontsize=8, color="#c1121f" if lead else "#5f6368",
                            ha="left", zorder=4)

    n_feat = int(tbl.n_features.iloc[0])
    ax.set_xticks(list(x))
    ax.set_xticklabels([lab for _, lab in LADDER], fontsize=9)
    ax.set_ylabel("mean |SHAP| on lending (log-odds)")
    ax.set_title("The leaking feature climbs to rank 1 and falls back when the gate is fixed\n"
                 f"lender-family features, lending, rank shown out of {n_feat}", fontsize=11)
    ax.grid(axis="y", alpha=0.25)
    ax.set_ylim(bottom=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    print(report.save_fig(fig, "shap_gate_ladder_lending"))

    out = (tbl[tbl.feature.isin(shown)]
           .assign(rung=lambda d: d.tag.map({t: i + 1 for i, (t, _) in enumerate(LADDER)}))
           .sort_values(["feature", "rung"])
           .loc[:, ["feature", "tag", "mean_abs_shap", "rank", "n_features"]]
           .round({"mean_abs_shap": 4}))
    print(report.save_table(
        out, "shap_gate_ladder_lending",
        caption="Lender-family SHAP importance on lending across the three as-of gates. "
                "Rank is out of the run's full feature list."))
    print()
    print(pd.concat([wide.round(3), ranks.astype(int).add_prefix("rank_")], axis=1).to_string())


if __name__ == "__main__":
    main()
