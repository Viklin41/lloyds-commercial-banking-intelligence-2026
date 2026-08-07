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
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

from src.features import ch_api, lenders, panel

BASE_URL = "https://api.company-information.service.gov.uk"

RAW_DIR = Path("data/raw/charges")
TARGET_PATH = Path("data/processed/charge_universe.parquet")
FLAT_PATH = Path("data/processed/charges_flat.parquet")
LENDER_PANEL_DIR = Path("data/processed/lender_panel")

# Days from `delivered_on` to the charge actually showing up in the bulk register.
#
# Delivery is not registration. Companies House takes time to process a delivered
# charge, and the monthly bulk extract is itself taken on a drifting date, so a
# charge delivered shortly before a snapshot is visible in the API and still absent
# from the register file that the `lending` label is computed from. Gating only on
# `delivered_on` therefore still leaks, just less.
#
# Measured by sweeping the margin and comparing the API's outstanding count at `t`
# against the register's, over company-months that go on to borrow (nb16b, section 5):
#
#     margin   mean(api - bulk)   % already at the post-borrowing value
#      0 days       +0.1014                 6.16
#     14 days       +0.0121                 0.81
#     21 days       +0.0013                 0.79   <- the knee
#     30 days       -0.0128                 0.78
#     60 days       -0.0511                 0.70
#
# 21 days is where the discrepancy reaches zero and stops improving; beyond it the
# gap goes negative, which is the features going stale rather than getting safer.
REGISTRATION_LAG_DAYS = 21

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


# --------------------------------------------------------------------------- #
# Step 2/3: flatten the shards, then replay them over the panel months
# --------------------------------------------------------------------------- #

# One row per (company, charge, person entitled). A charge with two banks on it is
# two rows, because both of them are lenders to that company and collapsing them to
# the "first" one would silently delete a relationship. Counts of *charges* therefore
# always go through `count(DISTINCT charge_id)`, never `count(*)`.
FLAT_SQL = """
WITH raw AS (
    SELECT * FROM read_json('{raw_glob}', format='newline_delimited',
                            maximum_object_size=50000000)
),
ch AS (
    SELECT company_number, fetched_at, unnest(charges) AS c FROM raw
),
exploded AS (
    SELECT
        company_number AS "CompanyNumber",
        fetched_at,
        c.charge_number,
        c.charge_code,
        c.status,
        TRY_CAST(c.created_on   AS DATE) AS created_on,
        TRY_CAST(c.delivered_on AS DATE) AS delivered_on,
        TRY_CAST(c.satisfied_on AS DATE) AS satisfied_on,
        c.classification.description AS classification,
        -- A charge with no persons_entitled at all still exists and still counts
        -- towards the outstanding total, so unnest must not drop it.
        unnest(coalesce(list_transform(c.persons_entitled, x -> x.name), [NULL])) AS lender_name
    FROM ch
)
SELECT
    "CompanyNumber",
    -- charge_number is per-company sequential and present on every charge, unlike
    -- charge_code which only exists for the ~44% filed since the 2013 regime.
    "CompanyNumber" || '-' || charge_number AS charge_id,
    charge_number, charge_code, status,
    created_on, delivered_on, satisfied_on,
    classification, lender_name,
    fetched_at
FROM exploded
"""


def build_flat(raw_dir: Path = RAW_DIR, out_path: Path = FLAT_PATH) -> pd.DataFrame:
    """Explode the NDJSON shards to (charge, lender) grain and classify the lender.

    The regex dictionary runs in pandas rather than SQL because it is ordered
    first-match-wins logic over ~79k distinct strings, which is a dict lookup once
    the distinct names are classified - see :func:`lenders.classify_series`.
    """
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    flat = con.execute(
        FLAT_SQL.format(raw_glob=(raw_dir / "part-*.jsonl").as_posix())
    ).df()
    con.close()

    flat["lender_group"] = lenders.classify_series(flat["lender_name"])
    flat["is_lbg"] = flat["lender_group"] == lenders.LBG_GROUP

    out_path.parent.mkdir(parents=True, exist_ok=True)
    flat.to_parquet(out_path, index=False)
    return flat


def harvest_date(flat_path: Path = FLAT_PATH) -> pd.Timestamp:
    """When the harvest ran, i.e. the last date any of this is known good.

    Charges are append-only and the API returns the full history, so unlike the
    contract feeds there is no per-source watermark to reconcile. There is still a
    censoring edge: a charge *created* before the harvest but *registered* after it
    is invisible here, and CH allows 21 days to deliver a charge. So the final month
    or so of every "new charge" feature is undercounted, exactly the way
    ``contracts.harvest_watermark`` describes, and the last panel month should be
    treated as censored for lender features.
    """
    fetched = pd.read_parquet(flat_path, columns=["fetched_at"])["fetched_at"]
    return pd.to_datetime(fetched, utc=True, format="mixed").max().tz_localize(None).normalize()


LENDER_FEATURE_COLS = [
    "n_charges_outstanding",
    "n_lbg_charges_outstanding",
    "is_lbg_client",
    "lbg_share_of_outstanding",
    "n_distinct_lenders",
    "n_competitor_lenders",
    "months_since_last_lbg_charge_created",
    "months_since_last_lbg_satisfaction",
    "competitor_entered_12m",
    "lbg_charge_satisfied_6m",
    "competitor_charge_created_6m",
    "ever_lbg_client",
]

LENDER_CATEGORICAL_COLS = ["primary_lender_group"]

# Counts and flags mean "none" for a company absent from this sparse table (it has
# never held a charge at all), so consumers coalesce them to 0. The two
# months_since_* columns have no zero-equivalent: "never borrowed from Lloyds" is a
# true NULL, the same convention as contracts.ASOF_COALESCE_ZERO.
LENDER_COALESCE_ZERO = [
    c for c in LENDER_FEATURE_COLS
    if not c.startswith("months_since") and c != "lbg_share_of_outstanding"
]

# ### THE AS-OF GATE IS ON `delivered_on`, NOT `created_on` (fixed 7 Aug 2026)
#
# This gate was `created_on <= snapshot_date` and that was a leak. `created_on` is
# the date the charge was *made*; `delivered_on` is the date it reached Companies
# House and became visible to anybody. 94.7% of charges are delivered after they are
# created, median 6 days, p90 16 days, and CH allows 21. So a charge created on the
# 20th and delivered on the 28th was being counted in the feature row for the 1st,
# while the bulk register, which is what the `lending` label is computed from, only
# saw it the following month. The label was then guaranteed by a feature.
#
# It showed up as the `lender` run scoring P@100 = 1.000 on `lending` against a
# 0.271% base rate while ROC-AUC barely moved: 46.6% of that model's top 500 held a
# charge counted before it was observable, against 0.01% of the population.
#
# Note why verification 7 in notebook 14b did not catch it: that test truncates the
# harvest at a cut date **on `created_on`** and replays, so it asks "does the panel
# use charges created after the cut" and the honest answer was no. It never asked
# whether a charge created before the cut was *knowable* by then. A blind-replay test
# is only as good as the clock you replay against.
#
# `satisfied_on` keeps the same treatment as before, because the API gives no
# delivery date for a satisfaction. Those features carry the same class of lag and
# are the obvious next thing to check if a satisfaction-driven target ever matters.
#
# The gate compares against the *first* of the month, not
# `last_day(snapshot_date)` as the contract table uses. Two different clocks:
# contracts are dated by publication and the panel row for month t is the register as
# it stood at the start of t, so anything a charge does later in the month is
# genuinely not knowable at t. Gating on month end would put up to 30 days of future
# charge activity into the feature row and break verification 7.
#
# June 2025 is computed like every other month. This table is built from event dates
# on a calendar spine, not from register snapshots, so it has no hole to step over -
# the same reason contracts.ASOF_SQL needs no special case. The panel simply never
# asks for that month because it has no partition there.
LENDER_PANEL_SQL = """
WITH months AS (
    SELECT (DATE '{first_month}' + INTERVAL (n) MONTH)::DATE AS snapshot_date
    FROM range(0, DATEDIFF('month', DATE '{first_month}', DATE '{last_month}') + 1) t(n)
),
charges AS (
    SELECT "CompanyNumber", charge_id, created_on, satisfied_on,
           -- The date the charge became visible **in the register the label is
           -- computed from**, which is what every as-of gate below uses. `created_on`
           -- is when the charge was made, `delivered_on` is when it reached Companies
           -- House, and CH then takes about three weeks to register it and have it
           -- appear in a bulk extract. GREATEST because a handful of rows carry a
           -- delivered date before the created one, and COALESCE because a few carry
           -- no delivered date at all. See REGISTRATION_LAG_DAYS for the measurement.
           GREATEST(created_on, COALESCE(delivered_on, created_on))
               + INTERVAL {lag_days} DAY AS visible_on,
           lender_group, is_lbg,
           lender_group NOT IN ('lbg', 'lbg_retail', 'unclassified') AS is_competitor
    FROM read_parquet('{flat_path}')
    WHERE created_on IS NOT NULL
),
companies AS (SELECT DISTINCT "CompanyNumber" FROM charges),
spine AS (SELECT * FROM companies CROSS JOIN months),
-- Everything a company's charge history says as at month t. `outstanding` is the
-- plan's definition verbatim: created on or before t, and either never satisfied or
-- satisfied after t.
joined AS (
    SELECT s."CompanyNumber", s.snapshot_date, c.*,
           (c.satisfied_on IS NULL OR c.satisfied_on > s.snapshot_date) AS outstanding
    FROM spine s
    JOIN charges c
      ON c."CompanyNumber" = s."CompanyNumber"
     AND c.visible_on <= s.snapshot_date
),
agg AS (
    SELECT
        "CompanyNumber", snapshot_date,
        count(DISTINCT CASE WHEN outstanding THEN charge_id END)
            AS n_charges_outstanding,
        count(DISTINCT CASE WHEN outstanding AND is_lbg THEN charge_id END)
            AS n_lbg_charges_outstanding,
        count(DISTINCT CASE WHEN outstanding AND lender_group <> 'unclassified'
                            THEN lender_group END)
            AS n_distinct_lenders,
        count(DISTINCT CASE WHEN outstanding AND is_competitor THEN lender_group END)
            AS n_competitor_lenders,
        max(is_lbg::INT)::BOOLEAN AS ever_lbg_client,
        max(CASE WHEN is_lbg THEN created_on END)   AS last_lbg_created,
        max(CASE WHEN is_lbg AND satisfied_on <= snapshot_date THEN satisfied_on END)
            AS last_lbg_satisfied,
        max(CASE WHEN is_competitor THEN created_on END) AS last_competitor_created,
        -- "the company was LBG-only a year ago": every charge outstanding at t-12m
        -- was ours. Compared against a competitor charge arriving since, this is the
        -- wallet-share erosion signal, which leads full defection.
        count(DISTINCT CASE WHEN visible_on <= snapshot_date - INTERVAL 12 MONTH
                             AND (satisfied_on IS NULL
                                  OR satisfied_on > snapshot_date - INTERVAL 12 MONTH)
                            THEN charge_id END) AS n_outstanding_12m_ago,
        count(DISTINCT CASE WHEN visible_on <= snapshot_date - INTERVAL 12 MONTH
                             AND (satisfied_on IS NULL
                                  OR satisfied_on > snapshot_date - INTERVAL 12 MONTH)
                             AND NOT is_lbg
                            THEN charge_id END) AS n_nonlbg_outstanding_12m_ago,
        count(DISTINCT CASE WHEN is_competitor
                             AND visible_on > snapshot_date - INTERVAL 12 MONTH
                            THEN charge_id END) AS n_competitor_created_12m,
        count(DISTINCT CASE WHEN is_competitor
                             AND visible_on > snapshot_date - INTERVAL 6 MONTH
                            THEN charge_id END) AS n_competitor_created_6m,
        count(DISTINCT CASE WHEN is_lbg AND satisfied_on <= snapshot_date
                             AND satisfied_on > snapshot_date - INTERVAL 6 MONTH
                            THEN charge_id END) AS n_lbg_satisfied_6m
    FROM joined
    GROUP BY 1, 2
),
-- Who holds the most of what is outstanding. Ties break on the most recent charge,
-- which is the more useful answer for an RM: the newest money is the live relationship.
primary_lender AS (
    SELECT "CompanyNumber", snapshot_date, lender_group AS primary_lender_group
    FROM (
        SELECT "CompanyNumber", snapshot_date, lender_group,
               row_number() OVER (PARTITION BY "CompanyNumber", snapshot_date
                                  ORDER BY count(DISTINCT charge_id) DESC,
                                           max(created_on) DESC,
                                           lender_group) AS rn
        FROM joined
        WHERE outstanding AND lender_group <> 'unclassified'
        GROUP BY 1, 2, 3
    ) WHERE rn = 1
)
SELECT
    a."CompanyNumber",
    a.snapshot_date,
    a.n_charges_outstanding,
    a.n_lbg_charges_outstanding,
    a.n_lbg_charges_outstanding > 0                       AS is_lbg_client,
    CASE WHEN a.n_charges_outstanding > 0
         THEN a.n_lbg_charges_outstanding::DOUBLE / a.n_charges_outstanding END
                                                          AS lbg_share_of_outstanding,
    a.n_distinct_lenders,
    a.n_competitor_lenders,
    DATEDIFF('month', a.last_lbg_created, a.snapshot_date) AS months_since_last_lbg_charge_created,
    DATEDIFF('month', a.last_lbg_satisfied, a.snapshot_date) AS months_since_last_lbg_satisfaction,
    (a.n_outstanding_12m_ago > 0 AND a.n_nonlbg_outstanding_12m_ago = 0
        AND a.n_competitor_created_12m > 0)               AS competitor_entered_12m,
    a.n_lbg_satisfied_6m > 0                              AS lbg_charge_satisfied_6m,
    a.n_competitor_created_6m > 0                         AS competitor_charge_created_6m,
    a.ever_lbg_client,
    p.primary_lender_group
FROM agg a
LEFT JOIN primary_lender p USING ("CompanyNumber", snapshot_date)
"""


def build_lender_panel(
    flat_path: Path = FLAT_PATH,
    out_dir: Path = LENDER_PANEL_DIR,
    threads: int | None = None,
    memory_limit: str = "10GB",
    lag_days: int = REGISTRATION_LAG_DAYS,
) -> int:
    """Replay the charge history as-of every panel month.

    Same partition layout as ``contracts_asof/`` (``snapshot_date=YYYY-MM-01``), so
    it joins onto the delta table with an identical ``LEFT JOIN`` and the same
    coalesce convention. Only the 158,684 companies that have ever held a charge get
    rows; everyone else is absent, which is the correct "not a client, no lenders".

    ``lag_days`` is the registration lag applied on top of ``delivered_on``; see
    :data:`REGISTRATION_LAG_DAYS`. Pass 0 to reproduce the un-lagged panel.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir.parent / "duckdb_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{tmp_dir.as_posix()}'")
    if threads:
        con.execute(f"PRAGMA threads={threads}")

    sql = LENDER_PANEL_SQL.format(
        flat_path=flat_path.as_posix(),
        first_month=panel.FIRST_MONTH,
        last_month=panel.LAST_MONTH,
        lag_days=lag_days,
    )
    con.execute(
        f"""
        COPY ({sql}) TO '{out_dir.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD,
         PARTITION_BY (snapshot_date), OVERWRITE_OR_IGNORE)
        """
    )
    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{(out_dir / '**' / '*.parquet').as_posix()}')"
    ).fetchone()[0]
    con.close()
    return n


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
