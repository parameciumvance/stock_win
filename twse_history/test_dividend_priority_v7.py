import unittest

import pandas as pd

from .dividend_priority_v7 import prioritize, validate_evidence


class DividendEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.day = pd.Timestamp("2025-06-24")
        self.actions = pd.DataFrame([dict(symbol="2303", effective_date=self.day,
            event_id="exrights:2303:20250624", event_type="exrights", event_subtype="息",
            official_previous_close=47., official_reference=44.14)])
        self.evidence = pd.DataFrame([dict(symbol="2303", ex_date=self.day,
            payment_date=pd.Timestamp("2025-07-16"), cash_per_share=2.85016443,
            announced_date=pd.Timestamp("2025-06-04"),
            amount_source_url="https://www.umc.com/", payment_source_url="https://mops.twse.com.tw/",
            evidence_status="issuer_amount_mops_republication_payment")])

    def test_issuer_cash_is_not_reference_gap_or_booked_nav(self):
        terms = validate_evidence(self.evidence, self.actions)
        self.assertAlmostEqual(terms.iloc[0].cash_minus_reference_gap, -.00983557)
        inventory = pd.DataFrame([dict(date=self.day, symbol="2303", method="equal",
            event_id="exrights:2303:20250624", event_type="exrights", event_subtype="息",
            adjusted_unit_equivalent_shares=.002)])
        exposure, ranked = prioritize(inventory, self.actions, terms)
        self.assertFalse(exposure.iloc[0].claim_in_portfolio_nav)
        self.assertAlmostEqual(exposure.iloc[0].priority_weight_not_payout, .002 * 2.86)
        self.assertEqual(ranked.iloc[0].affected_methods, 1)

    def test_mismatched_date_and_duplicate_fails(self):
        bad = self.evidence.copy()
        bad.loc[0, "ex_date"] = pd.Timestamp("2025-06-25")
        with self.assertRaisesRegex(ValueError, "match a pure official"):
            validate_evidence(bad, self.actions)
        with self.assertRaisesRegex(ValueError, "duplicate evidence"):
            validate_evidence(pd.concat([self.evidence] * 2), self.actions)

    def test_future_announcement_and_unknown_mixed_rights_fail(self):
        bad = self.evidence.copy()
        bad.loc[0, "announced_date"] = pd.Timestamp("2025-07-01")
        with self.assertRaisesRegex(ValueError, "Invalid cash amount or dividend dates"):
            validate_evidence(bad, self.actions)
        mixed = self.actions.copy()
        mixed["event_subtype"] = "權息"
        with self.assertRaisesRegex(ValueError, "match a pure official"):
            validate_evidence(self.evidence, mixed)


if __name__ == "__main__":
    unittest.main()
