# Historical Companies House panel + SHAP models

## Context

Today the repo has exactly **one** Companies House snapshot (`BasicCompanyDataAsOneFile-2026-06-01.csv`). Everything downstream (`filtered_bb_sme_sectors.csv`, `shap_feature_matrix.parquet`) is a single-vintage, overwrite-in-place artefact. Nothing is keyed on time.

That blocks two things:

1. **No deltas.** We cannot say "this company's charges grew 3x in six months", which is the actual buying signal.
2. **No SHAP.** There is no `import shap`, no `.fit(`, and no target variable anywhere in the repo. SHAP explains a *model's* predictions, and there is no model, because a single snapshot gives nothing to predict. A time series is what makes a target possible, and it makes it **self-labelling**: the label is just a future delta of a column we already have.

Two facts discovered while planning, both load-bearing:

- The CH download page lists **only the current month**. But older ZIPs remain on the server, unlisted and reachable by direct URL. Probing confirms **33 snapshots exist, Oct 2023 → Jul 2026**. This is a rolling window: the oldest files will age out, so we grab and keep them now.
- The bulk file contains **more than Active companies** (`Liquidation`, `In Administration`, `Active - Proposal to Strike off`, ...). NB01 filters these out. Replaying that filter per month would delete every failure event from the panel, leaving a dataset in which no company ever fails, so a credit-risk model could not learn risk. We keep all statuses and filter at *scoring* time instead.

**Outcome:** a 33-month company-month panel, ~25 delta features, three self-labelled targets, three LightGBM models, and SHAP attributions per composite index.

## Decisions

| Decision | Choice |
|---|---|
| History | 33 snapshots, Oct 2023 → Jul 2026 (June 2025 genuinely missing) |
| Membership | Union cohort; **keep all statuses**, filter `is_active` at scoring |
| Targets | Lending (new charge, 3m) · Distress (status decay, 6m) · Growth (segment upgrade, 12m) |
| Engine | DuckDB (new dep) |
| Panel schema | ~26 slim cols + the 9 `ch_static` features, computed per snapshot |
| Universe | Two-pass union (so SIC recodes ≠ dissolution) |
| Split | Out-of-time + embargo = horizon; GroupKFold-by-company as secondary check |
| Sampling | Quarterly origins, all positives, negatives downsampled 1:10 |
| Extra data | Contracts Finder, re-harvested from Oct 2022, joined **as-of** |
| Model | LightGBM + shap + scikit-learn, installed into `.venv` |
| Retention | Keep the 33 zips (~16GB) permanently; delete extracted CSVs after use |
| Existing work | NB10/NB11 untouched; this is purely additive |

## Snapshot manifest (verified live)

Filenames are **not** reliably `-01`. Verified list:

```
2023-10-04  2023-11-01  2023-12-04  2024-01-01  2024-02-07  2024-03-01
2024-04-01  2024-05-01  2024-06-01  2024-07-01  2024-08-01  2024-09-01
2024-10-01  2024-11-01  2024-12-01  2025-01-01  2025-02-01  2025-03-01
2025-04-01  2025-05-01  [2025-06 MISSING]        2025-07-01  2025-08-01
2025-09-01  2025-10-01  2025-11-01  2025-12-01  2026-01-01  2026-02-01
2026-03-02  2026-04-01  2026-05-01  2026-06-01  2026-07-01
```

URL: `https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-{date}.zip`

**June 2025 is a real hole.** Deltas must therefore be **calendar-aware**: a positional `LAG(3)` would silently span four months across the gap and corrupt every delta in that region. Build a month spine and join on explicit `snapshot_month - N`, leaving NULL where the lag month is absent.

## Files

**New:**
- `src/data/ch_bulk.py` - snapshot date probing (days 01–15), parallel download (4x) with resume/retry, extract, cleanup
- `src/features/panel.py` - two-pass DuckDB build + calendar-aware delta SQL
- `src/features/contracts.py` - Contracts Finder harvest + as-of aggregation
- `src/models/targets.py` - the three labels
- `notebooks/12_historical_snapshots.ipynb` - download, build panel, parity check
- `notebooks/13_panel_deltas.ipynb` - deltas, contracts join, targets, EDA
- `notebooks/14_shap_models.ipynb` - three LightGBM models + SHAP

**Reused as-is (do not modify):**
- `src/features/ch_static.py` - `strip_columns`, `add_static_features(df, today=...)`. The `today` param is the key: pass `today=snapshot_date` so `company_age_years` / `accounts_overdue` / `accounts_stale` are **point-in-time correct**. (This also fixes a latent repro bug in NB10, where those features silently change on every re-run because they are computed against `pd.Timestamp.today()`.)
- NB01's `SEGMENT_MAP`, `FAST_GROWTH_CODES`, `TARGET_SECTIONS`, and `data/processed/SIC.csv` → lift the sector-mapping logic into `panel.py` verbatim so the replay matches NB01 exactly.
- `src/features/ch_api.py` - unchanged; used only for post-scoring enrichment of the shortlist.

**Untouched:** `notebooks/10_feature_matrix.ipynb`, `notebooks/11_shap_sample.ipynb`, `filtered_bb_sme_sectors.csv`, `shap_feature_matrix.parquet`.

## Step 1 - Acquire snapshots (`src/data/ch_bulk.py`, NB12)

- `pip install duckdb lightgbm shap scikit-learn` into `.venv`.
- Probe each month Oct 2023 → Jul 2026 over days 01–15, take the first 200.
- Download 4 in parallel to `data/raw/snapshots/`, skipping any zip already present (resumable). `data/` is already fully gitignored (`.gitignore:11`) and nothing under it is tracked, so no new ignore rule is needed.
- **Keep the zips.** They are the only archive once CH ages them out; re-deriving the panel with a different column set then costs zero downloads.

## Step 2 - Build the panel (`src/features/panel.py`, NB12)

Two passes, because a company can be recoded out of our sectors without dying, and we must not confuse that with dissolution.

- **Pass 1 (universe):** for each snapshot, apply NB01's sector filter (`SICCode.SicText_1..4` → first 5 chars → `code_to_sector`, fast-growth codes take priority). Union all `CompanyNumber`s that match in *any* month → the universe (~1.8–2M).
- **Pass 2 (extract):** for each snapshot, emit slim rows for **any universe member present, whatever its status or current sector**. Absence now unambiguously means "gone from CH".

Per partition: `strip_columns` → `add_static_features(df, today=snapshot_date)` → map `segment` → write.

Columns (~26 + 9 static): `CompanyNumber`, `CompanyName`, `IncorporationDate`, `CompanyCategory`, `CountryOfOrigin`, `CompanyStatus`, `DissolutionDate`, the 4 `Mortgages.*`, the 4 `SICCode.*`, `Accounts.*` (5), `Returns.*` (2), `ConfStmt*` (2), `RegAddress.PostCode`, `sector`, `segment`, `snapshot_date`, plus `is_active` and the 9 `ch_static` features. Drop the 20 `PreviousName_*` cols (collapse to `num_previous_names`), the rest of the address block, `URI`, `LimitedPartnerships.*`.

Output: `data/processed/panel/snapshot_date=YYYY-MM-01/part.parquet` (~1.5–2GB total, ~60M rows). Delete each extracted CSV once written.

## Step 3 - Deltas (`panel.py`, NB13)

All strictly backward-looking from month `t`, via calendar-aware joins on a month spine (never positional `LAG`).

- **Charge dynamics:** `d_charges_{3,6,12}m`, `d_outstanding_{3,6,12}m`, `d_satisfied_12m`, `new_charge_events_12m`, `months_since_last_new_charge`, `debt_ratio_trend_12m`
- **Status:** `status_changed`, `months_in_current_status`, `ever_distressed_before`
- **Size:** `segment_upgraded_12m`, `segment_downgraded_12m`, `months_since_segment_change`
- **Filing behaviour:** `accounts_overdue_streak_months`, `confstmt_late`, `days_to_next_accounts_due`
- **Identity drift:** `sic_changed_12m`, `name_changed_12m`, `postcode_changed_12m`

No 1-month diffs: on a slow-moving register they are ~99% zeros and carry almost no signal.

## Step 4 - Contracts Finder (`src/features/contracts.py`, NB13)

NB05 already pulls a real Companies House number from the OCDS `parties` block via the `GB-COH` identifier scheme, so this is a **clean `CompanyNumber` join, not fuzzy name matching**. Three bugs to fix when lifting it:

1. Hardcoded `C:\MSC\Project\...` paths (it has never run on this machine).
2. `RECENT_CUTOFF = today - 18 months` → set `publishedFrom=2022-10-01` (12m lookback before the first Oct 2023 origin).
3. `max_batches=60` @ `limit=100` silently caps the harvest at 6,000 releases → page until the cursor is exhausted.

Cache the raw JSON once. Then, **per snapshot month**, aggregate only awards with `award_date <= month_end`: `contracts_won_12m`, `total_value_won_12m`, `months_since_last_award`, `d_contracts_12m`. Companies with no awards get a true `0`, not a sentinel. A static (non-time-varying) join would leak future wins onto past rows and must be avoided.

## Step 5 - Targets (`src/models/targets.py`, NB13)

Features from month `t`; labels from `t+1 … t+H`. Never from `t`.

| Index | Label | H |
|---|---|---|
| Lending Readiness | `Mortgages.NumMortCharges` increases | 3m |
| Credit Risk Exposure | Active at `t`, non-Active by `t+H` | 6m |
| Growth Signal | `size_tier` moves up | 12m |

Origins are **quarterly**, which makes the 3-month lending label windows **non-overlapping** (each company-quarter is an independent observation rather than ~15 near-copies). Distress and growth still overlap 2x/4x; grouped CV absorbs that.

Usable origins (33 months, 6m lookback): lending ~24, distress ~23, growth ~20 quarterly-spaced origins.

## Step 6 - Models + SHAP (NB14)

Three separate binary LightGBM classifiers over one shared feature matrix (different horizons, base rates and embargoes; per-index SHAP is what a relationship manager can actually act on).

- **Sampling:** keep every positive, downsample negatives to ~10x. Yields ~1–3M rows per target. **Record the sampling rate and recalibrate predicted probabilities back to the true base rate before ranking prospects.**
- **Split:** out-of-time is primary (train early origins, test latest), with an **embargo gap ≥ H** so training labels never peek into the test window. Report GroupKFold-by-`CompanyNumber` as a secondary generalisation check; a gap between the two numbers tells you which kind of overfitting you have.
- **SHAP:** `TreeExplainer` on a stratified ~100k subsample (exact, fast; plenty for stable summary plots).
- **Scoring:** score the latest partition filtered to `is_active`, rank, then run existing `ch_api.enrich_companies` on only the top few hundred to add director/lender colour. Score wide and cheap; enrich narrow and expensive.

## Verification

1. **Parity check (the important one).** The panel's `2026-06-01` partition, filtered to `CompanyStatus == "Active"` and in-sector, must reproduce `filtered_bb_sme_sectors.csv` exactly: **1,372,321 rows**, identical `CompanyNumber` set, and matching sector counts (Tech/legal 837,066 · Fast growth 320,670 · Manufacturing 214,585). This proves the historical replay is faithful to NB01. Run it on day one, before training anything.
2. **Gap handling.** Assert every `*_3m` / `*_12m` delta is NULL (not silently wrong) where the lag month is absent, specifically around the June 2025 hole.
3. **Point-in-time.** Assert `company_age_years` for a fixed company decreases monotonically as you walk back through snapshots, confirming `today=snapshot_date` was honoured rather than `Timestamp.today()`.
4. **Leakage.** Assert no feature column is derived from data at or after `t+1`. Sanity-check that a model trained with the target column removed cannot exceed ~0.5 AUC.
5. **Label sanity.** Base rates should land in plausible ranges (lending ~0.5–1% per quarter; distress well under 1% per 6m). A base rate of 20% means the label is wrong.
6. **Model.** Out-of-time AUC/PR-AUC per target, plus a SHAP summary plot per index; features should be economically sensible (e.g. `new_charge_events_12m` and `accounts_overdue_streak_months` ranking high).
