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
