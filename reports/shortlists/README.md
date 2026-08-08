# Ranked company shortlists, July 2026

**For Samuel and Vishal.** Generated 8 August 2026 by `scripts/make_shortlists.py`.

## What these are, and the thing I got wrong when I proposed this

I originally told you the `precision@N` metric would give us this list. It does not.
`precision@N` is a **scoring metric**: of the N companies the model ranked highest on a
month we had held out, how many actually went on to do the thing. It is a report card on a
past month, not a list of companies.

The list comes from a different place: the last stage of every run applies the fitted model to
the **most recent snapshot** and writes a calibrated probability per company to
`data/processed/scores/`. That covers **1,409,284 active companies at July 2026**. These
CSVs are just the top 100 of that, per target.

This also answers the staleness worry directly. The model is *trained* across 33 months,
but it is *applied* to July 2026 only, which is exactly what a Lloyds representative would
do. Nobody gets handed a company that was predicted to fail in October 2023 and has since
been struck off.

## The files

| File | Question it answers | Horizon from July 2026 |
|---|---|---|
| `top100_lending_2026-07.csv` | who is about to take on new borrowing | next **3 months** |
| `top100_insolvency_2026-07.csv` | who is heading for insolvency | next **6 months** |
| `top100_voluntary_exit_2026-07.csv` | who is likely to wind up voluntarily | next **6 months** |
| `top100_growth_2026-07.csv` | who is about to move up a size band | next **12 months** |

Columns: `rank`, `CompanyNumber`, `CompanyName`, `score`. `CompanyNumber` is the join key
for the unstructured pipeline. `score` is a calibrated probability, so 0.43 means roughly a
43% chance, not a rank percentile.

The four lists are almost disjoint: **398 unique companies across the four hundred rows**,
with only two companies appearing twice (both in `lending` and `growth`, which makes sense).
So this is 398 enrichment lookups, not 400 and not 100.

## What hit rate to expect, honestly

These are **per held-out month**, never pooled. Pooled precision@N is not an average of its
months (it lands outside their range in 9 of 12 cases), so the monthly figures are the ones
that describe what somebody receiving one month's list actually experiences.

| Target | precision@100, per month | base rate | lift |
|---|---|---|---|
| `lending` | 0.43, 0.41 | 0.26% | **~150x** |
| `insolvency` | 0.16, 0.14 | 0.38% | ~45x |
| `growth` | 0.22, 0.22 | 2.2% | ~10x |
| `voluntary_exit` | 0.85, 0.78 | ~8% | ~10x |

Read the **lift** column, not the precision column, when judging how good the model is.
`voluntary_exit` looks like the best list at 85% and is actually the weakest, because
roughly one in twelve companies exits anyway. `lending` at 43% is by far the strongest
result here: it is about 150 times better than picking at random.

For the report, `lending` is the list to lead with.

## One warning, on `voluntary_exit` specifically

**Do not treat the `voluntary_exit` ranking as meaningful, and be careful quoting it.**
Its top 1000 scores contain only **14 distinct values**, and **138 companies are tied at the
score that sits in 100th place**. So "the top 100" there is an arbitrary 100 drawn from a
pool of over 200 equally-ranked companies, and re-running the sort could return a different
hundred with identical scores.

The model is separating a broad band of at-risk companies rather than picking individuals,
which is a genuine finding about the target and not a bug. If you want to use this list,
either enrich the whole tied band and say so, or pick from it at random and document that.
The other three targets are fine: 993, 961 and 994 distinct scores in their top 1000, with
a single company sitting at the cut.

## Which model produced these

`refactor_growthfix`: the 41-feature control with the `growth` defect fixed, LightGBM.
Deliberately **not** one of the lender-feature runs.

The lender features do not earn their place here. At the most conservative visibility gate
we tested they give the boosted model nothing, and any apparent gain above that gate scales
with how much margin the gate allows, which is the region where we cannot separate signal
from lookahead. Using the control means the shortlist carries no exposure to that argument
at all, which matters because these names may end up in front of people.

Its scores are byte-identical to `refactor_det` for `lending`, `insolvency` and
`voluntary_exit`, and better for `growth`.

## Regenerating, and the phase-2 loop

```bash
python scripts/make_shortlists.py                    # top 100, as here
python scripts/make_shortlists.py --n 500            # the enrichment loop in section 6
python scripts/make_shortlists.py --month 2026-07 --tag refactor_det
```

Section 9 of `drafts/next-steps-2026-08-07.md` parked the "rank the top 500, enrich all of
them, re-run the model" design until we knew the API cost per company. **The ranking half of
that is now free and takes one command**, so the only open question left is the cost per
company. At 500 per target the union will be roughly 1,900 to 2,000 companies rather than
2,000, on the overlap seen above.

## Caveats worth carrying into the report

1. These are **predictions, not facts**, and the honest hit rates are in the table above.
2. `growth` uses 27 features rather than 41; the other three use 41. See
   `notebooks/18_growth_defect.ipynb`.
3. The scored population is the **active** company universe at July 2026, filtered to our
   BB/SME sectors, so this is not the whole register.
4. Scores are comparable **within** a target and a month, not across targets. A 0.43 on
   `lending` and a 0.43 on `insolvency` are not the same strength of claim, because the base
   rates differ by a factor of about 1.5 and the lifts by a factor of three.
