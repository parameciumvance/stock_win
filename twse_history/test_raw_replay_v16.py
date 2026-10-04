import json
import unittest
from pathlib import Path

import pandas as pd


ROOT = "twse_history/"
OUT = ROOT + "output_research_v16/"


class ReplayV16Tests(unittest.TestCase):
    def test_new_evidence_extends_only_pre_blocker_ledger(self):
        before = json.loads(Path(ROOT + "output_research_v15/summary.json").read_text())
        after = json.loads(Path(OUT + "summary.json").read_text())
        self.assertEqual(after["days_accounting_complete"], {
            "equal": 23, "momentum_60_skip5": 71,
            "logistic": 108, "hist_gradient_boosting": 105})
        self.assertEqual({m: b["symbol"] for m, b in after["first_unresolved"].items()},
                         {"equal": "6024", "momentum_60_skip5": "1786",
                          "logistic": "3094", "hist_gradient_boosting": "4133"})
        self.assertGreater(sum(after["days_accounting_complete"].values()),
                           sum(before["days_accounting_complete"].values()))
        self.assertFalse(after["stock_strategy_nav_produced"])
        audit = pd.read_csv(OUT + "held_action_audit.csv", dtype={"symbol": str})
        for day, method, symbol, status in [
            ("2025-02-07", "equal", "2547", "paid_subscription_waived_ratio_unverified"),
            ("2025-03-27", "momentum_60_skip5", "5388", "cash_receivable_recorded"),
            ("2025-06-13", "logistic", "6834", "cash_receivable_recorded"),
            ("2025-06-13", "hist_gradient_boosting", "6834", "cash_receivable_recorded")]:
            row = audit[(audit.date == day) & (audit.method == method) & (audit.symbol == symbol)]
            self.assertEqual(len(row), 1)
            self.assertEqual(row.iloc[0].status, status)
            self.assertTrue(row.iloc[0].valid_before_unresolved)
        row = audit[(audit.symbol == "2547") & (audit.method == "equal")].iloc[0]
        self.assertTrue(pd.isna(row.waived_subscription_shares))
        self.assertEqual(row.ratio_status, "issuer_aggregate_only")
        days = pd.read_csv(OUT + "daily_accounting_status.csv")
        self.assertTrue(days.loc[~days.accounting_complete, "nav_if_complete"].isna().all())

    def test_point_in_time_terms(self):
        cash = pd.read_csv(ROOT + "dividend_evidence_v16.csv", dtype={"symbol": str})
        rights = pd.read_csv(ROOT + "paid_rights_evidence_v16.csv", dtype={"symbol": str})
        self.assertFalse(cash[["symbol", "ex_date"]].duplicated().any())
        self.assertFalse(rights[["symbol", "ex_date"]].duplicated().any())
        for symbol, amount, payment in (("5388", 4.6, "2025-04-30"),
                                        ("6834", .5, "2025-07-11")):
            row = cash[cash.symbol == symbol].iloc[0]
            self.assertEqual(row.cash_per_share, amount)
            self.assertEqual(row.payment_date, payment)
            self.assertLess(row.announced_date, row.ex_date)
        row = rights[rights.symbol == "2547"].iloc[0]
        self.assertEqual(row.policy, "waive_paid_subscription")
        self.assertEqual(row.ratio_status, "issuer_aggregate_only")
        self.assertTrue(pd.isna(row.paid_subscription_shares_per_1000))
        self.assertEqual(row.issue_price_at_ex, 10.3)
        self.assertLess(row.price_announcement_date, row.ex_date)


if __name__ == "__main__":
    unittest.main()
