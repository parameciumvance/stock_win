"""Independent csv/Fraction audit of the fixed conditional quote diagnostic.

No production quote extraction, endpoint or calculation helper is imported.
"""
import bisect
import csv
import datetime as dt
from fractions import Fraction
from decimal import Decimal, localcontext
import gzip
import hashlib
import io
import json
from pathlib import Path
import zipfile


TOLERANCE = Fraction(1, 10 ** 45)
ROOT = Path('inputs/buyback_probe_20261020')
OUT = Path('deliverables/buyback_probe_20261020')
POLICY = Path('configs/buyback_probe_protocol_20261020.json')


def file_hash(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def scan_pinned_quotes(policy, selected):
    """Stream frozen zip/gzip CSV; independently retain the full date union."""
    source = policy['prices']
    require(file_hash(source['price_archive']) == source['price_archive_sha256'], 'Price archive SHA mismatch')
    dates, prices, total_rows = set(), {}, 0
    with zipfile.ZipFile(source['price_archive']) as archive:
        checksum = hashlib.sha256()
        with archive.open(source['price_member']) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                checksum.update(block)
        require(checksum.hexdigest() == source['price_sha256'], 'Compressed price member SHA mismatch')
        with archive.open(source['price_member']) as member:
            with gzip.GzipFile(fileobj=member) as stream:
                rows = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''))
                require(all((rows.fieldnames or []).count(field) == 1
                            for field in ['date', 'symbol', 'adj_open', 'adj_close']),
                        'Frozen quote CSV missing required columns')
                for row in rows:
                    total_rows += 1
                    date, symbol = row['date'], row['symbol']
                    dt.date.fromisoformat(date)
                    dates.add(date)
                    if symbol in selected:
                        key = date, symbol
                        require(key not in prices, 'Duplicate selected frozen quote')
                        prices[key] = row['adj_open'], row['adj_close']
    require(total_rows > 0 and prices, 'Empty frozen quote universe')
    return sorted(dates), prices, total_rows


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a quote or cost')
    try:
        return Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError('Invalid finite rational number') from error


def expected_window(calendar, publication, horizon=20):
    """First market DATE strictly after Taipei publication; entry counts as1."""
    require(isinstance(horizon, int) and not isinstance(horizon, bool) and horizon > 0,
            'Invalid horizon')
    days = [dt.date.fromisoformat(day) for day in calendar]
    require(days and days == sorted(set(days)), 'Duplicate or unordered market calendar')
    moment = dt.datetime.fromisoformat(publication)
    require(moment.utcoffset() == dt.timedelta(hours=8), 'Publication timezone is not Taipei offset')
    first = bisect.bisect_right(days, moment.date())
    last = first + horizon - 1
    require(last < len(days), 'Insufficient forward market calendar')
    return days[first].isoformat(), days[last].isoformat()


def fraction_change(entry, exit_, cost):
    entry, exit_, cost = map(number, [entry, exit_, cost])
    require(entry > 0 and exit_ > 0 and 0 <= cost < 1, 'Invalid quote/cost range')
    return exit_ / entry * (1 - cost) / (1 + cost) - 1


def median(values):
    ordered = sorted(values)
    require(bool(ordered), 'Cannot take median of empty values')
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def resource_metrics(quarter_values, complete):
    """Quarter means use each event; pooled median is not a median of means."""
    require(set(quarter_values) <= {'2024Q1', '2024Q2', '2024Q3', '2024Q4'}, 'Unexpected quarter')
    means = {quarter: sum(values, Fraction()) / len(values)
             for quarter, values in quarter_values.items() if values}
    pooled = [value for values in quarter_values.values() for value in values]
    pooled_median = median(pooled) if pooled else None
    passed = (complete and len(means) == 4 and sum(value > 0 for value in means.values()) >= 3
              and pooled_median is not None and pooled_median > 0)
    return means, pooled_median, bool(passed)


def verify_statistics(records, declared, label='pooled'):
    """Audit output summaries from independent rational per-event records."""
    require(records and declared['event_count'] == len(records), label + ' event count')
    issuers = sorted({record['issuer'] for record in records})
    require(declared['issuer_count'] == len(issuers), label + ' issuer count')
    errors = []
    for field in ['stock_change', 'benchmark_change', 'relative_change']:
        values = [record[field] for record in records]
        for key, expected in [('mean_' + field, sum(values, Fraction()) / len(values)),
                              ('median_' + field, median(values))]:
            error = abs(number(declared[key]) - expected)
            require(error <= TOLERANCE, label + ' statistic mismatch: ' + key)
            errors.append(error)
    require(sorted(declared['issuer_means']) == issuers, label + ' issuer summary population')
    for issuer in issuers:
        group = [record for record in records if record['issuer'] == issuer]
        reported = declared['issuer_means'][issuer]
        require(reported['event_count'] == len(group), label + ' per-issuer count')
        for field in ['stock_change', 'benchmark_change', 'relative_change']:
            expected = sum((record[field] for record in group), Fraction()) / len(group)
            error = abs(number(reported['mean_' + field]) - expected)
            require(error <= TOLERANCE, label + ' per-issuer mean: ' + field)
            errors.append(error)
    return errors


def csv_rows(path, columns):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == columns, 'Unexpected CSV schema: ' + str(path))
        rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows),
            'Malformed CSV row: ' + str(path))
    return rows


def verify_activation(policy):
    """Fail before price IO if the already approved source checkpoint drifted."""
    activation_path = OUT / 'activation_receipt.json'
    activation = json.loads(activation_path.read_text())
    require(activation['phase'] == 'source_checkpoint_pinned_before_quote_extraction', 'Wrong activation phase')
    require(activation['protocol_sha256'] == file_hash(POLICY), 'Activation protocol drift')
    require(activation['source_checkpoint'] == policy['source_checkpoint']
            and activation['source_checkpoint_sha256'] == file_hash(policy['source_checkpoint']),
            'Activation source checkpoint drift')
    checkpoints = [policy['source_checkpoint']]
    for path, expected in activation['prior_checkpoints'].items():
        require(file_hash(path) == expected, 'Activation prior checkpoint drift')
        checkpoints.append(path)
    count = 0
    for path in checkpoints:
        checkpoint = json.loads(Path(path).read_text())
        for member, expected in checkpoint['files'].items():
            require(file_hash(member) == expected, 'Pinned source checkpoint member drift: ' + member)
            count += 1
    return count


def run():
    policy = json.loads(POLICY.read_text())
    frozen = json.loads((OUT / 'protocol_freeze.json').read_text())
    require(file_hash(POLICY) == frozen['protocol_sha256'], 'Probe protocol drift')
    ledger_path = Path(policy['source_ledger'])
    require(file_hash(ledger_path) == policy['source_ledger_sha256'], 'Source ledger drift')
    require(file_hash(ledger_path.parent / 'documents_full.json') == policy['source_documents_sha256'],
            'Source documents drift')
    require(file_hash(policy['source_protocol']) == policy['source_protocol_sha256'], 'Source protocol drift')
    checkpoint_entries = verify_activation(policy)
    receipt = json.loads((OUT / 'source_receipt.json').read_text())
    require(receipt['activation_receipt_sha256'] == file_hash(OUT / 'activation_receipt.json'),
            'Extraction receipt activation drift')
    ledger = json.loads(ledger_path.read_text())
    cases = ledger['cases']
    require(len(cases) == policy['limits']['cases'] == 47, 'Cohort must retain all47 cases')
    case_ids = [case['case_id'] for case in cases]
    require(len(set(case_ids)) == 47, 'Duplicate ledger case IDs')
    selected = {'0050'} | {case['issuer'] for case in cases}
    calendar, raw_quotes, raw_row_count = scan_pinned_quotes(policy, selected)
    saved_calendar = json.loads((ROOT / 'calendar.json').read_text())
    require(saved_calendar == calendar, 'Extracted calendar differs from all-market raw date union')
    for key, expected in [('calendar_sha256', file_hash(ROOT / 'calendar.json')),
                          ('quotes_sha256', file_hash(ROOT / 'quotes.csv')),
                          ('price_archive_sha256', policy['prices']['price_archive_sha256']),
                          ('price_member_sha256', policy['prices']['price_sha256'])]:
        require(receipt[key] == expected, 'Extraction receipt hash mismatch: ' + key)
    require(sorted(receipt['selected_symbols']) == sorted(selected), 'Selected-symbol receipt mismatch')
    require(receipt['price_date_range'] == [calendar[0], calendar[-1]]
            and receipt['full_market_sessions'] == len(calendar)
            and receipt['raw_price_rows'] == raw_row_count
            and receipt['selected_quote_rows'] == len(raw_quotes), 'Extraction receipt coverage differs')
    extracted = csv_rows(ROOT / 'quotes.csv', ['date', 'symbol', 'adj_open', 'adj_close'])
    selected_map = {}
    for row in extracted:
        key = row['date'], row['symbol']
        require(key not in selected_map, 'Duplicate extracted quote')
        selected_map[key] = row['adj_open'], row['adj_close']
    require(selected_map == raw_quotes, 'Extracted quotes differ from pinned raw CSV strings')

    event_columns = ['case_id', 'issuer', 'publication_timestamp', 'event_id', 'entry_date', 'exit_date',
                     'stock_entry', 'stock_exit', 'benchmark_entry', 'benchmark_exit']
    events = csv_rows(OUT / 'event_quotes.csv', event_columns)
    require(len(events) == 47 and sorted(row['case_id'] for row in events) == sorted(case_ids),
            'Endpoint artifact drops or duplicates cohort cases')
    event_map = {row['case_id']: row for row in events}
    valid, gaps, errors, expected_events = {}, [], [], []
    for case in cases:
        first = case['earliest_retained_record']
        publication = first['reported_datetime']
        require(first['first_ever_publication_verified'] is False, 'Unjustified historical-first claim')
        entry, exit_ = expected_window(calendar, publication, policy['horizon_market_sessions'])
        row = event_map[case['case_id']]
        for key, expected in [('issuer', case['issuer']), ('publication_timestamp', publication),
                              ('event_id', first['event_id']), ('entry_date', entry), ('exit_date', exit_)]:
            require(row[key] == expected, 'Endpoint identity/date mismatch: ' + case['case_id'] + ' ' + key)
        required = {
            'stock_entry': ((entry, case['issuer']), 0),
            'stock_exit': ((exit_, case['issuer']), 1),
            'benchmark_entry': ((entry, '0050'), 0),
            'benchmark_exit': ((exit_, '0050'), 1),
        }
        prices, missing = {}, []
        for key, (raw_key, position) in required.items():
            try:
                price = number(raw_quotes[raw_key][position])
                require(price > 0, 'Invalid endpoint quote')
            except (KeyError, ValueError):
                require(row[key] == '', 'Missing endpoint was replaced by an invented quote')
                missing.append(key)
                continue
            require(row[key] != '' and number(row[key]) == price, 'Endpoint quote differs from pinned source')
            prices[key] = price
        expected_events.append(dict(case_id=case['case_id'], entry_date=entry, exit_date=exit_,
                                    endpoint_gaps=missing))
        if missing:
            gaps.append(case['case_id'])
        else:
            valid[case['case_id']] = dict(issuer=case['issuer'], publication_timestamp=publication,
                                          quarter=f'2024Q{(dt.datetime.fromisoformat(publication).month - 1) // 3 + 1}',
                                          prices=prices)

    scenarios = csv_rows(OUT / 'event_scenarios.csv', [
        'case_id', 'issuer', 'publication_timestamp', 'cost', 'stock_change', 'benchmark_change', 'relative_change'])
    costs = policy['one_way_hypothetical_costs']
    require(costs == ['0.0025', '0.005'] and policy['primary_one_way_cost'] == '0.005', 'Frozen cost scenarios drift')
    expected_keys = {(case_id, cost) for case_id in valid for cost in costs}
    observed_keys, by_cost = set(), {cost: [] for cost in costs}
    for row in scenarios:
        key = row['case_id'], row['cost']
        require(key in expected_keys and key not in observed_keys, 'Extra, missing-case or duplicate scenario')
        observed_keys.add(key)
        source = valid[row['case_id']]
        require(row['issuer'] == source['issuer'] and row['publication_timestamp'] == source['publication_timestamp'],
                'Scenario source identity drift')
        prices = source['prices']
        stock = fraction_change(prices['stock_entry'], prices['stock_exit'], row['cost'])
        benchmark = fraction_change(prices['benchmark_entry'], prices['benchmark_exit'], row['cost'])
        values = dict(stock_change=stock, benchmark_change=benchmark, relative_change=stock - benchmark)
        for field, value in values.items():
            error = abs(number(row[field]) - value)
            require(error <= TOLERANCE, 'Scenario return mismatch: ' + row['case_id'] + ' ' + field)
            errors.append(error)
        by_cost[row['cost']].append(dict(case_id=row['case_id'], issuer=row['issuer'],
                                          quarter=source['quarter'], **values))
    require(observed_keys == expected_keys, 'Incomplete frozen cost/case scenario grid')

    summary = json.loads((OUT / 'summary.json').read_text())
    require(set(summary['costs']) == (set(costs) if valid else set()), 'Summary cost population mismatch')
    for cost, records in by_cost.items():
        if not records:
            continue
        declared = summary['costs'][cost]
        errors.extend(verify_statistics(records, declared, 'cost=' + cost))
        require(declared['case_ids'] == sorted(valid), 'Pooled summary case population differs')
        quarters = sorted({record['quarter'] for record in records})
        require(sorted(declared['quarters']) == quarters, 'Quarter summary population differs')
        for quarter in quarters:
            errors.extend(verify_statistics([record for record in records if record['quarter'] == quarter],
                                             declared['quarters'][quarter], cost + '/' + quarter))
    primary_values = {}
    for row in by_cost['0.005']:
        primary_values.setdefault(row['quarter'], []).append(row['relative_change'])
    means, pooled_median, distribution = resource_metrics(primary_values, True)
    complete = len(valid) == 47
    resource_gate = complete and distribution
    missing_quarters = [f'2024Q{q}' for q in range(1, 5) if f'2024Q{q}' not in means]
    positive_quarters = [quarter for quarter in sorted(means) if means[quarter] > 0]
    for field, expected in [
        ('primary_cost', '0.005'), ('required_publication_quarters', [f'2024Q{q}' for q in range(1, 5)]),
        ('primary_cost_present', bool(valid)), ('primary_missing_quarters', missing_quarters),
        ('primary_positive_mean_relative_quarters', positive_quarters),
        ('primary_pooled_median_relative_positive', pooled_median is not None and pooled_median > 0),
        ('primary_distribution_rule_passed', distribution), ('coverage_complete', complete),
        ('coverage_verified_by_caller', complete), ('resource_allocation_gate_passed', resource_gate),
        ('expected_case_ids', sorted(case_ids)), ('historical_pit_verified', False),
        ('case_count', 47), ('scenario_count', len(scenarios)), ('protocol_sha256', file_hash(POLICY)),
        ('profit_edge_proven', False), ('actual_execution_verified', False), ('valid_signal', False),
        ('valid_prospective_signal_date', None), ('independent_holdout', False), ('samples_independent', False),
    ]:
        require(summary[field] == expected, 'Summary flag/population mismatch: ' + field)
    require(sorted({gap['case_id'] for gap in summary['gaps']}) == sorted(gaps), 'Summary gaps differ from raw endpoints')
    maximum_error = max(errors, default=Fraction())
    with localcontext() as context:
        context.prec = 50
        error_text = str(Decimal(maximum_error.numerator) / Decimal(maximum_error.denominator))
    result = dict(
        status='passed', method='Independent csv/gzip/zipfile/Fraction; no production quote/calculation helpers',
        protocol_sha256=file_hash(POLICY), source_ledger_sha256=file_hash(ledger_path),
        activation_receipt_sha256=file_hash(OUT / 'activation_receipt.json'),
        source_checkpoint_entries_verified=checkpoint_entries,
        source_checkpoint_sha256=file_hash(policy['source_checkpoint']),
        price_archive_sha256=policy['prices']['price_archive_sha256'],
        price_member_sha256=policy['prices']['price_sha256'], raw_price_rows_scanned=raw_row_count,
        full_market_calendar_days_verified=len(calendar), full_market_date_range=[calendar[0], calendar[-1]],
        selected_quotes_verified=len(raw_quotes), selected_symbols=sorted(selected),
        event_cases_verified=47, publication_endpoint_windows_verified=47,
        complete_endpoint_cases=len(valid), gap_case_ids=sorted(gaps),
        scenario_return_rows_verified=len(scenarios), scenario_numeric_fields_verified=len(scenarios) * 3,
        summary_numeric_fields_verified=len(errors) - len(scenarios) * 3,
        maximum_absolute_numeric_error=error_text, absolute_numeric_tolerance='1e-45',
        artifact_sha256={name: file_hash(OUT / name) for name in
                         ['source_receipt.json', 'event_quotes.csv', 'event_scenarios.csv', 'summary.json']},
        primary_distribution_rule_passed=distribution, resource_allocation_gate_passed=resource_gate,
        outcome='separate_independent_evidence_proposal_only' if resource_gate else 'close_fixed_hypothesis_no_tuning',
        endpoints=expected_events, historical_pit_verified=False, profit_edge_proven=False,
        actual_execution_verified=False, valid_signal=False, valid_prospective_signal_date=None,
    )
    target = OUT / 'independent_audit.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({field: result[field] for field in ['status', 'event_cases_verified',
                     'scenario_return_rows_verified', 'maximum_absolute_numeric_error',
                     'resource_allocation_gate_passed']}))


if __name__ == '__main__':
    run()
