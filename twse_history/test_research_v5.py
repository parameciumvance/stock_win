import json
import unittest

import pandas as pd

from .research_v5 import MERGERS, simulate


def quote(date, symbol, price, factor=1.):
    return dict(date=pd.Timestamp(date), symbol=symbol, open=price, high=price + .1,
                low=price - .1, close=price, volume=1000, causal_factor=factor,
                adj_open=price * factor, adj_close=price * factor)


class MergerLedgerTests(unittest.TestCase):
    def test_common_and_preferred_ratio_uses_physical_shares(self):
        days = pd.to_datetime(["2025-07-23", "2025-07-24"])
        p = pd.DataFrame([quote(days[0], "2888", 10, 1.2),
                          quote(days[1], "2887", 16, 1.5),
                          quote(days[1], "2887I", 9)])
        selection = {days[0]: {"equal": ["2888"]}}
        delist = pd.DataFrame({"delisted_date": [days[1]], "symbol": ["2888"]})
        nav, orders, rights = simulate(p, days, selection, delist,
                                       commission=0, sell_tax=0, slippage=0)
        row = rights.iloc[0]
        self.assertAlmostEqual(row.predecessor_physical_shares, .1)
        self.assertAlmostEqual(json.loads(row.successor_physical_shares)["2887I"], .0175)
        expected = .1 * (.672 * 16 + .175 * 9)
        self.assertAlmostEqual(nav[nav.method.eq("equal")].nav_proxy.iloc[-1], expected)
        self.assertFalse(orders.status.eq("unresolved_payoff").any())

    def test_cash_tax_and_effective_day_order(self):
        days = pd.to_datetime(["2025-09-30", "2025-10-01"])
        p = pd.DataFrame([quote(days[0], "2809", 50), quote(days[0], "8888", 10),
                          quote(days[1], "2890", 25), quote(days[1], "8888", 10)])
        selection = {days[0]: {"equal": ["2809"]}, days[1]: {"equal": ["8888"]}}
        delist = pd.DataFrame({"delisted_date": [days[1]], "symbol": ["2809"]})
        nav, orders, rights = simulate(p, days, selection, delist,
                                       commission=0, sell_tax=0, slippage=0)
        self.assertFalse(((orders.date.eq(days[1])) & (orders.side.eq("buy")) &
                          (orders.status.eq("filled"))).any())
        self.assertAlmostEqual(rights.iloc[0].gross_cash, 26.75 / 50)
        self.assertAlmostEqual(rights.iloc[0].cash_tax, 26.75 / 50 * .003)
        self.assertAlmostEqual(nav[nav.method.eq("equal")].cash.iloc[-1],
                               26.75 / 50 * .997)

    def test_missing_successor_quote_fails_closed(self):
        days = pd.to_datetime(["2025-08-14", "2025-08-15"])
        p = pd.DataFrame([quote(days[0], "6288", 20)])
        selection = {days[0]: {"equal": ["6288"]}}
        delist = pd.DataFrame({"delisted_date": [days[1]], "symbol": ["6288"]})
        with self.assertRaisesRegex(ValueError, "No successor quote"):
            simulate(p, days, selection, delist, commission=0, sell_tax=0, slippage=0)


if __name__ == "__main__":
    unittest.main()
