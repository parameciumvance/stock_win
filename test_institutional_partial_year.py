import json
from pathlib import Path
import tempfile
import unittest

from twse_history.institutional import market_days_from_cache


class PartialCalendarTests(unittest.TestCase):
    def test_only_cutoff_months_are_needed_and_later_dates_are_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'calendar_202601.json').write_text(json.dumps({'stat': 'OK', 'data': [['115/01/02']]}))
            (root / 'calendar_202602.json').write_text(json.dumps({'stat': 'OK', 'data': [['115/02/02'], ['115/02/03'], ['115/02/04']]}))
            self.assertEqual(market_days_from_cache(root, 2026, '2026-02-03'),
                             ['20260102', '20260202', '20260203'])

    def test_cutoff_year_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'requested year'):
                market_days_from_cache(Path(folder), 2026, '2025-12-31')


if __name__ == '__main__':
    unittest.main()
