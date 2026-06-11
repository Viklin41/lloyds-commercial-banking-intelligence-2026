"""Unit tests for the pure helpers in src/data_collection/gdelt_news.py.

These cover name cleaning and article parsing. Network code is not tested here.
Run from the repo root:

    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_collection import gdelt_news as g


class TestCleanName(unittest.TestCase):
    def test_strips_suffixes_and_punctuation(self):
        self.assertEqual(g.clean_company_name("ACME WIDGETS LIMITED"), "acme widgets")
        self.assertEqual(g.clean_company_name("Greggs PLC"), "greggs")
        self.assertEqual(g.clean_company_name("J.D. Wetherspoon Ltd."), "j d wetherspoon")

    def test_drops_filler_words(self):
        # "the", "group", "holdings", "uk" are dropped as low-value tokens.
        self.assertEqual(g.clean_company_name("The Cities Group UK"), "cities")

    def test_handles_empty(self):
        self.assertEqual(g.clean_company_name(""), "")
        self.assertEqual(g.clean_company_name(None), "")


class TestParseArtlist(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(g.parse_artlist(None), [])
        self.assertEqual(g.parse_artlist({}), [])
        self.assertEqual(g.parse_artlist({"articles": []}), [])

    def test_parse_fields(self):
        payload = {
            "articles": [
                {"title": "Greggs opens new bakery", "url": "http://x.com/a",
                 "domain": "bbc.co.uk", "seendate": "20240101T120000Z",
                 "language": "English", "sourcecountry": "United Kingdom"},
            ]
        }
        parsed = g.parse_artlist(payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["domain"], "bbc.co.uk")
        self.assertEqual(parsed[0]["title"], "Greggs opens new bakery")

    def test_summarise(self):
        articles = [
            {"title": "A", "domain": "bbc.co.uk"},
            {"title": "B", "domain": "bbc.co.uk"},
            {"title": "C", "domain": "ft.com"},
        ]
        s = g.summarise_articles(articles)
        self.assertEqual(s["n_articles"], 3)
        self.assertTrue(s["has_news"])
        # bbc appears most, so it should be first in top_domains.
        self.assertTrue(s["top_domains"].startswith("bbc.co.uk"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
