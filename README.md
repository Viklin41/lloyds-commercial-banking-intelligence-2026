# Lloyds Commercial Banking Intelligence 2026

A university project sponsored by Lloyds Banking Group, Business and Commercial
Banking (BCB). The goal is to test whether public data can help the bank spot a
company's future needs and risks before the company asks, using only free and
public sources.

## The question

Can public company data from Companies House, combined with public media data,
be used to predict business needs and inform commercial banking strategy?

The project links structured company records (Companies House) with unstructured
media coverage (news) to look for patterns that point to lending needs, growth,
or risk. Everything here uses public data and free APIs only. No Lloyds internal
data is used.

## Team and workstreams

The work maps onto the three aims the bank cares about:

- Grow the client base: Vishal and Viktor.
- Defend against attrition (dormant accounts, closures, and bank supplier
  changes): Sam.
- Deepen relationships with existing clients: Sneha.

This branch holds the shared data pipeline and the attrition workstream.

## Data sources

- Companies House. The structured base. The full monthly bulk file (about 5.7
  million UK companies) plus the live REST API for charges, filing history, and
  officers. Free, public, Open Government Licence.
- GDELT. A free global news index, used to find news coverage of a company by
  name. No key needed.

## Repository layout

```
notebooks/        exploratory notebooks (the original Companies House EDA)
src/
  data_collection/  shared pipeline: SIC lookup, static dataset, news
  attrition/        the attrition workstream (Sam)
tests/            unit tests for the pure logic (46 tests)
reports/          generated summaries and figures
data/             raw and processed data (gitignored, not in the repo)
```

## Setup

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env     # paste your Companies House REST API key
```

The bulk Companies House file is large and is not in git. Download it from
https://download.companieshouse.gov.uk/en_output.html and unzip the CSV into
`data/raw/`.

## How to run

```
# tests (no data or key needed)
.venv/Scripts/python -m unittest discover -s tests -v

# 1. Build the agreed static dataset (three sectors, BB and SME) and a sample
.venv/Scripts/python -m src.data_collection.build_static_dataset --sample 100

# 2. Link the sample to news and build the first joined dataset
.venv/Scripts/python -m src.data_collection.build_joined_dataset

# 3. Attrition: baseline rates, bank signals, and filing-history labels
.venv/Scripts/python -m src.attrition.run_bulk_eda
.venv/Scripts/python -m src.attrition.sample_companies --n 500
.venv/Scripts/python -m src.attrition.enrich_charges
.venv/Scripts/python -m src.attrition.sample_companies --strata status --n 600 \
    --out data/processed/attrition_status_sample.csv
.venv/Scripts/python -m src.attrition.build_attrition_labels \
    --sample data/processed/attrition_status_sample.csv
```

## What we have done so far

Companies House side:
- Loaded and described the full bulk file (5,698,274 companies).
- Built a reusable feature layer: company status to an attrition state, dormancy
  flag, size band from the account category, SIC code to a Lloyds target sector,
  and filing punctuality.
- Built the agreed static dataset to the criteria the group set (Technology legal
  and professional, Manufacturing, Fast growth and emerging; BB and SME turnover;
  still trading). Result: 824,632 companies.

News side:
- Built a free GDELT news client and a first joined company plus news dataset.

Attrition side (Sam):
- Built and tested signals for the three kinds of attrition (dormancy, closure,
  and bank supplier change) using charges and filing history from the API.

## Key findings so far

- Charges, and so the bank relationship signal, only really exist in larger
  firms. The share of companies with any charge rises from 10.9% (BB) to 27.1%
  (SME), 62.5% (Large), and 83.2% (Midcorporate).
- Distress varies by sector. Wholesale and retail has the highest distress rate
  of the target sectors (11.5%), then Manufacturing (10.3%).
- A bank supplier switch (one bank dropped, another picked up) is visible in
  about 12.5% of firms that hold a bank charge. This is the clearest competitive
  attrition signal.
- A bank loss does not predict company distress. In the 24 months before a
  distress event, only 7.2% of firms had lost a bank, against a 5.5% baseline. So
  charge signals are useful to describe attrition, not to predict it.
- News coverage is effectively absent for small firms. Of 100 sampled BB and SME
  companies, none had any GDELT news in the last year. The media side of the
  project only has signal for larger firms.

A practical conclusion: for small firms, the useful attrition signals come from
Companies House itself (filing punctuality, dormancy, status change), and the
media linkage is better aimed at larger firms.

## Limitations

- A single snapshot shows a state, not a change. Real attrition events need the
  time dimension, which we get from filing history and will extend with later
  monthly snapshots.
- Linking news to companies by name is imperfect. Common names cause false
  matches and small firms rarely appear at all. Proper entity resolution is the
  main open problem.
- Account level attrition, where a trading firm closes only its bank account, is
  not visible in public data.

## Notes

- The bulk data, processed datasets, API cache, and the `.env` key are not in
  git. See `.gitignore`.
- Tests cover the pure logic and can run without any data or key.
