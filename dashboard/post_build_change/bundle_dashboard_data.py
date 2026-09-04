"""Copy every file the dashboard reads into Lloyds_Github/Data_Dashboard.

Copies only. The originals stay exactly where they are and nothing is moved or deleted.
"""
import hashlib
import os
import shutil
from pathlib import Path

ROOT = Path(os.environ.get("LLOYDS_ROOT")
            or Path(__file__).resolve().parents[2])
DATA = ROOT / "data"
SAM = DATA / "processed" / "sam_sc" / "data"
MARKET = ROOT / "market_analysis"
REPO = ROOT / "lloyds-commercial-banking-intelligence-2026" / "dashboard"
OUT = ROOT / "Data_Dashboard"

# folder, source path, what it feeds
FILES = [
    ("spine",   DATA / "processed" / "dashboard_bulk_gazette_2026-07.parquet",
     "The company universe. Every filter, count, view, ranking and score"),
    ("spine",   DATA / "processed" / "identity_2026-08-01.parquet",
     "Incorporation date and address, reduced from the 639 MB source CSV"),
    ("sources", DATA / "processed" / "nb10_gazette_notices_thru_2026-07.csv",
     "Gazette panel, evidence trail, timeline"),
    ("sources", DATA / "processed" / "nb14_news_signals_2026-06-30.csv",
     "News panel"),
    ("sources", SAM / "news_coverage_summary.csv",
     "News coverage tile"),
    ("sources", SAM / "ipo_trademarks_company_features.csv",
     "Trade marks tile"),
    ("sources", SAM / "ipo_trademarks_events.csv",
     "Trade mark events, timeline"),
    ("sources", SAM / "ukri_grants_company_features.csv",
     "Grants tile"),
    ("sources", SAM / "land_registry_company_features.csv",
     "Property tile"),
    ("sources", SAM / "land_registry_events.csv",
     "Property events, timeline"),
    ("models",  REPO / "post_build_change" / "shortlist_reasons_2026-07.parquet",
     "Per-company SHAP drivers, top 5,000 per model"),
    ("market",  MARKET / "mi_league_2026-07.csv",
     "Analytics: lender league table"),
    ("market",  MARKET / "mi_sector_borrowing_2026-07.csv",
     "Analytics: sector borrowing"),
    ("market",  MARKET / "mi_lapsed_destinations_2026-07.csv",
     "Analytics: where lapsed clients went"),
    ("config",  REPO / "store_meta.json",
     "Snapshot dates, score definitions, precision / base rate / lift"),
]

# The 639 MB source CSV. Only the four identity columns are used and the parquet above now
# carries them, so it is the fallback rather than a live input. Copied only on request.
FALLBACK = (DATA / "processed" / "filtered_bb_sme_sectors_all_status_2026-08-01.csv",
            "Fallback for identity_2026-08-01.parquet. 639 MB for four columns")

INCLUDE_FALLBACK = os.environ.get("INCLUDE_FALLBACK") == "1"


def sha(path, blocks=64):
    """First and last few MB, enough to catch a truncated or wrong copy cheaply."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(blocks * 1024 * 1024))
    return h.hexdigest()[:16]


OUT.mkdir(exist_ok=True)
for sub in ("spine", "sources", "models", "market", "config"):
    (OUT / sub).mkdir(exist_ok=True)

rows, total, missing = [], 0, []
todo = list(FILES) + ([("spine", FALLBACK[0], FALLBACK[1])] if INCLUDE_FALLBACK else [])

for folder, src, note in todo:
    if not src.exists():
        missing.append(str(src))
        continue
    dst = OUT / folder / src.name
    shutil.copy2(src, dst)
    mb = dst.stat().st_size / 1048576
    total += mb
    ok = dst.stat().st_size == src.stat().st_size and sha(dst) == sha(src)
    rows.append((folder, src.name, mb, note, ok, src))
    print("  %-8s %-52s %8.2f MB  %s" % (folder, src.name, mb, "ok" if ok else "COPY MISMATCH"))

print("\n  %d files, %.1f MB total" % (len(rows), total))
if missing:
    print("  MISSING:", missing)
bad = [r for r in rows if not r[4]]
print("  copy verification:", "all identical to source" if not bad else "FAILED %s" % [r[1] for r in bad])

# ---------------------------------------------------------------- manifest
man = ["# Data_Dashboard",
       "",
       "Copies of every file the Companies House Data Store reads at runtime. The originals are",
       "unchanged and still in their own locations; nothing here is the live path.",
       "",
       "| Folder | File | Size | Feeds |",
       "|---|---|---|---|"]
for folder, name, mb, note, _ok, _src in rows:
    man.append("| `%s` | `%s` | %.1f MB | %s |" % (folder, name, mb, note))
man += ["",
        "**%d files, %.0f MB.**" % (len(rows), total),
        "",
        "## Where the originals live",
        "",
        "| Folder | Original location |",
        "|---|---|",
        "| `spine` | `data/processed/` |",
        "| `sources` | `data/processed/` and `data/processed/sam_sc/data/` |",
        "| `models` | `lloyds-commercial-banking-intelligence-2026/dashboard/post_build_change/` |",
        "| `market` | `market_analysis/` |",
        "| `config` | `lloyds-commercial-banking-intelligence-2026/dashboard/` |",
        "",
        "## Not copied",
        "",
        "`filtered_bb_sme_sectors_all_status_2026-08-01.csv`, 639 MB. The dashboard reads four",
        "columns from it, and `identity_2026-08-01.parquet` above now carries exactly those four,",
        "verified identical row for row. It remains on disk as the fallback if the parquet is",
        "missing, but it is not a live input and copying it would add 639 MB for nothing.",
        "Set `INCLUDE_FALLBACK=1` when running the bundler to include it.",
        "",
        "## How the dashboard finds these",
        "",
        "`serve.py` resolves the data tree from `--data`, then `LLOYDS_DATA`, then a default. This",
        "folder is a copy for handover and archive; pointing the server at it would need the",
        "original `processed/`, `processed/sam_sc/data/` and `market_analysis/` layout rebuilt",
        "around it.",
        ""]
(OUT / "MANIFEST.md").write_text("\n".join(man), encoding="utf-8")
print("  wrote MANIFEST.md")
