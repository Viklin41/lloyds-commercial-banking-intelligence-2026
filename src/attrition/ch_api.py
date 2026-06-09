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

import json
import os
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
        safe = key.replace("/", "_").strip("_")
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


def _normalise_lender(name: str) -> str:
    """Loose normalisation so 'Barclays Bank PLC' ~ 'BARCLAYS BANK PLC.'."""
    n = name.upper().strip().rstrip(".")
    for suffix in (" PLC", " LIMITED", " LTD", " LLP"):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    return n


def current_lenders(charges: list) -> set:
    """Distinct lenders on charges that are still outstanding."""
    return {
        _normalise_lender(l)
        for c in charges
        if (c.get("status") or "").lower() == "outstanding"
        for l in c["lenders"]
        if l
    }


def past_lenders(charges: list) -> set:
    """Distinct lenders whose charges are now satisfied (paid off)."""
    return {
        _normalise_lender(l)
        for c in charges
        if (c.get("status") or "").lower() == "satisfied"
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
