# Model runs

One directory per run of `notebooks/16_shap_models.ipynb`. A run is the combination of a
**matrix**, a **feature set** and a **model set**, named by its tag, and it is written by
`train.record_run`, which refuses to overwrite an existing tag.

```
<tag>/manifest.json                 how the run was configured
      metrics.json                  what came out
      shap_importance_<target>.csv  one per target
index.csv                           one row per run x target x model, regenerated on every write
```

`manifest.json` is what makes a run auditable without reading code: matrix and eval
directories, contract and lender sources, the exact feature list plus a short hash of it, the
categoricals, the targets, the model set, the registry as it stood, the LightGBM parameters,
the git commit and the timestamp.

Reading them back:

```python
from src.models import train

train.load_runs()                              # every run, flattened, one row per model
train.compare_runs(["baseline", "lender"])     # one metric, targets x runs
train.load_run("baseline")                     # manifest + metrics as written
```

## Runs

| Tag | What it is |
|---|---|
| `baseline` | The first recorded run: `model_matrix/`, 41 features, LightGBM and logistic. Migrated here unchanged from the old flat `reports/step6/`; the numbers are the same bytes. This is the fixed reference every later run is a diff against. |
| `lender` | The A/B: `model_matrix_lender/`, 54 features, three models. Same targets, same splits and the same evaluation population as `refactor` (identical `n` and positives per target), so the deltas are a clean feature-set comparison. **Its `lending` numbers are contaminated, see below.** |
| `lender_fixed` | The same A/B with the as-of gate moved to `delivered_on`. Halves the distortion and is **still contaminated** (`lending` P@500 = 0.742). Kept because "the obvious fix was not enough" is part of the finding. |
| `lender_asof21` | The same A/B again with the gate at `delivered_on` + a 21-day registration lag. Superseded: the 21 days were not a visibility lag, see the calibration below. Kept as the third act of the gate story. |
| `refactor` | The control. Same matrix, same 41 features (same `feature_hash`), the full registry including the MLP. Run from `notebooks/16_refactor_run.ipynb`, which is `16_shap_models.ipynb` with `CFG = train.REFACTOR` and nothing else changed. It isolates "we added a model family" from "we added features". |
| `refactor_det` | `refactor` with LightGBM's `deterministic=True`, plus bootstrap intervals and per-origin metrics. **This is the control every later run is read against.** |
| `lender_asof21_det` | `lender_asof21` under determinism. Re-baselines the lender A/B; every delta reproduced exactly. |
| `refactor_growthfix` | The control with `growth` cut to 27 features, dropping the nine long-history columns that are 100% NULL in every training origin plus `status_changed`. `n_features` is 27 for `growth` and 41 for the other three. |
| `lender_calib_hi` | The lender A/B at the calibrated gate, most conservative setting (7-day created lag, 3-day satisfied lag). **This is the run the lender verdict should be read off.** |
| `lender_calib` | The same at the point calibration (4 days / 1 day). |
| `lender_calib_lo` | The same at the loosest setting tested (2 days / 1 day). Not a verdict run; it exists to show the gradient. |

`baseline`'s manifest carries `migrated_from` and `created_at_source`, because it predates the manifest
and its timestamp is the old file's mtime rather than something recorded at run time.

**The `lender` run's `lending` result is leakage, not a win.** It reports P@100 = 1.000 and
P@500 = 0.992 against a 0.271% base rate (a 369x lift) while ROC-AUC moves only 0.877 to 0.895 and
PR-AUC is 0.207. Perfect top-of-list precision alongside a mediocre global ranking is the signature of
a feature that identifies a subset of positives exactly, and that is what it is.

The cause is the as-of gate in `src/features/charges.py`: it admits a charge when
`created_on <= snapshot_date`, but `created_on` is the date the charge was *created*, not the date it
became publicly visible. 94.7% of charges are delivered to Companies House after they are created
(median lag 6 days, p90 16 days), so a charge created on the 20th and delivered on the 28th is counted
by the lender features at the start of that month while the bulk register, which is what defines the
`lending` label, only sees it later. The label is then guaranteed. Measured:

- 12,182 charge-months are counted before they were observable.
- Among company-months that go on to borrow, the API-minus-bulk outstanding gap is 0.294 against
  0.048 across the population, and for 19.2% of them the API count at `t` already equals the
  post-borrowing count.
- **46.6% of the model's top 500 contain such a charge, against 0.01% of the eval population**, a
  roughly 4,600x enrichment.

**Fixing it took four passes.** Gating on `delivered_on` (`lender_fixed`) removed about half the
distortion and left `lending` at P@500 = 0.742, still nowhere near the control's 0.282. Delivery is
not registration: Companies House takes time to process a delivered charge into the register, so a
charge delivered shortly before a snapshot is visible in the API and absent from the register that
defines the label. Sweeping the margin put the knee at **21 days**, and `lender_asof21` is the run
built on it.

**The 21 days were not a visibility lag.** Recalibrating the sweep one flaw at a time
(`reports/tables/nb16_margin_sweep_ladder.csv`) gives 22.08 days verbatim, 23.68 across all 33 origins
rather than 7, 23.57 once the real extract date is used, **5.34 once the oracle is `NumMortCharges`**
(the register `y_lending` is actually computed from, rather than `NumMortOutstanding`), and **1.81
once the sample is every company-month rather than only companies that went on to borrow**. Eighteen
of the 21 days were the **satisfaction** clock: the sweep calibrated charge creation against a count
that moves on creation and on satisfaction, while the satisfaction gate itself was unlagged, so the
creation margin was paying for a different clock's error. The extract-date drift, which I expected to
explain most of it, is worth 0.11 days (mean drift 0.394 days, 29 of 33 months on the nominal 1st) and
runs the opposite way, since the extract is taken on or after the 1st. Calibrated residuals:
**4 days for `created_on`, 1 day for `satisfied_on`**, by two independent estimators.

The 21-day gate therefore overshot. It bought 0.60 pp of leak (0.62% to 0.02% of charges admitted
early) and paid 43 pp of staleness (8.9% to 52.3% of charges withheld a full extra month after the
register already had them).

```
lending, LightGBM
                 refactor   lender   lender_fixed   lender_asof21
ROC-AUC            0.8767   0.8951         0.8861          0.8763
precision@100        0.55     1.00           0.98            0.48
precision@500       0.282    0.992          0.742           0.310
```

**The corrected verdict: the entire apparent win was a clock error, and what is left is model-family
dependent.** That table, and `compare_runs` by default, is **LightGBM only**. An earlier version of
this note said "nothing moves by more than 0.001 either way", which is false as written: it is a
LightGBM statement that was stated as a whole-run one. Per model, `lender_asof21_det` minus
`refactor_det` from `index.csv` (identical to the pre-determinism deltas):

- **LightGBM:** largest ROC-AUC movement is +0.0011 (`insolvency`); the other three are under 0.0005,
  `lending` included (0.8763 against 0.8767).
- **Logistic:** `growth` +0.0096 with P@500 0.098 -> 0.170; `insolvency` +0.0022; `lending` +0.0010
  with P@500 0.150 -> 0.188; `voluntary_exit` +0.0001.
- **MLP:** `growth` +0.0066; `insolvency` -0.0045; `lending` +0.0008; `voluntary_exit` -0.0027.

`Mortgages.NumMortCharges/Outstanding/Satisfied` are already in the 41-feature base set, so the lender
columns refine information the base model already has, minus lender identity. **Lender identity adds
nothing a gradient-boosted model cannot already read off the `Mortgages.NumMort*` columns already in
the base set; the linear model gains materially, which locates the finding in encoding rather than in
information.**

**Determinism changed almost nothing.** `refactor_det` reproduces `refactor` to four decimal places on
every ROC-AUC across all 12 rows, and exactly two precision@500 cells move: `voluntary_exit` LightGBM
0.854 to 0.846 and `voluntary_exit` MLP 0.678 to 0.680. Every run from `refactor_det` onward carries
bootstrap intervals in `index.csv` as `roc_auc_lo/hi` and `precision_at_500_lo/hi`.

Those two moved cells are a **metric** artefact, not a model one: 982 of the top 1000 `voluntary_exit`
scores are exact ties, so precision@500 there reports which arbitrary slice of a tied block
`argpartition` returned, and a relative jitter of 1e-15 moves it by 0.004. Do not quote
`voluntary_exit` P@500 to three digits. The other three targets have 1, 6 and 14 tied pairs in their
top 1000.

**Reproducibility, stated accurately.** All three families fit twice in one process on identical inputs
give **bit-identical predictions, 0 rows differing**. So: LightGBM is bit-reproducible, and the dense
models are bit-reproducible within a process and reproducible to about nine decimal places across
processes, where the residual 1e-16 to 1e-9 is BLAS reduction order varying with the thread pool.
There is no second nondeterminism bug.

**Read the intervals with one caveat, and it is an important one.** They are produced by resampling
evaluation rows, so they measure **sampling** uncertainty and say nothing about **seed** uncertainty.
The row bootstrap is the whole error bar for LightGBM and logistic. For the MLP add a seed term that
dominates it: a single fit carries about +/-0.02 of ROC-AUC and a difference between two single fits
about +/-0.035. Across four seeds the `growth` 27-versus-41 difference comes out +0.0075, +0.0283,
-0.0063, -0.0101, so **its sign flips on two of four**. No MLP delta in this project below roughly 0.02
of ROC-AUC is interpretable. See `reports/tables/17_growth_seed_spread.csv`.

**Pooled precision@N is not an average of its months.** It falls outside the range of the two test
origins it pools in **9 of 12 rows, in both directions, and in 6 of those by more than 0.02**. The
count is 9 of 12 on `refactor_det` and 9 of 12 again on `lender_calib`, independently, so this is
structural rather than a quirk of one run. The row to quote is `voluntary_exit` logistic, which pools
to **0.296 from months of 0.404 and 0.450**, landing 0.108 below the worse of its own two months.
Averaging cannot do that; it happens because the pooled top-500 is drawn from a mixed population where
scores are not comparable across origins, so the pooled cut selects a worse set than either month's own
top-500. Per-origin figures are in `reports/tables/17_per_origin_spread.csv` and are the ones that
describe a single month's list.

## The calibrated gate, and why `lending` and `insolvency` disagree

At the calibrated gate the `lending` delta against `refactor_det` is **monotone in the gate margin in
every model family**, which is the signature of residual lookahead rather than of one model's greed:

```
lending, delta ROC-AUC vs refactor_det      7d/3d    4d/1d    2d/1d
                                            (_hi)  (calib)    (_lo)
LightGBM                                  -0.0000  +0.0043  +0.0056
logistic                                  +0.0036  +0.0053  +0.0070
MLP                                       +0.0045  +0.0056  +0.0077
LightGBM precision@500                      0.294    0.332    0.406
```

`y_lending` is computed from `NumMortCharges`, **the very register the gate governs**, so loosening
charge visibility leaks the lending label directly. `y_insolvency` comes from a separate register, and
it shows no gradient at all: LightGBM +0.0007, +0.0017, +0.0006 (non-monotone, every point inside its
bootstrap interval) and logistic **+0.0023 at all three gates, identical to four decimal places**. Two
targets, opposite behaviour, one mechanism.

The MLP row is shown for completeness and carries no weight, because a seed term dominates its
interval. The gradient claim rests on LightGBM and logistic, for which the row bootstrap is the whole
error bar and both of which move monotonically by several times it.

**Paired bootstrap on `lending`.** Both runs are evaluated on the same companies, so most sampling
noise is common and cancels; resampling once and differencing on each resample is the right test.
`lender_calib` minus `refactor_det` is **+0.00434 [+0.00345, +0.00524]**, width 0.0018 against 0.0089
unpaired, and it **excludes zero** where the overlapping single-run intervals read as inconclusive.
At the conservative 7d/3d gate the same test does **not** exclude zero, which is what licenses the
"gives a boosted model nothing" half of the verdict.
`reports/tables/17_gate_ladder_paired_delta.csv`.

**So: at the most conservative gate tested, the lender features give a boosted model nothing and give
the linear and MLP models a small but real gain. Everything above that gate scales with the margin
allowed, and in that region signal cannot be distinguished from lookahead.** Two caveats travel with
that. 7d/3d is the tightest gate **tested**, not proven clean, since the gradient has not flattened
there and the true leak-free intercept may be lower. And `lender_calib_lo`'s P@500 of 0.406 is the most
impressive number this project has produced, against the control's 0.282, and it is being discarded;
that is worth stating out loud, because "a looser gate looks better" is exactly the trap the first
lender run fell into.

See `drafts/provisional-claims-2026-08-07.md` for what is settled and what is still open.

The full post-mortem, with the evidence re-derived from disk and the margin sweep plotted, is
`notebooks/nb16_lender_leakage_fix.ipynb`. It also records why verification 7 in notebook 14b passed
while the leak was live: that test replays the harvest against `created_on`, the same wrong clock, so
it inherited the bug instead of catching it.

**On reproducing `baseline` from `refactor`.** Seven of the eight shared rows (4 targets x LightGBM
and logistic) reproduce exactly. The eighth, `voluntary_exit` LightGBM, agrees to 6 decimal places on
ROC-AUC and PR-AUC but moves P@100 from 0.830 to 0.820. That is LightGBM run-to-run nondeterminism,
not the refactor: fitting it twice in a single process on identical inputs gives different
predictions on **every** test row (max difference 0.028) and a top-100 overlap of 84/100, with P@100
landing on 0.840 and 0.850 across those two fits. Multithreaded histogram summation over 3.8M rows is
order-dependent in floating point, and only this target is large enough for it to show. Practical
consequence: on `voluntary_exit`, read AUC and P@1000, and treat P@100 differences below about 0.03
as noise. That is fixed from `refactor_det` onward.

## `refactor_growthfix`

`growth` was training on nine features that are 100% NULL in every one of its training origins and
populated in test, with `status_changed` NULL across half its test set because June 2025 is missing
from the register. The receipt is that all nine scored exactly 0.000000 mean absolute SHAP in
`refactor`. Dropping them takes `growth` from 41 features to **27**, from 9 zero-SHAP features to
**0**, and the worst train-versus-test null differential among the survivors to **0.0153**. Against
`refactor_det`: LightGBM 0.7620 to 0.7611 (-0.0010 against a seed sd of 0.0006, so genuinely unchanged,
because it never split on the dead columns) and logistic 0.7290 to 0.7324 (**+0.0035** against a seed sd
of 0.0009, a 4x margin, because a linear model cannot ignore a 100%-NULL column). Those two rows are the
whole demonstration. **The MLP row is retracted:** it reads 0.6941 to 0.7016, but the same difference
comes out +0.0075, +0.0283, -0.0063, -0.0101 across four seeds, so the sign flips on two of four. The
seed means are 0.7012 against 0.7060, and the 0.694114 recorded in `refactor_det` is exactly the
**minimum** of the four seeds, so the apparent +0.0075 was inflated by which fit happened to land in
the run. The bootstrap intervals on those two runs do not overlap, which
concealed the problem rather than revealing it. The 41-feature count was a fiction for `growth`; it was
a 32-feature model wearing a 41-feature label.

## Known-open

- **`lender_panel_asof21` fails the rewritten verification 7** at the 2025-01 origin by 2 companies of
  150,695, on the satisfaction side. Too small to move a verdict and not worth rebuilding the
  historical runs for, but recorded rather than fixed quietly. It **passes** at 2024-02, and only
  because six days of extract drift happen to buffer the missing satisfaction lag, so a single-month
  version of the test would have called the panel clean.
- **The MLP is seed-unstable.** Not nondeterministic: it is bit-reproducible in-process like the other
  two. But a seed term dominates its row bootstrap, so no MLP delta below roughly 0.02 of ROC-AUC is
  interpretable, which rules out every MLP comparison currently recorded here. Average over seeds
  before reporting any future MLP result.
- **`voluntary_exit` precision@N is partly arbitrary** because 982 of its top 1000 scores are exact
  ties. Irreducible, about +/-1 company. Read ROC-AUC on that target.
- **Four manifests record the wrong gate.** `lender`, `lender_fixed` and `lender_asof21` carry
  `registration_lag_days` as the module default rather than the gate their panel was built with,
  because the lender panels are built outside `RunConfig`. Explicit values are now pinned on those
  configs in `train.py` so it cannot recur, but the recorded manifests are still wrong. True gates are
  in `notebooks/17_metrics_and_determinism.ipynb` section 8.
- **`competitor_charge_created_6m` is misnamed.** It gates on `visible_on`, which is correct; the name
  says otherwise. Renaming changes `feature_hash` and would break comparability across every run above,
  so it waits for a run being re-recorded anyway.
