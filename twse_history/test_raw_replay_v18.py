import json
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path("twse_history")
OUT = ROOT / "output_research_v18"


class ReplayV18Tests(unittest.TestCase):
    def test_four_actions_advance_valid_ledger(self):
        old = json.loads((ROOT / "output_research_v17/summary.json").read_text())
        new = json.loads((OUT / "summary.json").read_text())
        self.assertEqual(new["days_accounting_complete"], {
            "equal": 24, "momentum_60_skip5": 104,
            "logistic": 110, "hist_gradient_boosting": 114})
        self.assertEqual({m: b["symbol"] for m, b in new["first_unresolved"].items()},
                         {"equal": "4557", "momentum_60_skip5": "2607",
                          "logistic": "6768", "hist_gradient_boosting": "4555"})
        self.assertEqual(sum(new["days_accounting_complete"].values()) -
                         sum(old["days_accounting_complete"].values()), 17)
        self.assertFalse(new["stock_strategy_nav_produced"])
        audit = pd.read_csv(OUT / "held_action_audit.csv", dtype={"symbol": str})
        for date, method, symbol, status in (
            ("2025-02-13", "equal", "6806", "paid_subscription_waived"),
            ("2025-05-28", "momentum_60_skip5", "1215", "cash_receivable_recorded"),
            ("2025-06-19", "logistic", "1711", "cash_receivable_recorded"),
            ("2025-06-24", "hist_gradient_boosting", "2368", "cash_receivable_recorded")):
            rows = audit[(audit.date == date) & (audit.method == method) & (audit.symbol == symbol)]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows.iloc[0].status, status)
            self.assertTrue(rows.iloc[0].valid_before_unresolved)
        days = pd.read_csv(OUT / "daily_accounting_status.csv")
        self.assertTrue(days.loc[~days.accounting_complete, "nav_if_complete"].isna().all())

    def test_evidence_before_event_and_no_2026_rate(self):
        cash = pd.read_csv(ROOT / "dividend_evidence_v18.csv", dtype={"symbol": str})
        rights = pd.read_csv(ROOT / "paid_rights_evidence_v18.csv", dtype={"symbol": str})
        self.assertFalse(cash[["symbol", "ex_date"]].duplicated().any())
        self.assertFalse(rights[["symbol", "ex_date"]].duplicated().any())
        for symbol, rate, payment in (("1215", 4.5, "2025-06-20"),
                                      ("1711", .3, "2025-07-18"),
                                      ("2368", 6., "2025-07-23")):
            row = cash[cash.symbol == symbol].iloc[0]
            self.assertEqual(row.cash_per_share, rate)
            self.assertEqual(row.payment_date, payment)
            self.assertLess(row.announced_date, row.ex_date)
        row = rights[rights.symbol == "6806"].iloc[0]
        self.assertEqual(row.policy, "waive_paid_subscription")
        self.assertAlmostEqual(row.paid_subscription_shares_per_1000, 178.06037779)
        self.assertEqual(row.issue_price_at_ex, 80)
        self.assertLess(row.price_announcement_date, row.ex_date)


if __name__ == "__main__":
    unittest.main()
