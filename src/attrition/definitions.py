"""Core attrition definitions for the Companies House bulk snapshot.

Pure Python, no third party dependencies, so it can be unit tested without the
large data file or any installed packages. Every rule here reflects a decision
recorded in docs/ATTRITION_WORKSTREAM.md.

The three attrition sub-problems and the public proxy each maps to:
  - dormancy  -> Accounts.AccountCategory becomes DORMANT (or no accounts)
  - closure   -> CompanyStatus moves to strike-off / insolvency / dissolved
  - switch    -> lender on charges changes over time (handled in ch_api.py, not here)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# 1. Company status -> attrition state (the "closure" axis)
# ---------------------------------------------------------------------------
# CompanyStatus is a free text field in the bulk file. We collapse it into a
# small set of attrition states. Distress states are ordered worst-last so a
# single severity can be derived if needed.

HEALTHY = "healthy_active"
STRIKE_OFF = "strike_off_risk"
INSOLVENCY = "insolvency"
DISSOLVED = "dissolved"
STATUS_OTHER = "other"

# Lower-cased exact matches taken from the live status vocabulary.
_INSOLVENCY_STATUSES = {
    "liquidation",
    "in administration",
    "in administration/administrative receiver",
    "administration order",
    "voluntary arrangement",
    "live but receiver manager on at least one charge",
    "receivership",
}


def classify_status(company_status: Optional[str]) -> str:
    """Map a raw CompanyStatus string to an attrition state.

    Unknown or missing values map to STATUS_OTHER rather than guessing.
    """
    if company_status is None:
        return STATUS_OTHER
    s = company_status.strip().lower()
    if s == "":
        return STATUS_OTHER
    if s == "active":
        return HEALTHY
    if "proposal to strike off" in s or "strike-off" in s or "strike off" in s:
        return STRIKE_OFF
    if "dissolved" in s:
        return DISSOLVED
    if s in _INSOLVENCY_STATUSES or "administration" in s or "liquidation" in s:
        return INSOLVENCY
    return STATUS_OTHER


def is_distress_status(company_status: Optional[str]) -> bool:
    """True if the status is any non-healthy, non-other attrition state."""
    return classify_status(company_status) in {STRIKE_OFF, INSOLVENCY, DISSOLVED}


# ---------------------------------------------------------------------------
# 2. Accounts category -> dormancy flag and size band (the "dormancy" axis)
# ---------------------------------------------------------------------------
# Account category is a coarse proxy. Post 6 April 2025 thresholds:
#   micro:  turnover < 1m,  small: < 15m,  medium: < 54m.
# Lloyds BCB segments by turnover: BB < 3m, SME 3-25m, Midcorp 25-500m.
# The mapping below is intentionally conservative and documented as a proxy.

DORMANT = "dormant"
NO_ACCOUNTS = "no_accounts"
TRADING = "trading"

_DORMANT_CATEGORIES = {"dormant"}
_NO_ACCOUNTS_CATEGORIES = {"no accounts filed", "accounts type not available"}


def classify_accounts_activity(account_category: Optional[str]) -> str:
    """Return TRADING, DORMANT, or NO_ACCOUNTS from Accounts.AccountCategory."""
    if account_category is None:
        return NO_ACCOUNTS
    c = account_category.strip().lower()
    if c == "":
        return NO_ACCOUNTS
    if c in _DORMANT_CATEGORIES:
        return DORMANT
    if c in _NO_ACCOUNTS_CATEGORIES:
        return NO_ACCOUNTS
    return TRADING


# Size band proxy. Categories that imply a larger filer map upward. Categories
# that carry no size information (dormant, no accounts, subsidiary exemptions)
# map to UNKNOWN so they are not misread as small.
BB = "BB"            # micro / very small, broadly Business Banking (< ~3m)
SME = "SME"          # small filers (3-25m bracket, approximate)
MID = "Midcorp"      # medium accounts (25-500m bracket, approximate)
LARGE = "Large"      # full / group filers, often above the BCB sweet spot
SIZE_UNKNOWN = "unknown"

_SIZE_MAP = {
    "micro entity": BB,
    "total exemption small": BB,
    "small": SME,
    "total exemption full": SME,
    "unaudited abridged": SME,
    "audited abridged": SME,
    "medium": MID,
    "full": LARGE,
    "group": LARGE,
}


def size_band(account_category: Optional[str]) -> str:
    """Map account category to an approximate Lloyds size band proxy."""
    if account_category is None:
        return SIZE_UNKNOWN
    return _SIZE_MAP.get(account_category.strip().lower(), SIZE_UNKNOWN)


# ---------------------------------------------------------------------------
# 3. SIC code -> UK SIC section -> Lloyds target sector
# ---------------------------------------------------------------------------
# Bulk file SIC fields look like "62020 - Information technology consultancy".
# We work from the 5 digit code, take the 2 digit division, then the section.

import re

_SIC_CODE_RE = re.compile(r"(\d{5})")


def extract_sic_code(sic_text: Optional[str]) -> Optional[str]:
    """Pull the 5 digit SIC code out of a bulk-file SIC string."""
    if not sic_text:
        return None
    m = _SIC_CODE_RE.search(sic_text)
    return m.group(1) if m else None


def sic_division(sic_code: Optional[str]) -> Optional[int]:
    """First two digits of a 5 digit SIC code, as an int."""
    if not sic_code or len(sic_code) < 2 or not sic_code[:2].isdigit():
        return None
    return int(sic_code[:2])


# UK SIC 2007 section letter by division range.
_SECTION_RANGES = [
    ("A", 1, 3), ("B", 5, 9), ("C", 10, 33), ("D", 35, 35), ("E", 36, 39),
    ("F", 41, 43), ("G", 45, 47), ("H", 49, 53), ("I", 55, 56), ("J", 58, 63),
    ("K", 64, 66), ("L", 68, 68), ("M", 69, 75), ("N", 77, 82), ("O", 84, 84),
    ("P", 85, 85), ("Q", 86, 88), ("R", 90, 93), ("S", 94, 96), ("T", 97, 98),
    ("U", 99, 99),
]


def sic_section(sic_code: Optional[str]) -> Optional[str]:
    """Map a 5 digit SIC code to its UK SIC 2007 section letter."""
    div = sic_division(sic_code)
    if div is None:
        return None
    for letter, lo, hi in _SECTION_RANGES:
        if lo <= div <= hi:
            return letter
    return None


# Lloyds target sectors (the eight from the brief), plus OTHER.
SECTOR_MANUFACTURING = "Manufacturing"
SECTOR_PUBLIC = "Public sector, education & charities"
SECTOR_HEALTHCARE = "Healthcare"
SECTOR_TECH_PROF = "Technology, legal & professional"
SECTOR_AGRICULTURE = "Agriculture"
SECTOR_REAL_ESTATE = "Real estate"
SECTOR_WHOLESALE_RETAIL = "Wholesale & retail"
SECTOR_FAST_GROWTH = "Fast growth & emerging"
SECTOR_OTHER = "Other"

# Section letter -> target sector for the straightforward cases.
_SECTION_TO_SECTOR = {
    "C": SECTOR_MANUFACTURING,
    "A": SECTOR_AGRICULTURE,
    "G": SECTOR_WHOLESALE_RETAIL,
    "L": SECTOR_REAL_ESTATE,
    "Q": SECTOR_HEALTHCARE,
    "O": SECTOR_PUBLIC,
    "P": SECTOR_PUBLIC,
    "J": SECTOR_TECH_PROF,
    "M": SECTOR_TECH_PROF,
}

# Fast growth and emerging: explicit 5 digit codes (software, data, biotech, fintech
# adjacent). Takes priority over the section mapping, per the team's draft.
_FAST_GROWTH_CODES = {
    "62011", "62012", "62020", "62030", "62090",
    "63110", "63120",
    "72110", "72190", "72200",
    "66190",
}

# Company categories that signal a charity or social enterprise regardless of SIC.
_CHARITY_CATEGORIES = {
    "community interest company",
    "charitable incorporated organisation",
    "scottish charitable incorporated organisation",
    "registered society",
}


def target_sector(
    sic_texts: Iterable[Optional[str]],
    company_category: Optional[str] = None,
) -> str:
    """Assign one Lloyds target sector to a company.

    Rules (documented in ATTRITION_WORKSTREAM.md):
      1. If any SIC code is in the fast-growth list, label Fast growth & emerging.
      2. Else, if the company type is a charity/social enterprise, label Public.
      3. Else, use the section of the first SIC code that maps to a target sector,
         scanning the provided SIC codes in order (primary SIC first).
      4. Else, Other.
    """
    codes = [extract_sic_code(t) for t in sic_texts]
    codes = [c for c in codes if c]

    # Rule 1: fast-growth override.
    if any(c in _FAST_GROWTH_CODES for c in codes):
        return SECTOR_FAST_GROWTH

    # Rule 2: charity / social enterprise by company type.
    if company_category and company_category.strip().lower() in _CHARITY_CATEGORIES:
        return SECTOR_PUBLIC

    # Rule 3: first mappable section wins (primary SIC first).
    for c in codes:
        sector = _SECTION_TO_SECTOR.get(sic_section(c))
        if sector:
            return sector

    return SECTOR_OTHER


# ---------------------------------------------------------------------------
# 4. Filing punctuality (a leading distress signal for dormancy and closure)
# ---------------------------------------------------------------------------

def _coerce_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        v = value.strip()
        if v == "":
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        return None
    return None


def days_overdue(next_due, as_of) -> Optional[int]:
    """Days a filing is overdue as of a reference date.

    Positive means overdue, zero or negative means not yet due. Returns None if
    either date is missing or unparseable.
    """
    due = _coerce_date(next_due)
    ref = _coerce_date(as_of)
    if due is None or ref is None:
        return None
    return (ref - due).days


def is_overdue(next_due, as_of, grace_days: int = 0) -> Optional[bool]:
    """True if a filing is overdue by more than grace_days as of a date."""
    d = days_overdue(next_due, as_of)
    if d is None:
        return None
    return d > grace_days
