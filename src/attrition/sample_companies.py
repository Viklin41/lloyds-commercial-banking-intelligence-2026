"""Build a fair sample of companies to study attrition signals from charges.

Why this script exists
----------------------
The baseline EDA showed that bank charges only really appear in SME and larger
firms (micro firms rarely borrow on a secured basis). To measure how often a
company loses or changes its bank, we need companies that actually have charges,
and we need a sample that is not skewed (the first rows of the bulk file are
sorted by name, so they are not representative).

What it does
------------
1. Loads the bulk Companies House snapshot and adds the attrition features from
   definitions.py (reusing the same code as the EDA, so the rules stay in one
   place).
2. Keeps only companies that are worth probing: they have at least one charge,
   they sit in the SME, Midcorp, or Large size band, and they belong to one of
   the eight Lloyds target sectors.
3. Draws a stratified random sample across the size bands so each band is well
   represented, instead of being swamped by the most common one.
4. Saves the chosen companies to data/processed/attrition_sample.csv for the
   next script to read. Company numbers are kept as text so leading zeros stay.

Run (from the repo root, with the venv):
    .venv/Scripts/python -m src.attrition.sample_companies --n 500
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.attrition import definitions as d
from src.attrition.run_bulk_eda import load_bulk, add_derived, find_default_csv, snapshot_date_from_name

# Size bands where bank relationships actually exist (micro firms rarely borrow).
TARGET_SIZES = [d.SME, d.MID, d.LARGE]

# Columns we carry forward into the sample for the next step.
KEEP_COLS = [
    "CompanyNumber",
    "CompanyName",
    "sector",
    "size_band",
    "attrition_status",
    "is_distress",
    "is_dormant",
    "accounts_overdue",
    "Mortgages.NumMortCharges",
    "Mortgages.NumMortOutstanding",
    "Mortgages.NumMortSatisfied",
]

OUT_PATH = Path("data/processed/attrition_sample.csv")


def build_population(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to companies worth probing for bank attrition."""
    mask = (
        df["has_charges"]
        & df["size_band"].isin(TARGET_SIZES)
        & (df["sector"] != d.SECTOR_OTHER)
    )
    return df.loc[mask].copy()


def stratified_sample(pop: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Take a roughly equal number of companies from each size band.

    If a band has fewer companies than its share, we take all of it and spread
    the remainder over the larger bands, so we still reach n where possible.
    """
    bands = [b for b in TARGET_SIZES if (pop["size_band"] == b).any()]
    if not bands:
        return pop.head(0)

    per_band = n // len(bands)
    chosen = []
    shortfall = 0
    for b in bands:
        sub = pop[pop["size_band"] == b]
        take = min(per_band, len(sub))
        shortfall += per_band - take
        chosen.append(sub.sample(take, random_state=seed))

    # Spread any shortfall over the bands that still have spare companies.
    if shortfall > 0:
        already = pd.concat(chosen)
        spare = pop.drop(already.index)
        if len(spare) > 0:
            extra = spare.sample(min(shortfall, len(spare)), random_state=seed)
            chosen.append(extra)

    return pd.concat(chosen).sample(frac=1, random_state=seed)  # shuffle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="Path to the bulk CSV")
    ap.add_argument("--n", type=int, default=500, help="Sample size")
    ap.add_argument("--seed", type=int, default=42, help="Random seed")
    args = ap.parse_args()

    csv_path = args.csv or find_default_csv()
    as_of = snapshot_date_from_name(csv_path)

    print(f"Loading {csv_path} ...")
    df = load_bulk(csv_path)
    print(f"Loaded {len(df):,} rows. Adding features ...")
    df = add_derived(df, as_of)

    pop = build_population(df)
    print(f"Population worth probing (charges + SME/Mid/Large + target sector): {len(pop):,}")
    print("By size band:")
    print(pop["size_band"].value_counts().to_string())

    sample = stratified_sample(pop, args.n, args.seed)
    sample = sample[[c for c in KEEP_COLS if c in sample.columns]]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(sample):,} companies to {OUT_PATH}")
    print("Sample by size band:")
    print(sample["size_band"].value_counts().to_string())
    print("Sample by sector:")
    print(sample["sector"].value_counts().to_string())


if __name__ == "__main__":
    main()
