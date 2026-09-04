"""Live Companies House API enrichment for the sampled companies.

Lifts the officer / filing / charge / lender logic from notebooks 06 and 04 into
importable functions. Requires a CH API key in the environment (``CH_API_KEY``, or
the legacy ``COMPANIES_HOUSE_API_KEY`` the notebooks used). With no key, callers
should skip enrichment - every consumer here raises if asked to call the API keyless.
"""

from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

BASE_URL = "https://api.company-information.service.gov.uk"

# 18-month lookback for "recent" officer changes and growth filings (matches NB06).
RECENT_CUTOFF_MONTHS = 18

# Filing types that signal a capital raise / restructure (NB06).
GROWTH_FILING_TYPES = {"SH01": "Shares allotted (capital raise)", "SH06": "Share capital reduction"}

# Lloyds-linked security-holder name keywords (NB04).
LLOYDS_KEYWORDS = [
    "lloyds bank",
    "bank of scotland",
    "halifax",
    "scottish widows",
    "mbna",
    "lloyds banking group",
    "hbos",
]

# Columns produced per company, with their sentinel value when a company is not enriched.
API_FEATURE_SENTINELS = {
    "active_directors": pd.NA,
    "recent_director_appointments": pd.NA,
    "recent_director_resignations": pd.NA,
    "has_recent_director_change": False,
    "recent_growth_filings": pd.NA,
    "has_recent_growth_filing": False,
    "accounts_filings_count": pd.NA,
    "last_accounts_filing_date": pd.NaT,
    "charges_outstanding": pd.NA,
    "charges_total": pd.NA,
    "has_lloyds_linked_lender": False,
    "has_other_lender": False,
    "lender_names_api": "Not checked by API",
    "lender_groups_api": "Not checked by API",
    "lender_check_status": "Not checked by API",
}


def get_api_key() -> str | None:
    return os.getenv("CH_API_KEY") or os.getenv("COMPANIES_HOUSE_API_KEY") or None


def has_api_key() -> bool:
    return bool(get_api_key())


def ch_get(path: str, params: dict | None = None):
    """GET a CH API path. Returns parsed JSON, or None on 404. Raises if no key."""
    key = get_api_key()
    if not key:
        raise ValueError("No Companies House API key found (set CH_API_KEY in .env).")

    resp = requests.get(
        BASE_URL + path,
        params=params,
        auth=HTTPBasicAuth(key, ""),  # key as username, blank password
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _paged(path: str, total_key: str, per_page: int = 100, max_items: int = 500) -> list:
    items, start = [], 0
    while True:
        data = ch_get(path, params={"items_per_page": per_page, "start_index": start})
        if data is None:
            break
        page = data.get("items", [])
        items.extend(page)
        total = data.get(total_key, len(items))
        start += per_page
        if not page or start >= total or len(items) >= max_items:
            break
    return items


def summarise_officer_changes(company_number: str, cutoff: pd.Timestamp) -> dict:
    active = appointed = resigned = 0
    for o in _paged(f"/company/{company_number}/officers", "total_results"):
        is_dir = "director" in str(o.get("officer_role", "")).lower()
        if not is_dir:
            continue
        a = pd.to_datetime(o.get("appointed_on"), errors="coerce")
        r = pd.to_datetime(o.get("resigned_on"), errors="coerce")
        if pd.isna(r):
            active += 1
        if pd.notna(a) and a >= cutoff:
            appointed += 1
        if pd.notna(r) and r >= cutoff:
            resigned += 1
    return {
        "active_directors": active,
        "recent_director_appointments": appointed,
        "recent_director_resignations": resigned,
        "has_recent_director_change": (appointed > 0) or (resigned > 0),
    }


def summarise_filings(company_number: str, cutoff: pd.Timestamp) -> dict:
    recent_growth = 0
    accounts_count = 0
    last_accounts_date = pd.NaT
    for f in _paged(f"/company/{company_number}/filing-history", "total_count"):
        ftype = f.get("type")
        fcat = str(f.get("category", "")).lower()
        fdate = pd.to_datetime(f.get("date"), errors="coerce")
        if ftype in GROWTH_FILING_TYPES and pd.notna(fdate) and fdate >= cutoff:
            recent_growth += 1
        if fcat == "accounts":
            accounts_count += 1
            if pd.notna(fdate) and (pd.isna(last_accounts_date) or fdate > last_accounts_date):
                last_accounts_date = fdate
    return {
        "recent_growth_filings": recent_growth,
        "has_recent_growth_filing": recent_growth > 0,
        "accounts_filings_count": accounts_count,
        "last_accounts_filing_date": last_accounts_date,
    }


def classify_lender_name(lender_name: str) -> str:
    lower = str(lender_name).lower()
    if any(k in lower for k in LLOYDS_KEYWORDS):
        return "Lloyds-linked lender"
    return "Other lender"


def summarise_charges(company_number: str) -> dict:
    """One /charges call → both health counts (NB06) and lender classification (NB04)."""
    data = ch_get(f"/company/{company_number}/charges")
    items = [] if data is None else data.get("items", [])

    outstanding = sum(1 for c in items if str(c.get("status", "")).lower() == "outstanding")

    lender_names, lender_groups = set(), set()
    for charge in items:
        for person in charge.get("persons_entitled", []) or []:
            name = person.get("name", "Unknown lender")
            lender_names.add(name)
            lender_groups.add(classify_lender_name(name))

    has_lloyds = "Lloyds-linked lender" in lender_groups
    has_other = "Other lender" in lender_groups

    if not items:
        status = "No charges returned by API"
    elif has_lloyds:
        status = "Lloyds-linked lender found"
    elif has_other:
        status = "Only other lender found"
    else:
        status = "Checked - no clear lender found"

    return {
        "charges_outstanding": outstanding,
        "charges_total": len(items),
        "has_lloyds_linked_lender": has_lloyds,
        "has_other_lender": has_other,
        "lender_names_api": "; ".join(sorted(lender_names)) or "No lender name found",
        "lender_groups_api": "; ".join(sorted(lender_groups)) or "No lender found",
        "lender_check_status": status,
    }


def enrich_company(company_number: str, cutoff: pd.Timestamp) -> dict:
    """All CH-API features for one company. Each block falls back to sentinels on error."""
    rec: dict = {}
    for fn in (
        lambda: summarise_officer_changes(company_number, cutoff),
        lambda: summarise_filings(company_number, cutoff),
        lambda: summarise_charges(company_number),
    ):
        try:
            rec.update(fn())
        except Exception:
            pass  # leave those keys to be sentinel-filled by the caller
    return rec


def enrich_companies(
    subset: pd.DataFrame,
    number_col: str = "CompanyNumber",
    sleep: float = 0.5,
    progress_every: int = 25,
) -> pd.DataFrame:
    """Enrich every row in ``subset``. Returns one row per company with the API features.

    ``subset[number_col]`` must be the 8-digit CH number used for API calls.
    """
    if not has_api_key():
        raise ValueError("Cannot enrich: no Companies House API key. Set CH_API_KEY in .env.")

    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(months=RECENT_CUTOFF_MONTHS)
    rows = []
    for i, (_, c) in enumerate(subset.iterrows(), start=1):
        cn = c[number_col]
        rec = {number_col: cn}
        rec.update(enrich_company(cn, cutoff))
        # fill any block that errored with its sentinel
        for col, sentinel in API_FEATURE_SENTINELS.items():
            rec.setdefault(col, sentinel)
        rows.append(rec)
        if progress_every and i % progress_every == 0:
            print(f"  enriched {i}/{len(subset)}")
        time.sleep(sleep)

    return pd.DataFrame(rows)
