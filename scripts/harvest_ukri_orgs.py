"""
Harvest every organisation from UKRI Gateway to Research, cached and resumable.

Two things found by probing the API before writing this, both of which shaped it:

  * The endpoint is `gtr.ukri.org/gtr/api/organisations`. Notebook 10 used
    `gtr.ukri.org/api/organisations`, which returns 404. That is why NB10 never ran.
  * `regNumber` is populated on 0 of 500 sampled organisations, so there is no company
    number to join on. Grants match on name and postcode, like trade marks.

What we can read per organisation: the name, the postcode when known, and the number of
PROJECT links, which is how many funded projects it took part in. There is no date at
this level. Dates live on the project records and would cost one call per organisation,
about 97,000 calls, so grants ship as presence and a count rather than as timeline events.

Output: work/ukri_orgs.csv  (id, name, postcode, n_projects)

Run:  python scripts/harvest_ukri_orgs.py
"""

import csv
import json
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
CACHE = BASE / "work" / "gtr_cache"
OUT = BASE / "work" / "ukri_orgs.csv"
CACHE.mkdir(parents=True, exist_ok=True)

URL = "https://gtr.ukri.org/gtr/api/organisations"
HEAD = {"Accept": "application/json",
        "User-Agent": "LloydsBCB-MSc-project/1.0 (academic; contact via GitHub elyokerr)"}
PAGE_SIZE = 100
PAUSE = 0.25          # polite, and well inside anything the service would object to


def fetch_page(p):
    """One page, from the cache if we already have it."""
    cached = CACHE / f"orgs_p{p:04d}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    for attempt in (1, 2, 3):
        try:
            r = requests.get(URL, params={"p": p, "s": PAGE_SIZE}, headers=HEAD, timeout=90)
            r.raise_for_status()
            body = r.json()
            cached.write_text(json.dumps(body), encoding="utf-8")
            time.sleep(PAUSE)
            return body
        except Exception as e:
            print(f"  page {p} attempt {attempt} failed: {e}", flush=True)
            time.sleep(3 * attempt)
    return None


first = fetch_page(1)
total_pages = first["totalPages"]
total_size = first["totalSize"]
print(f"{total_size:,} organisations across {total_pages:,} pages", flush=True)

rows = []
for p in range(1, total_pages + 1):
    body = first if p == 1 else fetch_page(p)
    if body is None:
        print(f"  page {p} skipped after 3 attempts", flush=True)
        continue
    for o in body.get("organisation", []):
        addr = (o.get("addresses") or {}).get("address") or [{}]
        pc = addr[0].get("postCode")
        if pc in ("Unknown", "Unspecified", ""):
            pc = None
        links = (o.get("links") or {}).get("link") or []
        rows.append({
            "gtr_id": o.get("id"),
            "name": o.get("name"),
            "postcode": pc,
            "n_projects": sum(1 for l in links if l.get("rel") == "PROJECT"),
        })
    if p % 50 == 0 or p == total_pages:
        print(f"  page {p}/{total_pages}  {len(rows):,} organisations", flush=True)

with open(OUT, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["gtr_id", "name", "postcode", "n_projects"])
    w.writeheader()
    w.writerows(rows)

with_pc = sum(1 for r in rows if r["postcode"])
print(f"\nwrote {OUT}")
print(f"  organisations   : {len(rows):,}")
print(f"  with a postcode : {with_pc:,}  ({with_pc / max(len(rows), 1):.1%})")
print(f"  with a project  : {sum(1 for r in rows if r['n_projects']):,}")
