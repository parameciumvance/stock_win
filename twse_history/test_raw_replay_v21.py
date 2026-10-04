"""Checks that documented 2025 actions extend the valid ledger without crossing policy gaps."""
import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path("twse_history")
OUT = ROOT / "output_research_v21"


class ReplayV21Tests(unittest.TestCase):
    def test_cumulative_replay_and_foreign_withholding_quarantine(self):
        old = json.loads((ROOT / "output_research_v20/summary.json").read_text())
        now = json.loads((OUT / "summary.json").read_text())
        self.assertEqual(now["days_accounting_complete"], {
            "equal": 47, "momentum_60_skip5": 120,
            "logistic": 127, "hist_gradient_boosting": 127,
        })
        self.assertEqual(sum(now["days_accounting_complete"].values()) -
                         sum(old["days_accounting_complete"].values()), 55)
        self.assertEqual({m: x["symbol"] for m, x in now["first_unresolved"].items()},
                         {"equal": "1342", "momentum_60_skip5": "6515",
                          "logistic": "6933", "hist_gradient_boosting": "6933"})
        self.assertFalse(now["stock_strategy_nav_produced"])
        audit = pd.read_csv(OUT / "held_action_audit.csv", dtype={"symbol": str})
        self.assertTrue((audit[(audit.symbol == "6933") &
                               (audit.date == "2025-07-16")].status == "unresolved").all())
        for date, method, symbol, status in (
            ("2025-02-25", "equal", "6177", "paid_subscription_waived_ratio_unverified"),
            ("2025-03-18", "equal", "2330", "cash_receivable_recorded"),
            ("2025-06-27", "momentum_60_skip5", "8114", "cash_receivable_recorded"),
        ):
            row = audit[(audit.date == date) & (audit.method == method) &
                        (audit.symbol == symbol)]
            self.assertEqual(len(row), 1)
            self.assertEqual(row.iloc[0].status, status)
        days = pd.read_csv(OUT / "daily_accounting_status.csv")
        self.assertTrue(days.loc[~days.accounting_complete, "nav_if_complete"].isna().all())
        self.assertEqual(int(days.nav_if_complete.notna().sum()), 414)

    def test_new_evidence_uses_prior_dated_rates_and_payment_dates(self):
        cash = pd.read_csv(ROOT / "dividend_evidence_v21.csv", dtype={"symbol": str})
        rights = pd.read_csv(ROOT / "paid_rights_evidence_v21.csv", dtype={"symbol": str})
        self.assertFalse(cash[["symbol", "ex_date"]].duplicated().any())
        self.assertFalse(rights[["symbol", "ex_date"]].duplicated().any())
        for symbol, date, amount, pay in (
            ("2330", "2025-03-18", 4.50002042, "2025-04-10"),
            ("2753", "2025-06-23", 6.00450148, "2025-07-18"),
            ("6937", "2025-07-09", 2.10252387, "2025-08-08"),
            ("8114", "2025-06-27", 7.76389668, "2025-07-25"),
        ):
            row = cash[(cash.symbol == symbol) & (cash.ex_date == date)].iloc[0]
            self.assertAlmostEqual(row.cash_per_share, amount)
            self.assertEqual(row.payment_date, pay)
            self.assertLess(row.announced_date, row.ex_date)
        self.assertFalse(((cash.symbol == "6933") &
                          (cash.ex_date == "2025-07-16")).any())
        for symbol in ("6177", "1598"):
            row = rights[rights.symbol == symbol].iloc[0]
            self.assertEqual(row.policy, "waive_paid_subscription")
            self.assertEqual(row.ratio_status, "issuer_aggregate_only")
            self.assertTrue(pd.isna(row.paid_subscription_shares_per_1000))


if __name__ == "__main__":
    unittest.main()
