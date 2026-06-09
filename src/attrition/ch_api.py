"""Companies House API client for attrition signals.

Focus: charges (secured lending and the lender behind it) and filing history
(dormancy and closure transitions). These are the signals the bulk snapshot
cannot provide.

Auth: the Companies House REST API uses HTTP Basic auth with the API key as the
username and an empty password. Get a free key at
https://developer.company-information.service.gov.uk/manage-applications/add and
put it in a local .env file as CH_API_KEY=...

Rate limit: 600 requests per 5 minutes. This client throttles to stay under it
and retries on HTTP 429.

The pure analysis helpers (parse_charges, lender_timeline, detect_switch) take
plain dictionaries, so they are unit tested without any network or install.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

BASE_URL = "https://api.company-information.service.gov.uk"

# 600 requests / 300 seconds = 0.5s minimum spacing. Add headroom.
_MIN_INTERVAL_SECONDS = 0.6


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------
def load_api_key(env_path: Optional[str] = None) -> str:
    """Load CH_API_KEY from the environment or a .env file.

    Raises a clear error if the key is missing, so set-up problems are obvious.
    """
    key = os.getenv("CH_API_KEY")
    if not key:
        # Try python-dotenv if available, then fall back to a tiny parser.
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv(env_path)
            key = os.getenv("CH_API_KEY")
        except Exception:
            key = _read_env_file(env_path)
    if not key:
        raise RuntimeError(
            "CH_API_KEY not found. Create a .env file with "
            "CH_API_KEY=your_key (see the docstring for where to get one)."
        )
    return key


def _read_env_file(env_path: Optional[str]) -> Optional[str]:
    path = Path(env_path) if env_path else Path(".env")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("CH_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class CompaniesHouseClient:
    """Thin, polite client with on-disk caching and rate limiting."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: str = "data/raw/api_cache",
        min_interval: float = _MIN_INTERVAL_SECONDS,
    ):
        self.api_key = api_key or load_api_key()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last_call = 0.0
        self._session = None  # lazy, so importing this module needs no requests

    def _get_session(self):
        if self._session is None:
            import requests  # lazy import

            s = requests.Session()
            s.auth = (self.api_key, "")
            self._session = s
        return self._session

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()

    def _cache_path(self, key: str) -> Path:
        # Keep only filename-safe characters (Windows forbids ? & = % etc).
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", key).strip("_")
        return self.cache_dir / f"{safe}.json"

    def _get(self, path: str, use_cache: bool = True) -> Optional[dict]:
        """GET an API path, with caching. Returns parsed JSON or None on 404."""
        cache_file = self._cache_path(path)
        if use_cache and cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        session = self._get_session()
        url = f"{BASE_URL}{path}"
        for attempt in range(5):
            self._throttle()
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if use_cache:
                    cache_file.write_text(json.dumps(data), encoding="utf-8")
                return data
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                # Rate limited: back off and retry.
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Giving up on {url} after repeated rate limiting")

    # --- endpoints -------------------------------------------------------
    def search_companies(self, query: str, items: int = 1) -> list:
        """Search companies by name. Returns the raw 'items' list (top matches)."""
        from urllib.parse import quote

        data = self._get(
            f"/search/companies?q={quote(query)}&items_per_page={items}",
            use_cache=False,
        )
        return data.get("items", []) if data else []

    def get_company(self, company_number: str) -> Optional[dict]:
        return self._get(f"/company/{company_number}")

    def get_charges(self, company_number: str) -> Optional[dict]:
        return self._get(f"/company/{company_number}/charges")

    def get_filing_history(self, company_number: str) -> Optional[dict]:
        return self._get(f"/company/{company_number}/filing-history")

    def get_officers(self, company_number: str) -> Optional[dict]:
        return self._get(f"/company/{company_number}/officers")


# ---------------------------------------------------------------------------
# Pure analysis helpers (no network) - unit tested
# ---------------------------------------------------------------------------
def parse_charges(charges_response: Optional[dict]) -> list:
    """Flatten a /charges response into simple per-charge dicts.

    Each item: {created_on, satisfied_on, status, classification, lenders}.
    """
    if not charges_response:
        return []
    out = []
    for item in charges_response.get("items", []):
        lenders = [
            p.get("name", "").strip()
            for p in item.get("persons_entitled", [])
            if p.get("name")
        ]
        classification = ""
        cls = item.get("classification")
        if isinstance(cls, dict):
            classification = cls.get("description", "")
        out.append(
            {
                "created_on": item.get("created_on"),
                "satisfied_on": item.get("satisfied_on"),
                "status": item.get("status"),  # outstanding / satisfied / part-satisfied
                "classification": classification,
                "lenders": lenders,
            }
        )
    return out


def lender_timeline(charges: list) -> list:
    """Charges sorted by creation date, each with its lenders and active window.

    Returns a list of (created_on, satisfied_on, lender, status) tuples, one per
    lender per charge, ordered by created_on. Useful for spotting a switch.
    """
    rows = []
    for c in charges:
        for lender in c["lenders"] or [""]:
            rows.append(
                (c.get("created_on") or "", c.get("satisfied_on"), lender, c.get("status"))
            )
    rows.sort(key=lambda r: r[0])
    return rows


# Charge status vocabulary used by the API. A charge still owed is "outstanding"
# or "part-satisfied"; a cleared charge is "satisfied" or "fully-satisfied".
OUTSTANDING_STATUSES = {"outstanding", "part-satisfied"}
SATISFIED_STATUSES = {"satisfied", "fully-satisfied"}


def is_outstanding(charge: dict) -> bool:
    return (charge.get("status") or "").lower() in OUTSTANDING_STATUSES


def is_satisfied(charge: dict) -> bool:
    return (charge.get("status") or "").lower() in SATISFIED_STATUSES


# Major UK banking groups: map any subsidiary name containing a keyword to the
# group, so 'Hsbc Equipment Finance' and 'Hsbc UK Bank' both become HSBC. This is
# a coarse entity resolution on the lender side; it reduces false switch signals
# between subsidiaries of the same group.
_BANK_GROUPS = {
    "LLOYDS": ("lloyds", "bank of scotland", "halifax", "hbos", "black horse", "mbna"),
    "HSBC": ("hsbc", "midland bank"),
    "BARCLAYS": ("barclays",),
    "NATWEST": (
        "natwest", "national westminster", "royal bank of scotland", "rbs",
        "ulster bank", "coutts", "lombard north",
    ),
    "SANTANDER": ("santander", "abbey national"),
    "NATIONWIDE": ("nationwide",),
    "VIRGIN MONEY": ("virgin money", "clydesdale", "yorkshire bank", "cybg"),
    "TSB": ("tsb",),
    "METRO BANK": ("metro bank",),
    "CO-OPERATIVE BANK": ("co-operative bank", "co-op bank"),
    "ALDERMORE": ("aldermore",),
    "SHAWBROOK": ("shawbrook",),
    "CLOSE BROTHERS": ("close brothers",),
}


def _normalise_lender(name: str) -> str:
    """Normalise a lender name to a banking group where possible.

    Falls back to a suffix-stripped upper-case name for non-bank or unknown
    lenders, so 'Barclays Bank PLC' ~ 'BARCLAYS BANK PLC.'.
    """
    low = name.lower()
    for group, keywords in _BANK_GROUPS.items():
        if any(k in low for k in keywords):
            return group
    n = name.upper().strip().rstrip(".")
    for suffix in (" PLC", " LIMITED", " LTD", " LLP"):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    return n


# Markers that a "person entitled" is a security trustee or agent acting for a
# syndicate or bondholders, not the lender itself. These dominate large/complex
# debt and must be stripped before reading a bank-supplier change.
_AGENT_MARKERS = (
    "security agent", "security trustee", "as trustee", "as security",
    "nominee", "fiduciary", "trust corporation", "trustees limited",
    "trustee company", "as agent",
)

LENDER_BANK = "bank"
LENDER_AGENT = "security_agent"
LENDER_OTHER = "other"  # non-bank lender, PE/credit fund, landlord, individual


def lender_type(name: str) -> str:
    """Classify a charge holder as a bank, a security agent, or other."""
    low = name.lower()
    for keywords in _BANK_GROUPS.values():
        if any(k in low for k in keywords):
            return LENDER_BANK
    if any(m in low for m in _AGENT_MARKERS):
        return LENDER_AGENT
    return LENDER_OTHER


def _bank_set(charges: list, status_pred) -> set:
    """Recognised banking groups among lenders matching a status predicate."""
    out = set()
    for c in charges:
        if not status_pred(c):
            continue
        for l in c["lenders"]:
            if l and lender_type(l) == LENDER_BANK:
                out.add(_normalise_lender(l))
    return out


def detect_bank_switch(charges: list) -> dict:
    """Bank-supplier change restricted to recognised banks.

    Ignores security agents, PE/credit funds, landlords, and individuals, so the
    signal reflects a genuine move between high-street/commercial banks. A bank
    is "lost" if its charge is cleared and it holds no outstanding charge, and a
    different bank is "gained" on an outstanding charge.
    """
    current = _bank_set(charges, is_outstanding)
    past = _bank_set(charges, is_satisfied)
    lost = past - current
    gained = current - past
    return {
        # Clean A -> B switch: a bank dropped and a different bank picked up.
        "bank_switch": bool(lost) and bool(gained),
        # More common and arguably stronger attrition signal: had bank charges,
        # now holds no outstanding bank charge at all.
        "lost_all_banks": bool(past) and not current,
        # Reduced the number of bank relationships (consolidation).
        "reduced_banks": len(lost) > 0,
        "banks_lost": sorted(lost),
        "banks_gained": sorted(gained),
        "current_banks": sorted(current),
        "past_banks": sorted(past),
        "n_current_banks": len(current),
        "n_past_banks": len(past),
    }


def _parse_iso(value):
    """Parse a 'YYYY-MM-DD' string to a date, or return None."""
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _months_between(later, earlier) -> "float | None":
    """Approximate months between two dates (later minus earlier)."""
    a, b = _parse_iso(later) if isinstance(later, str) else later, \
        _parse_iso(earlier) if isinstance(earlier, str) else earlier
    if a is None or b is None:
        return None
    return (a - b).days / 30.44


def bank_loss_date(charges: list):
    """Date the company most recently lost a bank (latest satisfied bank charge
    whose bank is no longer among its outstanding banks). Returns ISO str or None.
    """
    current = current_lenders_banks(charges)
    dates = []
    for c in charges:
        if not is_satisfied(c):
            continue
        for l in c["lenders"]:
            if l and lender_type(l) == LENDER_BANK:
                grp = _normalise_lender(l)
                if grp not in current and c.get("satisfied_on"):
                    dates.append(c["satisfied_on"])
    return max(dates) if dates else None


def recent_bank_loss(charges: list, as_of: str, months: int = 24) -> bool:
    """True if the company has lost all its banks and the loss is recent.

    "Recent" means the latest lost-bank charge was satisfied within `months` of
    the reference date. A fresh loss is a sharper attrition signal than an old one.
    """
    bs = detect_bank_switch(charges)
    if not bs["lost_all_banks"]:
        return False
    loss = bank_loss_date(charges)
    gap = _months_between(as_of, loss)
    return gap is not None and 0 <= gap <= months


def current_lenders_banks(charges: list) -> set:
    """Banks (grouped) on charges still owed. Bank-only version of current_lenders."""
    return _bank_set(charges, is_outstanding)


def current_lenders(charges: list) -> set:
    """Distinct lenders (grouped) on charges still owed."""
    return {
        _normalise_lender(l)
        for c in charges
        if is_outstanding(c)
        for l in c["lenders"]
        if l
    }


def past_lenders(charges: list) -> set:
    """Distinct lenders (grouped) whose charges are cleared (paid off)."""
    return {
        _normalise_lender(l)
        for c in charges
        if is_satisfied(c)
        for l in c["lenders"]
        if l
    }


def detect_switch(charges: list) -> dict:
    """Heuristic for a bank supplier change from a single charges pull.

    Signal: at least one lender's charge has been satisfied (a credit
    relationship ended) and a different lender now holds an outstanding charge
    (a new relationship began). Both being true is consistent with a switch of
    secured lender between banks.

    Returns a dict with the boolean flag and the lender sets, so the caller can
    inspect direction. This only sees secured lending, not current accounts.
    """
    current = current_lenders(charges)
    past = past_lenders(charges)
    gained = current - past
    lost = past - current
    switched = bool(lost) and bool(gained)
    return {
        "switched": switched,
        "lost_lenders": sorted(lost),
        "gained_lenders": sorted(gained),
        "current_lenders": sorted(current),
        "past_lenders": sorted(past),
    }


# ---------------------------------------------------------------------------
# Filing history: the time dimension for a real attrition label
# ---------------------------------------------------------------------------
# A single snapshot shows a state, not a change. The filing history endpoint
# lists a company's filings over time, so we can date when it first showed signs
# of dormancy or closure. That lets us build an attrition event timeline without
# waiting for a second snapshot.

def parse_filing_history(response: "dict | None") -> list:
    """Flatten a /filing-history response into simple per-filing dicts."""
    if not response:
        return []
    out = []
    for item in response.get("items", []):
        out.append(
            {
                "date": item.get("date"),
                "category": (item.get("category") or "").lower(),
                "type": (item.get("type") or "").upper(),
                "description": (item.get("description") or "").lower(),
            }
        )
    return out


def _is_strike_off(f: dict) -> bool:
    return (
        f["category"] == "gazette"
        or f["type"].startswith("GAZ")
        or f["type"] in {"DS01", "DS02"}
        or "strike" in f["description"]
        or "gazette" in f["description"]
    )


def _is_insolvency(f: dict) -> bool:
    return (
        f["category"] == "insolvency"
        or any(
            w in f["description"]
            for w in ("insolvency", "liquidation", "administration", "receiver", "winding")
        )
    )


def _is_dormant_accounts(f: dict) -> bool:
    return f["category"] == "accounts" and "dormant" in f["description"]


def _earliest_date(filings: list, predicate):
    dates = [f["date"] for f in filings if f.get("date") and predicate(f)]
    return min(dates) if dates else None


def extract_attrition_events(filings: list) -> dict:
    """Find the first date the company shows each kind of distress in its filings.

    Returns the first date of a strike-off step, an insolvency filing, and a
    dormant accounts filing, plus the earliest of the three and which it was.
    Any field is None if that event never appears.
    """
    strike = _earliest_date(filings, _is_strike_off)
    insolv = _earliest_date(filings, _is_insolvency)
    dormant = _earliest_date(filings, _is_dormant_accounts)

    candidates = {
        "strike_off": strike,
        "insolvency": insolv,
        "dormant_accounts": dormant,
    }
    present = {k: v for k, v in candidates.items() if v}
    if present:
        earliest_type = min(present, key=present.get)
        earliest_date = present[earliest_type]
    else:
        earliest_type = None
        earliest_date = None

    return {
        "first_strike_off": strike,
        "first_insolvency": insolv,
        "first_dormant_accounts": dormant,
        "first_event_type": earliest_type,
        "first_event_date": earliest_date,
        "has_event": earliest_date is not None,
    }
