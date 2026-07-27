# Step 6 baseline: models, SHAP, and the numbers to measure the lender harvest against

Written the day step 6 first ran end to end, before the Charges API lender harvest finished. That timing is the point of the document. Everything here is a **baseline**: the out-of-time numbers that will say, later, whether twenty-four hours of harvesting bought anything. Without them the harvest is an act of faith.

Machine-readable twin: `reports/step6/model_results.json`, under the tag `baseline`. Re-running `notebooks/16_shap_models.ipynb` with a grown `targets.FEATURE_COLS` writes a second tag and the comparison becomes a diff.

## The split

Out-of-time, primary, with an embargo of at least the horizon. Origins are read off each target's own partitions rather than a shared grid, because the base populations will stop agreeing as soon as a switching target lands.

| target | H (m) | train | embargo (dropped) | test | early-origin filter |
|---|---|---|---|---|---|
| lending | 3 | 2024-10, 2025-01, 2025-04, 2025-07, 2025-10 | - | 2026-01, 2026-04 | yes |
| insolvency | 6 | 2024-10, 2025-01, 2025-04 | 2025-07 | 2025-10, 2026-01 | yes |
| voluntary_exit | 6 | 2024-10, 2025-01, 2025-04 | 2025-07 | 2025-10, 2026-01 | yes |
| growth | 12 | 2023-10, 2024-01, 2024-04 | 2024-07, 2024-10, 2025-01 | 2025-04, 2025-07 | no |

Lending loses nothing to the embargo: horizon 3m, origins quarterly, so consecutive origins are already exactly `H` apart. That was the reason for quarterly origins in step 5.

Growth had to give up `targets.FIRST_FULL_ORIGIN`. A 12-month horizon means the embargo eats three origins, and honouring the filter as well would leave none. It therefore trains on 2023-10 to 2024-04, where the 12m deltas are partly NULL for calendar reasons. Read its numbers with that in mind.

## Out-of-time results

precision@N and PR-AUC are computed on the **unsampled** test population (every active company at the test origins, roughly 0.9-1.4M per origin), not on the 10:1 training matrix. ROC-AUC survives negative downsampling; those two do not, and precision@N is the headline metric because a relationship manager works a finite call list.

| target | model | base rate | ROC-AUC | PR-AUC | P@100 | P@500 | P@1000 | lift@100 |
|---|---|---|---|---|---|---|---|---|
| lending | lightgbm | 0.271% | 0.8767 | 0.0567 | 55.0% | 28.2% | 22.2% | 203x |
| lending | logistic | 0.271% | 0.8615 | 0.0403 | 18.0% | 15.0% | 14.0% | 66x |
| insolvency | lightgbm | 0.329% | 0.7615 | 0.0169 | 19.0% | 12.2% | 11.3% | 58x |
| insolvency | logistic | 0.329% | 0.7324 | 0.0119 | 3.0% | 5.8% | 5.9% | 9x |
| voluntary_exit | lightgbm | 7.728% | 0.7929 | 0.3512 | 83.0% | 84.8% | 85.5% | 11x |
| voluntary_exit | logistic | 7.728% | 0.7704 | 0.3104 | 6.0% | 29.6% | 42.6% | 1x |
| growth | lightgbm | 2.137% | 0.7620 | 0.0578 | 22.0% | 20.2% | 17.5% | 10x |
| growth | logistic | 2.137% | 0.7290 | 0.0468 | 7.0% | 9.8% | 12.7% | 3x |

The logistic floor loses on every target, and by enough that the boosting is clearly earning its complexity: 1.5 to 4 points of ROC-AUC, and a far larger gap on precision@100, which is where the non-linearity actually pays. That was the question the floor was fitted to answer.

Lending is the standout and it makes sense that it would be: taking a new charge is a *deliberate act with a run-up*, and the run-up is exactly what the charge-dynamics deltas measure. Insolvency is the hardest, which also makes sense: it is rarer, slower, and the public register is the last place to hear about it.

## Secondary check: GroupKFold by company

Out-of-time is the primary split because it mirrors production. Grouped CV ignores time on purpose, and the comparison is the informative part: if grouped CV were much the better of the two, the model would have learned something about this particular period that will not survive into the next one.

| target | rows | grouped-CV ROC-AUC | out-of-time ROC-AUC | gap |
|---|---|---|---|---|
| lending | 457,941 | 0.8809 | 0.8767 | +0.0043 |
| insolvency | 520,142 | 0.7694 | 0.7615 | +0.0078 |
| voluntary_exit | 2,000,000 | 0.8142 | 0.7929 | +0.0213 |
| growth | 1,657,611 | 0.7747 | 0.7620 | +0.0126 |

Gaps are small and all in the same direction. Nothing here suggests the models are riding a period effect.

## Calibration

Downsampling negatives at rate `r` multiplies the odds by `1/r`. The correction is `odds_true = odds_sampled * r`, applied per row from the `neg_keep_rate` step 5 carried along. Ranking is untouched; the numbers become true again.

| target | neg keep rate | mean pred, raw | mean pred, recalibrated | true base rate | ratio |
|---|---|---|---|---|---|
| lending | 0.0285 | 6.134% | 0.301% | 0.271% | 1.11x |
| insolvency | 0.0366 | 8.000% | 0.363% | 0.329% | 1.10x |
| voluntary_exit | 0.9000 | 8.799% | 8.140% | 7.728% | 1.05x |
| growth | 0.2112 | 8.694% | 2.115% | 2.137% | 0.99x |

A ratio near 1.0 is the check. Getting the correction the wrong way round would be easy to not notice, because the ranking would look identical.

## Top SHAP features per target

| rank | lending | insolvency | voluntary_exit | growth |
|---|---|---|---|---|
| 1 | Mortgages.NumMortCharges | segment | months_since_last_confstmt | tier_rank |
| 2 | segment | company_age_years | accounts_stale_streak_months | segment |
| 3 | sector | months_since_last_accounts_filing | days_to_next_accounts_due | months_since_last_accounts_filing |
| 4 | company_age_years | months_since_last_confstmt | company_age_years | months_since_segment_change |
| 5 | days_to_next_accounts_due | days_to_next_accounts_due | months_since_last_accounts_filing | Mortgages.NumMortCharges |
| 6 | months_since_last_confstmt | Mortgages.NumMortCharges | segment | days_to_next_accounts_due |
| 7 | postcode_changed_12m | segment_upgraded_12m | confstmt_late | company_age_years |
| 8 | sic_changed_12m | sector | sector | months_in_current_status |

## Do SHAP and the logistic floor agree on direction?

This was the other reason to fit the linear model. The direction of a feature is the relationship between its **value** and its **own SHAP value** (measured as a Spearman correlation, so it does not assume linearity), compared against the sign of the logistic coefficient. Note that the *mean signed SHAP value is not a direction* and using it as one is a mistake worth not repeating: for a non-monotone feature it can average to anything.

| target | disagree | agree |
|---|---|---|
| growth | 1 | 9 |
| insolvency | 7 | 3 |
| lending | 2 | 8 |
| voluntary_exit | 1 | 9 |

| target | feature | shap_direction | logit_coef |
|---|---|---|---|
| lending | days_to_next_accounts_due | +0.045 | -0.034 |
| lending | Mortgages.NumMortOutstanding | +0.531 | -0.057 |
| insolvency | months_since_last_accounts_filing | +0.277 | -0.010 |
| insolvency | days_to_next_accounts_due | -0.354 | +0.046 |
| insolvency | Mortgages.NumMortCharges | +0.541 | -0.072 |
| insolvency | segment_upgraded_12m | -0.107 | +0.013 |
| insolvency | tier_rank | +0.683 | -0.165 |
| insolvency | months_since_segment_change | -0.592 | +0.062 |
| insolvency | months_in_current_status | +0.035 | -0.075 |
| voluntary_exit | months_in_current_status | -0.153 | +0.071 |
| growth | d_charges_6m | -0.154 | +0.002 |

Disagreement is not automatically a bug. The logistic coefficient is a *partial* effect holding everything else fixed, and with features as correlated as these (`d_charges_3m`, `d_charges_6m` and `d_charges_12m` are overlapping windows on the same quantity) a partial effect can legitimately flip sign against the marginal relationship SHAP shows.

Insolvency is where most of them land, and the interesting pair is `tier_rank` and `Mortgages.NumMortCharges`: SHAP says bigger and more-charged companies score higher, the logit coefficient says lower once size is controlled for. Both readings are defensible, and the marginal one (SHAP) is the one that matches what a relationship manager sees. Worth a look before any of this is put in front of one, but not a red flag.

## What this does not include, on purpose

- **No hyperparameter tuning.** Tuning against a feature set that is about to gain columns is wasted effort. Tune once, at the end, on the final matrix.

- **No strict-vs-extended contract A/B yet.** The switch is one argument (`contracts_dir=contracts.ASOF_EXT_DIR`) and the harness above already supports it; it is the next comparison to run, and now there is something to run it against.

- **No lender features.** That is the whole point.

## Operational notes worth keeping

- **`n_jobs=-1` is a trap under WSL2.** It reads 22 logical cores and then spends all its time in thread contention: 50 boosting rounds on the 165k-row insolvency matrix took 98 seconds at `n_jobs=-1` against 0.9 seconds at `n_jobs=8`. `train.LGB_PARAMS` pins it to 6.

- **Category levels are positional.** `train.apply_categories` pins the scoring frame's `sector`/`segment` levels to the training frame's before predicting. A mismatch would produce a plausible ranked list and no error at all.

- **The live scoring month is past the contract harvest watermark.** Fine to score on, not fine to train on; `targets._check_contract_watermark` enforces the latter.

## Addendum, 27 July 2026: the pipeline refactor

Every number in this document was produced before the supervisor call and is unchanged by what follows. `src/models/train.py` was reorganised the same day to meet Fernando's requirements, and the reorganisation was checked against these results the boring way: insolvency re-run through the new code reproduces ROC-AUC 0.761520, PR-AUC 0.016923 and P@100 19.0% to every digit. The `baseline` tag in `reports/step6/model_results.json` therefore stays the fixed reference for the lender-harvest comparison, and the refactor run writes a separate `refactor` tag beside it.

What changed:

- `fit_lightgbm` and `fit_logistic` are gone, replaced by a `MODELS` registry of `ModelSpec`. `run_target` loops over it, so adding a model family is one dict entry.
- `dense_preprocessor` was lifted out of the old `fit_logistic` and is now shared, so no model comparison is confounded by differences in preprocessing.
- `mlp` (`MLPClassifier`) joins the registry as the complex, hard-to-explain end of the interpretability/accuracy trade-off the dissertation argues.
- `tune_model` plus `OriginEmbargoSplit` do hyperparameter search with a time-aware, embargoed CV. A default `KFold` inside a search would reintroduce both leaks the primary split exists to prevent. Note that insolvency affords exactly **one** legal fold under a six-month embargo across three training origins; that is the real amount of evidence available, not a defect.
- `explain` dispatches to the right SHAP explainer per family. Measured cost on the insolvency test sample: `TreeExplainer` does 100k rows in seconds, `KernelExplainer` on the MLP does 20 rows in 2.3s, which extrapolates to several hours for the same 100k.

The split, the unsampled evaluation population and the recalibration are untouched.
