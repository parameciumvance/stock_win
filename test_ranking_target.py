import unittest

import numpy as np
import pandas as pd

from ranking_target_research import (METHODS, PRICE_FEATURES, evaluate_day,
    feature_matrix, strict_mean, training_rows)
from ranking_target_review import calendar_interval, gate, missing_reason


class RankTargetTests(unittest.TestCase):
    @staticmethod
    def prices():
        dates = pd.bdate_range('2023-01-02', periods=250)
        frames = []
        for symbol, role in [('0050', 'benchmark'), ('1111', 'common_stock'), ('2222', 'common_stock')]:
            p = 100.+np.arange(len(dates))*.1+np.sin(np.arange(len(dates))/5)
            frames.append(pd.DataFrame(dict(date=dates, symbol=symbol, close=p,
                adj_open=p*.999, adj_high=p*1.01, adj_low=p*.99, adj_close=p,
                volume=1e6, turnover_twd=1e8, universe_role=role)))
        c = dict(horizon=60, commission=.001425, sell_tax=.003, slippage_each_side=.005, min_pool_size=1)
        return pd.concat(frames, ignore_index=True), dates, c

    def test_price_features_do_not_change_when_future_prices_change(self):
        p, dates, c = self.prices()
        a, _ = feature_matrix(p, c)
        columns = ['close', 'adj_open', 'adj_high', 'adj_low', 'adj_close']
        p.loc[p.date.gt(dates[180]) & p.symbol.eq('1111'), columns] *= 2
        b, _ = feature_matrix(p, c)
        key = lambda f: f[(f.symbol == '1111') & f.date.eq(dates[150])]
        np.testing.assert_array_equal(key(a)[PRICE_FEATURES], key(b)[PRICE_FEATURES])
        self.assertNotEqual(key(a).endpoint_target.iloc[0], key(b).endpoint_target.iloc[0])

    def test_market_horizon_and_unknown_entry_not_shifted(self):
        p, dates, c = self.prices()
        p = p[~(p.symbol.eq('1111') & p.date.eq(dates[151]))]
        f, _ = feature_matrix(p, c)
        row = f[(f.symbol == '1111') & f.date.eq(dates[150])].iloc[0]
        self.assertEqual(row.label_window_end, dates[210])
        self.assertEqual(row.entry_date, dates[151])
        self.assertTrue(np.isnan(row.endpoint_target))

    def test_interior_missing_quote_keeps_valid_endpoint(self):
        p, dates, c = self.prices()
        p = p[~(p.symbol.eq('1111') & p.date.eq(dates[180]))]
        f, _ = feature_matrix(p, c)
        row = f[(f.symbol == '1111') & f.date.eq(dates[150])].iloc[0]
        self.assertTrue(np.isfinite(row.endpoint_target))

    def test_unknown_future_outcomes_do_not_filter_scoring_pool(self):
        p, dates, c = self.prices()
        f, _ = feature_matrix(p, c)
        tail = f[f.date.eq(dates[240])]
        self.assertEqual(len(tail), 2)
        self.assertTrue(tail.endpoint_target.isna().all())

    def test_purge_then_average_tied_percentile_labels(self):
        f = pd.DataFrame(dict(date=pd.to_datetime(['2023-08-01']*4+['2023-12-29']*2),
            symbol=['a', 'b', 'c', 'd', 'a', 'b'], score_year=[2023]*4+[2024]*2,
            label_window_end=pd.to_datetime(['2023-10-30']*4+['2024-04-01']*2),
            endpoint_target=[.2, .2, -.1, np.nan, 999, -999]))
        train, test, cutoff = training_rows(f, 2024)
        self.assertEqual(train.symbol.tolist(), ['a', 'b', 'c'])
        np.testing.assert_allclose(train.rank_target, [5/6, 5/6, 1/3])
        self.assertLessEqual(train.label_window_end.max(), test.date.min())
        self.assertEqual(cutoff, pd.Timestamp('2023-12-29'))

    def test_outlier_magnitude_does_not_change_ordinal_target(self):
        f = pd.DataFrame(dict(date=pd.to_datetime(['2023-08-01']*3+['2023-12-29']),
            symbol=['a', 'b', 'c', 'a'], score_year=[2023]*3+[2024],
            label_window_end=pd.to_datetime(['2023-10-30']*3+['2024-04-01']), endpoint_target=[-.1, .1, .2, np.nan]))
        a, _, _ = training_rows(f, 2024)
        f.loc[2, 'endpoint_target'] = 10000
        b, _, _ = training_rows(f, 2024)
        np.testing.assert_array_equal(a.rank_target, b.rank_target)

    @staticmethod
    def candidates():
        f = pd.DataFrame(dict(date=pd.to_datetime(['2024-01-02']*3), symbol=['c', 'a', 'b'],
            entry_date=pd.Timestamp('2024-01-03'), label_window_end=pd.Timestamp('2024-03-29'),
            endpoint_target=[.5, np.nan, .1]))
        for method in METHODS:
            f[method] = [2., 3., 1.]
        return f

    def test_selection_keeps_unknown_highest_score_and_no_replacement(self):
        row, selected = evaluate_day(self.candidates(), 2)
        self.assertTrue(np.isnan(row['rank_tree_net_relative']))
        self.assertEqual(row['rank_tree_unknown'], 1)
        self.assertEqual(selected[selected.method.eq('rank_tree')].symbol.tolist(), ['a', 'c'])

    def test_fixed_tie_break_uses_symbol_not_outcome(self):
        f = self.candidates()
        f[METHODS] = 1.
        _, top = evaluate_day(f, 1)
        self.assertEqual(set(top.symbol), {'a'})

    def test_duplicate_keys_nonfinite_scores_and_bad_counts_fail(self):
        f = self.candidates()
        for bad, count in [(pd.concat([f, f.iloc[:1]]), 2), (f, 0), (f, 4)]:
            with self.assertRaises(ValueError):
                evaluate_day(bad, count)
        f.loc[0, 'rank_tree'] = np.nan
        with self.assertRaises(ValueError):
            evaluate_day(f, 1)

    def test_calendar_interval_retains_missing_positions(self):
        values = np.sin(np.arange(100))
        values[10:30] = np.nan
        r = calendar_interval(values, 20, 500, 7)
        self.assertEqual(r['calendar_positions'], 100)
        self.assertEqual(r['paired_dates'], 80)
        self.assertEqual(r['missing_positions'], 20)
        self.assertEqual(r['status'], 'descriptive_circular_block_interval')
        self.assertEqual(r, calendar_interval(values, 20, 500, 7))

    def test_insufficient_pairs_never_shorten_frozen_block(self):
        r = calendar_interval([1.]*40+[np.nan]*60, 60, 100, 7)
        self.assertIn('insufficient', r['status'])
        self.assertNotIn('lower_95', r)
        with self.assertRaises(ValueError):
            calendar_interval([np.inf]*100, 20, 100, 7)

    def test_constant_paired_gain_has_constant_interval(self):
        r = calendar_interval(np.full(100, .02), 20, 500, 7)
        self.assertAlmostEqual(r['lower_95'], .02)
        self.assertAlmostEqual(r['upper_95'], .02)

    def test_resource_gate_requires_all_years_not_one_good_year(self):
        def summary(a, b, v):
            return dict(comparisons={k: dict(mean=x) for k, x in [('return_tree', a), ('mom60', b), ('vol20', v)]})
        good = summary(.1, .1, .1)
        self.assertTrue(gate([good, good, summary(.1, -.1, -.1)])['passed'])
        self.assertFalse(gate([good, good, summary(-.01, .1, .1)])['passed'])
        self.assertFalse(gate([good, summary(.1, -.1, -.1), summary(.1, -.1, -.1)])['passed'])
        self.assertFalse(gate([good])['passed'])

    def test_strict_mean_does_not_ignore_unknowns(self):
        self.assertTrue(np.isnan(strict_mean([.1, np.nan])))
        self.assertAlmostEqual(strict_mean([.1, .3]), .2)

    def test_future_maturity_is_distinct_from_missing_quotes(self):
        self.assertEqual(missing_reason(pd.NaT, 10, np.nan, 100, np.nan), 'not_mature_by_asof')
        self.assertEqual(missing_reason(pd.Timestamp('2026-01-01'), 10, np.nan, 100, 110), 'stock_exit_unavailable')
        self.assertEqual(missing_reason(pd.Timestamp('2026-01-01'), np.nan, 11, 100, 0), 'stock_entry_unavailable;benchmark_exit_unavailable')
        self.assertIsNone(missing_reason(pd.Timestamp('2026-01-01'), 10, 11, 100, 110))

    def test_undefined_bootstrap_draws_are_not_silently_discarded(self):
        values = np.full(100, np.nan)
        values[:2] = .01
        r = calendar_interval(values, 1, 500, 7)
        self.assertEqual(r['status'], 'undefined_draws_no_interval')
        self.assertGreater(r['undefined_draws'], 0)
        self.assertNotIn('lower_95', r)


if __name__ == '__main__':
    unittest.main()
