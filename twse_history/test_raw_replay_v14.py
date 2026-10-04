import json
import unittest

import pandas as pd


ROOT = "twse_history/"
OUT = ROOT + "output_research_v14/"


class EvidenceReplayV14Tests(unittest.TestCase):
    def test_four_new_dividends_extend_valid_ledger(self):
        summary = json.loads(open(OUT + "summary.json").read())
        self.assertEqual(summary["days_accounting_complete"], {
            "equal": 17, "momentum_60_skip5": 47,
            "logistic": 101, "hist_gradient_boosting": 104})
        self.assertEqual({m: b["symbol"] for m, b in summary["first_unresolved"].items()},
                         {"equal": "2540", "momentum_60_skip5": "3029",
                          "logistic": "4722", "hist_gradient_boosting": "8467"})
        self.assertEqual(summary["valid_filled_orders"], 2817)
        audit = pd.read_csv(OUT + "held_action_audit.csv", dtype={"symbol": str})
        for date, method, symbol in [
            ("2025-01-21", "equal", "1707"),
            ("2025-03-18", "momentum_60_skip5", "9802"),
            ("2025-05-22", "logistic", "6658"),
            ("2025-06-12", "hist_gradient_boosting", "1760")]:
            row = audit[(audit.date == date) & (audit.method == method) & (audit.symbol == symbol)]
            self.assertEqual(len(row), 1)
            self.assertEqual(row.iloc[0].status, "cash_receivable_recorded")
            self.assertTrue(row.iloc[0].valid_before_unresolved)
            self.assertGreater(row.iloc[0].cash_receivable, 0)

    def test_revisions_are_prior_to_ex_date_and_capital_reserve_is_included(self):
        cash = pd.read_csv(ROOT + "dividend_evidence_v14.csv", dtype={"symbol": str})
        revisions = pd.read_csv(ROOT + "dividend_revisions_v14.csv", dtype={"symbol": str})
        self.assertFalse(cash[["symbol", "ex_date"]].duplicated().any())
        for symbol, rate, date in [("1707", 2.7, "2025-02-21"),
                                   ("9802", 1.90014758, "2025-04-18"),
                                   ("6658", 1.08452021, "2025-06-19"),
                                   ("1760", 1.8, "2025-07-10")]:
            row = cash[cash.symbol == symbol].iloc[0]
            self.assertAlmostEqual(row.cash_per_share, rate, places=8)
            self.assertEqual(row.payment_date, date)
            self.assertLess(row.announced_date, row.ex_date)
        for symbol in ("9802", "6658"):
            row = revisions[revisions.symbol == symbol].iloc[0]
            dividend = cash[(cash.symbol == symbol) & (cash.ex_date == row.ex_date)].iloc[0]
            self.assertLess(row.revised_announced_date, row.ex_date)
            self.assertAlmostEqual(row.revised_cash_per_share, dividend.cash_per_share, places=8)
            self.assertNotEqual(row.prior_cash_per_share, row.revised_cash_per_share)
        days = pd.read_csv(OUT + "daily_accounting_status.csv")
        self.assertTrue(days.loc[~days.accounting_complete, "nav_if_complete"].isna().all())


if __name__ == "__main__":
    unittest.main()
