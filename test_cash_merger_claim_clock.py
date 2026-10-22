"""Unknown actual terms stay unknown; arithmetic uses only explicit evidence."""
import copy
from decimal import Decimal
import unittest

from cash_merger_claim_clock import (
    evaluate_claim, net_cash, payment_deadline, REQUIRED_FACTS, six_month_reference,
)


def fact(value, **extra):
    return dict(value=value, verified=True,
                evidence=[dict(path='synthetic_verified_annotation.json', clause='fixture')], **extra)


def calendar():
    # Monday26 is an explicit applicable holiday; weekdays are never inferred.
    return dict(verified=True, basis='Synthetic applicable contract-calendar evidence',
                evidence=[dict(path='synthetic_calendar.json')], start='2026-10-20', end='2026-11-06',
                business_days=['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23',
                               '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30',
                               '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06'])


def ready_case():
    return dict(contract_copy_date='2026-09-18', business_calendar=calendar(), facts={
        'current_version_at_entry': fact(True), 'all_closing_conditions': fact(True),
        'final_conversion_date': fact('2026-10-23'), 'final_consideration_per_share': fact('18.50'),
        'lawful_withholding_twd': fact('0.00'), 'eligible_registered_ordinary_shares': fact(1),
        'holder_is_buyer_or_nominee': fact(False), 'holder_exercises_dissenters_rights': fact(False),
        'holder_has_unvested_employee_shares': fact(False),
    })


class ClaimClockTests(unittest.TestCase):
    def test_ready_verified_inputs_calculate_conditional_cash_and_seventh_day_but_never_signal(self):
        result = evaluate_claim(ready_case())
        self.assertTrue(result['calculation_ready'])
        self.assertEqual(result['payment_date'], '2026-11-04')
        self.assertEqual(result['cash'], '19')
        self.assertEqual(result['original_unextended_six_month_day'], '2027-03-18')
        self.assertEqual(result['reasons'], [])
        for flag in ('source_gate_passed', 'cash_claim_source_gate_passed', 'historical_pit_verified',
                     'profit_edge_proven', 'market_prices_or_returns_read', 'orders_authorized',
                     'automatic_expiry_inferred', 'voting_bookclosure_used', 'provisional_terms_used'):
            self.assertFalse(result[flag], flag)
        self.assertIsNone(result['valid_prospective_signal_date'])

    def test_current_real_unknowns_ignore_proposals_voting_closure_and_old_copy_deadline(self):
        case = dict(contract_copy_date='2026-09-18', as_of_date='2027-03-19', facts={},
                    proposed_conversion_date='2026-12-31', proposed_consideration='18.50',
                    voting_bookclosure=['2026-10-11', '2026-11-09'])
        result = evaluate_claim(case)
        self.assertFalse(result['calculation_ready'])
        self.assertIsNone(result['payment_date'])
        self.assertIsNone(result['cash'])
        self.assertIsNone(result['termination_conclusion'])
        self.assertFalse(result['automatic_expiry_inferred'])
        self.assertEqual(result['original_unextended_six_month_day'], '2027-03-18')
        self.assertIn('final_conversion_date_unknown', result['reasons'])
        self.assertIn('final_consideration_per_share_unknown', result['reasons'])
        self.assertIn('applicable_business_calendar_unknown', result['reasons'])

    def test_every_required_actual_fact_can_block_the_whole_cash_and_date_output(self):
        for name in REQUIRED_FACTS:
            case = ready_case()
            case['facts'][name] = dict(value=None, verified=None, evidence=[])
            result = evaluate_claim(case)
            with self.subTest(name=name):
                self.assertIn(name + '_unknown', result['reasons'])
                self.assertFalse(result['calculation_ready'])
                self.assertIsNone(result['cash'])
                self.assertIsNone(result['payment_date'])

    def test_unknown_closing_condition_is_distinct_from_verified_false(self):
        case = ready_case()
        case['facts']['all_closing_conditions'] = fact(False)
        false = evaluate_claim(case)
        self.assertIn('all_closing_conditions_not_confirmed', false['reasons'])
        case['facts']['all_closing_conditions'] = fact(None)
        unknown = evaluate_claim(case)
        self.assertIn('all_closing_conditions_unknown', unknown['reasons'])
        self.assertNotEqual(false['reasons'], unknown['reasons'])
        self.assertIsNone(false['cash'])
        self.assertIsNone(unknown['cash'])

    def test_provisional_date_or_consideration_cannot_become_actual_even_if_marked_verified(self):
        for name, value in [('final_conversion_date', '2026-12-31'), ('final_consideration_per_share', '18.50')]:
            case = ready_case()
            case['facts'][name] = fact(value, provisional=True)
            result = evaluate_claim(case)
            with self.subTest(name=name):
                self.assertIn(name + '_provisional', result['reasons'])
                self.assertIsNone(result['cash'])
                self.assertIsNone(result['payment_date'])

    def test_unverified_actual_values_or_missing_evidence_are_not_accepted(self):
        for mutation in ('unverified', 'no_evidence', 'stale_version'):
            case = ready_case()
            name = 'current_version_at_entry' if mutation == 'stale_version' else 'lawful_withholding_twd'
            if mutation == 'unverified':
                case['facts'][name]['verified'] = False
            elif mutation == 'no_evidence':
                case['facts'][name]['evidence'] = []
            else:
                case['facts'][name] = fact(False)
            result = evaluate_claim(case)
            with self.subTest(mutation=mutation):
                self.assertFalse(result['calculation_ready'])
                self.assertIsNone(result['cash'])

    def test_buyer_dissenter_or_unvested_employee_is_excluded(self):
        for name in ('holder_is_buyer_or_nominee', 'holder_exercises_dissenters_rights',
                     'holder_has_unvested_employee_shares'):
            case = ready_case()
            case['facts'][name] = fact(True)
            result = evaluate_claim(case)
            with self.subTest(name=name):
                self.assertIn(name + '_excluded', result['reasons'])
                self.assertIsNone(result['cash'])
                self.assertIsNone(result['payment_date'])

    def test_base_is_excluded_and_explicit_weekend_holiday_calendar_controls_deadline(self):
        self.assertEqual(payment_deadline('2026-10-23', calendar()), '2026-11-04')
        self.assertEqual(payment_deadline('2026-10-25', calendar()), '2026-11-04')
        special = calendar()
        special['business_days'].insert(4, '2026-10-24')
        self.assertEqual(payment_deadline('2026-10-23', special), '2026-11-03')

    def test_no_default_calendar_and_inadequate_coverage_leave_cash_and_date_null(self):
        for mutation in ('missing', 'unverified', 'short', 'late_start'):
            case = ready_case()
            if mutation == 'missing':
                case['business_calendar'] = None
            elif mutation == 'unverified':
                case['business_calendar']['verified'] = False
            elif mutation == 'short':
                case['business_calendar']['business_days'] = ['2026-10-23', '2026-10-27']
            else:
                case['business_calendar']['start'] = '2026-10-27'
                case['business_calendar']['business_days'] = case['business_calendar']['business_days'][4:]
            result = evaluate_claim(case)
            with self.subTest(mutation=mutation):
                self.assertIsNone(result['payment_date'])
                self.assertIsNone(result['cash'])

    def test_invalid_duplicate_unsorted_or_unbased_calendar_is_rejected(self):
        for mutation in ('duplicate', 'unsorted', 'basis', 'evidence', 'noncanonical'):
            days = calendar()
            if mutation == 'duplicate':
                days['business_days'].append(days['business_days'][-1])
            elif mutation == 'unsorted':
                days['business_days'].reverse()
            elif mutation == 'basis':
                days['basis'] = ''
            elif mutation == 'evidence':
                days['evidence'] = []
            else:
                days['business_days'][0] = '2026-1-20'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                payment_deadline('2026-10-23', days)

    def test_deduct_before_half_up_instead_of_bankers_rounding(self):
        self.assertEqual(net_cash(1, '18.50', '0')['cash'], '19')
        self.assertEqual(net_cash(1, '18.50', '0.50')['cash'], '18')
        self.assertEqual(net_cash(3, '18.50', '1.00')['cash'], '55')
        self.assertEqual(net_cash(1, Decimal('2.50'), Decimal('0'))['cash'], '3')

    def test_integer_and_boolean_misuse_nonfinite_or_impossible_withholding_is_rejected(self):
        for shares, price, tax in [(True, '18.5', '0'), (1.0, '18.5', '0'), (0, '18.5', '0'),
                                   (1, 18.5, '0'), (1, True, '0'), (1, 'NaN', '0'),
                                   (1, '18.5', 'Infinity'), (1, '18.5', '-1'), (1, '18.5', '19')]:
            with self.subTest(shares=shares, price=price, tax=tax), self.assertRaises(ValueError):
                net_cash(shares, price, tax)
        for key in ('verified', 'value'):
            case = ready_case()
            case['facts']['all_closing_conditions'][key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                evaluate_claim(case)

    def test_verified_written_extension_is_separate_from_reference_and_never_auto_expiry(self):
        case = ready_case()
        case['written_extension'] = dict(verified=True, deadline='2027-06-18', evidence=['verified-written-amendment'])
        result = evaluate_claim(case)
        self.assertEqual(result['verified_written_extension_deadline'], '2027-06-18')
        self.assertEqual(result['original_unextended_six_month_day'], '2027-03-18')
        self.assertIsNone(result['termination_conclusion'])
        self.assertFalse(result['automatic_expiry_inferred'])
        case['written_extension']['verified'] = None
        self.assertIsNone(evaluate_claim(case)['verified_written_extension_deadline'])

    def test_six_month_reference_does_not_guess_a_month_end_legal_convention(self):
        self.assertEqual(six_month_reference('2026-09-18'), '2027-03-18')
        with self.assertRaisesRegex(ValueError, 'month-end'):
            six_month_reference('2026-08-31')


if __name__ == '__main__':
    unittest.main()
