"""
Trade marks from the IPO open data file, matched to the dashboard universe.

The IPO file carries no company number. It gives a proprietor name and a postcode
*area* only (LU1, not LU1 3AB), so matching is name plus area and it is weaker than
anything keyed on a number. That is the point of the source-by-source honesty in the
report: property keys on a number and works, trade marks key on a name and do not work
as well.

Match rule, in order of strength:
  1. normalised name plus postcode area, unique in the universe   confidence 0.85
  2. everything else is dropped and counted

A name plus area that maps to more than one company is dropped rather than guessed at,
because a wrong attribution on a company page is worse than a missing one.

Run:  python scripts/build_trademark_pack.py
"""

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[2]          # the LLoyds Task folder
sys.path.insert(0, str(BASE / "GithubLLoyds" / "src"))
from dashboard_export import normalise_name, normalise_postcode, write_source_pack  # noqa: E402

IPO_ZIP = BASE / "opendatadomestic.zip"
MASTER = BASE / "work" / "gaz_jul" / "company_master_gazette_thru_2026-07.csv"
OUT_DIR = BASE / "dashboard_pack"

SNAPSHOT_DATE = "2026-07-31"     # the newest date anywhere in the store
CHUNK = 250_000
USE = ["Trade Mark", "Mark Text", "Name", "Postcode", "Status", "Filed", "Registered"]

IPO_URL = "https://www.ipo.gov.uk/tmcase/Results/1/"


def outward(pc):
    """The outward code, whichever form comes in.

    Companies House gives a full postcode, LU1 3AB. The IPO gives the outward code
    only, LU1. UK outward codes are 2 to 4 characters and full postcodes are 5 to 7,
    so length tells the two apart. Feeding a bare LU1 through a full-postcode stripper
    returns nothing, which is what produced zero matches on the first run.
    """
    s = normalise_postcode(pc)
    if not s:
        return None
    if len(s) <= 4:
        return s              # already an outward code
    return s[:-3]             # full postcode, drop the inward part


# ---------------------------------------------------------------------------
# 1. The universe lookup
# ---------------------------------------------------------------------------
print("reading the universe ...")
uni = pd.read_csv(MASTER, dtype=str, usecols=["CompanyNumber", "CompanyName",
                                              "RegAddress.PostCode"])
uni.columns = [c.strip() for c in uni.columns]
print(f"  {len(uni):,} companies")

uni["nn"] = uni["CompanyName"].map(normalise_name)
uni["area"] = uni["RegAddress.PostCode"].map(outward)
uni = uni.dropna(subset=["nn", "area"])
uni["key"] = uni["nn"] + "|" + uni["area"]

counts = uni["key"].value_counts()
unique_keys = counts[counts == 1].index
lookup = (uni[uni["key"].isin(unique_keys)]
          .set_index("key")["CompanyNumber"].to_dict())
print(f"  usable name+area keys : {len(lookup):,}")
print(f"  ambiguous keys dropped: {len(counts) - len(unique_keys):,}")
del uni

# ---------------------------------------------------------------------------
# 2. Stream the IPO file
# ---------------------------------------------------------------------------
print("\nreading the IPO file (817 MB, UTF-16) ...")
parts = []
n_marks = n_named = n_amb = 0
seen_keys = set()

zf = zipfile.ZipFile(IPO_ZIP)
with zf.open("OpenDataDomestic.txt") as fh:
    reader = pd.read_csv(io.TextIOWrapper(fh, encoding="utf-16"), sep="|", dtype=str,
                         usecols=USE, chunksize=CHUNK)
    for k, df in enumerate(reader, start=1):
        df.columns = [c.strip() for c in df.columns]
        n_marks += len(df)
        for c in USE:
            df[c] = df[c].str.strip()

        df["key"] = df["Name"].map(normalise_name).fillna("") + "|" + \
                    df["Postcode"].map(outward).fillna("")
        df["CompanyNumber"] = df["key"].map(lookup)
        m = df[df["CompanyNumber"].notna()]
        n_named += len(m)
        seen_keys.update(m["key"])

        if not m.empty:
            status = m["Status"].str.lower().str.replace(r"[^a-z]+", "_", regex=True)
            parts.append(pd.DataFrame({
                "CompanyNumber": m["CompanyNumber"].values,
                "event_date": m["Filed"].values,
                "event_type": ("trademark_" + status).values,
                "detail": (m["Mark Text"].fillna("(figurative mark)").str.slice(0, 120)
                           + "  [" + m["Status"] + "]").values,
                "value": 1.0,
                "url": (IPO_URL + m["Trade Mark"]).values,
                "confidence": 0.85,
                "match_method": "name_postcode_area",
                "trade_mark": m["Trade Mark"].values,
                "status": m["Status"].values,
                "registered_date": m["Registered"].values,
            }))
        print(f"  chunk {k}: {n_marks:,} marks read, {n_named:,} matched")

events = pd.concat(parts, ignore_index=True)
events = events[events["event_date"].str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]

print(f"\nmarks in the file    : {n_marks:,}")
print(f"matched to a company : {n_named:,}  ({n_named / n_marks:.2%})")
print(f"with a usable date   : {len(events):,}")
print(f"distinct companies   : {events['CompanyNumber'].nunique():,}")
print("\nby status:")
print(events["status"].value_counts().head(8).to_string())

# ---------------------------------------------------------------------------
# 3. Write
# ---------------------------------------------------------------------------
print()
write_source_pack(
    events=events,
    prefix="tm",
    source="ipo_trademarks",
    out_dir=OUT_DIR,
    snapshot_date=SNAPSHOT_DATE,
    extra_cols=["trade_mark", "status", "registered_date"],
    universe=None,          # already matched against the universe, nothing to filter
)
