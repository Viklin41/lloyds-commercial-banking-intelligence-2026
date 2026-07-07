"""Static features - computable for ALL companies straight from the base CSV.

Every function takes a DataFrame with **stripped** column names (see ``strip_columns``)
and returns the same DataFrame with new columns added. Formulas match the sneha
notebooks 04_exiting_relationships and 06_director_changes exactly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Size tiers among NB01's segment labels; the rest (No Filings/Dormant/Subsidiary/Unknown)
# are filing-status buckets, not size tiers
SIZE_TIERS = {"Micro", "Small", "Medium", "Large"}

CHARGE_COLS = [
    "Mortgages.NumMortCharges",
    "Mortgages.NumMortOutstanding",
    "Mortgages.NumMortSatisfied",
    "Mortgages.NumMortPartSatisfied",
]

PREV_NAME_COLS = [f"PreviousName_{i}.CompanyName" for i in range(1, 11)]

STATIC_FEATURE_COLS = [
    "company_age_years",
    "has_any_charge",
    "has_outstanding_charges",
    "debt_ratio",
    "accounts_overdue",
    "accounts_stale",
    "size_tier",
    "num_previous_names",
    "has_name_change",
]


def strip_columns(df: pd.DataFrame) -> pd.DataFrame:
    """The bulk CSV ships some headers with leading spaces; normalise them in place."""
    df.columns = df.columns.str.strip()
    return df


def add_company_age(df: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """company_age_years from IncorporationDate (NB04 formula)."""
    today = today or pd.Timestamp.today().normalize()
    if "IncorporationDate" in df.columns:
        inc = pd.to_datetime(df["IncorporationDate"], errors="coerce", dayfirst=True)
        df["company_age_years"] = ((today - inc).dt.days / 365.25).round(1)
    else:
        df["company_age_years"] = np.nan
    return df


def add_charge_features(df: pd.DataFrame) -> pd.DataFrame:
    """has_any_charge, has_outstanding_charges, debt_ratio (NB04 formula)."""
    for col in CHARGE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = 0

    charges = df["Mortgages.NumMortCharges"]
    outstanding = df["Mortgages.NumMortOutstanding"]

    df["has_any_charge"] = charges > 0
    df["has_outstanding_charges"] = outstanding > 0
    df["debt_ratio"] = np.where(charges > 0, outstanding / charges, 0).round(2)
    return df


def add_accounts_flags(df: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """accounts_overdue, accounts_stale from the accounts due-date columns (NB06 formula)."""
    today = today or pd.Timestamp.today().normalize()
    stale_cutoff = today - pd.DateOffset(months=24)

    next_due = pd.to_datetime(df.get("Accounts.NextDueDate"), errors="coerce", dayfirst=True)
    last_made_up = pd.to_datetime(df.get("Accounts.LastMadeUpDate"), errors="coerce", dayfirst=True)

    df["accounts_overdue"] = next_due < today
    df["accounts_stale"] = last_made_up.isna() | (last_made_up < stale_cutoff)
    return df


def add_size_tier(df: pd.DataFrame) -> pd.DataFrame:
    """size_tier = segment where it names a real size tier, else <NA> (reuses NB01 SEGMENT_MAP)."""
    if "segment" in df.columns:
        seg = df["segment"].astype("string")
        df["size_tier"] = seg.where(seg.isin(SIZE_TIERS), other=pd.NA)
    else:
        df["size_tier"] = pd.NA
    return df


def add_name_change(df: pd.DataFrame) -> pd.DataFrame:
    """num_previous_names / has_name_change from the PreviousName_*.CompanyName columns."""
    present = [c for c in PREV_NAME_COLS if c in df.columns]
    if present:
        df["num_previous_names"] = df[present].notna().sum(axis=1)
    else:
        df["num_previous_names"] = 0
    df["has_name_change"] = df["num_previous_names"] > 0
    return df


def add_static_features(df: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Add every static feature. df is modified in place and returned."""
    today = today or pd.Timestamp.today().normalize()
    add_company_age(df, today)
    add_charge_features(df)
    add_accounts_flags(df, today)
    add_size_tier(df)
    add_name_change(df)
    return df
