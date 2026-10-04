import unittest

import pandas as pd

from .physical_ledger_v9 import PhysicalBook


class RawShareCashTests(unittest.TestCase):
    def test_ex_date_entitlement_precedes_new_buy_and_payment_converts_receivable(self):
        b = PhysicalBook(cash=200.)
        b.buy("A", 5, 10, commission=0, slippage=0)
        d, pay = pd.Timestamp("2025-06-10"), pd.Timestamp("2025-07-10")
        self.assertEqual(b.ex_cash("A", d, pay, 2), 10)
        b.buy("A", 5, 10, commission=0, slippage=0)
        self.assertEqual(b.receivable, 10)
        self.assertEqual(b.pay(pd.Timestamp("2025-07-09")), 0)
        self.assertEqual(b.pay(pay), 10)
        self.assertEqual(b.pay(pay), 0)
        self.assertEqual(b.receivable, 0)
        self.assertEqual(b.nav({"A": 10}), 210.)

    def test_split_changes_shares_not_cash_and_oversell_rejected(self):
        b = PhysicalBook(cash=100.)
        b.buy("A", 2, 10, commission=0, slippage=0)
        before = b.nav({"A": 10})
        b.split("A", 4)
        self.assertEqual(b.shares["A"], 8)
        self.assertEqual(b.nav({"A": 2.5}), before)
        with self.assertRaisesRegex(ValueError, "more physical shares"):
            b.sell("A", 9, 2.5)


if __name__ == "__main__":
    unittest.main()
