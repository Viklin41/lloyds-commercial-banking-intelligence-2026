# Answers to the dashboard open questions, 25 August 2026

Companion to `drafts/meeting-open-questions-2026-08-25.md`. I worked the running order in
Part 3 of that file rather than the numbering, so the dependencies fall out in the right
order. Every number below was recomputed from the repository on 25 August rather than
quoted from a note, and where I could reproduce something independently I did.

Two things came out of this that were not on the question list and that change what I owe
Vishal. They are flagged **NEW** and both sit under Q5/Q9.

**Verdict on the freeze:** it can lift, but with a defect list attached. Nothing I found
invalidates the dashboard's data. One sentence on the model score card is wrong in a way
that matters commercially, and that is the thing to fix first.

---

## Q3. Is the 3/6/12 month window a training construct, or the window being predicted?

**Answer: it is really the window being predicted. Vishal was right and I was wrong. I owe
him the correction, and the card is already correct as written.**

The label SQL is in `src/models/targets.py`, `LABEL_SQL`. The forward windows are DuckDB
`RANGE` frames:

```sql
w3  AS (PARTITION BY cn ORDER BY m
        RANGE BETWEEN INTERVAL 1 MONTH FOLLOWING AND INTERVAL 3 MONTH FOLLOWING)
```

and the label is an aggregate *over that frame*, not a read of its last month:

```sql
CASE WHEN m <= DATE '{max_lending}' AND n_obs_f3 > 0
     THEN (max_charges_f3 > charges)::INT END AS y_lending
```

`max_charges_f3` is `max(charges) OVER w3`. So `y_lending = 1` if the charge count is
higher than it was at the origin **at any observed month in t+1 through t+3**. That is
reading B.

The module docstring says so in as many words at line 34: "A label fires if the thing
happened at *any* observed month in `t+1 ... t+H`, not if it is still true at `t+H`." It
even explains why it matters most for voluntary exit, where the event reading (7.2%) is
about twice the state-at-`t+H` reading (3.5%), because strike-off proposals get withdrawn.

**All four horizons behave identically.** Three frames exist, `w3`, `w6` and `w12`, and
every label is a `max(...)` over its frame:

| Target | Frame | Label expression |
|---|---|---|
| `lending` | w3 | `max_charges_f3 > charges` |
| `insolvency` | w6 | `max(status IN insolvent) OVER w6` |
| `voluntary_exit` | w6 | `max(status = strike off) OVER w6` |
| `growth` | w12 | `max_tier_f12 > tier_rank` |

**The arithmetic checks out.** Origin 1 July 2026, window `t+1 .. t+3` is August,
September and October 2026. The card's "August to October 2026" is right.
`reports/dashboard_handover_columns.md` lines 260 to 263 already state all four windows the
same way (Aug-Oct 2026, Aug 2026-Jan 2027 twice, Aug 2026-Jul 2027), so our own handover doc
had settled this before the call and neither of us had it in front of us.

One refinement for the lending card, since "takes on new secured borrowing" is slightly
loose: the event is specifically that `Mortgages.NumMortCharges` is *higher* at some point
in the window than it was on 1 July. It is a new charge registration, not a drawdown.

---

## Q1. How do we read the number on the MODEL SCORE card?

**Answer: it is a probability-scaled score, and it is empirically much better calibrated
than I expected across the bulk of the population, but it is not certified at the top of
the list, which is exactly where a dashboard looks. The README is wrong and needs
correcting. Vishal's second answer was closer to right than his first.**

### What produces the number

1. **The estimator is LightGBM.** `src/models/train.py:632` constructs
   `lgb.LGBMClassifier`. Logistic and MLP are in the registry and are fitted, but they are
   not what ships: `scripts/run_config_staged.py:189` writes the score column from
   `m["lightgbm"]` explicitly. So the shipped scores are a boosted tree ensemble, not a
   logistic model.

2. **`recalibrate` is a downsampling correction and nothing else.** `train.py:958`:

   ```python
   odds = p / (1 - p) * np.asarray(neg_keep_rate, dtype=float)
   return odds / (1 + odds)
   ```

   Training keeps every positive and a fraction `r` of negatives, which multiplies the odds
   by `1/r`; this multiplies them back by `r`. It is a monotone transform of the raw model
   output. It is **not** Platt scaling and **not** isotonic regression: no calibration curve
   is fitted to held-out data anywhere. I grepped `src/`, `scripts/` and every notebook for
   `CalibratedClassifierCV`, `IsotonicRegression`, `isotonic` and `Platt`, and there are
   **zero occurrences in the repository**.

3. **The shipped column is post-`recalibrate`, and it is untouched afterwards.**
   `notebook 20` selects `s."score_lending"` and friends verbatim out of
   `scores_refactor_growthfix_2026-07.parquet`. I verified this rather than trusting it:
   joining the handover parquet's scored rows to the source scores parquet gives 1,409,284
   rows matched on both sides, 0 left-only, 0 right-only, and **max absolute difference of
   exactly 0.000e+00 on all four score columns**.

### The evidence, which is the part that surprised me

I rebuilt the two held-out test origins for each target from `data/processed/eval_matrix/`,
scored them with the exact pickled models in
`data/processed/run_stage/refactor_growthfix/`, applied `recalibrate`, and compared
predicted against observed. This is the reliability curve the question asked for, and it
uses realised outcomes rather than the July frame, which has no outcomes yet.

**At the population level the correction works well.** Mean recalibrated score against
observed base rate on the unsampled held-out population:

| Target | Test rows | Mean score | Observed base rate |
|---|---|---|---|
| `lending` | 2,782,591 | 0.00301 | 0.00271 |
| `insolvency` | 2,779,612 | 0.00363 | 0.00329 |
| `voluntary_exit` | 2,779,612 | 0.08140 | 0.07728 |
| `growth` | 1,817,119 | 0.02082 | 0.02137 |

Decile by decile it also tracks. For `voluntary_exit`, which has enough positives to see it
clearly, predicted against observed by decile runs 0.008/0.009, 0.020/0.020, 0.026/0.028,
0.032/0.033, 0.038/0.039, 0.045/0.045, 0.055/0.055, 0.074/0.072, 0.132/0.135, 0.385/0.337.
That is a well-behaved curve. So the flat claim "this is not a probability, it is only a
rank" is too pessimistic, and I should not put it in the report in that form.

**In the top tail it drifts, and mostly optimistically.** By absolute score band, observed
over predicted:

| Band | `lending` | `insolvency` | `growth` | `voluntary_exit` |
|---|---|---|---|---|
| 0.01 to 0.05 | 0.90 | 0.79 | 1.05 | 1.03 |
| 0.05 to 0.10 | 0.80 | 0.86 | 0.97 | 0.99 |
| 0.10 to 0.20 | 0.71 | 0.85 | 0.88 | 1.02 |
| 0.20 to 0.30 | 0.69 | 0.85 | 0.76 | 0.89 |
| 0.30 to 0.40 | 0.89 | 0.30 | 0.70 | 0.81 |
| 0.40 to 0.50 | 1.21 | 0.65 | 0.54 | 0.81 |
| 0.50 and up | 1.12 | 0.00 | 0.00 | 0.94 |

**And the extreme tail has almost no data behind it.** The number of held-out rows landing
above 0.5 is **10 for lending, 2 for insolvency, 2 for growth**. On the July frame, 8
companies score at or above 0.5 on lending, 1 on growth, 0 on insolvency. So a statement
about what 0.577 means is a statement resting on ten observations. `voluntary_exit` is the
exception: 43,000 held-out rows sit above 0.5 and it is well calibrated there.

### The sentence that survives all of that

> The model score is the estimated probability that the company does the thing in the stated
> window, corrected back to the true base rate after training. It is not a fitted calibration
> curve, so treat it as approximately right in the middle of the range and as a ranking near
> the top, where it runs optimistic and where we have too few past cases to check it.

On the complement: because the label is binary and defined on a fixed window, `1 - score`
does have a meaning, namely the estimated chance the company **does not** take on new
secured borrowing between August and October 2026. That is a real quantity, so the answer to
"what is the other 42.3%" is not "nothing". But the specific figure inherits the same
uncertainty as the score, so I would not put the complement on screen.

### The README is wrong and Sam and Vishal have it

`reports/shortlists/README.md` currently says:

> `score` is a calibrated probability, so 0.43 means roughly a 43% chance, not a rank percentile.

Two problems. First, "calibrated" is doing work the word cannot bear here; it means
downsampling-corrected. Second, and worse, **0.43 is not a score, it is precision@100 for
lending**. The top-100 lending scores actually run 0.3556 to 0.5772. The example picked the
one number in the document most likely to be confused with the score, which is almost
certainly where Vishal's "the card shows precision" reading came from in the first place.
That is on me, not on him.

Replacement text I propose for the README:

> `score` is the model's estimated probability of the event inside the target's window,
> corrected back to the true base rate after negative downsampling. No calibration curve was
> fitted, so read it as approximately right in the middle of the distribution and as a
> ranking at the top, where it runs optimistic. Compare scores within a target and month,
> never across targets.

For what it is worth, the dashboard's own disclaimer is already the conservative version:
"These are model scores used to rank, not probabilities". So the dashboard is not the thing
that needs fixing here, the README is.

---

## Q6. Were the top 100 built from the full population, or from a sample?

**Answer: from the full population. The worry is dead.**

`scripts/make_shortlists.py` reads the whole scored parquet and calls
`scores.nlargest(args.n, f"score_{target}")`. There is no `sample`, no `head`, no `nrows`
and no row limit anywhere in the script or in the scoring stage that produced its input.

I reproduced it independently rather than only reading it. Loading
`scores_refactor_growthfix_2026-07.parquet` gives **1,409,284 rows, 1,409,284 unique
company numbers**, and taking the top 100 by score per target:

| Target | Set match | Order match | Max score difference | Score range |
|---|---|---|---|---|
| `lending` | yes | yes | 5.6e-17 | 0.3556 to 0.5772 |
| `insolvency` | yes | yes | 8.3e-17 | 0.1704 to 0.4779 |
| `growth` | yes | yes | 5.6e-17 | 0.2800 to 0.5139 |
| `voluntary_exit` | yes | yes | 1.1e-16 | 0.9162 to 0.9245 |

Identical companies in identical order, differing only in float printing. The README's
account is accurate.

**Disjointness: 398 is right and my 399 was wrong.** 398 unique companies across the 400
rows, with exactly two appearing twice, both on lending and growth:

- `08853263` SCHULTZ MEDICAL (UK) LTD
- `14703270` PILLAR CONTRACTS LIMITED

---

## Q2. How do we read the "Top x%"?

**Answer: it is computed live per company page against the 1,409,284 scored companies, with
ties resolved in the company's favour, and it is displayed as a coarse band rather than a
raw percentage. The convention is defensible; the label needs one clause added.**

**It is not a stored column.** There is no percentile column in
`dashboard_bulk_2026-07.parquet`; the only rank-like column is `tier_rank`, which is the size
ladder and unrelated. Vishal derives it in DuckDB at request time, in `full_record()`
(`serve.py:869`), as one scan producing all four at once:

```sql
SELECT count(*) AS n,
       count(*) FILTER (WHERE "score_lending" > ?) AS "score_lending", ...
FROM read_parquet(?) WHERE is_active
```

**The denominator is `is_active`, so 1,409,284, not 1,531,094.** That is the right choice
and it matches the population that was actually scored.

**The tie rule is strictly-greater**, so a company is counted as ahead of everyone with an
identical score. It is the most generous of the available conventions. For three of the four
targets this is a non-issue, because ties are effectively absent at the top (see Q7): the
company at rank 100 on lending, insolvency and growth is the *only* company at its score. It
matters only on `voluntary_exit`, where the rank-100 score is shared by 138 companies, and
there the strict rule reports a company as "top 0.0001%" when the honest range is "top
0.0001% to 0.0099%".

**What is on screen is a band, not a number.** `pctLabel()` buckets the percentage into Top
1% / Top 5% / Top 10% / Top 25% / Top half / Lower half, and `voluntary_exit` bypasses it
entirely for a High / Elevated / Moderate / Low band via `exitBand()`. So the tie problem is
largely absorbed by the coarseness of the band before it ever reaches a user. Vishal had
already solved most of this question before we asked it.

**Wording for the card.** The band label is fine as it stands. What is missing is the
population, so I would add one clause under the panel:

> Position among the 1,409,284 companies that were Active at 1 July 2026 and therefore
> scored. Companies with an identical score share a position.

---

## Q9. Which column is the card reading, and does it match the source?

**Answer: the score plumbing is exactly right. The precision figures beside it are not.**

**9.1 The scores match, across the whole range and the whole file.** Rather than 5 to 10
companies, I compared all of them: the handover parquet's scored rows join one-to-one to the
source scores parquet, 1,409,284 on both sides, and the maximum absolute difference on all
four score columns is **0.000e+00**. As a readable spot check, ten companies spanning the
lending distribution from 0.000234 to 0.312510 all agree on all four scores to the last bit.
The plumbing is not a worry.

**9.2 The precision figures do not come from the run JSONs at all. NEW.** They are hardcoded
constants in `dashboard/store_meta.json` under `score_models`, and `/api/meta` lifts that
block verbatim into `BUILD_META` without recomputing it. Two consequences:

- **Every value shown is the better of the two held-out months.** Lending is 0.43 where the
  months are 0.43 and 0.41; insolvency is 0.16 where they are 0.16 and 0.14; voluntary exit
  is 0.85 where they are 0.85 and 0.78. Growth is 0.22 and both months are 0.22. It is not
  the pooled figure, which would be worse in a different way, so Vishal avoided the trap in
  `make_shortlists.py`. But picking the flattering month and not saying so is its own
  problem.
- **The lift constant does not match anything.** `store_meta.json` says `lift: 160` for
  lending. The measured per-origin lifts are 166.9 and 144.1, and the README says about 150x.
  Three numbers, no source.

**9.3 THE ONE THAT MATTERS. NEW: the "43 in 100" sentence is shown to every company, in
every band.** In `index.html`, `scorePanel()` builds the note like this:

```js
const band = m.rankable ? pctLabel(s.pct) : exitBand(s.pct) + " band";
const note = m.rankable
  ? `${Math.round(m.hit_rate * 100)} in 100 at this level went on to ${esc(m.event)} when tested on past months`
  : `not ranked: ${esc(m.not_rankable_because)}`;
```

`note` depends only on `m.hit_rate`, which is a per-model constant. It does not read `s.pct`
at all. So a company sitting in **Lower half** on lending renders the sentence "43 in 100 at
this level went on to take on new secured borrowing when tested on past months", directly
underneath a band that says Lower half.

The phrase "at this level" makes it worse, because it explicitly promises the number is
about the company's band when it is not. `hit_rate` is precision@100: it is a property of
the top hundred companies and of nothing else. On a company at the median lending score the
true figure is roughly the base rate, about 1 in 400, not 43 in 100. The card overstates it
by a factor of about 170.

This is the same confusion as §1.4 of the question list, where we agreed the 43-in-100 is
global. It is global, and that is precisely the defect: a global top-100 statistic is being
narrated as a local one. This is the first thing to fix, and it is a one-line change.

**9.4 The row counts, so we stop saying three different things.** All three are true and they
describe different populations:

| Number | What it is |
|---|---|
| **1,531,094** | rows in `dashboard_bulk_2026-07.parquet`, all statuses. The dashboard universe |
| **1,409,284** | rows with `CompanyStatus = 'Active'`. Verified equal to the scored set |
| **121,810** | unscored, 7.96%, exactly the non-Active rows |

I verified that Active and scored are the same set, so the "1.4M" and "1.5M" figures are not
in conflict; one is the universe and the other is the scored population. The rule is to name
which one every time.

---

## Q4. Where do the shortlists and the top-5,000 extract live?

**Answer: confirmed, all four checks pass. One report correction falls out.**

**Row count.** `data/handover/shortlist_reasons_2026-07.parquet` holds exactly **60,000
rows**: 4 targets x 5,000 companies x 3 reasons, with every one of the 20,000 company-target
pairs carrying exactly 3 reasons. Columns are `CompanyNumber`, `target`,
`rank_within_reason`, `feature`, `contribution`, `value`. The `rank` column is dropped as
documented.

**The MS LENDING GROUP example in the report is accurate.** From
`top100_lending_2026-07_reasons.csv`:

| Field | Value |
|---|---|
| rank | 1 |
| CompanyNumber | 12723324 |
| score | 0.577182 |
| reason 1 | `Mortgages.NumMortCharges`, +2.7696, value 578 |
| reason 2 | `new_charge_events_12m`, +0.9157, value 11 |
| reason 3 | `segment`, +0.8557, value Large |

578 charges at +2.77, eleven new charge events at +0.92, Large segment at +0.86. That is
what §4.1 says.

**The units caveat is consistent between prose and code.** `make_shortlist_reasons.py`'s
docstring and §4.1.6 of the report both say `TreeExplainer` returns raw log-odds summing to
the logit of the uncalibrated score. Agreed and correct.

**But §4.1.6's worked pair is wrong.** It says "the top lending company on the July 2026 list
carries an uncalibrated probability of 0.972 and a shipped score of 0.500". The actual top
lending company, MS LENDING GROUP, carries a shipped score of **0.5772**, which back-solves
through `neg_keep_rate = 0.028487` to an uncalibrated **0.9796**. The quoted pair is
internally consistent (0.972 does recalibrate to 0.4972) but it is not this company under
this run. Either it predates the growth-fix run or it was worked by hand. Change it to
**0.9796 and 0.5772**, which makes the same point at least as well.

**Size, and why the 11 MB budget is the wrong question now.** 780 KB is trivial, but the 11
MB browser store it was going to be compared against no longer exists. That was the Design-2
sharded `data.js`, and the dashboard now runs DuckDB reading Parquet in place. This file
would be either a startup side table like Samuel's packs or, better, three columns joined
onto the spine. Neither has a browser budget. The real constraint is coverage, not size, and
that is Q8.

---

## Q5. Precision@N, base rate, lift, or a combination?

**Answer: show all three, in one sentence, scoped explicitly to the top 100, and stop
picking the better month silently.**

**The numbers, per origin, never pooled:**

| Target | Origin | Base rate | P@100 | Lift@100 | P@500 | Lift@500 |
|---|---|---|---|---|---|---|
| `lending` | 2026-01 | 0.26% | 0.43 | 167x | 0.218 | 85x |
| `lending` | 2026-04 | 0.28% | 0.41 | 144x | 0.226 | 79x |
| `insolvency` | 2025-10 | 0.33% | 0.16 | 49x | 0.108 | 33x |
| `insolvency` | 2026-01 | 0.33% | 0.14 | 42x | 0.116 | 35x |
| `growth` | 2025-04 | 2.12% | 0.22 | 10x | 0.176 | 8x |
| `growth` | 2025-07 | 2.15% | 0.22 | 10x | 0.172 | 8x |
| `voluntary_exit` | 2025-10 | 8.24% | 0.85 | 10x | 0.886 | 11x |
| `voluntary_exit` | 2026-01 | 7.22% | 0.78 | 11x | 0.820 | 11x |

**The pooled trap is real and I re-measured it.** Pooled precision falls outside the range of
its own months in 5 of the 8 target-metric combinations I checked:

| Target | Metric | Monthly range | Pooled | Verdict |
|---|---|---|---|---|
| `lending` | P@100 | 0.41 to 0.43 | **0.55** | outside |
| `lending` | P@500 | 0.218 to 0.226 | **0.282** | outside |
| `insolvency` | P@100 | 0.14 to 0.16 | **0.19** | outside |
| `insolvency` | P@500 | 0.108 to 0.116 | **0.122** | outside |
| `growth` | P@100 | 0.22 to 0.22 | 0.22 | inside |
| `growth` | P@500 | 0.172 to 0.176 | **0.194** | outside |
| `voluntary_exit` | P@100 | 0.78 to 0.85 | 0.83 | inside |
| `voluntary_exit` | P@500 | 0.820 to 0.886 | 0.848 | inside |

Note how badly it flatters lending: pooled P@100 of 0.55 against months of 0.43 and 0.41. If
we ever quoted 55 out of 100 it would be indefensible, and the dashboard does not, which is
to Vishal's credit.

**The recommendation.** Viktor's provisional preference from the question list survives the
numbers, with one non-negotiable change. Show:

> **Of the top 100 companies by this score, 41 to 43 took on new secured borrowing in the
> test months, against a base rate of 0.26%. That is roughly 150 times better than picking at
> random.**

Three changes from what is there now:

1. **"Of the top 100" replaces "at this level".** This is the Q9.3 fix and it is the whole
   ballgame. The sentence must not appear to describe the company being viewed.
2. **Give the range across held-out months, not the better one.** "41 to 43" rather than
   "43". It costs three characters and it is honest.
3. **Carry the base rate and the lift.** Precision alone flatters voluntary exit, lift alone
   is abstract, and the base rate is what makes both readable.

**Apply it to all four, including the two showing nothing.** Insolvency: "of the top 100, 14
to 16 hit a genuine insolvency event, against a base rate of 0.33%, roughly 45 times better
than random". Voluntary exit is the interesting one, because it is the target where the
sentence is most necessary and most deflating: "of the top 100, 78 to 85 had a strike-off
proposal filed, against a base rate of about 8%, roughly 10 times better than random". That
single sentence does the whole job the report's "read lift, not precision" argument does, and
it does it on screen where a banker will actually see it.

**Where the sentence should live.** Once it is scoped to the top 100 it is a statement about
the model, not about the company, so it belongs once at the foot of the panel next to the
existing disclaimer rather than repeated under every row. That also removes the temptation to
read it locally.

---

## Q7. Do we add a ranked view, and where?

**Answer: yes for lending, insolvency and growth; no for voluntary exit. And the server
already does it, so this is a frontend-only change.**

**The tie counts, which decide the scope:**

| Target | Distinct values in top 1000 | Companies tied at the rank-100 cut | Distinct scores overall |
|---|---|---|---|
| `lending` | **993** | **1** | 428,958 |
| `insolvency` | **961** | **1** | 451,527 |
| `growth` | **994** | **1** | 346,889 |
| `voluntary_exit` | **14** | **138** | 478,185 |

So the tie objection is a `voluntary_exit` objection, not a general one. For the other three
the top 100 is a single well-defined set of companies with a single company at the cut. My
"a global rank is stupid" position on the call was over-general: it is right for voluntary
exit and wrong for the other three. Vishal's separate argument, that a definitive call list
oversteps decision support, is a different point and still stands on its own merits, but it
should be argued as a product decision rather than as a data one, because the data supports
the list for three of four targets.

**Reconciling the three tie numbers we have all quoted for voluntary exit.** They come from
three different definitions and only one of them is wrong:

- **998**: rows in the top 1000 sharing their score with another row in the top 1000.
  `store_meta.json` uses this and it is **correct**.
- **986**: rows in the top 1000 not at the single most common value (1000 minus 14). Nobody
  quoted this, but it is the nearest thing to my "982" from the call, which I now think I
  simply misremembered.
- **138**: companies tied at the score sitting in 100th place. The README says 138 and it is
  **right**; `store_meta.json` says 139 and is off by one. Worth fixing since it is on screen.

For completeness, the modal score in the top 1000 carries 143 companies, at 0.914002.

**The ranked view already exists on the server and nothing calls it.** In `serve.py`:

```python
NUMERIC_FILTERS = {"score_lending", "score_insolvency", "score_voluntary_exit",
                   "score_growth", ...}
SORTABLE = NUMERIC_FILTERS | {"CompanyName", "CompanyNumber", "gaz_latest_notice_date"}
```

and `/api/browse` honours it:

```python
if request.args.get("sort") in SORTABLE:
    d = "DESC" if request.args.get("dir", "desc").lower() == "desc" else "ASC"
    order = f'ORDER BY "{request.args["sort"]}" {d} NULLS LAST'
order += TIE_BREAK
```

So `GET /api/browse?sort=score_lending&dir=desc&limit=100` returns a correct top 100 today,
with `NULLS LAST` keeping unscored companies off the head of the list and `TIE_BREAK`
(`, CompanyNumber ASC`) making the ordering total so pagination cannot lie. The frontend
simply never sends `sort`; `fparams()` only ever passes `limit` and `offset`.

**So the recommendation is the cheap option in the question list, and it is cheaper than we
thought:** a per-target sort control on the existing Home view. No new page, no new endpoint,
no re-export, no server change. One control, and an allow-list of three targets rather than
four so `score_voluntary_exit` cannot be selected. Excluding it is consistent with what the
dashboard already does, since voluntary exit is deliberately excluded from the score filters
for exactly this reason.

**Record the decision:** the report describes the shortlists as a deliverable, so with the
sort control the report and the dashboard agree without either changing its story.

---

## Q8. Do we ship the SHAP panel, and in what form?

**Answer: ship it, but not as "the top three reasons this company is here", because for three
of four targets that is not what it is. And coverage, not units, is the blocker.**

**The Q1.9 worry is confirmed and it is worse than I said on the call.** How often each
feature is reason 1, over the 5,000 companies per target in the handover extract:

| Target | Top feature as reason 1 | Share | Distinct features ever reason 1 |
|---|---|---|---|
| `lending` | `Mortgages.NumMortCharges` | **100.00%** | **1** |
| `voluntary_exit` | `accounts_stale_streak_months` | 92.52% | 5 |
| `insolvency` | `months_since_last_accounts_filing` | 80.98% | 6 |
| `growth` | `tier_rank` | 43.42% | 7 |

For lending it is not "nearly every company", it is **every single one of the 5,000**. And
reasons 2 and 3 do not rescue it: reason 2 is `segment` for 61.5% of them. For voluntary exit
it is worse still, with reason 2 being `confstmt_late` for 95.2%.

**Growth is the only target where the panel genuinely differentiates**: `tier_rank` 43.4%,
`Mortgages.NumMortCharges` 33.5%, `months_since_last_award` 15.5%, across 7 distinct
features. That matches what I noticed live.

This is not a defect in the SHAP work. It is §4.1.6's finding arriving on screen: lending is
a size-and-existing-debt story and the strongest signal for who borrows next is who has
borrowed before. The panel is faithfully reporting a real and slightly deflating fact.

**What follows for the design.** Do not label it "why this company is in your list", because
for lending that sentence is answered identically 5,000 times and a relationship manager will
notice by the third company. Two things do carry information even on lending, and they should
be what the panel leads with:

1. **The feature value, not the feature name.** "578 mortgage charges" against "3 mortgage
   charges" is the actual differentiator, and the value is already in the file.
2. **Reasons 2 and 3**, which is where what variety exists lives.

So: same feature name, different magnitude. A label like "What drives this score" is honest;
"why this company specifically" is not.

**Units.** Show direction and relative weight, not signed log-odds. A banker has no use for
+2.77 and, worse, three contributions that visibly fail to sum to the score on screen invite
exactly the arithmetic §4.1.6 warns against. Normalise the three contributions to shares of
their own absolute total and show an arrow for the sign. Keep the log-odds in the tooltip or
the info icon for anyone who asks.

**Coverage is the real blocker.** The extract is the top 5,000 per target, which is **0.35%
of the 1,409,284 scored companies**. Roughly 99.65% of company pages would show an empty
state. That is not a panel, it is a panel that is almost never there. Three options, in the
order I would take them:

1. **Restrict the panel to companies that have reasons, and say so.** Cheapest, honest, and
   it pairs naturally with the Q7 sort control, since the sorted top of the list is precisely
   where reasons exist. The panel then appears exactly where somebody is working a call list.
2. **Regenerate at a larger N.** The file costs about 13 bytes per row, so 50,000 per target
   is roughly 8 MB on disk, which is nothing next to the 64 MB spine under the current
   architecture. The cost is TreeExplainer compute, which needs measuring rather than
   guessing.
3. **Full coverage.** 1.4M x 4 targets x 3 reasons is about 17M rows. Storable, but I would
   not commit to the explainer runtime without measuring it first.

**Recommendation: option 1 now, option 2 if Vishal wants it after seeing it.** That keeps
his estimate at two days rather than opening a compute question.

**What Vishal needs from me if it is a go:** `data/handover/shortlist_reasons_2026-07.parquet`
(780 KB), plus a note saying the join key is `CompanyNumber` **plus** `target` (a company can
be in the lending top 5,000 and not the growth one), that `rank_within_reason` is 1 to 3,
that `contribution` is signed raw log-odds and must not be summed against `score`, and that
the load pattern is `load_aux()` the way Samuel's packs load. That note is the deliverable and
I owe it to him.

---

## Q10. Report and dashboard consistency

The rule from the call: if the report claims we have something useful and it is not in the
dashboard, we get asked why.

| Capability the report claims | In the dashboard? | Action |
|---|---|---|
| Four model scores per company, four targets | **Yes** | none |
| Per-target windows on screen (3/6/12m, dated) | **Yes**, and correct per Q3 | none |
| Scores absent for non-Active companies, with the reason rendered | **Yes**, `scorePanel` names the status | none |
| Bands rather than raw probabilities | **Yes** | none |
| Voluntary exit not offered as a ranked or banded filter | **Yes**, and for the documented reason | none |
| Precision@N per held-out month, never pooled | **Partially.** Per-origin, but the better month only, and narrated as if local | **Fix (Q5, Q9.3)** |
| Base rate and lift beside precision | **No.** Constants exist in `store_meta.json`, never shown | **Add (Q5)** |
| Top 100 ranked shortlists per target | **No** page, but the server supports it | **Add sort control (Q7)** |
| Per-company SHAP reasons, top three drivers | **No** | **Decide (Q8)** |
| Top-5,000 long-format reason extract | **No** | ships with Q8 |
| Scores are a "calibrated probability" | **Contradicted.** Dashboard says "not probabilities" | **Reword the report and README (Q1)** |
| §4.1.6 example: uncalibrated 0.972 / shipped 0.500 | n/a | **Correct to 0.9796 / 0.5772 (Q4)** |
| 398 unique companies across the four lists | n/a | confirmed, keep |
| Dashboard architecture as described in §3.7 | **Superseded** | rewrite from `drafts/dashboard-deep-dive-2026-08-25.md` (already a known item) |

**Nothing needs to come out of the report.** Every capability it claims either exists or is
one small change from existing. The corrections are all wording, plus the two numeric fixes.

---

## What I owe Vishal, filled in

1. **The window label, Q3.** He was right. The card is correct as written and needs no
   change. I will tell him so.
2. **The sentence for reading the model score, Q1.** "The model score is the estimated
   probability that the company does the thing in the stated window, corrected back to the
   true base rate after training. It is not a fitted calibration curve, so treat it as
   approximately right in the middle of the range and as a ranking near the top." His existing
   disclaimer is already compatible with this and does not need to change.
3. **Precision versus lift versus base rate, Q5.** All three, one sentence, at the foot of
   the panel: "Of the top 100 companies by this score, 41 to 43 took on new secured borrowing
   in the test months, against a base rate of 0.26%, roughly 150 times better than picking at
   random." Same shape for all four targets.
4. **SHAP, Q8.** Go, with the panel restricted to companies that have reasons, labelled "What
   drives this score" rather than "why this company", showing relative weights and the feature
   value rather than signed log-odds. Parquet plus the DuckDB note to follow from me.
5. **The ranked view, Q7.** Yes, as a per-target sort control on Home, limited to lending,
   insolvency and growth. No server work needed; `/api/browse` already accepts
   `sort=score_lending&dir=desc`.

**Plus three defects he did not know about, in priority order:**

- **The "43 in 100 at this level" sentence is rendered for every company in every band**
  (Q9.3). It overstates the figure by about 170x on a median lending company. One-line fix.
- **`store_meta.json` shows the better of the two held-out months** for all four targets, and
  its lending `lift: 160` matches neither the measured 167 and 144 nor the README's 150 (Q9.2).
- **`store_meta.json` says 139 companies tied at the voluntary-exit cut; it is 138** (Q7).

**And two of my own to fix before anything else is sent out:**

- `reports/shortlists/README.md` calls the score a calibrated probability and uses 0.43 as
  the worked example, which is precision@100 and not a score. Sam and Vishal both have this
  file. This is very likely the origin of the whole Q1 confusion.
- `drafts/report/04-1-modelling-evaluation.md` §4.1.6 quotes the wrong uncalibrated/shipped
  pair.

---

## How this was checked

Everything above is reproducible from the repository. The working scripts are in the session
scratchpad and the substantive ones are worth keeping if we want them in the report:

- **Reliability curves (Q1):** rebuilt the held-out test origins from
  `data/processed/eval_matrix/`, scored with the pickled models in
  `data/processed/run_stage/refactor_growthfix/`, applied `train.recalibrate`, binned by
  decile and by absolute score band against realised outcomes.
- **Shortlist reproduction (Q6):** `nlargest(100)` on
  `scores_refactor_growthfix_2026-07.parquet`, diffed against the shipped CSVs.
- **Score plumbing (Q9.1):** full outer join of the handover parquet against the source
  scores parquet on `CompanyNumber`, all four columns.
- **Tie counts (Q7), reason concentration (Q8), per-origin metrics (Q5):** direct reads of
  the scores parquet, `shortlist_reasons_2026-07.parquet`, and
  `data/processed/run_stage/refactor_growthfix/result_*.json`.
- **Dashboard behaviour (Q2, Q5, Q7, Q9.2, Q9.3):** read from `origin/vishal/dashboard`,
  `dashboard/serve.py` and `dashboard/index.html` at commit `8ebeef6`.

One environment note for whoever runs these next: the `.venv` in the repo had only duckdb,
pandas, numpy and pyarrow installed. `requirements-frozen.txt` restores the rest, which is
what the modelling code needs.
