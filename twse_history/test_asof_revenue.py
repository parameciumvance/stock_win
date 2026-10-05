import unittest

import pandas as pd

from .asof_revenue import attach_revenue


DAYS = pd.DatetimeIndex(pd.to_datetime([
    "2024-02-09", "2024-02-12", "2024-02-13", "2024-03-11", "2024-03-12",
    "2024-03-13", "2024-03-14", "2024-03-15"]))


def report(month, publication, amount=100, yoy=10, symbol="1234"):
    return dict(symbol=symbol, revenue_month=month,
                revenue_twd_thousands=amount, reported_yoy_pct=yoy,
                published_at=publication, source_url="https://mops.twse.com.tw/example",
                snapshot_sha256="a" * 64)


class RevenueAsOfTests(unittest.TestCase):
    def test_weekend_and_same_day_release_only_next_market_day(self):
        signals = pd.DataFrame({"date": ["2024-02-09", "2024-02-12",
                                          "2024-02-13", "2024-03-11", "2024-03-12"],
                                "symbol": ["1234"] * 5})
        reports = pd.DataFrame([report("2024-01", "2024-02-09T11:00:00+08:00"),
                                report("2024-02", "2024-03-11T17:00:00+08:00", 200)])
        result = attach_revenue(signals, reports, DAYS)
        self.assertTrue(pd.isna(result.revenue_month.iloc[0]))
        self.assertEqual(result.revenue_month.iloc[1:].tolist(),
                         ["2024-01", "2024-01", "2024-01", "2024-02"])
        self.assertEqual(result.revenue_yoy.iloc[1], .10)

    def test_late_old_month_revision_does_not_roll_back_latest_month(self):
        signals = pd.DataFrame({"date": ["2024-03-13", "2024-03-15"],
                                "symbol": ["1234", "1234"]})
        reports = pd.DataFrame([report("2024-01", "2024-02-09T11:00:00+08:00"),
                                report("2024-02", "2024-03-11T12:00:00+08:00", 200),
                                report("2024-01", "2024-03-13T16:00:00+08:00", 110)])
        result = attach_revenue(signals, reports, DAYS)
        self.assertEqual(result.revenue_month.tolist(), ["2024-02", "2024-02"])
        self.assertEqual(result.revenue_twd_thousands.tolist(), [200, 200])

    def test_latest_month_revision_uses_next_session(self):
        signals = pd.DataFrame({"date": ["2024-03-13", "2024-03-14"],
                                "symbol": ["1234", "1234"]})
        reports = pd.DataFrame([report("2024-02", "2024-03-11T12:00:00+08:00", 200),
                                report("2024-02", "2024-03-13T19:00:00+08:00", 210)])
        result = attach_revenue(signals, reports, DAYS)
        self.assertEqual(result.revenue_twd_thousands.tolist(), [200, 210])

    def test_rejects_unverified_release_time_and_bad_dates(self):
        signals = pd.DataFrame({"date": ["2024-03-12"], "symbol": ["1234"]})
        for publication in ("2024-03-11", "2024-02-27T09:00:00+08:00"):
            with self.subTest(publication=publication), self.assertRaises(ValueError):
                attach_revenue(signals, pd.DataFrame([
                    report("2024-02", publication)]), DAYS)

    def test_keeps_symbols_separate(self):
        signals = pd.DataFrame({"date": ["2024-03-12"] * 2,
                                "symbol": ["1234", "4321"]})
        reports = pd.DataFrame([report("2024-02", "2024-03-11T12:00:00+08:00")])
        result = attach_revenue(signals, reports, DAYS)
        self.assertEqual(result.revenue_month.iloc[0], "2024-02")
        self.assertTrue(pd.isna(result.revenue_month.iloc[1]))


if __name__ == "__main__":
    unittest.main()
