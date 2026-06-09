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
    "status_class",
    "attrition_status",
    "is_distress",
    "is_dormant",
    "accounts_overdue",
    "Mortgages.NumMortCharges",
    "Mortgages.NumMortOutstanding",
    "Mortgages.NumMortSatisfied",
]

OUT_PATH = Path("data/processed/attrition_sample.csv")


def status_class(row) -> str:
    """A simple outcome class for a company: distress, dormant, or healthy."""
    if row["is_distress"]:
        return "distress"
    if row["is_dormant"]:
        return "dormant"
    return "healthy"


def build_population(df: pd.DataFrame, include_dormant: bool = False) -> pd.DataFrame:
    """Filter to companies worth probing for bank attrition.

    By default we keep SME and larger firms (where bank charges exist). When we
    want a status-balanced sample we also let dormant firms in, because dormant
    accounts carry no size band yet are exactly the attrition cases we want.
    """
    size_ok = df["size_band"].isin(TARGET_SIZES)
    if include_dormant:
        size_ok = size_ok | df["is_dormant"]
    mask = df["has_charges"] & size_ok & (df["sector"] != d.SECTOR_OTHER)
    return df.loc[mask].copy()


def stratified_sample(pop: pd.DataFrame, column: str, n: int, seed: int) -> pd.DataFrame:
    """Take a roughly equal number of companies from each value of `column`.

    If a group has fewer companies than its share, we take all of it and spread
    the remainder over the larger groups, so we still reach n where possible.
    """
    groups = [g for g in pop[column].unique() if (pop[column] == g).any()]
    if not groups:
        return pop.head(0)

    per_group = n // len(groups)
    chosen = []
    shortfall = 0
    for g in groups:
        sub = pop[pop[column] == g]
        take = min(per_group, len(sub))
        shortfall += per_group - take
        chosen.append(sub.sample(take, random_state=seed))

    # Spread any shortfall over the groups that still have spare companies.
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
    ap.add_argument("--strata", choices=["size", "status"], default="size",
                    help="Balance the sample across size bands or across "
                         "outcome classes (healthy/distress/dormant)")
    ap.add_argument("--out", default=str(OUT_PATH), help="Output CSV path")
    args = ap.parse_args()

    csv_path = args.csv or find_default_csv()
    as_of = snapshot_date_from_name(csv_path)

    print(f"Loading {csv_path} ...")
    df = load_bulk(csv_path)
    print(f"Loaded {len(df):,} rows. Adding features ...")
    df = add_derived(df, as_of)
    df["status_class"] = df.apply(status_class, axis=1)

    strat_col = "size_band" if args.strata == "size" else "status_class"
    pop = build_population(df, include_dormant=(args.strata == "status"))
    print(f"Population worth probing: {len(pop):,}")
    print(f"By {strat_col}:")
    print(pop[strat_col].value_counts().to_string())

    sample = stratified_sample(pop, strat_col, args.n, args.seed)
    sample = sample[[c for c in KEEP_COLS if c in sample.columns]]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(out_path, index=False)
    print(f"\nWrote {len(sample):,} companies to {out_path}")
    print(f"Sample by {strat_col}:")
    print(sample[strat_col].value_counts().to_string())
    print("Sample by sector:")
    print(sample["sector"].value_counts().to_string())


if __name__ == "__main__":
    main()
