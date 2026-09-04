"""
Match UKRI funded organisations to the dashboard universe.

Grants are the weakest of the three sources and the file says so rather than hiding it:

  * no company number anywhere in the API, so matching is name plus postcode
  * no date without one API call per organisation, about 97,000 of them, so there is
    no events file and grants can never appear on the timeline
  * 45% of funded organisations publish no postcode at all, and those are dropped
    rather than matched on name alone, because a name-only match is how an Oxford
    "Amazon Ltd" ends up credited with someone else's work

Output: dashboard_pack/ukri_grants_company_features.csv, features only.

Run:  python scripts/build_grants_pack.py
"""

import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / "GithubLLoyds" / "src"))
from dashboard_export import normalise_name, normalise_postcode  # noqa: E402

ORGS = BASE / "work" / "ukri_orgs.csv"
MASTER = BASE / "work" / "gaz_jul" / "company_master_gazette_thru_2026-07.csv"
OUT = BASE / "dashboard_pack" / "ukri_grants_company_features.csv"

SNAPSHOT_DATE = "2026-08-11"      # the day the API was harvested


def outward(pc):
    s = normalise_postcode(pc)
    if not s:
        return None
    return s if len(s) <= 4 else s[:-3]


print("reading the universe ...")
uni = pd.read_csv(MASTER, dtype=str,
                  usecols=["CompanyNumber", "CompanyName", "RegAddress.PostCode"])
uni.columns = [c.strip() for c in uni.columns]
uni["nn"] = uni["CompanyName"].map(normalise_name)
uni["pc"] = uni["RegAddress.PostCode"].map(normalise_postcode)
uni["area"] = uni["RegAddress.PostCode"].map(outward)
uni = uni.dropna(subset=["nn"])
print(f"  {len(uni):,} companies")


def unique_map(df, key_cols, value_col="CompanyNumber"):
    """Build key -> value, keeping only keys that identify exactly one company."""
    d = df.dropna(subset=key_cols).copy()
    d["_k"] = d[key_cols[0]].str.cat(d[key_cols[1:]], sep="|")
    counts = d["_k"].value_counts()
    keep = counts[counts == 1].index
    return d[d["_k"].isin(keep)].set_index("_k")[value_col].to_dict(), \
        int((counts > 1).sum())


by_full, amb_full = unique_map(uni, ["nn", "pc"])
by_area, amb_area = unique_map(uni, ["nn", "area"])
print(f"  name+full postcode keys: {len(by_full):,}  (ambiguous dropped {amb_full:,})")
print(f"  name+area keys         : {len(by_area):,}  (ambiguous dropped {amb_area:,})")
del uni

print("\nreading the UKRI organisations ...")
orgs = pd.read_csv(ORGS, dtype=str)
orgs["n_projects"] = pd.to_numeric(orgs["n_projects"], errors="coerce").fillna(0).astype(int)
print(f"  {len(orgs):,} organisations")

orgs["nn"] = orgs["name"].map(normalise_name)
orgs["pc"] = orgs["postcode"].map(normalise_postcode)
orgs["area"] = orgs["postcode"].map(outward)

no_pc = orgs["pc"].isna().sum()
print(f"  without a postcode, dropped: {no_pc:,}  ({no_pc / len(orgs):.1%})")

usable = orgs.dropna(subset=["nn", "pc"]).copy()
usable["k_full"] = usable["nn"] + "|" + usable["pc"]
usable["k_area"] = usable["nn"] + "|" + usable["area"]

usable["cn_full"] = usable["k_full"].map(by_full)
usable["cn_area"] = usable["k_area"].map(by_area)

usable["CompanyNumber"] = usable["cn_full"].fillna(usable["cn_area"])
usable["confidence"] = usable["cn_full"].notna().map({True: 0.90, False: 0.80})
usable["match_method"] = usable["cn_full"].notna().map(
    {True: "name_postcode", False: "name_postcode_area"})

hit = usable[usable["CompanyNumber"].notna()].copy()
print(f"\nmatched: {len(hit):,} organisations")
print(hit["match_method"].value_counts().to_string())

feats = (hit.groupby("CompanyNumber")
         .agg(grant_n_organisations=("gtr_id", "count"),
              grant_n_projects=("n_projects", "sum"),
              grant_max_confidence=("confidence", "max"),
              grant_min_confidence=("confidence", "min"),
              grant_match_method=("match_method", lambda s: "|".join(sorted(set(s)))))
         .reset_index())
feats.insert(1, "grant_has_any", 1)
feats["grant_source_date"] = SNAPSHOT_DATE
feats["grant_has_date"] = 0        # stated on the row: no date exists for this source

feats.to_csv(OUT, index=False)
print(f"\ncompanies written: {len(feats):,}")
print(f"projects total   : {int(feats['grant_n_projects'].sum()):,}")
print(f"wrote {OUT}")
