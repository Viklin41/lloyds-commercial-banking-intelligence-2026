# Paired bootstrap, logistic: `lender_calib_hi` minus `refactor_det`

Generated 2026-08-25T18:21:44.391196+00:00 by `scripts/paired_linear_n4.py`. 1000 replicates, percentile method.

## Result

| target | control | treatment | delta | paired 95% CI | excludes 0 |
|---|---|---|---|---|---|
| lending | 0.8615 | 0.8651 | +0.0036 | [+0.0027, +0.0045] | **yes** |
| insolvency | 0.7324 | 0.7347 | +0.0023 | [+0.0013, +0.0033] | **yes** |
| voluntary_exit | 0.7704 | 0.7693 | -0.0010 | [-0.0011, -0.0009] | **yes** |
| growth | 0.7290 | 0.7382 | +0.0092 | [+0.0081, +0.0103] | **yes** |

### precision@500, same pairing

| target | control | treatment | delta | paired 95% CI |
|---|---|---|---|---|
| lending | 0.150 | 0.188 | +0.038 | [+0.012, +0.060] |
| insolvency | 0.058 | 0.068 | +0.010 | [-0.010, +0.032] |
| voluntary_exit | 0.296 | 0.336 | +0.040 | [+0.022, +0.066] |
| growth | 0.098 | 0.152 | +0.054 | [+0.020, +0.084] |

## Reproduction control

Each refit must reproduce the ROC-AUC already recorded in `reports/runs/index.csv`. A drift larger than 1e-06 means this script is measuring itself.

| target | run | refit | recorded | abs diff |
|---|---|---|---|---|
| lending | refactor_det | 0.861508 | 0.861508 | 1.11e-16 |
| lending | lender_calib_hi | 0.865086 | 0.865086 | 7.17e-10 |
| insolvency | refactor_det | 0.732376 | 0.732376 | 3.94e-11 |
| insolvency | lender_calib_hi | 0.734666 | 0.734666 | 9.46e-10 |
| voluntary_exit | refactor_det | 0.770367 | 0.770367 | 3.63e-12 |
| voluntary_exit | lender_calib_hi | 0.769327 | 0.769327 | 4.54e-10 |
| growth | refactor_det | 0.728975 | 0.728975 | 2.17e-10 |
| growth | lender_calib_hi | 0.738214 | 0.738222 | 8.44e-06 |

**Failures: 1**
- growth/lender_calib_hi: refit ROC-AUC 0.738214 != recorded 0.738222 (diff 8.44e-06)

### Why, and why it does not matter

`growth` under `lender_calib_hi` refits to 0.738214 against a recorded 0.738222, a
drift of 8.4e-06. It is not process noise: two fresh processes reproduce 0.738214
bit-for-bit, and two fits inside one process return identical prediction vectors. The
cause is the threaded-BLAS residual of section 4.1.7, and it is a function of the
thread count rather than of thread completion order. Refitting this exact cell at
several BLAS thread settings gives:

| OMP_NUM_THREADS | ROC-AUC |
|---|---|
| 1 | 0.738222396 |
| 4 | 0.738209146 |
| 8 | 0.738222101 |
| 16 (this machine's default) | 0.738213962 |

The recorded run matches the single-threaded value to six decimal places. So the
spread attributable to BLAS threading is about 1.3e-05 of ROC-AUC, which is 1/700 of
the growth delta this script measures (+0.0092) and about 1/85 of that delta's
interval half-width. It changes no conclusion, and it sharpens a claim already in
section 4.1.7: the dense-model residual is *deterministic within a threading
configuration* and differs *between* configurations, rather than being random per
process. The pairing itself is unaffected, because both configs are fitted in the same
process at the same thread count, so the difference between them is internally
consistent whatever that count happens to be.

Why this cell and not the other seven: `growth` is the target whose feature list
carries nine columns with no observed value in training (the defect of section 4.6),
which the imputer drops with a warning, and its solver stops at 100 iterations. That
is the worst-conditioned of the eight fits, so it is where a 1e-09 perturbation of the
scores is most able to reorder rows near the ranking boundaries.
