"""Close only a logically unattainable fixed gate; never fill missing returns.

The calculation uses already audited artifacts.  It reads no price archive and
requests no data.  Missing observations can change only their publication
quarter; an arbitrarily favorable completion cannot repair a different fully
observed nonpositive quarter.  This is a bound on the existing research gate,
not a new parameter, test or trading direction.
"""
import csv
import datetime as dt
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo


COSTS = ('0.0025', '0.005')
QUARTERS = tuple(f'2024Q{number}' for number in range(1, 5))
SCENARIO_COLUMNS = ('case_id', 'issuer', 'publication_timestamp', 'cost',
                    'stock_change', 'benchmark_change', 'relative_change')
OUT = Path('deliverables/buyback_probe_20261020')
POLICY = Path('configs/buyback_probe_protocol_20261020.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _hash(body):
    return hashlib.sha256(body).hexdigest()


def _summary_bytes(value):
    # Match research_runtime.atomic_json; preserve the audited source key order.
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def _scenario_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=SCENARIO_COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _number(value):
    require(not isinstance(value, (bool, float)), 'Numbers must retain exact source values')
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('Invalid finite numeric value') from error


def _quarter(publication):
    try:
        moment = dt.datetime.fromisoformat(publication)
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid publication timestamp') from error
    require(moment.utcoffset() is not None, 'Publication requires a timezone')
    moment = moment.astimezone(ZoneInfo('Asia/Taipei'))
    require(moment.year == 2024, 'Fixed cohort must use 2024 publication quarters')
    return f'2024Q{(moment.month - 1) // 3 + 1}'


def _text(number):
    with localcontext() as context:
        context.prec = 50
        return str(Decimal(number.numerator) / Decimal(number.denominator))


def decide(cohort, scenarios, summary, audit, expected_case_count=47):
    """Verify exact populations and bound the fixed three-positive-quarter gate.

    The audit must bind the unchanged summary and scenario artifacts.  Every
    retained case has both fixed cost rows or neither; all omissions must agree
    with audited endpoint gaps.  Unknown values are never assigned a return.
    Near numerical-zero complete means conservatively remain possibly positive
    within the audit's already stated tolerance, which can only weaken closure.
    """
    require(type(expected_case_count) is int and expected_case_count > 0, 'Invalid fixed case count')
    require(isinstance(cohort, list) and len(cohort) == expected_case_count, 'Unexpected cohort size')
    require(isinstance(scenarios, list), 'Scenarios must be the saved row list')
    require(audit.get('status') == 'passed', 'Independent audit has not passed')
    require(audit['protocol_sha256'] == summary['protocol_sha256'], 'Audit/protocol mismatch')
    artifacts = audit['artifact_sha256']
    require(artifacts['summary.json'] == _hash(_summary_bytes(summary)), 'Audited summary bytes mismatch')
    require(artifacts['event_scenarios.csv'] == _hash(_scenario_bytes(scenarios)),
            'Audited scenario bytes mismatch')
    tolerance = _number(audit['absolute_numeric_tolerance'])
    require(0 <= tolerance <= Fraction(1, 10**45), 'Unexpected audit numeric tolerance')
    require(0 <= _number(audit['maximum_absolute_numeric_error']) <= tolerance, 'Audit numeric failure')
    require(summary['primary_cost'] == '0.005' and summary['required_publication_quarters'] == list(QUARTERS),
            'Fixed primary cost or quarters changed')
    for value in (summary, audit):
        for flag in ('historical_pit_verified', 'profit_edge_proven', 'actual_execution_verified', 'valid_signal'):
            require(value[flag] is False, 'Unsupported claim: ' + flag)
        require(value['valid_prospective_signal_date'] is None, 'Unsupported prospective signal date')

    cases = {}
    for case in cohort:
        identity = case['case_id']
        require(isinstance(identity, str) and identity and identity not in cases, 'Duplicate or invalid cohort ID')
        require(isinstance(case['issuer'], str) and case['issuer'], 'Invalid issuer')
        cases[identity] = dict(**case, quarter=_quarter(case['publication_timestamp']))
    expected_ids = sorted(cases)
    require(summary['expected_case_ids'] == expected_ids and summary['case_count'] == expected_case_count,
            'Summary cohort differs')
    require(audit['event_cases_verified'] == audit['publication_endpoint_windows_verified'] == expected_case_count,
            'Audit cohort/window count differs')
    audited_endpoints = {row['case_id']: row for row in audit['endpoints']}
    require(len(audited_endpoints) == len(audit['endpoints']) == expected_case_count
            and sorted(audited_endpoints) == expected_ids, 'Audit endpoint case IDs differ')
    missing_ids = sorted(row['case_id'] for row in summary['gaps'])
    require(len(set(missing_ids)) == len(missing_ids) and set(missing_ids) <= set(cases), 'Invalid summary gaps')
    require(missing_ids == sorted(audit['gap_case_ids'])
            == sorted(case for case, row in audited_endpoints.items() if row['endpoint_gaps']),
            'Audit and summary missing case IDs differ')
    require(all(row['missing'] for row in summary['gaps']), 'Empty endpoint gap record')
    observed_ids = sorted(set(cases) - set(missing_ids))
    require(audit['complete_endpoint_cases'] == len(observed_ids), 'Audit complete case count differs')
    complete = not missing_ids
    require(summary['coverage_complete'] is complete and summary['coverage_verified_by_caller'] is complete,
            'Summary coverage claim differs')

    by_cost = {cost: {} for cost in COSTS}
    for row in scenarios:
        require(set(row) == set(SCENARIO_COLUMNS), 'Scenario schema differs')
        identity, cost = row['case_id'], row['cost']
        require(cost in by_cost and identity in observed_ids and identity not in by_cost[cost],
                'Extra, duplicate, missing-case or wrong-cost scenario')
        case = cases[identity]
        require(row['issuer'] == case['issuer'] and row['publication_timestamp'] == case['publication_timestamp'],
                'Scenario issuer or publication mismatch')
        value = _number(row['relative_change'])
        require(abs(value - (_number(row['stock_change']) - _number(row['benchmark_change']))) <= tolerance,
                'Scenario relative calculation mismatch')
        by_cost[cost][identity] = value
    require(len(scenarios) == len(observed_ids) * len(COSTS)
            == summary['scenario_count'] == audit['scenario_return_rows_verified'], 'Scenario row count differs')
    require(set(summary['costs']) == (set(COSTS) if observed_ids else set()), 'Summary cost population differs')
    bounds = {}
    for cost, values in by_cost.items():
        require(sorted(values) == observed_ids, 'Cost scenario exact case IDs differ')
        declared = summary['costs'].get(cost)
        if observed_ids:
            require(declared['case_ids'] == observed_ids and declared['event_count'] == len(observed_ids),
                    'Cost summary exact case IDs differ')
        quarters = {}
        possible_positive, definitely_nonpositive = [], []
        observed_quarters = {cases[case]['quarter'] for case in observed_ids}
        if observed_ids:
            require(set(declared['quarters']) == observed_quarters, 'Cost summary quarter population differs')
        for quarter in QUARTERS:
            expected = sorted(case for case in cases if cases[case]['quarter'] == quarter)
            observed = sorted(case for case in values if cases[case]['quarter'] == quarter)
            missing = sorted(set(expected) - set(observed))
            mean = sum((values[case] for case in observed), Fraction()) / len(observed) if observed else None
            if observed:
                reported = declared['quarters'][quarter]
                require(reported['event_count'] == len(observed)
                        and abs(_number(reported['mean_relative_change']) - mean) <= tolerance,
                        'Quarter count or audited mean differs')
            # An affected quarter may be positive after any missing value is
            # supplied.  A complete, robustly nonpositive quarter cannot change.
            possible = bool(expected) and (bool(missing) or (mean is not None and mean + tolerance > 0))
            if possible:
                possible_positive.append(quarter)
            elif expected and not missing:
                definitely_nonpositive.append(quarter)
            quarters[quarter] = dict(expected_case_ids=expected, observed_case_ids=observed,
                                     missing_case_ids=missing, coverage_complete=not missing,
                                     observed_mean_relative_change=None if mean is None else _text(mean),
                                     full_cohort_mean_known=not missing,
                                     positive_after_completion_possible=possible)
        bounds[cost] = dict(quarters=quarters,
                            affected_quarters=[q for q, item in quarters.items() if item['missing_case_ids']],
                            complete_nonpositive_quarters=definitely_nonpositive,
                            possible_positive_quarters=possible_positive,
                            maximum_positive_quarters_after_any_completion=len(possible_positive))

    primary = bounds['0.005']
    structural_missing = [q for q, value in primary['quarters'].items() if not value['expected_case_ids']]
    impossible = primary['maximum_positive_quarters_after_any_completion'] < 3 or bool(structural_missing)
    decision = ('stop_fixed_hypothesis_no_extra_data_needed_to_decide' if impossible
                else 'inconclusive_missing_quotes_may_change_fixed_gate' if not complete
                else 'complete_fixed_gate_result_use_existing_summary')
    return dict(
        status='audited_fixed_gate_completion_bound_verified', decision=decision,
        primary_cost='0.005', minimum_required_positive_quarters=3, cost_bounds=bounds,
        maximum_positive_quarters_after_any_completion=primary['maximum_positive_quarters_after_any_completion'],
        fixed_gate_unattainable_even_if_missing_quotes_supplied=impossible,
        no_extra_data_needed_to_decide_fixed_gate=impossible,
        coverage_complete=complete, full_cohort_quote_results_known=complete,
        expected_case_count=expected_case_count, observed_case_count=len(observed_ids),
        missing_case_ids=missing_ids, unknown_values_imputed=False,
        full_cohort_pooled_mean_relative_change=(summary['costs']['0.005']['mean_relative_change'] if complete else None),
        full_cohort_pooled_median_relative_change=(summary['costs']['0.005']['median_relative_change'] if complete else None),
        resource_allocation_gate_passed=bool(complete and summary['resource_allocation_gate_passed']),
        proof_scope='Necessary three-positive-publication-quarter condition of the existing fixed gate only',
        unqualified_quote_coverage_not_relabelled=True, protocol_sha256=summary['protocol_sha256'],
        historical_pit_verified=False, profit_edge_proven=False, actual_execution_verified=False,
        valid_signal=False, valid_prospective_signal_date=None, trade_authorized=False,
        daily_human_validation=False, parameter_changes=0, new_public_requests=0,
        reused_historical_years=[2024], samples_independent=False, independent_holdout=False,
    )


def run():
    """Read saved small artifacts only and write a separate closure decision."""
    cfg = json.loads(POLICY.read_text())
    summary = json.loads((OUT / 'summary.json').read_text())
    audit = json.loads((OUT / 'independent_audit.json').read_text())
    frozen = json.loads((OUT / 'protocol_freeze.json').read_text())
    require(_hash(POLICY.read_bytes()) == frozen['protocol_sha256'] == audit['protocol_sha256'],
            'Frozen protocol drift')
    ledger_body = Path(cfg['source_ledger']).read_bytes()
    require(_hash(ledger_body) == cfg['source_ledger_sha256'] == audit['source_ledger_sha256'], 'Source ledger drift')
    require(_hash(Path(cfg['source_checkpoint']).read_bytes()) == audit['source_checkpoint_sha256'],
            'Source checkpoint drift')
    ledger = json.loads(ledger_body)
    cohort = [dict(case_id=case['case_id'], issuer=case['issuer'],
                   publication_timestamp=case['earliest_retained_record']['reported_datetime'])
              for case in ledger['cases']]
    with (OUT / 'event_scenarios.csv').open(newline='') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == list(SCENARIO_COLUMNS), 'Saved scenario CSV schema differs')
        scenarios = list(reader)
    result = decide(cohort, scenarios, summary, audit, cfg['limits']['cases'])
    result['input_sha256'] = {name: _hash((OUT / name).read_bytes())
                              for name in ('summary.json', 'event_scenarios.csv', 'independent_audit.json')}
    (OUT / 'decision.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('decision', 'coverage_complete',
                     'maximum_positive_quarters_after_any_completion')}))


if __name__ == '__main__':
    run()
