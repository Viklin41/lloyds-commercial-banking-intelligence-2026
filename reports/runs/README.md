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

Its manifest carries `migrated_from` and `created_at_source`, because it predates the manifest
and its timestamp is the old file's mtime rather than something recorded at run time.
