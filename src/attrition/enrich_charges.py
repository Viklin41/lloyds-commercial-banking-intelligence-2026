"""Run the charges API over the sample and measure real bank-attrition signals.

Why this script exists
----------------------
The bulk file only tells us how many charges a company has, not who the lender
is or whether the relationship ended. This script calls the Companies House
charges endpoint for each company in the sample, works out the bank picture
over time, and turns it into plain rates we can report.

For every company it records:
  - how many distinct banks it owes now, and how many it has paid off
  - lost_all_banks: it used to have a bank charge but now has none outstanding
  - reduced_banks: it dropped at least one bank
  - bank_switch: it dropped one bank and picked up a different one

Then it crosses these against whether the company is in distress (strike-off,
insolvency, or dissolved), because "lost all banks" can mean two very different
things: a struggling firm losing its bank, or a healthy firm that simply repaid
its loan and is now debt free. Splitting by distress separates the two.

Results are cached per company (see ch_api), so re-running is fast and does not
spend the API rate limit again.

Run (from the repo root, with the venv and a .env that has CH_API_KEY):
    .venv/Scripts/python -m src.attrition.enrich_charges
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.attrition import ch_api as api
from src.attrition.run_bulk_eda import df_to_md

SAMPLE_PATH = Path("data/processed/attrition_sample.csv")
OUT_CSV = Path("data/processed/attrition_charges_enriched.csv")
OUT_MD = Path("reports/attrition/attrition_charges_summary.md")


def enrich(sample: pd.DataFrame, client: api.CompaniesHouseClient, as_of: str,
           recent_months: int = 24) -> pd.DataFrame:
    """Call the charges API for each company and add the bank-attrition fields."""
    rows = []
    total = len(sample)
    for i, rec in enumerate(sample.itertuples(index=False), start=1):
        num = str(rec.CompanyNumber).strip()
        charges = api.parse_charges(client.get_charges(num))
        bs = api.detect_bank_switch(charges)
        rows.append(
            {
                "CompanyNumber": num,
                "CompanyName": rec.CompanyName,
                "sector": rec.sector,
                "size_band": rec.size_band,
                "attrition_status": rec.attrition_status,
                "is_distress": rec.is_distress,
                "n_charges": len(charges),
                "n_current_banks": bs["n_current_banks"],
                "n_past_banks": bs["n_past_banks"],
                "bank_switch": bs["bank_switch"],
                "lost_all_banks": bs["lost_all_banks"],
                "reduced_banks": bs["reduced_banks"],
                # When the company last lost a bank, and whether that is recent.
                "bank_loss_date": api.bank_loss_date(charges),
                "recent_bank_loss": api.recent_bank_loss(charges, as_of, recent_months),
                "current_banks": "; ".join(bs["current_banks"]),
                "banks_lost": "; ".join(bs["banks_lost"]),
                "banks_gained": "; ".join(bs["banks_gained"]),
            }
        )
        if i % 50 == 0 or i == total:
            print(f"  {i}/{total} done")
    return pd.DataFrame(rows)


def summarise(res: pd.DataFrame) -> str:
    """Build a plain-English Markdown summary of the rates."""
    # Only companies that have any bank relationship in their charge history can
    # show a bank loss or switch, so most rates are measured against that group.
    has_bank = res[(res["n_current_banks"] > 0) | (res["n_past_banks"] > 0)]
    n_bank = len(has_bank)

    def pct(series):
        return round(100 * series.mean(), 1) if len(series) else 0.0

    headline = {
        "companies probed": len(res),
        "with any recognised bank charge": n_bank,
        "lost_all_banks (% of bank firms)": pct(has_bank["lost_all_banks"]),
        "recent_bank_loss last 24m (% of bank firms)": pct(has_bank["recent_bank_loss"]),
        "reduced_banks (% of bank firms)": pct(has_bank["reduced_banks"]),
        "bank_switch (% of bank firms)": pct(has_bank["bank_switch"]),
    }

    # The key cross-tab: lost_all_banks split by distress, to separate genuine
    # attrition from healthy repayment.
    if n_bank:
        ct = (
            has_bank.groupby("is_distress")["lost_all_banks"]
            .agg(["size", "mean"])
            .rename(columns={"size": "n", "mean": "lost_all_banks_rate"})
        )
        ct["lost_all_banks_rate"] = (100 * ct["lost_all_banks_rate"]).round(1)
        by_size = (
            has_bank.groupby("size_band")["lost_all_banks"]
            .agg(["size", "mean"])
            .rename(columns={"size": "n", "mean": "lost_all_banks_rate"})
        )
        by_size["lost_all_banks_rate"] = (100 * by_size["lost_all_banks_rate"]).round(1)
        by_sector = (
            has_bank.groupby("sector")["lost_all_banks"]
            .agg(["size", "mean"])
            .rename(columns={"size": "n", "mean": "lost_all_banks_rate"})
            .sort_values("n", ascending=False)
        )
        by_sector["lost_all_banks_rate"] = (100 * by_sector["lost_all_banks_rate"]).round(1)
    else:
        ct = by_size = by_sector = pd.DataFrame()

    lines = [
        "# Attrition signals from charges (sample)",
        "",
        f"Sample of {len(res):,} companies (SME, Midcorp, Large) that hold charges, "
        "across the Lloyds target sectors.",
        "",
        "Rates below are measured against the companies that have at least one",
        "recognised bank charge, because only those can show a bank being lost or",
        "changed. Security agents, trustees, private equity funds, landlords, and",
        "individuals are not counted as banks.",
        "",
        "## Headline",
        "",
        df_to_md(pd.DataFrame([headline]).T.rename(columns={0: "value"}), "metric"),
        "",
        "## Lost all banks, split by distress",
        "",
        "This is the important one. A firm in distress that has lost its bank is a",
        "real attrition case. A healthy firm that lost its bank has most likely just",
        "repaid its loan, which is a different story for the bank.",
        "",
        df_to_md(ct, "is_distress") if not ct.empty else "(no bank firms)",
        "",
        "## Lost all banks by size band",
        "",
        df_to_md(by_size, "size_band") if not by_size.empty else "(no bank firms)",
        "",
        "## Lost all banks by sector",
        "",
        df_to_md(by_sector, "sector") if not by_sector.empty else "(no bank firms)",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(SAMPLE_PATH), help="Path to the sample CSV")
    ap.add_argument("--as-of", default="2026-06-01", help="Reference date YYYY-MM-DD")
    ap.add_argument("--recent-months", type=int, default=24,
                    help="Window for a 'recent' bank loss")
    args = ap.parse_args()

    sample = pd.read_csv(args.sample, dtype={"CompanyNumber": str})
    print(f"Probing charges for {len(sample):,} companies ...")

    client = api.CompaniesHouseClient()  # raises if no key
    res = enrich(sample, client, args.as_of, args.recent_months)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT_CSV, index=False)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(summarise(res), encoding="utf-8")

    print(f"\nWrote {OUT_CSV} and {OUT_MD}")
    has_bank = res[(res["n_current_banks"] > 0) | (res["n_past_banks"] > 0)]
    print(f"Companies with a recognised bank charge: {len(has_bank)} of {len(res)}")
    if len(has_bank):
        print(f"  lost_all_banks: {round(100*has_bank['lost_all_banks'].mean(),1)}%")
        print(f"  reduced_banks:  {round(100*has_bank['reduced_banks'].mean(),1)}%")
        print(f"  bank_switch:    {round(100*has_bank['bank_switch'].mean(),1)}%")


if __name__ == "__main__":
    main()
