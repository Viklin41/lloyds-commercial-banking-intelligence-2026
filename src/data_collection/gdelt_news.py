"""Retrieve news coverage for companies from GDELT.

Why GDELT
---------
GDELT is a free global news index. It needs no API key and goes back years, which
suits a student project better than NewsAPI (whose free tier only covers the last
month). We use the GDELT Doc 2.0 API to count and sample articles that mention a
company by name.

Honest limitation, stated up front
----------------------------------
News is matched on the company name, which is messy. Small firms rarely appear in
the news at all, and common names cause false matches. So for BB and SME firms we
expect most companies to return little or no coverage. That sparsity is itself a
finding worth reporting, and it is the entity-resolution problem the project flags.

The pure helpers (clean_company_name, parse_artlist) take plain inputs, so they
are unit tested without any network.

Run as a quick check:
    .venv/Scripts/python -m src.data_collection.gdelt_news "Greggs"
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Legal suffixes we strip so the name matches news text better.
_SUFFIXES = (
    "limited", "ltd", "plc", "llp", "llp.", "ltd.", "plc.",
    "company", "co", "uk", "holdings", "group", "the",
)


def clean_company_name(name: str) -> str:
    """Turn a registered name into a cleaner phrase for a news search.

    Drops punctuation and common legal suffixes, so 'ACME WIDGETS LIMITED'
    becomes 'acme widgets'. Returns a lower-case string.
    """
    n = (name or "").lower()
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    words = [w for w in n.split() if w and w not in _SUFFIXES]
    return " ".join(words).strip()


def parse_artlist(payload: "dict | None") -> list:
    """Flatten a GDELT artlist JSON payload into simple article dicts."""
    if not payload:
        return []
    out = []
    for a in payload.get("articles", []):
        out.append(
            {
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "domain": a.get("domain", ""),
                "seendate": a.get("seendate", ""),
                "language": a.get("language", ""),
                "country": a.get("sourcecountry", ""),
            }
        )
    return out


def summarise_articles(articles: list) -> dict:
    """Counts and a few samples from a list of parsed articles."""
    domains = {}
    for a in articles:
        dom = a.get("domain", "")
        if dom:
            domains[dom] = domains.get(dom, 0) + 1
    top_domains = sorted(domains, key=domains.get, reverse=True)[:3]
    titles = [a["title"] for a in articles if a.get("title")][:3]
    return {
        "n_articles": len(articles),
        "has_news": len(articles) > 0,
        "top_domains": "; ".join(top_domains),
        "sample_titles": " || ".join(titles),
    }


class GdeltNews:
    """Polite GDELT Doc client with on-disk caching."""

    # GDELT asks for no more than one request every 5 seconds, so we space calls
    # at least that far apart.
    def __init__(self, cache_dir: str = "data/raw/gdelt_cache", min_interval: float = 5.5):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last_call = 0.0
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "lloyds-student-project/1.0"})
        return self._session

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()

    def _cache_path(self, key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", key).strip("_")[:120]
        return self.cache_dir / f"{safe}.json"

    def query_articles(self, query: str, timespan: str = "12months",
                       maxrecords: int = 75) -> "dict | None":
        """Call the GDELT Doc API in artlist mode and return parsed JSON.

        Returns None on a failure or an empty/garbled response, so callers can
        treat that as no coverage rather than crashing.
        """
        cache_file = self._cache_path(f"{query}_{timespan}_{maxrecords}")
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(maxrecords),
            "timespan": timespan,
            "sort": "datedesc",
        }
        session = self._get_session()
        for attempt in range(4):
            self._throttle()
            try:
                resp = session.get(DOC_API, params=params, timeout=30)
            except Exception:
                time.sleep(6)
                continue
            if resp.status_code == 429:
                # Too fast: wait out the rate limit and retry.
                time.sleep(6)
                continue
            if resp.status_code == 200 and resp.text.strip().startswith("{"):
                try:
                    data = resp.json()
                except ValueError:
                    data = {}
                cache_file.write_text(json.dumps(data), encoding="utf-8")
                return data
            # A 200 with non-JSON text means no results or a soft error.
            if resp.status_code == 200:
                cache_file.write_text("{}", encoding="utf-8")
                return {}
            time.sleep(6)
        return None

    def company_news(self, name: str, timespan: str = "12months",
                     maxrecords: int = 75) -> dict:
        """Get a news summary for one company, searching its cleaned name."""
        cleaned = clean_company_name(name)
        if len(cleaned) < 3:
            # Name too short or generic to search safely.
            return {"query_used": cleaned, "n_articles": 0, "has_news": False,
                    "top_domains": "", "sample_titles": ""}
        query = f'"{cleaned}"'  # quoted phrase to reduce false matches
        payload = self.query_articles(query, timespan, maxrecords)
        summary = summarise_articles(parse_artlist(payload))
        summary["query_used"] = query
        return summary


def main():
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "Greggs"
    client = GdeltNews()
    print(json.dumps(client.company_news(name), indent=2))


if __name__ == "__main__":
    main()
