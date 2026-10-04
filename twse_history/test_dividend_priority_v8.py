import unittest

import pandas as pd

from .dividend_priority_v8 import validate_revisions


class DividendRevisionTests(unittest.TestCase):
    def setUp(self):
        self.evidence = pd.DataFrame([dict(symbol="3002", ex_date=pd.Timestamp("2025-09-17"),
            announced_date=pd.Timestamp("2025-09-02"), cash_per_share=.69781688,
            amount_source_url="https://example.com/revised", evidence_status="mops_republication_amended")])
        self.revisions = pd.DataFrame([dict(symbol="3002", ex_date=pd.Timestamp("2025-09-17"),
            prior_cash_per_share=.69876859, revised_cash_per_share=.69781688,
            revised_announced_date=pd.Timestamp("2025-09-02"),
            prior_source_url="https://example.com/initial",
            revised_source_url="https://example.com/revised", reason="treasury shares")])

    def test_amended_terms_must_be_public_before_ex_date(self):
        self.assertEqual(len(validate_revisions(self.evidence, self.revisions)), 1)
        bad = self.revisions.copy()
        bad.loc[0, "revised_announced_date"] = pd.Timestamp("2025-09-18")
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_revisions(self.evidence, bad)

    def test_old_rate_or_untraced_rate_cannot_replace_revision(self):
        bad = self.evidence.copy()
        bad.loc[0, "cash_per_share"] = .69876859
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_revisions(bad, self.revisions)
        bad = self.evidence.copy()
        bad.loc[0, "amount_source_url"] = "https://example.com/initial"
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_revisions(bad, self.revisions)


if __name__ == "__main__":
    unittest.main()
