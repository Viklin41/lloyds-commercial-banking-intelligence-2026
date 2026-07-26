"""Charge-level lender identity, harvested once and replayed over the panel.

The 33-month panel knows *how many* charges a company has (``Mortgages.NumMort*``)
but not *who holds them*. That missing variable is the axis the client's three
macro areas are defined on: Growth is "not ours", Attrition is "ours and
leaving", Maintenance is "ours and staying". Charge counts cannot separate those.

The Companies House Charges API can, and cheaply, because **charges are
append-only and dated**. Every charge carries ``created_on`` and, once
discharged, ``satisfied_on``, alongside ``persons_entitled[].name`` (the lender).
A charge is therefore outstanding at month ``t`` iff ``created_on <= t`` and
(``satisfied_on`` is null or ``satisfied_on > t``). One harvest today
reconstructs the entire 33-month lender history retrospectively - no historical
downloads, no monthly re-fetch.

Two things make this affordable. Only **158,684** of the 2,038,130 companies in
the panel have ever held a charge (7.8%), and the endpoint returns the full
charge history in one call for the large majority of them.

Scope note: we harvest everything with ``Mortgages.NumMortCharges > 0`` in *any*
snapshot, not just those with an outstanding charge today. A company that has
paid off its last charge and taken nothing new is precisely an exit candidate,
so filtering on "currently outstanding" would delete the attrition signal.

This module deliberately **only harvests and persists**. Lender classification
lives in ``lenders.py`` so the taxonomy can be reworked without re-running a
22-hour job.

Why not reuse ``ch_api._paged``: it calls ``ch_get`` directly, which raises on
429. At 2 requests/second sustained for a day, 429s and transient 5xx are
routine, not exceptional, so this module needs its own retrying pager. Nothing
in ``ch_api`` is modified.

Run it detached, because it takes about a day::

    mkdir -p logs
    setsid nohup .venv/bin/python -m src.features.charges harvest \\
        > logs/charges_harvest.log 2>&1 < /dev/null &
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests
from requests.auth import HTTPBasicAuth

from src.features import ch_api, panel

BASE_URL = "https://api.company-information.service.gov.uk"

RAW_DIR = Path("data/raw/charges")
TARGET_PATH = Path("data/processed/charge_universe.parquet")

# Companies House allows 600 requests per rolling 5 minutes = 2/s. We pace on the
# interval between request *starts*, not with a fixed sleep after each one: a fixed
# sleep silently adds network latency on top (measured 0.52s sleep -> 1.5 req/s, a
# 29-hour run instead of 23). Pacing on start times self-corrects for latency and
# holds ~1.9/s, just under the ceiling.
MIN_REQUEST_INTERVAL = 0.53
COMPANIES_PER_SHARD = 5_000

# Per-request retry. 429 is expected at this cadence; 5xx and connection resets
# are expected over a 22-hour run on a home connection.
MAX_ATTEMPTS = 6
BACKOFF_BASE = 2.0

# Fields kept per charge. Generous on purpose: re-harvesting to recover a dropped
# field would cost another day. ``links`` and ``transactions`` are dropped because
# they are bulky and carry nothing about lender identity or timing.
CHARGE_FIELDS = [
    "charge_code",
    "charge_number",
    "status",
    "created_on",
    "delivered_on",
    "satisfied_on",
    "acquired_on",
    "resolved_on",
    "assets_ceased_on",
    "classification",
    "particulars",
    "persons_entitled",
    "more_than_four_persons_entitled",
    "secured_details",
    "scottish_alterations",
]


def build_target_list(panel_dir: Path = panel.PANEL_DIR, out: Path = TARGET_PATH) -> int:
    """Distinct companies that have ever held a charge in any snapshot."""
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT DISTINCT CompanyNumber
            FROM read_parquet('{panel_dir}/*/*.parquet')
            WHERE "Mortgages.NumMortCharges" > 0
            ORDER BY CompanyNumber
        ) TO '{out}' (FORMAT PARQUET)
        """
    )
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    con.close()
    return n


def load_targets(path: Path = TARGET_PATH) -> list[str]:
    if not path.exists():
        build_target_list(out=path)
    con = duckdb.connect()
    rows = con.execute(f"SELECT CompanyNumber FROM read_parquet('{path}')").fetchall()
    con.close()
    return [r[0] for r in rows]


def completed_companies(raw_dir: Path = RAW_DIR) -> set[str]:
    """Company numbers already harvested, read back from the shards themselves.

    Deriving resume state from the data rather than a side ledger means the two
    can never drift apart. A line torn by a kill mid-write fails to parse, is
    skipped here, and that one company is simply re-fetched.
    """
    done: set[str] = set()
    for shard in sorted(raw_dir.glob("part-*.jsonl")):
        with shard.open() as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)["company_number"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


_last_request_at = 0.0


def _pace() -> None:
    """Block until MIN_REQUEST_INTERVAL has elapsed since the last request start."""
    global _last_request_at
    wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _get(path: str, params: dict, key: str) -> dict | None:
    """GET with rate limit and retry. Returns None on 404. Raises after MAX_ATTEMPTS."""
    for attempt in range(MAX_ATTEMPTS):
        _pace()
        try:
            resp = requests.get(
                BASE_URL + path,
                params=params,
                auth=HTTPBasicAuth(key, ""),
                timeout=30,
            )
        except requests.RequestException as exc:
            wait = BACKOFF_BASE**attempt
            print(f"  connection error ({exc.__class__.__name__}), retry in {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue

        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", BACKOFF_BASE**attempt))
            print(f"  429 rate limited, sleeping {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            wait = BACKOFF_BASE**attempt
            print(f"  {resp.status_code} from CH, retry in {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"giving up on {path} after {MAX_ATTEMPTS} attempts")


def fetch_charges(company_number: str, key: str) -> list[dict] | None:
    """All charges for a company, paged. None means the company 404s."""
    items: list[dict] = []
    start = 0
    while True:
        data = _get(
            f"/company/{company_number}/charges",
            {"items_per_page": 100, "start_index": start},
            key,
        )
        if data is None:
            return None if start == 0 else items
        page = data.get("items", [])
        items.extend(page)
        total = data.get("total_count", len(items))
        start += 100
        if not page or start >= total:
            break
    return items


def _record(company_number: str, charges: list[dict] | None) -> dict:
    if charges is None:
        return {
            "company_number": company_number,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "not_found": True,
            "charges": [],
        }
    return {
        "company_number": company_number,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "not_found": False,
        "charges": [{f: c.get(f) for f in CHARGE_FIELDS if f in c} for c in charges],
    }


def harvest(raw_dir: Path = RAW_DIR, target_path: Path = TARGET_PATH) -> int:
    """Harvest every un-harvested target company. Resumable; safe to re-run."""
    key = ch_api.get_api_key()
    if not key:
        raise ValueError("No Companies House API key found (set CH_API_KEY in .env).")

    raw_dir.mkdir(parents=True, exist_ok=True)
    targets = load_targets(target_path)
    done = completed_companies(raw_dir)
    todo = [c for c in targets if c not in done]

    print(
        f"[{datetime.now():%Y-%m-%d %H:%M:%S}] targets={len(targets):,} "
        f"already_done={len(done):,} todo={len(todo):,} "
        f"eta={len(todo) * MIN_REQUEST_INTERVAL / 3600:.1f}h",
        flush=True,
    )
    if not todo:
        print("nothing to do", flush=True)
        return 0

    written = len(done)
    started = time.time()
    fh = None
    shard_idx = None

    try:
        for i, company_number in enumerate(todo, 1):
            idx = written // COMPANIES_PER_SHARD
            if idx != shard_idx:
                if fh is not None:
                    fh.close()
                shard_idx = idx
                fh = (raw_dir / f"part-{idx:04d}.jsonl").open("a")

            try:
                charges = fetch_charges(company_number, key)
            except RuntimeError as exc:
                # Do not write a line: leaving it absent means the next run retries it.
                print(f"  SKIP {company_number}: {exc}", flush=True)
                continue

            fh.write(json.dumps(_record(company_number, charges)) + "\n")
            fh.flush()
            written += 1
            if written % 50 == 0:
                os.fsync(fh.fileno())

            if i % 1000 == 0:
                rate = i / (time.time() - started)
                remaining = (len(todo) - i) / rate / 3600
                print(
                    f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {i:,}/{len(todo):,} "
                    f"({rate:.2f}/s, {remaining:.1f}h left)",
                    flush=True,
                )
    finally:
        if fh is not None:
            os.fsync(fh.fileno())
            fh.close()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] done, {written:,} companies on disk", flush=True)
    return written


def status(raw_dir: Path = RAW_DIR, target_path: Path = TARGET_PATH) -> dict:
    targets = load_targets(target_path)
    done = completed_companies(raw_dir)
    return {"targets": len(targets), "done": len(done), "remaining": len(targets) - len(done)}


if __name__ == "__main__":
    # ch_api reads the key from the environment but does not load .env itself; the
    # notebooks call load_dotenv for it. Running detached there is no notebook.
    from dotenv import load_dotenv

    load_dotenv()

    cmd = sys.argv[1] if len(sys.argv) > 1 else "harvest"
    if cmd == "harvest":
        harvest()
    elif cmd == "status":
        print(status())
    elif cmd == "targets":
        print(f"{build_target_list():,} companies with at least one charge")
    else:
        sys.exit(f"unknown command: {cmd}")
