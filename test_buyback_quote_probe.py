"""Pure fixed-endpoint and cost-screen tests using synthetic numbers only."""
import copy
import datetime as dt
from decimal import Decimal, localcontext
import unittest

from buyback_quote_probe import aggregate, endpoints, quote_change


def calendar():
    # Synthetic weekdays, not an asserted Taiwan exchange calendar.
    start = dt.date(2024, 1, 1)
    days = [start + dt.timedelta(days=offset) for offset in range(100)]
    return [day.isoformat() for day in days if day.weekday() < 5]


def event(case, quarter, stock='0.02', benchmark='0.01', cost='0.005', issuer='1210'):
    return dict(case_id=case, issuer=issuer,
                publication_timestamp=f'2024-{3 * quarter - 2:02d}-02T19:30:00+08:00',
                cost=cost, stock_change=stock, benchmark_change=benchmark)


class BuybackQuoteProbeTests(unittest.TestCase):
    def assert_closed(self, value):
        for field in ('historical_pit_verified', 'profit_edge_proven', 'actual_execution_verified',
                      'valid_signal', 'resource_allocation_gate_passed', 'coverage_verified_by_caller',
                      'samples_independent', 'independent_holdout', 'multiple_research_attempts_reset'):
            self.assertFalse(value[field], field)
        self.assertIsNone(value['valid_prospective_signal_date'])
        self.assertEqual(value['reused_historical_years'], [2024])

    def test_preopen_publication_still_enters_strictly_next_market_day(self):
        entry, exit = endpoints(calendar(), '2024-01-02T07:00:00+08:00')
        self.assertEqual(entry, '2024-01-03')
        self.assertEqual(exit, '2024-01-30')

    def test_weekend_waits_until_next_session_and_horizon_includes_entry(self):
        entry, exit = endpoints(calendar(), '2024-01-06T12:00:00+08:00')
        self.assertEqual(entry, '2024-01-08')
        self.assertEqual(exit, '2024-02-02')
        self.assertEqual(endpoints(calendar(), '2024-01-06T12:00:00+08:00', horizon=1),
                         ('2024-01-08', '2024-01-08'))

    def test_timezone_is_converted_before_determining_publication_day(self):
        # UTC Jan 2 17:00 is Taipei Jan 3, so entry is Jan 4.
        self.assertEqual(endpoints(calendar(), '2024-01-02T17:00:00+00:00')[0], '2024-01-04')

    def test_missing_short_unsorted_duplicate_or_invalid_calendar_fails(self):
        values = calendar()
        bad = ([], None, values[:10], list(reversed(values)),
               [values[0]] + values, ['2024-01-01', '2024-02-30'],
               [1.0], ['2024-1-1'])
        for days in bad:
            with self.subTest(days=str(days)[:80]), self.assertRaises(ValueError):
                endpoints(days, '2024-01-02T19:00:00+08:00')
        for stamp in ('2023-12-31T19:00:00+08:00', '2024-12-31T19:00:00+08:00'):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                endpoints(values, stamp)

    def test_timestamp_and_horizon_require_explicit_valid_values(self):
        for stamp in ('2024-01-02T07:00:00', 'not a timestamp', 1.0):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                endpoints(calendar(), stamp)
        for horizon in (0, -1, True, 20.0, '20'):
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                endpoints(calendar(), '2024-01-02T07:00:00+08:00', horizon)

    def test_quote_change_uses_both_cost_legs_and_exact_source_decimals(self):
        with localcontext() as context:
            context.prec = 50
            expected = Decimal('105.25') / Decimal('100.01') * Decimal('0.995') / Decimal('1.005') - 1
        self.assertEqual(quote_change('100.01', Decimal('105.25'), '0.005'), expected)
        self.assertEqual(quote_change(100, 110, 0), Decimal('0.1'))
        self.assertLess(quote_change('100', '100', '0.0025'), 0)

    def test_invalid_quotes_costs_and_float_approximations_fail(self):
        for price in (None, 1.0, True, 'NaN', 'Infinity', '-Infinity', '0', '-1', 'bad'):
            with self.subTest(price=price), self.assertRaises(ValueError):
                quote_change(price, '100', '0.005')
            with self.subTest(exit=price), self.assertRaises(ValueError):
                quote_change('100', price, '0.005')
        for cost in (0.005, True, 'NaN', 'Infinity', '-0.1', '1', '2', None):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                quote_change('100', '101', cost)

    def test_missing_price_does_not_choose_another_date(self):
        fixed = endpoints(calendar(), '2024-01-02T19:00:00+08:00')
        with self.assertRaises(ValueError):
            quote_change(None, '100', '0.005')
        self.assertEqual(endpoints(calendar(), '2024-01-02T19:00:00+08:00'), fixed)

    def test_all_quarters_and_primary_positive_distribution_rule(self):
        rows = [event(str(quarter), quarter) for quarter in range(1, 5)]
        result = aggregate(rows)
        self.assertTrue(result['primary_distribution_rule_passed'])
        self.assertEqual(result['primary_positive_mean_relative_quarters'],
                         ['2024Q1', '2024Q2', '2024Q3', '2024Q4'])
        summary = result['costs']['0.005']
        self.assertEqual(summary['event_count'], 4)
        self.assertEqual(Decimal(summary['mean_relative_change']), Decimal('0.01'))
        self.assertEqual(Decimal(summary['median_relative_change']), Decimal('0.01'))
        self.assertEqual(summary['issuer_means']['1210']['event_count'], 4)
        self.assert_closed(result)

    def test_mean_median_and_issuer_means_are_distinct(self):
        rows = [event('a', 1, stock='0.03'), event('b', 1, stock='0.01'),
                event('c', 1, stock='0.09', issuer='8070')]
        result = aggregate(rows)
        values = result['costs']['0.005']['quarters']['2024Q1']
        with localcontext() as context:
            context.prec = 50
            expected_mean = Decimal('0.10') / 3
        self.assertEqual(Decimal(values['mean_relative_change']), expected_mean)
        self.assertEqual(Decimal(values['median_relative_change']), Decimal('0.02'))
        self.assertEqual(Decimal(values['issuer_means']['1210']['mean_relative_change']), Decimal('0.01'))
        self.assertEqual(Decimal(values['issuer_means']['8070']['mean_relative_change']), Decimal('0.08'))
        self.assertFalse(result['primary_distribution_rule_passed'])

    def test_three_positive_quarters_pass_only_with_positive_pooled_median(self):
        rows = [event(str(q), q, stock=('0.00' if q == 4 else '0.02')) for q in range(1, 5)]
        self.assertTrue(aggregate(rows)['primary_distribution_rule_passed'])
        # Two negative observations in one quarter drive the pooled median to zero.
        rows.append(event('another-negative', 4, stock='0.00'))
        rows.append(event('third-negative', 4, stock='0.00'))
        result = aggregate(rows)
        self.assertEqual(len(result['primary_positive_mean_relative_quarters']), 3)
        self.assertFalse(result['primary_pooled_median_relative_positive'])
        self.assertFalse(result['primary_distribution_rule_passed'])

    def test_low_cost_success_never_replaces_failed_primary_cost(self):
        rows = [event(str(q), q, stock='0.02', cost='0.0025') for q in range(1, 5)]
        rows += [event(str(q), q, stock='0.00', cost='0.005') for q in range(1, 5)]
        result = aggregate(rows)
        self.assertEqual(result['primary_cost'], '0.005')
        self.assertEqual(set(result['costs']), {'0.0025', '0.005'})
        self.assertFalse(result['primary_distribution_rule_passed'])
        self.assertEqual(result['primary_positive_mean_relative_quarters'], [])
        self.assert_closed(result)

    def test_empty_missing_primary_or_missing_quarter_does_not_pass(self):
        for rows in ([], [event(str(q), q, cost='0.0025') for q in range(1, 5)],
                     [event(str(q), q) for q in range(1, 4)]):
            result = aggregate(rows)
            self.assertFalse(result['primary_distribution_rule_passed'])
            self.assertTrue(result['primary_missing_quarters'])
            self.assert_closed(result)

    def test_duplicate_case_cost_or_changed_case_identity_fails(self):
        first = event('a', 1)
        for second in (event('a', 1, cost='0.0050'),
                       event('a', 1, cost='0.0025', issuer='other'),
                       event('a', 2, cost='0.0025')):
            with self.subTest(second=second), self.assertRaises(ValueError):
                aggregate([first, second])

    def test_non2024_events_bad_values_and_float_changes_fail(self):
        for change in ({'publication_timestamp': '2025-01-02T19:00:00+08:00'},
                       {'stock_change': 0.02}, {'benchmark_change': 'NaN'},
                       {'cost': 0.005}, {'case_id': ''}):
            row = event('a', 1)
            row.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                aggregate([row])

    def test_publication_quarter_uses_taipei_and_inputs_remain_unchanged(self):
        row = event('a', 2)
        row['publication_timestamp'] = '2024-03-31T17:30:00Z'
        rows = [row]
        before = copy.deepcopy(rows)
        result = aggregate(rows)
        self.assertEqual(set(result['costs']['0.005']['quarters']), {'2024Q2'})
        self.assertEqual(rows, before)


if __name__ == '__main__':
    unittest.main()
