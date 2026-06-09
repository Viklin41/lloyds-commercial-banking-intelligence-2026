"""Build attrition labels from filing history and test the lead-lag with banks.

Why this script exists
----------------------
A single snapshot only shows a company's state today, not the moment it ran into
trouble. The filing history endpoint lists a company's filings over time, so we
can date the first sign of distress: a strike-off notice, an insolvency filing,
or a switch to dormant accounts. That gives us a real attrition event and a date.

We then bring in the charges data to ask the question that matters for the bank:
when a company gets into trouble, does it tend to lose its bank first? If the
bank loss usually comes before the distress event, then losing the bank is an
early warning sign the bank could act on.

What it does, for each company in the sample
--------------------------------------------
1. Pulls filing history and finds the first distress event and its date.
2. Pulls charges and works out when it last lost a bank.
3. Compares the two dates to see if the bank loss came first, and by how long.
4. Writes a per-company table and a plain-English summary, including:
   - how often firms with an event had lost all their banks, versus firms with
     no event (this is the predictive comparison)
   - among event firms that had lost a bank, how often the loss came first.

Run (from the repo root, with the venv and a .env that has CH_API_KEY). Build a
status-balanced sample first so there are enough distress and dormant cases:

    .venv/Scripts/python -m src.attrition.sample_companies --strata status --n 600 \
        --out data/processed/attrition_status_sample.csv
    .venv/Scripts/python -m src.attrition.build_attrition_labels \
        --sample data/processed/attrition_status_sample.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.attrition import ch_api as api
from src.attrition.run_bulk_eda import df_to_md

OUT_CSV = Path("data/processed/attrition_labels.csv")
OUT_MD = Path("reports/attrition/attrition_labels_summary.md")


def build(sample: pd.DataFrame, client: api.CompaniesHouseClient) -> pd.DataFrame:
    rows = []
    total = len(sample)
    for i, rec in enumerate(sample.itertuples(index=False), start=1):
        num = str(rec.CompanyNumber).strip()

        filings = api.parse_filing_history(client.get_filing_history(num))
        ev = api.extract_attrition_events(filings)

        charges = api.parse_charges(client.get_charges(num))
        bs = api.detect_bank_switch(charges)
        loss = api.bank_loss_date(charges)
        had_bank = (bs["n_past_banks"] + bs["n_current_banks"]) > 0

        # Did the bank loss come before the first distress event?
        loss_before = None
        lead_months = None
        if ev["has_event"] and loss:
            lead_months = api._months_between(ev["first_event_date"], loss)
            loss_before = lead_months is not None and lead_months > 0

        rows.append(
            {
                "CompanyNumber": num,
                "CompanyName": rec.CompanyName,
                "sector": rec.sector,
                "status_class": rec.status_class,
                "had_bank": had_bank,
                "lost_all_banks": bs["lost_all_banks"],
                "bank_loss_date": loss,
                "has_event": ev["has_event"],
                "first_event_type": ev["first_event_type"],
                "first_event_date": ev["first_event_date"],
                "bank_loss_before_event": loss_before,
                "lead_months": round(lead_months, 1) if lead_months is not None else None,
            }
        )
        if i % 50 == 0 or i == total:
            print(f"  {i}/{total} done")
    return pd.DataFrame(rows)


def summarise(res: pd.DataFrame) -> str:
    def pct(s):
        return round(100 * s.mean(), 1) if len(s) else 0.0

    # Event rate by class (sanity check: distressed firms should show more events).
    by_class = (
        res.groupby("status_class")
        .agg(n=("has_event", "size"), event_rate=("has_event", "mean"),
             lost_all_banks_rate=("lost_all_banks", "mean"))
    )
    by_class["event_rate"] = (100 * by_class["event_rate"]).round(1)
    by_class["lost_all_banks_rate"] = (100 * by_class["lost_all_banks_rate"]).round(1)

    # Predictive comparison: lost-all-banks among event vs no-event firms.
    event_firms = res[res["has_event"]]
    no_event = res[~res["has_event"]]
    predictive = pd.DataFrame(
        {
            "n": [len(event_firms), len(no_event)],
            "lost_all_banks_rate": [pct(event_firms["lost_all_banks"]),
                                    pct(no_event["lost_all_banks"])],
        },
        index=["had_distress_event", "no_event"],
    )

    # Lead-lag: among event firms that lost a bank, did the loss come first?
    lead_pool = res[(res["has_event"]) & (res["bank_loss_before_event"].notna())]
    if len(lead_pool):
        loss_first_rate = pct(lead_pool["bank_loss_before_event"])
        median_lead = round(
            lead_pool.loc[lead_pool["bank_loss_before_event"] == True, "lead_months"].median(), 1
        ) if (lead_pool["bank_loss_before_event"] == True).any() else None
    else:
        loss_first_rate = 0.0
        median_lead = None

    lines = [
        "# Attrition labels from filing history (sample)",
        "",
        f"Sample of {len(res):,} companies, balanced across outcome classes "
        "(healthy, distress, dormant), all holding charges.",
        "",
        "A distress event is the first strike-off notice, insolvency filing, or",
        "dormant accounts filing found in a company's filing history.",
        "",
        "## Event rate and bank loss by outcome class",
        "",
        df_to_md(by_class, "status_class"),
        "",
        "## Does losing the bank go with distress?",
        "",
        "Share of firms that have lost all their banks, split by whether the firm",
        "had a distress event. If the event group is higher, bank loss is",
        "associated with attrition.",
        "",
        df_to_md(predictive, "group"),
        "",
        "## Lead-lag: did the bank loss come first?",
        "",
        f"Among firms that had both a distress event and a datable bank loss "
        f"(n = {len(lead_pool)}):",
        "",
        f"- bank loss happened before the event: {loss_first_rate}% of them",
        f"- typical lead time when it did: "
        f"{median_lead if median_lead is not None else 'n/a'} months",
        "",
        "Note: cell counts can be small, so read these as indicative, not final.",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True, help="Path to a sample CSV")
    args = ap.parse_args()

    sample = pd.read_csv(args.sample, dtype={"CompanyNumber": str})
    print(f"Building labels for {len(sample):,} companies (2 API calls each) ...")

    client = api.CompaniesHouseClient()
    res = build(sample, client)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT_CSV, index=False)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(summarise(res), encoding="utf-8")

    print(f"\nWrote {OUT_CSV} and {OUT_MD}")
    print(f"Companies with a distress event: {int(res['has_event'].sum())} of {len(res)}")


if __name__ == "__main__":
    main()
