"""Build the company-month panel from the monthly Companies House bulk snapshots.

The panel is what turns a single-vintage snapshot into a time series: one row per
(company, month), so downstream code can compute deltas and self-label targets.

**Two passes, on purpose.** A company can be re-coded out of our target SIC sectors
without dying. If we applied NB01's sector filter independently to every month, that
company would simply vanish from the panel and look identical to a dissolution. So:

- **Pass 1 (universe):** union every ``CompanyNumber`` that matches our sectors in
  *any* month.
- **Pass 2 (extract):** emit a row for every universe member present in a month,
  whatever its status or current sector. Absence now unambiguously means "gone".

**All statuses are kept.** NB01 filters to ``CompanyStatus == "Active"``. Replaying
that per month would delete every failure event, leaving a panel in which no company
ever fails, so a credit-risk model would have nothing to learn from. We keep the
failures as labels and filter ``is_active`` at *scoring* time instead.

The sector/segment mapping below is lifted verbatim from NB01 so the replay is
faithful; the parity check in NB12 is what proves it.

Layout on disk::

    data/processed/panel_stage/snapshot_date=YYYY-MM-01/part.parquet   (intermediate)
    data/processed/panel/snapshot_date=YYYY-MM-01/part.parquet         (the panel)

Staging exists so each 2.7 GB CSV is extracted and parsed exactly **once**: the
universe union and the extract both read the cheap parquet instead. The extracted
CSV is deleted as soon as its stage partition is written.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from . import ch_static
from ..data import ch_bulk

# ---------------------------------------------------------------------------
# NB01 config, lifted verbatim (do not "improve" - parity depends on it)
# ---------------------------------------------------------------------------

SIC_PATH = Path("data/processed/SIC.csv")

# Accounts.AccountCategory -> size-tier label (Companies House definitions)
SEGMENT_MAP = {
    "MICRO ENTITY":                "Micro",       # turnover < £1M, < 10 employees
    "SMALL":                       "Small",       # turnover < £15M, < 50 employees
    "TOTAL EXEMPTION FULL":        "Small",       # small company, full accounts, audit-exempt
    "TOTAL EXEMPTION SMALL":       "Small",       # legacy small-company category
    "UNAUDITED ABRIDGED":          "Small",       # abridged unaudited - small company
    "AUDITED ABRIDGED":            "Small",       # abridged audited - small company
    "MEDIUM":                      "Medium",      # turnover < £54M, < 250 employees
    "FULL":                        "Large",       # full audited - large company
    "GROUP":                       "Large",       # parent with consolidated accounts
    "DORMANT":                     "Dormant",
    "NO ACCOUNTS FILED":           "No Filings",
    "AUDIT EXEMPTION SUBSIDIARY":  "Subsidiary",
    "FILING EXEMPTION SUBSIDIARY": "Subsidiary",
    "ACCOUNTS TYPE NOT AVAILABLE": "Unknown",
}

FAST_GROWTH_CODES = {
    "62011", "62012",           # software development
    "62020", "62030", "62090",  # IT consultancy / facilities / other
    "63110", "63120",           # data processing, hosting, web portals
    "72110", "72190", "72200",  # biotech R&D / other R&D
    "66190",                    # fintech-adjacent auxiliary financial services
}

TARGET_SECTIONS = {
    "Section J - Information and communication": "Technology, legal & professional",
    "Section M - Professional, scientific and technical activities": "Technology, legal & professional",
    "Section C - Manufacturing": "Manufacturing",
}

SIC_COLS = ["SICCode.SicText_1", "SICCode.SicText_2",
            "SICCode.SicText_3", "SICCode.SicText_4"]

# ---------------------------------------------------------------------------
# Panel schema
# ---------------------------------------------------------------------------

# Raw columns (already stripped of their leading spaces) carried into the panel.
SLIM_COLS = [
    "CompanyNumber", "CompanyName", "IncorporationDate", "CompanyCategory",
    "CountryOfOrigin", "CompanyStatus", "DissolutionDate",
    "Mortgages.NumMortCharges", "Mortgages.NumMortOutstanding",
    "Mortgages.NumMortPartSatisfied", "Mortgages.NumMortSatisfied",
    "SICCode.SicText_1", "SICCode.SicText_2", "SICCode.SicText_3", "SICCode.SicText_4",
    "Accounts.AccountRefDay", "Accounts.AccountRefMonth", "Accounts.NextDueDate",
    "Accounts.LastMadeUpDate", "Accounts.AccountCategory",
    "Returns.NextDueDate", "Returns.LastMadeUpDate",
    "ConfStmtNextDueDate", "ConfStmtLastMadeUpDate",
    "RegAddress.PostCode",
]

# Needed only to compute num_previous_names via ch_static; dropped from the panel.
PREV_NAME_COLS = [f"PreviousName_{i}.CompanyName" for i in range(1, 11)]

STAGE_DIR = Path("data/processed/panel_stage")
PANEL_DIR = Path("data/processed/panel")
DELTA_DIR = Path("data/processed/panel_deltas")
UNIVERSE_PATH = Path("data/processed/panel_universe.parquet")


def load_sector_map(sic_path: Path = SIC_PATH) -> dict[str, str]:
    """SIC code -> sector label, exactly as NB01 builds it.

    Fast-growth codes are assigned *first* so they take priority over whatever
    section they happen to sit in.
    """
    sic_df = pd.read_csv(sic_path, dtype=str)
    code_to_section = dict(zip(sic_df["Code"].str.strip(), sic_df["Section"].str.strip()))

    code_to_sector = {code: "Fast growth & emerging" for code in FAST_GROWTH_CODES}
    for code, section in code_to_section.items():
        if section in TARGET_SECTIONS and code not in code_to_sector:
            code_to_sector[code] = TARGET_SECTIONS[section]
    return code_to_sector


def month_start(date: str) -> str:
    """'2023-10-04' -> '2023-10-01'.

    Snapshot filenames are not reliably the 1st, but the panel is a *monthly*
    series, so partitions are keyed on the month. The true file date is kept
    alongside as ``source_date`` and is what point-in-time features are computed
    against.
    """
    return f"{date[:7]}-01"


def _register_sector_map(con: duckdb.DuckDBPyConnection) -> None:
    """Put the SIC->sector lookup into DuckDB as a table we can join against."""
    sector_map = load_sector_map()
    df = pd.DataFrame(
        {"code": list(sector_map.keys()), "sector": list(sector_map.values())}
    )
    con.register("sector_map_df", df)
    con.execute("CREATE OR REPLACE TEMP TABLE sector_map AS SELECT * FROM sector_map_df")


def _select_list(csv_cols: list[str]) -> str:
    """Build a SELECT that strips leading spaces from headers and fills gaps.

    The bulk CSV ships some headers with a leading space (' CompanyNumber',
    ' PreviousName_1.CompanyName', ...). We normalise to the stripped name so the
    rest of the code, and ch_static, see consistent columns. Any column a given
    vintage happens not to have becomes NULL rather than blowing up.
    """
    by_stripped = {c.strip(): c for c in csv_cols}
    parts = []
    for want in SLIM_COLS + PREV_NAME_COLS:
        actual = by_stripped.get(want)
        if actual is None:
            parts.append(f'NULL AS "{want}"')
        else:
            parts.append(f'"{actual}" AS "{want}"')
    return ",\n    ".join(parts)


def stage_snapshot(
    date: str,
    con: duckdb.DuckDBPyConnection,
    snapshot_dir: Path = ch_bulk.SNAPSHOT_DIR,
    stage_dir: Path = STAGE_DIR,
    keep_csv: bool = False,
) -> Path:
    """Extract one snapshot zip, parse it once, write a stage partition, drop the CSV.

    The stage partition holds **every** company in that month (all statuses, all
    sectors) with ``sector`` and ``segment`` attached. Pass 2 needs the non-matching
    rows too, because a universe member that gets SIC-recoded must still emit a row.
    """
    part_dir = stage_dir / f"snapshot_date={month_start(date)}"
    out = part_dir / "part.parquet"
    if out.exists():
        return out  # resumable: already staged

    csv_path = ch_bulk.extract_snapshot(date, dest_dir=snapshot_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    try:
        # all_varchar: 33 vintages, one consistent parse. ch_static coerces types
        # later with the same dayfirst=True / to_numeric rules NB01 relied on.
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW raw AS
            SELECT * FROM read_csv('{csv_path.as_posix()}',
                                   header=true, all_varchar=true, ignore_errors=false)
            """
        )
        csv_cols = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]

        con.execute(
            f"""
            COPY (
                WITH renamed AS (
                    SELECT {_select_list(csv_cols)}
                    FROM raw
                ),
                mapped AS (
                    SELECT
                        r.* EXCLUDE ("CompanyNumber"),
                        trim(r."CompanyNumber") AS "CompanyNumber",
                        -- NB01: first non-null SIC match wins, in column order 1..4
                        COALESCE(m1.sector, m2.sector, m3.sector, m4.sector) AS sector
                    FROM renamed r
                    LEFT JOIN sector_map m1 ON substr(r."SICCode.SicText_1", 1, 5) = m1.code
                    LEFT JOIN sector_map m2 ON substr(r."SICCode.SicText_2", 1, 5) = m2.code
                    LEFT JOIN sector_map m3 ON substr(r."SICCode.SicText_3", 1, 5) = m3.code
                    LEFT JOIN sector_map m4 ON substr(r."SICCode.SicText_4", 1, 5) = m4.code
                )
                SELECT * FROM mapped
            ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        if not keep_csv:
            csv_path.unlink(missing_ok=True)  # the zip is the archive; the CSV is scratch
    return out


def build_universe(
    con: duckdb.DuckDBPyConnection,
    stage_dir: Path = STAGE_DIR,
    out: Path = UNIVERSE_PATH,
) -> int:
    """Pass 1. Union of every CompanyNumber matching our sectors in *any* month.

    Deliberately does **not** filter on status: a company already in liquidation but
    in-sector belongs in the universe, because it is exactly the failure signal the
    credit-risk model needs.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT DISTINCT "CompanyNumber"
            FROM read_parquet('{(stage_dir / "**" / "*.parquet").as_posix()}')
            WHERE sector IS NOT NULL
        ) TO '{out.as_posix()}' (FORMAT PARQUET)
        """
    )
    return con.execute(
        f"SELECT count(*) FROM read_parquet('{out.as_posix()}')"
    ).fetchone()[0]


def extract_partition(
    date: str,
    con: duckdb.DuckDBPyConnection,
    stage_dir: Path = STAGE_DIR,
    panel_dir: Path = PANEL_DIR,
    universe_path: Path = UNIVERSE_PATH,
) -> Path:
    """Pass 2. Emit the panel partition for one month.

    Every universe member present that month is kept, whatever its status or current
    sector. Static features are computed with ``today=<the real snapshot date>`` so
    they are point-in-time correct: company_age_years / accounts_overdue / accounts_stale
    reflect what was true *then*, not what is true when the code happens to run.
    """
    ms = month_start(date)
    part_dir = panel_dir / f"snapshot_date={ms}"
    out = part_dir / "part.parquet"
    if out.exists():
        return out

    stage_part = stage_dir / f"snapshot_date={ms}" / "part.parquet"
    df = con.execute(
        f"""
        SELECT s.*
        FROM read_parquet('{stage_part.as_posix()}') s
        SEMI JOIN read_parquet('{universe_path.as_posix()}') u
          ON s."CompanyNumber" = u."CompanyNumber"
        """
    ).df()

    ch_static.strip_columns(df)
    df["segment"] = df["Accounts.AccountCategory"].map(SEGMENT_MAP)
    # The real file date, not the month start: that is when the data was true.
    ch_static.add_static_features(df, today=pd.Timestamp(date))

    df["is_active"] = df["CompanyStatus"] == "Active"
    df["snapshot_date"] = pd.Timestamp(ms)
    df["source_date"] = pd.Timestamp(date)

    keep = (
        SLIM_COLS
        + ["sector", "segment", "is_active", "snapshot_date", "source_date"]
        + ch_static.STATIC_FEATURE_COLS
    )
    df = df[[c for c in keep if c in df.columns]]

    part_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, compression="zstd")
    return out


# ---------------------------------------------------------------------------
# Step 3: deltas
# ---------------------------------------------------------------------------

# Every delta is strictly backward-looking from month t.
#
# **The gap problem.** June 2025 is genuinely missing from the register, so a bare
# positional LAG(3) would silently reach back *four* calendar months around the hole
# and quietly corrupt every delta in that region. Nothing would error or look odd.
#
# **The fix: a dense month spine.** We materialise every company against all 34 calendar
# months (universe CROSS JOIN months, LEFT JOIN the panel), so June 2025 exists as an
# explicit all-NULL row. Positional LAG(N) is then *exactly* N calendar months back by
# construction: reaching over the hole lands on the NULL row and the delta is NULL,
# while months either side still compute normally.
#
# Two rejected alternatives, recorded so nobody re-treads them:
#   - Four calendar self-joins (``l3.m = b.m - INTERVAL 3 MONTH``): correct, and the
#     semantics we want, but it materialises four hash tables over 49.6M rows and had
#     spilled 27GB without finishing. The spine gets the same answer with one join.
#   - Validating a positional LAG against the calendar and nulling mismatches: correct
#     but badly lossy. After the hole, LAG(12) is off-by-one for a whole year, so
#     ``d_charges_12m`` would be NULL from Jul 2025 to May 2026 even though the true
#     lag month exists and is perfectly usable.
#
# ``present`` distinguishes "no row for this company this month" from a real NULL, so a
# missing lag never masquerades as a change.
#
# **Streaks and recency** use window functions over the observed months, then express
# the answer with calendar arithmetic (``datediff('month', ...)``) so the output is
# still in real months. Note these are *censored* at the panel edges: a company whose
# first observed month is already overdue has an unknowable true streak start, so the
# streak counts from Oct 2023 rather than from whenever it really began.

DELTA_SQL = """
WITH months AS (
    SELECT CAST(unnest(generate_series(DATE '{first_month}', DATE '{last_month}',
                                       INTERVAL 1 MONTH)) AS DATE) AS m
),
universe AS (
    SELECT "CompanyNumber" AS cn FROM read_parquet('{universe_path}')
),
spine AS (
    -- Every company against every calendar month, including the missing June 2025.
    SELECT u.cn, mo.m FROM universe u CROSS JOIN months mo
),
observed AS (
    SELECT
        "CompanyNumber" AS cn,
        snapshot_date   AS m,
        source_date,
        "Mortgages.NumMortCharges"     AS charges,
        "Mortgages.NumMortOutstanding" AS outstanding,
        "Mortgages.NumMortSatisfied"   AS satisfied,
        debt_ratio, "CompanyStatus" AS status, is_active,
        size_tier, segment, sector, accounts_overdue, company_age_years,
        "SICCode.SicText_1"   AS sic1,
        "CompanyName"         AS cname,
        "RegAddress.PostCode" AS postcode,
        try_strptime("Accounts.NextDueDate", '%d/%m/%Y') AS accounts_next_due,
        try_strptime("ConfStmtNextDueDate", '%d/%m/%Y')  AS confstmt_next_due,
        -- Only the four real size tiers rank; Dormant/No Filings/Subsidiary/Unknown
        -- are filing buckets, not sizes, so they stay NULL and never fake an upgrade.
        CASE size_tier WHEN 'Micro' THEN 1 WHEN 'Small' THEN 2
                       WHEN 'Medium' THEN 3 WHEN 'Large' THEN 4 END AS tier_rank
    FROM read_parquet('{panel_glob}')
),
base AS (
    SELECT
        s.cn, s.m,
        o.cn IS NOT NULL AS present,
        o.source_date, o.charges, o.outstanding, o.satisfied, o.debt_ratio,
        o.status, o.is_active, o.size_tier, o.segment, o.sector, o.accounts_overdue,
        o.company_age_years, o.sic1, o.cname, o.postcode,
        o.accounts_next_due, o.confstmt_next_due, o.tier_rank
    FROM spine s
    LEFT JOIN observed o ON o.cn = s.cn AND o.m = s.m
),
lagged AS (
    SELECT
        *,
        -- On a dense spine LAG(N) IS the N-calendar-month lag. `present` at the lag
        -- position tells us whether that month held real data.
        COALESCE(LAG(present, 1)  OVER w, false) AS has_l1,
        COALESCE(LAG(present, 12) OVER w, false) AS has_l12,
        LAG(charges, 1)      OVER w AS charges_l1,
        LAG(status, 1)       OVER w AS status_l1,
        LAG(charges, 3)      OVER w AS charges_l3,
        LAG(charges, 6)      OVER w AS charges_l6,
        LAG(charges, 12)     OVER w AS charges_l12,
        LAG(outstanding, 3)  OVER w AS outstanding_l3,
        LAG(outstanding, 6)  OVER w AS outstanding_l6,
        LAG(outstanding, 12) OVER w AS outstanding_l12,
        LAG(satisfied, 12)   OVER w AS satisfied_l12,
        LAG(debt_ratio, 12)  OVER w AS debt_ratio_l12,
        LAG(tier_rank, 12)   OVER w AS tier_rank_l12,
        LAG(sic1, 12)        OVER w AS sic1_l12,
        LAG(cname, 12)       OVER w AS cname_l12,
        LAG(postcode, 12)    OVER w AS postcode_l12,
        -- Previous *observed* month, skipping absent rows, for run detection.
        LAG(status IGNORE NULLS)           OVER w AS status_prev_obs,
        LAG(segment IGNORE NULLS)          OVER w AS segment_prev_obs,
        LAG(accounts_overdue IGNORE NULLS) OVER w AS overdue_prev_obs
    FROM base
    WINDOW w AS (PARTITION BY cn ORDER BY m)
),
deltas AS (
    SELECT
        *,
        -- Arithmetic deltas go NULL automatically when the lag month held no data.
        charges     - charges_l3      AS d_charges_3m,
        charges     - charges_l6      AS d_charges_6m,
        charges     - charges_l12     AS d_charges_12m,
        outstanding - outstanding_l3  AS d_outstanding_3m,
        outstanding - outstanding_l6  AS d_outstanding_6m,
        outstanding - outstanding_l12 AS d_outstanding_12m,
        satisfied   - satisfied_l12   AS d_satisfied_12m,
        debt_ratio  - debt_ratio_l12  AS debt_ratio_trend_12m,
        CASE WHEN tier_rank IS NOT NULL AND tier_rank_l12 IS NOT NULL
             THEN tier_rank > tier_rank_l12 END AS segment_upgraded_12m,
        CASE WHEN tier_rank IS NOT NULL AND tier_rank_l12 IS NOT NULL
             THEN tier_rank < tier_rank_l12 END AS segment_downgraded_12m,
        -- IS DISTINCT FROM never returns NULL, so it would read an absent lag month as
        -- "changed". has_l12 is the guard that keeps missingness missing.
        CASE WHEN has_l12 THEN sic1     IS DISTINCT FROM sic1_l12     END AS sic_changed_12m,
        CASE WHEN has_l12 THEN cname    IS DISTINCT FROM cname_l12    END AS name_changed_12m,
        CASE WHEN has_l12 THEN postcode IS DISTINCT FROM postcode_l12 END AS postcode_changed_12m,
        CASE WHEN has_l1  THEN charges > charges_l1              END AS is_new_charge,
        CASE WHEN has_l1  THEN status IS DISTINCT FROM status_l1 END AS status_changed
    FROM lagged
),
runs AS (
    SELECT *,
        -- Only present rows can break a run; the gap month must not reset everyone.
        CASE WHEN present THEN status_prev_obs  IS NOT NULL
                           AND status_prev_obs  IS DISTINCT FROM status
             ELSE false END AS status_break,
        CASE WHEN present THEN segment_prev_obs IS NOT NULL
                           AND segment_prev_obs IS DISTINCT FROM segment
             ELSE false END AS segment_break,
        CASE WHEN present THEN overdue_prev_obs IS NOT NULL
                           AND overdue_prev_obs IS DISTINCT FROM accounts_overdue
             ELSE false END AS overdue_break
    FROM deltas
),
islands AS (
    SELECT *,
        SUM(CASE WHEN status_break  THEN 1 ELSE 0 END) OVER w AS status_grp,
        SUM(CASE WHEN segment_break THEN 1 ELSE 0 END) OVER w AS segment_grp,
        SUM(CASE WHEN overdue_break THEN 1 ELSE 0 END) OVER w AS overdue_grp,
        -- Trailing 12 calendar months inclusive of t. A RANGE frame keyed on the date
        -- is calendar-aware for free; the gap month simply contributes nothing.
        COALESCE(SUM(CASE WHEN is_new_charge THEN 1 ELSE 0 END)
                 OVER (PARTITION BY cn ORDER BY m
                       RANGE BETWEEN INTERVAL 11 MONTHS PRECEDING AND CURRENT ROW), 0)
            AS new_charge_events_12m,
        MAX(CASE WHEN is_new_charge THEN m END) OVER w AS last_new_charge_m,
        -- Strictly *before* t: the frame stops at 1 PRECEDING so month t never labels itself.
        COALESCE(MAX(CASE WHEN present AND NOT is_active THEN 1 ELSE 0 END)
                 OVER (PARTITION BY cn ORDER BY m
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)::BOOLEAN
            AS ever_distressed_before
    FROM runs
    WINDOW w AS (PARTITION BY cn ORDER BY m ROWS UNBOUNDED PRECEDING)
)
SELECT
    cn AS "CompanyNumber", m AS snapshot_date, source_date,
    charges AS "Mortgages.NumMortCharges",
    outstanding AS "Mortgages.NumMortOutstanding",
    satisfied AS "Mortgages.NumMortSatisfied",
    status AS "CompanyStatus", is_active, sector, segment, size_tier, tier_rank,
    sic1 AS "SICCode.SicText_1", cname AS "CompanyName", postcode AS "RegAddress.PostCode",
    company_age_years, debt_ratio, accounts_overdue,
    d_charges_3m, d_charges_6m, d_charges_12m,
    d_outstanding_3m, d_outstanding_6m, d_outstanding_12m,
    d_satisfied_12m, debt_ratio_trend_12m,
    new_charge_events_12m,
    datediff('month', last_new_charge_m, m) AS months_since_last_new_charge,
    status_changed,
    -- Island starts are measured over present months only, so a company that joins the
    -- register mid-panel does not inherit the spine's start date.
    datediff('month', MIN(CASE WHEN present THEN m END) OVER (PARTITION BY cn, status_grp),  m)
        AS months_in_current_status,
    ever_distressed_before,
    segment_upgraded_12m, segment_downgraded_12m,
    datediff('month', MIN(CASE WHEN present THEN m END) OVER (PARTITION BY cn, segment_grp), m)
        AS months_since_segment_change,
    CASE WHEN accounts_overdue
         THEN datediff('month', MIN(CASE WHEN present THEN m END) OVER (PARTITION BY cn, overdue_grp), m) + 1
         ELSE 0 END AS accounts_overdue_streak_months,
    -- Point-in-time: compared against the real snapshot date, never against "now".
    confstmt_next_due < source_date AS confstmt_late,
    datediff('day', source_date, accounts_next_due) AS days_to_next_accounts_due,
    sic_changed_12m, name_changed_12m, postcode_changed_12m
FROM islands
WHERE present
"""

# The panel's calendar span. June 2025 sits inside this range but has no snapshot, which
# is exactly why the spine is built from the calendar rather than from the manifest.
FIRST_MONTH = "2023-10-01"
LAST_MONTH = "2026-07-01"

DELTA_FEATURE_COLS = [
    "d_charges_3m", "d_charges_6m", "d_charges_12m",
    "d_outstanding_3m", "d_outstanding_6m", "d_outstanding_12m",
    "d_satisfied_12m", "debt_ratio_trend_12m",
    "new_charge_events_12m", "months_since_last_new_charge",
    "status_changed", "months_in_current_status", "ever_distressed_before",
    "segment_upgraded_12m", "segment_downgraded_12m", "months_since_segment_change",
    "accounts_overdue_streak_months", "confstmt_late", "days_to_next_accounts_due",
    "sic_changed_12m", "name_changed_12m", "postcode_changed_12m",
]


def build_deltas(
    panel_dir: Path = PANEL_DIR,
    out_dir: Path = DELTA_DIR,
    threads: int | None = None,
    memory_limit: str = "10GB",
) -> int:
    """Compute the backward-looking delta features over the whole panel at once.

    Deltas need the full history in scope (a 12-month lag reaches across partitions),
    so unlike the panel build this is one query, not a per-month loop. Output is
    written back out partitioned by ``snapshot_date`` to match the panel layout.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir.parent / "duckdb_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{tmp_dir.as_posix()}'")  # spill rather than OOM
    if threads:
        con.execute(f"PRAGMA threads={threads}")

    panel_glob = (panel_dir / "**" / "*.parquet").as_posix()
    sql = DELTA_SQL.format(
        panel_glob=panel_glob,
        universe_path=UNIVERSE_PATH.as_posix(),
        first_month=FIRST_MONTH,
        last_month=LAST_MONTH,
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


def build_panel(
    dates: list[str] | None = None,
    snapshot_dir: Path = ch_bulk.SNAPSHOT_DIR,
    stage_dir: Path = STAGE_DIR,
    panel_dir: Path = PANEL_DIR,
    threads: int | None = None,
) -> dict[str, int]:
    """Run the whole build: stage every snapshot, union the universe, extract the panel.

    Resumable throughout: any stage or panel partition already on disk is skipped, so
    an interrupted run picks up where it left off.
    """
    dates = list(ch_bulk.MANIFEST) if dates is None else dates
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")  # keeps the notebook/log output readable
    if threads:
        con.execute(f"PRAGMA threads={threads}")
    _register_sector_map(con)

    print(f"Pass 0: staging {len(dates)} snapshots")
    for i, date in enumerate(dates, 1):
        stage_snapshot(date, con, snapshot_dir=snapshot_dir, stage_dir=stage_dir)
        print(f"  [{i:>2}/{len(dates)}] staged {date}", flush=True)

    print("Pass 1: building universe")
    n_universe = build_universe(con, stage_dir=stage_dir)
    print(f"  universe: {n_universe:,} companies")

    print(f"Pass 2: extracting {len(dates)} panel partitions")
    counts: dict[str, int] = {}
    for i, date in enumerate(dates, 1):
        out = extract_partition(date, con, stage_dir=stage_dir, panel_dir=panel_dir)
        n = con.execute(
            f"SELECT count(*) FROM read_parquet('{out.as_posix()}')"
        ).fetchone()[0]
        counts[month_start(date)] = n
        print(f"  [{i:>2}/{len(dates)}] {month_start(date)}  {n:>9,} rows", flush=True)

    con.close()
    return counts
