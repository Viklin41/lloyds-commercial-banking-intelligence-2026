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
| `refactor` | The control. Same matrix, same 41 features (same `feature_hash`), the full registry including the MLP. Run from `notebooks/16_refactor_run.ipynb`, which is `16_shap_models.ipynb` with `CFG = train.REFACTOR` and nothing else changed. It isolates "we added a model family" from "we added features". |

`baseline`'s manifest carries `migrated_from` and `created_at_source`, because it predates the manifest
and its timestamp is the old file's mtime rather than something recorded at run time.

**On reproducing `baseline` from `refactor`.** Seven of the eight shared rows (4 targets x LightGBM
and logistic) reproduce exactly. The eighth, `voluntary_exit` LightGBM, agrees to 6 decimal places on
ROC-AUC and PR-AUC but moves P@100 from 0.830 to 0.820. That is LightGBM run-to-run nondeterminism,
not the refactor: fitting it twice in a single process on identical inputs gives different
predictions on **every** test row (max difference 0.028) and a top-100 overlap of 84/100, with P@100
landing on 0.840 and 0.850 across those two fits. Multithreaded histogram summation over 3.8M rows is
order-dependent in floating point, and only this target is large enough for it to show. Practical
consequence: on `voluntary_exit`, read AUC and P@1000, and treat P@100 differences below about 0.03
as noise.
