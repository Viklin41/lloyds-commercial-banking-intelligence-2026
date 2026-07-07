# SHAP feature catalog

A **selection surface** for the model: every variable available per company, so we can
visualise and pick which to feed a SHAP model. Covers three layers:

1. **Raw** - Companies House bulk columns, passed through unchanged.
2. **Static engineered** - derived from raw for **all** 1,372,321 companies (`src/features/ch_static.py`).
3. **API-derived** - fetched from live APIs for a **sample** of companies (`src/features/ch_api.py`,
   NB05 contracts); sentinel elsewhere. Coverage flagged by `api_enriched`.

Base table: `data/processed/filtered_bb_sme_sectors.csv` (1,372,321 × 57), keyed on
`CompanyNumber` (**kept verbatim** - never zero-padded - so other DBs can be joined later).
Assembled matrix: `data/processed/shap_feature_matrix.parquet`. A machine-readable version of
this catalog with live coverage counts is written to `data/processed/shap_feature_catalog.csv`
by `notebooks/10_feature_matrix.ipynb`.

---

## Layer 1 - Raw Companies House columns (passthrough)

| Group | Columns | Modelling note |
|---|---|---|
| Identity | `CompanyName`, `CompanyNumber`*, `URI`, `CompanyCategory`, `CompanyStatus`, `CountryOfOrigin` | IDs/keys - exclude from features; `CompanyCategory`/`CompanyStatus` categorical |
| Address | `RegAddress.PostCode`, `.PostTown`, `.County`, `.Country`, `.AddressLine1/2`, `.CareOf`, `.POBox` | Geography; `PostCode`/`County` usable as region features |
| SIC / activity | `SICCode.SicText_1..4` | High-cardinality text; use for sector derivation / embeddings |
| Accounts & returns | `Accounts.AccountRefDay`, `.AccountRefMonth`, `.NextDueDate`, `.LastMadeUpDate`, `.AccountCategory`, `Returns.NextDueDate`, `Returns.LastMadeUpDate`, `ConfStmtNextDueDate`, `ConfStmtLastMadeUpDate` | Dates feed the static flags below; `AccountCategory` feeds `size_tier` |
| Mortgages (raw counts) | `Mortgages.NumMortCharges`, `.NumMortOutstanding`, `.NumMortSatisfied`, `.NumMortPartSatisfied` | Numeric - direct SHAP features |
| Partnerships | `LimitedPartnerships.NumGenPartners`, `.NumLimPartners` | Numeric; mostly 0 |
| History | `IncorporationDate`, `DissolutionDate`, `PreviousName_1..10.CONDATE`, `PreviousName_1..10.CompanyName` | Feed `company_age_years` / name-change features |
| Classification (NB01) | `sector`, `segment` | `sector` = coarse SIC grouping; `segment` = size tier + filing-status buckets |

\* `CompanyNumber` is the canonical join key and is preserved byte-for-byte from source.

## Layer 2 - Static engineered features (all 1,372,321 companies)

| Variable | Type | Source col(s) | Derivation | Coverage |
|---|---|---|---|---|
| `company_age_years` | float | `IncorporationDate` | `(today − inc).days / 365.25`, 1 dp (`dayfirst=True`) | 100% |
| `has_any_charge` | bool | `Mortgages.NumMortCharges` | `> 0` | 100% |
| `has_outstanding_charges` | bool | `Mortgages.NumMortOutstanding` | `> 0` | 100% |
| `debt_ratio` | float | Outstanding / Charges | `Outstanding/Charges` if Charges>0 else 0, 2 dp; ∈ [0,1] | 100% |
| `accounts_overdue` | bool | `Accounts.NextDueDate` | `< today` | 100% |
| `accounts_stale` | bool | `Accounts.LastMadeUpDate` | `isna()` or `< today − 24mo` | 100% |
| `size_tier` | category | `segment` (from `Accounts.AccountCategory` via NB01 `SEGMENT_MAP`) | `segment` where ∈ {Micro,Small,Medium,Large}, else `<NA>` | ~66% (rest are filing-status buckets) |
| `num_previous_names` | int | `PreviousName_*.CompanyName` | count of non-null | 100% |
| `has_name_change` | bool | `num_previous_names` | `> 0` | 100% |

## Layer 3 - API-derived features (sample only; sentinel elsewhere)

`api_enriched` (bool) marks whether a company was in the live-CH sample. `N` is a config knob
in the notebook (default 1,000; outstanding-charge companies prioritised). **A CH API key is
required** (`CH_API_KEY`); with no key these are all sentinels. Contracts features come from the
public Contracts Finder API (no key), covering only companies that appear in award notices.

### Companies House - Officers API (NB06)
| Variable | Type | Sentinel |
|---|---|---|
| `active_directors` | int | `<NA>` |
| `recent_director_appointments` | int (≤18mo) | `<NA>` |
| `recent_director_resignations` | int (≤18mo) | `<NA>` |
| `has_recent_director_change` | bool | `False` |

### Companies House - Filing History API (NB06)
| Variable | Type | Sentinel |
|---|---|---|
| `recent_growth_filings` | int (SH01/SH06, ≤18mo) | `<NA>` |
| `has_recent_growth_filing` | bool | `False` |
| `accounts_filings_count` | int | `<NA>` |
| `last_accounts_filing_date` | date | `NaT` |

### Companies House - Charges API (NB06 health + NB04 lender)
| Variable | Type | Sentinel |
|---|---|---|
| `charges_outstanding` | int | `<NA>` |
| `charges_total` | int | `<NA>` |
| `financial_health_concern` | bool - `charges_outstanding>0` OR `accounts_overdue` OR `accounts_stale` (composite; computed for **all** companies, the charges term contributing only for enriched rows) | n/a (100% coverage) |
| `has_lloyds_linked_lender` | bool - lender name matches Lloyds/Bank of Scotland/HBOS/Halifax/MBNA/Scottish Widows | `False` |
| `has_other_lender` | bool | `False` |
| `lender_names_api` | text | `"Not checked by API"` |
| `lender_groups_api` | text | `"Not checked by API"` |
| `lender_check_status` | category | `"Not checked by API"` |

### Contracts Finder API - public procurement (NB05)
Coverage = companies appearing in award notices (independent of `N`).
| Variable | Type | Sentinel |
|---|---|---|
| `contracts_won_as_supplier` | int | `0` |
| `total_value_won_gbp` | float | `0` |
| `avg_value_won_gbp` | float | `0` |
| `contracts_given_as_buyer` | int (≈0, buyers rarely carry a CH number) | `0` |
| `total_value_given_gbp` | float | `0` |
| `total_contracts_linked` | int | `0` |
| `total_value_linked_gbp` | float | `0` |
| `latest_supplier_award_date` | date | `NaT` |

### Assembly metadata
| Variable | Type | Meaning |
|---|---|---|
| `api_enriched` | bool | company was in the live-CH sample (its CH-API columns are real, not sentinel) |
