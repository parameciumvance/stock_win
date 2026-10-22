"""Independent rational/date-enumeration checks and rejection of the pending case.

Synthetic arithmetic examples are not stock quotations, an applicable payment
calendar or an executable cash claim. No production tests are imported.
"""
import argparse
import copy
import datetime as dt
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from cash_merger_claim_clock import evaluate_claim, net_cash, payment_deadline


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def review(case_path, code_path='cash_merger_claim_clock.py', test_path='test_cash_merger_claim_clock.py',
           claim_output_path=None):
    money_cases = date_cases = 0
    for shares in (1, 2, 3, 17, 999, 1000, 3001):
        for price in ('0.01', '0.50', '1.005', '2.50', '18.50', '27.3333',
                      '1000.125', '1.000000000000000000005', '999999999999.99999999999'):
            for cents in (0, 1, 25, 50, 99, 100):
                withholding = f'{cents//100}.{cents%100:02}'
                amount = shares*Fraction(price)-Fraction(withholding)
                if amount < 0:
                    continue
                # floor(x+1/2) is half-up for these nonnegative exact rationals.
                expected = (2*amount.numerator+amount.denominator)//(2*amount.denominator)
                require(int(net_cash(shares,price,withholding)['cash']) == expected,
                        'Decimal implementation differs from exact rational oracle')
                money_cases += 1
    first = dt.date(2028,2,20)
    # An explicit artificial calendar spans leap day and includes some weekends.
    # Its omissions are synthetic facts; no weekday/market calendar is assumed.
    days = [(first+dt.timedelta(days=n)).isoformat() for n in range(90)
            if n % 7 not in (1,5) and n not in (19,20,48)]
    calendar = dict(verified=True,basis='Synthetic enumeration only; not a Taiwan calendar',
                    evidence=['independent synthetic calendar'],start=first.isoformat(),
                    end=(first+dt.timedelta(days=89)).isoformat(),business_days=days)
    for offset in range(70):
        base = (first+dt.timedelta(days=offset)).isoformat()
        remaining = [day for day in days if day > base]
        require(len(remaining) >= 7, 'Independent calendar fixture too short')
        require(payment_deadline(base,calendar) == remaining[6], 'Seventh-day enumeration differs')
        date_cases += 1
    actual = json.loads(Path(case_path).read_bytes())
    require(actual.get('actual_inputs_state') == 'pending', 'Review is pinned to the pending research case')
    require(all(fact.get('value') is None and fact.get('verified') is None
                for fact in actual['facts'].values()), 'Actual pending fact population changed')
    require(actual.get('business_calendar') is None, 'Actual applicable calendar is no longer unknown')
    rejection = evaluate_claim(actual)
    require(rejection['status'] == 'actual_inputs_incomplete'
            and rejection['cash'] is None and rejection['payment_date'] is None
            and not rejection['calculation_ready'] and len(rejection['reasons']) == 10,
            'Actual pending case did not reject all unresolved actual inputs')
    require(not rejection['provisional_terms_used'] and not rejection['voting_bookclosure_used']
            and not rejection['automatic_expiry_inferred'] and rejection['termination_conclusion'] is None,
            'Pending case used proposal/voting closure or inferred expiry')
    future = copy.deepcopy(actual)
    future['as_of_date'] = '2030-01-01'
    future_result = evaluate_claim(future)
    require(future_result['cash'] is None and future_result['payment_date'] is None
            and future_result['termination_conclusion'] is None
            and not future_result['automatic_expiry_inferred'], 'Old copy date became an expiry conclusion')
    output_reference = None
    if claim_output_path is not None:
        replay = json.loads(Path(claim_output_path).read_bytes())
        require(replay['case_config_sha256'] == digest(case_path)
                and replay['claim'] == rejection, 'Actual claim output differs from independently reviewed pending case')
        require(all(replay.get(flag) is False for flag in (
                    'source_gate_passed','cash_claim_source_gate_passed','historical_pit_verified',
                    'profit_edge_proven','market_prices_or_returns_read','orders_authorized',
                    'source_acquisition_performed'))
                and replay.get('valid_prospective_signal_date') is None,
                'Actual replay output improperly promotes a gate')
        output_reference = dict(path=str(claim_output_path),sha256=digest(claim_output_path))
    return dict(schema_version=1,status='independent_oracles_and_actual_pending_rejection_verified',
                inputs=dict(case_path=str(case_path),case_sha256=digest(case_path),
                            clock_code_sha256=digest(code_path),clock_tests_sha256=digest(test_path)),
                exact_rational_half_up_comparisons=money_cases,
                independently_enumerated_calendar_comparisons=date_cases,
                calendar_examples_are_synthetic=True,prices_are_synthetic_arithmetic_inputs=True,
                actual_case_rejection=rejection,
                actual_claim_output_compared=claim_output_path is not None,
                actual_claim_output=output_reference,
                future_asof_cannot_infer_expiry=True,blocking_code_findings=[],
                review_limits='External verified facts/evidence and calendar completeness remain caller responsibilities; arithmetic does not authenticate documents or qualify entry.',
                source_gate_passed=False,historical_pit_verified=False,profit_edge_proven=False,
                valid_prospective_signal_date=None,orders_authorized=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case',default='configs/cash_merger_claim_case_20261022.json')
    parser.add_argument('--claim-output',default=None)
    parser.add_argument('--output',default='deliverables/cash_merger_claim_20261022/independent_audit.json')
    args = parser.parse_args()
    result = review(args.case,claim_output_path=args.claim_output)
    path = Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:result[key] for key in ('status','exact_rational_half_up_comparisons',
                                                'independently_enumerated_calendar_comparisons',
                                                'blocking_code_findings')},ensure_ascii=False))
