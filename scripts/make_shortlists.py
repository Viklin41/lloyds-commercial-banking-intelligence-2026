"""Top-N ranked company shortlists for the unstructured enrichment work.

`precision@N` is a *metric*: of the N companies the model ranked highest on a held-out
month, how many actually went on to do the thing. It does not hand you a list. The list
comes from the scoring stage, which applies the fitted model to the most recent snapshot
and writes a calibrated probability per company to `data/processed/scores/`.

This script turns that into the thing Samuel and Vishal can actually work from: the top N
companies per target for the live month, with the honest hit rate to expect next to it.

    python scripts/make_shortlists.py                 # top 100, refactor_growthfix, 2026-07
    python scripts/make_shortlists.py --n 500         # the phase-2 enrichment loop
"""
import argparse
import json
from pathlib import Path

import pandas as pd

TARGETS = ("lending", "insolvency", "growth", "voluntary_exit")
OUT_DIR = Path("reports/shortlists")


def per_origin_hit_rate(tag: str, target: str, model: str = "lightgbm") -> pd.DataFrame:
    """What precision@N actually was, per held-out month. Never pooled.

    Pooled precision@N is not an average of its months (it falls outside their range in
    9 of 12 rows), so the per-origin figures are the ones that describe what somebody
    receiving one month's list should expect.
    """
    r = json.loads(Path(f"data/processed/run_stage/{tag}/result_{target}.json").read_text())
    rows = [{"origin": o, "base_rate": m["base_rate"],
             "precision_at_100": m["precision_at_100"], "lift_at_100": m["lift_at_100"]}
            for o, m in sorted(r["metrics_by_origin"][model].items())]
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="refactor_growthfix")
    ap.add_argument("--month", default="2026-07")
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()

    scores = pd.read_parquet(f"data/processed/scores/scores_{args.tag}_{args.month}.parquet")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{len(scores):,} companies scored at {args.month} from `{args.tag}`\n")

    for target in TARGETS:
        top = (scores.nlargest(args.n, f"score_{target}")
                     .loc[:, ["CompanyNumber", "CompanyName", f"score_{target}"]]
                     .rename(columns={f"score_{target}": "score"})
                     .reset_index(drop=True))
        top.insert(0, "rank", top.index + 1)
        path = OUT_DIR / f"top{args.n}_{target}_{args.month}.csv"
        top.to_csv(path, index=False)

        hits = per_origin_hit_rate(args.tag, target)
        print(f"{target:15s} -> {path}")
        print(f"{'':15s}   score {top.score.min():.3f} to {top.score.max():.3f}")
        print(f"{'':15s}   held-out precision@100 "
              f"{' '.join(f'{r.origin[:7]}={r.precision_at_100:.2f}' for r in hits.itertuples())}"
              f"  (lift {hits.lift_at_100.min():.0f}x to {hits.lift_at_100.max():.0f}x)")


if __name__ == "__main__":
    main()
