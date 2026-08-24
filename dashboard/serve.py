"""Query server for the dashboard: Parquet -> DuckDB -> HTTP API.

The point of this file is that the browser stops being the place the company universe
lives. DuckDB reads the parquet in place and answers questions about all 1,531,094
companies; the API returns only the rows asked for. Nothing is precomputed into a
store, no database file is created, and the parquet is never written to.

    python dashboard/serve.py            # then open http://127.0.0.1:8000

Which parquet
-------------
Defaults to `dashboard_bulk_gazette_2026-07.parquet` rather than the raw
`dashboard_bulk_2026-07.parquet` that the brief names. Both hold exactly the same
1,531,094 companies, and the enriched file is a verified strict superset: every one of
the raw file's 69 columns is present, plus 55 `gaz_` columns. Defaulting to the raw file
would mean the API could not answer any Gazette question, which the dashboard already
asks. Pass --parquet to point at the raw file instead; the universe is identical either
way.

Safety
------
Every value reaching SQL goes through a DuckDB parameter, and every column name is
checked against an explicit allow-list below. A filter or sort key the server does not
recognise is rejected rather than interpolated, because these values arrive from the
query string.
"""
import argparse
import os
import threading
import webbrowser
from pathlib import Path

import duckdb
from flask import Flask, jsonify, request, send_from_directory

HERE = Path(__file__).parent

# The data tree lives outside the repository, because it holds files far too large
# to commit. Where it sits differs per machine, so it is resolved in three steps:
# --data on the command line, then the LLOYDS_DATA environment variable, then the
# path it was developed against. The last is a fallback, not a requirement: anyone
# cloning this repo can point it at their own copy without editing the source.
DEFAULT_DATA = Path(r"C:\Users\visha\Lloyds_Github\data")
DATA = Path(os.environ.get("LLOYDS_DATA") or DEFAULT_DATA)
DEFAULT_PARQUET = DATA / "processed" / "dashboard_bulk_gazette_2026-07.parquet"
RAW_PARQUET = DATA / "raw" / "dashboard_bulk_2026-07.parquet"

MAX_LIMIT = 500          # nothing may ask the server for the whole universe
DEFAULT_LIMIT = 50

# --------------------------------------------------------------------------------
# THE FILTER SYSTEM
#
# One declarative table, used by three things: the WHERE builder, the facet-count
# endpoint, and the /api/filters listing the UI renders itself from. Defining a filter
# once is what stops the panel and the query drifting apart.
#
# Every entry is verified against the parquet and documented in FILTER_SPEC.md.
#
# `kind`:
#   in       value IN (...) on a column
#   in_expr  value IN (...) on a SQL expression
#   tri      Yes / No / Not stated, where "No" means observed-false, never unknown
#   bool     simple true filter (no NULLs exist in these columns)
#   range    numeric min/max
#   choice   a named set of predicates
# --------------------------------------------------------------------------------
REGION_EXPR = "regexp_extract(\"RegAddress.PostCode\", '^[A-Z]+')"
# The lifecycle CASE is defined further down, so it is referenced here by placeholder and
# substituted at query time by sql_of().

FILTERS = {
    # ---- Core -----------------------------------------------------------------
    "segment":    dict(group="Core", label="Segment", kind="in", col="segment"),
    "lifecycle":  dict(group="Core", label="Lifecycle", kind="in_expr", expr="__LIFECYCLE__"),
    "region":     dict(group="Core", label="Region", kind="in_expr", expr=REGION_EXPR,
                       many=True),
    "industry":   dict(group="Core", label="Industry (SIC)", kind="in",
                       col="SICCode.SicText_1", many=True),
    "sector":     dict(group="Core", label="Sector", kind="in", col="sector", nullable=True),
    "age":        dict(group="Core", label="Company age", kind="range", col="company_age_years"),

    # ---- Borrowing ------------------------------------------------------------
    "ever_borrowed":  dict(group="Borrowing", label="Ever borrowed", kind="bool",
                           expr='"Mortgages.NumMortCharges" > 0'),
    "outstanding":    dict(group="Borrowing", label="Outstanding mortgages", kind="range",
                           col="Mortgages.NumMortOutstanding"),
    "repayment":      dict(group="Borrowing", label="Repayment state", kind="choice", choices={
                           "fully_repaid": '"Mortgages.NumMortCharges" > 0 AND debt_ratio = 0',
                           "partial": "debt_ratio > 0 AND debt_ratio < 1",
                           "all_outstanding": "debt_ratio = 1"}),
    "new_charge_12m": dict(group="Borrowing", label="New charge in 12m", kind="bool",
                           expr="new_charge_events_12m > 0"),

    # ---- Lender ---------------------------------------------------------------
    "lbg":            dict(group="Lender", label="LBG relationship", kind="choice", choices={
                           "current": "is_lbg_client",
                           "former": "ever_lbg_client AND NOT is_lbg_client",
                           "never": "NOT ever_lbg_client"}),
    "main_lender":    dict(group="Lender", label="Main lender", kind="in",
                           col="primary_lender_group", nullable=True),
    "lenders":        dict(group="Lender", label="Number of lenders", kind="range",
                           col="n_distinct_lenders"),
    "competitor":     dict(group="Lender", label="Competitor lender present", kind="bool",
                           expr="n_competitor_lenders > 0"),
    "competitor_6m":  dict(group="Lender", label="Competitor charge created (6m)",
                           kind="bool", expr="competitor_charge_created_6m"),
    "competitor_lbg": dict(group="Lender", label="Competitor entered an LBG relationship (12m)",
                           kind="bool", expr="competitor_entered_12m"),

    # ---- Filing ---------------------------------------------------------------
    "overdue":        dict(group="Filing", label="Accounts overdue", kind="bool",
                           expr="accounts_overdue"),
    "overdue_6m":     dict(group="Filing", label="Overdue 6+ months", kind="bool",
                           expr="accounts_overdue_streak_months >= 6"),
    "confstmt_late":  dict(group="Filing", label="Confirmation statement late", kind="bool",
                           expr="confstmt_late"),
    "no_filing_24m":  dict(group="Filing", label="No filing 24+ months", kind="bool",
                           expr="accounts_stale_streak_months >= 24"),

    # ---- Momentum (all tri-state: NULL means no 12-month history) -------------
    "size_move":      dict(group="Momentum", label="Size tier moved", kind="choice",
                           nullable=True, null_col="segment_upgraded_12m", choices={
                           "up": "segment_upgraded_12m", "down": "segment_downgraded_12m",
                           "none": "NOT segment_upgraded_12m AND NOT segment_downgraded_12m"}),
    "relocated":      dict(group="Momentum", label="Relocated in 12m", kind="tri",
                           col="postcode_changed_12m"),
    "sic_changed":    dict(group="Momentum", label="Industry changed 12m", kind="tri",
                           col="sic_changed_12m"),

    # ---- Signals --------------------------------------------------------------
    "lending":   dict(group="Signals", label="Lending readiness", kind="choice",
                      nullable=True, null_col="score_lending", choices={
                      "top1": "score_lending >= __P99_LENDING__",
                      "top10": "score_lending >= __P90_LENDING__"}),
    "growth":    dict(group="Signals", label="Growth", kind="choice",
                      nullable=True, null_col="score_growth", choices={
                      "top1": "score_growth >= __P99_GROWTH__",
                      "top10": "score_growth >= __P90_GROWTH__"}),
    "risk":      dict(group="Signals", label="Credit risk", kind="choice",
                      nullable=True, null_col="score_insolvency", choices={
                      "top1": "score_insolvency >= __P99_RISK__",
                      "top10": "score_insolvency >= __P90_RISK__"}),
    "gazette":   dict(group="Signals", label="Gazette", kind="choice", choices={
                      "none": "gaz_matched = 0",
                      "any": "gaz_matched = 1",
                      "formal_insolvency": "gaz_severity_tier = 'formal_insolvency'",
                      "recent_365": "gaz_recent_notice_365d_flag = 1",
                      "active_case": "gaz_active_case_flag = 1",
                      "court": "gaz_court_involved_flag = 1",
                      "petition": "gaz_has_winding_up_petition = 1",
                      "recent_90": "gaz_recent_notice_90d_flag = 1",
                      "terminal": "gaz_severity_tier = 'terminal'",
                      "early_warning": "gaz_severity_tier = 'early_warning'"}),
}

# Trading segments: excludes Dormant, No Filings, Subsidiary, Unknown. `is_active` alone
# does not do this, because Dormant is a SEGMENT while is_active is a STATUS, and 89.4%
# of Dormant-segment companies hold Active status.
TRADING = "segment IN ('Micro','Small','Medium','Large')"

# Approved presets. `retains` records how much of the closest single filter each keeps;
# anything above ~80% would be a filter wearing a preset's clothes and was rejected.
#
# `filters` is the SAME predicate written in the panel's own vocabulary, so a preset can be
# loaded into the filter controls and then adjusted rather than being an opaque clause. The
# values are exactly what the controls themselves emit ("yes"/"no" for bool, choice keys for
# choice, arrays for multi-selects, strings for range bounds), so a loaded preset shows up
# as selected options rather than as something the panel has to special-case.
#
# Every mapping below was verified by SET DIFFERENCE against the `where` clause, not by
# count: for each of these, the companies matched by `where` and the companies matched by
# `filters` differ by 0 in both directions. `where` remains the definition; `filters` is a
# second expression of it that the UI can take apart. If the two ever drift, the preset is
# what is right and the mapping is what is wrong.
#
# `contract_no_borrowing` carries no mapping on purpose. Its `contracts_won_12m > 0`
# condition has no filter control in the approved set, and expressing the preset without it
# would return 805,602 companies rather than 2,303. Rather than invent a filter that the
# spec never approved, that preset stays server-side and says so on screen.
PRESETS = [
    # "No outstanding charge" is now stated directly rather than through debt_ratio.
    # debt_ratio is rounded to 2dp upstream (99 distinct values in the file), so a company
    # whose true ratio fell below 0.005 stored as 0.00 and read as fully repaid. Exactly one
    # company in the file did: ANTALIS LIMITED (01088345), 416 charges with 2 still
    # outstanding, ratio 0.0048. The new form is a strict subset of the old, 31,003 -> 31,002,
    # and nothing enters that was not there before.
    dict(key="proven_borrower", label="Proven borrower, no incumbent", pop=31002, retains=26.8,
         where=f'is_active AND {TRADING} AND "Mortgages.NumMortCharges" > 0 '
               f'AND "Mortgages.NumMortOutstanding" = 0',
         filters={"lifecycle": ["Trading"], "segment": ["Micro", "Small", "Medium", "Large"],
                  "ever_borrowed": "yes", "outstanding_max": "0"},
         note="Borrowed before and cleared it. No incumbent to displace."),
    dict(key="unlevered_growth", label="Established, unlevered, high growth", pop=31012, retains=28.6,
         where=f'is_active AND {TRADING} AND company_age_years >= 5 '
               f'AND "Mortgages.NumMortCharges" = 0 AND score_growth >= __P90_GROWTH__',
         filters={"lifecycle": ["Trading"], "segment": ["Micro", "Small", "Medium", "Large"],
                  "age_min": "5", "ever_borrowed": "no", "growth": "top10"},
         note="Five years trading, never borrowed, top 10% growth."),
    dict(key="prospects_not_banked", label="Best prospects we don't bank", pop=8992, retains=63.8,
         where=f"is_active AND {TRADING} AND score_lending >= __P99_LENDING__ "
               f"AND NOT ever_lbg_client",
         filters={"lifecycle": ["Trading"], "segment": ["Micro", "Small", "Medium", "Large"],
                  "lending": "top1", "lbg": "never"},
         note="Top 1% for new borrowing, never an LBG client."),
    dict(key="exposure_deteriorating", label="Secured exposure deteriorating", pop=5916, retains=8.8,
         where='"Mortgages.NumMortOutstanding" > 0 AND accounts_overdue_streak_months >= 6',
         filters={"outstanding_min": "1", "overdue_6m": "yes"},
         note="Security is held and the company has stopped filing on time."),
    dict(key="growing_borrowing", label="Growing and borrowing", pop=3609, retains=32.2,
         where=f"is_active AND {TRADING} AND new_charge_events_12m > 0 "
               f"AND score_growth >= __P90_GROWTH__",
         filters={"lifecycle": ["Trading"], "segment": ["Micro", "Small", "Medium", "Large"],
                  "new_charge_12m": "yes", "growth": "top10"},
         note="Expanding and actively taking on secured debt."),
    dict(key="silent_distress", label="Silent distress, no Gazette yet", pop=2520, retains=50.4,
         where="is_active AND gaz_matched = 0 AND accounts_overdue_streak_months >= 6 "
               "AND confstmt_late",
         filters={"lifecycle": ["Trading"], "gazette": ["none"],
                  "overdue_6m": "yes", "confstmt_late": "yes"},
         note="Both filing signals failed, nothing has reached the Gazette."),
    dict(key="contract_no_borrowing", label="Contract winner with no borrowing", pop=2303, retains=39.2,
         where=f'is_active AND {TRADING} AND contracts_won_12m > 0 '
               f'AND "Mortgages.NumMortCharges" = 0',
         filters=None,
         not_adjustable="won a public contract in the last 12 months",
         # No mapping means no controls to read the conditions off, so they are spelled
         # out here instead. Display only: the preset is still applied from `where`.
         conditions=["Still trading", "Micro, Small, Medium or Large",
                     "Won a public contract in the last 12 months",
                     "Has never registered a charge"],
         note="Just won public work, never borrowed. Delivery needs working capital."),
    dict(key="rival_moved_in", label="Lapsed client, rival moved in", pop=467, retains=9.4,
         where="ever_lbg_client AND NOT is_lbg_client AND competitor_charge_created_6m",
         filters={"lbg": "former", "competitor_6m": "yes"},
         note="Left us, and a competitor took a charge within 6 months."),
    dict(key="risk_on_our_security", label="High credit risk on our security", pop=401, retains=3.6,
         where="is_active AND score_insolvency >= __P99_RISK__ AND n_lbg_charges_outstanding > 0",
         filters={"lifecycle": ["Trading"], "risk": "top1", "lbg": "current"},
         note="Top 1% insolvency risk where LBG holds an outstanding charge."),
]

# --------------------------------------------------------------------------------
# Legacy allow-lists, still used by /api/filter. A name not here never reaches SQL.
# --------------------------------------------------------------------------------
TEXT_FILTERS = {
    "sector", "segment", "CompanyStatus", "size_tier",
    "gaz_severity_tier", "gaz_current_stage", "primary_lender_group",
}
BOOL_FILTERS = {
    "is_active", "accounts_overdue", "confstmt_late", "ever_distressed_before",
    "is_lbg_client", "ever_lbg_client", "ever_won_contract", "competitor_charge_created_6m",
}
NUMERIC_FILTERS = {
    "score_lending", "score_insolvency", "score_voluntary_exit", "score_growth",
    "company_age_years", "debt_ratio", "gaz_notice_count_total", "gaz_max_distress_stage",
    "n_charges_outstanding", "n_competitor_lenders", "contracts_won_12m",
    "Mortgages.NumMortCharges", "Mortgages.NumMortOutstanding",
}
# Filters the parquet does not store as a column, expressed once here so the API and
# the existing build script cannot drift apart on what they mean.
DERIVED_FILTERS = {
    "former_lbg": "(coalesce(ever_lbg_client, false) AND NOT coalesce(is_lbg_client, false))",
    "gazette": "(gaz_matched = 1)",
    "scored": "(score_lending IS NOT NULL)",
}
SORTABLE = NUMERIC_FILTERS | {"CompanyName", "CompanyNumber", "gaz_latest_notice_date"}
GROUPABLE = TEXT_FILTERS | {"is_active", "lifecycle"}

# Columns returned by list endpoints. Deliberately short: a search result does not need
# 124 columns, and sending them would put us back where we started.
LIST_COLS = ["CompanyNumber", "CompanyName", "CompanyStatus", "sector", "segment",
             "is_active", "gaz_matched", "gaz_severity_tier",
             "score_lending", "score_insolvency", "score_growth"]

LIFECYCLE_SQL = """CASE
    WHEN trim(CompanyStatus) = 'Active' THEN 'Trading'
    WHEN trim(CompanyStatus) = 'Active - Proposal to Strike off' THEN 'Fading'
    WHEN trim(CompanyStatus) IN ('Live but Receiver Manager on at least one charge',
                                 'Voluntary Arrangement') THEN 'Distressed'
    WHEN trim(CompanyStatus) IN ('In Administration','In Administration/Administrative Receiver',
         'In Administration/Receiver Manager','ADMINISTRATION ORDER','ADMINISTRATIVE RECEIVER',
         'RECEIVERSHIP','RECEIVER MANAGER / ADMINISTRATIVE RECEIVER','Liquidation')
         THEN 'Insolvent'
    ELSE 'Unknown' END"""

# The Gazette ladder measures how far through an insolvency a company has gone, not how
# bad the outcome is. Copied from build_data.py so the API and the static build describe
# a stage the same way.
STAGE_LABEL = {1: "Winding-up petition", 2: "Formal insolvency", 3: "Creditor process",
               4: "Dividend to creditors", 5: "Final meeting"}
GAZ_FLAGS = [("active_case", "gaz_active_case_flag"), ("court", "gaz_court_involved_flag"),
             ("progressed", "gaz_stage_progressed_flag"),
             ("recurring", "gaz_recurring_distress_flag"),
             ("recent_90d", "gaz_recent_notice_90d_flag")]
MAX_NOTICES = 8

# Land Registry, from Samuel's pack. Exact company-number match, confidence 1.00 on all
# 318,068 titles, so nothing here is a name guess.
SAM = DATA / "processed" / "sam_sc" / "data"

# Sneha's competitive market analysis, run against this same July parquet. The three CSVs
# are her saved outputs and are read where they sit rather than copied in: serve.py already
# reads from outside the repo for `data/`, and duplicating a file is how two versions of the
# same number start to disagree.
MARKET = DATA.parent / "market_analysis"
MAX_PROPERTY_EVENTS = 8

# Holdings are wildly skewed: median 1 title, 90th percentile 4, 99th 29, maximum 65,556.
# The long tail is trust and corporate-services firms holding titles for clients rather
# than on their own balance sheet, so a profile reading "65,556 properties" would say
# something untrue about the business. The true count is always shown and never altered;
# above this threshold the page adds the caveat. 30 is the 99th percentile rounded up,
# which puts 680 of 60,629 companies on the right side of the line.
PROPERTY_TRUSTEE_THRESHOLD = 30

# The CCOD extract behind the pack. Its own vintage, not the company snapshot: titles run
# to 26 June 2026 and recency in the feature file is measured against 1 July 2026.
PROPERTY_ASOF = "2026-06-29"

# The second Guardian run: all 398 companies the models flagged for July 2026, same method
# and same verification rules as the 96-company stress test, so the two are comparable and
# are counted together. The file carries no per-row search date, so this is the pack's own
# harvest date.
NEWS398_PACK_DATE = "2026-08-11"
NEWS398_WINDOW_YEARS = 3

# UKRI Gateway to Research, harvested 11 Aug 2026. Two properties of this source shape how
# it may be displayed, and neither is negotiable:
#
#   1. There are NO dates. `grant_has_date` is 0 on all 10,254 rows, because dates live on
#      the project records and reading them would cost one API call per organisation, about
#      97,000 calls. Grants therefore never appear on the timeline, only as a tile and a
#      panel.
#   2. It is a NAME match, not a company-number match. `regNumber` was populated on 0 of 500
#      organisations sampled, so there is no number to join on. Confidence is 0.90 for
#      name+postcode and 0.80 for name+postcode-area, and that has to be visible wherever a
#      person reads a number that came from it.
#
# The second point also means an absence is weaker evidence here than it is for property:
# 45.3% of UKRI organisations publish no postcode at all and were dropped rather than
# guessed at, so "no grant" can mean "no match was possible", not "no funding".
GRANTS_ASOF = "2026-08-11"

# IPO trade marks. The register behind this file STOPS on 28 January 2018: the Intellectual
# Property Office published its free bulk extract on 13 February 2018 and has never updated
# it. That is a property of the source, not of our download, and it drives three rules:
#
#   1. `tm_count_12m` is 0 for every one of the 15,713 companies. It is never displayed.
#   2. `tm_days_since_latest` averages 5,596 days. It is never displayed as recency.
#   3. Every number carries the vintage, or a reader will conclude the company stopped
#      filing rather than that the data stopped.
#
# Status is also as-at-2018: a mark "Registered" then may have lapsed since, so the screen
# says "registered as at" and never "currently holds".
#
# Matching is name plus postcode AREA only, confidence 0.85 on all 15,713 rows, the weakest
# of the three packs. It is labelled everywhere a person sees a number from it.
TRADEMARK_ASOF = "2018-01-28"
MAX_TRADEMARK_EVENTS = 8

# The register's own words, grouped into what a reader needs: was it granted, and is it
# still standing as at the cut-off.
TRADEMARK_LIVE = ("Registered",)
TRADEMARK_LAPSED = ("Dead", "Expired", "Removed")

# `fetch` in that file is the searched/not-searched flag: 371 rows read 'cache' and were
# searched, 27 read 'skip' and were not. A skipped company must stay "unknown", never
# "searched and clean", which is why only 'cache' rows produce a news block at all.
NEWS398_SEARCHED = "cache"

# One row in the file reports a verified hit that its own author reviewed and rejected
# before shipping, and the CSV was never updated to match. Wiring it as-is would put a
# headline about Flying Tiger Copenhagen on the page of a London company incorporated in
# April 2025 with no filings. The exclusion is encoded here, with the reason, so it cannot
# be silently reintroduced by a future reload of the same file.
NEWS_FALSE_POSITIVES = {
    "16392251": ("Matched an article about Flying Tiger Copenhagen. \"HOLDINGS\" is "
                 "stripped as a legal suffix, leaving the single word TIGER, which appears "
                 "inside \"Flying Tiger\"; the corroborating signal was the town LONDON, "
                 "which appears in most Guardian business articles. Reviewed and rejected."),
}
NOTICE_URL_STEM = "https://www.thegazette.co.uk/id/notice/"

# Canonical company number, matching the rest of the pipeline. Verified row-for-row
# against the Python cleaner in build_data.py on 3,027,787 rows, 0 mismatches.
CLEAN_CN = """CASE
    WHEN replace(upper(trim({col})),' ','') IS NULL
      OR replace(upper(trim({col})),' ','') IN ('','NAN','NONE') THEN NULL
    WHEN regexp_matches(replace(upper(trim({col})),' ',''),'^[0-9]+$')
      THEN lpad(replace(upper(trim({col})),' ',''),
                greatest(8, CAST(length(replace(upper(trim({col})),' ','')) AS INTEGER)), '0')
    WHEN length(replace(upper(trim({col})),' ','')) <= 8
      THEN lpad(replace(upper(trim({col})),' ',''), 8, '0')
    ELSE NULL END"""

app = Flask(__name__, static_folder=None)
_con = None          # the one connection; each request gets its own cursor off it
PARQUET = str(DEFAULT_PARQUET)
BUILD_META = {}      # the meta block from data.js, so the UI keeps its existing config


class FilterError(ValueError):
    """A filter value the server does not recognise.

    Raised rather than ignored on purpose. Silently dropping an unrecognised value made
    a bad request return the WHOLE universe, which is the opposite of what the caller
    asked for and reads on screen as a filter that did nothing. An unusable request
    should fail loudly; only an ABSENT or EMPTY value means "filter off".
    """


@app.errorhandler(FilterError)
def _bad_filter(e):
    return jsonify(error="bad filter value", detail=str(e)), 400


def q(sql, params=None):
    """Run a query on a private cursor so concurrent requests do not share state."""
    cur = _con.cursor()
    try:
        return cur.execute(sql, params or []).df()
    finally:
        cur.close()


def clean_number(raw):
    """Same canonical form the rest of the pipeline uses: 8 chars, upper, zero-padded."""
    s = str(raw or "").strip().upper().replace(" ", "")
    if not s or s in ("NAN", "NONE"):
        return None
    return s.zfill(8) if len(s) <= 8 else s


_QUANTILES = {}          # filled once at startup; score thresholds are population-wide


def sql_of(text):
    """Substitute the runtime placeholders (lifecycle CASE, score thresholds)."""
    text = text.replace("__LIFECYCLE__", LIFECYCLE_SQL)
    for k, v in _QUANTILES.items():
        text = text.replace(k, repr(v))
    return text


def clause_for(key, spec, args):
    """One filter -> (sql, params) or None. Tri-state rule: 'no' means observed false,
    'notstated' means the underlying column is NULL. Absence of the parameter means the
    filter is off and nothing is excluded."""
    kind = spec["kind"]

    if kind in ("in", "in_expr"):
        vals = [v for v in args.getlist(key) if v != ""]
        if not vals:
            return None
        target = f'"{spec["col"]}"' if kind == "in" else sql_of(spec["expr"])
        want_null = "__notstated__" in vals
        vals = [v for v in vals if v != "__notstated__"]
        parts, params = [], []
        if vals:
            parts.append(f"{target} IN (" + ",".join("?" * len(vals)) + ")")
            params.extend(vals)
        if want_null:
            parts.append(f"{target} IS NULL")
        return ("(" + " OR ".join(parts) + ")", params) if parts else None

    if kind == "bool":
        v = (args.get(key) or "").lower()
        if v == "":
            return None
        if v in ("1", "true", "yes"):
            return (f"({sql_of(spec['expr'])})", [])
        if v in ("0", "false", "no"):
            return (f"(NOT ({sql_of(spec['expr'])}))", [])
        raise FilterError(f"{key}: expected yes or no, got {v!r}")

    if kind == "tri":
        v = (args.get(key) or "").lower()
        col = f'"{spec["col"]}"'
        if v == "":
            return None
        if v == "yes":
            return (f"({col} IS TRUE)", [])
        if v == "no":
            # observed false, never unknown
            return (f"({col} IS FALSE)", [])
        if v == "notstated":
            return (f"({col} IS NULL)", [])
        raise FilterError(f"{key}: expected yes, no or notstated, got {v!r}")

    if kind == "choice":
        vals = [v for v in args.getlist(key) if v]
        if not vals:
            return None
        parts = []
        for v in vals:
            if v == "__notstated__" and spec.get("nullable"):
                parts.append(f'"{spec["null_col"]}" IS NULL')
            elif v in spec["choices"]:
                parts.append(f"({sql_of(spec['choices'][v])})")
            else:
                allowed = list(spec["choices"]) + (["__notstated__"] if spec.get("nullable") else [])
                raise FilterError(f"{key}: {v!r} is not one of {allowed}")
        return ("(" + " OR ".join(parts) + ")", []) if parts else None

    if kind == "range":
        col = f'"{spec["col"]}"'
        parts, params = [], []
        for suffix, op in (("_min", ">="), ("_max", "<=")):
            raw = args.get(key + suffix)
            if raw in (None, ""):
                continue
            # Both rejections matter. A non-numeric bound used to drop the filter and
            # return everything; nan/inf parsed fine and compared false against every
            # row, returning nothing. Two kinds of bad input, two silent and opposite
            # outcomes, neither visible to the caller.
            try:
                v = float(raw)
            except ValueError:
                raise FilterError(f"{key}{suffix}: {raw!r} is not a number")
            if v != v or v in (float("inf"), float("-inf")):
                raise FilterError(f"{key}{suffix}: {raw!r} is not a finite number")
            params.append(v)
            parts.append(f"{col} {op} ?")
        return (" AND ".join(parts), params) if parts else None

    return None


def build_filter_where(args, skip=None):
    """Compose every active filter into one WHERE. `skip` omits one filter, which is how
    a facet counts its own options without excluding them."""
    clauses, params = [], []
    for key, spec in FILTERS.items():
        if key == skip:
            continue
        got = clause_for(key, spec, args)
        if got and got[0]:
            clauses.append(got[0])
            params.extend(got[1])
    # A preset is applied as one more clause, so it can be combined with the panel.
    pkey = args.get("preset")
    if pkey:
        p = next((x for x in PRESETS if x["key"] == pkey), None)
        if p is None:
            raise FilterError(f"preset: {pkey!r} is not one of {[x['key'] for x in PRESETS]}")
        clauses.append("(" + sql_of(p["where"]) + ")")
    return (" AND ".join(clauses) if clauses else "TRUE"), params


VIEWS = {"all": "TRUE",
         "gazette": "gaz_matched = 1",
         "lbg": "ever_lbg_client AND NOT is_lbg_client"}


def view_where(view):
    # An unknown view used to fall back to "all", so a typo quietly widened the result
    # from one view's population to the whole universe.
    if view not in VIEWS:
        raise FilterError(f"view: {view!r} is not one of {list(VIEWS)}")
    return VIEWS[view]


def build_where(args):
    """Turn query-string arguments into a WHERE clause plus bound parameters.

    Returns (sql_fragment, params). Unknown keys are ignored rather than interpolated.
    """
    clauses, params = [], []

    for key in TEXT_FILTERS:
        vals = args.getlist(key)
        if vals:
            clauses.append(f'"{key}" IN (' + ",".join("?" * len(vals)) + ")")
            params.extend(vals)

    for key in BOOL_FILTERS:
        if key in args:
            want = args.get(key).lower() in ("1", "true", "yes")
            clauses.append(f'coalesce("{key}", false) = ?')
            params.append(want)

    for key in NUMERIC_FILTERS:
        for prefix, op in (("min_", ">="), ("max_", "<=")):
            if prefix + key in args:
                try:
                    params.append(float(args.get(prefix + key)))
                except ValueError:
                    continue
                clauses.append(f'"{key}" {op} ?')

    for key, expr in DERIVED_FILTERS.items():
        if key in args:
            want = args.get(key).lower() in ("1", "true", "yes")
            clauses.append(expr if want else f"NOT {expr}")

    if args.get("lifecycle"):
        vals = args.getlist("lifecycle")
        clauses.append(f"({LIFECYCLE_SQL}) IN (" + ",".join("?" * len(vals)) + ")")
        params.extend(vals)

    if args.get("q"):
        # Name contains, case-insensitive. Company numbers are handled by /api/search.
        clauses.append("upper(CompanyName) LIKE ?")
        params.append(f"%{args.get('q').strip().upper()}%")

    return (" AND ".join(clauses) if clauses else "TRUE"), params


def paging(args):
    # Both are clamped at BOTH ends. Only offset was floored before, so a negative limit
    # reached DuckDB as `LIMIT -5` and returned a 500. Zero stays legal: it is a
    # meaningful "count only, no rows" request.
    try:
        limit = min(max(int(args.get("limit", DEFAULT_LIMIT)), 0), MAX_LIMIT)
    except ValueError:
        limit = DEFAULT_LIMIT
    try:
        offset = max(int(args.get("offset", 0)), 0)
    except ValueError:
        offset = 0
    return limit, offset


# Final tie-break on every ordered query. Without it, LIMIT/OFFSET over a non-unique
# ORDER BY has no total order and DuckDB's parallel scan is free to return ties in a
# different arrangement each time. Measured before this was added: five identical calls
# to the Former LBG view returned five different sets of companies, and walking six
# pages of 100 showed 526 distinct companies in 600 slots, so 74 were never displayed at
# all. CompanyNumber is unique across all 1,531,094 rows and never null, so appending it
# makes every sort a total order. It is always ASC: the tie-break only has to be stable,
# and flipping it with the primary key would make ties jump when the user changes
# direction.
TIE_BREAK = ", CompanyNumber ASC"


def order_by(args):
    col = args.get("sort")
    if col not in SORTABLE:
        return "ORDER BY CompanyNumber ASC"
    direction = "DESC" if args.get("dir", "desc").lower() == "desc" else "ASC"
    # NULLS LAST so unscored companies never head a ranked list.
    return f'ORDER BY "{col}" {direction} NULLS LAST{TIE_BREAK}'


# --------------------------------------------------------------------------------
# Record builders.
#
# These return exactly the shape build_data.py bakes into data.js, so the frontend
# renders an API result with the code it already has. The alternative, returning raw
# parquet rows, would have meant rewriting every panel.
# --------------------------------------------------------------------------------
def _num(v, default=0):
    try:
        f = float(v)
        return default if f != f else (int(f) if f == int(f) else f)   # f != f catches NaN
    except (TypeError, ValueError):
        return default


def _flag(v):
    return str(v).strip().lower() in ("1", "1.0", "true", "yes")


def _tri(v):
    """True / False / None, for the momentum columns.

    _flag() collapses NULL to False, which is right for a flag that is always
    populated and wrong for these: 213,566 companies are simply too young to have a
    12-month history, and reporting that as "did not change" would invent a fact.
    Same rule the filters already enforce in SQL.
    """
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("nan", "nat", "none", ""):
        return None
    return s in ("1", "1.0", "true", "yes")


def _txt(v):
    """Text for display, with the CSV null markers scrubbed.

    The side files are read with all_varchar=true, so a missing value arrives as the
    literal string "nan", "nat" or "none". Those are absences, not content.
    """
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "nat", "none") else s


def _cat(v):
    """Text for a field where "none" is a real category rather than a missing marker.

    gaz_severity_tier is exactly that: 27 matched companies carry the tier 'none',
    meaning their notice sits outside the distress ladder. Sending them through _txt()
    blanked the value and the row rendered as " · 2 notices" with a dangling separator.
    The stored value and every filter predicate are unchanged; only the display of an
    already-matched company is affected.
    """
    return "" if v is None else str(v).strip()


def _date(v):
    s = _txt(v)
    return s[:10] if s else ""


def list_record(r):
    """The subset the watchlist rows and search results render."""
    rec = {"number": r["CompanyNumber"], "name": _txt(r.get("CompanyName")),
           "status": _txt(r.get("CompanyStatus")), "lifecycle": r.get("lifecycle"),
           "sector": _txt(r.get("sector")), "segment": _txt(r.get("segment")),
           "gazette": None, "lender": None}
    if _num(r.get("gaz_matched")) == 1:
        stage = _num(r.get("gaz_max_distress_stage"))
        rec["gazette"] = {"notice_count": _num(r.get("gaz_notice_count_total")),
                          "count_12m": _num(r.get("gaz_notice_count_12m")),
                          "stage": stage, "stage_label": STAGE_LABEL.get(stage, "Unclassified"),
                          "severity_tier": _cat(r.get("gaz_severity_tier")),
                          "latest_date": _date(r.get("gaz_latest_notice_date"))}
    ever, now = _flag(r.get("ever_lbg_client")), _flag(r.get("is_lbg_client"))
    if ever or now:
        rec["lender"] = {"former_lbg": bool(ever and not now), "is_lbg": now,
                         "competitors": _num(r.get("n_competitor_lenders")),
                         "primary": _txt(r.get("primary_lender_group")) or None,
                         "months_since_lbg_satisfied":
                             _num(r.get("months_since_last_lbg_satisfaction"), None)}
    return rec


def full_record(cn):
    """Everything the company page shows, assembled from the parquet plus the three
    side files. Percentiles are computed against the live scored population rather
    than read from a precomputed column, so they cannot go stale."""
    df = q("SELECT * FROM read_parquet(?) WHERE CompanyNumber = ?", [PARQUET, cn])
    if df.empty:
        return None
    r = df.where(df.notna(), None).to_dict("records")[0]
    r["lifecycle"] = q(f"SELECT {LIFECYCLE_SQL} AS v FROM read_parquet(?) "
                       f"WHERE CompanyNumber = ?", [PARQUET, cn]).v[0]
    rec = list_record(r)
    rec["active"] = _flag(r.get("is_active"))

    ident = q("SELECT * FROM ident WHERE cn = ?", [cn])
    if not ident.empty:
        i = ident.iloc[0]
        rec["incorporated"] = _txt(i["IncorporationDate"])
        bits = [_txt(i["RegAddress.AddressLine1"]), _txt(i["RegAddress.PostTown"]),
                _txt(i["RegAddress.PostCode"])]
    else:
        rec["incorporated"] = ""
        bits = [_txt(r.get("RegAddress.PostCode"))]       # July fallback, one snapshot only
    rec["address"] = ", ".join(b for b in bits if b)

    if rec["gazette"]:
        rec["gazette"].update({
            "first_date": _date(r.get("gaz_first_notice_date")),
            "days_since": _num(r.get("gaz_days_since_latest_notice"), None),
            "flags": [name for name, col in GAZ_FLAGS if _flag(r.get(col))]})
        nt = q("SELECT notice_date, notice_type, notice_url FROM notices "
               "WHERE cn = ? ORDER BY notice_date", [cn]).tail(MAX_NOTICES)
        rec["timeline"] = [{"date": _date(x.notice_date), "detail": _txt(x.notice_type),
                            "source": "gazette",
                            "id": _txt(x.notice_url).rsplit("/", 1)[-1] or None}
                           for x in nt.itertuples()]
    else:
        rec["timeline"] = []

    # Land Registry. The summary comes from the feature row; the tenure split and the
    # timeline entries are read from the titles themselves.
    pf = q("SELECT * FROM prop_f WHERE cn = ?", [cn])
    rec["property"] = None
    if not pf.empty:
        p = pf.iloc[0]
        total = _num(p.get("prop_count_total"))
        # Counted in SQL rather than pandas: one company holds 65,556 titles and there is
        # no reason to materialise them just to count two prefixes.
        split = q("""SELECT count(*) FILTER (WHERE detail LIKE 'Freehold%') AS freehold,
                            count(*) FILTER (WHERE detail LIKE 'Leasehold%') AS leasehold
                     FROM prop_e WHERE cn = ?""", [cn])
        rec["property"] = {
            "titles": total,
            "freehold": int(split.freehold[0]), "leasehold": int(split.leasehold[0]),
            "first_date": _date(p.get("prop_first_date")),
            "latest_date": _date(p.get("prop_latest_date")),
            "days_since": _num(p.get("prop_days_since_latest"), None),
            "count_12m": _num(p.get("prop_count_12m")),
            # Price paid is on about a sixth of titles nationally, so the count travels
            # with the totals and the screen never quotes a total on its own.
            "value_total": _num(p.get("prop_value_total"), None),
            "value_max": _num(p.get("prop_value_max"), None),
            "value_count": _num(p.get("prop_value_count")),
            "match_method": _txt(p.get("prop_match_method")),
            "confidence": _num(p.get("prop_max_confidence"), None),
            "large_holder": total >= PROPERTY_TRUSTEE_THRESHOLD,
            "threshold": PROPERTY_TRUSTEE_THRESHOLD,
        }
        pe = q("""SELECT event_date, detail, value, postcode, title_number FROM prop_e
                  WHERE cn = ? ORDER BY event_date DESC LIMIT ?""",
               [cn, MAX_PROPERTY_EVENTS])
        rec["property"]["shown"] = len(pe)
        rec["timeline"] += [{"date": _date(x.event_date), "detail": _txt(x.detail),
                             "source": "property", "id": None,
                             "title_number": _txt(x.title_number),
                             "value": _num(x.value, None),
                             "postcode": _txt(x.postcode)} for x in pe.itertuples()]

    # IPO trade marks. Dated, so they belong on the timeline, but every date here is 2018
    # or earlier and the panel has to say why.
    tf = q("SELECT * FROM tm_f WHERE cn = ?", [cn])
    rec["trademarks"] = None
    if not tf.empty:
        t = tf.iloc[0]
        # Counted in SQL: one company carries 4,174 marks.
        st = q(f"""SELECT count(*) AS total,
                     count(*) FILTER (WHERE status IN ({','.join('?' * len(TRADEMARK_LIVE))}))
                       AS registered,
                     count(*) FILTER (WHERE status IN ({','.join('?' * len(TRADEMARK_LAPSED))}))
                       AS lapsed
                   FROM tm_e WHERE cn = ?""",
               list(TRADEMARK_LIVE) + list(TRADEMARK_LAPSED) + [cn])
        rec["trademarks"] = {
            "total": _num(t.get("tm_count_total")),
            "registered": int(st.registered[0]), "lapsed": int(st.lapsed[0]),
            "other": int(st.total[0]) - int(st.registered[0]) - int(st.lapsed[0]),
            "first_date": _date(t.get("tm_first_date")),
            "latest_date": _date(t.get("tm_latest_date")),
            "match_method": _txt(t.get("tm_match_method")),
            "confidence": _num(t.get("tm_max_confidence"), None),
            "asof": TRADEMARK_ASOF,
            # tm_count_12m and tm_days_since_latest are deliberately absent: the first is
            # zero for every company and the second averages fifteen years, so both would
            # describe the register's age rather than the company's behaviour.
        }
        te = q("""SELECT event_date, detail, url, trade_mark, status, registered_date
                  FROM tm_e WHERE cn = ? ORDER BY event_date DESC LIMIT ?""",
               [cn, MAX_TRADEMARK_EVENTS])
        rec["trademarks"]["shown"] = len(te)
        rec["timeline"] += [{"date": _date(x.event_date), "detail": _txt(x.detail),
                             "source": "trademark", "id": None,
                             "url": _txt(x.url) or None,
                             "mark": _txt(x.trade_mark),
                             "status": _txt(x.status)} for x in te.itertuples()]

    # UKRI grants. Deliberately built after the timeline is assembled and deliberately not
    # added to it: this source carries no dates at all, so it can be a tile and a panel and
    # nothing else.
    gr = q("SELECT * FROM grants WHERE cn = ?", [cn])
    rec["grants"] = None
    if not gr.empty:
        g = gr.iloc[0]
        rec["grants"] = {
            "projects": _num(g.get("grant_n_projects")),
            "organisations": _num(g.get("grant_n_organisations")),
            "match_method": _txt(g.get("grant_match_method")),
            "confidence": _num(g.get("grant_max_confidence"), None),
            "min_confidence": _num(g.get("grant_min_confidence"), None),
            "asof": GRANTS_ASOF,
        }

    # One column, so the sources interleave by date rather than sitting in blocks.
    rec["timeline"].sort(key=lambda e: e["date"] or "")

    # Scores exist for Active companies only; the reason is rendered, never a zero.
    rec["scores"] = None
    if rec["active"] and r.get("score_lending") is not None:
        # All four percentiles in ONE scan of the scored population. Written as four
        # correlated subqueries first, which cost eight scans and 900ms per company.
        pct = q(f"""SELECT count(*) AS n, {', '.join(
            f'count(*) FILTER (WHERE "{c}" > ?) AS "{c}"' for c in SCORE_COLS)}
            FROM read_parquet(?) WHERE is_active""",
               [float(r[c]) for c in SCORE_COLS] + [PARQUET])
        n = int(pct.n[0]) or 1
        rec["scores"] = {c.replace("score_", ""): {
            "score": round(float(r[c]), 6),
            "pct": round(100.0 * int(pct[c][0]) / n, 2)} for c in SCORE_COLS}

    news = q("SELECT * FROM news WHERE cn = ?", [cn])
    if not news.empty:
        n = news.iloc[0]
        rec["news"] = {"source": _txt(n["news_source"]), "searched": _txt(n["news_search_date"]),
                       "window_years": _num(n["news_window_years"]),
                       "verified": _num(n["news_verified_count"]),
                       "raw_hits": _num(n["news_raw_hits"]),
                       "status": _txt(n["news_status"])}
        rej = [t.strip() for t in _txt(n["news_rejected_titles"]).split("|") if t.strip()]
        urls = [u.strip() for u in _txt(n["news_rejected_urls"]).split("|") if u.strip()]
        if rej:
            rec["news"]["rejected"] = [{"title": t, "url": urls[i] if i < len(urls) else None}
                                       for i, t in enumerate(rej)][:3]
    else:
        rec["news"] = None
        # The second run. Only reached when the 96-company file has no row for this
        # company, and the two samples do not overlap at all, so nothing is overwritten.
        n398 = q("SELECT * FROM news398 WHERE cn = ?", [cn])
        if not n398.empty and _txt(n398.iloc[0]["fetch"]) == NEWS398_SEARCHED:
            s = n398.iloc[0]
            verified, raw = _num(s["n_verified"]), _num(s["raw_hits"])
            excluded = NEWS_FALSE_POSITIVES.get(cn)
            if excluded:
                # raw_hits already counts the article; only the verification is reversed.
                verified = 0
            rec["news"] = {"source": "guardian", "searched": NEWS398_PACK_DATE,
                           "window_years": NEWS398_WINDOW_YEARS,
                           "verified": verified, "raw_hits": raw,
                           "status": "searched",
                           # This run shipped counts only, no article titles or links, so
                           # there is no rejected list to show and the screen must not
                           # offer one.
                           "articles_available": False}
            if excluded:
                rec["news"]["excluded_note"] = excluded

    if _num(r.get("n_charges_outstanding")) > 0 or rec["lender"]:
        rec.setdefault("lender", {}) or rec.__setitem__("lender", rec["lender"] or {})
        rec["lender"].update({
            "ever_lbg": _flag(r.get("ever_lbg_client")),
            "outstanding": _num(r.get("n_charges_outstanding")),
            "lbg_outstanding": _num(r.get("n_lbg_charges_outstanding")),
            "lenders": _num(r.get("n_distinct_lenders")),
            "competitor_6m": _flag(r.get("competitor_charge_created_6m")),
            "competitor_12m": _flag(r.get("competitor_entered_12m")),
            "lbg_satisfied_6m": _flag(r.get("lbg_charge_satisfied_6m")),
            # When the relationship STARTED, alongside when it ended. Without this the
            # page cannot separate a live LBG client from a decades-old register entry:
            # of current clients, 3,588 hold a charge created within 5 years and 9,211
            # hold one created over 20 years ago.
            "months_since_lbg_created":
                _num(r.get("months_since_last_lbg_charge_created"), None)})

    if _num(r.get("Mortgages.NumMortCharges")) > 0:
        rec["borrowing"] = {"total": _num(r.get("Mortgages.NumMortCharges")),
                            "outstanding": _num(r.get("Mortgages.NumMortOutstanding")),
                            "satisfied": _num(r.get("Mortgages.NumMortSatisfied")),
                            "debt_ratio": _num(r.get("debt_ratio"), None),
                            "d_3m": _num(r.get("d_charges_3m"), None),
                            "new_12m": _num(r.get("new_charge_events_12m")),
                            "months_since_new": _num(r.get("months_since_last_new_charge"), None)}
    else:
        rec["borrowing"] = None

    rec["filing"] = {k: v for k, v in {
        "overdue": _flag(r.get("accounts_overdue")),
        "overdue_streak": _num(r.get("accounts_overdue_streak_months")),
        "stale_streak": _num(r.get("accounts_stale_streak_months")),
        "confstmt_late": _flag(r.get("confstmt_late")),
        "days_to_due": _num(r.get("days_to_next_accounts_due"), None),
        "months_since_accounts": _num(r.get("months_since_last_accounts_filing"), None),
        "months_since_confstmt": _num(r.get("months_since_last_confstmt"), None),
    }.items() if v is not None and v is not False}

    # The company's own SIC line. Present on all 1,531,094 rows and filterable, but the
    # profile had no place that stated what the company actually does.
    rec["sic"] = _txt(r.get("SICCode.SicText_1"))
    rec["age_years"] = _num(r.get("company_age_years"), None)

    # What moved in the last 12 months. Tri-state throughout: None means no history,
    # which for 213,566 companies is the true answer and is not the same as "no".
    rec["momentum"] = {
        "up": _tri(r.get("segment_upgraded_12m")),
        "down": _tri(r.get("segment_downgraded_12m")),
        "months_since_segment_change": _num(r.get("months_since_segment_change"), None),
        "relocated": _tri(r.get("postcode_changed_12m")),
        "sic_changed": _tri(r.get("sic_changed_12m")),
        "name_changed": _tri(r.get("name_changed_12m")),
        "status_changed": _tri(r.get("status_changed")),
        "months_in_status": _num(r.get("months_in_current_status"), None),
        "ever_distressed": _tri(r.get("ever_distressed_before")),
    }

    rec["contracts"] = ({"ever": True, "won_12m": _num(r.get("contracts_won_12m")),
                         "value_12m": _num(r.get("total_value_won_12m")),
                         "months_since": _num(r.get("months_since_last_award"), None),
                         "first_in_12m": _flag(r.get("first_award_in_12m"))}
                        if _flag(r.get("ever_won_contract")) else None)
    return rec


SCORE_COLS = ["score_lending", "score_insolvency", "score_voluntary_exit", "score_growth"]


# --------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------
@app.route("/api/health")
def health():
    n = q(f"SELECT count(*) AS n FROM read_parquet(?)", [PARQUET]).n[0]
    return jsonify(status="ok", parquet=PARQUET, universe=int(n))


@app.route("/api/meta")
def meta():
    """Universe size, live facet counts, and the config block the UI already reads.

    The config half (score models, source list, news counts) is lifted verbatim from
    data.js at startup rather than restated here, so there is one definition of those
    values and the two cannot drift. The counts below are recomputed live against the
    parquet, which is why they describe the whole universe rather than the old store.
    """
    n = int(q("SELECT count(*) AS n FROM read_parquet(?)", [PARQUET]).n[0])
    out = dict(BUILD_META)
    out.update({"universe": n, "parquet": Path(PARQUET).name, "facets": {}})

    counts = q(f"""SELECT
        count(*) FILTER (WHERE gaz_matched = 1) AS gazette,
        count(*) FILTER (WHERE {DERIVED_FILTERS['former_lbg']}) AS former_lbg,
        count(*) FILTER (WHERE is_active) AS scored
        FROM read_parquet(?)""", [PARQUET])
    out["companies_with_signal"] = int(counts.gazette[0])
    out["former_lbg"] = out["former_lbg_in_store"] = int(counts.former_lbg[0])
    out["scored_companies"] = int(counts.scored[0])
    out["unscored_companies"] = n - int(counts.scored[0])
    # Gazette companies by lifecycle, for the landing filter chips.
    fl = q(f"SELECT {LIFECYCLE_SQL} AS v, count(*) AS n FROM read_parquet(?) "
           f"WHERE gaz_matched = 1 GROUP BY 1", [PARQUET])
    out["flagged_by_lifecycle"] = {r.v: int(r.n) for r in fl.itertuples()}
    out["notice_url_stem"] = NOTICE_URL_STEM
    # Which sources are attached is a fact about this process, not about whichever
    # data.js happens to be on disk, so it is answered from what load_aux() actually
    # read. Hiring is gone entirely: Adzuna returned 401 on every endpoint and no data
    # was ever collected, so there is nothing to declare as pending.
    out["sources_live"] = ["gazette", "news", "contracts", "property", "grants", "trademark"]
    out["sources_pending"] = []
    tstat = q("SELECT count(*) AS n FROM tm_f")
    out["trademark"] = {"companies": int(tstat.n[0]),
                        "marks": int(q("SELECT count(*) AS n FROM tm_e").n[0]),
                        "asof": TRADEMARK_ASOF}
    gstat = q("SELECT count(*) AS n, sum(CAST(grant_n_projects AS INT)) AS p, "
              "count(*) FILTER (WHERE CAST(grant_n_projects AS INT) = 0) AS z FROM grants")
    out["grants"] = {"companies": int(gstat.n[0]), "projects": int(gstat.p[0]),
                     "no_projects": int(gstat.z[0]), "asof": GRANTS_ASOF}
    out["property"] = {"companies": int(q("SELECT count(*) AS n FROM prop_f").n[0]),
                       "titles": int(q("SELECT count(*) AS n FROM prop_e").n[0]),
                       "asof": PROPERTY_ASOF,
                       "trustee_threshold": PROPERTY_TRUSTEE_THRESHOLD}

    # News now spans two runs. The numbers on the screen have to describe both, and the
    # only one that matters most is `not_searched`: it is unknown, not clean.
    n96 = q("SELECT count(*) AS n, sum(CAST(news_verified_count AS INT)) AS v, "
            "count(*) FILTER (WHERE CAST(news_raw_hits AS INT) > 0) AS r FROM news")
    n398 = q("SELECT count(*) AS n, sum(CAST(n_verified AS INT)) AS v, "
             "count(*) FILTER (WHERE CAST(raw_hits AS INT) > 0) AS r "
             'FROM news398 WHERE "fetch" = ?', [NEWS398_SEARCHED])
    skipped = int(q('SELECT count(*) AS n FROM news398 WHERE "fetch" <> ?',
                    [NEWS398_SEARCHED]).n[0])
    searched = int(n96.n[0]) + int(n398.n[0])
    # The one verified row in the 398 was reviewed and rejected, see NEWS_FALSE_POSITIVES,
    # so it is removed from the headline the same way it is removed from the company page.
    verified = int(n96.v[0] or 0) + int(n398.v[0] or 0) - len(NEWS_FALSE_POSITIVES)
    out["news"] = {**BUILD_META.get("news", {}),
                   "source": "guardian", "window_years": NEWS398_WINDOW_YEARS,
                   "searched": searched, "not_searched": n - searched,
                   "with_verified_coverage": max(verified, 0),
                   "with_raw_hits_rejected": int(n96.r[0]) + int(n398.r[0]),
                   "runs": [{"label": "stress-test sample", "n": int(n96.n[0]),
                             "date": BUILD_META.get("news", {}).get("search_date")},
                            {"label": "model shortlist", "n": int(n398.n[0]),
                             "date": NEWS398_PACK_DATE, "not_searchable": skipped}]}
    for col in ("sector", "segment", "CompanyStatus", "size_tier"):
        df = q(f'SELECT "{col}" AS v, count(*) AS n FROM read_parquet(?) '
               f'GROUP BY 1 ORDER BY 2 DESC', [PARQUET])
        out["facets"][col] = [{"value": None if r.v is None else str(r.v), "count": int(r.n)}
                              for r in df.itertuples()]
    df = q(f"SELECT {LIFECYCLE_SQL} AS v, count(*) AS n FROM read_parquet(?) "
           f"GROUP BY 1 ORDER BY 2 DESC", [PARQUET])
    out["facets"]["lifecycle"] = [{"value": r.v, "count": int(r.n)} for r in df.itertuples()]
    return jsonify(out)


@app.route("/api/company/<number>")
def company(number):
    """One company, in the shape the dashboard already renders."""
    cn = clean_number(number)
    if not cn:
        return jsonify(error="bad company number"), 400
    rec = full_record(cn)
    if rec is None:
        return jsonify(error="not found", CompanyNumber=cn), 404
    return jsonify(rec)


@app.route("/api/company/<number>/raw")
def company_raw(number):
    """Every parquet column untransformed, for debugging and ad-hoc inspection."""
    cn = clean_number(number)
    df = q("SELECT * FROM read_parquet(?) WHERE CompanyNumber = ?", [PARQUET, cn])
    if df.empty:
        return jsonify(error="not found", CompanyNumber=cn), 404
    rec = df.where(df.notna(), None).to_dict("records")[0]
    return jsonify({k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in rec.items()})


LIST_SELECT = """CompanyNumber, CompanyName, CompanyStatus, sector, segment, is_active,
    gaz_matched, gaz_severity_tier, gaz_notice_count_total, gaz_notice_count_12m,
    gaz_max_distress_stage, gaz_latest_notice_date, ever_lbg_client, is_lbg_client,
    n_competitor_lenders, primary_lender_group, months_since_last_lbg_satisfaction"""


@app.route("/api/search")
def search():
    """Company number if it looks like one, otherwise a name contains-match.

    Searches all 1,531,094 companies, not the legacy store.
    """
    raw = (request.args.get("q") or "").strip()
    if len(raw) < 2:
        return jsonify(query=raw, count=0, rows=[])
    limit, _ = paging(request.args)

    if raw.replace(" ", "").isalnum() and any(ch.isdigit() for ch in raw) and len(raw) <= 8:
        df = q(f"SELECT {LIST_SELECT}, {LIFECYCLE_SQL} AS lifecycle FROM read_parquet(?) "
               f"WHERE CompanyNumber = ?", [PARQUET, clean_number(raw)])
        if not df.empty:
            return jsonify(query=raw, matched_on="company_number", count=len(df),
                           rows=[list_record(r) for r in records(df)])
    df = q(f"SELECT {LIST_SELECT}, {LIFECYCLE_SQL} AS lifecycle FROM read_parquet(?) "
           f"WHERE upper(CompanyName) LIKE ? "
           f"ORDER BY length(CompanyName), CompanyName{TIE_BREAK} "
           f"LIMIT ?", [PARQUET, f"%{raw.upper()}%", limit])
    return jsonify(query=raw, matched_on="name", count=len(df),
                   rows=[list_record(r) for r in records(df)])


@app.route("/api/watchlist")
def watchlist():
    """The two ranked views the landing page shows, over the whole universe.

    gazette: furthest through the insolvency ladder, most recent first.
    lbg:     former LBG clients, most recently lapsed first, because a charge satisfied
             two months ago is a warmer call than one satisfied nine years ago.
    """
    view = request.args.get("view", "gazette")
    limit, offset = paging(request.args)
    lifecycles = request.args.getlist("lifecycle")

    clauses, params = [], []
    if view == "lbg":
        clauses.append(DERIVED_FILTERS["former_lbg"])
        order = "ORDER BY months_since_last_lbg_satisfaction ASC NULLS LAST" + TIE_BREAK
    else:
        clauses.append(DERIVED_FILTERS["gazette"])
        order = ("ORDER BY gaz_max_distress_stage DESC NULLS LAST, "
                 "gaz_latest_notice_date DESC NULLS LAST" + TIE_BREAK)
    if lifecycles:
        clauses.append(f"({LIFECYCLE_SQL}) IN (" + ",".join("?" * len(lifecycles)) + ")")
        params.extend(lifecycles)
    where = " AND ".join(clauses)

    total = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {where}",
                  [PARQUET] + params).n[0])
    df = q(f"SELECT {LIST_SELECT}, {LIFECYCLE_SQL} AS lifecycle FROM read_parquet(?) "
           f"WHERE {where} {order} LIMIT ? OFFSET ?",
           [PARQUET] + params + [limit, offset])
    return jsonify(view=view, total=total, returned=len(df), offset=offset,
                   rows=[list_record(r) for r in records(df)])


def records(df):
    return df.where(df.notna(), None).to_dict("records")


# Facets counted eagerly. Region (175) and Industry (727) are excluded: too many options
# to count on every keystroke, and both are search fields in the UI rather than lists.
# Display names for `choice` options. DISPLAY ONLY: the values, predicates and counts are
# untouched, and every filter still resolves through the same `choices` SQL as before.
# Without this the options render as their raw keys ("none", "top10", "recent_365"), which
# was tolerable while they were only dropdown entries but is not now that a preset states
# its conditions in these words. The Gazette wording is taken from FILTER_SPEC section 4.2.
CHOICE_LABELS = {
    "gazette": {"none": "No notice", "any": "Any notice",
                "formal_insolvency": "Severity: formal insolvency",
                "recent_365": "Notice in last 365 days",
                "active_case": "Active insolvency case",
                "court": "Court involved", "petition": "Winding-up petition",
                "recent_90": "Notice in last 90 days", "terminal": "Severity: terminal",
                "early_warning": "Severity: early warning"},
    "repayment": {"fully_repaid": "Fully repaid", "partial": "Partly repaid",
                  "all_outstanding": "All outstanding"},
    "lbg": {"current": "Current client", "former": "Former client",
            "never": "Never a client"},
    "size_move": {"up": "Moved up a tier", "down": "Moved down a tier",
                  "none": "No tier change"},
    "lending": {"top1": "Top 1%", "top10": "Top 10%"},
    "growth": {"top1": "Top 1%", "top10": "Top 10%"},
    "risk": {"top1": "Top 1%", "top10": "Top 10%"},
}


EAGER_FACETS = ["segment", "lifecycle", "sector", "repayment", "lbg", "main_lender",
                "size_move", "lending", "growth", "risk", "gazette",
                "ever_borrowed", "new_charge_12m", "competitor", "competitor_6m",
                "competitor_lbg", "overdue", "overdue_6m", "confstmt_late",
                "no_filing_24m", "relocated", "sic_changed"]


@app.route("/api/filters")
def filters_meta():
    """The panel renders itself from this: groups, labels, and each option's count.

    Counts are computed with every OTHER active filter applied but not the facet's own,
    which is what makes a multi-select behave sensibly. The spec requires an option to
    show its live population, so the user can see a choice is empty before making it.
    """
    view = request.args.get("view", "all")
    base = view_where(view)
    out, params_cache = [], {}

    for key in EAGER_FACETS:
        spec = FILTERS[key]
        where, params = build_filter_where(request.args, skip=key)
        scope = f"({base}) AND ({where})"
        options = []

        if spec["kind"] in ("in", "in_expr"):
            target = f'"{spec["col"]}"' if spec["kind"] == "in" else sql_of(spec["expr"])
            df = q(f"SELECT {target} AS v, count(*) AS n FROM read_parquet(?) "
                   f"WHERE {scope} GROUP BY 1 ORDER BY 2 DESC LIMIT 40", [PARQUET] + params)
            for r in df.itertuples():
                options.append({"value": "__notstated__" if r.v is None else str(r.v),
                                "label": "Not stated" if r.v is None else str(r.v),
                                "count": int(r.n)})
        elif spec["kind"] == "choice":
            for cv, expr in spec["choices"].items():
                n = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {scope} "
                          f"AND ({sql_of(expr)})", [PARQUET] + params).n[0])
                options.append({"value": cv,
                                "label": CHOICE_LABELS.get(key, {}).get(cv, cv.replace("_", " ")),
                                "count": n})
            if spec.get("nullable"):
                n = int(q(f'SELECT count(*) AS n FROM read_parquet(?) WHERE {scope} '
                          f'AND "{spec["null_col"]}" IS NULL', [PARQUET] + params).n[0])
                options.append({"value": "__notstated__", "label": "Not stated", "count": n})
        elif spec["kind"] in ("bool", "tri"):
            expr = sql_of(spec["expr"]) if spec["kind"] == "bool" else f'"{spec["col"]}" IS TRUE'
            neg = f"NOT ({expr})" if spec["kind"] == "bool" else f'"{spec["col"]}" IS FALSE'
            yes = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {scope} AND ({expr})",
                        [PARQUET] + params).n[0])
            no = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {scope} AND ({neg})",
                       [PARQUET] + params).n[0])
            options = [{"value": "yes", "label": "Yes", "count": yes},
                       {"value": "no", "label": "No", "count": no}]
            if spec["kind"] == "tri":
                ns = int(q(f'SELECT count(*) AS n FROM read_parquet(?) WHERE {scope} '
                           f'AND "{spec["col"]}" IS NULL', [PARQUET] + params).n[0])
                options.append({"value": "notstated", "label": "Not stated", "count": ns})

        out.append({"key": key, "group": spec["group"], "label": spec["label"],
                    "kind": spec["kind"], "options": options})

    # Range filters carry no option list, only bounds.
    for key in ("age", "outstanding", "lenders"):
        spec = FILTERS[key]
        out.append({"key": key, "group": spec["group"], "label": spec["label"],
                    "kind": "range", "options": []})
    # Search-only facets.
    for key in ("region", "industry"):
        spec = FILTERS[key]
        out.append({"key": key, "group": spec["group"], "label": spec["label"],
                    "kind": "search", "options": []})

    return jsonify(view=view, groups=["Core", "Borrowing", "Lender", "Filing",
                                      "Momentum", "Signals"], filters=out)


@app.route("/api/options")
def options():
    """Values for the two search-only facets, filtered by what the user has typed."""
    key = request.args.get("key")
    if key not in ("region", "industry"):
        return jsonify(error="unknown option list"), 400
    spec = FILTERS[key]
    target = f'"{spec["col"]}"' if spec["kind"] == "in" else sql_of(spec["expr"])
    term = (request.args.get("q") or "").strip().upper()
    where, params = build_filter_where(request.args, skip=key)
    scope = f"({view_where(request.args.get('view','all'))}) AND ({where})"
    if term:
        scope += f" AND upper(CAST({target} AS VARCHAR)) LIKE ?"
        params = params + [f"%{term}%"]
    df = q(f"SELECT {target} AS v, count(*) AS n FROM read_parquet(?) WHERE {scope} "
           f"AND {target} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 30",
           [PARQUET] + params)
    return jsonify(key=key, options=[{"value": str(r.v), "label": str(r.v), "count": int(r.n)}
                                     for r in df.itertuples()])


@app.route("/api/presets")
def presets():
    """Approved presets with their verified populations, recomputed live.

    `filters` is the preset restated in the panel's vocabulary so the UI can load it into
    the controls; `adjustable` says whether that restatement is complete. The count is
    always computed from `where`, the definition, never from the mapping.
    """
    out = []
    for p in PRESETS:
        n = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {sql_of(p['where'])}",
                  [PARQUET]).n[0])
        out.append({"key": p["key"], "label": p["label"], "count": n,
                    "expected": p["pop"], "note": p["note"],
                    "filters": p.get("filters"),
                    "adjustable": bool(p.get("filters")),
                    "not_adjustable": p.get("not_adjustable"),
                    "conditions": p.get("conditions")})
    return jsonify(presets=out)


_MARKET_CACHE = {}


@app.route("/api/market")
def market():
    """Sneha's competitive market analysis, served for the Analytics page.

    Two rules govern this endpoint.

    1. It does not re-analyse anything. The three figures she saved to CSV are read from
       those CSVs; the other eight are recomputed with HER expressions, transcribed from
       the notebook, so the page shows the same measurement rather than a new one. Every
       value was checked against the notebook's printed output before this was written:
       league table, HHI 0.133, top-4 65.6%, 73.3% sole-banked, 11,733 clients, 14,416
       lapsed splitting 5,860 / 8,556, median age 6.3, and the sector table all reproduce.

    2. It is static for a given parquet, so it is computed once and cached. The page is a
       report on a fixed month, not a live query surface.
    """
    if _MARKET_CACHE:
        return jsonify(_MARKET_CACHE)

    def csv(name):
        return q(f"SELECT * FROM read_csv('{(MARKET / name).as_posix()}', "
                 f"all_varchar=true, ignore_errors=true)")

    out = {"asof": "2026-07", "universe": int(q("SELECT count(*) AS n FROM read_parquet(?)",
                                                [PARQUET]).n[0])}

    # -- The market at a glance (cells 5, 6, 7) ---------------------------------------
    # value_counts() drops nulls, so both of these exclude unclassified companies, and
    # cell 6 uses size_tier rather than segment. Kept exactly as she plotted them.
    sec = q('SELECT sector AS v, count(*) AS n FROM read_parquet(?) '
            'WHERE sector IS NOT NULL GROUP BY 1 ORDER BY 2 DESC', [PARQUET])
    siz = q('SELECT size_tier AS v, count(*) AS n FROM read_parquet(?) '
            'WHERE size_tier IS NOT NULL GROUP BY 1 ORDER BY 2 DESC', [PARQUET])
    # hist(age.clip(upper=40), bins=40): one-year bins, everything past 40 in the last one.
    age = q("SELECT least(floor(company_age_years), 40) AS bin, count(*) AS n "
            "FROM read_parquet(?) WHERE company_age_years IS NOT NULL "
            "GROUP BY 1 ORDER BY 1", [PARQUET])
    med = float(q("SELECT median(company_age_years) AS m FROM read_parquet(?)", [PARQUET]).m[0])
    out["glance"] = {
        "sector": [{"value": r.v, "count": int(r.n)} for r in sec.itertuples()],
        "size":   [{"value": r.v, "count": int(r.n)} for r in siz.itertuples()],
        "age":    {"bins": [{"x": int(r.bin), "n": int(r.n)} for r in age.itertuples()],
                   "median": round(med, 1)},
    }

    # -- 1. Who lends (cell 9, from her CSV) + 3. concentration (cell 13) --------------
    lg = csv("mi_league_2026-07.csv")
    league = [{"lender": _txt(r.primary_lender_group), "count": _num(r.count)}
              for r in lg.itertuples()]
    total_named = sum(x["count"] for x in league)
    for x in league:
        x["pct"] = round(100.0 * x["count"] / total_named, 1)
    rank = next((i + 1 for i, x in enumerate(league) if x["lender"] == "lbg"), None)
    cum, run = [], 0.0
    for i, x in enumerate(league, start=1):
        run += x["pct"]
        cum.append({"n": i, "pct": round(run, 1)})
    out["league"] = {"rows": league, "identified": total_named, "lbg_rank": rank}
    out["concentration"] = {
        "top4_pct": round(sum(x["pct"] for x in league[:4]), 1),
        # Squared shares on a 0-1 scale: 0 is perfect competition, 1 a monopoly.
        "hhi": round(sum((x["pct"] / 100) ** 2 for x in league), 3),
        "cumulative": cum,
    }

    # -- 2. Each bank's strength by sector (cell 11) -----------------------------------
    # crosstab(lender, sector), top 8 lenders by total, each cell as a % of its SECTOR
    # column, so the columns are what add to ~100 and the rows do not.
    hm = q("""
        WITH t AS (SELECT primary_lender_group g, sector s, count(*) n FROM read_parquet(?)
                   WHERE primary_lender_group IS NOT NULL AND sector IS NOT NULL GROUP BY 1,2),
             tot AS (SELECT s, sum(n) sn FROM t GROUP BY 1),
             top8 AS (SELECT g FROM t GROUP BY 1 ORDER BY sum(n) DESC LIMIT 8)
        SELECT t.g, t.s, round(100.0 * t.n / tot.sn, 1) AS pct
        FROM t JOIN tot USING(s) WHERE t.g IN (SELECT g FROM top8)""", [PARQUET])
    lenders = [x["lender"] for x in league if x["lender"] in set(hm.g)][:8]
    sectors = [r.v for r in sec.itertuples()]
    grid = {(r.g, r.s): float(r.pct) for r in hm.itertuples()}
    out["heatmap"] = {
        "lenders": lenders, "sectors": sectors,
        "cells": [[grid.get((g, s), 0.0) for s in sectors] for g in lenders],
    }

    # -- 4, 5, 6. Our own book (cells 15, 17, 19) --------------------------------------
    bk = q("""SELECT count(*) AS clients,
                count(*) FILTER (WHERE lbg_share_of_outstanding >= 0.999) AS sole,
                count(*) FILTER (WHERE lbg_share_of_outstanding IS NOT NULL) AS with_share,
                count(*) FILTER (WHERE n_competitor_lenders > 0) AS with_rival,
                count(*) FILTER (WHERE competitor_entered_12m) AS arrived_12m,
                count(*) FILTER (WHERE competitor_charge_created_6m) AS new_loan_6m
              FROM read_parquet(?) WHERE is_lbg_client""", [PARQUET])
    clients = int(bk.clients[0])
    # hist(share*100, bins=20): five-point bands.
    wal = q("""SELECT least(floor(lbg_share_of_outstanding * 100 / 5), 19) AS bin, count(*) AS n
               FROM read_parquet(?) WHERE is_lbg_client AND lbg_share_of_outstanding IS NOT NULL
               GROUP BY 1 ORDER BY 1""", [PARQUET])
    con = q("""SELECT least(n_competitor_lenders, 5) AS rivals, count(*) AS n
               FROM read_parquet(?) WHERE is_lbg_client GROUP BY 1 ORDER BY 1""", [PARQUET])
    out["book"] = {
        "clients": clients,
        "sole_pct": round(100.0 * int(bk.sole[0]) / int(bk.with_share[0]), 1),
        "wallet": [{"x": int(r.bin) * 5, "n": int(r.n)} for r in wal.itertuples()],
        "contested": [{"rivals": int(r.rivals), "n": int(r.n),
                       "pct": round(100.0 * int(r.n) / clients, 1)} for r in con.itertuples()],
        "pressure": [
            {"label": "Shares with a rival", "n": int(bk.with_rival[0])},
            {"label": "Rival arrived in 12m", "n": int(bk.arrived_12m[0])},
            {"label": "Rival lent in 6m", "n": int(bk.new_loan_6m[0])},
        ],
    }

    # -- 7. Where lapsed clients went (cell 21, from her CSV) --------------------------
    lp = csv("mi_lapsed_destinations_2026-07.csv")
    lapsed = q("""SELECT count(*) AS total,
                    count(*) FILTER (WHERE primary_lender_group IS NOT NULL) AS elsewhere,
                    count(*) FILTER (WHERE primary_lender_group IS NULL) AS stopped
                  FROM read_parquet(?)
                  WHERE ever_lbg_client AND NOT is_lbg_client""", [PARQUET])
    elsewhere = int(lapsed.elsewhere[0])
    out["lapsed"] = {
        "total": int(lapsed.total[0]), "elsewhere": elsewhere,
        "stopped": int(lapsed.stopped[0]),
        # Her chart is a % of those who now borrow elsewhere, not of all lapsed clients.
        "destinations": [{"lender": _txt(r.primary_lender_group), "count": _num(r.count),
                          "pct": round(100.0 * _num(r.count) / elsewhere, 1)}
                         for r in lp.itertuples()],
    }

    # -- 8. Which sectors borrow, and where we stand (cell 23, from her CSV) -----------
    sb = csv("mi_sector_borrowing_2026-07.csv")
    out["sectors"] = [{"sector": _txt(r.sector), "companies": _num(r.companies),
                       "loan_pct": float(getattr(r, "_3")),
                       "lbg_pct": float(getattr(r, "_4"))} for r in sb.itertuples()]

    out["caveat"] = (
        "All of this is secured borrowing only, covering about 7% of companies, so it shows "
        "who holds loans-against-assets, not overall banking share. Percentages leave out the "
        "1-in-5 lenders we could not name. The contested-book and lapsed-client views use "
        "summary flags, not dated events, so treat “who took our clients” as a strong "
        "hint, not an exact count.")

    _MARKET_CACHE.update(out)
    return jsonify(out)


@app.route("/api/browse")
def browse():
    """The list the panel drives: view + filters + preset, one page of results.

    Returns `total` for the whole matching set so the header can say "Showing N of M"
    while only one page crosses the wire.
    """
    view = request.args.get("view", "all")
    where, params = build_filter_where(request.args)
    scope = f"({view_where(view)}) AND ({where})"
    limit, offset = paging(request.args)

    total = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {scope}",
                  [PARQUET] + params).n[0])
    universe = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {view_where(view)}",
                     [PARQUET]).n[0])

    order = {"gazette": "ORDER BY gaz_max_distress_stage DESC NULLS LAST, "
                        "gaz_latest_notice_date DESC NULLS LAST",
             "lbg": "ORDER BY months_since_last_lbg_satisfaction ASC NULLS LAST"
             }.get(view, "ORDER BY CompanyName")
    if request.args.get("sort") in SORTABLE:
        d = "DESC" if request.args.get("dir", "desc").lower() == "desc" else "ASC"
        order = f'ORDER BY "{request.args["sort"]}" {d} NULLS LAST'
    order += TIE_BREAK

    df = q(f"SELECT {LIST_SELECT}, {LIFECYCLE_SQL} AS lifecycle FROM read_parquet(?) "
           f"WHERE {scope} {order} LIMIT ? OFFSET ?", [PARQUET] + params + [limit, offset])
    return jsonify(view=view, total=total, universe=universe, returned=len(df),
                   offset=offset, rows=[list_record(r) for r in records(df)])


@app.route("/api/filter")
def filter_():
    """Any combination of the allow-listed filters, across the whole universe.

    Returns the matching count for the WHOLE result set alongside just one page of
    rows, so the UI can say "13,412 companies" while holding 50 in memory.
    """
    where, params = build_where(request.args)
    limit, offset = paging(request.args)
    cols = ", ".join(f'"{c}"' for c in LIST_COLS)

    total = int(q(f"SELECT count(*) AS n FROM read_parquet(?) WHERE {where}",
                  [PARQUET] + params).n[0])
    df = q(f"SELECT {cols} FROM read_parquet(?) WHERE {where} {order_by(request.args)} "
           f"LIMIT ? OFFSET ?", [PARQUET] + params + [limit, offset])
    return jsonify(total=total, returned=len(df), limit=limit, offset=offset,
                   sort=request.args.get("sort"), rows=rows_out(df))


@app.route("/api/aggregate")
def aggregate():
    """count / avg / min / max grouped by one allow-listed column, with filters applied."""
    by = request.args.get("by", "sector")
    if by not in GROUPABLE:
        return jsonify(error=f"cannot group by {by!r}", allowed=sorted(GROUPABLE)), 400
    metric = request.args.get("metric", "count")
    col = request.args.get("metric_col", "score_lending")
    if metric != "count" and col not in NUMERIC_FILTERS:
        return jsonify(error=f"cannot aggregate {col!r}"), 400

    expr = "count(*)" if metric == "count" else f'{metric}("{col}")'
    group = LIFECYCLE_SQL if by == "lifecycle" else f'"{by}"'
    where, params = build_where(request.args)
    df = q(f"SELECT {group} AS value, count(*) AS n, {expr} AS metric "
           f"FROM read_parquet(?) WHERE {where} GROUP BY 1 ORDER BY 2 DESC",
           [PARQUET] + params)
    return jsonify(group_by=by, metric=metric if metric == "count" else f"{metric}({col})",
                   groups=[{"value": None if r.value is None else str(r.value),
                            "count": int(r.n),
                            "metric": None if r.metric is None else float(r.metric)}
                           for r in df.itertuples()])


def rows_out(df):
    df = df.where(df.notna(), None)
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in rec.items()}
            for rec in df.to_dict("records")]


# --------------------------------------------------------------------------------
# Static files, so the existing dashboard keeps working untouched
# --------------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/<path:filename>")
def static_file(filename):
    return send_from_directory(HERE, filename)


def load_aux(con):
    """Three side files the company page needs, held in memory. These are tables in the
    in-memory connection, not a database on disk; nothing is written anywhere."""
    P = DATA / "processed"
    con.execute(f"""CREATE TABLE notices AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(P / "nb10_gazette_notices_thru_2026-07.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE news AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(P / "nb14_news_signals_2026-06-30.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE news398 AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(SAM / "news_coverage_summary.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE tm_f AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(SAM / "ipo_trademarks_company_features.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE tm_e AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(SAM / "ipo_trademarks_events.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE grants AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(SAM / "ukri_grants_company_features.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE prop_f AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(SAM / "land_registry_company_features.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE prop_e AS
        SELECT *, {CLEAN_CN.format(col='"CompanyNumber"')} AS cn
        FROM read_csv('{(SAM / "land_registry_events.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)""")
    con.execute(f"""CREATE TABLE ident AS
        SELECT {CLEAN_CN.format(col='"CompanyNumber"')} AS cn,
               "IncorporationDate", "RegAddress.AddressLine1", "RegAddress.PostTown",
               "RegAddress.PostCode"
        FROM read_csv('{(P / "filtered_bb_sme_sectors_all_status_2026-08-01.csv").as_posix()}',
                      all_varchar=true, ignore_errors=true)
        QUALIFY row_number() OVER (PARTITION BY cn) = 1""")
    for t in ("notices", "news", "news398", "grants", "tm_f", "tm_e",
              "prop_f", "prop_e", "ident"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:<8} {n:>9,} rows")


def load_build_meta():
    """UI configuration the browser reads at boot: snapshot dates, which sources are
    live, the score-model definitions, and the Gazette notice URL stem. It is config,
    not data, so it lives in its own small file rather than being restated here.

    store_meta.json was lifted out of the old data.js store, which held the same block
    under a 26 MB payload the browser no longer loads. data.js is still accepted as a
    fallback so an older checkout keeps working, but it is no longer required."""
    global BUILD_META
    import json
    small = HERE / "store_meta.json"
    if small.exists():
        try:
            BUILD_META = json.loads(small.read_text(encoding="utf-8"))
            print(f"  config    {len(BUILD_META)} keys from store_meta.json")
            return
        except Exception as e:
            print(f"  could not read store_meta.json ({e}); trying data.js")
    f = HERE / "data.js"
    if not f.exists():
        print("  no store_meta.json or data.js; serving live counts only")
        return
    try:
        BUILD_META = json.loads(f.read_text(encoding="utf-8")[len("window.STORE = "):-1])["meta"]
        BUILD_META.pop("companies_without_signal", None)   # store-specific, meaningless now
        print(f"  config    {len(BUILD_META)} keys lifted from data.js")
    except Exception as e:
        print(f"  could not read data.js meta ({e}); serving live counts only")


def main():
    global _con, PARQUET, DATA, DEFAULT_PARQUET, RAW_PARQUET, SAM, MARKET
    ap = argparse.ArgumentParser(description="DuckDB query server over the company parquet")
    ap.add_argument("--data", default=None, metavar="DIR",
                    help="root of the data tree holding processed/, raw/ and "
                         "processed/sam_sc/. Also settable with the LLOYDS_DATA "
                         f"environment variable. Currently: {DATA}")
    # Left as None rather than defaulted here: --data may move the whole tree, and
    # argparse builds this default before --data has been read.
    ap.add_argument("--parquet", default=None,
                    help=f"default: <data>/processed/{DEFAULT_PARQUET.name}")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    if a.data:
        DATA = Path(a.data).expanduser().resolve()
        DEFAULT_PARQUET = DATA / "processed" / "dashboard_bulk_gazette_2026-07.parquet"
        RAW_PARQUET = DATA / "raw" / "dashboard_bulk_2026-07.parquet"
        SAM = DATA / "processed" / "sam_sc" / "data"
        MARKET = DATA.parent / "market_analysis"

    PARQUET = str(Path(a.parquet or DEFAULT_PARQUET).resolve())
    if not Path(PARQUET).exists():
        raise SystemExit(
            f"\nCould not find the company parquet:\n  {PARQUET}\n\n"
            f"The data tree is currently taken to be:\n  {DATA}\n\n"
            "Point it somewhere else with --data DIR, or by setting LLOYDS_DATA.\n"
            "That directory needs processed/ (with sam_sc/data/ inside it) and raw/.\n")
    print(f"data    : {DATA}")
    # In-memory connection: no .duckdb file is created anywhere.
    _con = duckdb.connect()
    n = _con.execute("SELECT count(*) FROM read_parquet(?)", [PARQUET]).fetchone()[0]
    print(f"parquet : {PARQUET}")
    print(f"universe: {n:,} companies queryable")
    print("loading side tables ...")
    load_aux(_con)
    load_build_meta()

    # Score thresholds are population-wide constants, so they are computed once here
    # rather than as a correlated subquery inside every filter.
    row = _con.execute(f"""SELECT
        quantile_cont(score_lending, 0.99), quantile_cont(score_lending, 0.90),
        quantile_cont(score_growth, 0.99),  quantile_cont(score_growth, 0.90),
        quantile_cont(score_insolvency, 0.99), quantile_cont(score_insolvency, 0.90)
        FROM read_parquet(?) WHERE is_active""", [PARQUET]).fetchone()
    for name, val in zip(["__P99_LENDING__", "__P90_LENDING__", "__P99_GROWTH__",
                          "__P90_GROWTH__", "__P99_RISK__", "__P90_RISK__"], row):
        _QUANTILES[name] = float(val)
    print(f"  score thresholds computed (lending p99 = {_QUANTILES['__P99_LENDING__']:.6f})")
    print(f"serving : http://127.0.0.1:{a.port}   (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{a.port}")).start()
    app.run(host="127.0.0.1", port=a.port, threaded=True)


if __name__ == "__main__":
    main()
