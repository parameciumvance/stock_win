import tempfile
import unittest
from pathlib import Path

import pandas as pd

from audit_institutional_increment import dataset, FLOW_FEATURES


class IncrementDiagnosticTests(unittest.TestCase):
    def fixture(self, root):
        days = pd.bdate_range('2023-01-02', '2024-01-31')
        rows = []
        for symbol, role, price in [('0050', 'benchmark', 100), ('2330', 'common_stock', 500)]:
            rows.append(pd.DataFrame({'date': days, 'symbol': symbol, 'open': price, 'high': price,
                'low': price, 'close': price, 'volume': 100000, 'turnover_twd': price * 100000,
                'adj_open': price, 'adj_high': price, 'adj_low': price, 'adj_close': price,
                'universe_role': role}))
        quotes = pd.concat(rows, ignore_index=True)
        features = pd.DataFrame({'date': days[days.year == 2023], 'symbol': '2330'})
        for column in FLOW_FEATURES:features[column] = .1
        p = root / 'prices.csv';f = root / 'features.csv'
        quotes.to_csv(p, index=False);features.to_csv(f, index=False)
        return p, f, quotes

    def test_label_purge_and_future_quotes_cannot_change_training(self):
        with tempfile.TemporaryDirectory() as folder:
            p, f, quotes = self.fixture(Path(folder));cutoff = pd.Timestamp('2023-08-31')
            train, test, _ = dataset(p, f, cutoff, .001425, .003, .005)
            self.assertTrue(train.label_window_end.le(cutoff).all())
            self.assertTrue(test.date.gt(cutoff).all())
            self.assertLess(train.date.max(), cutoff)
            for column in ['open', 'high', 'low', 'close', 'adj_open', 'adj_high', 'adj_low', 'adj_close']:
                quotes.loc[quotes.symbol.eq('2330') & quotes.date.gt(cutoff), column] *= 2
            quotes.to_csv(p, index=False)
            changed, _, _ = dataset(p, f, cutoff, .001425, .003, .005)
            pd.testing.assert_frame_equal(train.reset_index(drop=True), changed.reset_index(drop=True))

    def test_flat_quote_target_includes_all_costs(self):
        with tempfile.TemporaryDirectory() as folder:
            p, f, _ = self.fixture(Path(folder))
            train, _, _ = dataset(p, f, pd.Timestamp('2023-08-31'), .001425, .003, .005)
            expected = (1 - .005) * (1 - .001425 - .003) / ((1 + .005) * (1 + .001425)) - 1
            self.assertTrue(train.target.sub(expected).abs().lt(1e-12).all())

    def test_missing_future_quote_does_not_remove_asof_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            p, f, quotes = self.fixture(Path(folder))
            missing = quotes.symbol.eq('2330') & quotes.date.eq('2023-09-08')
            quotes.loc[missing, 'adj_close'] = float('nan')
            quotes.to_csv(p, index=False)
            _, test, _, candidates = dataset(p, f, pd.Timestamp('2023-08-31'),
                .001425, .003, .005, return_candidates=True)
            signal = candidates[candidates.date.eq('2023-09-01')].iloc[0]
            self.assertTrue(signal.eligible)
            self.assertTrue(signal[FLOW_FEATURES].notna().all())
            self.assertFalse(signal.future_quotes_complete)
            self.assertTrue(pd.isna(signal.target))
            self.assertTrue(pd.notna(signal.endpoint_target))
            self.assertFalse(test.date.eq('2023-09-01').any())

    def test_benchmark_suspension_does_not_shorten_market_label_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            p, f, quotes = self.fixture(Path(folder))
            quotes = quotes[~(quotes.symbol.eq('0050') & quotes.date.eq('2023-09-08'))]
            quotes.to_csv(p, index=False)
            _, _, _, candidates = dataset(p, f, pd.Timestamp('2023-08-31'),
                .001425, .003, .005, return_candidates=True)
            signal = candidates[candidates.date.eq('2023-09-01')].iloc[0]
            self.assertEqual(signal.label_window_end, pd.Timestamp('2023-09-29'))
            self.assertTrue(candidates.date.eq('2023-09-08').any())
            self.assertTrue(pd.isna(signal.target))
            self.assertTrue(pd.notna(signal.endpoint_target))


if __name__ == '__main__':unittest.main()

