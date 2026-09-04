# Steps 5 and 6: what they are and how to start

Written at the end of step 4b, before any modelling code exists. This is my orientation note for
the next session, so it assumes no context beyond the repo.

**Where we are.** Steps 1 to 4b are done: a 33-month company-month panel (49.6M rows,
`data/processed/panel/`), 25 backward-looking delta features (`data/processed/panel_deltas/`), and
two contract feature sets, strict and name-matched (`data/processed/contracts_asof/` and
`contracts_asof_ext/`). What does not exist yet: any label, any model, or `src/models/`.

Everything below has features. Nothing below has a target. That is the gap steps 5 and 6 close.

---

## 1. Steps 5 and 6 in plain terms

**Step 5 is labels. Step 6 is models.**

That is the whole distinction, and it is worth holding onto because they fail in different ways.

**Step 5: write down what happened next.** Right now every row of the panel says what a company
looked like in a given month. Step 5 stands in month `t`, looks *forward* in the same panel, and
writes down whether the thing we care about happened. Did it take on a new charge in the next three
months? Did it go into liquidation within six? Did it move up a size band within twelve?

The output is a small table: one row per (company, origin month), with a handful of 0/1 columns.
The features come from month `t`, the labels come from `t+1` onwards, and **never from `t` itself**.

This is what the master plan means by "self-labelling". We do not need anyone to tell us who is a
good prospect, because the future of the panel already says so. That is only possible because we
have a time series, which is the entire reason steps 1 to 3 existed.

**Step 6: try to predict those labels.** Join the features to the labels, split into train and
test, fit models, measure whether they work, explain them with SHAP, and score the latest month to
produce an actual ranked list of companies.

If I want one line to remember: **step 5 decides what "good" means, step 6 tries to predict it.**
Getting step 5 wrong is much worse, because a model that predicts the wrong thing perfectly is
still useless.

---

## 2. Which step handles the train/test split

**Step 6 performs the split, but step 5 is what makes a legitimate split possible.**

Step 5 fixes two things that the split depends on entirely: the **origin months** (which months we
stand in) and the **horizon `H`** (how far forward each label looks). Without those there is no
notion of "before" and "after" to split on.

Then step 6 does the actual splitting, and it must **not** be a random split. Two rules:

1. **Out of time.** Train on early origin months, test on late ones. This is the primary split
   because it mirrors reality: in production the model is always predicting a future it has not
   seen.
2. **Embargo gap of at least `H`.** Leave a gap between the last training origin and the first test
   origin, at least as wide as the horizon. Without it, a training row from month `t` has a label
   that resolves at `t+H`, which may land *inside* the test window. The model would be trained on
   the answer to its own exam.

As a secondary check, run GroupKFold grouped by `CompanyNumber`. If out-of-time and grouped CV give
similar numbers, the model generalises. If grouped CV is much better than out-of-time, the model is
learning something about this particular period that will not survive.

### Why `train_test_split` is wrong here

Sneha's baseline notebook uses `train_test_split(X, y, test_size=0.25, stratify=y)`. That is the
right call for the cross-sectional problem she set up, and the wrong one for ours, in two
independent ways:

- **Company leakage.** Each company appears in up to 33 monthly rows. A random split puts some of
  those rows in train and others in test, so the model can memorise the company rather than learn
  the pattern. Test scores come out flattering and mean nothing.
- **Time leakage.** A random split mixes 2026 rows into training while testing on 2024 rows. The
  model gets to see the future.

Either one alone invalidates the evaluation. This is the single biggest difference between what
steps 5 and 6 do and what the existing baseline notebook does.

---

## 3. What I actually do in each step

### Step 5, concretely

Create `src/models/targets.py` and a notebook to drive it. Four labels, all "Active at `t`, then
what":

| index | label | horizon | measured base rate |
|---|---|---|---|
| Lending Readiness | `Mortgages.NumMortCharges` increases | 3m | **0.25 - 0.31%** |
| Credit Risk Exposure | enters liquidation / administration / receivership / voluntary arrangement | 6m | **0.32 - 0.41%** |
| Voluntary Exit (strike-off) | status becomes "Proposal to Strike off" | 6m | **3.4 - 3.8%** |
| Growth Signal | size band moves up | 12m | **2.3 - 2.4%** |

I measured all of these on the panel at quarterly origins from 2024-01 to 2025-01. They are stable
across origins, which is good news for the out-of-time split: no drift to explain away. **Use them
as the assertion in step 5.** If a label comes out at 20%, it is wrong.

> **Two corrections from later work, left here rather than rewritten** (26 Jul 2026).
>
> 1. The strike-off label was called **Attrition** throughout this note and is now **Voluntary
>    Exit**. Lloyds uses "attrition" for a client switching to a competitor; a struck-off company is
>    not a relationship to win back. Real attrition needs lender identity, which the bulk file does
>    not carry, and is being built from the Charges API in `src/features/charges.py`. See
>    `reports/client-requirements.md`.
> 2. The **3.4 - 3.8%** above is the strike-off *state* at `t+6`. `targets.py` labels the *event*
>    anywhere in `t+1 ... t+6` and measures **6.7 - 8.5%**. Both are correct; proposals are routinely
>    withdrawn once a company files its overdue accounts, so "ever proposed" is about twice "still
>    proposed". The event definition is the one that shipped. Notebook 15 verifies the reconciliation
>    (3.49% state vs 7.16% event at the 2024-01 origin).

Then: pick quarterly origins (this makes the 3-month lending windows non-overlapping, so each
company-quarter is an independent observation rather than fifteen near-copies), join
`panel_deltas` + `contracts_asof` to the labels, and sample: keep every positive, downsample
negatives to roughly 10x. **Write down the sampling rate**, because step 6 has to undo it.

#### Two label traps I already hit while measuring

**Trap 1: "non-Active" is not distress.** The master plan originally defined the distress label as
"Active at `t`, non-Active by `t+H`". That runs at 3.6 to 4.1%, but roughly **90% of it is voluntary
strike-off**: dormant micro-companies quietly closing. That is not a credit event and no bank cares
about it in a risk model. Filtering to genuine insolvency drops the rate to 0.34%, which is both
more meaningful and exactly where the plan predicted a real distress rate should sit.

I decided to model **both**, separately: insolvency as Credit Risk Exposure, strike-off as a
voluntary-exit signal. They are different questions with different audiences, and mixing them into one
label would have let the loud one drown the important one.

**Trap 2: `segment` is not a size ladder.** The plan's growth label says "size tier moves up", but
the `segment` column mixes actual sizes with filing states:

```
Micro 563,377 | Small 406,255 | No Filings 338,047 | Dormant 181,186
Large 30,726 | Subsidiary 9,448 | Medium 2,026 | Unknown 25
```

Naive "segment changed" is 13.1 to 13.7% at 12m, and most of that is `No Filings` <-> `Micro`
churn, which is a filing event and not growth. The fix is an explicit rank:

```
Dormant(0) < Micro(1) < Small(2) < Medium(3) < Large(4)
```

with `No Filings`, `Subsidiary` and `Unknown` left unranked and excluded from the label rather than
squeezed in somewhere. That gives a 2.3 to 2.4% upgrade rate on the ~72% of active companies that
have a size at all. Sensible, learnable, and it means what it says.

### Step 6, concretely

1. Split out of time with the embargo, as above.
2. Train two models per target: a **logistic regression** as an interpretable floor, and
   **LightGBM** as the real model.
3. Evaluate with **precision@top-N** (N = 100, 500, 1000) as the headline, plus ROC-AUC and PR-AUC.
   Precision@top-N is the honest business metric here: a relationship manager works a finite call
   list, so "of our top 500 picks, how many were right" is the question that matters. AUC over 1.5M
   companies does not answer it.
4. **Recalibrate probabilities back to the true base rate.** Downsampling negatives inflates every
   predicted probability. Skip this and the ranking is still fine but the numbers are lies.
5. SHAP via `TreeExplainer` on a stratified ~100k subsample. Exact and fast for trees.
6. Score the latest partition filtered to `is_active`, rank, and enrich only the top few hundred
   using the existing `src/features/ch_api.py`. Score wide and cheap, enrich narrow and expensive.

**Why the logistic regression is worth the extra twenty minutes:** it is a floor. If LightGBM
cannot clearly beat a regularised linear model on the same features, the gradient boosting is not
earning its complexity and I should say so. It also gives signed coefficients, which are an
independent check that the SHAP directions are economically sensible. If SHAP says more charges
means more distress and the logit coefficient says the opposite, something is wrong.

---

## 4. After the baseline: is LIME the next move?

Short answer: **no, and the question has a false premise worth clearing up.**

LIME (Local Interpretable Model-agnostic Explanations) is **not a model or a training framework**.
It is a post-hoc explainer, the same category of tool as SHAP. You do not "train on LIME". You
train a model, then use SHAP or LIME to explain it. Swapping one for the other would not change a
single prediction.

And for our case SHAP is strictly better:

- We are using tree models, and SHAP's `TreeExplainer` is **exact** for trees and fast. LIME
  approximates by fitting a little local surrogate model around each prediction.
- LIME is **unstable**: it samples randomly around a point, so re-running it can give different
  explanations for the same company. That is a bad property when the explanation is going in front
  of a relationship manager.
- SHAP values are additive and sum to the prediction, which is exactly what I need to decompose a
  composite index into contributions.

The repo is already built around SHAP and that was the right call. LIME is at best a spot-check on
a handful of companies, not a direction.

### What actually moves the needle, in priority order

1. **Calibration.** Not optional. After downsampling, predicted probabilities are wrong and any
   threshold or "X% chance of insolvency" statement is meaningless until they are corrected.
2. **The strict vs extended contract A/B.** Already set up in step 4b: two directories, identical
   schema, one-line switch. Train each target on `contracts_asof/`, then re-run with
   `contracts_asof_ext/`, and compare out-of-time AUC. This finally answers whether the 1.55x
   coverage was worth the ~8% matching noise. My guess is it helps lending and does nothing for
   insolvency, but that is a prediction to test.
3. **The composite indices.** This is the real deliverable and the thing the project charter
   actually promises. The four model scores become **Lending Readiness**, **Credit Risk Exposure**
   and **Growth Signal**, with per-company SHAP reasons attached so the output is "this company,
   this score, and here are the three things driving it" rather than an unexplained number.
4. Only then: hyperparameter tuning, more features, better horizons. Ordinary iteration.

Note that a model is not needed for every index. Lending Readiness and Growth Signal map cleanly to
the lending and growth models. Credit Risk Exposure is best read as the insolvency model, with the
voluntary-exit model kept beside it rather than blended in.

---

## 5. How useful is `notebooks/12_baseline_model.ipynb`?

I read it properly. Verdict up front: **the modelling scaffolding is worth mirroring, the data
foundation is not.**

Two things to know before judging it. First, it has **zero stored outputs** in all 17 cells, and its
input file `data/processed/shap_feature_matrix_with_insolvencies.parquet` **does not exist in this
repo**. So it has never run here and there is no evidence of what it scored. Second, it is built on
`shap_feature_matrix.parquet`, the single-snapshot artefact from notebook 10, patched to re-include
insolvent firms. It is cross-sectional: no time dimension, no horizon, no origins.

That framing is the crux. Her model answers **"who is insolvent right now"**. Steps 5 and 6 answer
**"who will become insolvent in the next six months"**. Those are different questions, and only the
second one is useful for prospecting, because by the time a company is in liquidation there is no
lending decision left to make.

So my scepticism was justified about the dataset. But the notebook is genuinely useful in parts.

### Reuse

- **`is_insolvent`, the status mapping.** This is the most valuable thing in the notebook and I am
  taking it wholesale. It enumerates which `CompanyStatus` values are real insolvency (liquidation,
  administration, receivership, voluntary arrangement) as opposed to strike-off or dormancy. My own
  measurement above proves the point: without this distinction the distress label is 90% noise. Do
  not rebuild this from scratch, and do credit it.
- **The evaluation harness shape.** ROC-AUC + PR-AUC + precision@k, tabulated per model with the
  base rate alongside. Good structure. Her `prec_at_k` uses a percentage; I am switching to absolute
  top-N for the reason in section 3, but the function is three lines either way.
- **Logistic regression as an interpretable floor next to a boosted model.** Good instinct, and I
  am keeping it.
- **`class_weight="balanced"` / `sample_weight`** as an alternative to downsampling negatives. Worth
  remembering as a fallback if the downsampling ratio proves awkward.

### Adapt, do not copy

- **Her leaky-feature exclusion list does not transfer**, and this is a subtle one. She deliberately
  drops `accounts_overdue`, `accounts_stale` and `financial_health_concern` because they are
  *symptoms* of insolvency: in a cross-sectional model, a company that has stopped filing is already
  in trouble, so those features leak the answer.

  In our panel that reasoning inverts. `accounts_overdue` at month `t` predicting insolvency at
  `t+6m` is not a symptom, it is a **leading indicator**, and notebook 13a already showed it
  separates hard (non-Active companies are overdue ~61% of the time with a ~13 month average streak,
  versus ~2% and near-zero for active ones). **Keep those features.** The time structure is exactly
  what converts them from leakage into signal.

### Do not copy

- **`train_test_split(..., stratify=y)`.** See section 2. Both company leakage and time leakage.
- **The cross-sectional label.** No horizon means no prospecting use.
- **Hardcoded `C:/MSC/Project/...` paths.** Same problem as notebooks 5 and 6 had.
- **The 10-column static feature set.** Superseded by ~25 delta features plus contract features.
- **The `%pip install` cell pinning `numpy<2` and `pyarrow<16`.** That was for her conda env; our
  `.venv` already has what it needs and the pins would break duckdb.

---

## 6. Starting checklist for the next session

1. Create `src/models/targets.py`. Lift `is_insolvent` from notebook 12, add the ordinal segment
   rank from section 3.
2. Write the four label definitions against `data/processed/panel/`, at quarterly origins.
3. **Assert the base rates match the table in section 3.** This is the cheapest possible check that
   the labels mean what I think, and it catches almost every labelling mistake.
4. Assemble the modelling matrix: `panel_deltas` LEFT JOIN `contracts_asof` on
   `(CompanyNumber, snapshot_date)`, coalescing the contract counts and flags to 0 and leaving
   `months_since_last_award` NULL. `contracts.ASOF_COALESCE_ZERO` lists exactly which columns take a
   zero.
5. Sample: all positives, negatives to ~10x. Record the rate.
6. Only then move to step 6 and the split.

### Things already known that will bite if forgotten

- **The last two panel months (2026-06, 2026-07) are censored for contract features.** The Find a
  Tender bulk file stops at 2026-06-05 while Contracts Finder runs to 2026-07-03. Fine to score on,
  not fine to train on. `contracts.harvest_watermark()` returns the cutoff.
- **June 2025 does not exist.** Any label horizon that lands on it must be NULL, not silently
  shifted. The delta features already handle this on a calendar spine; the label code needs the same
  care.
- **`total_value_won_12m` is dominated by framework ceilings.** 2,767 awards priced at £1bn or more
  hold 95% of all contract value, because OCDS stamps a framework's whole lifetime ceiling on every
  appointed supplier. Fine as an ordinal feature for LightGBM, not fine to quote as revenue.
- **Filter fuzzy-matched contract rows out of anything RM-facing.** `match_method = 'coh'` only. A
  model can absorb 8% noise; a phone call about a contract the company never won cannot.
