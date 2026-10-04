import unittest

import numpy as np
import pandas as pd

from .research_v4 import FEATURES, feature_panel, limit_locked, select_training_rows, simulate


class ResearchTests(unittest.TestCase):
    def test_future_quote_mutation_cannot_change_earlier_features(self):
        dates = pd.bdate_range("2024-01-02", periods=145)
        rows = []
        for symbol in ["1111", "0050"]:
            for n, date in enumerate(dates):
                price = 20 + n * .1 if symbol == "1111" else 100 + n * .05
                rows.append(dict(date=date, symbol=symbol, close=price, adj_close=price,
                                 adj_high=price * 1.02, adj_low=price * .98,
                                 volume=1e6, turnover_twd=20e6))
        p = pd.DataFrame(rows)
        before = feature_panel(p, dates)
        later = p.symbol.eq("1111") & p.date.gt(dates[130])
        p.loc[later, ["adj_close", "adj_high", "adj_low", "close"]] *= 10
        after = feature_panel(p, dates)
        old = before[before.date.eq(dates[130])].iloc[0]
        new = after[after.date.eq(dates[130])].iloc[0]
        np.testing.assert_allclose(old[FEATURES].astype(float), new[FEATURES].astype(float))
        self.assertTrue(old.signal_eligible)

    def test_purged_label_never_trains_across_holdout(self):
        dates = pd.to_datetime(["2024-12-02", "2024-12-30", "2025-01-02"])
        data = pd.DataFrame(dict(date=dates, role=["train_eligible", "train_eligible", "test_eligible"],
            signal_eligible=True, quarantined_label=False, label_available=True,
            surge_adjusted=[False, True, False],
            label_window_end=pd.to_datetime(["2024-12-30", "2025-01-15", "2025-01-31"])))
        for feature in FEATURES:
            data[feature] = 1.
        with self.assertRaisesRegex(ValueError, "touches the holdout"):
            select_training_rows(data)

    def test_locked_open_blocks_buy_without_using_future_high_as_fill(self):
        self.assertTrue(limit_locked(dict(open=11., high=11., low=11., adj_open=11., volume=100), 10., "buy"))
        self.assertFalse(limit_locked(dict(open=10.5, high=11., low=10.5, adj_open=10.5, volume=100), 10., "buy"))
        self.assertTrue(limit_locked(dict(open=9., high=9., low=9., adj_open=9., volume=100), 10., "sell"))

    def test_unresolved_delisting_is_visible_zero_event(self):
        dates = pd.to_datetime(["2024-12-31", "2025-01-02", "2025-01-03"])
        p = pd.DataFrame(dict(date=dates, symbol="1111", open=[10., 10., np.nan],
            high=[10., 11., np.nan], low=[10., 9., np.nan], close=[10., 10., np.nan],
            adj_open=[10., 10., np.nan], adj_close=[10., 10., np.nan], volume=[100, 100, 0]))
        selections = {pd.Timestamp("2025-01-02"): {"equal": ["1111"]}}
        delisted = pd.DataFrame({"symbol": ["1111"], "delisted_date": [pd.Timestamp("2025-01-03")]})
        nav, orders = simulate(p, dates, selections, delisted, commission=0, sell_tax=0, slippage=0)
        actual = nav[nav.method.eq("equal")]
        self.assertAlmostEqual(actual.nav_proxy.iloc[0], 1)
        self.assertAlmostEqual(actual.nav_proxy.iloc[-1], 0)
        self.assertEqual(orders[orders.status.eq("unresolved_payoff")].shape[0], 1)

    def test_buy_costs_reduce_cash_and_marked_nav(self):
        dates = pd.to_datetime(["2024-12-31", "2025-01-02"])
        p = pd.DataFrame(dict(date=dates, symbol="1111", open=[10., 10.],
            high=[10., 11.], low=[10., 9.], close=[10., 10.],
            adj_open=[10., 10.], adj_close=[10., 10.], volume=[100, 100]))
        signals = {pd.Timestamp("2025-01-02"): {"equal": ["1111"]}}
        empty = pd.DataFrame(columns=["symbol", "delisted_date"])
        nav, _ = simulate(p, dates, signals, empty, commission=.01, sell_tax=0,
                          etf_sell_tax=0, slippage=.01)
        result = nav[nav.method.eq("equal")].nav_proxy.item()
        self.assertAlmostEqual(result, 1 / (1.01 * 1.01))


if __name__ == "__main__":
    unittest.main()
