"""
Shared helpers for turning any source into the two CSV files the dashboard reads.

The dashboard build script (dashboard/build_data.py) already reads the Gazette work as
two files: one row per event, and one row per company. Every source we add follows the
same pattern, so the build script only needs a new file name and a prefix.

    <stem>_events.csv            one row per event   (like nb10_gazette_notices.csv)
    <stem>_company_features.csv  one row per company (like nb10_gazette_company_features.csv)

Both key on CompanyNumber, cleaned the same way everywhere.

One rule that changed on 10 August 2026: we no longer filter our output down to the
companies in the local spine. The spine is an older and smaller vintage than the
dashboard universe, so filtering on it silently threw away most of what the dashboard
could use. We emit every company number the source names, and the dashboard build joins
it to whichever universe it holds.

Put this file next to lloyds.duckdb in your Drive folder so the notebooks can import it.
"""

import re
from pathlib import Path

import pandas as pd

# The event columns every source produces. Keep the order, the export checks it.
EVENT_COLS = [
    "CompanyNumber",   # cleaned 8 character key, the only join key
    "event_date",      # YYYY-MM-DD, the date the thing actually happened
    "event_type",      # short machine readable label, e.g. property_title
    "detail",          # one readable line for the screen
    "value",           # number if the event has one (pounds, count), else blank
    "url",             # link to the public record, blank if there is none
    "confidence",      # 1.0 exact company number, lower for a name match
    "match_method",    # company_number | name_postcode | name_postcode_area | name_only
]


# ---------------------------------------------------------------------------
# Cleaners. Every source uses these, so the same company looks the same everywhere.
# ---------------------------------------------------------------------------
def clean_company_number(raw):
    """Canonical 8 character Companies House number, or None if it cannot be one.

    Pure digits are zero padded. Two letter prefixes (SC, NI, OC, SO, NC) keep the
    letters and pad the digits, so SC12345 becomes SC012345 rather than 0SC12345.
    Anything longer than 8 characters is not a company number, so it is dropped
    rather than guessed at.
    """
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if s in ("", "NAN", "NONE", "NULL", "N/A"):
        return None
    s = re.sub(r"[^A-Z0-9]", "", s)
    if not s or len(s) > 8:
        return None
    if s.isdigit():
        return s.zfill(8)
    m = re.match(r"^([A-Z]{2})(\d+)$", s)
    if m:
        return m.group(1) + m.group(2).zfill(6)
    return None


_SUFFIXES = [
    "LIMITED", "LTD", "PLC", "PUBLIC LIMITED COMPANY", "LLP",
    "LIMITED LIABILITY PARTNERSHIP", "LP", "CIC", "CIO",
    "COMPANY", "CO", "AND", "THE",
]
_SUFFIX_RE = re.compile(r"\b(" + "|".join(_SUFFIXES) + r")\b")


def normalise_name(name):
    """Plain comparable name key. Same rule as notebook 05, so keys line up."""
    if name is None:
        return None
    s = str(name).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = _SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


_NOT_A_POSTCODE = {"", "NAN", "NONE", "NULL", "NAT", "NA", "N/A",
                   "UNKNOWN", "UNSPECIFIED", "-"}


def normalise_postcode(pc):
    """Uppercase, no spaces. SL3 9EH and sl39eh both become SL39EH.

    Missing values must return None, not a string. Pandas reads a blank cell as the
    float nan, and str(nan) is "nan", which stripped and uppercased becomes the literal
    "NAN". Left unchecked that is a postcode as far as any join is concerned, so two
    companies with no postcode match each other and get scored as a confident match.
    """
    if pc is None:
        return None
    s = str(pc).strip().upper()
    if s in _NOT_A_POSTCODE:
        return None
    s = re.sub(r"[^A-Z0-9]", "", s)
    if not s or s in _NOT_A_POSTCODE:
        return None
    return s


def postcode_area(pc):
    """The outward part only, e.g. SL3 from SL3 9EH. Some sources give nothing finer."""
    s = normalise_postcode(pc)
    if not s or len(s) < 4:
        return None
    return s[:-3]


def to_iso_date(v, dayfirst=True):
    """Anything date shaped to YYYY-MM-DD, or None. Government files are mostly
    day first, which pandas guesses wrong often enough to be worth stating.

    Already ISO dates are returned untouched. Without that shortcut, calling this
    twice on the same value flips 2025-08-02 into 2025-02-08 under dayfirst, which is
    silent and wrong. The export calls it again on values a notebook has already
    parsed, so the shortcut is load bearing rather than an optimisation.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s in ("", "nan", "NaT", "None"):
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    d = pd.to_datetime(s, dayfirst=dayfirst, errors="coerce")
    if pd.isna(d):
        return None
    return d.date().isoformat()


# ---------------------------------------------------------------------------
# The export
# ---------------------------------------------------------------------------
def build_company_features(events, prefix, snapshot_date):
    """Roll the event rows up to one row per company.

    Column names follow the Gazette file, so gaz_notice_count_total becomes
    <prefix>_count_total and so on. Absence is a zero, never a blank, because the
    dashboard treats a blank as "we did not look".
    """
    p = prefix
    ev = events.copy()
    ev["_d"] = pd.to_datetime(ev["event_date"], errors="coerce")
    ev["_v"] = pd.to_numeric(ev["value"], errors="coerce")
    snap = pd.Timestamp(snapshot_date)
    cutoff_12m = snap - pd.DateOffset(months=12)

    g = ev.groupby("CompanyNumber", sort=False)
    out = pd.DataFrame({
        f"{p}_count_total": g.size(),
        # How many events actually carried a value. Land Registry prints a price on about
        # four titles in ten, so a total without this denominator invites a wrong average.
        f"{p}_value_count": g["_v"].count(),
        f"{p}_first_date": g["_d"].min().dt.date.astype("string"),
        f"{p}_latest_date": g["_d"].max().dt.date.astype("string"),
        f"{p}_value_total": g["_v"].sum(min_count=1),
        f"{p}_value_max": g["_v"].max(),
        f"{p}_max_confidence": g["confidence"].max(),
        f"{p}_min_confidence": g["confidence"].min(),
        f"{p}_types": g["event_type"].agg(lambda s: "|".join(sorted(set(s.dropna())))),
        f"{p}_match_method": g["match_method"].agg(
            lambda s: "|".join(sorted(set(s.dropna())))),
    })

    recent = ev[ev["_d"] >= cutoff_12m].groupby("CompanyNumber").size()
    out[f"{p}_count_12m"] = recent.reindex(out.index).fillna(0).astype(int)

    days = (snap - g["_d"].max()).dt.days
    out[f"{p}_days_since_latest"] = days.reindex(out.index)

    out[f"{p}_has_any"] = 1
    out = out.reset_index()

    order = ["CompanyNumber", f"{p}_has_any", f"{p}_count_total", f"{p}_count_12m",
             f"{p}_first_date", f"{p}_latest_date", f"{p}_days_since_latest",
             f"{p}_value_total", f"{p}_value_max", f"{p}_value_count", f"{p}_types",
             f"{p}_match_method", f"{p}_max_confidence", f"{p}_min_confidence"]
    return out[order]


def to_signal_rows(events, source, snapshot_date):
    """The same events in the eight column signal shape agreed with Vishal, plus the
    link as a ninth. This is the file that feeds a timeline."""
    return pd.DataFrame({
        "company_number": events["CompanyNumber"],
        "signal_type": events["event_type"],
        "signal_date": events["event_date"],
        "value": events["value"],
        "detail": events["detail"],
        "source": source,
        "confidence": events["confidence"],
        "retrieved_at": snapshot_date,
        "url": events["url"],
    })


def write_source_pack(events, prefix, source, out_dir, snapshot_date, stem=None,
                      extra_cols=None, universe=None):
    """Write both CSVs for one source and print what went out.

    events must hold the EVENT_COLS columns. Rows with no usable company number or no
    usable date are dropped here and counted, so the drop is visible rather than silent.

    extra_cols: source specific columns to carry into the events file, for example a
    postcode or a title number. They are not rolled up into the company features.

    universe: an iterable of company numbers. When given, only companies inside it are
    written, and the drop is reported. Use the dashboard universe here. Land Registry
    names 65,794 companies of which only about 4% are in our sectors, so writing
    everything makes a file twenty times bigger than the dashboard can use.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or f"{source}"

    missing = [c for c in EVENT_COLS if c not in events.columns]
    if missing:
        raise ValueError(f"events is missing columns: {missing}")

    extra_cols = [c for c in (extra_cols or []) if c in events.columns]
    ev = events[EVENT_COLS + extra_cols].copy()
    before = len(ev)
    ev["CompanyNumber"] = ev["CompanyNumber"].map(clean_company_number)
    ev = ev[ev["CompanyNumber"].notna()]
    no_number = before - len(ev)

    ev["event_date"] = ev["event_date"].map(to_iso_date)
    dated = ev[ev["event_date"].notna()].copy()
    no_date = len(ev) - len(dated)

    outside = 0
    if universe is not None:
        keep = set(universe)
        before_u = len(dated)
        dated = dated[dated["CompanyNumber"].isin(keep)].copy()
        outside = before_u - len(dated)

    ev_path = out_dir / f"{stem}_events.csv"
    ft_path = out_dir / f"{stem}_company_features.csv"
    sg_path = out_dir / f"{stem}_signals.csv"

    dated = dated.sort_values(["CompanyNumber", "event_date"])
    dated.to_csv(ev_path, index=False)

    feats = build_company_features(dated, prefix, snapshot_date)
    feats.to_csv(ft_path, index=False)

    to_signal_rows(dated, source, snapshot_date).to_csv(sg_path, index=False)

    print(f"source            : {source}")
    print(f"rows in           : {before:,}")
    print(f"dropped, no number: {no_number:,}")
    print(f"dropped, no date  : {no_date:,}")
    if universe is not None:
        print(f"dropped, outside universe: {outside:,}")
    print(f"events written    : {len(dated):,}")
    print(f"companies written : {len(feats):,}")
    print(f"date range        : {dated['event_date'].min()} to {dated['event_date'].max()}")
    print(f"\n  {ev_path}\n  {ft_path}\n  {sg_path}")
    return {"events": ev_path, "features": ft_path, "signals": sg_path,
            "n_events": len(dated), "n_companies": len(feats)}
