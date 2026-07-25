"""Resolve contract suppliers that published no Companies House number.

Step 4 matched suppliers on the ``GB-COH`` identifier only. That is exact, but it
is published on ~32% of Contracts Finder supplier parties and ~11% of Find a
Tender ones, so the contract features reach only ~1% of the panel. This module
recovers roughly twice that by matching the remainder on **normalised name plus
postcode**, and, just as importantly, measures how often it is wrong.

**Why name+postcode and not name alone.** Measured against a ground-truth set of
~102k supplier records whose true ``CompanyNumber`` we know from their ``GB-COH``
identifier: name alone is 87.6% precise, name+postcode is 92.4%. Tightening the
name rules further (>=2 words, >=3 words, >=12 characters) buys about one
percentage point of precision for up to 62% of the recall, so it is not worth it.

**Where the residual ~8% comes from.** Only 37% of contract-winning companies are
in our three-sector universe at all. Conditioned on the true company being in the
universe, precision is 98%. So the errors are dominated by suppliers whose true
company sits *outside* the universe but whose name happens to match an in-universe
company uniquely. Matching against the **full 5.7M-company register** rather than
just the universe lets those out-of-universe companies absorb their own names, and
that is why :func:`build_reference` reads ``panel_stage`` and not ``panel``.

**On point-in-time.** The reference spans all 33 snapshots, so a company that has
since renamed or relocated is still findable. That is deliberate and is not
leakage: deciding that the string "ACME LTD" denotes company 01234567 is identity
resolution, not a feature. It names the row; it says nothing about the future. The
features built on top of these rows stay strictly as-of, gated on publication date
exactly as in :mod:`src.features.contracts`.

Nothing here overwrites the strict artefacts. The extended set lands in its own
directory so the two can be A/B'd in the modelling notebooks.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.features import contracts, panel

# This module builds several SQL globs internally rather than taking them all as
# arguments, so it resolves the repo root from its own location and is safe to
# call from a notebook (cwd=notebooks/) or from the repo root alike.
ROOT = Path(__file__).resolve().parents[2]

# Legal-form suffixes carry no identifying information and are written
# inconsistently by procurement officers ("Ltd", "LIMITED", "ltd."), so they come
# off both sides of the join.
SUFFIX_RE = r"( LIMITED| LTD| PLC| LLP| CIC| CIO)+$"


def normalise_name_sql(column: str) -> str:
    """SQL that normalises a company name for matching.

    Uppercase, drop everything that is not a letter, digit or space, collapse
    whitespace, then strip trailing legal-form suffixes. Applied identically to
    both sides of the join, which is the only property that really matters.
    """
    cleaned = f"regexp_replace({column}, '[^A-Za-z0-9 ]', '', 'g')"
    collapsed = f"regexp_replace(upper({cleaned}), '\\s+', ' ', 'g')"
    return f"trim(regexp_replace({collapsed}, '{SUFFIX_RE}', '', 'g'))"


def build_reference(con: duckdb.DuckDBPyConnection,
                    stage_dir: Path = panel.STAGE_DIR,
                    table: str = "ref") -> int:
    """Build the (company, normalised name, postcode) lookup from the full register.

    Reads ``panel_stage``, which holds every company on the register (~5.7M) for
    every snapshot, not just our sector universe. Using the full register is what
    keeps precision up: a supplier whose true company is out of universe will
    usually match *that* company too, making the key ambiguous, and ambiguous keys
    are discarded rather than resolved.

    Falls back to the sector panel if the staging tree has been cleaned up, at a
    measured cost of about 0.4 percentage points of precision.
    """
    stage_dir = ROOT / stage_dir
    source_dir = stage_dir if stage_dir.exists() else ROOT / panel.PANEL_DIR
    if source_dir is not stage_dir:
        print(f"  {stage_dir} missing, falling back to {panel.PANEL_DIR} "
              f"(slightly lower precision)")
    glob = (source_dir / "**" / "*.parquet").as_posix()
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {table} AS
        SELECT DISTINCT "CompanyNumber" AS cn,
               {normalise_name_sql('"CompanyName"')} AS nm,
               upper(replace("RegAddress.PostCode", ' ', '')) AS pc
        FROM read_parquet('{glob}')
        WHERE "CompanyName" IS NOT NULL
    """)
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _connect(threads: int | None = None, memory_limit: str = "12GB") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    con.execute(f"SET memory_limit='{memory_limit}'")
    tmp = ROOT / panel.DELTA_DIR.parent / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    if threads:
        con.execute(f"PRAGMA threads={threads}")
    return con


# Accept a supplier only when its (name, postcode) resolves to exactly one company
# on the whole register, and that company is in our universe. Ambiguity is thrown
# away, never broken by a tie-break: picking one of two candidates would be a coin
# flip recorded as a fact.
RESOLVE_SQL = """
WITH sup AS (
    SELECT DISTINCT {norm_name} AS nm, match_pc AS pc
    FROM supplier_keys
    WHERE match_pc <> '' AND match_name <> ''
),
cand AS (
    SELECT s.nm, s.pc, count(DISTINCT r.cn) AS n_cand, min(r.cn) AS cn
    FROM sup s JOIN ref r ON r.nm = s.nm AND r.pc = s.pc
    GROUP BY 1, 2
)
SELECT nm, pc, cn
FROM cand
WHERE n_cand = 1
  AND cn IN (SELECT DISTINCT "CompanyNumber" FROM read_parquet('{panel_glob}'))
"""


def resolve_by_name(unmatched: pd.DataFrame,
                    con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Map unmatched supplier ``(match_name, match_pc)`` pairs to a CompanyNumber.

    Returns one row per resolvable pair with columns ``nm``, ``pc``, ``cn``.
    Suppliers with no postcode are dropped: name-only matching measured 87.6%,
    below the bar we are willing to defend, so the extended set keeps a single
    uniform quality standard.
    """
    con.register("supplier_keys", unmatched[["match_name", "match_pc"]])
    sql = RESOLVE_SQL.format(
        norm_name=normalise_name_sql("match_name"),
        panel_glob=(ROOT / panel.PANEL_DIR / "**" / "*.parquet").as_posix(),
    )
    return con.execute(sql).df()


def build_flat_ext(raw_dir: Path = contracts.RAW_DIR,
                   out_path: Path = contracts.FLAT_EXT_PATH,
                   threads: int | None = None) -> pd.DataFrame:
    """Flatten both feeds keeping unmatched suppliers, resolve them, post-process.

    The cross-source de-duplication in :func:`contracts.postprocess` runs *after*
    resolution, so a contract identified by ``GB-COH`` on one platform and by name
    on the other still collapses to a single award.
    """
    flat = contracts.flatten_sources(ROOT / raw_dir, keep_unmatched=True)
    matched = flat["CompanyNumber"].notna()
    print(f"  {matched.sum():,} rows already have GB-COH, "
          f"{(~matched).sum():,} need resolving", flush=True)

    con = _connect(threads=threads)
    print("  building full-register reference...", flush=True)
    n_ref = build_reference(con)
    print(f"  reference: {n_ref:,} (company, name, postcode) triples", flush=True)

    lookup = resolve_by_name(flat[~matched], con)
    con.close()
    print(f"  resolved {len(lookup):,} distinct (name, postcode) keys "
          f"to {lookup['cn'].nunique():,} companies", flush=True)

    # Apply the lookup back onto the unmatched rows.
    norm = (flat.loc[~matched, "match_name"].str.upper()
            .str.replace(r"[^A-Z0-9 ]", "", regex=True)
            .str.replace(r"\s+", " ", regex=True)
            .str.replace(SUFFIX_RE, "", regex=True).str.strip())
    keys = pd.MultiIndex.from_arrays([norm, flat.loc[~matched, "match_pc"]])
    resolved = pd.Series(
        lookup.set_index(pd.MultiIndex.from_arrays([lookup["nm"], lookup["pc"]]))["cn"]
    ).reindex(keys)

    flat.loc[~matched, "CompanyNumber"] = resolved.to_numpy()
    flat.loc[~matched & flat["CompanyNumber"].notna(), "match_method"] = "name_pc"

    kept = flat[flat["CompanyNumber"].notna()]
    print(f"  {len(kept):,} rows survive ({len(kept) - matched.sum():,} newly resolved)",
          flush=True)

    ext = contracts.postprocess(kept)
    out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ext.to_parquet(out_path, index=False)
    return ext


def evaluate_precision(raw_dir: Path = contracts.RAW_DIR,
                       threads: int | None = None) -> pd.DataFrame:
    """Measure the matcher against ground truth, rather than asserting it works.

    Every supplier that published a ``GB-COH`` identifier is a labelled example: we
    know the answer. So we throw the identifier away, run the matcher on the name
    (and postcode) alone, and compare. Reported per strategy:

    - ``precision`` - of the matches we would have accepted, how many are right.
      This is the number that decides whether the extended set is safe to use.
    - ``recall`` - of the labelled suppliers that are in our universe and therefore
      *could* be recovered, how many we actually recover.

    The labelled set is mildly optimistic: a buyer diligent enough to enter a
    company number may also enter a tidier company name. It is still far stronger
    evidence than any unvalidated assumption.
    """
    flat = contracts.flatten_sources(ROOT / raw_dir, keep_unmatched=True)
    lab = (flat.loc[flat["CompanyNumber"].notna(),
                    ["CompanyNumber", "match_name", "match_pc"]]
           .rename(columns={"CompanyNumber": "true_cn"})
           .drop_duplicates())
    lab = lab[lab["match_name"] != ""]

    con = _connect(threads=threads)
    build_reference(con)
    con.register("lab_df", lab)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE lab AS
        SELECT true_cn, {normalise_name_sql('match_name')} AS nm, match_pc AS pc
        FROM lab_df""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE uni AS
        SELECT DISTINCT "CompanyNumber" AS cn
        FROM read_parquet('{(ROOT / panel.PANEL_DIR / "**" / "*.parquet").as_posix()}')""")

    strategies = {
        "name only": ("r.nm = l.nm", ""),
        "name + postcode": ("r.nm = l.nm AND r.pc = l.pc", "WHERE pc <> ''"),
    }
    rows = []
    for label, (join, where) in strategies.items():
        res = con.execute(f"""
            WITH l AS (SELECT DISTINCT true_cn, nm, pc FROM lab {where}),
            m AS (SELECT l.true_cn, l.nm, count(DISTINCT r.cn) AS n_cand, min(r.cn) AS cn
                  FROM l JOIN ref r ON {join} GROUP BY 1, 2),
            kept AS (SELECT * FROM m WHERE n_cand = 1 AND cn IN (SELECT cn FROM uni))
            SELECT (SELECT count(*) FROM kept) AS accepted,
                   (SELECT count(*) FROM kept WHERE cn = true_cn) AS correct,
                   (SELECT count(*) FROM l JOIN uni u ON u.cn = l.true_cn) AS recoverable
        """).fetchone()
        accepted, correct, recoverable = res
        rows.append({
            "strategy": label,
            "accepted": accepted,
            "correct": correct,
            "precision": correct / max(accepted, 1),
            "recall": correct / max(recoverable, 1),
        })
    con.close()
    return pd.DataFrame(rows)
