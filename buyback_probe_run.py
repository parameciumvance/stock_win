"""Frozen conditional quote screen, with explicit source/coverage gates.

This is descriptive resource triage on reused historical data, not a cash
portfolio, historical first-availability proof, or permission to trade.
"""
import argparse
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation, localcontext
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

from buyback_quote_probe import aggregate, endpoints, quote_change
from research_reassessment import verified_bundle
from research_runtime import atomic_bytes, atomic_json, exclusive_lock, sha256, utcnow

ROOT = Path('inputs/buyback_probe_20261020')
OUT = Path('deliverables/buyback_probe_20261020')
POLICY = Path('configs/buyback_probe_protocol_20261020.json')
OLD_CHECKPOINTS = [
    'deliverables/buyback_preflight_20261020/checkpoint.json',
    'deliverables/discrete_accounting_20261020/checkpoint.json',
    'deliverables/rebalance_accounting_20261020/checkpoint.json',
    'deliverables/risk_control_20261018/checkpoint.json',
    'deliverables/benchmark_cash_20261019/checkpoint.json',
]


def read(path):
    return json.loads(Path(path).read_text())


def policy():
    cfg = read(POLICY)
    if sha256(POLICY) != read(OUT / 'protocol_freeze.json')['protocol_sha256']:
        raise ValueError('Frozen quote protocol drift')
    return cfg


def checkpoint(path):
    value = read(path)
    for name, digest in value['files'].items():
        if sha256(name) != digest:
            raise ValueError('Checkpoint member drift: ' + name)
    return len(value['files'])


def cohort_from_ledger(ledger, expected=47):
    cases = ledger['cases']
    if (len(cases) != expected or ledger['cases_missing_initial_evidence'] != 0
            or ledger['ambiguous_case_count'] != 0 or ledger['unresolved_case_ids']
            or ledger['duplicate_document_ids'] or ledger['unmatched_board_documents']):
        raise ValueError('Unresolved source cohort or unexpected population')
    cohort = []
    for case in cases:
        versions = case['versions']
        if not versions:
            raise ValueError('No retained board version for source case')
        first = min(versions, key=lambda r: dt.datetime.fromisoformat(r['reported_datetime']))
        earliest = case['earliest_retained_record']
        if (case['issues'] or case['missing_initial_evidence'] or case['linkage_ambiguous']
                or first['explicitly_titled_revision'] or first['document_form'] != 'board_resolution'
                or first['event_id'] != earliest['event_id']
                or first['reported_datetime'] != earliest['reported_datetime']
                or first['issuer'] != case['issuer']):
            raise ValueError('Earliest record cannot be used as an initial observation')
        cohort.append(dict(case_id=case['case_id'], issuer=case['issuer'],
                           publication_timestamp=first['reported_datetime'], event_id=first['event_id']))
    if len({row['case_id'] for row in cohort}) != expected:
        raise ValueError('Duplicate case identifiers')
    if len({row['event_id'] for row in cohort}) != expected:
        raise ValueError('One source event cannot supply multiple cases')
    return cohort


def source_state(cfg):
    count = sum(checkpoint(p) for p in OLD_CHECKPOINTS)
    checkpoint(cfg['source_checkpoint'])
    if (sha256(cfg['source_ledger']) != cfg['source_ledger_sha256']
            or sha256(cfg['source_protocol']) != cfg['source_protocol_sha256']
            or sha256('inputs/buyback_coverage_20261020/documents_full.json')
            != cfg['source_documents_sha256']):
        raise ValueError('Frozen source ledger/protocol/documents changed')
    decision = read('deliverables/buyback_coverage_20261020/decision.json')
    audit = read('deliverables/buyback_coverage_20261020/independent_audit.json')
    if not (decision['current_vintage_source_gate_passed']
            and decision['documents_verified'] == 122 and decision['annual_cases_linked'] == 47
            and audit['status'] == 'passed' and audit['original_identities_verified'] == 122
            and audit['earliest_retained_chronologies_verified'] == 47):
        raise ValueError('Independent current-vintage source gate not passed')
    cohort = cohort_from_ledger(read(cfg['source_ledger']), cfg['limits']['cases'])
    return cohort, count


def activate():
    cfg = policy()
    cohort, count = source_state(cfg)
    dest = OUT / 'activation_receipt.json'
    source_commit = (read(dest)['source_commit'] if dest.exists() else
                     subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
    receipt = dict(phase='source_checkpoint_pinned_before_quote_extraction',
                   protocol_sha256=sha256(POLICY), source_checkpoint=cfg['source_checkpoint'],
                   source_checkpoint_sha256=sha256(cfg['source_checkpoint']),
                   prior_checkpoints={p: sha256(p) for p in OLD_CHECKPOINTS},
                   prior_checkpoint_entries_verified=count, case_count=len(cohort),
                   source_commit=source_commit,
                   historical_pit_verified=False, valid_signal=False)
    if dest.exists():
        old = read(dest)
        if {k: v for k, v in old.items() if k != 'activated_at'} != receipt:
            raise ValueError('Existing activation receipt differs; do not overwrite')
    else:
        atomic_json(dest, dict(activated_at=utcnow(), **receipt))


def require_activation():
    cfg = policy()
    receipt = read(OUT / 'activation_receipt.json')
    if (receipt['protocol_sha256'] != sha256(POLICY)
            or receipt['source_checkpoint_sha256'] != sha256(cfg['source_checkpoint'])
            or any(sha256(p) != digest for p, digest in receipt['prior_checkpoints'].items())):
        raise ValueError('Activation receipt hash drift')
    cohort, _ = source_state(cfg)
    return cfg, cohort


def positive_quote(value):
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Quote must retain its original exact numeric value')
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError('Invalid quote text') from error
    if not result.is_finite() or result <= 0:
        raise ValueError('Quote must be finite and strictly positive')
    return result


def scan_quotes(stream, selected):
    """Preserve source strings; union calendar includes every source symbol."""
    reader = csv.DictReader(stream)
    needed = ['date', 'symbol', 'adj_open', 'adj_close']
    if not reader.fieldnames or any(reader.fieldnames.count(k) != 1 for k in needed):
        raise ValueError('Missing or duplicate price columns')
    days, quotes, rows = set(), {}, 0
    for row in reader:
        rows += 1
        day = row['date']
        if dt.date.fromisoformat(day).isoformat() != day:
            raise ValueError('Noncanonical source date')
        days.add(day)
        symbol = row['symbol']
        if symbol not in selected:
            continue
        key = day, symbol
        if key in quotes:
            raise ValueError('Duplicate selected quote: ' + str(key))
        for col in ('adj_open', 'adj_close'):
            if row[col] != '':
                positive_quote(row[col])
        quotes[key] = {col: row[col] for col in needed}
    if not days:
        raise ValueError('Empty price archive')
    return sorted(days), quotes, rows


def write_csv(path, fields, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, stream.getvalue().encode())


def extract():
    cfg, cohort = require_activation()  # Must fail before opening price archive.
    prices = cfg['prices']
    manifest = verified_bundle(prices['price_archive'], prices['price_archive_sha256'])
    if manifest[prices['price_member']] != prices['price_sha256']:
        raise ValueError('Frozen price member mismatch')
    selected = sorted({case['issuer'] for case in cohort} | {'0050'})
    with zipfile.ZipFile(prices['price_archive']) as archive:
        with archive.open(prices['price_member']) as member:
            digest = hashlib.file_digest(member, 'sha256').hexdigest()
        if digest != prices['price_sha256']:
            raise ValueError('Price member bytes changed')
        with archive.open(prices['price_member']) as member:
            with gzip.GzipFile(fileobj=member) as compressed:
                with io.TextIOWrapper(compressed, encoding='utf-8-sig', newline='') as stream:
                    calendar, quotes, rows = scan_quotes(stream, selected)
    atomic_json(ROOT / 'calendar.json', calendar)
    write_csv(ROOT / 'quotes.csv', ['date', 'symbol', 'adj_open', 'adj_close'],
              [quotes[key] for key in sorted(quotes)])
    atomic_json(OUT / 'source_receipt.json', dict(
        status='pinned_archive_and_selected_quote_strings_verified',
        activation_receipt_sha256=sha256(OUT / 'activation_receipt.json'),
        calendar_sha256=sha256(ROOT / 'calendar.json'), quotes_sha256=sha256(ROOT / 'quotes.csv'),
        price_archive_sha256=prices['price_archive_sha256'], price_member_sha256=digest,
        price_date_range=[calendar[0], calendar[-1]], full_market_sessions=len(calendar),
        raw_price_rows=rows, selected_quote_rows=len(quotes), selected_symbols=selected,
        archive_manifest_members=len(manifest), crc_and_manifest_verified=True,
        calendar_basis='date union of ALL symbols; no issuer/benchmark compression',
        quotes_preserve_source_strings=True, new_public_requests=0,
        historical_pit_verified=False, valid_signal=False))


def calculate(cohort, calendar, quotes, cfg):
    expected = sorted(row['case_id'] for row in cohort)
    if len(expected) != cfg['limits']['cases'] or len(set(expected)) != len(expected):
        raise ValueError('Fixed cohort population mismatch')
    costs = cfg['one_way_hypothetical_costs']
    records, scenarios, gaps = [], [], []
    for case in cohort:
        entry, exit = endpoints(calendar, case['publication_timestamp'], cfg['horizon_market_sessions'])
        record = dict(case, entry_date=entry, exit_date=exit)
        missing = []
        for label, day, symbol, column in [
            ('stock_entry', entry, case['issuer'], 'adj_open'),
            ('stock_exit', exit, case['issuer'], 'adj_close'),
            ('benchmark_entry', entry, '0050', 'adj_open'),
            ('benchmark_exit', exit, '0050', 'adj_close')]:
            value = quotes.get((day, symbol), {}).get(column, '')
            record[label] = value
            if value == '':
                missing.append(dict(endpoint=label, date=day, symbol=symbol, column=column))
            else:
                positive_quote(value)
        records.append(record)
        if missing:
            gaps.append(dict(case_id=case['case_id'], missing=missing))
            continue
        for cost in costs:
            stock = quote_change(record['stock_entry'], record['stock_exit'], cost)
            benchmark = quote_change(record['benchmark_entry'], record['benchmark_exit'], cost)
            with localcontext() as context:
                context.prec = 50
                relative = stock - benchmark
            scenarios.append(dict(case_id=case['case_id'], issuer=case['issuer'],
                                  publication_timestamp=case['publication_timestamp'], cost=cost,
                                  stock_change=str(stock), benchmark_change=str(benchmark),
                                  relative_change=str(relative)))
    summary = aggregate(scenarios, cfg['primary_one_way_cost'])
    population_matches = (set(summary['costs']) == set(costs)
                          and all(summary['costs'][cost]['case_ids'] == expected for cost in costs))
    complete = not gaps and population_matches and len(scenarios) == len(expected) * len(costs)
    summary.update(coverage_complete=complete, coverage_verified_by_caller=complete,
                   expected_case_ids=expected, gaps=gaps, case_count=len(cohort),
                   scenario_count=len(scenarios),
                   resource_allocation_gate_passed=complete and summary['primary_distribution_rule_passed'],
                   protocol_sha256=sha256(POLICY))
    return records, scenarios, summary


def replay():
    cfg, cohort = require_activation()
    receipt = read(OUT / 'source_receipt.json')
    if (receipt['calendar_sha256'] != sha256(ROOT / 'calendar.json')
            or receipt['quotes_sha256'] != sha256(ROOT / 'quotes.csv')
            or receipt['activation_receipt_sha256'] != sha256(OUT / 'activation_receipt.json')):
        raise ValueError('Extracted price input drift')
    calendar = read(ROOT / 'calendar.json')
    quotes = {}
    with (ROOT / 'quotes.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            key = row['date'], row['symbol']
            if key in quotes:
                raise ValueError('Duplicate extracted quote')
            quotes[key] = row
    records, scenarios, summary = calculate(cohort, calendar, quotes, cfg)
    write_csv(OUT / 'event_quotes.csv', ['case_id', 'issuer', 'publication_timestamp', 'event_id',
              'entry_date', 'exit_date', 'stock_entry', 'stock_exit', 'benchmark_entry', 'benchmark_exit'], records)
    write_csv(OUT / 'event_scenarios.csv', ['case_id', 'issuer', 'publication_timestamp', 'cost',
              'stock_change', 'benchmark_change', 'relative_change'], scenarios)
    atomic_json(OUT / 'summary.json', summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['activate', 'extract', 'replay'])
    args = parser.parse_args()
    with exclusive_lock(ROOT / 'run.lock'):
        globals()[args.stage]()
