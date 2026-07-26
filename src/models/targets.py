"""Step 5: self-labelled targets over the company-month panel.

Everything up to step 4b produced *features*. Nothing produced a target. This module
closes that gap: it stands in an origin month ``t``, looks **forward** in the same
panel, and writes down whether the thing we care about happened by ``t + H``.

The features come from month ``t``; the labels come from ``t+1 ... t+H`` and
**never from ``t`` itself**. That one rule is what makes the whole thing a
prospecting model rather than a description of the present: "who will need lending
in the next three months" is actionable, "who has a charge today" is not.

Four labels, all conditioned on **Active at ``t``**:

===================  ==========================================  ====  ===============
index                label                                       H     measured rate
===================  ==========================================  ====  ===============
Lending Readiness    ``Mortgages.NumMortCharges`` increases      3m    0.25 - 0.31%
Credit Risk          enters genuine insolvency                   6m    0.30 - 0.41%
Voluntary Exit       status becomes "Proposal to Strike off"     6m    6.7 - 8.5%
Growth Signal        size band moves up                          12m   2.1 - 2.2%
===================  ==========================================  ====  ===============

**Voluntary Exit is not attrition, and used to be called that.** This label fires when
a company proposes to strike itself off: it is winding down, and its revenue is going
to zero. That is *not* what the client means by attrition. Lloyds means a client
moving their banking to a competitor, and a struck-off company is not a relationship
to win back, it is a dead company. The two need different teams and different actions,
so the word is reserved for provider switching (see
``reports/client-requirements.md``) and this label says what it actually measures.
Real attrition is measured from charge-level lender identity in
``src/features/charges.py``, which the bulk file cannot see at all.

**Event, not state.** A label fires if the thing happened at *any* observed month in
``t+1 ... t+H``, not if it is still true at ``t+H``. For lending and insolvency the
two are near-identical, because a charge count only climbs and liquidation does not
reverse. For voluntary exit they differ by 2x: the earlier scoping note in
``reports/steps-5-6-modelling-guide.md`` quotes 3.4 - 3.8%, which is the strike-off
*state* at ``t+6`` (verified: 3.49% for the 2024-01 origin). Strike-off proposals are
routinely withdrawn when a company files its overdue accounts, so "ever proposed
within six months" is roughly twice "still proposed at month six".

We label the event. A proposal raised and withdrawn is still the moment a
relationship manager wanted to know about, and a state read off one month is
hostage to that month existing at all - which, given June 2025, is not a property
worth depending on.

Two traps that shaped these definitions, both hit while measuring (see
``reports/steps-5-6-modelling-guide.md``):

1. **"non-Active" is not distress.** "Active at t, non-Active by t+H" runs at ~4%,
   but ~90% of it is voluntary strike-off: dormant micro-companies quietly closing.
   That is not a credit event. Filtering to genuine insolvency drops it to ~0.34%.
   We model both, separately, because they are different questions with different
   audiences and blending them lets the loud one drown the important one.
2. **``segment`` is not a size ladder.** It mixes real sizes with filing states, so
   "segment changed" is ~13% at 12m and mostly ``No Filings`` <-> ``Micro`` churn.
   The panel already carries ``tier_rank``, which ranks only the four real tiers
   (Micro < Small < Medium < Large) and leaves the filing buckets NULL. Companies
   with no rank are **excluded** from the growth label rather than squeezed in.

**Origins are quarterly.** That makes the 3-month lending windows non-overlapping,
so each company-quarter is an independent observation rather than fifteen near-copies
of the same one. Distress and growth still overlap 2x and 4x; step 6's grouped CV
absorbs that.

**The June 2025 hole.** Forward windows are ``RANGE`` frames keyed on the calendar
date, not positional offsets, so a missing month simply contributes no rows to the
window instead of silently shifting it. Where a window contains *no* observed month
at all the label is NULL, never 0.

Layout on disk::

    data/processed/labels/origin_month=YYYY-MM-01/part.parquet
    data/processed/model_matrix/{target}/origin_month=YYYY-MM-01/part.parquet
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ..features import contracts, panel

LABEL_DIR = Path("data/processed/labels")
MATRIX_DIR = Path("data/processed/model_matrix")

# Quarterly, anchored on the first panel month.
ORIGIN_STEP_MONTHS = 3

# First origin at which every backward-looking feature is actually formed.
#
# The panel starts 2023-10, so a 12-month delta is NULL until 2024-10 and *every*
# delta is NULL at the 2023-10 origin itself. Labels are perfectly valid there, and
# the level features are real, so we label those origins anyway. But the missingness
# pattern is a calendar artefact, and in an out-of-time split it lands entirely in
# train and never in test - exactly the kind of thing a tree happily splits on and
# then cannot use. Step 6 should filter to this origin onwards for any target that
# can afford it (lending, insolvency and voluntary exit have 7+ origins left; growth has
# only 4, so there it is a genuine trade against sample size).
FIRST_FULL_ORIGIN = pd.Timestamp("2024-10-01")

# Genuine insolvency, as opposed to strike-off or dormancy. Lifted from Sneha's
# `is_insolvent` in notebooks/12_baseline_model.ipynb (itself adapted from Sam's
# attrition work) - the enumeration is the valuable part and it is the reason the
# credit-risk label is 0.34% signal rather than 90% strike-off noise.
#
# Written as an explicit set rather than her substring test because the panel has
# exactly ten distinct statuses and we would rather fail loudly on an eleventh than
# have it quietly fall through a `"administration" in s` check. `check_statuses`
# is what enforces that.
INSOLVENT_STATUSES = {
    "liquidation",
    "in administration",
    "in administration/administrative receiver",
    "in administration/receiver manager",
    "voluntary arrangement",
    "voluntary arrangement / receiver manager",
    "receivership",
    "live but receiver manager on at least one charge",
}

STRIKE_OFF_STATUS = "active - proposal to strike off"

# Every status we have seen in the panel, so an unrecognised one is a hard error
# rather than a silent zero in the insolvency label.
KNOWN_STATUSES = INSOLVENT_STATUSES | {"active", STRIKE_OFF_STATUS}

# target -> (label column, horizon in months)
#
# `voluntary_exit` was called `attrition` until 26 Jul 2026. Renamed because the
# client uses "attrition" for provider switching; see the docstring above.
TARGETS = {
    "lending":        ("y_lending", 3),
    "insolvency":     ("y_insolvency", 6),
    "voluntary_exit": ("y_voluntary_exit", 6),
    "growth":         ("y_growth", 12),
}

# Plausible per-origin base rates, bracketing the measured table in the module
# docstring with room either side. The point of the check is to catch a label that is
# *wrong*, not one that drifted a few basis points: a 20% "insolvency" rate means the
# definition broke.
EXPECTED_BASE_RATES = {
    "lending":        (0.0015, 0.0060),
    "insolvency":     (0.0020, 0.0060),
    "voluntary_exit": (0.0500, 0.1100),
    "growth":         (0.0150, 0.0300),
}

# Features carried straight off the panel at month t. `size_tier` is deliberately
# absent: `tier_rank` is the same information as a number LightGBM can split on.
LEVEL_FEATURE_COLS = [
    "Mortgages.NumMortCharges",
    "Mortgages.NumMortOutstanding",
    "Mortgages.NumMortSatisfied",
    "company_age_years",
    "debt_ratio",
    "accounts_overdue",
    "tier_rank",
]

CATEGORICAL_COLS = ["sector", "segment"]

FEATURE_COLS = (
    LEVEL_FEATURE_COLS
    + panel.DELTA_FEATURE_COLS
    + contracts.ASOF_FEATURE_COLS
    + CATEGORICAL_COLS
)


def _quote(values) -> str:
    """Render a python iterable as a SQL literal list."""
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


def origin_months(
    first_month: str = panel.FIRST_MONTH,
    last_month: str = panel.LAST_MONTH,
    step: int = ORIGIN_STEP_MONTHS,
) -> list[pd.Timestamp]:
    """The quarterly grid of origin months, anchored on the first panel month."""
    return list(pd.date_range(first_month, last_month, freq=pd.DateOffset(months=step)))


def max_origin(horizon: int, last_month: str = panel.LAST_MONTH) -> pd.Timestamp:
    """Latest origin whose label window still fits inside the panel.

    A label at ``t`` resolves at ``t + H``; past this month the window runs off the
    end of the register and "nothing happened" would mean "we cannot see yet".
    """
    return pd.Timestamp(last_month) - pd.DateOffset(months=horizon)


def target_origins(target: str, **kwargs) -> list[pd.Timestamp]:
    """Origin months usable for one target, i.e. those with a complete window."""
    _, horizon = TARGETS[target]
    cap = max_origin(horizon, kwargs.get("last_month", panel.LAST_MONTH))
    return [m for m in origin_months(**kwargs) if m <= cap]


def check_statuses(delta_dir: Path = panel.DELTA_DIR) -> pd.DataFrame:
    """Fail if the panel holds a CompanyStatus the insolvency mapping does not know.

    Cheap, and it is the only thing standing between a new status value and a label
    that quietly under-counts insolvency forever.
    """
    con = duckdb.connect()
    df = con.execute(
        f"""
        SELECT lower(trim("CompanyStatus")) AS status, count(*) AS n
        FROM read_parquet('{(delta_dir / "**" / "*.parquet").as_posix()}')
        GROUP BY 1 ORDER BY n DESC
        """
    ).df()
    con.close()
    unknown = set(df["status"]) - KNOWN_STATUSES
    if unknown:
        raise ValueError(
            f"unrecognised CompanyStatus values {sorted(unknown)} - decide whether "
            "each is insolvency, strike-off or neither, then add it to targets.py"
        )
    return df


LABEL_SQL = """
WITH obs AS (
    SELECT "CompanyNumber" AS cn,
           snapshot_date   AS m,
           is_active,
           "Mortgages.NumMortCharges" AS charges,
           tier_rank,
           lower(trim("CompanyStatus")) AS status
    FROM read_parquet('{delta_glob}')
),
fwd AS (
    -- RANGE frames on the date, so the window is t+1 .. t+H in *calendar* months.
    -- The missing June 2025 contributes no row instead of shifting the frame, which
    -- is the same reason panel.DELTA_SQL never uses a positional LAG.
    SELECT
        cn, m, is_active, charges, tier_rank,
        max(charges)  OVER w3  AS max_charges_f3,
        count(charges) OVER w3 AS n_obs_f3,
        max(CASE WHEN status IN ({insolvent}) THEN 1 ELSE 0 END) OVER w6 AS insolvent_f6,
        max(CASE WHEN status = '{strike_off}'  THEN 1 ELSE 0 END) OVER w6 AS strikeoff_f6,
        count(*)      OVER w6  AS n_obs_f6,
        max(tier_rank) OVER w12 AS max_tier_f12,
        count(*)      OVER w12 AS n_obs_f12
    FROM obs
    WINDOW
        w3  AS (PARTITION BY cn ORDER BY m
                RANGE BETWEEN INTERVAL 1 MONTH FOLLOWING AND INTERVAL 3 MONTH FOLLOWING),
        w6  AS (PARTITION BY cn ORDER BY m
                RANGE BETWEEN INTERVAL 1 MONTH FOLLOWING AND INTERVAL 6 MONTH FOLLOWING),
        w12 AS (PARTITION BY cn ORDER BY m
                RANGE BETWEEN INTERVAL 1 MONTH FOLLOWING AND INTERVAL 12 MONTH FOLLOWING)
)
SELECT
    cn AS "CompanyNumber",
    m  AS origin_month,
    -- Each label is NULL past its usable origin (window would run off the panel) and
    -- NULL where the window holds no observed month at all. NULL means "cannot say",
    -- and only 0 means "it did not happen".
    CASE WHEN m <= DATE '{max_lending}'    AND n_obs_f3  > 0
         THEN (max_charges_f3 > charges)::INT END AS y_lending,
    CASE WHEN m <= DATE '{max_insolvency}' AND n_obs_f6  > 0
         THEN insolvent_f6 END                    AS y_insolvency,
    CASE WHEN m <= DATE '{max_voluntary_exit}' AND n_obs_f6 > 0
         THEN strikeoff_f6 END                    AS y_voluntary_exit,
    -- Growth only means something for a company that has a size band at t; the
    -- filing buckets (No Filings / Dormant / Subsidiary / Unknown) rank NULL and are
    -- excluded rather than squeezed into the ladder.
    CASE WHEN m <= DATE '{max_growth}'     AND n_obs_f12 > 0
          AND tier_rank IS NOT NULL AND max_tier_f12 IS NOT NULL
         THEN (max_tier_f12 > tier_rank)::INT END AS y_growth
FROM fwd
WHERE is_active
  AND m IN ({origins})
"""


def build_labels(
    delta_dir: Path = panel.DELTA_DIR,
    out_dir: Path = LABEL_DIR,
    threads: int | None = None,
    memory_limit: str = "10GB",
) -> int:
    """Write the label table: one row per (company, quarterly origin), four 0/1 columns.

    Rows are restricted to companies **Active at the origin**, which is what all four
    labels are conditioned on. Forward windows need the whole history in scope, so
    like the delta build this is one query rather than a per-month loop.
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

    sql = LABEL_SQL.format(
        delta_glob=(delta_dir / "**" / "*.parquet").as_posix(),
        insolvent=_quote(sorted(INSOLVENT_STATUSES)),
        strike_off=STRIKE_OFF_STATUS,
        origins=_quote(m.date() for m in origin_months()),
        max_lending=max_origin(TARGETS["lending"][1]).date(),
        max_insolvency=max_origin(TARGETS["insolvency"][1]).date(),
        max_voluntary_exit=max_origin(TARGETS["voluntary_exit"][1]).date(),
        max_growth=max_origin(TARGETS["growth"][1]).date(),
    )
    con.execute(
        f"""
        COPY ({sql}) TO '{out_dir.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD,
         PARTITION_BY (origin_month), OVERWRITE_OR_IGNORE)
        """
    )
    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{(out_dir / '**' / '*.parquet').as_posix()}')"
    ).fetchone()[0]
    con.close()
    return n


def base_rates(label_dir: Path = LABEL_DIR) -> pd.DataFrame:
    """Positive rate per target per origin month, with the labelled row count.

    This is the cheapest possible check that the labels mean what we think they mean,
    and it catches almost every labelling mistake.
    """
    con = duckdb.connect()
    parts = " UNION ALL ".join(
        f"""
        SELECT '{name}' AS target, origin_month,
               count({col}) AS n, avg({col}::DOUBLE) AS base_rate
        FROM read_parquet('{(label_dir / "**" / "*.parquet").as_posix()}')
        WHERE {col} IS NOT NULL GROUP BY 2
        """
        for name, (col, _) in TARGETS.items()
    )
    df = con.execute(f"{parts} ORDER BY target, origin_month").df()
    con.close()
    return df


def check_base_rates(label_dir: Path = LABEL_DIR) -> pd.DataFrame:
    """Assert every per-origin base rate sits in its plausible band. Returns the table."""
    rates = base_rates(label_dir)
    bad = [
        f"  {r.target} @ {r.origin_month:%Y-%m}: {r.base_rate:.4%} "
        f"(expected {EXPECTED_BASE_RATES[r.target][0]:.2%} - {EXPECTED_BASE_RATES[r.target][1]:.2%})"
        for r in rates.itertuples()
        if not (
            EXPECTED_BASE_RATES[r.target][0] <= r.base_rate <= EXPECTED_BASE_RATES[r.target][1]
        )
    ]
    if bad:
        raise AssertionError("base rates outside their plausible band:\n" + "\n".join(bad))
    return rates


# The modelling matrix. Features at t LEFT JOIN contracts as-of t, then the label.
#
# Contract counts and flags mean "none" when a company is absent from the sparse
# as-of table, so they coalesce to 0; months_since_last_award has no zero-equivalent
# ("never won anything" is a true NULL) and is left alone. contracts.ASOF_COALESCE_ZERO
# is the authority on which is which.
#
# Sampling: keep every positive, downsample negatives to `neg_ratio` x. Done *per
# origin* so the origin mix is preserved for the out-of-time split, with a hash on
# the company number instead of a random draw so the sample is reproducible without
# carrying a seeded RNG through DuckDB. `neg_keep_rate` rides along on every row
# because step 6 has to undo it: downsampling negatives inflates every predicted
# probability, and the ranking survives that but the numbers do not.
MATRIX_SQL = """
WITH lab AS (
    SELECT "CompanyNumber", origin_month, {ycol} AS y
    FROM read_parquet('{label_glob}')
    WHERE {ycol} IS NOT NULL
),
rates AS (
    SELECT origin_month,
           least(1.0, {neg_ratio} * n_pos / nullif(n_neg, 0)) AS neg_keep_rate
    FROM (
        SELECT origin_month,
               sum(y)::DOUBLE            AS n_pos,
               sum(1 - y)::DOUBLE        AS n_neg
        FROM lab GROUP BY 1
    )
),
sampled AS (
    SELECT l.*, r.neg_keep_rate
    FROM lab l JOIN rates r USING (origin_month)
    WHERE l.y = 1
       OR (hash(l."CompanyNumber" || '|{target}') % 1000000) / 1000000.0 < r.neg_keep_rate
)
SELECT
    s."CompanyNumber",
    s.origin_month,
    s.y,
    s.neg_keep_rate,
    {feature_select}
FROM sampled s
JOIN read_parquet('{delta_glob}') f
  ON f."CompanyNumber" = s."CompanyNumber" AND f.snapshot_date = s.origin_month
LEFT JOIN read_parquet('{contracts_glob}') c
  ON c."CompanyNumber" = s."CompanyNumber" AND c.snapshot_date = s.origin_month
"""


def _feature_select() -> str:
    """SELECT list for FEATURE_COLS, taking contract columns from `c` and the rest from `f`."""
    parts = []
    for col in FEATURE_COLS:
        if col in contracts.ASOF_COALESCE_ZERO:
            parts.append(f'coalesce(c."{col}", 0) AS "{col}"')
        elif col in contracts.ASOF_FEATURE_COLS:
            parts.append(f'c."{col}"')
        else:
            parts.append(f'f."{col}"')
    return ",\n    ".join(parts)


def build_matrix(
    target: str,
    delta_dir: Path = panel.DELTA_DIR,
    label_dir: Path = LABEL_DIR,
    contracts_dir: Path = contracts.ASOF_DIR,
    out_dir: Path = MATRIX_DIR,
    neg_ratio: int = 10,
    threads: int | None = None,
    memory_limit: str = "10GB",
) -> pd.DataFrame:
    """Assemble and sample the modelling matrix for one target.

    ``contracts_dir`` is the A/B switch set up in step 4b: point it at
    ``contracts.ASOF_EXT_DIR`` to re-run with the name-matched contract rows and
    compare out-of-time AUC.

    Returns the per-origin summary (rows, positives, negative keep rate).
    """
    ycol, horizon = TARGETS[target]
    _check_contract_watermark(target, contracts_dir)

    target_dir = out_dir / target
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir.parent / "duckdb_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{tmp_dir.as_posix()}'")
    if threads:
        con.execute(f"PRAGMA threads={threads}")

    sql = MATRIX_SQL.format(
        ycol=ycol,
        target=target,
        neg_ratio=neg_ratio,
        label_glob=(label_dir / "**" / "*.parquet").as_posix(),
        delta_glob=(delta_dir / "**" / "*.parquet").as_posix(),
        contracts_glob=(contracts_dir / "**" / "*.parquet").as_posix(),
        feature_select=_feature_select(),
    )
    con.execute(
        f"""
        COPY ({sql}) TO '{target_dir.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD,
         PARTITION_BY (origin_month), OVERWRITE_OR_IGNORE)
        """
    )
    summary = con.execute(
        f"""
        SELECT origin_month,
               count(*) AS rows,
               sum(y)   AS positives,
               avg(y)   AS sampled_rate,
               any_value(neg_keep_rate) AS neg_keep_rate
        FROM read_parquet('{(target_dir / "**" / "*.parquet").as_posix()}')
        GROUP BY 1 ORDER BY 1
        """
    ).df()
    con.close()
    summary.insert(0, "target", target)
    summary.insert(1, "horizon_m", horizon)
    return summary


def _check_contract_watermark(target: str, contracts_dir: Path) -> None:
    """Refuse to build on origin months where the contract harvest is censored.

    The two OCDS bulk files are refreshed on different cadences, so contract counts
    in the final month or two fall because we stopped observing, not because
    companies stopped winning work. Fine to score on, not fine to train on.
    """
    flat = (
        contracts.FLAT_EXT_PATH
        if contracts_dir == contracts.ASOF_EXT_DIR
        else contracts.FLAT_PATH
    )
    watermark = contracts.harvest_watermark(flat)
    # Only a month that ends on or before the watermark is fully observed.
    last_complete = (watermark.to_period("M") - 1).to_timestamp()
    latest = max(target_origins(target))
    if latest > last_complete:
        raise ValueError(
            f"{target}: origin {latest:%Y-%m} is past the contract harvest watermark "
            f"({watermark:%Y-%m-%d}, last complete month {last_complete:%Y-%m}). "
            "Re-harvest contracts or shorten the origin grid."
        )
