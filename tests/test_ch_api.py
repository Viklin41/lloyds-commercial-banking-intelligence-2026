"""Unit tests for the pure (no network) helpers in src/attrition/ch_api.py.

These cover charge parsing and the bank-switch detection heuristic, which is the
original contribution of the attrition workstream. Network code is not tested
here. Run from the repo root:

    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.attrition import ch_api as api


def _charge(created, satisfied, status, lenders, classification="Charge"):
    return {
        "created_on": created,
        "satisfied_on": satisfied,
        "status": status,
        "classification": {"description": classification},
        "persons_entitled": [{"name": n} for n in lenders],
    }


class TestParseCharges(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(api.parse_charges(None), [])
        self.assertEqual(api.parse_charges({}), [])
        self.assertEqual(api.parse_charges({"items": []}), [])

    def test_parse_fields(self):
        raw = {
            "items": [
                _charge("2020-01-01", None, "outstanding", ["Barclays Bank PLC"]),
            ]
        }
        parsed = api.parse_charges(raw)
        self.assertEqual(len(parsed), 1)
        c = parsed[0]
        self.assertEqual(c["created_on"], "2020-01-01")
        self.assertEqual(c["status"], "outstanding")
        self.assertEqual(c["classification"], "Charge")
        self.assertEqual(c["lenders"], ["Barclays Bank PLC"])


class TestSwitchDetection(unittest.TestCase):
    def test_no_switch_single_outstanding(self):
        charges = api.parse_charges(
            {"items": [_charge("2021-01-01", None, "outstanding", ["Lloyds Bank PLC"])]}
        )
        result = api.detect_switch(charges)
        self.assertFalse(result["switched"])

    def test_switch_lloyds_to_barclays(self):
        # Old Lloyds charge satisfied, new Barclays charge outstanding -> switch.
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2018-01-01", "2022-01-01", "satisfied", ["Lloyds Bank PLC"]),
                    _charge("2022-02-01", None, "outstanding", ["Barclays Bank PLC"]),
                ]
            }
        )
        result = api.detect_switch(charges)
        self.assertTrue(result["switched"])
        self.assertIn("LLOYDS", result["lost_lenders"])
        self.assertIn("BARCLAYS", result["gained_lenders"])

    def test_no_switch_same_lender_refinance(self):
        # Same lender pays off and re-lends: not a switch.
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2018-01-01", "2022-01-01", "satisfied", ["Lloyds Bank PLC"]),
                    _charge("2022-02-01", None, "outstanding", ["Lloyds Bank PLC."]),
                ]
            }
        )
        result = api.detect_switch(charges)
        self.assertFalse(result["switched"])

    def test_fully_satisfied_status(self):
        # The API returns 'fully-satisfied', not 'satisfied'. Both must count.
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2018-01-01", "2022-01-01", "fully-satisfied", ["Lloyds Bank PLC"]),
                    _charge("2022-02-01", None, "outstanding", ["Barclays Bank PLC"]),
                ]
            }
        )
        result = api.detect_switch(charges)
        self.assertTrue(result["switched"])
        self.assertIn("LLOYDS", result["lost_lenders"])
        self.assertIn("BARCLAYS", result["gained_lenders"])

    def test_bank_group_normalisation(self):
        # Subsidiaries of one group collapse to the group, so no false switch.
        self.assertEqual(api._normalise_lender("Hsbc UK Bank PLC"), "HSBC")
        self.assertEqual(api._normalise_lender("Hsbc Equipment Finance (UK) Limited"), "HSBC")
        self.assertEqual(api._normalise_lender("Bank of Scotland PLC"), "LLOYDS")
        self.assertEqual(api._normalise_lender("National Westminster Bank Plc"), "NATWEST")
        # Unknown / non-bank lender falls back to suffix-stripped name.
        self.assertEqual(api._normalise_lender("Acme Capital Partners LLP"), "ACME CAPITAL PARTNERS")

    def test_no_false_switch_within_group(self):
        # HSBC subsidiary satisfied, another HSBC subsidiary outstanding: not a switch.
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2018-01-01", "2022-01-01", "fully-satisfied", ["Hsbc UK Bank PLC"]),
                    _charge("2022-02-01", None, "outstanding", ["Hsbc Equipment Finance (UK) Limited"]),
                ]
            }
        )
        self.assertFalse(api.detect_switch(charges)["switched"])


class TestLenderType(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(api.lender_type("Lloyds Bank PLC"), api.LENDER_BANK)
        self.assertEqual(api.lender_type("Hsbc Equipment Finance (UK) Limited"), api.LENDER_BANK)
        self.assertEqual(
            api.lender_type("GLAS Trust Corporation Limited as security agent"),
            api.LENDER_AGENT,
        )
        self.assertEqual(
            api.lender_type("U.S. Bank Trustees Limited as Security Trustee"),
            api.LENDER_AGENT,
        )
        self.assertEqual(api.lender_type("Permira Credit Solutions II"), api.LENDER_OTHER)
        self.assertEqual(api.lender_type("Mrs Doreen Davidson"), api.LENDER_OTHER)

    def test_bank_switch_ignores_agents(self):
        # Lloyds cleared, then only a security agent holds the new charge:
        # not a bank switch (no new *bank* gained).
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2018-01-01", "2022-01-01", "fully-satisfied", ["Lloyds Bank PLC"]),
                    _charge("2022-02-01", None, "outstanding",
                            ["GLAS Trust Corporation Limited as security agent"]),
                ]
            }
        )
        self.assertFalse(api.detect_bank_switch(charges)["bank_switch"])

    def test_bank_switch_real(self):
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2018-01-01", "2022-01-01", "fully-satisfied", ["Barclays Bank PLC"]),
                    _charge("2022-02-01", None, "outstanding", ["Lloyds Bank PLC"]),
                ]
            }
        )
        result = api.detect_bank_switch(charges)
        self.assertTrue(result["bank_switch"])
        self.assertEqual(result["banks_lost"], ["BARCLAYS"])
        self.assertEqual(result["banks_gained"], ["LLOYDS"])
        self.assertFalse(result["lost_all_banks"])

    def test_lost_all_banks(self):
        # Cleared a bank charge, now no outstanding bank charge: lost the bank.
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2018-01-01", "2023-01-01", "fully-satisfied", ["Barclays Bank PLC"]),
                ]
            }
        )
        result = api.detect_bank_switch(charges)
        self.assertFalse(result["bank_switch"])
        self.assertTrue(result["lost_all_banks"])
        self.assertEqual(result["banks_lost"], ["BARCLAYS"])
        self.assertEqual(result["current_banks"], [])


class TestRecentBankLoss(unittest.TestCase):
    def test_bank_loss_date(self):
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2015-01-01", "2020-06-15", "fully-satisfied", ["Lloyds Bank PLC"]),
                    _charge("2012-01-01", "2018-03-01", "fully-satisfied", ["Barclays Bank PLC"]),
                ]
            }
        )
        # Most recent satisfied bank charge wins.
        self.assertEqual(api.bank_loss_date(charges), "2020-06-15")

    def test_recent_vs_old_loss(self):
        recent = api.parse_charges(
            {"items": [_charge("2015-01-01", "2025-01-01", "fully-satisfied", ["Lloyds Bank PLC"])]}
        )
        old = api.parse_charges(
            {"items": [_charge("2005-01-01", "2010-01-01", "fully-satisfied", ["Lloyds Bank PLC"])]}
        )
        self.assertTrue(api.recent_bank_loss(recent, "2026-06-01", months=24))
        self.assertFalse(api.recent_bank_loss(old, "2026-06-01", months=24))

    def test_lost_bank_within_window(self):
        charges = api.parse_charges(
            {"items": [_charge("2010-01-01", "2021-06-01", "fully-satisfied", ["Lloyds Bank PLC"])]}
        )
        # Event in 2022: the loss (2021-06) is within 24 months before it.
        self.assertTrue(api.lost_bank_within(charges, "2022-12-01", months=24))
        # Event in 2026: the loss is more than 24 months before it.
        self.assertFalse(api.lost_bank_within(charges, "2026-12-01", months=24))
        # Loss after the reference date does not count.
        self.assertFalse(api.lost_bank_within(charges, "2020-01-01", months=24))

    def test_no_recent_loss_if_still_banked(self):
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2015-01-01", "2025-01-01", "fully-satisfied", ["Lloyds Bank PLC"]),
                    _charge("2025-02-01", None, "outstanding", ["HSBC UK Bank PLC"]),
                ]
            }
        )
        # Still has an outstanding bank, so not "lost all banks".
        self.assertFalse(api.recent_bank_loss(charges, "2026-06-01", months=24))


class TestFilingHistory(unittest.TestCase):
    def _fh(self, items):
        return {"items": items}

    def test_parse(self):
        raw = self._fh(
            [{"date": "2024-01-01", "category": "Accounts", "type": "AA",
              "description": "accounts-with-accounts-type-dormant"}]
        )
        parsed = api.parse_filing_history(raw)
        self.assertEqual(parsed[0]["category"], "accounts")
        self.assertEqual(parsed[0]["type"], "AA")

    def test_extract_events(self):
        filings = api.parse_filing_history(
            self._fh(
                [
                    {"date": "2023-05-01", "category": "accounts", "type": "AA",
                     "description": "accounts-with-accounts-type-dormant"},
                    {"date": "2024-02-01", "category": "gazette", "type": "GAZ1",
                     "description": "first-gazette-notice-for-compulsory-strike-off"},
                    {"date": "2020-01-01", "category": "confirmation-statement", "type": "CS01",
                     "description": "confirmation-statement"},
                ]
            )
        )
        ev = api.extract_attrition_events(filings)
        self.assertTrue(ev["has_event"])
        self.assertEqual(ev["first_dormant_accounts"], "2023-05-01")
        self.assertEqual(ev["first_strike_off"], "2024-02-01")
        # Earliest distress event is the dormant filing in 2023.
        self.assertEqual(ev["first_event_type"], "dormant_accounts")
        self.assertEqual(ev["first_event_date"], "2023-05-01")

    def test_no_events(self):
        filings = api.parse_filing_history(
            self._fh(
                [{"date": "2024-01-01", "category": "confirmation-statement",
                  "type": "CS01", "description": "confirmation-statement"}]
            )
        )
        ev = api.extract_attrition_events(filings)
        self.assertFalse(ev["has_event"])
        self.assertIsNone(ev["first_event_date"])


class TestLenderTimeline(unittest.TestCase):
    def test_sorted_by_creation(self):
        charges = api.parse_charges(
            {
                "items": [
                    _charge("2022-02-01", None, "outstanding", ["Barclays Bank PLC"]),
                    _charge("2018-01-01", "2022-01-01", "satisfied", ["Lloyds Bank PLC"]),
                ]
            }
        )
        timeline = api.lender_timeline(charges)
        self.assertEqual(timeline[0][0], "2018-01-01")
        self.assertEqual(timeline[1][0], "2022-02-01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
