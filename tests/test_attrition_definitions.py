"""Unit tests for src/attrition/definitions.py.

Uses only the standard library (unittest) so it runs without pandas or any
install. Run from the repo root:

    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

# Make src importable when running from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.attrition import definitions as d


class TestStatus(unittest.TestCase):
    def test_active_is_healthy(self):
        self.assertEqual(d.classify_status("Active"), d.HEALTHY)

    def test_strike_off(self):
        self.assertEqual(
            d.classify_status("Active - Proposal to Strike off"), d.STRIKE_OFF
        )

    def test_insolvency_variants(self):
        for s in [
            "Liquidation",
            "In Administration",
            "In Administration/Administrative Receiver",
            "ADMINISTRATION ORDER",
            "Voluntary Arrangement",
            "Live but Receiver Manager on at least one charge",
        ]:
            self.assertEqual(d.classify_status(s), d.INSOLVENCY, msg=s)

    def test_dissolved(self):
        self.assertEqual(d.classify_status("Dissolved"), d.DISSOLVED)

    def test_missing_and_unknown(self):
        self.assertEqual(d.classify_status(None), d.STATUS_OTHER)
        self.assertEqual(d.classify_status(""), d.STATUS_OTHER)
        self.assertEqual(d.classify_status("Something new"), d.STATUS_OTHER)

    def test_distress_flag(self):
        self.assertTrue(d.is_distress_status("Liquidation"))
        self.assertTrue(d.is_distress_status("Active - Proposal to Strike off"))
        self.assertFalse(d.is_distress_status("Active"))
        self.assertFalse(d.is_distress_status(None))


class TestAccounts(unittest.TestCase):
    def test_dormant(self):
        self.assertEqual(d.classify_accounts_activity("DORMANT"), d.DORMANT)

    def test_no_accounts(self):
        self.assertEqual(d.classify_accounts_activity("NO ACCOUNTS FILED"), d.NO_ACCOUNTS)
        self.assertEqual(d.classify_accounts_activity(None), d.NO_ACCOUNTS)
        self.assertEqual(d.classify_accounts_activity(""), d.NO_ACCOUNTS)

    def test_trading(self):
        for c in ["MICRO ENTITY", "SMALL", "TOTAL EXEMPTION FULL", "FULL", "MEDIUM"]:
            self.assertEqual(d.classify_accounts_activity(c), d.TRADING, msg=c)

    def test_size_band(self):
        self.assertEqual(d.size_band("MICRO ENTITY"), d.BB)
        self.assertEqual(d.size_band("SMALL"), d.SME)
        self.assertEqual(d.size_band("MEDIUM"), d.MID)
        self.assertEqual(d.size_band("FULL"), d.LARGE)
        self.assertEqual(d.size_band("GROUP"), d.LARGE)
        self.assertEqual(d.size_band("DORMANT"), d.SIZE_UNKNOWN)
        self.assertEqual(d.size_band(None), d.SIZE_UNKNOWN)


class TestSic(unittest.TestCase):
    def test_extract_code(self):
        self.assertEqual(
            d.extract_sic_code("62020 - Information technology consultancy"), "62020"
        )
        self.assertEqual(d.extract_sic_code("None Supplied"), None)
        self.assertEqual(d.extract_sic_code(None), None)

    def test_division_and_section(self):
        self.assertEqual(d.sic_division("62020"), 62)
        self.assertEqual(d.sic_section("62020"), "J")   # information & communication
        self.assertEqual(d.sic_section("10110"), "C")   # manufacturing
        self.assertEqual(d.sic_section("01110"), "A")   # agriculture
        self.assertEqual(d.sic_section("47110"), "G")   # retail
        self.assertEqual(d.sic_section("68209"), "L")   # real estate
        self.assertEqual(d.sic_section("86101"), "Q")   # health
        self.assertEqual(d.sic_section("85100"), "P")   # education
        self.assertEqual(d.sic_section("84110"), "O")   # public admin
        self.assertEqual(d.sic_section("70229"), "M")   # management consultancy
        self.assertEqual(d.sic_section("98000"), "T")   # households (not a target)

    def test_target_sector_basic(self):
        self.assertEqual(
            d.target_sector(["10110 - Processing of meat"]), d.SECTOR_MANUFACTURING
        )
        self.assertEqual(
            d.target_sector(["68209 - Other letting of own real estate"]),
            d.SECTOR_REAL_ESTATE,
        )
        self.assertEqual(
            d.target_sector(["86101 - Hospital activities"]), d.SECTOR_HEALTHCARE
        )
        self.assertEqual(
            d.target_sector(["70229 - Management consultancy"]), d.SECTOR_TECH_PROF
        )

    def test_fast_growth_override(self):
        # Even if primary SIC is professional, a fast-growth code wins.
        self.assertEqual(
            d.target_sector(
                ["70229 - Management consultancy", "62012 - Software development"]
            ),
            d.SECTOR_FAST_GROWTH,
        )

    def test_charity_by_company_type(self):
        # A charity company type routes to Public sector / charities regardless of
        # its activity SIC, because the legal form drives its financial and
        # attrition behaviour (grant dependence) more than the activity does.
        self.assertEqual(
            d.target_sector(
                ["88990 - Other social work"],
                company_category="Charitable Incorporated Organisation",
            ),
            d.SECTOR_PUBLIC,
        )
        self.assertEqual(
            d.target_sector(
                ["94990 - Activities of other membership organisations"],
                company_category="Community Interest Company",
            ),
            d.SECTOR_PUBLIC,
        )
        # But a fast-growth SIC still overrides charity type (rule order 1 > 2).
        self.assertEqual(
            d.target_sector(
                ["62012 - Software development"],
                company_category="Community Interest Company",
            ),
            d.SECTOR_FAST_GROWTH,
        )

    def test_other(self):
        self.assertEqual(
            d.target_sector(["98000 - Residents property management"]), d.SECTOR_OTHER
        )
        self.assertEqual(d.target_sector([None, "None Supplied"]), d.SECTOR_OTHER)


class TestOverdue(unittest.TestCase):
    def test_days_overdue(self):
        self.assertEqual(d.days_overdue("01/01/2026", "11/01/2026"), 10)
        self.assertEqual(d.days_overdue("11/01/2026", "01/01/2026"), -10)

    def test_iso_format(self):
        self.assertEqual(d.days_overdue("2026-01-01", "2026-01-11"), 10)

    def test_missing(self):
        self.assertIsNone(d.days_overdue(None, "01/01/2026"))
        self.assertIsNone(d.days_overdue("01/01/2026", None))
        self.assertIsNone(d.days_overdue("not a date", "01/01/2026"))

    def test_is_overdue_grace(self):
        self.assertTrue(d.is_overdue("01/01/2026", "20/01/2026", grace_days=7))
        self.assertFalse(d.is_overdue("01/01/2026", "05/01/2026", grace_days=7))


if __name__ == "__main__":
    unittest.main(verbosity=2)
