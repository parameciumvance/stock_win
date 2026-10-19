"""Bounded public-tender source inspection; deliberately contains no price engine."""
import argparse
import datetime as dt
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import zipfile

from research_runtime import atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback

ROOT = Path('inputs/tender_preflight_20261019')
OUT = Path('deliverables/tender_preflight_20261019')
POLICY = Path('configs/tender_preflight_protocol_20261019.json')
REQUESTS = Path('configs/tender_preflight_sources_20261019.json')
RAW = ROOT / 'raw'
TAG = 'sources'
COHORT_POLICY = Path('configs/tender_cohort_protocol_20261019.json')


def policy():
    freeze = json.loads((OUT / 'protocol_freeze.json').read_text())
    if sha256(POLICY) != freeze['protocol_sha256']:
        raise ValueError('Frozen source preflight protocol drift')
    if TAG == 'cohort' and sha256(COHORT_POLICY) != json.loads((OUT / 'cohort_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen cohort protocol drift')
    return json.loads(POLICY.read_text())


def verified_records(cfg, results, read):
    """HTTP 200 is transport evidence only. Check every captured body/header too."""
    if results['workers'] != 2 or [r['request'] for r in results['requests']] != cfg['requests']:
        raise ValueError('Source request list/workers differ')
    for record in results['requests']:
        name = record['request']['filename']
        if json.loads(read(name + '.meta.json')) != record:
            raise ValueError('Source metadata differs')
        for suffix, key in [('', 'sha256'), ('.headers', 'headers_sha256')]:
            if key in record and hashlib.sha256(read(name + suffix)).hexdigest() != record[key]:
                raise ValueError('Source bytes differ: ' + name + suffix)
    return results['requests']


def package():
    c = policy()
    cfg = json.loads(REQUESTS.read_text())
    limit = json.loads(COHORT_POLICY.read_text())['max_requests'] if TAG == 'cohort' else c['max_initial_requests' if TAG == 'sources' else 'max_form_discovered_followups']
    if len(cfg['requests']) > limit:
        raise ValueError('Request budget exceeded')
    results = json.loads((RAW / 'results.json').read_text())
    if results['config_sha256'] != sha256(REQUESTS):
        raise ValueError('Acquisition configuration differs')
    if 'discovered_from' in cfg:
        origin = cfg['discovered_from']
        if sha256(origin['path']) != origin['sha256']:
            raise ValueError('Form discovery source differs')
    verified_records(cfg, results, lambda name: (RAW / name).read_bytes())
    entries = {'protocol.json': POLICY, 'requests.json': REQUESTS}
    if TAG == 'cohort':
        entries['cohort_protocol.json'] = COHORT_POLICY
    entries.update({'raw/' + p.name: p for p in RAW.iterdir() if p.is_file()})
    with exclusive_lock(ROOT / 'acquisition.lock'):
        package_sources(ROOT, OUT, TAG, entries)


def inspect():
    policy()
    package, transfer = readback(OUT, TAG)
    with zipfile.ZipFile(package['retrieved']) as z:
        for member, source in [('protocol.json', POLICY), ('requests.json', REQUESTS)]:
            if hashlib.sha256(z.read(member)).hexdigest() != sha256(source):
                raise ValueError('Archived policy/requests differ')
        if TAG == 'cohort' and hashlib.sha256(z.read('cohort_protocol.json')).hexdigest() != sha256(COHORT_POLICY):
            raise ValueError('Archived cohort protocol differs')
        results = json.loads(z.read('raw/results.json'))
        if results['config_sha256'] != sha256(REQUESTS):
            raise ValueError('Archived acquisition configuration differs')
        records = verified_records(json.loads(REQUESTS.read_text()), results, lambda name: z.read('raw/' + name))
    receipt_name = 'source_receipt.json' if TAG == 'sources' else TAG + '_source_receipt.json'
    atomic_json(OUT / receipt_name, dict(archive_sha256=package['sha256'], manifest_files=package['manifest_files'],
                roundtrip_verified=True, crc_manifest_verified=True, backup=transfer,
                observations=[dict(filename=r['request']['filename'], url=r['request']['url'],
                    http_status=r['http_status'], exit_code=r.get('exit_code'), sha256=r.get('sha256'),
                    size_bytes=r.get('size_bytes'), request_started_at=r['request_started_at'], observed_at=r['observed_at'],
                    transport_stderr=r.get('stderr', ''), error=r.get('error')) for r in records],
                meaning='Byte preservation only; complete historical cohort and PIT are not implied'))


class Tables(HTMLParser):
    """Extract cell text, keeping each table separate (including nested tables)."""
    def __init__(self):
        super().__init__()
        self.tables, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            table = []
            self.tables.append(table)
            self.stack.append(dict(table=table, row=None, cell=None))
        elif self.stack:
            s = self.stack[-1]
            if tag == 'tr':
                s['row'] = []
                s['table'].append(s['row'])
                s['cell'] = None
            elif tag in ('th', 'td') and s['row'] is not None:
                s['cell'] = []
                s['row'].append(s['cell'])
            elif tag == 'br' and s['cell'] is not None:
                s['cell'].append(' ')

    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell'].append(data)

    def handle_endtag(self, tag):
        if tag == 'table' and self.stack:
            self.stack.pop()
        elif self.stack and tag in ('td', 'th'):
            self.stack[-1]['cell'] = None
        elif self.stack and tag == 'tr':
            self.stack[-1]['row'] = self.stack[-1]['cell'] = None


def table_text(body):
    p = Tables()
    p.feed(body.decode('utf-8-sig') if isinstance(body, bytes) else body)
    return [[[re.sub(r'\s+', ' ', ''.join(c)).strip() for c in row] for row in t] for t in p.tables]


def parse_index(body, roc_year):
    text = body.decode('utf-8') if isinstance(body, bytes) else body
    if not re.search(r'收購開始年度[：:]\s*' + str(roc_year) + r'(?!\d)', text):
        raise ValueError('Missing/wrong-year tender result; HTTP 200 alone is insufficient')
    header = ['序號', '公開收購人', '被收購公司', '被收購公司證券代號', '相關檔案', '申報日期']
    matches = [t for t in table_text(text) if t and t[0] == header]
    if len(matches) != 1 or len(matches[0]) < 2:
        raise ValueError('Missing/ambiguous tender result table; not zero events')
    result = []
    for i, r in enumerate(matches[0][1:], 1):
        if len(r) != 6 or r[0] != str(i) or not re.fullmatch(r'\d{4,6}', r[3]) or not re.fullmatch(r'\d{3}/\d{2}/\d{2}', r[5]):
            raise ValueError('Tender row schema/sequence differs')
        result.append(dict(sequence=i, bidder=r[1], target=r[2], symbol=r[3], filed_roc=r[5]))
        roc_date(r[5])
    if len({(r['symbol'], r['bidder'], r['filed_roc']) for r in result}) != len(result):
        raise ValueError('Duplicate case identity')
    return result


def roc_date(value):
    m = re.fullmatch(r'(\d{3})/(\d{2})/(\d{2})', value)
    if not m:
        raise ValueError('Invalid ROC date')
    return dt.date(int(m[1]) + 1911, int(m[2]), int(m[3])).isoformat()


FILING_HEADER = ['序號', '公開收購期間起日', '公開收購期間末日', '公開收購人名稱或姓名',
                 '公開收購人或其股東(含最終控股股東)是否為私募基金',
                 '公開收購人或其股東(含最終控股股東)是否為被收購公司之管理階層',
                 '被收購公司名稱及代號', '受委任機構名稱', '收購標的', '收購對價', '資金來源',
                 '具履行支付收購對價能力之證明類型', '預定最高收購數量', '預定最低收購數量',
                 '實際收購數量', '被收購公司於收購後是否終止上市、上櫃或興櫃', '公開收購成功或失敗', '公開收購失敗之原因']


def parse_filings(body):
    matches = [t for t in table_text(body) if t and t[0] == FILING_HEADER]
    if len(matches) != 1 or len(matches[0]) < 2:
        raise ValueError('Missing/ambiguous unfiltered filing result table')
    rows = []
    for i, r in enumerate(matches[0][1:], 1):
        symbol = re.search(r'\((\d{4,6})\)$', r[6]) if len(r) == 18 else None
        if len(r) != 18 or r[0] != str(i) or not symbol or r[16] not in ['成功', '失敗', '辦理中']:
            raise ValueError('Filing row schema/sequence/outcome differs')
        row = dict(sequence=i, symbol=symbol[1], reported_fields=dict(zip(matches[0][0], r)), reported_outcome=r[16], source_issues=[])
        for key, value in [('start', r[1]), ('end', r[2])]:
            try:
                row[key] = roc_date(value)
            except ValueError:
                row[key] = None
                row['source_issues'].append('invalid_' + key + '_date')
        if row['start'] and row['end'] and row['start'] > row['end']:
            row['source_issues'].append('end_before_start')
        quantities = []
        for value in r[12:15]:
            if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)股', value):
                quantities.append(None)
                row['source_issues'].append('unknown_share_quantity')
            else:
                quantities.append(int(value[:-1].replace(',', '')))
        row.update(max_shares=quantities[0], min_shares=quantities[1], reported_actual_shares=quantities[2])
        row['quantity_conflict'] = None in quantities or quantities[1] > quantities[0] or (r[16] == '成功' and not quantities[1] <= quantities[2] <= quantities[0])
        rows.append(row)
    keys = [(r['symbol'], r['start'], r['reported_fields']['公開收購人名稱或姓名']) for r in rows]
    for key, row in zip(keys, rows):
        if keys.count(key) > 1:
            row['source_issues'].append('duplicate_case_identity')
    return rows


def parse_case(body, symbol):
    header = ['公開收購人', '被收購公司', '被收購公司證券代號', '主旨', '電子檔案', '申報日期']
    matches = [t for t in table_text(body) if t and t[0] == header]
    if len(matches) != 1 or len(matches[0]) < 2:
        raise ValueError('Missing/ambiguous case document index')
    rows = []
    for r in matches[0][1:]:
        if len(r) != 6 or r[2] != symbol or not re.fullmatch(r'\d{3}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}', r[5]):
            raise ValueError('Wrong-symbol/malformed case index row')
        timestamp = dt.datetime.fromisoformat(roc_date(r[5][:9]) + 'T' + r[5][10:])
        rows.append(dict(bidder=r[0], title=r[3], filename=r[4] or None,
                         reported_timestamp_taipei=timestamp.isoformat() + '+08:00', original_bytes_verified=False))
    return rows


def audit():
    """Reconcile archived indexes only. Missing original versions keep the gate closed."""
    policy()
    saved = {}
    archives = {}
    for tag in ['sources', 'followups', 'cohort']:
        pkg, _ = readback(OUT, tag)
        archives[tag] = pkg['sha256']
        with zipfile.ZipFile(pkg['retrieved']) as z:
            saved[tag] = {n: z.read(n) for n in z.namelist()}
        cfg_path = Path('configs/' + dict(sources='tender_preflight_sources',followups='tender_preflight_followups',cohort='tender_cohort_sources')[tag] + '_20261019.json')
        for name, path in [('protocol.json', POLICY), ('requests.json', cfg_path)]:
            if hashlib.sha256(saved[tag][name]).hexdigest() != sha256(path):
                raise ValueError('Archived source configuration differs')
        results = json.loads(saved[tag]['raw/results.json'])
        if results['config_sha256'] != sha256(cfg_path):
            raise ValueError('Archived result configuration differs')
        records = verified_records(json.loads(cfg_path.read_text()), results, lambda name: saved[tag]['raw/' + name])
        if any(r.get('http_status') != 200 or r.get('exit_code') != 0 for r in records):
            raise ValueError('A required source is unavailable; no cohort promotion')
    source = saved['followups']['raw/mops_2024.html']
    phase = json.loads(COHORT_POLICY.read_text())
    if sha256(COHORT_POLICY) != json.loads((OUT / 'cohort_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen cohort protocol drift')
    if hashlib.sha256(source).hexdigest() != phase['parent_index_sha256']:
        raise ValueError('Parent case index differs')
    if phase['parent_protocol_sha256'] != sha256(POLICY) or phase['parent_followups_archive_sha256'] != archives['followups']:
        raise ValueError('Cohort phase parent chain differs')
    if hashlib.sha256(saved['cohort']['cohort_protocol.json']).hexdigest() != sha256(COHORT_POLICY):
        raise ValueError('Archived cohort protocol differs')
    cases = parse_index(source, 113)
    if cases != phase['case_rows']:
        raise ValueError('Frozen cohort differs')
    all_rows = parse_filings(saved['cohort']['raw/filings_2024_2025.html'])
    selected = [r for r in all_rows if r['start'] and r['start'].startswith('2024-')]
    if any(r['source_issues'] for r in selected):
        raise ValueError('Unresolved schema/date/duplicate issue inside reference year')
    # Sets alone cannot prove global coverage: repeated company cases must remain explicit.
    rows_by_symbol = {}
    for r in selected:
        rows_by_symbol.setdefault(r['symbol'], []).append(r)
    if set(rows_by_symbol) != {r['symbol'] for r in cases} or any(len(v) != 1 for v in rows_by_symbol.values()):
        raise ValueError('Index/filing cohort mismatch or repeated-company ambiguity')
    for case in cases:
        name = 'raw/case_' + case['symbol'] + '.html'
        body = saved['cohort'][name]
        case.update(filing=rows_by_symbol[case['symbol']][0], document_index_sha256=hashlib.sha256(body).hexdigest(),
                    documents=parse_case(body, case['symbol']), historical_pit_verified=False, eligible_for_returns=False)
        case['filing_year_matches_start_year'] = roc_date(case['filed_roc'])[:4] == case['filing']['start'][:4]
    atomic_json(OUT / 'case_ledger.json', dict(cases=cases, other_start_year_rows=[r for r in all_rows if r not in selected],
                archive_sha256=archives, scope='Current official 2024-start indexes reconcile; neither historical snapshots nor withdrawn/pre-commencement proposals proven complete'))
    conflicts = [r['symbol'] for r in cases if r['filing']['quantity_conflict']]
    amendments = {r['symbol']: sum('修正' in d['title'] for d in r['documents']) for r in cases}
    atomic_json(OUT / 'decision.json', dict(status='source_access_feasible_research_gate_not_passed',
                index_rows=len(cases), broad_filing_rows=len(all_rows), other_start_year_rows=len(all_rows)-len(selected),
                broad_query_returned_out_of_range_rows=any(r['start'] and not '2024-01-01' <= r['start'] <= '2025-12-31' for r in all_rows),
                broad_query_filter_semantics_verified=False,
                outside_reference_year_source_issues=[dict(sequence=r['sequence'],symbol=r['symbol'],issues=r['source_issues']) for r in all_rows if r not in selected and r['source_issues']],
                start_2024_cohort_reconciled=True, independent_provider_reconciliation=False,
                index_same_official_system=True, reported_successes=sum(r['filing']['reported_outcome']=='成功' for r in cases),
                reported_failures=sum(r['filing']['reported_outcome']=='失敗' for r in cases),
                failed_symbols=[r['symbol'] for r in cases if r['filing']['reported_outcome']=='失敗'],
                unresolved_quantity_conflict_symbols=conflicts, amendments_by_symbol=amendments,
                case_document_index_entries=sum(len(r['documents']) for r in cases),
                crossyear_end_symbols=[r['symbol'] for r in cases if r['filing']['end'].startswith('2025-')],
                fully_verified_original_case_documents=0, historical_pit_verified=False,
                withdrawn_and_uncommenced_proposals_complete=False, source_gate_passed=False,
                backtest_authorized_by_gate=False, valid_prospective_signals=0,
                reason='Preserve success/quantity conflict; original terms, amendments and expiry contents still needed. Current indexes do not establish historical availability or all proposals.',
                next_action='Do not launch returns/daily validation. Any later original-document audit must pin case/version coverage and resolve conflicts before a separately frozen economic study.',
                no_user_manual_download_requests=True))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['package', 'inspect', 'audit'])
    p.add_argument('--followup', action='store_true')
    p.add_argument('--cohort', action='store_true')
    args = p.parse_args()
    if args.followup:
        REQUESTS = Path('configs/tender_preflight_followups_20261019.json')
        RAW = ROOT / 'followups'
        TAG = 'followups'
    if args.cohort:
        if args.followup:
            p.error('Choose one batch')
        REQUESTS = Path('configs/tender_cohort_sources_20261019.json')
        RAW = ROOT / 'cohort_raw'
        TAG = 'cohort'
    globals()[args.stage]()
