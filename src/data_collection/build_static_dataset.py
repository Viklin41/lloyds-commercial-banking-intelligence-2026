"""Build the group's agreed static dataset from Companies House.

This is the shared base dataset the whole team works from, built to the criteria
agreed in the meeting:
  - Sectors: Technology legal and professional, Manufacturing, Fast growth and
    emerging.
  - Size (turnover proxy by account category): BB (Business Banking, under about
    3 million) and SME (about 3 to 25 million).
  - Still trading (company status Active).

It reuses the tested feature logic in src/attrition/definitions.py (sector
mapping, size band) so the whole project uses one consistent set of rules. That
module is general purpose despite its folder name.

It writes two files:
  - data/processed/static_dataset.csv: every company that matches the criteria.
  - data/processed/static_dataset_sample.csv: a random sample (default 100) for
    the next step, linking each firm to the news API. The meeting asked for a
    sample of 50 to 100 companies for that.

Run (from the repo root, with the venv):
    .venv/Scripts/python -m src.data_collection.build_static_dataset --sample 100
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.attrition import definitions as d
from src.attrition.run_bulk_eda import (
    load_bulk, add_derived, find_default_csv, snapshot_date_from_name,
)

# The three sectors the group agreed to focus on.
AGREED_SECTORS = [d.SECTOR_TECH_PROF, d.SECTOR_MANUFACTURING, d.SECTOR_FAST_GROWTH]
# The two turnover bands the group agreed to keep.
AGREED_SIZES = [d.BB, d.SME]

KEEP_COLS = [
    "CompanyNumber",
    "CompanyName",
    "sector",
    "size_band",
    "attrition_status",
    "Accounts.AccountCategory",
    "SICCode.SicText_1",
    "IncorporationDate",
    "age_years",
    "has_charges",
    "Mortgages.NumMortCharges",
]

FULL_OUT = Path("data/processed/static_dataset.csv")
SAMPLE_OUT = Path("data/processed/static_dataset_sample.csv")


def build_static(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the agreed sector, size, and trading-status filters."""
    mask = (
        df["sector"].isin(AGREED_SECTORS)
        & df["size_band"].isin(AGREED_SIZES)
        & (df["attrition_status"] == d.HEALTHY)  # still trading
    )
    out = df.loc[mask, [c for c in KEEP_COLS if c in df.columns]].copy()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="Path to the bulk CSV")
    ap.add_argument("--sample", type=int, default=100, help="Companies for the news step")
    ap.add_argument("--seed", type=int, default=42, help="Random seed")
    args = ap.parse_args()

    csv_path = args.csv or find_default_csv()
    as_of = snapshot_date_from_name(csv_path)

    print(f"Loading {csv_path} ...")
    df = load_bulk(csv_path)
    print(f"Loaded {len(df):,} rows. Adding features ...")
    df = add_derived(df, as_of)

    static = build_static(df)
    FULL_OUT.parent.mkdir(parents=True, exist_ok=True)
    static.to_csv(FULL_OUT, index=False)
    print(f"\nStatic dataset (agreed criteria): {len(static):,} companies -> {FULL_OUT}")
    print("By sector:")
    print(static["sector"].value_counts().to_string())
    print("By size band:")
    print(static["size_band"].value_counts().to_string())

    n = min(args.sample, len(static))
    sample = static.sample(n, random_state=args.seed)
    sample.to_csv(SAMPLE_OUT, index=False)
    print(f"\nSample for the news step: {len(sample):,} companies -> {SAMPLE_OUT}")


if __name__ == "__main__":
    main()
