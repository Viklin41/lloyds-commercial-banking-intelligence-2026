"""Baseline attrition EDA on the Companies House bulk snapshot.

Produces the descriptive picture that must come before any modelling:
  - how common dormancy and closure are, overall and by sector, size, and age
  - charge / secured-lending presence
  - a demonstration that the first-50k-rows sample is biased versus a random one

This is a cross-sectional view from a single snapshot. It establishes base
rates. Detecting transitions (the actual attrition events) needs a second
snapshot or the API, handled elsewhere.

Run (from repo root, with the venv):
    .venv/Scripts/python -m src.attrition.run_bulk_eda --csv data/raw/BasicCompanyDataAsOneFile-2026-06-01.csv

If --csv is omitted it picks the most recent BasicCompanyData file in data/raw.
"""

from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path

import pandas as pd

from src.attrition import definitions as d

# Columns we actually need (names as they appear after stripping whitespace).
WANTED = {
    "CompanyName",
    "CompanyNumber",
    "CompanyCategory",
    "CompanyStatus",
    "IncorporationDate",
    "Accounts.AccountCategory",
    "Accounts.NextDueDate",
    "ConfStmtNextDueDate",
    "Mortgages.NumMortCharges",
    "Mortgages.NumMortOutstanding",
    "Mortgages.NumMortSatisfied",
    "Mortgages.NumMortPartSatisfied",
    "SICCode.SicText_1",
    "SICCode.SicText_2",
    "SICCode.SicText_3",
    "SICCode.SicText_4",
}

SIC_COLS = [
    "SICCode.SicText_1",
    "SICCode.SicText_2",
    "SICCode.SicText_3",
    "SICCode.SicText_4",
]

OUT_DIR = Path("reports/attrition")
FIG_DIR = OUT_DIR / "figures"


def find_default_csv() -> str:
    matches = sorted(glob.glob("data/raw/BasicCompanyData*.csv"))
    if not matches:
        raise FileNotFoundError(
            "No bulk file in data/raw. Download it from "
            "https://download.companieshouse.gov.uk/en_output.html and place the "
            "unzipped CSV in data/raw/."
        )
    return matches[-1]


def snapshot_date_from_name(path: str) -> pd.Timestamp:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path)
    return pd.Timestamp(m.group(1)) if m else pd.Timestamp.today().normalize()


def load_bulk(csv_path: str, nrows: int | None = None) -> pd.DataFrame:
    """Load only the needed columns, tolerant of the file's leading-space headers."""
    df = pd.read_csv(
        csv_path,
        usecols=lambda c: c.strip() in WANTED,
        nrows=nrows,
        dtype=str,
        low_memory=False,
    )
    df.columns = [c.strip() for c in df.columns]
    # Numeric mortgage counts.
    for col in [
        "Mortgages.NumMortCharges",
        "Mortgages.NumMortOutstanding",
        "Mortgages.NumMortSatisfied",
        "Mortgages.NumMortPartSatisfied",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


def add_derived(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Add attrition-relevant derived columns, vectorised where it matters."""
    # Status and accounts: map over the small set of unique values (fast).
    status_map = {v: d.classify_status(v) for v in df["CompanyStatus"].dropna().unique()}
    df["attrition_status"] = df["CompanyStatus"].map(status_map).fillna(d.STATUS_OTHER)
    df["is_distress"] = df["attrition_status"].isin(
        [d.STRIKE_OFF, d.INSOLVENCY, d.DISSOLVED]
    )

    acc = df["Accounts.AccountCategory"]
    act_map = {v: d.classify_accounts_activity(v) for v in acc.dropna().unique()}
    df["accounts_activity"] = acc.map(act_map).fillna(d.NO_ACCOUNTS)
    df["is_dormant"] = df["accounts_activity"].eq(d.DORMANT)

    size_map = {v: d.size_band(v) for v in acc.dropna().unique()}
    df["size_band"] = acc.map(size_map).fillna(d.SIZE_UNKNOWN)

    # Sector: map unique primary-SIC values, then apply fast-growth and charity rules.
    sic1 = df["SICCode.SicText_1"]
    base_sector_map = {
        v: d.target_sector([v]) for v in sic1.dropna().unique()
    }
    df["sector"] = sic1.map(base_sector_map).fillna(d.SECTOR_OTHER)

    # Fast-growth override: any of the 4 SIC columns holds a fast-growth code.
    fg = pd.Series(False, index=df.index)
    for col in SIC_COLS:
        if col in df.columns:
            codes = df[col].str.extract(r"(\d{5})", expand=False)
            fg = fg | codes.isin(d._FAST_GROWTH_CODES)
    df.loc[fg, "sector"] = d.SECTOR_FAST_GROWTH

    # Charity by company type (only where not already fast-growth).
    charity = df["CompanyCategory"].str.strip().str.lower().isin(d._CHARITY_CATEGORIES)
    df.loc[charity & ~fg, "sector"] = d.SECTOR_PUBLIC

    # Age in years.
    incorp = pd.to_datetime(df["IncorporationDate"], format="%d/%m/%Y", errors="coerce")
    df["age_years"] = (as_of - incorp).dt.days / 365.25

    # Filing punctuality.
    acc_due = pd.to_datetime(df["Accounts.NextDueDate"], format="%d/%m/%Y", errors="coerce")
    df["accounts_days_overdue"] = (as_of - acc_due).dt.days
    df["accounts_overdue"] = df["accounts_days_overdue"] > 0

    # Charge presence.
    df["has_charges"] = df["Mortgages.NumMortCharges"] > 0
    df["has_outstanding_charge"] = df["Mortgages.NumMortOutstanding"] > 0
    # Satisfied charges but none outstanding: possible deleveraging or switch.
    df["satisfied_no_outstanding"] = (df["Mortgages.NumMortSatisfied"] > 0) & (
        df["Mortgages.NumMortOutstanding"] == 0
    )
    return df


def rate_table(df: pd.DataFrame, group: str) -> pd.DataFrame:
    """Counts and attrition rates by a grouping column."""
    g = df.groupby(group)
    out = pd.DataFrame(
        {
            "n": g.size(),
            "dormant_rate": g["is_dormant"].mean(),
            "distress_rate": g["is_distress"].mean(),
            "overdue_rate": g["accounts_overdue"].mean(),
            "has_charge_rate": g["has_charges"].mean(),
        }
    )
    return out.sort_values("n", ascending=False).round(4)


def df_to_md(df: pd.DataFrame, index_name: str = "") -> str:
    """Minimal Markdown table from a DataFrame (avoids a tabulate dependency)."""
    cols = list(df.columns)
    header = "| " + " | ".join([index_name] + [str(c) for c in cols]) + " |"
    sep = "| " + " | ".join(["---"] * (len(cols) + 1)) + " |"
    lines = [header, sep]
    for idx, row in df.iterrows():
        cells = [str(idx)] + [str(row[c]) for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def age_buckets(df: pd.DataFrame) -> pd.Series:
    return pd.cut(
        df["age_years"],
        bins=[-1, 1, 3, 5, 10, 20, 200],
        labels=["<1", "1-3", "3-5", "5-10", "10-20", "20+"],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="Path to the bulk CSV")
    ap.add_argument("--nrows", type=int, default=None, help="Limit rows (for testing)")
    ap.add_argument("--as-of", default=None, help="Snapshot date YYYY-MM-DD")
    args = ap.parse_args()

    csv_path = args.csv or find_default_csv()
    as_of = pd.Timestamp(args.as_of) if args.as_of else snapshot_date_from_name(csv_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {csv_path} (as of {as_of.date()}) ...")
    df = load_bulk(csv_path, nrows=args.nrows)
    print(f"Loaded {len(df):,} rows. Computing derived columns ...")
    df = add_derived(df, as_of)

    # Headline numbers.
    headline = {
        "companies": len(df),
        "dormant_rate": round(df["is_dormant"].mean(), 4),
        "distress_rate": round(df["is_distress"].mean(), 4),
        "accounts_overdue_rate": round(df["accounts_overdue"].mean(), 4),
        "has_charge_rate": round(df["has_charges"].mean(), 4),
        "satisfied_no_outstanding_rate": round(df["satisfied_no_outstanding"].mean(), 4),
    }

    by_sector = rate_table(df, "sector")
    by_size = rate_table(df, "size_band")
    df["age_bucket"] = age_buckets(df)
    by_age = rate_table(df, "age_bucket")

    # Sampling-bias demonstration: first N rows vs a random N rows.
    bias = pd.DataFrame()
    if len(df) > 50_000:
        first = df.head(50_000)
        rand = df.sample(50_000, random_state=42)
        bias = pd.DataFrame(
            {
                "first_50k": [
                    first["is_dormant"].mean(),
                    first["is_distress"].mean(),
                    (first["size_band"] == d.MID).mean(),
                ],
                "random_50k": [
                    rand["is_dormant"].mean(),
                    rand["is_distress"].mean(),
                    (rand["size_band"] == d.MID).mean(),
                ],
                "full": [
                    df["is_dormant"].mean(),
                    df["is_distress"].mean(),
                    (df["size_band"] == d.MID).mean(),
                ],
            },
            index=["dormant_rate", "distress_rate", "midcorp_share"],
        ).round(4)

    # Write the Markdown summary (committable; CSVs are gitignored).
    lines = [
        "# Attrition baseline EDA",
        "",
        f"Source: `{Path(csv_path).name}`  |  snapshot date: {as_of.date()}  "
        f"|  rows: {len(df):,}",
        "",
        "Cross-sectional base rates from a single snapshot. Transitions (the actual",
        "attrition events) require a second snapshot or the API.",
        "",
        "## Headline",
        "",
        df_to_md(pd.DataFrame([headline]).T.rename(columns={0: "value"}), "metric"),
        "",
        "## By target sector",
        "",
        df_to_md(by_sector, "sector"),
        "",
        "## By size band (account-category proxy)",
        "",
        df_to_md(by_size, "size_band"),
        "",
        "## By company age",
        "",
        df_to_md(by_age, "age_bucket"),
    ]
    if not bias.empty:
        lines += [
            "",
            "## Sampling bias check (first 50k vs random 50k vs full)",
            "",
            "Shows why the first-N-rows sample must not be used for attrition rates.",
            "",
            df_to_md(bias, "metric"),
        ]
    summary_path = OUT_DIR / "attrition_baseline_summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")

    # Also save the raw tables as CSV for further work (gitignored).
    by_sector.to_csv(OUT_DIR / "rates_by_sector.csv")
    by_size.to_csv(OUT_DIR / "rates_by_size.csv")
    by_age.to_csv(OUT_DIR / "rates_by_age.csv")

    # Figures.
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        ax = by_sector["dormant_rate"].plot(kind="barh", figsize=(9, 5),
                                            title="Dormancy rate by sector")
        ax.set_xlabel("dormant rate")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "dormancy_by_sector.png", dpi=120)
        plt.close()

        ax = by_sector["distress_rate"].plot(kind="barh", figsize=(9, 5),
                                             title="Distress rate by sector")
        ax.set_xlabel("distress rate")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "distress_by_sector.png", dpi=120)
        plt.close()
    except Exception as e:  # plotting is optional
        print(f"(Skipped figures: {e})")

    print(f"\nWrote {summary_path}")
    print("Headline:")
    for k, v in headline.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
