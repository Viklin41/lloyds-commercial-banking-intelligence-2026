"""Gazette delta crawl: extend the notice window from 2026-06-30 to 2026-07-31.

Why a delta and not a re-run of NB10:

NB10 derives its window as SEARCH_DATE minus WINDOW_YEARS, and the page cache is
keyed `cat{code}_{FROM}_{TO}_p{page}.json`. Moving SEARCH_DATE to 2026-07-31
also moves FROM to 2023-07-31, so all 2,844 cached pages would miss and the full
~7.9 hour crawl would run again for data we already hold. This script instead
crawls only the new window as its own cache key, leaving the existing cache
untouched, then concatenates.

    existing   cat24/cat11   2023-06-30 -> 2026-06-30   2,844 pages, on disk
    this run   cat24/cat11   2026-07-01 -> 2026-07-31   ~88 pages, ~15 min

2026-07-01 as the start is deliberate: the existing crawl's end date is
inclusive (max notice_date in the CSV is exactly 2026-06-30), so this leaves no
gap and no overlap. Output is deduplicated on notice_url regardless.

Category 25 (Personal Insolvency) is deliberately NOT crawled. A 200-notice
probe on 2026-08-10 found 0% carry a company number (control: cat24 83%), because
those notices name individuals, not companies. Without officer data there is no
way to join them to the spine. Revisit if the Companies House API is added.

    in   data/raw/gazette_cache/                      (existing pages reused)
         data/processed/nb10_gazette_notices.csv      284,230 notices to 2026-06-30
    out  data/raw/gazette_cache/                      (new pages added)
         data/processed/nb10_gazette_notices_delta_2026-07.csv
         data/processed/nb10_gazette_notices_thru_2026-07.csv   (concatenated)

The original nb10_gazette_notices.csv is never overwritten.

Run:  python notebooks/gazette_delta_crawl.py
"""

import os
import re
import time
import json
from html import unescape
from pathlib import Path

import requests
import pandas as pd

DATA = Path(os.environ.get("LLOYDS_DATA")
            or Path(__file__).resolve().parent.parent / "data")
CACHE = DATA / "raw" / "gazette_cache"
PROCESSED = DATA / "processed"

EXISTING_NOTICES = PROCESSED / "nb10_gazette_notices.csv"
DELTA_OUT = PROCESSED / "nb10_gazette_notices_delta_2026-07.csv"
MERGED_OUT = PROCESSED / "nb10_gazette_notices_thru_2026-07.csv"

# The new window only. The existing cache keeps its own key and is not touched.
FROM_DATE = "2026-07-01"
TO_DATE = "2026-07-31"
CATEGORIES = {24: "Corporate Insolvency", 11: "Companies"}

URL = "https://www.thegazette.co.uk/all-notices/notice/data.json"
HEADERS = {"User-Agent": "LloydsUniProject/1.0 (MSc research, University of Bristol)"}
PAGE_SIZE = 100
DELAY_SECS = 10          # the Gazette asks for 1 request / 10 seconds
TIMEOUT = 60
MAX_RETRIES = 4
MAX_PAGES = 400          # safety cap; one month should need well under 100


# ---------------------------------------------------------------------------
# Parser: copied verbatim from NB10 so the delta rows match the existing schema
# ---------------------------------------------------------------------------
CH_NUMBER_RE = r"(?:[A-Z]{2}\d{6}|\d{8})"
UK_POSTCODE_RE = r"[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}"


def _degazette_html(s):
    """Strip the notice HTML down to plain text."""
    return unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def extract_notice(entry):
    """Turn one raw Gazette notice into a tidy signal dict (pure function)."""
    content = _degazette_html(entry.get("content", ""))
    m = re.search(r"Company\s*(?:Registration\s*)?Number[:\s]*(" + CH_NUMBER_RE + r")",
                  content, re.I)
    if not m:
        m = re.search(r"\b(" + CH_NUMBER_RE + r")\b", content)
    pc = re.search(UK_POSTCODE_RE, content)
    return {
        "company_name": (entry.get("title") or "").strip(),
        "CompanyNumber": m.group(1) if m else None,
        "notice_code": entry.get("f:notice-code", ""),
        "notice_type": (entry.get("category") or {}).get("@term", ""),
        "notice_date": (entry.get("published") or "")[:10],
        "postcode": pc.group(0) if pc else None,
        "notice_url": entry.get("id", ""),
    }


# Self-test before any network call, same example NB10 used.
_demo = extract_notice({
    "title": "KM TELECOM LTD",
    "content": "<div><p>KM TELECOM LTD (Company Number 09857485) Registered office: "
               "Ellenborough House, Wellington Street, Cheltenham, GL50 1YD</p></div>",
    "f:notice-code": "2452",
    "category": {"@term": "Winding-Up Orders"},
    "published": "2026-07-04T07:43:53",
})
assert _demo["CompanyNumber"] == "09857485" and _demo["postcode"] == "GL50 1YD"
print("extract_notice self-test passed")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def _page_path(cat, page):
    return CACHE / f"cat{cat}_{FROM_DATE}_{TO_DATE}_p{page}.json"


def _as_entry_list(data):
    """'entry' is a list normally, but a single dict when a page has one result."""
    e = data.get("entry", [])
    return [e] if isinstance(e, dict) else e


def fetch_page(cat, page, use_cache=True):
    """One page. Returns (json_dict, source) with source in cache/api/error.

    Errors are left uncached so a re-run retries them.
    """
    cache_file = _page_path(cat, page)
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8")), "cache"

    params = {
        "categorycode": cat,
        "start-publish-date": FROM_DATE,
        "end-publish-date": TO_DATE,
        "results-page": page,
        "results-page-size": PAGE_SIZE,
        "sort-by": "latest-date",
    }

    resp = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            break
        except requests.exceptions.RequestException as ex:
            wait = DELAY_SECS * attempt
            print(f"   [retry {attempt}/{MAX_RETRIES}] cat {cat} page {page}: "
                  f"{type(ex).__name__}; waiting {wait}s")
            time.sleep(wait)

    if resp is None:
        print(f"   [warning] cat {cat} page {page} failed after {MAX_RETRIES} retries")
        return {"entry": []}, "error"
    if resp.status_code != 200:
        print(f"   [warning] HTTP {resp.status_code} on cat {cat} page {page}")
        return {"entry": []}, "error"

    data = resp.json()
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return data, "api"


def crawl(cat):
    """Page through one category until a short/empty page ends it."""
    label = CATEGORIES[cat]
    print(f"\ncat{cat} {label}: {FROM_DATE} -> {TO_DATE}")
    out, page, api_calls, total_pages = [], 1, 0, None
    while page <= MAX_PAGES:
        data, source = fetch_page(cat, page)
        entries = _as_entry_list(data)
        out += entries
        if source == "api":
            api_calls += 1

        # The feed reports the true result count, so after page 1 we know exactly
        # how much is left instead of discovering the end by hitting a short page.
        if total_pages is None:
            total = int(data.get("f:total") or 0)
            total_pages = max(1, -(-total // PAGE_SIZE))
            cached = sum(1 for p in range(1, total_pages + 1) if _page_path(cat, p).exists())
            eta = (total_pages - cached) * (DELAY_SECS + 1.3) / 60
            print(f"   {total:,} notices = {total_pages} pages | "
                  f"{cached} already cached | ETA {eta:.0f} min")
        if page % 20 == 0 or len(entries) < PAGE_SIZE:
            print(f"   page {page:>3} | {len(entries):>3} entries | {source} | "
                  f"running total {len(out):,}")
        if len(entries) < PAGE_SIZE:
            break
        if source == "api":
            time.sleep(DELAY_SECS)
        page += 1
    print(f"   done: {len(out):,} notices over {page} pages ({api_calls} fetched, "
          f"{page - api_calls} from cache)")
    return out


all_entries = []
for cat in CATEGORIES:
    all_entries += crawl(cat)

delta = pd.DataFrame([extract_notice(e) for e in all_entries])
delta = delta.drop_duplicates(subset=["notice_url"])
delta.to_csv(DELTA_OUT, index=False)

print(f"\ndelta: {len(delta):,} notices")
print(f"  with a parsed CompanyNumber: {int(delta['CompanyNumber'].notna().sum()):,} "
      f"({100 * delta['CompanyNumber'].notna().mean():.0f}%)")
print(f"  date range: {delta['notice_date'].min()} -> {delta['notice_date'].max()}")
print(f"  saved -> {DELTA_OUT}")


# ---------------------------------------------------------------------------
# Concatenate onto the existing notices. The original file is left alone.
# ---------------------------------------------------------------------------
existing = pd.read_csv(EXISTING_NOTICES, dtype=str)
print(f"\nexisting: {len(existing):,} notices "
      f"({existing['notice_date'].min()} -> {existing['notice_date'].max()})")

merged = pd.concat([existing, delta.astype(str).replace("nan", pd.NA)],
                   ignore_index=True)
before = len(merged)
merged = merged.drop_duplicates(subset=["notice_url"])
print(f"merged: {len(merged):,} notices ({before - len(merged):,} duplicate URLs dropped)")
print(f"  date range: {merged['notice_date'].min()} -> {merged['notice_date'].max()}")
merged.to_csv(MERGED_OUT, index=False)
print(f"  saved -> {MERGED_OUT}")

print("\nnotices per month, last 6:")
m = pd.to_datetime(merged["notice_date"], errors="coerce").dt.to_period("M")
print(m.value_counts().sort_index().tail(6).to_string())
