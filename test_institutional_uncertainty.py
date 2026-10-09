import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from audit_institutional_uncertainty import circular_block_intervals, load_daily, SCORES


class UncertaintyBoundaryTests(unittest.TestCase):
    def test_pairing_preserves_constant_increment_under_noisy_returns(self):
        noisy = np.random.default_rng(2).normal(size=100)
        paired_difference = noisy + .003 - noisy
        result = circular_block_intervals(paired_difference[:, None], 20, 500, 1)[0]
        self.assertAlmostEqual(result["mean"], .003)
        self.assertAlmostEqual(result["lower_95"], .003)
        self.assertAlmostEqual(result["upper_95"], .003)

    def test_nonfinite_and_too_long_blocks_rejected(self):
        with self.assertRaises(ValueError):
            circular_block_intervals(np.array([[np.nan], [0]]), 1, 500, 1)
        with self.assertRaises(ValueError):
            circular_block_intervals(np.ones((20, 1)), 20, 500, 1)

    def test_duplicate_dates_and_changed_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "daily.csv"
            rows = {"date": ["2024-01-02", "2024-01-02"], "pool": [100, 100],
                    "top_count": [10, 10], "pool_net_relative": [.01, .01]}
            for score in SCORES:
                rows[score + "_top_net_relative"] = [.02, .02]
                rows[score + "_rank_ic"] = [.01, .01]
            pd.DataFrame(rows).to_csv(p, index=False)
            cfg = {"daily_input": str(p), "expected_daily_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                   "expected_dates": 2}
            with self.assertRaisesRegex(ValueError, "distinct"):
                load_daily(cfg)
            p.write_bytes(p.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_daily(cfg)


if __name__ == "__main__":
    unittest.main()

