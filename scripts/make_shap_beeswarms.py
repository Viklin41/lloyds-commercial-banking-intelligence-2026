"""The four SHAP beeswarm summary plots, saved as files this time.

These plots have existed since `16_shap_models.ipynb`, but only ever as PNG blobs inside
a notebook. §2.3 of the report promises an examiner can read our SHAP figures, and every
other analytical figure in the project goes through `report.save_fig` and lands in
`reports/figures/` as a PDF. These were the only ones that got rendered and then dropped
on the floor, so this puts them where the rest are.

Nothing is retrained. The models are the ones `refactor_growthfix` already pickled; this
rebuilds the same out-of-time test frame `run_target` used, takes the same stratified
100k subsample, and explains it.

    ./.venv/bin/python scripts/make_shap_beeswarms.py
"""
import gc
import pickle
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import shap

from src.models import report, train, targets

TARGETS = ("lending", "insolvency", "growth", "voluntary_exit")
STAGE = Path("data/processed/run_stage/refactor_growthfix")
MAX_DISPLAY = 15

CFG = replace(
    train.REFACTOR,
    tag="refactor_growthfix",
    feature_overrides=(("growth", tuple(targets.FEATURE_COLS_SHORT_HISTORY)),),
)


def test_frame(target: str, levels: dict):
    """The unsampled out-of-time test frame, rebuilt exactly as `run_target` builds it.

    The categories come off the pickle rather than from `align_categories`, because the
    training frame is not in memory here and the pickled levels are what the fitted model
    was given in the first place.
    """
    cols, cats = CFG.cols(target), CFG.cats(target)
    split = train.split_origins(target, CFG)
    test = train.load_origins(target, split.test, CFG.eval_dir, cols, cats)
    X = train.feature_frame(test, cols)
    for c, lv in levels.items():
        if c in X.columns:
            X[c] = pd.Categorical(X[c], categories=lv)
    return X, test["y"].to_numpy(), split


def main() -> None:
    for target in TARGETS:
        with open(STAGE / f"model_{target}.pkl", "rb") as fh:
            model = pickle.load(fh)

        X, y, split = test_frame(target, model["levels"])
        print(f"{target}: {len(X):,} test rows over "
              f"{', '.join(f'{m:%Y-%m}' for m in split.test)}, {X.shape[1]} features")

        Xs, ys = train.shap_sample(X, y)
        del X, y
        gc.collect()
        sv = train.explain("lightgbm", model["lightgbm"], Xs)
        print(f"{target}: explained {len(Xs):,} rows, {int(ys.sum()):,} positives")

        # summary_plot draws onto the current figure and does not hand one back, so the
        # figure has to be sized before the call and collected after it.
        plt.figure(figsize=(9, 6))
        shap.summary_plot(sv, Xs, max_display=MAX_DISPLAY, show=False)
        fig = plt.gcf()
        fig.suptitle(f"SHAP summary, {target} ({CFG.tag}, {len(Xs):,} held-out rows)",
                     fontsize=11)
        fig.axes[0].set_xlabel("SHAP contribution (log-odds)")
        fig.tight_layout()
        print("   ", report.save_fig(fig, f"shap_beeswarm_{target}"))
        plt.close(fig)

        del Xs, ys, sv, model
        gc.collect()


if __name__ == "__main__":
    main()
