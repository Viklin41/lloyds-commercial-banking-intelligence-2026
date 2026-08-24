"""
Widened company universe: NB01's filter with the status line removed.

NB01 (`01_companies_house.ipynb`, Samuel's) builds the 1.37M universe with two
filters applied to the Companies House bulk file:

    1. CompanyStatus == "Active"
    2. at least one of the four SIC columns maps to a target sector

The team has since agreed to include companies that are no longer Active, so
this script keeps filter 2 and drops filter 1. Everything else, including the
SIC map and the segment map, is copied verbatim from NB01 so the two files stay
comparable.

It writes a NEW file and does not touch Samuel's. NB01 stays as it is.

    in   data/raw/BasicCompanyDataAsOneFile-{SNAPSHOT}.csv
    out  data/processed/filtered_bb_sme_sectors_all_status_{SNAPSHOT}.csv

Set SNAPSHOT below to choose the month. Output is named after the snapshot so a
rebuild never silently replaces a universe other people have already matched against.

Run:  python notebooks/build_widened_universe.py
"""

import time
from pathlib import Path

import pandas as pd

DATA = Path(r"C:\Users\visha\Lloyds_Github\data")

# Which Companies House monthly bulk file to build from. The output is named after
# it, so universes from different snapshots sit side by side instead of one quietly
# replacing another. Companies House publishes these around the 7th of each month.
SNAPSHOT = "2026-08-01"

CSV_PATH = DATA / "raw" / f"BasicCompanyDataAsOneFile-{SNAPSHOT}.csv"
SIC_PATH = DATA / "processed" / "SIC.csv"
OUTPUT_PATH = DATA / "processed" / f"filtered_bb_sme_sectors_all_status_{SNAPSHOT}.csv"
CHUNKSIZE = 50_000

# ---- copied verbatim from NB01 -------------------------------------------
SEGMENT_MAP = {
    "MICRO ENTITY": "Micro",
    "SMALL": "Small",
    "TOTAL EXEMPTION FULL": "Small",
    "TOTAL EXEMPTION SMALL": "Small",
    "UNAUDITED ABRIDGED": "Small",
    "AUDITED ABRIDGED": "Small",
    "MEDIUM": "Medium",
    "FULL": "Large",
    "GROUP": "Large",
    "DORMANT": "Dormant",
    "NO ACCOUNTS FILED": "No Filings",
    "AUDIT EXEMPTION SUBSIDIARY": "Subsidiary",
    "FILING EXEMPTION SUBSIDIARY": "Subsidiary",
    "ACCOUNTS TYPE NOT AVAILABLE": "Unknown",
}

FAST_GROWTH_CODES = {
    "62011", "62012", "62020", "62030", "62090",
    "63110", "63120", "72110", "72190", "72200", "66190",
}

TARGET_SECTIONS = {
    "Section J - Information and communication": "Technology, legal & professional",
    "Section M - Professional, scientific and technical activities": "Technology, legal & professional",
    "Section C - Manufacturing": "Manufacturing",
}

SIC_COLS = ["SICCode.SicText_1", "SICCode.SicText_2",
            "SICCode.SicText_3", "SICCode.SicText_4"]

# ---- lifecycle grouping, new here ----------------------------------------
# Three groups, because they mean very different things to a relationship
# manager. Trading, fading, and finished.
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

# --------------------------------------------------------------------------
sic_df = pd.read_csv(SIC_PATH, dtype=str)
code_to_section = dict(zip(sic_df["Code"].str.strip(), sic_df["Section"].str.strip()))
code_to_sector = {code: "Fast growth & emerging" for code in FAST_GROWTH_CODES}
for code, section in code_to_section.items():
    if section in TARGET_SECTIONS and code not in code_to_sector:
        code_to_sector[code] = TARGET_SECTIONS[section]
print(f"SIC codes mapped: {len(code_to_sector):,}   (NB01 reports 325)")

chunks = []
t0 = time.time()
for i, chunk in enumerate(pd.read_csv(CSV_PATH, chunksize=CHUNKSIZE, low_memory=False)):
    # NB01 filter 1 (CompanyStatus == "Active") deliberately NOT applied here.
    c = chunk
    sector = pd.Series(pd.NA, index=c.index, dtype="object")
    for col in SIC_COLS:
        sector = sector.combine_first(c[col].str[:5].map(code_to_sector))
    c = c.assign(sector=sector).dropna(subset=["sector"])
    if not c.empty:
        chunks.append(c)
    if (i + 1) % 40 == 0:
        print(f"  chunk {i+1:>4} | kept so far: {sum(len(x) for x in chunks):>9,} "
              f"| {time.time()-t0:.0f}s")

df = pd.concat(chunks, ignore_index=True)
df["segment"] = df["Accounts.AccountCategory"].map(SEGMENT_MAP)
df["lifecycle"] = df["CompanyStatus"].str.strip().map(LIFECYCLE).fillna("Unknown")
print(f"\nfiltered in {time.time()-t0:.0f}s: {df.shape}")

df.to_csv(OUTPUT_PATH, index=False)
print(f"saved {OUTPUT_PATH}  ({len(df):,} rows, "
      f"{OUTPUT_PATH.stat().st_size/1e6:.0f} MB)\n")

# ---- what changed, and what the new groups look like ---------------------
print("LIFECYCLE x STATUS")
print(df.groupby(["lifecycle", "CompanyStatus"]).size()
        .sort_values(ascending=False).to_string())

print("\nSEGMENT MIX BY LIFECYCLE  (row %)")
mix = pd.crosstab(df["lifecycle"], df["segment"], normalize="index").mul(100).round(1)
print(mix.to_string())

print("\nSEGMENT MIX BY LIFECYCLE  (counts)")
print(pd.crosstab(df["lifecycle"], df["segment"]).to_string())

print("\nHEADLINE")
active = int((df["CompanyStatus"].str.strip() == "Active").sum())
# Computed, not hardcoded: the Active count moves with every monthly snapshot.
print(f"  Active only {active:,} -> all statuses {len(df):,}   (+{len(df)-active:,})")
fading = df[df["lifecycle"] == "Fading"]
print(f"  'Fading' (proposal to strike off): {len(fading):,}")
real = fading[~fading["segment"].isin(["Dormant", "No Filings", "Unknown"])]
print(f"    of which have filed real accounts: {len(real):,} "
      f"({100*len(real)/len(fading):.1f}%)")
