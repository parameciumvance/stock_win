import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from model_failure_diagnostic import (bin_values, cutpoints, overlap_pair, paired_months,
    price_panel, relative_return, require_hashes, strict_mean, validate_selections)
from research_runtime import sha256


class DiagnosticTests(unittest.TestCase):
    def test_unknown_selected_stock_invalidates_entire_mean(self):
        self.assertIsNone(strict_mean([.1, np.nan]))
        self.assertIsNone(strict_mean([]))
        self.assertAlmostEqual(strict_mean([.1, -.2]), -.05)

    def test_paired_months_do_not_compare_different_known_months(self):
        f = pd.DataFrame(dict(date=[1, 1, 1, 1, 2, 2, 3, 3],
            model=['a', 'a', 'b', 'b', 'a', 'b', 'a', 'b'],
            frozen=[.1, np.nan, .3, .2, .2, .1, np.nan, .8]))
        diff = paired_months(f, 'a', 'b')
        self.assertEqual(diff.index.tolist(), [2])
        self.assertAlmostEqual(diff.iloc[0], .1)

    def test_empty_group_stays_unavailable(self):
        f = pd.DataFrame(dict(date=[1], model=['a'], frozen=[.1]))
        self.assertTrue(paired_months(f, 'a', 'b').empty)

    def test_reference_bins_do_not_use_later_observations(self):
        f = pd.DataFrame(dict(date=pd.to_datetime(['2023-01-01']*3+['2024-01-01']),
            eligible=True, vol20=[1, 2, 3, 1000], turnover20=[10, 20, 30, 1000], r60=[0, 1, 2, 1000]))
        a = cutpoints(f, '2023-12-31')
        f.loc[3, ['vol20', 'turnover20', 'r60']] = -999999
        self.assertEqual(a, cutpoints(f, '2023-12-31'))
        self.assertLess(a['vol20'][1], 3)

    def test_unavailable_groups_are_not_low_or_high(self):
        self.assertEqual(bin_values([0, 1, 2, 3, np.nan], [1, 2]).tolist(),
                         ['low', 'low', 'mid', 'high', 'unknown'])
        with self.assertRaises(ValueError):
            bin_values([1], [2, 1])

    def test_costs_match_cash_flows(self):
        # Spend 100*1.005*1.001425; receive 110*.995*(1-.001425-.003).
        expected = 110*.995*(1-.001425-.003)/(100*1.005*1.001425)-1-.03
        self.assertAlmostEqual(relative_return(1.1, .03, 'frozen'), expected)
        self.assertAlmostEqual(relative_return(1.1, .03, 'gross'), .07)
        self.assertTrue(np.isnan(relative_return(np.nan, .03, 'gross')))

    def test_proportional_costs_preserve_model_baseline_order(self):
        gross = relative_return(1.2, .1, 'gross')-relative_return(1.1, .1, 'gross')
        net = relative_return(1.2, .1, 'frozen')-relative_return(1.1, .1, 'frozen')
        factor = .995*(1-.001425-.003)/(1.005*1.001425)
        self.assertAlmostEqual(net, factor*gross)
        self.assertGreater(net, 0)

    def test_exclusive_names_explain_difference(self):
        a = pd.DataFrame(dict(symbol=['a', 'b', 'c'], frozen=[.2, .1, .3]))
        b = pd.DataFrame(dict(symbol=['a', 'd', 'e'], frozen=[.2, -.1, 0]))
        r = overlap_pair(a, b)
        self.assertEqual(r['overlap'], 1)
        self.assertAlmostEqual(r['difference'], 2/3*(.2+.05))
        self.assertAlmostEqual(r['difference'], r['exclusive_identity'])

    def test_identical_selections_have_zero_exclusive_contribution(self):
        a = pd.DataFrame(dict(symbol=['a', 'b'], frozen=[.2, .1]))
        r = overlap_pair(a, a)
        self.assertEqual(r['difference'], 0)
        self.assertEqual(r['exclusive_identity'], 0)
        self.assertIsNone(r['exclusive_model'])

    def test_unknown_overlap_never_becomes_zero_return(self):
        a = pd.DataFrame(dict(symbol=['a', 'b'], frozen=[np.nan, .1]))
        b = pd.DataFrame(dict(symbol=['a', 'c'], frozen=[np.nan, .2]))
        r = overlap_pair(a, b)
        self.assertIsNone(r['difference'])
        self.assertIsNone(r['exclusive_identity'])
        with self.assertRaises(ValueError):
            overlap_pair(a, b.iloc[:1])

    @staticmethod
    def prices():
        dates = pd.bdate_range('2023-01-02', periods=130)
        pieces = []
        for symbol, role in [('0050', 'benchmark'), ('1111', 'common_stock')]:
            pieces.append(pd.DataFrame(dict(date=dates, symbol=symbol,
                close=np.arange(130)+100., volume=1e6, turnover_twd=1e8,
                adj_open=np.arange(130)+100., adj_close=np.arange(130)+100., universe_role=role)))
        return pd.concat(pieces, ignore_index=True), dates

    def test_market_horizon_does_not_contract_across_stock_suspension(self):
        p, dates = self.prices()
        p = p[~(p.symbol.eq('1111') & p.date.eq(dates[121]))]
        panel, clock = price_panel(p, 3)
        r = panel[(panel.symbol == '1111') & panel.date.eq(dates[120])].iloc[0]
        self.assertEqual(len(clock), 130)
        self.assertEqual(r.replay_end, dates[123])
        self.assertTrue(np.isnan(r.ratio))  # missing t+1, never use t+2 instead

    def test_missing_interior_quote_does_not_remove_valid_endpoints(self):
        p, dates = self.prices()
        p = p[~(p.symbol.eq('1111') & p.date.eq(dates[122]))]
        panel, _ = price_panel(p, 3)
        r = panel[(panel.symbol == '1111') & panel.date.eq(dates[120])].iloc[0]
        self.assertAlmostEqual(r.ratio, 223/221)

    def test_missing_benchmark_endpoint_propagates(self):
        p, dates = self.prices()
        p = p[~(p.symbol.eq('0050') & p.date.eq(dates[123]))]
        panel, _ = price_panel(p, 3)
        r = panel[(panel.symbol == '1111') & panel.date.eq(dates[120])].iloc[0]
        self.assertTrue(np.isnan(r.benchmark))
        self.assertTrue(np.isnan(relative_return(r.ratio, r.benchmark, 'frozen')))

    def test_duplicate_prices_rejected(self):
        p, _ = self.prices()
        with self.assertRaises(ValueError):
            price_panel(pd.concat([p, p.iloc[:1]]), 3)

    def test_hash_drift_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)/'input'
            p.write_bytes(b'frozen')
            expected = {str(p): sha256(p)}
            require_hashes(expected)
            p.write_bytes(b'replaced')
            with self.assertRaises(ValueError):
                require_hashes(expected)

    def test_missing_method_rank_duplicate_and_future_source_rejected(self):
        date = pd.Timestamp('2024-01-02')
        a = pd.DataFrame(dict(date=[date]*4, model=['a', 'a', 'b', 'b'],
            symbol=['x', 'y', 'x', 'z'], rank=[1, 2, 1, 2],
            entry_date=date+pd.Timedelta(days=1), proxy_available_date=date,
            margin_source_date=date-pd.Timedelta(days=1)))
        validate_selections(a, ['a', 'b'], 2)
        for bad in [a.iloc[:2], pd.concat([a, a.iloc[:1]])]:
            with self.assertRaises(ValueError):
                validate_selections(bad, ['a', 'b'], 2)
        for column, value in [('rank', 0), ('margin_source_date', date),
                              ('proxy_available_date', date+pd.Timedelta(days=1))]:
            bad = a.copy()
            bad.loc[0, column] = value
            with self.assertRaises(ValueError):
                validate_selections(bad, ['a', 'b'], 2)


if __name__ == '__main__':
    unittest.main()
