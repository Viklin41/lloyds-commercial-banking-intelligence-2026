"""Per-company SHAP reasons for the July 2026 shortlists.

`scripts/make_shortlists.py` gives you the *who*: the top N companies per target for the
live month, ranked by the recalibrated score. It does not give you the *why*, and a call
list without a reason attached is not something a relationship manager can act on. This
script attaches the reason.

For each shortlisted company we run `TreeExplainer` over the row the model actually scored
and keep the three features with the largest absolute contribution, sign and feature value
included. Three, because that is what §4.3 of the report and the dashboard mock-up both
promise, and because past three the contributions are small enough that reading them out
would be over-claiming.

**Units.** `TreeExplainer` on an `LGBMClassifier` returns contributions in raw log-odds
(margin) space. The shipped score is a recalibrated probability, so the contributions sum
to the logit of the *uncalibrated* score and not to the number in the `score` column. The
ranking is unaffected, because the recalibration is monotone: the reasons explain the
ranking, and the probability is that ranking recalibrated.

    ./.venv/bin/python scripts/make_shortlist_reasons.py              # 100 / 5000
    ./.venv/bin/python scripts/make_shortlist_reasons.py --n 500      # phase-2 loop

Writes a *sibling* file per shortlist rather than touching `top100_<target>_<month>.csv`,
because numbers from those have already gone to Sam and Vishal. Join on rank + CompanyNumber.
"""
import argparse
import pickle
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from src.models import train, targets

TARGETS = ("lending", "insolvency", "growth", "voluntary_exit")
OUT_DIR = Path("reports/shortlists")
HANDOVER_DIR = Path("data/handover")
N_REASONS = 3

# `refactor_growthfix` is not a constant in train.py; it is assembled in
# scripts/run_config_staged.py and has to be rebuilt the same way, or the growth model
# gets scored on the 41-column list it was never trained on.
CFG = replace(
    train.REFACTOR,
    tag="refactor_growthfix",
    feature_overrides=(("growth", tuple(targets.FEATURE_COLS_SHORT_HISTORY)),),
)


def load_model(target: str) -> dict:
    path = Path("data/processed/run_stage") / CFG.tag / f"model_{target}.pkl"
    with open(path, "rb") as fh:
        return pickle.load(fh)


def pin_levels(frame: pd.DataFrame, levels: dict) -> pd.DataFrame:
    """Restore the training categories on the live frame.

    A category the model never saw has to become NaN rather than a new level, otherwise
    LightGBM is handed a code it has no split for. Same pattern as the scoring stage.
    """
    for col, lv in levels.items():
        if col in frame.columns:
            frame[col] = pd.Categorical(frame[col], categories=lv)
    return frame


def as_value(v):
    """The feature value as something that survives a CSV and a parquet round trip.

    Missingness is meaningful in this matrix, so a missing value stays null rather than
    being coerced to a zero that would read as a measurement.
    """
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return str(v)


def reasons_for(target: str, scores: pd.DataFrame, live: pd.DataFrame, n: int) -> pd.DataFrame:
    """Long-format top-3 reasons for the top `n` companies on one target."""
    model = load_model(target)
    cols = CFG.cols(target)

    # nlargest, exactly as make_shortlists.py does it, so rank k here is rank k there.
    top = (scores.nlargest(n, f"score_{target}")
                 .loc[:, ["CompanyNumber", "CompanyName", f"score_{target}"]]
                 .rename(columns={f"score_{target}": "score"})
                 .reset_index(drop=True))
    top.insert(0, "rank", top.index + 1)

    X = (live.set_index("CompanyNumber")
             .loc[top.CompanyNumber, cols]
             .reset_index(drop=True))
    X = pin_levels(X, model["levels"])

    sv = train.explain("lightgbm", model["lightgbm"], X)
    assert sv.shape == X.shape, f"{target}: shap {sv.shape} against X {X.shape}"

    # The three largest by absolute contribution, per row, sign kept.
    order = np.argsort(-np.abs(sv), axis=1)[:, :N_REASONS]
    rows = []
    for i, cs in enumerate(order):
        for k, c in enumerate(cs):
            rows.append({
                "CompanyNumber": top.CompanyNumber.iat[i],
                "target": target,
                "rank": top["rank"].iat[i],
                "rank_within_reason": k + 1,
                "feature": cols[c],
                "contribution": float(sv[i, c]),
                "value": as_value(X.iloc[i, c]),
            })
    return top, pd.DataFrame(rows)


def widen(top: pd.DataFrame, long: pd.DataFrame) -> pd.DataFrame:
    """One row per company, reason_1..3 across the columns, for the CSV."""
    wide = top.copy()
    for k in range(1, N_REASONS + 1):
        part = (long[long.rank_within_reason == k]
                .set_index("CompanyNumber")[["feature", "contribution", "value"]])
        wide[f"reason_{k}"] = wide.CompanyNumber.map(part.feature)
        wide[f"contribution_{k}"] = wide.CompanyNumber.map(part.contribution)
        wide[f"value_{k}"] = wide.CompanyNumber.map(part.value)
    return wide


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="2026-07")
    ap.add_argument("--n", type=int, default=100, help="rows per shortlist CSV")
    ap.add_argument("--n-handover", type=int, default=5000,
                    help="rows per target in the dashboard parquet")
    args = ap.parse_args()

    scores = pd.read_parquet(f"data/processed/scores/scores_{CFG.tag}_{args.month}.parquet")
    print(f"{len(scores):,} companies scored at {args.month} from `{CFG.tag}`")

    print("loading the live frame")
    live = train.load_scoring_frame(CFG)
    print(f"{len(live):,} rows, {len(live.columns)} columns")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HANDOVER_DIR.mkdir(parents=True, exist_ok=True)
    handover = []

    for target in TARGETS:
        n_big = max(args.n, args.n_handover)
        top, long = reasons_for(target, scores, live, n_big)

        csv_top = top.head(args.n)
        csv_long = long[long["rank"] <= args.n]
        path = OUT_DIR / f"top{args.n}_{target}_{args.month}_reasons.csv"
        widen(csv_top, csv_long).to_csv(path, index=False)

        handover.append(long[long["rank"] <= args.n_handover]
                        .drop(columns=["rank"]))

        counts = long[long["rank"] <= args.n].feature.value_counts()
        print(f"\n{target:15s} -> {path}")
        print(f"{'':15s}   {len(cols_used := set(counts.index))} distinct features across "
              f"{args.n} companies")
        for feat, c in counts.head(5).items():
            print(f"{'':15s}     {feat:38s} {c:4d} of {args.n * N_REASONS}")

        # The growth model trains on the 27-feature short-history list. If a 41-feature
        # name reaches this far the feature_overrides wiring is wrong, and it would be
        # wrong silently, so fail loudly instead.
        if target == "growth":
            allowed = set(targets.FEATURE_COLS_SHORT_HISTORY)
            stray = cols_used - allowed
            assert not stray, f"growth reasons cite non-short-history features: {sorted(stray)}"

    out = HANDOVER_DIR / f"shortlist_reasons_{args.month}.parquet"
    pd.concat(handover, ignore_index=True).to_parquet(out, index=False)
    print(f"\n{out}  ({out.stat().st_size / 1e6:.1f} MB, "
          f"top {args.n_handover} per target, long format)")


if __name__ == "__main__":
    main()
