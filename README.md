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

This branch holds the attrition workstream, written as a single self-contained
notebook so the whole analysis can be read in one place.

## Data sources

- Companies House. The structured base. The full monthly bulk file (about 5.7
  million UK companies) plus the live REST API for charges, filing history, and
  officers. Free, public, Open Government Licence.
- GDELT. A free global news index, used to find news coverage of a company by
  name. No key needed.

## Repository layout

```
notebooks/
  attrition_analysis.ipynb   the whole attrition workstream, code and explanation in one notebook
  01_companies_house.ipynb   the team's original Companies House exploration
src/data_collection/
  SIC_converter.py           builds the SIC code lookup table
reports/                     the project brief
data/                        raw and processed data (gitignored, not in the repo)
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

Open `notebooks/attrition_analysis.ipynb` and run the cells top to bottom. It is
self-contained: it explains each step, holds all the code, and shows the results.
You need the bulk file in `data/raw/` and your API key in `.env` (above) for the
live cells; the rest runs on their own.

## What the notebook covers

`notebooks/attrition_analysis.ipynb` runs end to end:

- Loads and describes the full bulk file (5,698,274 companies).
- Turns the raw fields into signals: company status to an attrition state,
  dormancy flag, size band from the account category, SIC code to a Lloyds target
  sector, and filing punctuality.
- Reads the live Companies House service for loans and filing history, and builds
  the signals for the three kinds of attrition (dormancy, closure, and bank
  supplier change), including the bank-switch detector.
- Checks news coverage from GDELT.

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
- The whole workstream lives in `notebooks/attrition_analysis.ipynb`.
