import unittest

import numpy as np
import pandas as pd

from audit_institutional_increment import PRICE_FEATURES, FLOW_FEATURES
from audit_institutional_pool import audit


class PoolSelectionTests(unittest.TestCase):
    def test_unknown_future_target_preserves_asof_top_instead_of_replacing_it(self):
        candidates = pd.DataFrame({'date': pd.to_datetime(['2024-01-02'] * 3),
            'symbol': ['A', 'B', 'C'], 'eligible': True,
            'target': [np.nan, .02, .01], 'endpoint_target': [.03, .02, .01]})
        for name in PRICE_FEATURES + FLOW_FEATURES:
            candidates[name] = 1.
        candidates['r1'] = [3., 2., 1.]
        model = {'features': ['r1'], 'scaler_mean': [0.], 'scaler_scale': [1.],
                 'ridge_coefficients': [1.], 'ridge_intercept': 0.}
        config = {'train_cutoff': '2023-12-29', 'top_fraction': .3}
        row = audit(candidates, {'model': model}, config, 'test').iloc[0]
        self.assertEqual(row.model_missing_target_in_top, 1)
        self.assertEqual(row.model_missing_endpoints_in_top, 0)
        self.assertEqual(row.model_top_overlap, 0)
        self.assertTrue(pd.isna(row.model_asof_top_mean))
        self.assertAlmostEqual(row.model_endpoint_top_mean, .03)
        self.assertAlmostEqual(row.model_future_filtered_top_mean, .02)


if __name__ == '__main__':
    unittest.main()
