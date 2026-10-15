import json
from datetime import datetime
from zoneinfo import ZoneInfo
import tempfile
import unittest
from pathlib import Path
import pandas as pd

from prospective_selection import select, validate_snapshot_refs
from prospective_journal import seal


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = json.loads(Path('configs/tpex_prospective_protocol.json').read_text())

    def matrix(self):
        return pd.DataFrame([dict(date='2026-10-14', code=f'{i:04}', mom1=.01, mom5=.02,
                                  mom20=.03, mom60=.1, vol20=.2, atr20_pct=.05,
                                  volume_ratio20=1.6, breakout60_volume15=1 if i % 3 == 0 else 0,
                                  institutional_five_days=1 if i % 2 == 0 else 0,
                                  revenue_acceleration=1 if i % 4 == 0 else 0,
                                  flow_source_date='2026-10-13', proxy_available_date='2026-09-15',
                                  month_end='2026-07-31') for i in range(100, 0, -1)])

    def test_seven_methods_same_pool_and_tie_order(self):
        result = select(self.matrix(), '2026-10-14', self.protocol)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['common_pool'], 100)
        self.assertEqual(result['selections']['all_three'], ['0012', '0024', '0036', '0048', '0060', '0072', '0084', '0096'])
        self.assertEqual(result['selections']['vol20'], [f'{i:04}' for i in range(1, 11)])
        self.assertEqual(set(result['selections']), set(self.protocol['methods']))

    def test_missing_flow_does_not_fill_zero(self):
        frame = self.matrix(); frame.loc[0, 'institutional_five_days'] = None
        result = select(frame, '2026-10-14', self.protocol)
        self.assertEqual(result['status'], 'insufficient_pool')
        self.assertEqual(result['common_pool'], 99)

    def test_future_label_cannot_filter_pool(self):
        frame = self.matrix(); frame['target60'] = 1
        with self.assertRaisesRegex(ValueError, 'Future outcome'): select(frame, '2026-10-14', self.protocol)

    def test_same_day_flow_and_early_revenue_rejected(self):
        frame = self.matrix(); frame.loc[0, 'flow_source_date'] = '2026-10-14'
        with self.assertRaisesRegex(ValueError, 'same-day'): select(frame, '2026-10-14', self.protocol)
        frame = self.matrix(); frame.loc[0, 'proxy_available_date'] = '2026-09-14'
        with self.assertRaisesRegex(ValueError, 'frozen lag'): select(frame, '2026-10-14', self.protocol)

    def test_missing_raw_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            seal(root, 'snapshot', 's1', {'raw_sha256': '0'*64}, now=datetime(2026, 10, 14, 16, tzinfo=ZoneInfo('Asia/Taipei')))
            with self.assertRaises(FileNotFoundError): validate_snapshot_refs(root, ['s1'], '2026-10-14')


if __name__ == '__main__': unittest.main()
