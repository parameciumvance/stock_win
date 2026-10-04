import json
import unittest

import pandas as pd


ROOT = "twse_history/"
OUT = ROOT + "output_research_v15/"


class ReplayV15Tests(unittest.TestCase):
    def test_four_blockers_resolved_with_only_pre_event_evidence(self):
        summary = json.loads(open(OUT + "summary.json").read())
        self.assertEqual(summary["days_accounting_complete"], {
            "equal": 19, "momentum_60_skip5": 52,
            "logistic": 104, "hist_gradient_boosting": 104})
        self.assertEqual({m: b["symbol"] for m, b in summary["first_unresolved"].items()},
                         {"equal": "2547", "momentum_60_skip5": "5388",
                          "logistic": "6834", "hist_gradient_boosting": "6834"})
        audit = pd.read_csv(OUT + "held_action_audit.csv", dtype={"symbol": str})
        for day, method, symbol, status in [
            ("2025-02-05", "equal", "2540", "paid_subscription_waived"),
            ("2025-03-20", "momentum_60_skip5", "3029", "cash_receivable_recorded"),
            ("2025-06-10", "logistic", "4722", "cash_receivable_recorded"),
            ("2025-06-13", "hist_gradient_boosting", "8467", "cash_receivable_recorded")]:
            row = audit[(audit.date == day) & (audit.method == method) & (audit.symbol == symbol)]
            self.assertEqual(len(row), 1)
            self.assertEqual(row.iloc[0].status, status)
            self.assertTrue(row.iloc[0].valid_before_unresolved)
        days = pd.read_csv(OUT + "daily_accounting_status.csv")
        self.assertTrue(days.loc[~days.accounting_complete, "nav_if_complete"].isna().all())

    def test_revised_rates_and_non_subscription_policy(self):
        cash = pd.read_csv(ROOT + "dividend_evidence_v15.csv", dtype={"symbol": str})
        rights = pd.read_csv(ROOT + "paid_rights_evidence_v15.csv", dtype={"symbol": str})
        revisions = pd.read_csv(ROOT + "dividend_revisions_v15.csv", dtype={"symbol": str})
        self.assertFalse(cash[["symbol", "ex_date"]].duplicated().any())
        for symbol, amount, pay in [("3029", 5., "2025-04-18"),
                                    ("4722", 1.39624577, "2025-07-11"),
                                    ("8467", 2.05788749, "2025-07-10")]:
            row = cash[cash.symbol == symbol].iloc[0]
            self.assertAlmostEqual(row.cash_per_share, amount, places=8)
            self.assertEqual(row.payment_date, pay)
            self.assertLess(row.announced_date, row.ex_date)
        for symbol in ("4722", "8467"):
            revision = revisions[revisions.symbol == symbol].iloc[0]
            row = cash[cash.symbol == symbol].iloc[0]
            self.assertAlmostEqual(revision.revised_cash_per_share, row.cash_per_share, places=8)
            self.assertLess(revision.revised_announced_date, row.ex_date)
        row = rights[rights.symbol == "2540"].iloc[0]
        self.assertEqual(row.policy, "waive_paid_subscription")
        self.assertAlmostEqual(row.paid_subscription_shares_per_1000, 60.00864364)
        self.assertEqual(row.issue_price_at_ex, 83)
        self.assertLess(row.price_announcement_date, row.ex_date)


if __name__ == "__main__":
    unittest.main()
