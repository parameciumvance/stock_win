import unittest
import numpy as np
import pandas as pd
from .institutional_features import build_features


class InstitutionalFeatureTests(unittest.TestCase):
    def fixture(self):
        days = pd.bdate_range('2024-01-02', periods=24)
        prices = pd.DataFrame({'date': days, 'symbol': '2330', 'volume': 1000})
        flows = pd.DataFrame({'date': days, 'symbol': '2330', 'foreign_schema': 'excluding_foreign_dealer',
                              'foreign_net_shares': 100, 'trust_net_shares': -20, 'total_net_shares': 80})
        return prices, flows, days

    def test_no_same_day_input_and_no_future_changes(self):
        prices, flows, days = self.fixture()
        first = build_features(prices, flows, days)
        self.assertTrue(np.isnan(first.foreign_net_volume_ratio_1d.iloc[0]))
        self.assertAlmostEqual(first.foreign_net_volume_ratio_1d.iloc[1], .1)
        flows.loc[flows.date >= days[10], 'foreign_net_shares'] = 1000000
        second = build_features(prices, flows, days)
        pd.testing.assert_frame_equal(first.iloc[:11], second.iloc[:11])
        self.assertNotEqual(first.foreign_net_volume_ratio_1d.iloc[11], second.foreign_net_volume_ratio_1d.iloc[11])

    def test_missing_row_is_missing_and_breaks_rolling_window(self):
        prices, flows, days = self.fixture()
        flows = flows.drop(index=8)
        out = build_features(prices, flows, days)
        self.assertTrue(np.isnan(out.foreign_net_volume_ratio_1d.iloc[9]))
        self.assertTrue(np.isnan(out.foreign_net_volume_ratio_5d.iloc[13]))
        self.assertAlmostEqual(out.foreign_net_volume_ratio_5d.iloc[14], .1)
        self.assertTrue(out.foreign_net_volume_ratio_20d.isna().all())

    def test_zero_volume_does_not_create_infinite_ratios(self):
        prices, flows, days = self.fixture();prices.loc[0, 'volume'] = 0
        out = build_features(prices, flows, days)
        self.assertTrue(np.isnan(out.foreign_net_volume_ratio_1d.iloc[1]))
        self.assertFalse(np.isinf(out.select_dtypes('number')).any().any())

    def test_legacy_schema_is_rejected(self):
        prices, flows, days = self.fixture();flows.loc[0, 'foreign_schema'] = 'legacy_foreign'
        with self.assertRaises(ValueError):build_features(prices, flows, days)


if __name__ == '__main__':unittest.main()
