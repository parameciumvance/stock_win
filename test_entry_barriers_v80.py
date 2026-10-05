"""Tests for daily OHLC ambiguity, gaps, censoring, and horizon handling."""
import unittest

import numpy as np

from audit_entry_barriers_v80 import HORIZON, first_touch


class BarrierLabels(unittest.TestCase):
    def prices(self):
        n=HORIZON+2
        return [np.full(n,100.,dtype=float) for _ in range(4)]+[
            np.full(n,1000.,dtype=float)]

    def test_both_barriers_same_day_stop_first(self):
        a=self.prices();a[1][1]=125.;a[2][1]=85.
        r=first_touch(*a).iloc[0]
        self.assertEqual((r.outcome,r.exit_market_day),("stop",1))
        self.assertEqual(r.exit_adj_price,90.)
        self.assertTrue(r.both_barriers_same_day)

    def test_gap_through_stop_exits_at_open(self):
        a=self.prices();a[0][2]=85.;a[1][2]=100.;a[2][2]=80.
        r=first_touch(*a).iloc[0]
        self.assertEqual((r.outcome,r.exit_market_day),("stop",2))
        self.assertEqual(r.exit_adj_price,85.)

    def test_early_target_survives_later_missing_quote(self):
        a=self.prices();a[1][1]=125.;a[0][5]=np.nan
        r=first_touch(*a).iloc[0]
        self.assertEqual((r.outcome,r.exit_market_day),("target",1))
        self.assertEqual(r.exit_adj_price,120.)
        self.assertFalse(r.full20_quote_complete)

    def test_missing_quote_censors_unresolved_path(self):
        a=self.prices();a[4][5]=0
        r=first_touch(*a).iloc[0]
        self.assertEqual((r.outcome,r.exit_market_day),("censored",-1))

    def test_timeout_at_exact_twentieth_market_day(self):
        a=self.prices();a[3][20]=105.
        r=first_touch(*a).iloc[0]
        self.assertEqual((r.outcome,r.exit_market_day),("timeout",20))
        self.assertEqual(r.exit_adj_price,105.)
        self.assertEqual(first_touch(*a).iloc[2].outcome,"censored")


if __name__=="__main__":
    unittest.main()
