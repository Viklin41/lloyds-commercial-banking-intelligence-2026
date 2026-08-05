"""
Gazette adapter + minimal builder, written against the NB11 blueprint.

This is step 3 of the plan: one adapter, end to end, into something the screen
can read. It does not fetch anything. It reads files that are already on disk.

    data/processed/filtered_bb_sme_sectors_all_status.csv   1,493,972 companies
    data/processed/nb10_gazette_company_features.csv        106,664 companies
    data/processed/nb10_gazette_notices.csv                 284,230 notices

The universe is the WIDENED one built by notebooks/build_widened_universe.py,
so companies that have stopped being Active are included. Each company carries a
`lifecycle` value (Trading, Fading, Distressed, Insolvent) because those mean
very different things to a relationship manager.

Output:

    dashboard/data.js    window.STORE = { companies: [...], meta: {...} }

A .js file rather than .json on purpose, so the dashboard still opens by
double-clicking. Browsers block fetch() on file:// URLs.

Run:  python dashboard/build_data.py
"""

import json
import random
from pathlib import Path

import pandas as pd

DATA = Path(r"C:\Users\visha\Lloyds_Github\data\processed")
OUT = Path(__file__).parent / "data.js"

SNAPSHOT_DATE = "2026-06-30"   # pinned, same value NB10 used
SEED = 42
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


STAGE_LABEL = {1: "Early warning", 2: "Creditor action", 3: "Formal insolvency",
               4: "Liquidation", 5: "Closing"}


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
print("reading the widened universe (669 MB, this takes a moment) ...")
uni = pd.read_csv(
    DATA / "filtered_bb_sme_sectors_all_status.csv",
    dtype=str,
    usecols=lambda c: c.strip() in {
        "CompanyName", "CompanyNumber", "CompanyStatus", "IncorporationDate",
        "sector", "segment", "lifecycle",
        "RegAddress.AddressLine1", "RegAddress.PostTown", "RegAddress.PostCode",
    },
)
uni = norm_cols(uni)
uni["cn"] = uni["CompanyNumber"].map(clean_company_number)
uni = uni[uni["cn"].notna()].drop_duplicates("cn")
print(f"  {len(uni):,} companies")
print("  " + uni["lifecycle"].value_counts().to_string().replace("\n", "\n  "))

print("reading Gazette company features ...")
ft = norm_cols(pd.read_csv(DATA / "nb10_gazette_company_features.csv", dtype=str))
ft["cn"] = ft["CompanyNumber"].map(clean_company_number)
ft = ft[ft["cn"].notna()].drop_duplicates("cn")
print(f"  {len(ft):,} companies with Gazette features")

print("reading notices ...")
nt = norm_cols(pd.read_csv(DATA / "nb10_gazette_notices.csv", dtype=str))
nt["cn"] = nt["CompanyNumber"].map(clean_company_number)
before = len(nt)
nt = nt[nt["cn"].notna() & nt["notice_date"].notna()].copy()
print(f"  {len(nt):,} notices kept of {before:,}  "
      f"({before - len(nt):,} dropped: no company number or no date)")

# The join. Rule 1: on the cleaned company number, never the name.
flagged = ft[ft["cn"].isin(set(uni["cn"]))].copy()
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


def address(p):
    bits = [p.get("RegAddress.AddressLine1"), p.get("RegAddress.PostTown"),
            p.get("RegAddress.PostCode")]
    return ", ".join(str(b).strip() for b in bits
                     if b is not None and str(b).strip() not in ("", "nan"))


profiles = uni.set_index("cn").to_dict("index")


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
    }

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

# Companies with nothing. Gazette is our only source, so "not flagged" means
# zero signals. Rule 3: these are results, not missing rows.
random.seed(SEED)
flagged_set = set(flagged["cn"])
pool = [c for c in uni["cn"].tolist() if c not in flagged_set]
for cn in random.sample(pool, N_QUIET):
    companies.append(build_company(cn, gaz=None))

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
        "built_from": ["filtered_bb_sme_sectors_all_status.csv",
                       "nb10_gazette_company_features.csv",
                       "nb10_gazette_notices.csv"],
        "sources_live": ["gazette"],
        "sources_pending": ["news", "contracts", "hiring", "property",
                            "trademark", "grants"],
        "signal_rows": len(signals),
        "companies_with_signal": int(len(flagged)),
        "companies_without_signal": N_QUIET,
        "universe": int(len(uni)),
        "lifecycle_counts": lifecycle_counts,
        "flagged_by_lifecycle": flagged_by_life,
        "notice_url_stem": NOTICE_URL_STEM,
    },
    "companies": companies,
}

OUT.write_text("window.STORE = " + json.dumps(store, separators=(",", ":")) + ";",
               encoding="utf-8")
print(f"wrote {OUT}  ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")
