"""
Gazette adapter + minimal builder, written against the NB11 blueprint.

This is step 3 of the plan: one adapter, end to end, into something the screen
can read. It does not fetch anything. It reads files that are already on disk.

    data/processed/dashboard_bulk_gazette_2026-07.parquet   1,531,094 companies
    data/processed/nb10_gazette_notices_thru_2026-07.csv      291,045 notices
    data/processed/nb14_news_signals_2026-06-30.csv               96 searched companies

The company file is the unified one built by notebooks/13_merge_bulk_gazette.ipynb:
the engineered July bulk with the Gazette features already joined on, so the join
no longer happens here. Selecting the companies with a signal is a filter on
`gaz_matched` rather than a merge.

This replaces company_master_gazette_2026-08.csv, which paired an August company
snapshot with July Gazette notices. Both halves of this file are July, so the
company state and the notices describe the same month. The universe also grew from
1,496,693 to 1,531,094 because the July bulk covers slightly more companies.

`lifecycle` (Trading, Fading, Distressed, Insolvent) is not a stored column here.
It is a pure lookup from CompanyStatus, so it is recomputed below from the July
status rather than carried over from the August file, which would have reintroduced
the month mismatch this change exists to remove.

Three fields the screen displays are identity rather than signal, and the July bulk
does not carry them: IncorporationDate, RegAddress.AddressLine1 and
RegAddress.PostTown. They are read from the August universe file. An incorporation
date cannot change and a registered address rarely does, so a one month gap on
these costs nothing, whereas losing them would leave a relationship manager with a
postcode and no way to recognise the company. Companies present in the July bulk
but absent from the August file simply have these blank.

The news source is live but its finding is an absence. 96 companies were searched on the
Guardian over a three year window and none has verifiable, company specific coverage. Five
had raw hits and all five were name collisions that verification rejected, which is recorded
per company so the screen can show the disambiguation working rather than just a zero.

This matters for how the screen must read the field. A company carries a `news` block only if
it was actually searched. "Searched and found nothing" and "never searched" are different
facts, and 1,530,998 companies are in the second group: searching the whole universe at the
Guardian's one call per second against a 500 per day quota would take about 18 days. Absence
of a `news` block therefore means unknown, not clean. See notebooks/14_news_signal_audit.ipynb,
which also records why the earlier NB08 news output could not be used.

Output:

    dashboard/data.js    window.STORE = { companies: [...], meta: {...} }

A .js file rather than .json on purpose, so the dashboard still opens by
double-clicking. Browsers block fetch() on file:// URLs.

Run:  python dashboard/build_data.py
"""

import json
import random
from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(r"C:\Users\visha\Lloyds_Github\data\processed")
OUT = Path(__file__).parent / "data.js"

SNAPSHOT_DATE = "2026-07-31"   # pinned, the end of the Gazette notice window
COMPANY_MONTH = "2026-07-01"   # the bulk's base_month, a month label not an instant
IDENTITY_SNAPSHOT = "2026-08-01"   # where the address and incorporation date come from
NEWS_SEARCH_DATE = "2026-06-30"    # pinned in NB09, the day the Guardian run treated as "now"
SEARCH_SOURCE = "guardian"
SEED = 42

# The four models, as handed over. Horizons run from 1 July 2026.
#
# `hit_rate` and `base_rate` are measured on held-out historical origins where the outcome
# window had closed. They are the honest way to describe a score, because the raw number runs
# optimistic exactly at the top of the list where the dashboard looks: the highest lending
# scores read about 0.577 while the observed hit rate in that band is 0.43. So the screen
# sorts on the score and describes with the hit rate, and never says "probability".
#
# `rankable` is not taken on trust from the handover. It was re-measured against this parquet:
#   score_lending        993 distinct values in its top 1,000   -> rankable
#   score_insolvency     961 distinct                            -> rankable
#   score_growth         994 distinct                            -> rankable
#   score_voluntary_exit  14 distinct, 998 of 1,000 rows tied    -> NOT rankable
# For voluntary exit the top-100 cutoff value alone is shared by 139 companies, so a "top 100"
# cannot even be formed without cutting a tie arbitrarily. It ships as a band, never a rank,
# and is excluded from every ordered list.
SCORE_MODELS = [
    {"key": "score_lending", "label": "Lending readiness", "horizon": "3 months",
     "window": "Aug to Oct 2026", "event": "take on new secured borrowing",
     "base_rate": 0.0027, "hit_rate": 0.43, "lift": 160, "rankable": True},
    {"key": "score_insolvency", "label": "Credit risk", "horizon": "6 months",
     "window": "Aug 2026 to Jan 2027", "event": "hit a genuine insolvency event",
     "base_rate": 0.0033, "hit_rate": 0.16, "lift": 45, "rankable": True},
    {"key": "score_voluntary_exit", "label": "Voluntary exit", "horizon": "6 months",
     "window": "Aug 2026 to Jan 2027", "event": "have a strike-off proposal filed",
     "base_rate": 0.077, "hit_rate": 0.85, "lift": 10, "rankable": False,
     "not_rankable_because": "998 of the top 1,000 scores are exact ties, and the top-100 "
                             "cutoff value alone is shared by 139 companies"},
    {"key": "score_growth", "label": "Growth", "horizon": "12 months",
     "window": "Aug 2026 to Jul 2027", "event": "move up a size tier",
     "base_rate": 0.021, "hit_rate": 0.22, "lift": 10, "rankable": True},
]
N_QUIET = 250                  # companies with no signal, for the empty state
MAX_NOTICES_PER_COMPANY = 8    # keeps the timeline readable and the file small

# The store ships as one file the browser parses on load, so every repeated
# string costs. Notice URLs are all the same stem, so we store the id only and
# the screen rebuilds the link.
NOTICE_URL_STEM = "https://www.thegazette.co.uk/id/notice/"


# ---------------------------------------------------------------------------
# Rule 1: one cleaning function, imported by every adapter
# ---------------------------------------------------------------------------
def clean_company_number(raw):
    """Canonical 8 character company number, or None if it cannot be one."""
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if s in ("", "NAN", "NONE"):
        return None
    s = s.replace(" ", "")
    if s.isdigit():
        return s.zfill(8)
    if len(s) == 8 and s[:2].isalpha() and s[2:].isdigit():
        return s
    if len(s) <= 8:
        return s.zfill(8)
    return None


def norm_cols(df):
    """Some columns in this project carry a leading space. Strip them."""
    df.columns = [c.strip() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Notice type -> the vocabulary the screen uses
# ---------------------------------------------------------------------------
SIGNAL_TYPE = [
    ("winding up", "gazette_petition"),
    ("winding-up", "gazette_petition"),
    ("administrat", "gazette_administration"),
    ("liquidat", "gazette_liquidation"),
    ("receiver", "gazette_receivership"),
    ("creditor", "gazette_creditors"),
    ("dividend", "gazette_dividend"),
    ("strike", "gazette_strike_off"),
]


def classify(notice_type):
    t = str(notice_type).lower()
    for needle, key in SIGNAL_TYPE:
        if needle in t:
            return key
    return "gazette_other"


# These must match the ladder NB10/NB11 actually build, which is STAGE_MAP:
#   1 petition | 2 winding-up order, administration, voluntary liquidation
#   3 creditor process | 4 dividend | 5 closing
# The ladder measures how far through the insolvency a company has gone, not how
# bad the outcome is. Severity is a separate field (gaz_severity_tier), so these
# labels name the step rather than editorialising about it.
#
# An earlier version of this map was shifted by one and labelled stage 2 as
# "Creditor action", which described 17,438 companies holding a winding-up order
# or an administration as though a supplier were chasing an invoice.
STAGE_LABEL = {1: "Winding-up petition", 2: "Formal insolvency",
               3: "Creditor process", 4: "Dividend to creditors",
               5: "Final meeting"}


# Copied verbatim from notebooks/build_widened_universe.py rather than imported,
# because that file is a script that reads a 2.8 GB CSV on import. It is a pure
# lookup on CompanyStatus, which is why it can be recomputed here from the July
# status instead of being carried across from the August file.
LIFECYCLE = {
    "Active": "Trading",
    "Active - Proposal to Strike off": "Fading",
    "Live but Receiver Manager on at least one charge": "Distressed",
    "Voluntary Arrangement": "Distressed",
    "In Administration": "Insolvent",
    "In Administration/Administrative Receiver": "Insolvent",
    "In Administration/Receiver Manager": "Insolvent",
    "ADMINISTRATION ORDER": "Insolvent",
    "ADMINISTRATIVE RECEIVER": "Insolvent",
    "RECEIVERSHIP": "Insolvent",
    "RECEIVER MANAGER / ADMINISTRATIVE RECEIVER": "Insolvent",
    "Liquidation": "Insolvent",
}


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
# Only the columns the screen actually reads. The unified file carries 124, and
# materialising all of them for 1.5M rows costs memory for data nothing renders.
PROFILE_COLS = [
    "CompanyName", "CompanyNumber", "CompanyStatus", "is_active",
    "sector", "segment", "size_tier", "company_age_years",
    "gaz_matched", "RegAddress.PostCode",
]
# The four model scores. Present only on Active companies by design, see SCORE_MODELS.
SCORE_COLS = ["score_lending", "score_insolvency", "score_voluntary_exit", "score_growth"]
LENDER_COLS = [
    "is_lbg_client", "ever_lbg_client", "primary_lender_group", "n_charges_outstanding",
    "n_lbg_charges_outstanding", "lbg_share_of_outstanding", "n_distinct_lenders",
    "n_competitor_lenders", "months_since_last_lbg_charge_created",
    "months_since_last_lbg_satisfaction", "competitor_entered_12m",
    "lbg_charge_satisfied_6m", "competitor_charge_created_6m",
]
BORROWING_COLS = [
    "Mortgages.NumMortCharges", "Mortgages.NumMortOutstanding", "Mortgages.NumMortSatisfied",
    "debt_ratio", "d_charges_3m", "d_charges_6m", "new_charge_events_12m",
    "months_since_last_new_charge",
]
FILING_COLS = [
    "accounts_overdue", "accounts_overdue_streak_months", "accounts_stale_streak_months",
    "confstmt_late", "days_to_next_accounts_due", "months_since_last_accounts_filing",
    "months_since_last_confstmt",
]
CONTRACT_COLS = [
    "ever_won_contract", "contracts_won_12m", "total_value_won_12m", "awards_with_value_12m",
    "months_since_last_award", "d_contracts_12m", "first_award_in_12m",
    "contracts_asof_month", "contracts_stale",
]
GAZ_COLS = [
    "gaz_notice_count_total", "gaz_notice_count_12m", "gaz_max_distress_stage",
    "gaz_severity_tier", "gaz_first_notice_date", "gaz_latest_notice_date",
    "gaz_days_since_latest_notice", "gaz_active_case_flag", "gaz_court_involved_flag",
    "gaz_stage_progressed_flag", "gaz_recurring_distress_flag", "gaz_recent_notice_90d_flag",
]
# Identity only. Not signals, and not present in the July bulk. See the module docstring.
#
# The postcode is pulled across too, even though the July bulk has one. 17,751 companies
# (1.2%) moved registered office between the two snapshots, and taking the street and town
# from August while keeping the July postcode produced addresses that never existed. A
# displayed address has to come whole from one snapshot. The July postcode is untouched in
# the parquet and remains the one to use for any analysis.
IDENTITY_COLS = ["IncorporationDate", "RegAddress.AddressLine1", "RegAddress.PostTown",
                 "identity.PostCode"]

IDENTITY_SRC = ["IncorporationDate", "RegAddress.AddressLine1", "RegAddress.PostTown",
                "RegAddress.PostCode"]

# --------------------------------------------------------------------------
# The read, the derived columns and the identity join, done in DuckDB against
# the parquet directly. No database file is created and the parquet is never
# rewritten; DuckDB reads it in place and hands back one DataFrame, so every
# consumer below this point is unchanged.
#
# Two pieces of this were verified against the pandas code they replace before
# the swap, because both could have silently changed meaning:
#
#   clean_cn()  matched clean_company_number() on 3,027,787 rows across the
#               parquet and the identity CSV, 0 mismatches.
#   the _pct    matched Series.rank(pct=True, method="average") on all
#   window      1,409,284 scored companies, max difference 0.000000.
#
# The percentile is the subtle one: DuckDB's own PERCENT_RANK() is (rank-1)/(n-1)
# over the minimum rank, which is NOT what pandas computes for ties. The
# expression below reproduces pandas exactly: average rank over n.
# --------------------------------------------------------------------------
con = duckdb.connect()

def clean_cn(expr):
    """SQL twin of clean_company_number(), verified row-for-row against it."""
    s = f"replace(upper(trim({expr})),' ','')"
    return (f"CASE WHEN {s} IS NULL OR {s} IN ('','NAN','NONE') THEN NULL "
            f"WHEN regexp_matches({s},'^[0-9]+$') "
            f"THEN lpad({s}, greatest(8, CAST(length({s}) AS INTEGER)), '0') "
            f"WHEN length({s}) <= 8 THEN lpad({s}, 8, '0') ELSE NULL END")

# One source of truth for the lifecycle map: the Python dict above, rendered to SQL.
_life = " ".join(f"WHEN trim(\"CompanyStatus\") = '{k}' THEN '{v}'" for k, v in LIFECYCLE.items())
LIFECYCLE_SQL = f"CASE {_life} ELSE 'Unknown' END"

_cols = (PROFILE_COLS + GAZ_COLS + SCORE_COLS + LENDER_COLS
         + BORROWING_COLS + FILING_COLS + CONTRACT_COLS)
_select = ", ".join(f'b."{c}"' for c in _cols if c not in
                    ("gaz_first_notice_date", "gaz_latest_notice_date"))
# Rendered to YYYY-MM-DD here so nothing downstream has to care about types.
_dates = ", ".join(f"coalesce(strftime(b.\"{c}\", '%Y-%m-%d'), '') AS \"{c}\""
                   for c in ("gaz_first_notice_date", "gaz_latest_notice_date"))
# Windows are partitioned by is_active so the rank is computed over the scored
# population only, exactly as the pandas version did; the CASE then discards the
# non-active partition so those rows stay null rather than carrying a rank of their own.
_pcts = ", ".join(
    f"""CASE WHEN b.is_active THEN
        round(100.0 * (1.0 - ((rank() OVER (PARTITION BY b.is_active ORDER BY b."{c}")
        + (count(*) OVER (PARTITION BY b.is_active, b."{c}") - 1) / 2.0)
        / count(*) OVER (PARTITION BY b.is_active))), 2) END AS "{c}_pct\"""" for c in SCORE_COLS)
_ident = ", ".join(f'i."{c}"' for c in IDENTITY_SRC if c != "RegAddress.PostCode")

PARQUET = (DATA / "dashboard_bulk_gazette_2026-07.parquet").as_posix()
IDENT_CSV = (DATA / "filtered_bb_sme_sectors_all_status_2026-08-01.csv").as_posix()

print("reading the unified July company file (duckdb, direct on the parquet) ...")
uni = con.execute(f"""
    WITH ident AS (
        SELECT {clean_cn('"CompanyNumber"')} AS cn,
               "IncorporationDate", "RegAddress.AddressLine1", "RegAddress.PostTown",
               "RegAddress.PostCode" AS "identity.PostCode"
        FROM read_csv('{IDENT_CSV}', all_varchar=true, ignore_errors=true)
        QUALIFY row_number() OVER (PARTITION BY cn) = 1
    ),
    base AS (
        SELECT *, {clean_cn('"CompanyNumber"')} AS cn
        FROM read_parquet('{PARQUET}')
        QUALIFY row_number() OVER (PARTITION BY cn) = 1
    )
    SELECT b.cn, {_select}, {_dates}, {_pcts},
           {LIFECYCLE_SQL} AS lifecycle,
           (coalesce(b.ever_lbg_client, false) AND NOT coalesce(b.is_lbg_client, false))
               AS former_lbg,
           {_ident}, i."identity.PostCode"
    FROM base b
    LEFT JOIN ident i USING (cn)
    WHERE b.cn IS NOT NULL
    -- Explicit, because DuckDB parallelises the join and does not otherwise guarantee
    -- row order. Without it two runs of this script produced byte-different data.js
    -- files with identical content, which makes the output impossible to diff.
    ORDER BY b.cn
""").df()

print(f"  {len(uni):,} companies")
print("  " + uni["lifecycle"].value_counts().to_string().replace("\n", "\n  "))

# The full universe stays whole. Nothing is filtered out here, including the 25,891
# rows with a NULL sector, which are companies that were in one of our target sectors
# in another month of the panel and are deliberately kept so a SIC recode does not
# look like a dissolution.
assert len(uni) == 1_531_094, f"universe changed size: {len(uni):,}"

n_former = int(uni["former_lbg"].sum())
print(f"  former LBG clients: {n_former:,} ({int((uni['former_lbg'] & uni['is_active']).sum()):,} still Active)")
assert n_former == 14_416, f"former-LBG count changed: {n_former:,}"

active_mask = uni["is_active"].fillna(False)

missing = int(uni["IncorporationDate"].isna().sum())
print(f"attaching identity fields from the {IDENTITY_SNAPSHOT} universe ...")
print(f"  matched {len(uni) - missing:,} of {len(uni):,}  "
      f"({missing:,} left blank: in the July bulk but not the August file)")

# The old CSV source handed everything over as a string, so the builder below leans
# on `(value or "")`. A parquet hands over real nulls, and NaN is truthy, so that
# idiom would sail past the guard and then fail on .strip(). Normalise once here.
for c in ["CompanyName", "CompanyStatus", "sector", "segment",
          "RegAddress.PostCode", "gaz_severity_tier"] + IDENTITY_COLS:
    uni[c] = uni[c].fillna("").astype(str)

print("reading notices ...")
NOTICES_CSV = (DATA / "nb10_gazette_notices_thru_2026-07.csv").as_posix()
nt = con.execute(f"""
    SELECT *, {clean_cn('"CompanyNumber"')} AS cn
    FROM read_csv('{NOTICES_CSV}', all_varchar=true, ignore_errors=true)
""").df()
before = len(nt)
no_number = int(nt["cn"].isna().sum())
no_date = int(nt["notice_date"].isna().sum())
nt = nt[nt["cn"].notna() & nt["notice_date"].notna()].copy()
# Reported separately because they are not the same problem and the split matters.
# In the 2026-07 crawl the whole loss is missing numbers: 129,918 notices whose text
# never prints a registered number, and zero with a missing date. See the "notices with
# no company number" section of notebooks/13_merge_bulk_gazette.ipynb for what that
# costs and how it would be recovered. It is an upstream gap, not something this
# builder introduces, and it means notice counts here are floors rather than totals.
print(f"  {len(nt):,} notices kept of {before:,}  "
      f"({no_number:,} dropped: no company number, {no_date:,}: no date)")

print("reading news signals ...")
NEWS_CSV = (DATA / "nb14_news_signals_2026-06-30.csv").as_posix()
news = con.execute(f"""
    SELECT * FROM (
        SELECT *, {clean_cn('"CompanyNumber"')} AS cn
        FROM read_csv('{NEWS_CSV}', all_varchar=true, ignore_errors=true))
    WHERE cn IS NOT NULL
    QUALIFY row_number() OVER (PARTITION BY cn) = 1
""").df()
# news_verified_count arrives as text under all_varchar; the comparison below and the
# per-company block both expect a number, so restore the type the CSV reader inferred.
news["news_verified_count"] = pd.to_numeric(news["news_verified_count"], errors="coerce")
news["news_raw_hits"] = pd.to_numeric(news["news_raw_hits"], errors="coerce")
news_by_cn = news.set_index("cn").to_dict("index")
print(f"  {len(news):,} companies searched ({SEARCH_SOURCE}, {NEWS_SEARCH_DATE}), "
      f"{int((news['news_verified_count'] > 0).sum())} with verified coverage, "
      f"{int((news['news_raw_hits'] > 0).sum())} with raw hits that verification rejected")

# NB13 already did the join on the cleaned company number, so this is a filter.
flagged = uni[uni["gaz_matched"] == 1].copy()
print(f"\nGazette companies inside the universe: {len(flagged):,}")

nt = nt[nt["cn"].isin(set(flagged["cn"]))].copy()
print(f"notices belonging to them:            {len(nt):,}")


# ---------------------------------------------------------------------------
# Adapter: notices -> signal rows
# ---------------------------------------------------------------------------
def to_signals(frame):
    """One row per notice, in the agreed eight column shape."""
    rows = []
    for r in frame.itertuples(index=False):
        rows.append({
            "company_number": r.cn,
            "signal_type": classify(r.notice_type),
            "signal_date": str(r.notice_date)[:10],
            "value": 1,
            "detail": str(r.notice_type),
            "source": "gazette",
            # These notices print a company number in the body, so the match is
            # exact. Name-only notices are excluded upstream.
            "confidence": 1.0,
            "retrieved_at": SNAPSHOT_DATE,
            "url": None if pd.isna(r.notice_url) else str(r.notice_url),
        })
    return rows


signals = to_signals(nt)
print(f"built {len(signals):,} signal rows")

by_company = {}
for s in signals:
    by_company.setdefault(s["company_number"], []).append(s)
for k in by_company:
    by_company[k].sort(key=lambda s: s["signal_date"])


# ---------------------------------------------------------------------------
# Build one row per company
# ---------------------------------------------------------------------------
def num(v, default=0):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return default


def flag(v):
    return str(v).strip().lower() in ("1", "1.0", "true", "yes")


# Keys where 0 is the natural default and absence means the same thing, so they can be
# dropped from the store. Deliberately excludes every months_since_* and days_to_* field,
# where 0 means "this month" or "due today" and dropping it would change the meaning.
ZERO_IS_DEFAULT = {
    "overdue_streak", "stale_streak", "outstanding", "lbg_outstanding", "lenders",
    "competitors", "satisfied", "new_12m", "won_12m", "value_12m", "with_value_12m",
}


def compact(block):
    """Drop the values a reader can assume, so 33k companies do not each carry a row of
    false and zero. None and False always go; 0 goes only for the counts listed above."""
    return {k: v for k, v in block.items()
            if v is not None and v is not False and not (v == 0 and k in ZERO_IS_DEFAULT)}


def none_if_blank(v):
    """Parquet nulls arrive as None or NaN; both should ship as null, not the string 'nan'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def address(p):
    """One address, from one snapshot. Never a mix of the two.

    Normally the August identity record: street, town and its own postcode. If a
    company is in the July bulk but not the August file there is no identity record
    at all, and the July postcode is shown alone rather than nothing.
    """
    line1 = str(p.get("RegAddress.AddressLine1") or "").strip()
    town = str(p.get("RegAddress.PostTown") or "").strip()
    postcode = str(p.get("identity.PostCode") or "").strip()

    if not any(b and b != "nan" for b in (line1, town, postcode)):
        postcode = str(p.get("RegAddress.PostCode") or "").strip()   # July fallback

    return ", ".join(b for b in (line1, town, postcode) if b and b != "nan")


# Which companies the store will actually carry, decided before any dict is built. The
# universe is 1.53M rows and now ~50 columns wide; materialising a dict per company for all
# of them costs gigabytes for rows nothing renders. Nothing is filtered from the universe
# here, this only decides what gets written to the page.
all_cns = set(uni["cn"])
flagged_set = set(flagged["cn"])
# Sorted for the same reason as the quiet sample and the main query: this list feeds the
# order of the companies array, and an unordered reader result made the output vary run
# to run with identical content.
news_only = sorted(cn for cn in news_by_cn if cn not in flagged_set and cn in all_cns)

# Former LBG clients are the most directly actionable segment in the file, and only 601 of
# the 14,416 carry a Gazette notice. Without adding the rest, the filter chip would offer a
# twentieth of the list it claims to.
lbg_only = sorted(set(uni.loc[uni["former_lbg"], "cn"]) - flagged_set - set(news_only))

random.seed(SEED)
covered = flagged_set | set(news_only) | set(lbg_only)
# Sorted before sampling so the seed alone determines the pick. Without this the sample
# rides on whatever row order the reader happened to return, and swapping the query
# engine silently changed all 250 quiet companies despite the seed being unchanged.
quiet = random.sample(sorted(c for c in uni["cn"] if c not in covered), N_QUIET)

needed = covered | set(quiet)
profiles = uni[uni["cn"].isin(needed)].set_index("cn").to_dict("index")
print(f"\nstore will carry {len(needed):,} companies "
      f"({len(flagged_set):,} Gazette, {len(news_only):,} news-only, "
      f"{len(lbg_only):,} former-LBG-only, {N_QUIET} quiet)")


def build_company(cn, gaz=None):
    p = profiles.get(cn, {})
    rec = {
        "number": cn,
        "name": (p.get("CompanyName") or "").strip(),
        "status": (p.get("CompanyStatus") or "").strip(),
        "lifecycle": (p.get("lifecycle") or "Unknown").strip(),
        "incorporated": (p.get("IncorporationDate") or "").strip(),
        "sector": (p.get("sector") or "").strip(),
        "segment": (p.get("segment") or "").strip(),
        "address": address(p),
        "timeline": [],
        "gazette": None,
        "news": None,
        "active": bool(p.get("is_active")),
        "scores": None,
        "lender": None,
        "borrowing": None,
        "filing": None,
        "contracts": None,
    }

    # Scores exist for Active companies only. For everyone else the field stays null so
    # the screen can render the reason: a lending forecast for a company already in
    # liquidation is a number with nothing behind it, and a zero would read as one.
    if rec["active"] and p.get("score_lending") is not None and not pd.isna(p.get("score_lending")):
        rec["scores"] = {}
        for m in SCORE_MODELS:
            rec["scores"][m["key"].replace("score_", "")] = {
                "score": round(float(p[m["key"]]), 6),
                "pct": round(float(p[m["key"] + "_pct"]), 2),   # 0 = top of the population
            }

    ever_lbg, is_lbg = flag(p.get("ever_lbg_client")), flag(p.get("is_lbg_client"))
    if ever_lbg or is_lbg or num(p.get("n_charges_outstanding")) > 0:
        rec["lender"] = compact({
            "is_lbg": is_lbg,
            "ever_lbg": ever_lbg,
            "former_lbg": bool(ever_lbg and not is_lbg),
            "primary": none_if_blank(p.get("primary_lender_group")),
            "outstanding": num(p.get("n_charges_outstanding")),
            "lbg_outstanding": num(p.get("n_lbg_charges_outstanding")),
            "lenders": num(p.get("n_distinct_lenders")),
            "competitors": num(p.get("n_competitor_lenders")),
            "months_since_lbg_satisfied": num(p.get("months_since_last_lbg_satisfaction"), None),
            "competitor_6m": flag(p.get("competitor_charge_created_6m")),
            "competitor_12m": flag(p.get("competitor_entered_12m")),
            "lbg_satisfied_6m": flag(p.get("lbg_charge_satisfied_6m")),
        })

    if num(p.get("Mortgages.NumMortCharges")) > 0:
        rec["borrowing"] = compact({
            "total": num(p.get("Mortgages.NumMortCharges")),
            "outstanding": num(p.get("Mortgages.NumMortOutstanding")),
            "satisfied": num(p.get("Mortgages.NumMortSatisfied")),
            "debt_ratio": num(p.get("debt_ratio"), None),
            "d_3m": num(p.get("d_charges_3m"), None),
            "d_6m": num(p.get("d_charges_6m"), None),
            "new_12m": num(p.get("new_charge_events_12m")),
            "months_since_new": num(p.get("months_since_last_new_charge"), None),
        })

    # Filing health applies to every company, so it is always emitted.
    rec["filing"] = compact({
        "overdue": flag(p.get("accounts_overdue")),
        "overdue_streak": num(p.get("accounts_overdue_streak_months")),
        "stale_streak": num(p.get("accounts_stale_streak_months")),
        "confstmt_late": flag(p.get("confstmt_late")),
        "days_to_due": num(p.get("days_to_next_accounts_due"), None),
        "months_since_accounts": num(p.get("months_since_last_accounts_filing"), None),
        "months_since_confstmt": num(p.get("months_since_last_confstmt"), None),
    })

    # Contracts are as at 31 May 2026, two months behind the rest of the file, because
    # Find a Tender's feed ends 5 June and later months would understate awards.
    if flag(p.get("ever_won_contract")):
        rec["contracts"] = compact({
            "ever": True,
            "won_12m": num(p.get("contracts_won_12m")),
            "value_12m": num(p.get("total_value_won_12m")),
            "with_value_12m": num(p.get("awards_with_value_12m")),
            "months_since": num(p.get("months_since_last_award"), None),
            "d_12m": num(p.get("d_contracts_12m"), None),
            "first_in_12m": flag(p.get("first_award_in_12m")),
        })

    # Present only for companies that were actually searched. Absent means unknown, not clean.
    n = news_by_cn.get(cn)
    if n is not None:
        verified = num(n.get("news_verified_count"))
        rec["news"] = {
            "source": n.get("news_source"),
            "searched": n.get("news_search_date"),
            "window_years": num(n.get("news_window_years")),
            "verified": verified,
            "raw_hits": num(n.get("news_raw_hits")),
            "status": n.get("news_status"),
        }
        # Headline plus link, so anything the screen shows can be checked by a reader
        # rather than taken on trust. The same shape as the Gazette evidence links.
        def articles(title_col, url_col):
            titles = [t.strip() for t in str(n.get(title_col) or "").split("|") if t.strip()]
            urls = [u.strip() for u in str(n.get(url_col) or "").split("|") if u.strip()]
            if not titles or titles[0].lower() == "nan":
                return []
            return [{"title": t, "url": urls[i] if i < len(urls) else None}
                    for i, t in enumerate(titles)][:3]

        # The rejected articles are the evidence that disambiguation ran and refused a
        # collision, so they ship for the five companies that had any. A zero with nothing
        # behind it looks like the search never happened.
        rejected = articles("news_rejected_titles", "news_rejected_urls")
        if rejected:
            rec["news"]["rejected"] = rejected
        if verified:
            rec["news"]["sentiment"] = num(n.get("news_sentiment_score"), None)
            rec["news"]["sentiment_label"] = n.get("news_sentiment_label")
            found = articles("news_verified_titles", "news_verified_urls")
            if found:
                rec["news"]["articles"] = found

    events = by_company.get(cn, [])
    if len(events) > MAX_NOTICES_PER_COMPANY:
        events = events[-MAX_NOTICES_PER_COMPANY:]
    # Compact shape: date, detail, notice id. Source is always gazette and
    # confidence is always 1.0 for these, so the screen supplies both.
    rec["timeline"] = [
        {"date": e["signal_date"], "detail": e["detail"],
         "id": (e["url"] or "").rsplit("/", 1)[-1] or None}
        for e in events
    ]

    if gaz is not None:
        stage = num(gaz.get("gaz_max_distress_stage"))
        # Only the flags that are true are shipped, as a short list. A flag that
        # is absent is false, which keeps 19,000 rows of False out of the file.
        flags = [name for name, col in [
            ("active_case", "gaz_active_case_flag"),
            ("court", "gaz_court_involved_flag"),
            ("progressed", "gaz_stage_progressed_flag"),
            ("recurring", "gaz_recurring_distress_flag"),
            ("recent_90d", "gaz_recent_notice_90d_flag"),
        ] if flag(gaz.get(col))]
        rec["gazette"] = {
            "notice_count": num(gaz.get("gaz_notice_count_total")),
            "count_12m": num(gaz.get("gaz_notice_count_12m")),
            "stage": stage,
            "stage_label": STAGE_LABEL.get(stage, "Unclassified"),
            "severity_tier": (gaz.get("gaz_severity_tier") or "").strip(),
            "first_date": (gaz.get("gaz_first_notice_date") or "")[:10],
            "latest_date": (gaz.get("gaz_latest_notice_date") or "")[:10],
            "days_since": num(gaz.get("gaz_days_since_latest_notice"), None),
            "flags": flags,
        }
    return rec


companies = [build_company(r["cn"], gaz=r) for r in flagged.to_dict("records")]

# Every searched company has to be in the store or the news source is invisible: only 1 of the
# 96 carries a Gazette notice, so 95 would otherwise never be rendered. Same reasoning for the
# former-LBG segment. Quiet companies are results, not missing rows.
for cn in news_only + lbg_only + quiet:
    companies.append(build_company(cn, gaz=None))
print(f"added: {len(news_only):,} news-only, {len(lbg_only):,} former-LBG-only, {len(quiet):,} quiet")

lifecycle_counts = uni["lifecycle"].value_counts().to_dict()
flagged_by_life = {}
for c in companies:
    if c["gazette"]:
        flagged_by_life[c["lifecycle"]] = flagged_by_life.get(c["lifecycle"], 0) + 1

print(f"\n{len(companies):,} companies in the store "
      f"({len(flagged):,} with a signal, {N_QUIET} with none)")
print("flagged by lifecycle:", flagged_by_life)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
store = {
    "meta": {
        "snapshot_date": SNAPSHOT_DATE,
        "built_from": ["dashboard_bulk_gazette_2026-07.parquet",
                       "nb10_gazette_notices_thru_2026-07.csv"],
        # Company state and Gazette signals now describe the same month. The identity
        # date is separate because address and incorporation date come from August.
        "company_snapshot_date": COMPANY_MONTH,
        "identity_snapshot_date": IDENTITY_SNAPSHOT,
        # Contracts joins the live set: the columns are already in the parquet. It is the
        # one live source that is not July, being frozen at 31 May 2026 on purpose.
        # Property joined the live set on 19 Aug 2026: HM Land Registry CCOD, matched on
        # company number at confidence 1.00, 60,588 of these companies. Hiring was dropped
        # entirely rather than left pending, because Adzuna returned 401 on every endpoint
        # and no data was ever collected. serve.py reports these from what it actually
        # loaded, so this list matters only if data.js is rebuilt.
        "sources_live": ["gazette", "news", "contracts", "property", "grants", "trademark"],
        "sources_pending": [],
        # News is live but reports an absence, and the screen needs the numbers to say so
        # honestly. `not_searched` is the important one: it is unknown, not clean.
        "news": {
            "source": SEARCH_SOURCE,
            "search_date": NEWS_SEARCH_DATE,
            "window_years": 3,
            "searched": int(len(news)),
            "with_verified_coverage": int((news["news_verified_count"] > 0).sum()),
            "with_raw_hits_rejected": int((news["news_raw_hits"] > 0).sum()),
            "not_searched": int(len(uni) - len(news)),
        },
        "signal_rows": len(signals),
        "companies_with_signal": int(len(flagged)),
        "companies_without_signal": N_QUIET,
        "universe": int(len(uni)),
        # The four models, their horizons, and the measured performance the screen should
        # describe them with. `rankable` was re-verified against this parquet, not assumed.
        "score_models": SCORE_MODELS,
        "scored_companies": int(active_mask.sum()),
        "unscored_companies": int(len(uni) - active_mask.sum()),
        "former_lbg": n_former,
        "former_lbg_active": int((uni["former_lbg"] & uni["is_active"]).sum()),
        # Counted over the store itself. Deriving it as lbg_only + flagged undercounted by 9,
        # the former-LBG companies that arrived via the news sample rather than either branch.
        "former_lbg_in_store": int(uni.loc[uni["cn"].isin(needed), "former_lbg"].sum()),
        # The column stores the month label 2026-05-01, but the as-of gate is
        # publication_date <= last_day(month), so coverage is complete to 31 May.
        # Showing the 1st would understate the vintage by a month.
        "contracts_asof": "2026-05-31",
        "lifecycle_counts": lifecycle_counts,
        "flagged_by_lifecycle": flagged_by_life,
        "notice_url_stem": NOTICE_URL_STEM,
    },
    "companies": companies,
}

OUT.write_text("window.STORE = " + json.dumps(store, separators=(",", ":")) + ";",
               encoding="utf-8")
print(f"wrote {OUT}  ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")
