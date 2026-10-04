"""Economic and temporal invariants; run python -m unittest twse_history.test_history."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from .build_history import (adjust_prices, build_labels, build_universe,
                            classify_security, date_value, full_window_max,
                            load_actions, load_table)


def quotes(close, start="2025-01-02", symbol="2330"):
    close = np.asarray(close, float)
    dates = pd.bdate_range(start, periods=len(close))
    return pd.DataFrame(dict(date=dates, symbol=symbol, name="測試", open=close,
                             high=close, low=close, close=close, volume=1000.0))


def events(dates, factors, symbol="2330"):
    return pd.DataFrame(dict(symbol=symbol, effective_date=pd.to_datetime(dates),
                             adjustment_factor=factors))


class AdjustmentTests(unittest.TestCase):
    def test_cash_dividend_removes_reference_drop(self):
        q = quotes([100, 95, 104.5])
        e = events([q.date.iloc[1]], [0.95])
        p = adjust_prices(q, e, q.date.max())
        np.testing.assert_allclose(p.adj_close, [100, 100, 110])
        np.testing.assert_allclose(p.back_adj_close, [95, 95, 104.5])
        np.testing.assert_allclose(p.volume, 1000)  # never dividend-adjust volume

    def test_split_and_event_day_boundary(self):
        q = quotes([200, 50, 55])
        p = adjust_prices(q, events([q.date.iloc[1]], [0.25]), q.date.max())
        np.testing.assert_allclose(p.adj_close, [200, 200, 220])
        np.testing.assert_allclose(p.backward_factor, [0.25, 1, 1])

    def test_reverse_split_and_deficit_reduction(self):
        q = quotes([10, 40, 44])
        p = adjust_prices(q, events([q.date.iloc[1]], [4.0]), q.date.max())
        np.testing.assert_allclose(p.adj_close, [10, 10, 11])

    def test_cash_reduction_is_reference_continuity_not_total_return(self):
        # 100 old price; 5 cash returned; 0.5 new shares; reference 190.
        q = quotes([100, 190, 200])
        p = adjust_prices(q, events([q.date.iloc[1]], [1.9]), q.date.max())
        self.assertAlmostEqual(p.adj_close.iloc[1], 100)
        self.assertAlmostEqual(p.adj_close.iloc[2], 200 / 1.9)
        self.assertNotAlmostEqual(p.adj_close.iloc[2], 0.5 * 200 + 5)

    def test_rights_subscription_reference(self):
        # 100 previous, +1 new share at 60 => reference 80.
        q = quotes([100, 80, 88])
        p = adjust_prices(q, events([q.date.iloc[1]], [0.8]), q.date.max())
        np.testing.assert_allclose(p.adj_close, [100, 100, 110])

    def test_causal_prefix_unchanged_when_future_events_arrive(self):
        q = quotes([100, 105, 52.5, 50])
        e = events([q.date.iloc[2], q.date.iloc[3]], [0.5, 50 / 52.5])
        full = adjust_prices(q, e, q.date.max())
        prior = adjust_prices(q, e, q.date.iloc[1])
        np.testing.assert_array_equal(full.adj_close.iloc[:2], prior.adj_close)
        np.testing.assert_array_equal(prior.causal_factor, [1, 1])

    def test_multiple_events_compound_once(self):
        q = quotes([100, 90, 45])
        p = adjust_prices(q, events(q.date.iloc[1:], [0.9, 0.5]), q.date.max())
        np.testing.assert_allclose(p.adj_close, [100, 100, 100])

    def test_same_day_composite_requires_review(self):
        q = quotes([100, 50])
        e = events([q.date.iloc[1]] * 2, [0.5, 0.9])
        with self.assertRaises(ValueError):
            adjust_prices(q, e, q.date.max())

    def test_bad_factor_rejected(self):
        q = quotes([100, 50])
        for factor in [0, -1, np.nan, np.inf]:
            with self.subTest(factor=factor), self.assertRaises(ValueError):
                adjust_prices(q, events([q.date.iloc[1]], [factor]), q.date.max())


class LabelTests(unittest.TestCase):
    def test_any_missing_future_price_censors(self):
        x = full_window_max([100, 150, np.nan, 130, 140], 3)
        self.assertTrue(np.isnan(x).all())

    def test_signal_high_not_included_and_tail_unavailable(self):
        x = full_window_max([999, 110, 120, 130], 2)
        np.testing.assert_allclose(x[:2], [120, 130])
        self.assertTrue(np.isnan(x[2:]).all())

    def test_threshold_boundary_and_next_open_not_fill_claim(self):
        q = quotes([100, 130, 120])
        p = adjust_prices(q, events([], []), q.date.max())
        m = q[["date", "symbol"]]
        labels = build_labels(p, m, pd.DatetimeIndex(q.date), horizon=2)
        self.assertTrue(labels.surge_adjusted.iloc[0])
        self.assertFalse(labels.surge_next_open.iloc[0])

    def test_market_calendar_not_compressed_around_suspension(self):
        q = quotes([100, 110, 120, 130, 140])
        calendar = pd.DatetimeIndex(q.date)
        p = adjust_prices(q.drop(index=1), events([], []), q.date.max())
        labels = build_labels(p, q[["date", "symbol"]], calendar, horizon=2)
        self.assertFalse(labels.label_available.iloc[0])
        self.assertEqual(labels.censor_reason.iloc[0], "missing_future_high")
        self.assertFalse(labels.label_available.iloc[1])

    def test_delisted_tail_not_shortened_to_last_quote(self):
        q = quotes([100, 110, 120, 130, 140])
        calendar = pd.DatetimeIndex(q.date)
        p = adjust_prices(q.iloc[:2], events([], []), q.date.max())
        labels = build_labels(p, q.iloc[:2][["date", "symbol"]], calendar, horizon=2)
        self.assertTrue(labels.surge_adjusted.isna().all())
        self.assertTrue(labels.censor_reason.eq("missing_future_high").all())


class SourceTests(unittest.TestCase):
    def test_historical_member_survives_current_master_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "list.html").write_text(
                '<table><tr><td>2330　台積電</td><td>TW0002330008</td>'
                '<td>1994/09/05</td><td>上市</td><td>半導體</td>'
                '<td>ESVUFR</td><td></td></tr></table>')
            (raw / "delisted_2025.json").write_text(json.dumps(dict(
                status="ok", fields=["終止上市日期", "公司名稱", "上市編號"],
                data=[["114/01/07", "舊公司", "2888"]])))
            current = quotes([100] * 5)
            departed = quotes([20] * 2, symbol="2888")
            departed.loc[0, "name"] = "歷史舊名"
            departed.loc[1, "name"] = "改名"
            q = pd.concat([current, departed], ignore_index=True)
            master, members, names, _ = build_universe(q, raw, pd.DatetimeIndex(current.date))
            self.assertEqual(master.loc[master.symbol.eq("2888"), "security_type"].item(), "common_stock")
            old = members[members.symbol.eq("2888")]
            self.assertEqual(old.date.max(), pd.Timestamp("2025-01-06"))
            self.assertFalse(old.quote_present.iloc[-1])  # missing quote before delisting retained
            self.assertEqual(old.name.iloc[0], "歷史舊名")  # future rename not backfilled
            self.assertEqual(old.name.iloc[-1], "改名")
            self.assertFalse((old.date >= pd.Timestamp("2025-01-07")).any())

    def test_predecessor_listing_date_does_not_backfill_new_ticker(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "list.html").write_text(
                '<table><tr><td>3717　新控股</td><td>TW0003717002</td>'
                '<td>2008/01/01</td><td>上市</td><td>其他</td>'
                '<td>ESVUFR</td><td></td></tr></table>')
            (raw / "delisted_2025.json").write_text(json.dumps(dict(
                status="ok", fields=["終止上市日期", "公司名稱", "上市編號"],
                data=[["114/01/07", "舊公司", "2888"]])))
            calendar = pd.bdate_range("2025-01-02", periods=5)
            q = quotes([100, 110, 120], start="2025-01-06", symbol="3717")
            _, members, _, _ = build_universe(q, raw, calendar)
            self.assertEqual(members.date.min(), pd.Timestamp("2025-01-06"))

    def test_roc_dates(self):
        for s in ["114年06月18日", "114/06/18", "114.06.18", "20250618", "2025-06-18"]:
            self.assertEqual(date_value(s), pd.Timestamp("2025-06-18"))

    def test_wrong_year_response_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.json"
            path.write_text(json.dumps(dict(stat="OK", fields=["date"], data=[["115/06/18"]])))
            with self.assertRaises(ValueError):
                load_table(path, "date", 2025)

    def test_common_preferred_tdr_and_departed_issuer(self):
        self.assertEqual(classify_security("1101", "ESVUFR", set())[0], "common_stock")
        self.assertEqual(classify_security("1101B", "EPNRAR", set())[0], "preferred_or_other_equity")
        self.assertEqual(classify_security("9103", "EDSDDR", set())[0], "depository_receipt")
        self.assertEqual(classify_security("0050", "CEOGEU", set())[0], "fund_note_or_other")
        self.assertEqual(classify_security("2888", "", {"2888"})[0], "common_stock")
        self.assertEqual(classify_security("9998", "", set())[0], "unresolved")


if __name__ == "__main__":
    unittest.main()
