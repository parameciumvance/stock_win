import json
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path("twse_history")
OUT = ROOT / "output_research_v17"


class ReplayV17Tests(unittest.TestCase):
    def test_four_events_advance_pre_blocker_ledger(self):
        old = json.loads((ROOT / "output_research_v16/summary.json").read_text())
        new = json.loads((OUT / "summary.json").read_text())
        self.assertEqual(new["days_accounting_complete"], {
            "equal": 23, "momentum_60_skip5": 93,
            "logistic": 108, "hist_gradient_boosting": 111})
        self.assertEqual({m: b["symbol"] for m, b in new["first_unresolved"].items()},
                         {"equal": "6806", "momentum_60_skip5": "1215",
                          "logistic": "1711", "hist_gradient_boosting": "2368"})
        self.assertEqual(sum(new["days_accounting_complete"].values()) -
                         sum(old["days_accounting_complete"].values()), 28)
        self.assertFalse(new["stock_strategy_nav_produced"])
        audit = pd.read_csv(OUT / "held_action_audit.csv", dtype={"symbol": str})
        for date, method, symbol, status in (
            ("2025-02-13", "equal", "6024", "paid_subscription_waived"),
            ("2025-04-25", "momentum_60_skip5", "1786", "cash_receivable_recorded"),
            ("2025-06-16", "hist_gradient_boosting", "4133", "cash_receivable_recorded"),
            ("2025-06-19", "logistic", "3094", "cash_receivable_recorded")):
            rows = audit[(audit.date == date) & (audit.method == method) & (audit.symbol == symbol)]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows.iloc[0].status, status)
            self.assertTrue(rows.iloc[0].valid_before_unresolved)
        days = pd.read_csv(OUT / "daily_accounting_status.csv")
        self.assertTrue(days.loc[~days.accounting_complete, "nav_if_complete"].isna().all())

    def test_revised_1786_rate_and_paid_6024_terms(self):
        cash = pd.read_csv(ROOT / "dividend_evidence_v17.csv", dtype={"symbol": str})
        revisions = pd.read_csv(ROOT / "dividend_revisions_v17.csv", dtype={"symbol": str})
        rights = pd.read_csv(ROOT / "paid_rights_evidence_v17.csv", dtype={"symbol": str})
        self.assertFalse(cash[["symbol", "ex_date"]].duplicated().any())
        self.assertFalse(rights[["symbol", "ex_date"]].duplicated().any())
        for symbol, amount, payment in (("1786", 3.23959430, "2025-05-29"),
                                        ("4133", .9, "2025-07-03"),
                                        ("3094", .17, "2025-07-14")):
            row = cash[cash.symbol == symbol].iloc[0]
            self.assertAlmostEqual(row.cash_per_share, amount, places=8)
            self.assertEqual(row.payment_date, payment)
            self.assertLess(row.announced_date, row.ex_date)
        revision = revisions[revisions.symbol == "1786"].iloc[0]
        self.assertAlmostEqual(revision.prior_cash_per_share, 3.25)
        self.assertAlmostEqual(revision.revised_cash_per_share, 3.23959430, places=8)
        self.assertLess(revision.revised_announced_date, revision.ex_date)
        row = rights[rights.symbol == "6024"].iloc[0]
        self.assertEqual(row.policy, "waive_paid_subscription")
        self.assertAlmostEqual(row.paid_subscription_shares_per_1000, 150.16329022)
        self.assertAlmostEqual(row.issue_price_at_ex, 52.8)
        self.assertLess(row.price_announcement_date, row.ex_date)


if __name__ == "__main__":
    unittest.main()
