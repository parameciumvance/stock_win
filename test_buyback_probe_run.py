"""Synthetic runner integration and fail-closed checks; no real prices read."""
import copy
import csv
import datetime as dt
from fractions import Fraction
import io
import unittest
from unittest.mock import patch

import buyback_probe_run as runner


def source_stream(rows, columns=('date', 'symbol', 'adj_open', 'adj_close')):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    return stream


def quote(day, symbol='1210', opening='100', closing='110'):
    return dict(date=day, symbol=symbol, adj_open=opening, adj_close=closing)


def synthetic():
    start = dt.date(2023, 12, 29)
    days = [start + dt.timedelta(days=n) for n in range(435)]
    calendar = [day.isoformat() for day in days if day.weekday() < 5]
    cohort = [dict(case_id=f'case-{n}', issuer=issuer, publication_timestamp=stamp,
                   event_id=f'M35:{issuer}:{stamp[:10]}:{n}')
              for n, (issuer, stamp) in enumerate([
                  ('1210', '2024-01-02T07:00:00+08:00'),
                  ('8070', '2024-04-02T19:00:00+08:00'),
                  ('1210', '2024-07-02T19:00:00+08:00'),
                  ('6869', '2024-12-31T19:00:00+08:00'),
              ], 1)]
    quotes = {(day, issuer): quote(day, issuer, '100', '110')
              for day in calendar for issuer in {'1210', '8070', '6869'}}
    quotes.update({(day, '0050'): quote(day, '0050', '100', '101') for day in calendar})
    cfg = dict(limits=dict(cases=4), horizon_market_sessions=20,
               one_way_hypothetical_costs=['0.0025', '0.005'], primary_one_way_cost='0.005')
    return cohort, calendar, quotes, cfg


def ledger():
    cohort, _, _, _ = synthetic()
    cases = []
    for item in cohort:
        first = dict(event_id=item['event_id'], issuer=item['issuer'],
                     reported_datetime=item['publication_timestamp'], sequence=1,
                     document_form='board_resolution', explicitly_titled_revision=False)
        cases.append(dict(case_id=item['case_id'], issuer=item['issuer'], versions=[first],
                          earliest_retained_record=dict(event_id=first['event_id'],
                                                        reported_datetime=first['reported_datetime']),
                          issues=[], missing_initial_evidence=False, linkage_ambiguous=False))
    return dict(cases=cases, cases_missing_initial_evidence=0, ambiguous_case_count=0,
                unresolved_case_ids=[], duplicate_document_ids=[], unmatched_board_documents=[])


class BuybackProbeRunnerTests(unittest.TestCase):
    def test_scan_uses_all_symbol_calendar_and_keeps_decimal_text_and_0050(self):
        rows = [quote('2024-01-04'), quote('2024-01-02', '0050', '100.00000000000000001'),
                quote('2024-01-03', 'unselected'), quote('2024-01-02')]
        calendar, quotes, count = runner.scan_quotes(source_stream(rows), ['1210', '0050'])
        self.assertEqual(calendar, ['2024-01-02', '2024-01-03', '2024-01-04'])
        self.assertEqual(count, 4)
        self.assertNotIn(('2024-01-03', 'unselected'), quotes)
        self.assertEqual(quotes[('2024-01-02', '0050')]['symbol'], '0050')
        self.assertEqual(quotes[('2024-01-02', '0050')]['adj_open'], '100.00000000000000001')

    def test_duplicate_selected_quotes_fail_instead_of_last_record_winning(self):
        for symbol in ('1210', '0050'):
            rows = [quote('2024-01-02', symbol), quote('2024-01-02', symbol, '101')]
            with self.subTest(symbol=symbol), self.assertRaisesRegex(ValueError, 'Duplicate selected quote'):
                runner.scan_quotes(source_stream(rows), ['1210', '0050'])

    def test_scan_invalid_dates_columns_and_truncated_rows_fail(self):
        bad_streams = [io.StringIO('date,symbol,adj_open\n2024-01-02,1210,100\n'),
                       io.StringIO('date,symbol,adj_open,adj_open,adj_close\n2024-01-02,1210,100,100,110\n'),
                       io.StringIO('date,symbol,adj_open,adj_close\n2024-01-02,1210,100\n'),
                       source_stream([quote('2024-1-2')]), source_stream([quote('2024-02-30')]),
                       source_stream([])]
        for stream in bad_streams:
            with self.subTest(csv=stream.getvalue()), self.assertRaises(ValueError):
                runner.scan_quotes(stream, ['1210'])

    def test_nonfinite_nonpositive_and_approximate_quotes_fail(self):
        for value in ('NaN', 'Infinity', '-Infinity', '0', '-1', None, True, 1.25):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.positive_quote(value)
        for value in ('NaN', 'Infinity', '0', '-1'):
            with self.subTest(scan=value), self.assertRaises(ValueError):
                runner.scan_quotes(source_stream([quote('2024-01-02', opening=value)]), ['1210'])

    def test_complete_fixed_cohort_two_costs_uses_independent_fraction_formula(self):
        cohort, calendar, quotes, cfg = synthetic()
        records, scenarios, summary = runner.calculate(cohort, calendar, quotes, cfg)
        self.assertEqual(len(records), 4)
        self.assertEqual(len(scenarios), 8)
        self.assertTrue(summary['coverage_complete'])
        self.assertTrue(summary['resource_allocation_gate_passed'])
        for cost in cfg['one_way_hypothetical_costs']:
            self.assertEqual(summary['costs'][cost]['case_ids'], sorted(c['case_id'] for c in cohort))
        for scenario in scenarios:
            cost = Fraction(scenario['cost'])
            expected_stock = Fraction(110, 100) * (1 - cost) / (1 + cost) - 1
            expected_benchmark = Fraction(101, 100) * (1 - cost) / (1 + cost) - 1
            self.assertLess(abs(Fraction(scenario['stock_change']) - expected_stock), Fraction(1, 10**45))
            self.assertLess(abs(Fraction(scenario['benchmark_change']) - expected_benchmark), Fraction(1, 10**45))
            self.assertLess(abs(Fraction(scenario['relative_change']) - (expected_stock - expected_benchmark)),
                            Fraction(1, 10**45))
        self.assertFalse(summary['historical_pit_verified'])
        self.assertFalse(summary['profit_edge_proven'])
        self.assertFalse(summary['valid_signal'])
        self.assertIsNone(summary['valid_prospective_signal_date'])

    def test_preopen_and_late2024_endpoint_rules_keep_publication_quarter(self):
        records, _, summary = runner.calculate(*synthetic())
        self.assertEqual((records[0]['entry_date'], records[0]['exit_date']),
                         ('2024-01-03', '2024-01-30'))
        self.assertEqual((records[-1]['entry_date'], records[-1]['exit_date']),
                         ('2025-01-01', '2025-01-28'))
        self.assertEqual(summary['costs']['0.005']['quarters']['2024Q4']['event_count'], 1)
        self.assertNotIn('2025Q1', summary['costs']['0.005']['quarters'])

    def test_each_missing_endpoint_blocks_whole_gate_without_shifting(self):
        for symbol, day, column in [('1210', '2024-01-03', 'adj_open'),
                                    ('1210', '2024-01-30', 'adj_close'),
                                    ('0050', '2024-01-03', 'adj_open'),
                                    ('0050', '2024-01-30', 'adj_close')]:
            cohort, calendar, quotes, cfg = synthetic()
            quotes[(day, symbol)][column] = ''
            records, scenarios, summary = runner.calculate(cohort, calendar, quotes, cfg)
            with self.subTest(symbol=symbol, day=day, column=column):
                self.assertFalse(summary['coverage_complete'])
                self.assertFalse(summary['resource_allocation_gate_passed'])
                self.assertEqual(len(scenarios), 6)
                self.assertEqual(summary['gaps'][0]['case_id'], 'case-1')
                self.assertEqual(summary['gaps'][0]['missing'][0]['date'], day)
                self.assertEqual((records[0]['entry_date'], records[0]['exit_date']),
                                 ('2024-01-03', '2024-01-30'))

    def test_halt_on_global_entry_day_does_not_shorten_calendar(self):
        cohort, calendar, quotes, cfg = synthetic()
        del quotes[('2024-01-03', '1210')]
        records, _, summary = runner.calculate(cohort, calendar, quotes, cfg)
        self.assertEqual(records[0]['entry_date'], '2024-01-03')
        self.assertEqual(records[0]['exit_date'], '2024-01-30')
        self.assertFalse(summary['coverage_complete'])
        self.assertEqual(summary['gaps'][0]['missing'][0]['date'], '2024-01-03')

    def test_missing_horizon_or_duplicate_calendar_fails_not_subset_calculation(self):
        for replacement in (['2023-12-29', '2024-01-02', '2024-01-03'],
                            ['2023-12-29', '2024-01-02', '2024-01-02']):
            cohort, _, quotes, cfg = synthetic()
            with self.subTest(calendar=replacement), self.assertRaises(ValueError):
                runner.calculate(cohort, replacement, quotes, cfg)

    def test_population_mismatch_and_duplicate_case_ids_are_rejected(self):
        cohort, calendar, quotes, cfg = synthetic()
        for rows in (cohort[:-1], cohort[:3] + [cohort[0]]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, 'cohort population'):
                runner.calculate(rows, calendar, quotes, cfg)

    def test_source_cohort_rejects_revision_missing_ambiguity_and_duplicate_event(self):
        self.assertEqual(len(runner.cohort_from_ledger(ledger(), expected=4)), 4)
        for failure in ('revision', 'missing', 'ambiguous', 'unmatched', 'empty_versions', 'duplicate_event'):
            source = ledger()
            if failure == 'revision':
                source['cases'][0]['versions'][0]['explicitly_titled_revision'] = True
            elif failure == 'missing':
                source['cases_missing_initial_evidence'] = 1
            elif failure == 'ambiguous':
                source['cases'][0]['linkage_ambiguous'] = True
            elif failure == 'unmatched':
                source['unmatched_board_documents'] = [{'event_id': 'unlinked'}]
            elif failure == 'empty_versions':
                source['cases'][0]['versions'] = []
            else:
                duplicate = source['cases'][0]['versions'][0]['event_id']
                source['cases'][1]['versions'][0]['event_id'] = duplicate
                source['cases'][1]['earliest_retained_record']['event_id'] = duplicate
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                runner.cohort_from_ledger(source, expected=4)

    def test_earliest_retained_source_cannot_skip_a_revision_for_later_initial(self):
        source = ledger()
        first = source['cases'][0]['versions'][0]
        earlier = dict(first, event_id='earlier-revision', reported_datetime='2024-01-01T23:00:00+08:00',
                       explicitly_titled_revision=True)
        source['cases'][0]['versions'].append(earlier)
        with self.assertRaisesRegex(ValueError, 'Earliest record'):
            runner.cohort_from_ledger(source, expected=4)

    def test_activation_failure_precedes_any_archive_or_quote_read(self):
        with patch.object(runner, 'require_activation', side_effect=ValueError('source changed')), \
             patch.object(runner, 'verified_bundle') as bundle, \
             patch.object(runner.zipfile, 'ZipFile') as archive:
            with self.assertRaisesRegex(ValueError, 'source changed'):
                runner.extract()
            bundle.assert_not_called()
            archive.assert_not_called()

    def test_activation_protocol_checkpoint_and_prior_sha_drift_fail_before_source_replay(self):
        cfg = {'source_checkpoint': 'synthetic-source-checkpoint'}
        receipt = dict(protocol_sha256='policy-sha', source_checkpoint_sha256='source-sha',
                       prior_checkpoints={'synthetic-prior': 'prior-sha'})
        original = {str(runner.POLICY): 'policy-sha', 'synthetic-source-checkpoint': 'source-sha',
                    'synthetic-prior': 'prior-sha'}
        for changed in original:
            digests = dict(original, **{changed: 'changed'})
            with self.subTest(path=changed), patch.object(runner, 'policy', return_value=cfg), \
                 patch.object(runner, 'read', return_value=receipt), \
                 patch.object(runner, 'sha256', side_effect=lambda path: digests[str(path)]), \
                 patch.object(runner, 'source_state') as source:
                with self.assertRaisesRegex(ValueError, 'Activation receipt hash drift'):
                    runner.require_activation()
                source.assert_not_called()

    def test_extracted_quote_sha_drift_blocks_calculation(self):
        receipt = dict(calendar_sha256='expected-calendar', quotes_sha256='expected-quotes',
                       activation_receipt_sha256='expected-activation')
        with patch.object(runner, 'require_activation', return_value=({}, [])), \
             patch.object(runner, 'read', return_value=receipt), \
             patch.object(runner, 'sha256', return_value='changed'), \
             patch.object(runner, 'calculate') as calculate:
            with self.assertRaisesRegex(ValueError, 'Extracted price input drift'):
                runner.replay()
            calculate.assert_not_called()

    def test_calculation_does_not_mutate_inputs_or_reset_reuse_disclosures(self):
        inputs = synthetic()
        before = copy.deepcopy(inputs)
        _, _, summary = runner.calculate(*inputs)
        self.assertEqual(inputs, before)
        self.assertFalse(summary['independent_holdout'])
        self.assertFalse(summary['samples_independent'])
        self.assertEqual(summary['reused_historical_years'], [2024])


if __name__ == '__main__':
    unittest.main()
