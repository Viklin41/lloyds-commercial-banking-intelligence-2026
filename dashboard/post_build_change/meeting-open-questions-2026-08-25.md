# Dashboard review call with Vishal, 25 August 2026

Two things this file is for. First, so I can see in one place every question we
opened and did not close. Second, so I can point a Claude Code session at it and
have it walk the repo and answer them, which is why every question below has a
"how to answer it" block with concrete files to open. Part 3 is the running
order for that.

**The freeze we agreed on:** Vishal does not touch the dashboard until I have
verified the numbers. He said it twice, I said it twice. So nothing in Part 2 is
a work item for him yet, it is a verification list for me.

---

## 1. What we actually checked in the call

### 1.1 The dashboard is fed from the July 2026 bulk file

Confirmed with him directly. He builds from
`data/handover/dashboard_bulk_2026-07.parquet`. It was originally a JSON export,
but once we agreed to show all ~1.5M companies rather than a sample, he moved it
into DuckDB and the front end hits JSON endpoints backed by queries. The join key
everywhere is `CompanyNumber`, which matches what the handover doc assumes.

### 1.2 The four views, and the one from the original design that is missing

Present: all-company view (he calls it Home), individual company view (opens when
you click a company name), market view (he calls it Analytics). The fourth one
from our original sketch, the model and rank view, does not exist as a page. His
position is that it is already embedded in the company page, since the model
scores are shown there. My point was that this covers the per-company read but
not the "give me the top 100 companies for lending" read, which is a different
question. Unresolved, see Q7.

### 1.3 Home page sorting is alphabetical

Ascending by name. He checked his own notes live on the call and confirmed. There
are secondary orderings for the Gazette field (non-insolvent first, insolvent
last) and for the LBG relationship field (former LBG customer first). There is no
score-based sort anywhere. He thinks there used to be a "still trading" sort and
that it is no longer active.

### 1.4 What is global on the model score card versus what is company specific

This one we did settle, and it matters for reading everything else. The 43-in-100
figure is a **global** number. It is the same on every company page you open. The
numbers that are actually about the company you are looking at are the model score
and the top x% position. Vishal and I agreed on this explicitly.

### 1.5 Precision@N is not base-rate aware, and I already handle that in the report

I walked him through it. Precision@100 for voluntary exit is around 85 out of 100,
and that is not because the model is good, it is because voluntary exit happens a
lot. Lending is near 0.26% base rate and so its precision is doing far more work
for far less credit. In the report I show precision@N divided by the base rate,
the lift, which for lending comes out around 150x better than picking at random.
He accepted the reasoning. What we did not decide is what the dashboard should
show, see Q5.

### 1.6 Why insolvency and voluntary exit are shown as bands and not numbers

His reasoning, which I think is right: the score is not a calibrated probability,
so putting a number in front of a banker invites them to act on it as if it were
one. A band says "this company sits in this group" without pretending to a
precision we do not have. He also gave the concrete reason: `score_voluntary_exit`
has 982 exact ties in its top 1000 values, so any ordering inside that band is
arbitrary. This matches what is already written in
`reports/dashboard_handover_columns.md`. Good call on his part, and I said so.

### 1.7 Correction he made mid-call about the model score card

He came in believing the number on the card was the precision figure. Partway
through the call he corrected himself: the card is showing the raw model output,
not precision. He then described lending as "event is taking on new secured
borrowing, horizon 3 months, window August to October 2026, base rate 0.227%,
score 0.004, roughly 1.5x the average company". So both readings were live in the
same conversation, which is exactly why Q1 needs closing properly.

### 1.8 The shortlists and the SHAP reasons exist, and are not in the dashboard

I showed him `reports/shortlists/`. He had not seen them because I never sent
them. He can add a SHAP panel to the model score card and estimates about 2 days
including his own report writing. Fernando specifically asked about SHAP, and we
currently have none of it in the dashboard, which is the main reason to do it.

### 1.9 A shape problem in the SHAP reasons that I noticed live

Scrolling the lending reasons file, nearly every company is driven by the same
feature, the mortgage charge count. That makes the lending explanations close to
useless as *explanations*, since they all say the same thing. Growth is more
varied, one company's top driver was months since last accounts filing rather than
mortgages. Worth knowing before we ship a panel that promises per-company reasons.

### 1.10 The ties problem, and why I now think a global rank is a bad idea

With 1.4M companies and heavy score ties, "rank 1" is not one company, it can be
thousands of companies sharing a score. I said on the call that I think a single
global rank is stupid for that reason. Per-target top 100 lists are a different
thing and those do exist. Vishal's counter-argument, which I like, is that a
definitive ranked call list turns the dashboard from a decision-support tool into
a "call this company" instruction, and he would rather we describe the ranking in
the report than ship it as an answer.

### 1.11 A worry I raised about how the top 100 were built

I said out loud that I was afraid I had asked Claude to build a top 100 and it had
sampled 100 companies and then ranked those, which would make the list worthless.
I then found the README, which says otherwise. I have not verified the README
against the code. See Q6.

---

## 2. Open questions

The first five are the ones I wrote down from memory right after the call. The
rest came out of re-reading the transcript.

---

### Q1. How do we read the company-specific number on the MODEL SCORE card?

When I say "this company has 0.577 on lending", does that mean a 57.7% chance of
lending? If so, what is the other 42.3%? Is this a logistic model or something
else, and what does the model type imply for how the number should be read?

State of play: Vishal first said it was precision, then corrected himself to
"uncalibrated likelihood, raw model output". Meanwhile
`reports/shortlists/README.md` states in writing that `score` is a calibrated
probability and that 0.43 means roughly a 43% chance. Those two claims cannot both
be right, and one of them is in a file I already sent to Sam and Vishal.

**How to answer it**
1. Open `src/models/train.py`. Find the estimator. Line 632 constructs an
   `lgb.LGBMClassifier`, so confirm whether LightGBM is what actually produces the
   shipped scores or whether a logistic baseline is what feeds the dashboard file.
2. Read `train.recalibrate` (around line 958). Its docstring says it undoes
   negative downsampling by multiplying the odds by the keep rate. Establish
   clearly that this is a **downsampling correction**, not a probability
   calibration in the Platt or isotonic sense. Confirm there is no
   `CalibratedClassifierCV`, `IsotonicRegression` or sigmoid calibration anywhere
   in the modelling path.
3. Trace which exact column lands in `data/handover/dashboard_bulk_2026-07.parquet`
   as `score_lending` and friends, and whether the value written is pre- or
   post-`recalibrate`. Start from `notebooks/20_dashboard_handover.ipynb`.
4. Write the one-sentence reading of the number that survives all of the above,
   plus what the complement means. If it is a downsampling-corrected LightGBM
   probability with no calibration curve fitted, then the honest reading is
   "monotone score with probability-like units", and 1 minus the score is not a
   meaningful "chance it does not happen".
5. Produce evidence rather than an assertion: bin the July 2026 scores into
   deciles, and if we have any month with realised outcomes, plot predicted versus
   observed rate. That reliability curve settles it either way.
6. Flag the README claim explicitly. If it is wrong, it needs correcting and Sam
   and Vishal need telling, because they have the file.

---

### Q2. How do we read the "Top x%" shown per company per target?

Top x% of what population, computed how, and does it mean the same thing for a
target whose scores are mostly ties?

**How to answer it**
1. Find where the percentile is computed. Check whether it exists as a column in
   `dashboard_bulk_2026-07.parquet` or whether Vishal derives it in DuckDB at
   query time. `reports/dashboard_handover_columns.md` is the reference for what
   we shipped him.
2. Establish the denominator: all 1,531,094 rows in the file, or the 1,409,284
   active companies that were actually scored. Those give different percentiles
   and the handover doc notes the file includes non-Active companies.
3. Establish the tie-handling rule. With 982 exact ties in the top 1000 of
   voluntary exit, "top 1%" is either meaningless or needs a stated convention.
   Check what pandas or DuckDB rank method is in play and what it does to ties.
4. Decide the wording for the card. "Top 1% by model score among 1.4M active
   companies at July 2026" is defensible. "Top 1%" alone is not.

---

### Q3. Is the 3/6/12 month window only a training construct, or is it really the window being predicted?

The card says lending, 3 months, August to October 2026. Two readings:
**A)** the company lends in August 2026, or
**B)** the company lends at some point in the three months from August 2026.
I argued on the call it was A and that the window is a training artefact. Vishal
described it as B. One of us is wrong and it changes the card's label.

**How to answer it**
1. Open `notebooks/15_targets.ipynb` and the target construction in
   `src/models/targets.py`. Find how the label is defined at an origin month.
2. The decisive question: is the label `event occurs in month t+1`, or
   `event occurs at any point in months t+1 through t+h`? Look for the horizon
   parameter and whether it widens the label window or only shifts it.
3. Confirm the same horizon logic is applied at scoring time, in
   `train.load_scoring_frame` and the scoring stage that writes
   `data/processed/scores/scores_refactor_growthfix_2026-07.parquet`.
4. Check the four horizons individually, since lending is 3m, insolvency and
   voluntary exit are 6m, growth is 12m, and confirm each behaves the same way.
5. Sanity check the arithmetic on the label too. July 2026 origin plus a 3 month
   forward window is August to October 2026, which is what the card says, so if
   reading B holds the card is already right and I owe Vishal a correction.
6. Cross-check against `reports/dashboard_handover_columns.md` lines 260 to 263,
   which state the windows as Aug-Oct 2026 (3m), Aug 2026-Jan 2027 (6m) and
   Aug 2026-Jul 2027 (12m). If those are right, that is reading B and the
   question is settled by our own handover doc.

---

### Q4. Where do the shortlist files and the top-5,000 long-format extract actually live?

The report claims both exist. I need the paths so I can (a) verify the claim and
(b) send them to Vishal.

Already located while writing these notes, so this one is mostly confirmation:

**a) The shortlists**, in `reports/shortlists/`:
- `top100_{lending,insolvency,growth,voluntary_exit}_2026-07.csv`, columns
  `rank, CompanyNumber, CompanyName, score`
- `top100_{target}_2026-07_reasons.csv`, the sibling reason files, columns
  `rank, CompanyNumber, CompanyName, score` then `reason_N, contribution_N,
  value_N` for N in 1..3
- `README.md` explaining provenance
- built by `scripts/make_shortlists.py` and `scripts/make_shortlist_reasons.py`

**b) The long-format top-5,000 extract**:
`data/handover/shortlist_reasons_2026-07.parquet`, 780 KB, written at the end of
`make_shortlist_reasons.py` main() from `--n-handover`, default 5000, per target,
long format with the `rank` column dropped.

**How to finish it**
1. Read the parquet and confirm the row count is 4 targets x 5000 companies x 3
   reasons = 60,000, and confirm the column names.
2. Check the report prose in `drafts/report/04-1-modelling-evaluation.md` against
   what is actually in the files, in particular the MS LENDING GROUP LIMITED
   example: 578 mortgage charges at +2.77 log-odds, eleven new charge events at
   +0.92, Large segment at +0.86. Grep the reasons CSV for that row.
3. Confirm the report's caveat is accurate, that `TreeExplainer` returns raw
   log-odds so the three contributions sum toward the uncalibrated logit and not
   toward the `score` column. The script docstring says exactly this, so this is a
   consistency check between prose and code.
4. Note the size for Vishal: 780 KB against the 11 MB browser store he already
   has, which is the number that decides whether this is a drop-in.

---

### Q5. On the dashboard, do we show precision@N, base rate, lift, or a combination?

Right now the card shows the precision figure, 43 out of 100 for lending, 16 for
another target, and nothing for insolvency and voluntary exit because their base
rates make precision meaningless. I argued lift is the fairer number. Vishal's
current display is not obviously wrong. We did not decide.

**How to answer it**
1. Pull the actual numbers for all four targets, per origin, not pooled. They are
   in `data/processed/run_stage/refactor_growthfix/result_{target}.json` under
   `metrics_by_origin`, and `scripts/make_shortlists.py` already has a helper
   (`per_origin_hit_rate`) that reads exactly this.
2. Note the trap already documented in that script: pooled precision@N is not an
   average of its months and falls outside their range in 9 of 12 rows. So
   whatever we display must be the per-origin figure or an honestly labelled
   summary of it, never the pooled one.
3. Lay the three candidate numbers side by side per target: base rate,
   precision@100, lift@100. Then judge which combination a relationship manager
   reads correctly without a footnote.
4. My provisional preference, to be tested against the numbers rather than
   assumed: show all three as one sentence, "43 of the top 100 were right, against
   a base rate of 0.26%, which is 150x better than random". Precision alone
   flatters the high-base-rate targets; lift alone is abstract; the base rate makes
   both legible.
5. Whatever we choose, apply it consistently across all four targets, including
   the two that currently show nothing.

---

### Q6. Were the top 100 shortlists built from the full scored population or from a sample?

This is the fear I voiced on the call. If the list is a sample of 100 that was then
sorted, it is worthless.

**How to answer it**
1. Read `scripts/make_shortlists.py` end to end. The docstring already says the
   list comes from the scoring stage applied to the most recent snapshot, and the
   README says it covers 1,409,284 active companies at July 2026. Verify the code
   does what the prose says.
2. Reproduce it independently: load
   `data/processed/scores/scores_refactor_growthfix_2026-07.parquet`, count the
   rows, take the top 100 by score for lending, and diff against
   `reports/shortlists/top100_lending_2026-07.csv`. If they match, the worry is
   dead.
3. While there, verify the disjointness claim: 398 unique companies across the 400
   rows, with two companies appearing in both lending and growth. I quoted 399 on
   the call, the README says 398, so one of those is wrong.

---

### Q7. Do we add a ranked view to the dashboard at all, and if so where?

Options that came up: a new page; a sort control on the existing Home view; extra
columns on an existing view; Vishal's toggle sketch next to the view switcher that
opens a top-100 list. Against all of them: the tie problem, and Vishal's argument
that a ranked call list oversteps what a decision-support tool should do.

**How to answer it**
1. Quantify the ties per target before arguing about UI. For each of the four
   score columns, compute how many distinct values exist in the top 1000 and how
   many companies sit at the modal top score. We know voluntary exit is 982 of
   1000 tied. If lending has 1000 distinct values in its top 1000, then a lending
   top-100 list is perfectly well defined and the tie objection only applies to
   some targets.
2. Let that decide scope. It may well be that lending and growth support a ranked
   list and insolvency and voluntary exit do not, which is the same split we
   already made for numbers versus bands.
3. Only then pick the UI. If it goes ahead, the cheapest version is a per-target
   sort on the existing view, since the score columns are already in the parquet
   and DuckDB can order by them without any new export.
4. Record the decision either way, because the report currently describes the
   shortlists and the report and the dashboard need to agree.

---

### Q8. Do we ship the SHAP panel on the company page, and in what form?

Fernando asked about SHAP. We have none in the dashboard. Vishal estimates 2 days
including his report work and is willing. The design I described: under the model
score card, per target, the top three drivers with feature name, value and signed
contribution, behind a dropdown or the same info-icon pattern he already uses in
Analytics.

**How to answer it**
1. Decide the units question first, because it determines the label. Contributions
   are raw log-odds and do not sum to the displayed score. Either we show them as
   relative importances without units, or we show signed log-odds with an
   explanation. The former is probably right for a banker.
2. Test the Q1.9 usefulness problem quantitatively before committing. From
   `data/handover/shortlist_reasons_2026-07.parquet`, compute per target how often
   each feature appears as reason 1. If mortgage charge count is reason 1 for
   nearly every lending company, the lending panel tells the user nothing and we
   should say so, or show reasons 2 and 3 more prominently, or restrict the panel
   to the targets where the drivers vary.
   `make_shortlist_reasons.py` already prints a version of this count at build
   time, so the code to do it exists.
3. Decide coverage. The extract is top 5,000 per target. Companies outside that
   have no reasons, so the panel needs a defined empty state, or we regenerate at
   a larger N and check the size cost against the 11 MB budget.
4. If it is a go, hand Vishal
   `data/handover/shortlist_reasons_2026-07.parquet` plus a short note on the join
   (`CompanyNumber` plus target) and the units caveat. I promised him a written
   how-to based on how he already wired DuckDB, so that note is the deliverable.

---

### Q9. Which exact column is the card reading, and does it match the source file?

We did a live spot check that mostly passed and is worth completing properly. I
had him search two companies. The growth score he read off the dashboard for one
of them, 0.049, matched what I had in my file. So the plumbing looks right.

**How to answer it**
1. Take 5 to 10 companies spanning the score range, not just the two we happened
   to check, and compare all four scores in
   `data/handover/dashboard_bulk_2026-07.parquet` against what the dashboard shows.
2. Check the precision figures the card shows against the run JSONs. I matched 43
   for lending and 16 for another target by eye on the call; do it properly for
   all four.
3. Confirm the row count the dashboard reports. I have said 1.5 million, 1.53
   million and 1.4 million at different points. The handover doc says 1,531,094
   rows in the file and the shortlist README says 1,409,284 active companies
   scored. Both can be true, and the card needs to be clear which population it is
   describing.

---

### Q10. Report and dashboard consistency

The rule I stated on the call: if the report claims we have something useful, and
it is not in the dashboard, we get asked why. So either it goes in the dashboard
or it comes out of the report.

**How to answer it**
1. Go through `drafts/report/` and list every capability the report claims we
   deliver: shortlists, SHAP reasons, lift, rankings, the per-target windows.
2. Mark each as in the dashboard, not in the dashboard, or partially.
3. For each gap, decide add to dashboard or reword the report, and record it.
4. Do this last, once Q1 to Q9 are settled, because the answers change what the
   report should say.

---

## 3. Running order

Not the order the questions are numbered in. This is the order that avoids
redoing work, since the later answers depend on the earlier ones.

1. **Q3** (the window). Cheapest, purely a code read, and it changes a label that
   is on screen right now.
2. **Q1** (what the score means). Everything about how we present the card depends
   on this, and it has a documented contradiction to resolve.
3. **Q6** (how the shortlists were built). Fast, and if the answer is bad it
   invalidates Q4, Q7 and Q8 in one go.
4. **Q2** (the top x%) and **Q9** (column and value verification). Same
   investigation, do them together.
5. **Q4** (locate and verify the artefacts). Mostly done above, needs confirming.
6. **Q5** (precision, base rate or lift) and **Q7** (ranked view). Both need the
   tie counts and the per-origin metrics, so do the number pulling once.
7. **Q8** (ship SHAP or not). Depends on Q1 for units and Q4 for the files.
8. **Q10** (report and dashboard consistency). Last, by construction.

## 4. What I owe Vishal when this is done

- A yes or no on the window label, Q3.
- The correct sentence for reading the model score, Q1.
- The decision on precision versus lift versus base rate, and the exact wording
  for the card, Q5.
- The SHAP go or no-go, and if go, the parquet plus a DuckDB-flavoured how-to,
  Q8.
- The ranked view decision, Q7.

Until all of that lands, the dashboard stays frozen, which is what we agreed.