"""Public-procurement contract wins, joined as-of each panel month.

Two sources, because UK procurement publishing split in half inside our panel
window. The Procurement Act 2023 took effect on **24 Feb 2025**: procurements
started on or after that date publish to **Find a Tender**, above *and* below
threshold, while **Contracts Finder** retains only the legacy pre-Act processes.
A Contracts Finder-only feature would therefore decay towards zero from Feb 2025
for purely regulatory reasons, and the out-of-time split (train early, test late)
would learn that calendar artefact and then find it missing in the test window.
So we harvest both and union them.

Both come from the Open Contracting Partnership data registry as bulk OCDS
``.jsonl.gz`` (one compiled release per line), not from the live APIs. The bulk
files remove the rate limiting, the cursor paging and the ``max_batches`` cap that
silently truncated NB05's harvest at 6,000 releases.

The two sources are shaped differently and need separate flatteners:

- **Contracts Finder** puts the money and the dates on ``awards[]``:
  ``awards[].datePublished`` and ``awards[].value.amount``.
- **Find a Tender** leaves ``awards[]`` almost empty (1% have a date) and carries
  the money and dates on ``contracts[]`` instead: ``contracts[].dateSigned`` and
  ``contracts[].value.amount``, linked back via ``contracts[].awardID``. Its
  publication date is the release-level ``date``.

Matching is on the ``GB-COH`` identifier only, never on company name. That is a
real Companies House number, so the join to the panel is exact. The price is
coverage: only ~32% of Contracts Finder supplier parties and ~11% of Find a
Tender ones carry a ``GB-COH`` identifier (the rest use internal ``GB-CFS`` /
``GB-FTS`` ids, or the new ``GB-PPON`` Central Digital Platform number). Every
unmatched supplier is dropped, so contract counts here are a *floor*, not a
census. That undercount is uniform noise; a name-based fallback would instead
invent contract wins on innocent companies, which is worse for a model that is
meant to rank prospects.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Iterator

import duckdb
import pandas as pd
import requests

from src.features import panel

# The registry redirects these to a versioned CDN path; requests follows it.
SOURCES = {
    "CF": "https://data.open-contracting.org/en/publication/128/download?name=full.jsonl.gz",
    "FTS": "https://data.open-contracting.org/en/publication/41/download?name=full.jsonl.gz",
}

RAW_DIR = Path("data/raw/contracts")
FLAT_PATH = Path("data/processed/contracts_flat.parquet")
ASOF_DIR = Path("data/processed/contracts_asof")

# The wider set, adding suppliers resolved by name+postcode. Same schema, same
# partitioning; consumers switch by pointing at this directory instead. See
# src/features/matching.py for how those rows are resolved and what they cost.
FLAT_EXT_PATH = Path("data/processed/contracts_flat_ext.parquet")
ASOF_EXT_DIR = Path("data/processed/contracts_asof_ext")

REQUEST_TIMEOUT = 60
CHUNK_BYTES = 1 << 20

ASOF_FEATURE_COLS = [
    "contracts_won_12m",
    "total_value_won_12m",
    "awards_with_value_12m",
    "months_since_last_award",
    "d_contracts_12m",
    "ever_won_contract",
    "first_award_in_12m",
]

# Counts and flags mean "none" when a company is absent from the sparse table, so
# consumers coalesce them to 0. months_since_last_award has no zero-equivalent -
# "never won anything" is a true NULL, exactly like months_since_last_new_charge.
ASOF_COALESCE_ZERO = [c for c in ASOF_FEATURE_COLS if c != "months_since_last_award"]


def download_bulk(dest_dir: Path = RAW_DIR) -> dict[str, str]:
    """Fetch both bulk OCDS files, skipping any already on disk.

    Written to a ``.part`` first and renamed on success, so an interrupted run
    never leaves a truncated file that looks complete.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for source, url in SOURCES.items():
        final_path = dest_dir / f"{source.lower()}_full.jsonl.gz"
        if final_path.exists() and final_path.stat().st_size > 0:
            results[source] = f"skipped ({final_path.stat().st_size / (1 << 20):,.0f} MB)"
            continue
        part_path = final_path.with_suffix(".gz.part")
        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
            r.raise_for_status()
            with open(part_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=CHUNK_BYTES):
                    if chunk:
                        fh.write(chunk)
        part_path.rename(final_path)
        results[source] = f"downloaded ({final_path.stat().st_size / (1 << 20):,.0f} MB)"
    return results


def iter_releases(path: Path) -> Iterator[dict]:
    """Yield one compiled release per line.

    Streamed rather than loaded, because the Contracts Finder file is 395 MB
    gzipped and several GB of parsed JSON.
    """
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


# A UK postcode sitting anywhere in a free-text address. Contracts Finder never
# fills address.postalCode but does put the postcode at the end of streetAddress,
# so this recovers it for ~87% of CF supplier parties.
POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)


def _supplier_index(release: dict) -> dict[str, dict]:
    """Party id -> what we know about that organisation.

    ``cn`` is the Companies House number when the party carries a ``GB-COH``
    identifier (normalised as in NB05: strip, upper, pad to 8) and ``None``
    otherwise. ``name`` and ``pc`` are kept for every party so an unmatched
    supplier can still be resolved later by :mod:`src.features.matching`.
    """
    out: dict[str, dict] = {}
    for party in release.get("parties") or []:
        ident = party.get("identifier") or {}
        cn = None
        if ident.get("scheme") == "GB-COH" and ident.get("id"):
            cn = str(ident["id"]).strip().upper().zfill(8)

        address = party.get("address") or {}
        pc = address.get("postalCode") or ""
        if not pc:
            found = POSTCODE_RE.search(address.get("streetAddress") or "")
            pc = found.group(0) if found else ""

        out[party.get("id")] = {
            "cn": cn,
            "name": party.get("name") or ident.get("legalName") or "",
            "pc": pc.upper().replace(" ", ""),
        }
    return out


def _date(value) -> str | None:
    """Trim an OCDS timestamp to a plain ISO date."""
    return str(value)[:10] if value else None


def _row(party, release, buyer, published, signed, amount, currency, n_suppliers):
    """One (supplier company, award) row in the shared cross-source schema.

    ``CompanyNumber`` is NULL for a supplier with no ``GB-COH`` identifier. Those
    rows are dropped on the strict path and resolved by name+postcode on the
    extended one, which is why ``match_name`` / ``match_pc`` travel with the row.
    """
    return {
        "CompanyNumber": party["cn"],
        "match_method": "coh" if party["cn"] else None,
        "match_name": party["name"],
        "match_pc": party["pc"],
        "company_name_src": party["name"],
        "ocid": release.get("ocid"),
        "buyer_name": buyer,
        "publication_date": published,
        "signature_date": signed,
        "award_value_gbp": amount,
        # A framework split across five suppliers is not five times its value to
        # each of them; the share is what a single company plausibly booked.
        "award_value_share_gbp": (amount / n_suppliers) if amount is not None else None,
        "num_suppliers_on_award": n_suppliers,
        "currency": currency,
    }


def flatten_cf(release: dict) -> list[dict]:
    """Contracts Finder: money and dates live on ``awards[]``."""
    parties = _supplier_index(release)
    if not parties:
        return []

    buyer = (release.get("buyer") or {}).get("name")
    release_date = _date(release.get("date"))
    rows = []
    for award in release.get("awards") or []:
        suppliers = award.get("suppliers") or []
        if not suppliers:
            continue
        value = award.get("value") or {}
        amount = value.get("amount")
        # datePublished is when the award notice became public, which is what a
        # model standing in month t could actually have known.
        published = _date(award.get("datePublished")) or release_date
        signed = _date(award.get("date"))
        for supplier in suppliers:
            party = parties.get(supplier.get("id"))
            if party is None:
                continue
            rows.append(_row(party, release, buyer, published,
                             signed, amount, value.get("currency"), len(suppliers)))
    return rows


def flatten_fts(release: dict) -> list[dict]:
    """Find a Tender: ``awards[]`` carries the suppliers, ``contracts[]`` the money.

    Only ~1% of FTS awards have a date or value of their own, so we walk
    ``contracts[]`` and link back to the award through ``contracts[].awardID`` to
    recover the supplier list. Publication is release-level; FTS has no
    ``datePublished`` on the award.
    """
    parties = _supplier_index(release)
    if not parties:
        return []

    buyer = (release.get("buyer") or {}).get("name")
    published = _date(release.get("date"))
    awards = {a.get("id"): a for a in (release.get("awards") or [])}

    rows = []
    for contract in release.get("contracts") or []:
        award = awards.get(contract.get("awardID"))
        if award is None:
            continue
        suppliers = award.get("suppliers") or []
        if not suppliers:
            continue
        value = contract.get("value") or award.get("value") or {}
        amount = value.get("amount")
        signed = _date(contract.get("dateSigned")) or _date(award.get("date"))
        for supplier in suppliers:
            party = parties.get(supplier.get("id"))
            if party is None:
                continue
            rows.append(_row(party, release, buyer, published,
                             signed, amount, value.get("currency"), len(suppliers)))
    return rows


FLATTENERS = {"CF": flatten_cf, "FTS": flatten_fts}


def flatten_sources(raw_dir: Path = RAW_DIR, keep_unmatched: bool = False) -> pd.DataFrame:
    """Flatten both bulk files to contract grain, before any de-duplication.

    With ``keep_unmatched`` the result also carries suppliers that published no
    ``GB-COH`` identifier, with a NULL ``CompanyNumber`` and their ``match_name`` /
    ``match_pc`` intact. :mod:`src.features.matching` resolves those; the strict
    path drops them here.
    """
    frames = []
    for source, flatten in FLATTENERS.items():
        path = raw_dir / f"{source.lower()}_full.jsonl.gz"
        df = pd.DataFrame([row for release in iter_releases(path) for row in flatten(release)])
        df["source"] = source
        if not keep_unmatched:
            df = df[df["CompanyNumber"].notna()]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def postprocess(flat: pd.DataFrame) -> pd.DataFrame:
    """De-duplicate, clean dates and money. Shared by the strict and extended paths.

    Deduplicated within source on ``(ocid, CompanyNumber)``: a compiled release can
    list the same company on more than one award of the same process, and we count
    contracting processes, not rows (NB05's ``nunique`` on ``ocid``, same idea).
    Then deduplicated *across* sources, because the pre-Act regime required
    above-threshold awards to be published on both services; see the comment below.
    """
    before = len(flat)
    flat = flat.drop_duplicates(["source", "ocid", "CompanyNumber"])
    print(f"  {before:,} rows -> {len(flat):,} after within-source dedup, "
          f"{flat['CompanyNumber'].nunique():,} companies", flush=True)

    flat = flat.copy()
    flat["publication_date"] = pd.to_datetime(flat["publication_date"], errors="coerce")
    flat["signature_date"] = pd.to_datetime(flat["signature_date"], errors="coerce")

    # Under the pre-Act regime an above-threshold award had to be published on BOTH
    # Find a Tender and Contracts Finder, so the union double-counts exactly the
    # larger contracts. The two platforms mint different ocids for the same process
    # (ocds-b5fd17-* vs ocds-h6vhtk-*), so ocid cannot detect it; we match on
    # (company, exact value, publication month) instead and keep the earliest
    # publication, which is also the correct as-of answer for "when did this become
    # public". Measured: 2,633 cross-source collisions against a ~1% within-source
    # collision rate, so the key is specific enough to be worth it. Awards with no
    # stated value cannot be matched this way and are left alone.
    # Only collapse *across* sources: two distinct same-value awards inside one
    # platform are real and must both count, so within-source multiplicity is kept.
    priced = flat[flat["award_value_gbp"].notna()].copy()
    priced["_key"] = list(zip(priced["CompanyNumber"], priced["award_value_gbp"],
                              priced["publication_date"].dt.to_period("M")))
    per_key = priced.groupby("_key")["source"].nunique()
    both = set(per_key[per_key > 1].index)

    contested = priced[priced["_key"].isin(both)]
    # Whichever platform published it first is the one we believe.
    winner = contested.sort_values("publication_date").groupby("_key")["source"].first()
    drop_idx = contested.index[
        contested["source"] != contested["_key"].map(winner)
    ]
    print(f"  dropping {len(drop_idx):,} cross-published duplicate awards "
          f"across {len(both):,} contracts")
    flat = flat.drop(index=drop_idx)

    # 35 of ~176k awards are priced in USD/EUR/CNY. Too few to be worth an FX table
    # and too wrong to sum as if they were sterling, so the award still counts
    # towards contracts_won but contributes nothing to the value columns.
    non_gbp = flat["award_value_gbp"].notna() & flat["currency"].ne("GBP")
    if non_gbp.any():
        print(f"  blanking value on {non_gbp.sum():,} non-GBP awards "
              f"({sorted(flat.loc[non_gbp, 'currency'].unique())})")
        flat.loc[non_gbp, ["award_value_gbp", "award_value_share_gbp"]] = None

    # A row we cannot date cannot be placed in time, so it cannot be used as-of.
    undated = flat["publication_date"].isna().sum()
    if undated:
        print(f"  dropping {undated:,} rows with no usable publication date")
        flat = flat[flat["publication_date"].notna()]

    return flat


def build_flat(raw_dir: Path = RAW_DIR, out_path: Path = FLAT_PATH) -> pd.DataFrame:
    """The strict path: ``GB-COH`` matched suppliers only, written to ``out_path``."""
    flat = postprocess(flatten_sources(raw_dir, keep_unmatched=False))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    flat.to_parquet(out_path, index=False)
    return flat


# Same calendar-spine idea as panel.DELTA_SQL: build every contract-winning company
# against every month, then gate on publication_date so month t only ever sees what
# was public by the end of month t. The 12m windows are calendar windows, so the
# missing June 2025 snapshot is irrelevant here - this table is built from event
# dates, not from register snapshots, and has no hole to step over.
ASOF_SQL = """
WITH months AS (
    -- cast back to DATE so the partition directories match the panel layout
    -- exactly (snapshot_date=2026-07-01, not a URL-encoded timestamp)
    SELECT (DATE '{first_month}' + INTERVAL (n) MONTH)::DATE AS snapshot_date
    FROM range(0, DATEDIFF('month', DATE '{first_month}', DATE '{last_month}') + 1) t(n)
),
awards AS (
    SELECT "CompanyNumber", ocid, publication_date,
           award_value_share_gbp AS value_gbp
    FROM read_parquet('{flat_path}')
),
companies AS (SELECT DISTINCT "CompanyNumber" FROM awards),
spine AS (SELECT * FROM companies CROSS JOIN months),
agg AS (
    SELECT s."CompanyNumber",
           s.snapshot_date,
           last_day(s.snapshot_date) AS month_end,
           count(DISTINCT CASE WHEN a.publication_date
                     > last_day(s.snapshot_date) - INTERVAL 12 MONTH
                   THEN a.ocid END)                                  AS contracts_won_12m,
           sum(CASE WHEN a.publication_date
                     > last_day(s.snapshot_date) - INTERVAL 12 MONTH
                   THEN a.value_gbp END)                             AS total_value_won_12m,
           count(CASE WHEN a.publication_date
                     > last_day(s.snapshot_date) - INTERVAL 12 MONTH
                    AND a.value_gbp IS NOT NULL
                   THEN 1 END)                                       AS awards_with_value_12m,
           count(DISTINCT CASE WHEN a.publication_date
                     > last_day(s.snapshot_date) - INTERVAL 24 MONTH
                    AND a.publication_date
                     <= last_day(s.snapshot_date) - INTERVAL 12 MONTH
                   THEN a.ocid END)                                  AS contracts_won_prev_12m,
           max(a.publication_date)                                   AS last_award_date,
           min(a.publication_date)                                   AS first_award_date
    FROM spine s
    JOIN awards a
      ON a."CompanyNumber" = s."CompanyNumber"
     -- the as-of gate: nothing published after month end is visible at month end
     AND a.publication_date <= last_day(s.snapshot_date)
    GROUP BY 1, 2
)
SELECT "CompanyNumber",
       snapshot_date,
       contracts_won_12m,
       coalesce(total_value_won_12m, 0.0)                 AS total_value_won_12m,
       awards_with_value_12m,
       DATEDIFF('month', last_award_date, month_end)      AS months_since_last_award,
       contracts_won_12m - contracts_won_prev_12m         AS d_contracts_12m,
       TRUE                                               AS ever_won_contract,
       first_award_date > month_end - INTERVAL 12 MONTH   AS first_award_in_12m
FROM agg
"""


def harvest_watermark(flat_path: Path = FLAT_PATH) -> pd.Timestamp:
    """Last month for which the union is actually complete.

    The two registry files are refreshed on different cadences (Contracts Finder
    monthly, Find a Tender weekly) and were retrieved at different times, so one
    source always runs out before the other. Any month past the *earlier* of the
    two last-publication dates is censored: contract counts there fall not because
    companies stopped winning work but because we stopped observing it.

    Treat months after this watermark as unusable for contract features, the same
    way the panel treats a missing snapshot month.
    """
    flat = pd.read_parquet(flat_path, columns=["source", "publication_date"])
    return flat.groupby("source")["publication_date"].max().min()


def build_asof(
    flat_path: Path = FLAT_PATH,
    out_dir: Path = ASOF_DIR,
    threads: int | None = None,
) -> int:
    """Aggregate the flat contract table as-of every panel month.

    Only companies with at least one award published by that month are written, so
    this stays in the tens of thousands of rows per month rather than 1.5M.
    Consumers ``LEFT JOIN`` it onto the delta table and coalesce.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    if threads:
        con.execute(f"PRAGMA threads={threads}")

    sql = ASOF_SQL.format(
        flat_path=flat_path.as_posix(),
        first_month=panel.FIRST_MONTH,
        last_month=panel.LAST_MONTH,
    )
    con.execute(
        f"""
        COPY ({sql}) TO '{out_dir.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD,
         PARTITION_BY (snapshot_date), OVERWRITE_OR_IGNORE)
        """
    )
    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{(out_dir / '**' / '*.parquet').as_posix()}')"
    ).fetchone()[0]
    con.close()
    return n
