import json
import unittest

import pandas as pd

from .research_cash_v6 import etf_physical_ledger, held_action_inventory


class CashLedgerTests(unittest.TestCase):
    def test_etf_ex_date_receivable_and_later_payment(self):
        days = pd.to_datetime(["2025-01-02", "2025-01-17", "2025-02-20",
                               "2025-06-18", "2025-07-21", "2025-08-08"])
        prices = pd.DataFrame(dict(date=days, symbol="0050",
                                   open=[100, 97.3, 98, 25, 24.64, 25],
                                   close=[100, 97.3, 98, 25, 24.64, 25]))
        nav, claims = etf_physical_ledger(prices, days, commission=0, slippage=0)
        self.assertEqual(len(claims), 2)
        self.assertAlmostEqual(nav.iloc[1].dividend_receivable, .027)
        self.assertAlmostEqual(nav.iloc[1].uninvested_cash, 0)
        self.assertAlmostEqual(nav.iloc[2].uninvested_cash, .027)
        self.assertAlmostEqual(nav.iloc[2].dividend_receivable, 0)
        self.assertAlmostEqual(nav.iloc[3].physical_units, .04)
        self.assertAlmostEqual(nav.iloc[4].dividend_receivable, .0144)
        self.assertAlmostEqual(nav.iloc[-1].uninvested_cash, .0414)
        self.assertAlmostEqual(nav.iloc[-1].dividend_receivable, 0)

    def test_actions_use_pre_open_positions_and_merger_rights_replay(self):
        days = pd.to_datetime(["2025-07-23", "2025-07-24", "2025-07-25"])
        p = pd.DataFrame([dict(date=d, symbol=s, adj_open=price, causal_factor=1.)
                          for d, s, price in [(days[0], "2888", 10),
                                              (days[1], "2887", 16),
                                              (days[1], "2887I", 9),
                                              (days[2], "2887", 16),
                                              (days[2], "2887I", 9)]])
        orders = pd.DataFrame([dict(date=days[0], method="equal", symbol="2888",
                                    side="buy", notional=10., status="filled"),
                               dict(date=days[1], method="equal", symbol="2887",
                                    side="buy", notional=16., status="filled")])
        rights = pd.DataFrame([dict(date=days[1], method="equal", predecessor="2888",
                                    predecessor_synthetic_units=1.,
                                    successor_physical_shares=json.dumps({"2887": .672,
                                                                          "2887I": .175}))])
        actions = pd.DataFrame([dict(effective_date=days[1], symbol="2888",
                                     event_id="before", event_type="exrights",
                                     event_subtype="息", source_url="x"),
                                dict(effective_date=days[1], symbol="2887",
                                     event_id="same-day", event_type="exrights",
                                     event_subtype="息", source_url="x"),
                                dict(effective_date=days[2], symbol="2887I",
                                     event_id="after", event_type="exrights",
                                     event_subtype="息", source_url="x")])
        inventory = held_action_inventory(p, orders, rights, actions, days)
        self.assertEqual(inventory.event_id.tolist(), ["before", "after"])
        self.assertAlmostEqual(inventory.iloc[1].adjusted_unit_equivalent_shares, .175)


if __name__ == "__main__":
    unittest.main()
