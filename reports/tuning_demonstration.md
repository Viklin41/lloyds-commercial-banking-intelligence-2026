# The leakage-safe search, run properly

Generated 2026-08-25T18:54:05.539174+00:00 by `scripts/tuning_demonstration.py` against `refactor_det`.

## Stage A: how much independent evidence is there to tune on?

| target | horizon | train origins | legal folds | family | best CV | worst CV | spread | fold sd |
|---|---|---|---|---|---|---|---|---|
| lending | 3m | 5 | 3 | lightgbm | 0.8803 | 0.8582 | 0.0221 | 0.0020 |
| lending | 3m | 5 | 3 | logistic | 0.8667 | 0.8663 | 0.0004 | 0.0009 |
| insolvency | 6m | 3 | 1 | lightgbm | 0.7529 | 0.7170 | 0.0359 | 0.0000 |
| insolvency | 6m | 3 | 1 | logistic | 0.7340 | 0.7324 | 0.0015 | 0.0000 |
| voluntary_exit | 6m | 3 | 1 | lightgbm | 0.7998 | 0.7769 | 0.0230 | 0.0000 |
| voluntary_exit | 6m | 3 | 1 | logistic | 0.7908 | 0.7903 | 0.0005 | 0.0000 |
| growth | 12m | 3 | **0** | lightgbm | not tunable | | | |
| growth | 12m | 3 | **0** | logistic | not tunable | | | |

### Winners

| target | family | best parameters |
|---|---|---|
| lending | lightgbm | `{'num_leaves': 31, 'min_child_samples': 100, 'learning_rate': 0.03}` |
| lending | logistic | `{'clf__C': 1.0}` |
| insolvency | lightgbm | `{'num_leaves': 31, 'min_child_samples': 100, 'learning_rate': 0.03}` |
| insolvency | logistic | `{'clf__C': 1.0}` |
| voluntary_exit | lightgbm | `{'num_leaves': 31, 'min_child_samples': 100, 'learning_rate': 0.03}` |
| voluntary_exit | logistic | `{'clf__C': 0.1}` |

### Where the shipped default ranks, and why that is the finding

The boosted search picks the same corner of the grid on all three tunable targets, and ranks the shipped default tenth of twelve on all three:

**lending** (3 fold(s))

| rank | mean CV ROC-AUC | num_leaves | min_child_samples | learning_rate |
|---|---|---|---|---|
| 1 | 0.8803 | 31 | 100 | 0.03 |
| 2 | 0.8770 | 31 | 100 | 0.05 |
| 3 | 0.8768 | 31 | 200 | 0.05 |
| 4 | 0.8759 | 63 | 100 | 0.03 |
| 5 | 0.8751 | 63 | 200 | 0.03 |
| 6 | 0.8699 | 63 | 500 | 0.05 |
| 7 | 0.8697 | 127 | 500 | 0.03 |
| 8 | 0.8693 | 31 | 200 | 0.1 |
| 9 | 0.8692 | 31 | 500 | 0.1 |
| 10 | 0.8688 | 63 | 200 | 0.05 **(shipped default)** |
| 11 | 0.8630 | 127 | 500 | 0.05 |
| 12 | 0.8582 | 127 | 100 | 0.05 |

**insolvency** (1 fold(s))

| rank | mean CV ROC-AUC | num_leaves | min_child_samples | learning_rate |
|---|---|---|---|---|
| 1 | 0.7529 | 31 | 100 | 0.03 |
| 2 | 0.7490 | 127 | 500 | 0.03 |
| 3 | 0.7455 | 31 | 200 | 0.05 |
| 4 | 0.7448 | 63 | 200 | 0.03 |
| 5 | 0.7439 | 31 | 100 | 0.05 |
| 6 | 0.7430 | 63 | 500 | 0.05 |
| 7 | 0.7411 | 127 | 500 | 0.05 |
| 8 | 0.7408 | 63 | 100 | 0.03 |
| 9 | 0.7385 | 31 | 500 | 0.1 |
| 10 | 0.7347 | 63 | 200 | 0.05 **(shipped default)** |
| 11 | 0.7339 | 31 | 200 | 0.1 |
| 12 | 0.7170 | 127 | 100 | 0.05 |

**voluntary_exit** (1 fold(s))

| rank | mean CV ROC-AUC | num_leaves | min_child_samples | learning_rate |
|---|---|---|---|---|
| 1 | 0.7998 | 31 | 100 | 0.03 |
| 2 | 0.7952 | 31 | 200 | 0.05 |
| 3 | 0.7941 | 31 | 100 | 0.05 |
| 4 | 0.7926 | 63 | 200 | 0.03 |
| 5 | 0.7920 | 63 | 100 | 0.03 |
| 6 | 0.7916 | 127 | 500 | 0.03 |
| 7 | 0.7898 | 63 | 500 | 0.05 |
| 8 | 0.7892 | 31 | 500 | 0.1 |
| 9 | 0.7869 | 127 | 500 | 0.05 |
| 10 | 0.7868 | 63 | 200 | 0.05 **(shipped default)** |
| 11 | 0.7866 | 31 | 200 | 0.1 |
| 12 | 0.7769 | 127 | 100 | 0.05 |


## Stage B: what adopting the winner would have bought

Target `lending`, family `lightgbm`, 2,782,591 held-out rows.

- default (recorded, shipped): `{'num_leaves': 63, 'min_child_samples': 200, 'learning_rate': 0.05}`
- tuned (Stage A winner): `{'num_leaves': 31, 'min_child_samples': 100, 'learning_rate': 0.03}`

| metric | default | tuned | delta | paired 95% CI |
|---|---|---|---|---|
| ROC-AUC | 0.8767 | 0.8759 | -0.0008 | [-0.0013, -0.0003] |
| precision@500 | 0.282 | 0.300 | +0.018 | [+0.000, +0.038] |

Control: the recorded model re-scored here gives 0.876666 against 0.876666 in the run index (difference 0.00e+00).

Boosting rounds actually used: 143 at the default parameters, 262 at the tuned ones. The search itself runs at a fixed 1,500 rounds with no early stopping, because `RandomizedSearchCV` cannot be handed an `eval_set`, so the applied refit is not the configuration the search scored. That is deliberate: the question is what adopting the winner into the production path would do, not whether the search can be replayed.

### Reading

The search ranks the shipped default tenth of twelve on all three tunable targets and prefers the same corner every time: fewest leaves, lowest learning rate, smallest minimum child size. Applied through the production path, that winner is **worse** out of time, by a margin whose paired interval excludes zero.

The mechanism is in the two round counts above. The search scores every configuration at a fixed 1,500 boosting rounds, because `RandomizedSearchCV` has no `eval_set` to stop on. At 1,500 rounds a slow, small-leaf configuration is still improving while a fast, wide one has long since overfitted, so the ranking is largely a ranking of how gracefully each configuration tolerates being run far past its useful length. The production fit never operates there: it stops at 143 rounds at the default parameters. The search and the deployed model are therefore optimising different objects, and the search's confident ordering does not transfer.

This is the same shape as the three findings in section 4.1.7 and it belongs next to them. The search ran, returned a clean and internally consistent ranking, and was believed. It was not wrong about what it computed. It was wrong about what we would have taken it to mean.
