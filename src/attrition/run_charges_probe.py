"""Probe the charges endpoint for a few companies and report bank-switch signals.

This is a quick way to validate the switch-detection idea on real data once a
CH_API_KEY is in place. It pulls charges for the company numbers you pass, runs
the switch heuristic, and prints a per-company summary.

Run (from repo root, with the venv and a .env containing CH_API_KEY):
    .venv/Scripts/python -m src.attrition.run_charges_probe 00445790 02065. ...

Tip for finding companies that have charges: filter the bulk file for
Mortgages.NumMortSatisfied > 0 AND Mortgages.NumMortOutstanding > 0, then pass a
sample of those CompanyNumbers here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.attrition import ch_api as api

OUT = Path("reports/attrition/charges_probe.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("company_numbers", nargs="+", help="Companies House numbers")
    args = ap.parse_args()

    client = api.CompaniesHouseClient()  # raises if no key
    results = []
    for num in args.company_numbers:
        num = num.strip()
        raw = client.get_charges(num)
        charges = api.parse_charges(raw)
        switch = api.detect_switch(charges)
        profile = client.get_company(num) or {}
        row = {
            "company_number": num,
            "company_name": profile.get("company_name"),
            "company_status": profile.get("company_status"),
            "n_charges": len(charges),
            "n_outstanding": sum(1 for c in charges if api.is_outstanding(c)),
            "n_satisfied": sum(1 for c in charges if api.is_satisfied(c)),
            **switch,
        }
        results.append(row)
        flag = "  <-- SWITCH SIGNAL" if switch["switched"] else ""
        print(
            f"{num} {row['company_name'] or ''}: "
            f"{row['n_charges']} charges "
            f"(out {row['n_outstanding']}, sat {row['n_satisfied']}){flag}"
        )
        if switch["switched"]:
            print(
                f"    lost {switch['lost_lenders']} -> gained {switch['gained_lenders']}"
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
