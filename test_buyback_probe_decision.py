"""Logical completion bounds use synthetic audited artifacts, never new quotes."""
import copy
import csv
from decimal import Decimal
import hashlib
import io
import json
import unittest

from buyback_probe_decision import COSTS, SCENARIO_COLUMNS, decide
from buyback_quote_probe import aggregate


def seal(scenarios, summary, audit):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=SCENARIO_COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(scenarios)
    audit['artifact_sha256'] = {
        'summary.json': hashlib.sha256((json.dumps(summary, indent=2, allow_nan=False) + '\n').encode()).hexdigest(),
        'event_scenarios.csv': hashlib.sha256(stream.getvalue().encode()).hexdigest(),
    }


def fixture(missing=('q4b',), fourth='-0.02'):
    cohort, scenarios = [], []
    for quarter, relative in enumerate(('-0.10', '-0.05', '0.04', fourth), 1):
        for suffix in ('a', 'b'):
            identity = f'q{quarter}{suffix}'
            case = dict(case_id=identity, issuer='1210',
                        publication_timestamp=f'2024-{3 * quarter - 2:02d}-02T19:00:00+08:00')
            cohort.append(case)
            if identity not in missing:
                scenarios.extend(dict(**case, cost=cost, stock_change=relative,
                                      benchmark_change='0', relative_change=relative) for cost in COSTS)
    summary = aggregate(scenarios)
    complete = not missing
    summary.update(expected_case_ids=sorted(c['case_id'] for c in cohort), case_count=8,
                   scenario_count=len(scenarios), coverage_complete=complete,
                   coverage_verified_by_caller=complete,
                   resource_allocation_gate_passed=complete and summary['primary_distribution_rule_passed'],
                   gaps=[dict(case_id=identity, missing=[{'endpoint': 'stock_entry'}]) for identity in missing],
                   protocol_sha256='synthetic-frozen-protocol')
    audit = dict(status='passed', protocol_sha256='synthetic-frozen-protocol',
                 event_cases_verified=8, publication_endpoint_windows_verified=8,
                 endpoints=[dict(case_id=case['case_id'], endpoint_gaps=(['stock_entry'] if case['case_id'] in missing else []))
                            for case in cohort],
                 gap_case_ids=sorted(missing), complete_endpoint_cases=8 - len(missing),
                 scenario_return_rows_verified=len(scenarios), absolute_numeric_tolerance='1e-45',
                 maximum_absolute_numeric_error='0', historical_pit_verified=False,
                 profit_edge_proven=False, actual_execution_verified=False,
                 valid_signal=False, valid_prospective_signal_date=None)
    seal(scenarios, summary, audit)
    return cohort, scenarios, summary, audit


class BuybackProbeDecisionTests(unittest.TestCase):
    def decision(self, fixture_values):
        return decide(*fixture_values, expected_case_count=8)

    def test_two_complete_negative_quarters_make_three_positive_quarters_unattainable(self):
        result = self.decision(fixture())
        self.assertEqual(result['decision'], 'stop_fixed_hypothesis_no_extra_data_needed_to_decide')
        self.assertEqual(result['maximum_positive_quarters_after_any_completion'], 2)
        self.assertTrue(result['fixed_gate_unattainable_even_if_missing_quotes_supplied'])
        self.assertFalse(result['coverage_complete'])
        self.assertFalse(result['full_cohort_quote_results_known'])
        self.assertIsNone(result['full_cohort_pooled_mean_relative_change'])
        self.assertIsNone(result['full_cohort_pooled_median_relative_change'])
        self.assertFalse(result['unknown_values_imputed'])
        for cost in COSTS:
            bound = result['cost_bounds'][cost]
            self.assertEqual(bound['complete_nonpositive_quarters'], ['2024Q1', '2024Q2'])
            self.assertEqual(bound['possible_positive_quarters'], ['2024Q3', '2024Q4'])
            self.assertEqual(bound['quarters']['2024Q4']['missing_case_ids'], ['q4b'])

    def test_counterexample_missing_q1_can_allow_three_quarters_and_must_stay_inconclusive(self):
        result = self.decision(fixture(missing=('q1b',), fourth='0.03'))
        self.assertEqual(result['maximum_positive_quarters_after_any_completion'], 3)
        self.assertFalse(result['fixed_gate_unattainable_even_if_missing_quotes_supplied'])
        self.assertEqual(result['decision'], 'inconclusive_missing_quotes_may_change_fixed_gate')
        self.assertFalse(result['resource_allocation_gate_passed'])

    def test_multiple_missing_values_in_one_quarter_only_add_one_possible_positive_quarter(self):
        result = self.decision(fixture(missing=('q4a', 'q4b')))
        self.assertEqual(result['maximum_positive_quarters_after_any_completion'], 2)
        quarter = result['cost_bounds']['0.005']['quarters']['2024Q4']
        self.assertEqual(quarter['observed_case_ids'], [])
        self.assertEqual(quarter['missing_case_ids'], ['q4a', 'q4b'])
        self.assertIsNone(quarter['observed_mean_relative_change'])
        self.assertTrue(quarter['positive_after_completion_possible'])

    def test_gaps_in_two_quarters_increase_the_bound_by_two_not_observation_count(self):
        result = self.decision(fixture(missing=('q1b', 'q4b')))
        self.assertEqual(result['maximum_positive_quarters_after_any_completion'], 3)
        self.assertFalse(result['no_extra_data_needed_to_decide_fixed_gate'])

    def test_changed_artifact_after_successful_audit_is_rejected(self):
        for target in ('summary', 'scenario'):
            values = fixture()
            if target == 'summary':
                values[2]['case_count'] = 999
            else:
                values[1][0]['relative_change'] = '0.90'
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'Audited .* bytes mismatch'):
                self.decision(values)

    def test_missing_cost_case_duplicate_and_wrong_cost_fail_even_with_resealed_bytes(self):
        for failure in ('missing_cost', 'duplicate', 'wrong_cost', 'outside_case'):
            cohort, scenarios, summary, audit = fixture()
            if failure == 'missing_cost':
                scenarios.pop(0)
            elif failure == 'duplicate':
                scenarios.append(dict(scenarios[0]))
            elif failure == 'wrong_cost':
                scenarios[0]['cost'] = '0.001'
            else:
                scenarios[0]['case_id'] = 'not-in-frozen-cohort'
            seal(scenarios, summary, audit)
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                decide(cohort, scenarios, summary, audit, expected_case_count=8)

    def test_quarter_summary_population_and_mean_mismatch_fail(self):
        for field, value in (('event_count', 3), ('mean_relative_change', '0.10')):
            cohort, scenarios, summary, audit = fixture()
            summary['costs']['0.005']['quarters']['2024Q1'][field] = value
            seal(scenarios, summary, audit)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Quarter count or audited mean'):
                decide(cohort, scenarios, summary, audit, expected_case_count=8)

    def test_scenario_issuer_publication_and_cost_summary_exact_ids_are_verified(self):
        for failure in ('issuer', 'publication', 'summary_case_ids'):
            cohort, scenarios, summary, audit = fixture()
            if failure == 'issuer':
                scenarios[0]['issuer'] = 'wrong'
            elif failure == 'publication':
                scenarios[0]['publication_timestamp'] = '2024-04-02T19:00:00+08:00'
            else:
                summary['costs']['0.005']['case_ids'][0] = 'unverified-case'
            seal(scenarios, summary, audit)
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                decide(cohort, scenarios, summary, audit, expected_case_count=8)

    def test_audit_gap_endpoint_and_count_mismatch_are_rejected(self):
        for failure in ('gap', 'endpoint', 'count', 'status'):
            cohort, scenarios, summary, audit = fixture()
            if failure == 'gap':
                audit['gap_case_ids'] = ['q1b']
            elif failure == 'endpoint':
                audit['endpoints'][0]['case_id'] = 'outside-case'
            elif failure == 'count':
                audit['complete_endpoint_cases'] = 8
            else:
                audit['status'] = 'failed'
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                decide(cohort, scenarios, summary, audit, expected_case_count=8)

    def test_numerically_uncertain_zero_is_conservatively_allowed_to_be_positive(self):
        values = fixture(missing=('q4b',))
        cohort, scenarios, summary, audit = values
        for row in scenarios:
            if row['case_id'].startswith('q2'):
                row['stock_change'] = row['relative_change'] = '0'
        new = aggregate(scenarios)
        for key in ('costs', 'primary_positive_mean_relative_quarters',
                    'primary_pooled_median_relative_positive', 'primary_distribution_rule_passed'):
            summary[key] = new[key]
        seal(scenarios, summary, audit)
        result = decide(cohort, scenarios, summary, audit, expected_case_count=8)
        self.assertEqual(result['maximum_positive_quarters_after_any_completion'], 3)
        self.assertFalse(result['fixed_gate_unattainable_even_if_missing_quotes_supplied'])

    def test_unqualified_flags_remain_false_and_input_objects_unchanged(self):
        values = fixture()
        before = copy.deepcopy(values)
        result = self.decision(values)
        self.assertEqual(values, before)
        for flag in ('historical_pit_verified', 'profit_edge_proven', 'actual_execution_verified',
                     'valid_signal', 'trade_authorized', 'daily_human_validation',
                     'samples_independent', 'independent_holdout'):
            self.assertFalse(result[flag], flag)
        self.assertIsNone(result['valid_prospective_signal_date'])
        self.assertEqual(result['new_public_requests'], 0)
        self.assertEqual(result['parameter_changes'], 0)


if __name__ == '__main__':
    unittest.main()
