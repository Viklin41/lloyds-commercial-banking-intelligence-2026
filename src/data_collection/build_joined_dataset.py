"""Join the static company dataset to news coverage from GDELT.

This is the first joined dataset the meeting asked for: company information from
Companies House on one side, news coverage on the other, linked by company name.
For each company in the sample it adds the number of articles, whether there was
any coverage, the top news domains, and a few sample headlines. It then writes a
short set of descriptive statistics.

Expect sparse coverage. Most BB and SME firms get little or no national news, so
many rows will show zero articles. That is a real result about how far public
news data reaches down the size scale, not a bug.

Run (from the repo root, with the venv), after building the sample:
    .venv/Scripts/python -m src.data_collection.build_static_dataset --sample 100
    .venv/Scripts/python -m src.data_collection.build_joined_dataset
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.data_collection.gdelt_news import GdeltNews

SAMPLE_IN = Path("data/processed/static_dataset_sample.csv")
OUT_CSV = Path("data/processed/joined_company_news.csv")
OUT_MD = Path("reports/news/joined_dataset_summary.md")


def join_news(sample: pd.DataFrame, client: GdeltNews, timespan: str) -> pd.DataFrame:
    rows = []
    total = len(sample)
    for i, rec in enumerate(sample.itertuples(index=False), start=1):
        news = client.company_news(rec.CompanyName, timespan=timespan)
        rows.append(
            {
                "CompanyNumber": str(rec.CompanyNumber),
                "CompanyName": rec.CompanyName,
                "sector": rec.sector,
                "size_band": rec.size_band,
                "query_used": news["query_used"],
                "n_articles": news["n_articles"],
                "has_news": news["has_news"],
                "top_domains": news["top_domains"],
                "sample_titles": news["sample_titles"],
            }
        )
        if i % 20 == 0 or i == total:
            print(f"  {i}/{total} done")
    return pd.DataFrame(rows)


def summarise(joined: pd.DataFrame) -> str:
    n = len(joined)
    with_news = int(joined["has_news"].sum())
    by_sector = (
        joined.groupby("sector")
        .agg(n=("has_news", "size"), with_news=("has_news", "sum"),
             mean_articles=("n_articles", "mean"))
    )
    by_sector["pct_with_news"] = (100 * by_sector["with_news"] / by_sector["n"]).round(1)
    by_sector["mean_articles"] = by_sector["mean_articles"].round(2)

    from src.attrition.run_bulk_eda import df_to_md

    lines = [
        "# First joined dataset: companies and news (sample)",
        "",
        f"Sample of {n} companies from the agreed static dataset (three sectors, "
        "BB and SME), linked to GDELT news coverage by company name.",
        "",
        "## Coverage",
        "",
        f"- companies with any news in the period: {with_news} of {n} "
        f"({round(100 * with_news / n, 1) if n else 0}%)",
        f"- companies with no news at all: {n - with_news}",
        f"- most articles for a single company: {int(joined['n_articles'].max()) if n else 0}",
        "",
        "## By sector",
        "",
        df_to_md(by_sector[["n", "with_news", "pct_with_news", "mean_articles"]], "sector"),
        "",
        "## Reading this",
        "",
        "Coverage is sparse because BB and SME firms rarely make the news, and",
        "name matching is imperfect. This supports the wider project point that",
        "media signals are strongest for larger firms, and that linking by name",
        "needs careful entity resolution.",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(SAMPLE_IN), help="Static sample CSV")
    ap.add_argument("--timespan", default="12months", help="GDELT lookback window")
    args = ap.parse_args()

    sample = pd.read_csv(args.sample, dtype={"CompanyNumber": str})
    print(f"Linking {len(sample):,} companies to GDELT news ...")

    client = GdeltNews()
    joined = join_news(sample, client, args.timespan)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    joined.to_csv(OUT_CSV, index=False)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(summarise(joined), encoding="utf-8")

    print(f"\nWrote {OUT_CSV} and {OUT_MD}")
    print(f"Companies with any news: {int(joined['has_news'].sum())} of {len(joined)}")


if __name__ == "__main__":
    main()
