import json
import unittest

import pandas as pd


ROOT = "twse_history/"
OUT = ROOT + "output_research_v13/"


class EvidenceReplayV13Tests(unittest.TestCase):
    def test_new_events_are_accounted_before_first_blocker(self):
        summary = json.loads(open(OUT + "summary.json").read())
        self.assertEqual(summary["days_accounting_complete"], {
            "equal": 13, "momentum_60_skip5": 45,
            "logistic": 89, "hist_gradient_boosting": 103})
        self.assertEqual({m: b["symbol"] for m, b in summary["first_unresolved"].items()},
                         {"equal": "1707", "momentum_60_skip5": "9802",
                          "logistic": "6658", "hist_gradient_boosting": "1760"})
        audit = pd.read_csv(OUT + "held_action_audit.csv", dtype={"symbol": str})
        expected = [("2025-01-14", "equal", "2543", "paid_subscription_waived"),
                    ("2025-03-17", "momentum_60_skip5", "2630", "cash_receivable_recorded"),
                    ("2025-03-28", "hist_gradient_boosting", "6835", "cash_receivable_recorded"),
                    ("2025-04-18", "logistic", "6756", "cash_receivable_recorded")]
        for date, method, symbol, status in expected:
            row = audit[(audit.date == date) & (audit.method == method) & (audit.symbol == symbol)]
            self.assertEqual(len(row), 1)
            self.assertEqual(row.iloc[0].status, status)
            self.assertTrue(row.iloc[0].valid_before_unresolved)
        rights = audit[(audit.date == "2025-01-14") & (audit.method == "equal") & (audit.symbol == "2543")].iloc[0]
        self.assertTrue(pd.isna(rights.cash_receivable))
        self.assertGreater(rights.waived_subscription_shares, 0)

    def test_announcement_order_revised_rate_and_payment_day(self):
        cash = pd.read_csv(ROOT + "dividend_evidence_v13.csv", dtype={"symbol": str})
        rights = pd.read_csv(ROOT + "paid_rights_evidence_v13.csv", dtype={"symbol": str})
        self.assertFalse(cash[["symbol", "ex_date"]].duplicated().any())
        self.assertFalse(rights[["symbol", "ex_date"]].duplicated().any())
        for symbol, rate, announced, pay in [
            ("2630", .62056, "2025-02-26", "2025-04-15"),
            ("6835", 2., "2025-03-04", "2025-04-21"),
            ("6756", 1.79956203, "2025-03-28", "2025-05-22")]:
            row = cash[cash.symbol == symbol].iloc[0]
            self.assertAlmostEqual(row.cash_per_share, rate, places=8)
            self.assertEqual(row.announced_date, announced)
            self.assertLess(announced, row.ex_date)
            self.assertEqual(row.payment_date, pay)
        self.assertEqual(rights[rights.symbol == "2543"].iloc[0].issue_price_at_ex, 58.1)
        days = pd.read_csv(OUT + "daily_accounting_status.csv")
        for date, method in [("2025-04-21", "hist_gradient_boosting"),
                             ("2025-05-22", "hist_gradient_boosting")]:
            row = days[(days.date == date) & (days.method == method)].iloc[0]
            self.assertTrue(row.accounting_complete)
            self.assertGreater(row.cash_received_today, 0)
        blocked = days[(days.date == "2025-04-15") & (days.method == "momentum_60_skip5")].iloc[0]
        self.assertFalse(blocked.accounting_complete)
        self.assertTrue(pd.isna(blocked.cash_received_today))


if __name__ == "__main__":
    unittest.main()
