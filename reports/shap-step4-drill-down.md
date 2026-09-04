
# Step 4 - Contracts Finder + Find a Tender, joined as-of

## Context

Steps 1-3 of `reports/shap-bulk-dataset-plan.md` are done and verified: 33 CH bulk snapshots
(`src/data/ch_bulk.py`, NB12), a 49.6M-row company-month panel that reproduces NB01 exactly at
the 2026-06 vintage, and 25 backward-looking delta features with the June-2025 hole provably
handled (`src/features/panel.py`, NB13, documented in NB13a).

Everything so far is derived from one source: the CH bulk register. That gives us how a company
*files and borrows*, but nothing about whether it is *winning work*. Public procurement is the
one large, free, company-number-keyed signal of new revenue, and a first public contract win is
a textbook working-capital / invoice-finance trigger. This step adds it.

Sneha's NB05 already proved the join is clean: Contracts Finder's OCDS `parties` block carries a
`GB-COH` identifier, so this is a real `CompanyNumber` join, not fuzzy name matching. What NB05
does *not* have is history or scale, and it has three known defects (hardcoded `C:\MSC\...` paths,
an 18-month cutoff, and `max_batches=60 @ limit=100` silently capping the harvest at 6,000
releases -> 2,154 contract rows -> 1,317 companies).

**Four findings from this planning session that change the design:**

1. **Bulk beats the API.** The OCP Data Registry publishes all of Contracts Finder as OCDS:
   `full.jsonl.gz`, 395 MB, Nov 2016 -> Jul 2026, refreshed monthly, 588k tenders / 434k awards.
   That removes the cap, the rate limiting and the run-to-run variance in one move, and it mirrors
   how we already treat CH (bulk, not API).
   [https://data.open-contracting.org/en/publication/128](https://data.open-contracting.org/en/publication/128)
2. **There is a structural break inside our panel window.** The Procurement Act 2023 took effect
   **24 Feb 2025**. Procurements started on or after that date publish to **Find a Tender**, above
   *and* below threshold; Contracts Finder now carries only legacy pre-Feb-2025 processes. A
   CF-only join would produce a feature that decays to ~0 from Feb 2025 for purely regulatory
   reasons - fatal for the out-of-time split (train early / test late), which would learn a
   calendar artefact and then find it missing in the test window.
3. **FTS has an equivalent bulk feed**: OCP Registry publication 41, Jan 2021 -> Jun 2026, 209 MB,
   refreshed weekly, 241k awards. [https://data.open-contracting.org/en/publication/41](https://data.open-contracting.org/en/publication/41)
4. **FTS is shaped differently and is only partly CH-linked.** In a live 20-release sample, ~4 of
   13 supplier parties carried `GB-COH-*`; the rest were internal `GB-FTS-*` or `GB-UKPRN-*`.
   FTS also puts the money and date in `contracts[].value` / `contracts[].dateSigned`, **not** in
   `awards[]`. So NB05's `flatten_release` does not lift across unchanged - we need two flatteners
   normalising to one schema.

**Outcome:** a sparse as-of contract table, `data/processed/contracts_asof/`, giving six
point-in-time contract features per company-month, joinable onto `panel_deltas` at model time.

## Decisions

| Decision   | Choice                                                                               |
| ---------- | ------------------------------------------------------------------------------------ |
| Source     | OCP Registry bulk OCDS files, not the live APIs                                      |
| Coverage   | **Union of Contracts Finder + Find a Tender**, to span the Feb-2025 break      |
| Matching   | `GB-COH` identifier only, both sources. No name fallback                           |
| As-of gate | **Publication date**, not signature date (signature leaks the publication lag) |
| Storage    | Separate sparse table;`panel_deltas` is not rewritten                              |
| Features   | Plan's four, plus`ever_won_contract` and `first_award_in_12m`                    |
| Values     | Sum stated amounts only, plus`awards_with_value_12m` coverage counter              |
| Notebook   | New`notebooks/13b_contracts_asof.ipynb`; NB13 untouched                            |
| NB06       | **Out of scope this week.** Re-entry path documented below, no code touched    |

## Why NB06 (director changes) is deferred, and how it comes back

Worth recording, because the reason is not the obvious one.

Director changes do **not** need monthly snapshots. `appointed_on` / `resigned_on` are carried on
the record itself, so a single current pull retrospectively reconstructs the full history:
"directors appointed in the 12m before month `t`" is computable for every `t` from one fetch. The
same is true of filing history (`date`) and charges (`created_on` / `satisfied_on`). History is
not the blocker.

**Scale is.** The CH REST API allows 600 requests / 5 min (~173k/day). 2.04M universe companies
x 3 endpoints is ~6M requests, roughly **35 days of continuous polling**. NB06 as written calls
1,000 companies at `time.sleep(0.5)`; that is an enrichment tool, not a panel builder.

The only route to panel scale is CH bulk **product 216** (all officer appointments including
resigned, ~22.6M appointments, ~6.6 GB uncompressed, fixed-width `.dat`). It is free but *not* a
public download - you request it from `bulkproducts@companieshouse.gov.uk` and receive a
cloud-storage link. Lead time is unknown, which does not fit a ship-this-week deadline.

**Re-entry path when the file arrives:** parse product 216 -> one row per (CompanyNumber, officer,
appointed_on, resigned_on) -> aggregate as-of each snapshot month exactly like contracts, gated on
`appointed_on <= month_end` / `resigned_on <= month_end`, yielding `active_directors`,
`director_appointments_12m`, `director_resignations_12m`, `director_churn_12m`,
`months_since_director_change`. It slots into the same `LEFT JOIN` seam as `contracts_asof`, so no
existing artefact needs rebuilding. `notebooks/06_director_changes.ipynb` stays as it is.

## Files

**New:**

- `src/features/contracts.py` - download, flatten (two source shapes), as-of aggregation
- `notebooks/13b_contracts_asof.ipynb` - drive it, verify it, EDA

**Reused:**

- `src/features/panel.py` - `DELTA_DIR`, `UNIVERSE_PATH`, `FIRST_MONTH` / `LAST_MONTH`,
  `month_start`, and the DuckDB `COPY ... PARTITION_BY (snapshot_date)` pattern in
  `build_deltas` (`panel.py:542`). Mirror that structure so the two tables sit side by side.
- `notebooks/05_contract_finder.ipynb` - `flatten_release`'s `party_ch` logic (`GB-COH` ->
  `.strip().upper().zfill(8)`) is correct and lifts across for the CF path.

**Untouched:** `panel.py`'s `DELTA_SQL`, `data/processed/panel/`, `data/processed/panel_deltas/`,
NB13, NB13a, NB05, NB06.

## Implementation

### 4.1 Acquire (`contracts.py`)

Two downloads to `data/raw/contracts/`, skip-if-present, same discipline as `ch_bulk.py`:

- `https://data.open-contracting.org/en/publication/128/download?name=full.jsonl.gz` -> `cf_full.jsonl.gz`
- `https://data.open-contracting.org/en/publication/41/download?name=full.jsonl.gz` -> `fts_full.jsonl.gz`

~600 MB combined. Keep them; they are the reproducibility anchor and the registry refreshes
in place. Record the retrieval date in the notebook.

### 4.2 Flatten to one schema (`contracts.py`)

Stream the `.jsonl.gz` line by line (never load 395 MB of JSON into memory at once) and emit one
row per (supplier company, award), with columns:

`source` (`CF`/`FTS`), `ocid`, `CompanyNumber`, `company_name_src`, `buyer_name`,
`publication_date`, `signature_date`, `award_value_gbp`, `currency`.

- **Both:** build `party_ch` from `parties[]` where the identifier resolves to a Companies House
  number, then `.strip().upper().zfill(8)`. On CF that is `identifier.scheme == "GB-COH"`; on FTS
  it appears as a `GB-COH-<number>` party id, so accept both forms. Drop every supplier without one.
- **CF:** date and value from `awards[].date` / `awards[].value.amount`, suppliers from
  `awards[].suppliers[]` (NB05's logic).
- **FTS:** suppliers from `awards[].suppliers[]`, but date and value from `contracts[]` joined
  back on `contracts[].awardID -> awards[].id`, using `dateSigned` and `value.amount`.
- **`publication_date`** is the release/compiled-release publication date. Where a compiled
  release has no single publication date, use the earliest release date in the process. If it is
  missing entirely, fall back to `signature_date` and flag the row - report the fallback rate.
- Deduplicate within source on `(ocid, CompanyNumber)`. Across sources, a process lives on one
  platform or the other, so cross-source duplication should be near zero; **verify it** rather
  than assume (see Verification 3).
- Non-GBP awards: count them; if <1% of rows, exclude from value sums and say so. Otherwise
  convert at a single documented flat rate.

Write to `data/processed/contracts_flat.parquet`.

### 4.3 As-of aggregation (`contracts.py`, DuckDB)

Cross the distinct contract-winning `CompanyNumber`s with the 34-month calendar spine
(`FIRST_MONTH`..`LAST_MONTH`, same spine idea as `DELTA_SQL`), and for each (company, month)
aggregate awards where `publication_date <= month_end`:

| feature                     | definition                                                        |
| --------------------------- | ----------------------------------------------------------------- |
| `contracts_won_12m`       | distinct`ocid` published in `(month_end - 12m, month_end]`    |
| `total_value_won_12m`     | sum of stated`award_value_gbp` over the same window             |
| `awards_with_value_12m`   | how many of those awards actually stated an amount                |
| `months_since_last_award` | months from the most recent publication at or before`month_end` |
| `d_contracts_12m`         | `contracts_won_12m` at `t` minus at `t-12m`                 |
| `ever_won_contract`       | any award published at or before`month_end`                     |
| `first_award_in_12m`      | their first-ever award landed inside the 12m window               |

Only companies with >= 1 award by that month are written, so this is tens of thousands of rows per
month, not 1.5M. Output:
`data/processed/contracts_asof/snapshot_date=YYYY-MM-01/part.parquet`.

**Consumers `LEFT JOIN` on `(CompanyNumber, snapshot_date)` and `COALESCE` the counts/flags to 0.**
`months_since_last_award` stays NULL for never-winners - a true "no such event", exactly like
`months_since_last_new_charge` in the delta table (~1% non-null, and correct at that).

Restrict nothing at write time; filter to the panel universe at join time. That keeps the table
reusable if the universe is ever widened.

## Verification

Run these in NB13b; each is an `assert`, not an eyeball.

1. **Harvest sanity.** Flattened CF rows from 2022-10 onward must far exceed NB05's 2,154, and
   distinct CF companies must far exceed 1,317. If they don't, the bulk parse is dropping rows.
2. **The Feb-2025 break is closed.** Plot distinct award-winning companies per month, by source.
   CF must fall off a cliff after 2025-02 and FTS must pick up. Assert the **union** has no month
   after 2024-01 with fewer than half the trailing-12-month median - that is the whole reason FTS
   is in scope, so it gets tested directly.
3. **No cross-source double count.** Count companies appearing in both CF and FTS with awards of
   the same value in the same month. Expect ~0; if material, dedup on
   `(CompanyNumber, value, publication month)` and document it.
4. **No future leakage.** For a fixed company with a known award, assert every
   `contracts_won_12m` in months strictly before that award's publication month is 0. Assert
   `max(publication_date)` contributing to any month `t` is `<= month_end(t)`.
5. **Join integrity.** `LEFT JOIN contracts_asof` onto one `panel_deltas` partition must leave the
   row count **exactly** unchanged (49.6M across all months; per-partition equality is the check).
   Any increase means duplicate `(CompanyNumber, snapshot_date)` keys.
6. **Coverage, stated honestly.** Report the share of the ~2.04M universe with
   `ever_won_contract` at the latest month. Expect ~1%. That is fine - it is a sparse,
   high-precision feature like `months_since_last_new_charge` - but it must be written down in the
   notebook so nobody expects it to dominate a SHAP summary plot.
7. **Signal check.** Compare `d_charges_12m > 0` rates and segment mix for `first_award_in_12m`
   companies vs the rest. If a first public contract win really is a working-capital trigger,
   first-time winners should show more subsequent new-charge activity. Same style as NB13a's
   `is_active` separation check.

## Out of scope

Director/officer history (NB06), CH accounts iXBRL financials, name-based matching of the ~70% of
FTS suppliers without a Companies House identifier, and Steps 5-6 (targets, models) - those follow
once this table exists.
