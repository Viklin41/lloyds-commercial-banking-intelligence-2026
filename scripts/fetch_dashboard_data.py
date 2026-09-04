#!/usr/bin/env python3
"""
Download the dashboard data bundle and unpack it into the tree serve.py expects.

The bundle is 217 MB across 15 files and is not in git. It is published as a
release asset on the repository, and this script is the only step between a
fresh clone and a working dashboard:

    git clone <repo> && cd lloyds-commercial-banking-intelligence-2026
    pip install -r requirements.txt
    python scripts/fetch_dashboard_data.py
    python dashboard/serve.py

Two layouts are involved and they are not the same, which is the reason this
script exists rather than a plain unzip. The bundle groups files by what they
are (spine, sources, models, market, config). serve.py reads them from where
the pipeline wrote them (processed/, processed/sam_sc/data/, market_analysis/).
LAYOUT below is the translation, and it is the authoritative record of it.

If you already have the zip on disk, skip the download:

    python scripts/fetch_dashboard_data.py --zip ~/Downloads/Data_Dashboard.zip

Nothing is overwritten unless --force is passed, so re-running is cheap.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "Viklin41/lloyds-commercial-banking-intelligence-2026"
TAG = "data-2026-07"
ASSET = "Data_Dashboard.zip"
URL = f"https://github.com/{REPO}/releases/download/{TAG}/{ASSET}"

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"

# bundle path (inside the zip, under Data_Dashboard/)  ->  destination under data/
LAYOUT = {
    "spine/dashboard_bulk_gazette_2026-07.parquet":   "processed",
    "spine/identity_2026-08-01.parquet":              "processed",
    "sources/nb10_gazette_notices_thru_2026-07.csv":  "processed",
    "sources/nb14_news_signals_2026-06-30.csv":       "processed",
    "models/shortlist_reasons_2026-07.parquet":       "processed",
    "sources/news_coverage_summary.csv":              "processed/sam_sc/data",
    "sources/ipo_trademarks_company_features.csv":    "processed/sam_sc/data",
    "sources/ipo_trademarks_events.csv":              "processed/sam_sc/data",
    "sources/land_registry_company_features.csv":     "processed/sam_sc/data",
    "sources/land_registry_events.csv":               "processed/sam_sc/data",
    "sources/ukri_grants_company_features.csv":       "processed/sam_sc/data",
    "market/mi_league_2026-07.csv":                   "market_analysis",
    "market/mi_sector_borrowing_2026-07.csv":         "market_analysis",
    "market/mi_lapsed_destinations_2026-07.csv":      "market_analysis",
}

# store_meta.json is in the bundle's config/ folder but is deliberately not
# unpacked: dashboard/store_meta.json is the copy serve.py reads, it is tracked
# in git, and the two were verified byte-identical. Unpacking a second copy is
# how two versions of the same file start to disagree.


def human(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{n / 1024:.0f} KB"


def download(dest: Path) -> None:
    print(f"downloading {URL}")
    try:
        with urllib.request.urlopen(URL) as r, dest.open("wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100 * done / total
                    print(f"\r  {human(done)} of {human(total)}  ({pct:.0f}%)",
                          end="", flush=True)
            print()
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"\nDownload failed: HTTP {e.code}.\n\n"
            f"Check that release '{TAG}' exists on {REPO} and carries the asset\n"
            f"'{ASSET}'. If you already have the zip, pass it directly:\n"
            f"    python scripts/fetch_dashboard_data.py --zip PATH\n")


def unpack(zip_path: Path, force: bool) -> None:
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        # The zip may or may not carry the Data_Dashboard/ top-level folder,
        # depending on how it was made. Detect rather than assume.
        prefix = "Data_Dashboard/" if any(
            n.startswith("Data_Dashboard/") for n in names) else ""

        missing = [m for m in LAYOUT if prefix + m not in names]
        if missing:
            raise SystemExit(
                "\nThis zip is not the expected bundle. Missing:\n  "
                + "\n  ".join(missing) + "\n")

        written = skipped = 0
        for member, subdir in LAYOUT.items():
            out_dir = DATA / subdir
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / Path(member).name
            if out.exists() and not force:
                print(f"  skip   {out.relative_to(REPO_ROOT)} (exists)")
                skipped += 1
                continue
            with z.open(prefix + member) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            print(f"  wrote  {out.relative_to(REPO_ROOT)}  {human(out.stat().st_size)}")
            written += 1

    print(f"\n{written} written, {skipped} already present, into {DATA}")
    if skipped and not force:
        print("Pass --force to overwrite the files that were skipped.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", type=Path, default=None, metavar="PATH",
                    help="use a local copy of the bundle instead of downloading it")
    ap.add_argument("--force", action="store_true",
                    help="overwrite files that are already unpacked")
    a = ap.parse_args()

    if a.zip:
        if not a.zip.exists():
            raise SystemExit(f"No such file: {a.zip}")
        unpack(a.zip, a.force)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / ASSET
            download(zip_path)
            unpack(zip_path, a.force)

    spine = DATA / "processed" / "dashboard_bulk_gazette_2026-07.parquet"
    if spine.exists():
        print("\nReady. Start the dashboard with:\n    python dashboard/serve.py")
    else:
        print("\nThe company parquet is still missing; the dashboard will not start.",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
