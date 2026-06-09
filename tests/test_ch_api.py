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
        self.assertIn("LLOYDS BANK", result["lost_lenders"])
        self.assertIn("BARCLAYS BANK", result["gained_lenders"])

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

    def test_lender_normalisation(self):
        self.assertEqual(api._normalise_lender("Barclays Bank PLC"), "BARCLAYS BANK")
        self.assertEqual(api._normalise_lender("LLOYDS BANK PLC."), "LLOYDS BANK")
        self.assertEqual(
            api._normalise_lender("HSBC UK Bank Limited"), "HSBC UK BANK"
        )


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
