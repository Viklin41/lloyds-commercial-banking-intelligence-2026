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
| `refactor` | The control. Same matrix, same 41 features (same `feature_hash`), the full registry including the MLP. Run from `notebooks/16_refactor_run.ipynb`, which is `16_shap_models.ipynb` with `CFG = train.REFACTOR` and nothing else changed. It isolates "we added a model family" from "we added features". |

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

The fix is to gate on `delivered_on` (already harvested, `charges.py:85`, and currently unused)
rather than `created_on`, then rebuild `lender_panel/` and `model_matrix_lender/` and re-run. This is
the same distinction the contract features already get right by gating on `publication_date` rather
than `signature_date`. The other three targets move by less than 0.001 ROC-AUC either way, so they are
not materially affected, but they share the gate and should be rebuilt with it.

**On reproducing `baseline` from `refactor`.** Seven of the eight shared rows (4 targets x LightGBM
and logistic) reproduce exactly. The eighth, `voluntary_exit` LightGBM, agrees to 6 decimal places on
ROC-AUC and PR-AUC but moves P@100 from 0.830 to 0.820. That is LightGBM run-to-run nondeterminism,
not the refactor: fitting it twice in a single process on identical inputs gives different
predictions on **every** test row (max difference 0.028) and a top-100 overlap of 84/100, with P@100
landing on 0.840 and 0.850 across those two fits. Multithreaded histogram summation over 3.8M rows is
order-dependent in floating point, and only this target is large enough for it to show. Practical
consequence: on `voluntary_exit`, read AUC and P@1000, and treat P@100 differences below about 0.03
as noise.
