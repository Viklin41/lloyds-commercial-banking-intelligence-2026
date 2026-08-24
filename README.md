# Lloyds-commercial-banking-intelligence-2026
This project leverages publicly available structured and unstructured data to identify future business needs, risks, and growth opportunities for companies. The project is inspired by real-world commercial banking challenges, where proactive identification of clients' needs can improve retention, growth, and attrition management.

## 1. Instructions on how to use

1. Run `notebooks/01_companies_house.ipynb` to get the bulk dataset (`data/processed/filtered_bb_sme_sectors.csv`) of the current month, filtered by SIC sectors and company size
2.  Run `notebooks/02_companies_var.ipynb` for EDA

## 2. The dashboard

`dashboard/` holds the Companies House Data Store: a search and filter surface over
1,531,094 UK companies, with six evidence sources attached to each company profile.

To run it:

```bash
pip install -r requirements.txt
python dashboard/serve.py --data /path/to/your/data
```

It opens at http://127.0.0.1:8000. The `--data` directory is the tree holding
`processed/` and `raw/`; it lives outside this repository because the files are far too
large to version. `LLOYDS_DATA` works instead of the flag if you prefer an environment
variable, and `serve.py` prints the paths it tried if it cannot find them.

**[`dashboard/dashboard_handbook.md`](dashboard/dashboard_handbook.md) is the guide** —
what every filter and preset does, how the scores are built, what each source can and
cannot tell you, and the exact files the server expects. Read it before using the
numbers for anything. There is a PDF of it in the same folder.

[`dashboard/dashboard_design.md`](dashboard/dashboard_design.md) is the companion for
anyone changing the code: what was planned, what the testing broke, and what we can
actually prove.