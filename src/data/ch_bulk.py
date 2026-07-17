"""Discover, download and extract the monthly Companies House bulk snapshots.

Companies House publishes one big CSV of every UK company each month as
``BasicCompanyDataAsOneFile-YYYY-MM-DD.zip``. The public download page only ever
links the *current* month, but the older ZIPs stay on the server, unlisted and
reachable by direct URL. This is a rolling window, so the oldest files age out
over time; we grab the whole visible history now and keep the zips permanently.

Two quirks this module has to cope with:

- **The snapshot day is not reliably the 1st.** Most months land on ``-01`` but
  some are ``-04``, ``-07``, ``-02`` etc. We probe days 01..15 per month and take
  the first one that exists.
- **Some months are genuinely missing** (e.g. June 2025). Probing simply returns
  no hit for that month; downstream deltas handle the hole on a calendar spine.

Everything lands in ``data/raw/snapshots/`` which sits under the already fully
gitignored ``data/`` tree, so nothing here is ever pushed to the online repo.
"""

from __future__ import annotations

import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = "https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-{date}.zip"

# The 33 months of history that exist as of Jul 2026 (Oct 2023 -> Jul 2026).
# June 2025 is a real hole on the CH server, so it is deliberately absent here.
MANIFEST = [
    "2023-10-04", "2023-11-01", "2023-12-04", "2024-01-01", "2024-02-07",
    "2024-03-01", "2024-04-01", "2024-05-01", "2024-06-01", "2024-07-01",
    "2024-08-01", "2024-09-01", "2024-10-01", "2024-11-01", "2024-12-01",
    "2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01",
    "2025-07-01", "2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01",
    "2025-12-01", "2026-01-01", "2026-02-01", "2026-03-02", "2026-04-01",
    "2026-05-01", "2026-06-01", "2026-07-01",
]

# Where the zips live (kept) and where CSVs are extracted (deleted after use).
SNAPSHOT_DIR = Path("data/raw/snapshots")

# Politeness / robustness knobs.
PROBE_DAYS = range(1, 16)            # days 01..15
REQUEST_TIMEOUT = 60                 # seconds for a HEAD/GET to respond
CHUNK_BYTES = 1 << 20               # 1 MiB streaming chunks
MAX_RETRIES = 3
PARALLEL = 4                         # simultaneous downloads


def _url_exists(url: str) -> bool:
    """True if a HEAD request comes back 200. Used to probe candidate dates."""
    try:
        r = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return r.status_code == 200
    except requests.RequestException:
        return False


def probe_snapshot_dates(months: list[str] | None = None) -> list[str]:
    """Find the real snapshot date for each month by trying days 01..15.

    ``months`` is a list of ``"YYYY-MM"`` strings. Returns the list of full
    ``"YYYY-MM-DD"`` dates that resolved to a live URL (first hit per month wins).
    Pass ``None`` to just return the verified :data:`MANIFEST` without hitting the
    network, which is what the notebook does day-to-day.
    """
    if months is None:
        return list(MANIFEST)

    found: list[str] = []
    for ym in months:
        for day in PROBE_DAYS:
            date = f"{ym}-{day:02d}"
            if _url_exists(BASE_URL.format(date=date)):
                found.append(date)
                break
    return found


def _download_one(date: str, dest_dir: Path) -> tuple[str, str]:
    """Download a single snapshot zip. Returns ``(date, status)``.

    Resumable in the coarse sense: if the fully-downloaded zip is already on disk
    we skip it. Writes to a ``.part`` file first and only renames on success, so an
    interrupted run never leaves a half-file that looks complete.
    """
    url = BASE_URL.format(date=date)
    final_path = dest_dir / f"BasicCompanyDataAsOneFile-{date}.zip"
    part_path = final_path.with_suffix(".zip.part")

    if final_path.exists() and final_path.stat().st_size > 0:
        return date, "skipped (already present)"

    last_err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
                r.raise_for_status()
                with open(part_path, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=CHUNK_BYTES):
                        if chunk:
                            fh.write(chunk)
            part_path.rename(final_path)
            mb = final_path.stat().st_size / (1 << 20)
            return date, f"downloaded ({mb:,.0f} MB)"
        except requests.RequestException as exc:
            last_err = str(exc)
            part_path.unlink(missing_ok=True)
    return date, f"FAILED after {MAX_RETRIES} tries: {last_err}"


def download_snapshots(
    dates: list[str] | None = None,
    dest_dir: Path = SNAPSHOT_DIR,
    parallel: int = PARALLEL,
) -> dict[str, str]:
    """Download every snapshot in ``dates`` (defaults to the full manifest), 4x
    parallel, skipping any zip already on disk. Returns ``{date: status}``.
    """
    dates = list(MANIFEST) if dates is None else dates
    dest_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_download_one, d, dest_dir): d for d in dates}
        for fut in as_completed(futures):
            date, status = fut.result()
            results[date] = status
            print(f"  {date}  {status}", flush=True)
    return results


def extract_snapshot(date: str, dest_dir: Path = SNAPSHOT_DIR) -> Path:
    """Extract the CSV out of one snapshot zip and return its path.

    The zip holds a single ``BasicCompanyDataAsOneFile-YYYY-MM-DD.csv``. Callers
    (the panel builder) delete that CSV again once the parquet partition is
    written; the zip is what we keep.
    """
    zip_path = dest_dir / f"BasicCompanyDataAsOneFile-{date}.zip"
    with zipfile.ZipFile(zip_path) as zf:
        member = zf.namelist()[0]
        zf.extract(member, path=dest_dir)
    return dest_dir / member


def snapshot_status(dest_dir: Path = SNAPSHOT_DIR) -> dict[str, bool]:
    """Which manifest dates are already downloaded. Handy for the notebook."""
    return {
        date: (dest_dir / f"BasicCompanyDataAsOneFile-{date}.zip").exists()
        for date in MANIFEST
    }
