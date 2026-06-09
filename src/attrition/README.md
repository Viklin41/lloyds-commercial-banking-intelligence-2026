# Attrition workstream (defend against attrition)

Public-data-only signals for the three attrition sub-problems: dormancy (soft),
closure (hard), and bank supplier change (competitive). See the reasoning write
up in the team's working notes.

## Modules

- `definitions.py` - pure functions that turn raw Companies House fields into
  attrition features: status classification, dormancy flag, size band, SIC to
  Lloyds target sector, and filing punctuality. No dependencies, fully unit
  tested.
- `ch_api.py` - Companies House API client (charges, filing history, officers)
  with caching and rate limiting, plus pure helpers for charge parsing and the
  bank-switch heuristic. Charges carry the lender name and created/satisfied
  dates, so a single charges call gives the full secured-lending timeline.
- `run_bulk_eda.py` - baseline cross-sectional attrition EDA on the bulk
  snapshot (rates by sector, size, age; charge presence; a sampling-bias check).
- `run_charges_probe.py` - validate switch detection on real companies.
- `sample_companies.py` - draw a fair sample of companies that hold charges,
  balanced across size bands (default) or across outcome classes
  (`--strata status`: healthy, distress, dormant).
- `enrich_charges.py` - call the charges API per company and write the bank
  picture, including lost-all-banks, reduced-banks, clean switch, and a recent
  bank loss flag (last 24 months).
- `build_attrition_labels.py` - use filing history to date the first distress
  event per company, then test whether a bank loss tends to come first.

## Setup

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env   # then paste your CH_API_KEY
```

## Data inputs (not in git)

- Bulk snapshot: download from
  https://download.companieshouse.gov.uk/en_output.html and unzip into
  `data/raw/` (about 5.7M companies). Used by `run_bulk_eda.py`.
- API key: free from
  https://developer.company-information.service.gov.uk/manage-applications/add
  Used by `ch_api.py` / `run_charges_probe.py`.

## Run

```
# tests (no data or key needed)
.venv/Scripts/python -m unittest discover -s tests -v

# baseline EDA (needs the bulk file)
.venv/Scripts/python -m src.attrition.run_bulk_eda

# switch-detection probe (needs an API key)
.venv/Scripts/python -m src.attrition.run_charges_probe 00445790 02065704

# bank attrition signals on a fair sample (needs the bulk file and an API key)
.venv/Scripts/python -m src.attrition.sample_companies --n 500
.venv/Scripts/python -m src.attrition.enrich_charges

# attrition labels from filing history, with a status-balanced sample
.venv/Scripts/python -m src.attrition.sample_companies --strata status --n 600 \
    --out data/processed/attrition_status_sample.csv
.venv/Scripts/python -m src.attrition.build_attrition_labels \
    --sample data/processed/attrition_status_sample.csv
```

## Why charges matter most here

The bulk file only has charge counts. The lender identity and charge dates,
which power the dormancy/closure distress view and the bank-switch detection,
come from the API. That is why the API client is central to this workstream.
