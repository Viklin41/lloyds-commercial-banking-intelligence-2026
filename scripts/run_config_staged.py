"""Run one `train.RunConfig` in resumable stages.

The notebook is the nicer artefact, but it has to run start to finish in one go, and
this machine keeps restarting under me (WSL comes back with an uptime of a couple of
minutes and takes any long job with it). So this does exactly what
`notebooks/16_shap_models.ipynb` does, one stage at a time, checkpointing to disk
after each one. Re-running it picks up where it stopped and a restart costs one
target rather than the whole run.

Checkpoints go under `data/processed/run_stage/<tag>/` because /tmp does not survive
the reboot either.

    python scripts/run_config_staged.py lender
"""
import json
import pickle
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features import panel
from src.models import targets, train

CONFIGS = {"refactor": train.REFACTOR, "lender": train.LENDER,
           "lender_fixed": train.LENDER_FIXED,
           "lender_asof21": train.LENDER_ASOF21}

# The 7 Aug remediation queue. These are defined here rather than in `train.py`
# because they are queue entries rather than reference configs, and `train.py` is
# being edited in parallel. Each is one deliberate deviation from a config above.
#
# `refactor_det` and `lender_asof21_det` are not new experiments: they are the same
# two runs re-recorded now that `LGB_PARAMS` carries `deterministic=True`, which
# changes every LightGBM digit on disk. Everything in the report's results section
# is read off these rather than off `refactor`/`lender_asof21`.
CONFIGS["refactor_det"] = replace(train.REFACTOR, tag="refactor_det")
CONFIGS["lender_asof21_det"] = replace(train.LENDER_ASOF21, tag="lender_asof21_det")

# The growth fix: `growth` trains on the 27 features that exist at its training
# origins, instead of 41 of which 13 are 100% NULL in train and populated in test.
# The other three targets are untouched, which is what makes this a clean A/B
# against `refactor_det`.
# The recalibrated gate, plus the two sensitivity variants. The variants move the
# *criterion* rather than a standard error, because the bootstrap interval on the lag
# came out degenerate ([4, 4] over 500 cluster resamples): the real uncertainty is in
# how you decide the lag, not in the sampling noise around it. `_lo` is the
# mean-matching end (2d/1d), `_hi` is the leak-averse end (7d/3d, under 1% early).
for _tag, _suffix in (("lender_calib", "_calib"),
                      ("lender_calib_lo", "_calib_lo"),
                      ("lender_calib_hi", "_calib_hi")):
    CONFIGS[_tag] = replace(
        train.LENDER_ASOF21,
        tag=_tag,
        matrix_dir=Path(f"data/processed/model_matrix_lender{_suffix}"),
        eval_dir=Path(f"data/processed/eval_matrix_lender{_suffix}"),
        lender_dir=Path(f"data/processed/lender_panel{_suffix}"),
    )

CONFIGS["refactor_growthfix"] = replace(
    train.REFACTOR,
    tag="refactor_growthfix",
    feature_overrides=(("growth", tuple(targets.FEATURE_COLS_SHORT_HISTORY)),),
)
CFG = CONFIGS[sys.argv[1]]
STAGE = Path("data/processed/run_stage") / CFG.tag
STAGE.mkdir(parents=True, exist_ok=True)


def done(name: str) -> bool:
    return (STAGE / name).exists()


def save_json(name: str, obj) -> None:
    (STAGE / name).write_text(json.dumps(obj, indent=2, default=str))


def load_json(name: str):
    return json.loads((STAGE / name).read_text())


def log(msg: str) -> None:
    print(f"[{pd.Timestamp.now():%H:%M:%S}] {msg}", flush=True)


splits = {t: train.split_origins(t, CFG) for t in CFG.target_names}

# --- stage 1: the unsampled evaluation population -------------------------- #
for t in CFG.target_names:
    if done(f"eval_{t}.json"):
        continue
    log(f"eval matrix: {t}")
    summary = train.build_eval_matrix(t, splits[t].test, CFG, threads=6)
    save_json(f"eval_{t}.json", summary.to_dict("records"))

# --- stage 2: train, evaluate, SHAP and the direction check, per target ----- #
#
# All four of these live in one stage on purpose: they share the fitted models and
# the held-out frame, and reloading a 2.8M-row test matrix to do them separately
# would cost more than it saves.
def logit_directions(target, importance, X, sv, pipe, k=12):
    names = pipe.named_steps["pre"].get_feature_names_out()
    coefs = pd.Series(pipe.named_steps["clf"].coef_[0], index=names)
    cols = list(X.columns)
    out = []
    for row in importance.head(k).itertuples():
        hits = coefs[[n for n in names
                      if n.endswith("__" + row.feature) and "missingindicator" not in n]]
        if len(hits) == 0:
            continue
        j = cols.index(row.feature)
        x = X.iloc[:, j].to_numpy(dtype=float)
        ok = ~np.isnan(x)
        if ok.sum() < 1000 or np.nanstd(x[ok]) == 0:
            continue
        rho = float(spearmanr(x[ok], sv[ok, j]).statistic)
        c = float(hits.iloc[int(np.argmax(np.abs(hits.to_numpy())))])
        out.append({"feature": row.feature, "shap_direction": rho, "logit_coef": c,
                    "agree": bool(np.sign(rho) == np.sign(c)), "target": target})
    return out


for t in CFG.target_names:
    if done(f"result_{t}.json"):
        continue
    log(f"train: {t}")
    r = train.run_target(t, CFG)
    public = {k: v for k, v in r.items() if not k.startswith("_")}

    log(f"shap: {t}")
    Xs, ys = train.shap_sample(r["_X_test"], r["_y_test"])
    sv = train.explain("lightgbm", r["_models"]["lightgbm"], Xs)
    importance = train.shap_importance(sv, Xs)
    importance.to_csv(STAGE / f"shap_importance_{t}.csv", index=False)

    save_json(f"directions_{t}.json",
              logit_directions(t, importance, Xs, sv, r["_models"]["logistic"]))

    # Only what the scoring stage needs: the ranker, its calibration, and the
    # category levels the models were trained on.
    with open(STAGE / f"model_{t}.pkl", "wb") as fh:
        pickle.dump({
            "lightgbm": r["_models"]["lightgbm"],
            "neg_keep_rate": r["calibration"]["train_neg_keep_rate"],
            "levels": {c: list(r["_X_test"][c].cat.categories) for c in CFG.cats(t)},
        }, fh)

    save_json(f"result_{t}.json", public)
    del r, Xs, sv

# --- stage 3: grouped CV --------------------------------------------------- #
for t in CFG.target_names:
    if done(f"cv_{t}.json"):
        continue
    log(f"grouped cv: {t}")
    save_json(f"cv_{t}.json", train.grouped_cv_auc(t, CFG))

# --- stage 4: the tuning demonstration ------------------------------------- #
for t in ("lending", "insolvency"):
    for m in ("logistic", "lightgbm"):
        if done(f"tune_{t}_{m}.json"):
            continue
        log(f"tune: {t} {m}")
        res = {k: v for k, v in train.tune_model(m, t, CFG, n_iter=4).items()
               if k != "cv_results"}
        save_json(f"tune_{t}_{m}.json", res)

# --- stage 5: score the live month ----------------------------------------- #
SCORE_PATH = train.score_path(CFG)
if not SCORE_PATH.exists():
    log("scoring the live month")
    live = train.load_scoring_frame(CFG)
    with open(STAGE / f"model_{CFG.target_names[0]}.pkl", "rb") as fh:
        levels = pickle.load(fh)["levels"]
    for c, lv in levels.items():
        if c in live.columns:
            live[c] = pd.Categorical(live[c], categories=lv)
    for t in CFG.target_names:
        with open(STAGE / f"model_{t}.pkl", "rb") as fh:
            m = pickle.load(fh)
        # `target=t` matters under `feature_overrides`: the live frame carries every
        # column, and a model trained on a target's shorter list has to be handed
        # that same list back or it scores on columns it never saw.
        live[f"score_{t}"] = train.score_frame(m["lightgbm"], live, m["neg_keep_rate"], CFG,
                                               target=t)
    train.SCORE_DIR.mkdir(parents=True, exist_ok=True)
    live[["CompanyNumber", "CompanyName", "origin_month",
          *[f"score_{t}" for t in CFG.target_names]]].to_parquet(SCORE_PATH, index=False)
    log(f"wrote {SCORE_PATH}")

# --- stage 6: record the run ----------------------------------------------- #
results = [load_json(f"result_{t}.json") for t in CFG.target_names]
cv = [load_json(f"cv_{t}.json") for t in CFG.target_names]
tuning = [load_json(f"tune_{t}_{m}.json")
          for t in ("lending", "insolvency") for m in ("logistic", "lightgbm")]
directions = [d for t in CFG.target_names for d in load_json(f"directions_{t}.json")]

out = train.record_run(results, CFG, grouped_cv=cv, direction_check=directions,
                       tuning=tuning, scores=str(SCORE_PATH))
for t in CFG.target_names:
    dest = train.shap_importance_path(t, CFG.tag)
    dest.write_text((STAGE / f"shap_importance_{t}.csv").read_text())
log(f"recorded {out}")
print(train.load_runs()[["tag", "target", "model", "n_features", "roc_auc", "precision_at_500"]]
      .to_string(index=False))
