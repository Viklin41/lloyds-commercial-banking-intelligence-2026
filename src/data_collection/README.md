# Data collection (group shared)

Code for the shared parts of the pipeline: building the agreed static dataset
from Companies House and linking each company to news coverage. These follow the
tasks agreed in the team meeting.

## Scripts

- `SIC_converter.py` - turns the SIC code reference into a lookup table
  (code, description, section).
- `build_static_dataset.py` - builds the agreed static dataset from the bulk
  Companies House file: the three sectors (Technology legal and professional,
  Manufacturing, Fast growth and emerging) and the BB and SME turnover bands,
  still trading. Writes the full set and a small sample for the news step.
- `gdelt_news.py` - retrieves news coverage for a company from GDELT (free, no
  key). Includes name cleaning and article parsing.
- `build_joined_dataset.py` - links the static sample to GDELT news and writes
  the first joined company plus news dataset, with basic statistics.

## Inputs (not in git)

- Bulk Companies House file in `data/raw/` (see the attrition README for the
  download link).

## Run order

```
# 1. Build the agreed static dataset and a 100 company sample
.venv/Scripts/python -m src.data_collection.build_static_dataset --sample 100

# 2. Link the sample to news and build the first joined dataset
.venv/Scripts/python -m src.data_collection.build_joined_dataset
```

Outputs go to `data/processed/` (gitignored) and a summary to `reports/news/`.

## Notes

- The sector and size rules live in `src/attrition/definitions.py`, which is
  general purpose despite the folder name, so the whole project uses one
  consistent set of rules. It could be moved to a shared module later.
- GDELT matches on company name, which is imperfect, and small firms rarely
  appear in the news. Expect sparse coverage for BB and SME firms. That is a real
  finding about how far public news reaches, and it points to the need for proper
  entity resolution when linking names to records.
