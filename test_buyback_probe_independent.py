import datetime as dt
import copy
from fractions import Fraction
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from buyback_probe_independent import (expected_window, file_hash, fraction_change,
                                      resource_metrics, scan_pinned_quotes, verify_statistics)


class IndependentProbeFaultTests(unittest.TestCase):
    def test_independent_raw_scan_keeps_market_day_when_selected_benchmark_has_no_row(self):
        data = gzip.compress(b'date,symbol,adj_open,adj_close\n2024-01-02,0050,10,11\n'
                             b'2024-01-03,9999,20,21\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'quotes.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('quotes.csv.gz', data)
            policy = {'prices': dict(price_archive=str(path), price_archive_sha256=file_hash(path),
                                     price_member='quotes.csv.gz', price_sha256=hashlib.sha256(data).hexdigest())}
            calendar, selected, rows = scan_pinned_quotes(policy, {'0050'})
            self.assertEqual(calendar, ['2024-01-02', '2024-01-03'])
            self.assertEqual(selected, {('2024-01-02', '0050'): ('10', '11')})
            self.assertEqual(rows, 2)

    def test_preopen_publication_still_waits_next_market_date_and_entry_is_first_session(self):
        days = [(dt.date(2024, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(25)]
        self.assertEqual(expected_window(days, '2024-01-01T06:30:00+08:00'),
                         ('2024-01-02', '2024-01-21'))
        self.assertEqual(expected_window(days, '2024-01-01T23:59:59+08:00'),
                         ('2024-01-02', '2024-01-21'))

    def test_holiday_has_no_phantom_session_and_insufficient_tail_is_not_shifted(self):
        days = ['2024-01-05', '2024-01-08', '2024-01-09']
        self.assertEqual(expected_window(days, '2024-01-06T12:00:00+08:00', 2),
                         ('2024-01-08', '2024-01-09'))
        with self.assertRaises(ValueError):
            expected_window(days, '2024-01-08T06:00:00+08:00', 2)
        for invalid in [days + ['2024-01-09'], days[::-1]]:
            with self.assertRaises(ValueError):
                expected_window(invalid, '2024-01-05T12:00:00+08:00', 1)
        with self.assertRaises(ValueError):
            expected_window(days, '2024-01-05T23:00:00+00:00', 1)

    def test_buy_and_sell_cost_is_exact_ratio_not_subtracted_twice(self):
        result = fraction_change('100', '100', '0.005')
        self.assertEqual(result, Fraction(-2, 201))
        self.assertNotEqual(result, Fraction('-0.01'))
        for bad_entry in ['0', '-1', 'NaN', 'inf', True]:
            with self.assertRaises(ValueError):
                fraction_change(bad_entry, '100', '0.005')

    def test_three_positive_quarters_do_not_override_negative_pooled_event_median(self):
        values = {'2024Q1': [Fraction(1)], '2024Q2': [Fraction(1)],
                  '2024Q3': [Fraction(1)], '2024Q4': [Fraction('-0.01')] * 10}
        means, pooled_median, passed = resource_metrics(values, True)
        self.assertEqual(sum(value > 0 for value in means.values()), 3)
        self.assertEqual(pooled_median, Fraction('-0.01'))
        self.assertFalse(passed)

    def test_missing_quarter_or_missing_endpoint_cannot_pass_resource_gate(self):
        values = {f'2024Q{q}': [Fraction(1)] for q in range(1, 5)}
        self.assertTrue(resource_metrics(values, True)[2])
        self.assertFalse(resource_metrics(values, False)[2])
        values.pop('2024Q4')
        self.assertFalse(resource_metrics(values, True)[2])

    def test_summary_audit_rejects_issuer_weighting_instead_of_event_weighting(self):
        records = [dict(issuer=issuer, stock_change=Fraction(value), benchmark_change=Fraction(0),
                        relative_change=Fraction(value)) for issuer, value in [('A', 1), ('A', 3), ('B', 7)]]
        declared = dict(event_count=3, issuer_count=2,
                        mean_stock_change='11/3', mean_benchmark_change='0', mean_relative_change='11/3',
                        median_stock_change='3', median_benchmark_change='0', median_relative_change='3',
                        issuer_means={
                            'A': dict(event_count=2, mean_stock_change='2', mean_benchmark_change='0', mean_relative_change='2'),
                            'B': dict(event_count=1, mean_stock_change='7', mean_benchmark_change='0', mean_relative_change='7'),
                        })
        verify_statistics(records, declared)
        wrong = copy.deepcopy(declared)
        wrong['mean_relative_change'] = '4.5'  # (issuer A mean2 + issuer B mean7)/2
        with self.assertRaises(ValueError):
            verify_statistics(records, wrong)


if __name__ == '__main__':
    unittest.main()
