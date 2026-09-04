"""Select which companies to send to the live CH APIs.

Mirrors NB06's selection: active companies only, outstanding-charge companies first,
capped at ``n`` (the config knob). Keeps ``CompanyNumber`` verbatim and adds an 8-digit
``_join_key`` used both for the API calls and for merging the results back.
"""

from __future__ import annotations

import pandas as pd

JOIN_KEY = "_join_key"


def build_api_sample(
    base: pd.DataFrame,
    n: int = 1000,
    number_col: str = "CompanyNumber",
    name_col: str = "CompanyName",
) -> pd.DataFrame:
    """Return the top-``n`` prioritized companies to enrich.

    Priority: outstanding-charge companies (``Mortgages.NumMortOutstanding`` > 0) first.
    """
    active = base[base["CompanyStatus"].astype(str).str.lower() == "active"].copy()

    outstanding = pd.to_numeric(
        active.get("Mortgages.NumMortOutstanding"), errors="coerce"
    ).fillna(0)
    active["_priority"] = (outstanding > 0).astype(int)

    subset = (
        active.sort_values("_priority", ascending=False)[[name_col, number_col]]
        .drop_duplicates()
        .head(n)
        .reset_index(drop=True)
    )
    subset[JOIN_KEY] = subset[number_col].astype(str).str.strip().str.upper().str.zfill(8)
    return subset
