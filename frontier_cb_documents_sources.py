"""Bounded original CB documents, with exact identities before any request.

The initial three GETs copy whole URLs from a pinned all-issuer report. Later
document-pointer rules must be reviewed after their source bodies are read back.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit, urljoin
import zipfile

from lxml import html

import frontier_sources

ROOT = Path('inputs/frontier_cb_documents_20261023')
OUT = Path('deliverables/frontier_cb_documents_20261023')
POLICY = Path('configs/frontier_cb_documents_protocol_20261023.json')
FIELDS = ['發行機構代碼', '發行機構名稱', '債券名稱', '掛牌日期', '發行資料']
QUERY_KEYS = ['TYPEK', 'bond_id', 'bond_kind', 'bond_subn', 'bond_yrn', 'come',
              'encodeURIComponent', 'firstin', 'issuer_stock_code', 'monyr_reg', 'pg', 'step', 'tg']
CONTROL_CODES = ['99587', '68351', '68741']
ROUTE_CHECKPOINT = 'deliverables/frontier_cb_contract_20261022/checkpoint.json'


def require(value, message):
    if not value:
        raise ValueError(message)


def strict_json(body):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('Nonfinite JSON value: '+value)
    return json.loads(body, object_pairs_hook=pairs, parse_constant=nonfinite)


def _listed_date(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9]{2,3}/[0-9]{2}/[0-9]{2}', value),
            'Listing date must preserve a ROC date')
    year, month, day = map(int, value.split('/'))
    return date(year+1911, month, day).strftime('%Y%m%d')


def _pointer(url, issuer):
    parts = urlsplit(url)
    require(parts.scheme == 'https' and parts.netloc == 'mopsov.twse.com.tw'
            and parts.path == '/mops/web/t120sg01' and not parts.fragment
            and not parts.username and not parts.password, 'Unexpected issuance URL host/path')
    pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    require([key for key, value in pairs] == QUERY_KEYS, 'Issuance query keys/order/duplicates changed')
    values = dict(pairs)
    require(values['issuer_stock_code'] == issuer and values['bond_id'].startswith(issuer)
            and len(values['bond_id']) > len(issuer)
            and re.fullmatch(r'[0-9A-Z]+', values['bond_id']), 'Issuance issuer/bond identity mismatch')
    require(values['TYPEK'] == values['pg'] == values['tg'] == '' and values['bond_kind'] == '5'
            and values['bond_subn'] in {'$M00000001', '$M00000002', '$M00000003'}
            and values['come'] == '2' and values['encodeURIComponent'] == '1'
            and values['firstin'] == 'ture' and values['step'] == '0'
            and re.fullmatch(r'[0-9]+', values['bond_yrn'])
            and re.fullmatch(r'[0-9]{6}', values['monyr_reg'])
            and 1 <= int(values['monyr_reg'][4:]) <= 12, 'Issuance literal query fields changed')
    return pairs


def validate_report(body: bytes, expected_count=389):
    """Retain all root/table/row fields; validate even unselected row identities."""
    value = strict_json(body)
    require(isinstance(value, dict) and set(value) == {'tables', 'stat'} and value['stat'] == 'ok'
            and isinstance(value['tables'], list) and len(value['tables']) == 1, 'Report root/schema/status changed')
    table = value['tables'][0]
    require(isinstance(table, dict) and set(table) == {'title','subtitle','date','fields','totalCount','notes','summary','data'}
            and table['title'] == '最近上櫃轉(交)換公司債' and table['fields'] == FIELDS
            and isinstance(table['subtitle'], str) and isinstance(table['date'], str)
            and isinstance(table['notes'], list) and isinstance(table['summary'], list)
            and type(table['totalCount']) is int and table['totalCount'] == expected_count
            and isinstance(table['data'], list) and len(table['data']) == expected_count,
            'Report table fields/count/schema changed')
    rows = []
    for number, fields in enumerate(table['data'], 1):
        require(isinstance(fields, list) and len(fields) == 5
                and all(isinstance(item, str) and item for item in fields), 'Malformed original report row')
        issuer, issuer_name, bond_name, listed, url = fields
        require(re.fullmatch(r'[0-9]{4,8}', issuer), 'Malformed issuer code')
        _listed_date(listed)
        pairs = _pointer(url, issuer)
        rows.append(dict(row_number=number, original_fields=fields, issuer=issuer,
            issuer_name=issuer_name, bond_name=bond_name, listed_date=listed, url=url,
            bond_id=dict(pairs)['bond_id'], query_pairs=pairs))
    require(len({row['bond_id'] for row in rows}) == expected_count
            and len({row['url'] for row in rows}) == expected_count, 'Duplicate report bond/pointer')
    return dict(raw=value, body_sha256=hashlib.sha256(body).hexdigest(),
                record_count=expected_count, fields=table['fields'], rows=rows)


def select_issuance(report, selection, requests, *, original_selection):
    require(selection['source_report_sha256'] == report['body_sha256']
            and selection['source_report_records'] == report['record_count'] == 389
            and selection['source_report_fields'] == report['fields'], 'Selection report binding drift')
    require(selection['controls_bond_codes'] == original_selection['controls_bond_codes'] == CONTROL_CODES
            and selection['original_calendar_population_count'] == original_selection['original_calendar_population_count'] == 29
            and selection['original_calendar_fields'] == original_selection['original_calendar_fields']
            and selection['original_calendar_rows'] == original_selection['original_calendar_rows'],
            'Frozen29 population/three chronological source controls changed')
    controls, originals = selection['controls'], original_selection['controls']
    require([item['bond_code'] for item in controls] == [item['bond_code'] for item in originals] == CONTROL_CODES
            and len(requests) == 3, 'Exactly three frozen issuance controls are required')
    identities = []
    for control, old, request in zip(controls, originals, requests):
        number = control['report_row_number']
        require(type(number) is int and 1 <= number <= report['record_count'], 'Selected report row outside saved data')
        row = report['rows'][number-1]
        require(control['report_original_fields'] == row['original_fields']
                and control['bond_code'] == row['bond_id']
                and control['issuer'] == row['issuer'] and control['issuer_name'] == row['issuer_name']
                and control['bond_name'] == row['bond_name'] and control['listed_date'] == row['listed_date']
                and control['issuance_url'] == row['url'] and control['nominal_put_date'] == old['nominal_put_date'],
                'Selected original row/company/bond/clock identity drift')
        meta = old['metadata_20261020_original']
        require(row['issuer'] == meta['IssuerCode']
                and dict(row['query_pairs'])['bond_yrn'] == meta['SeriesNumber']
                and _listed_date(row['listed_date']) == meta['ListingDate'], 'Original metadata issuer/series/listing mismatch')
        require(set(request) == {'filename','url','method'} and request['method'] == 'GET'
                and request['filename'] == control['request_filename'] == control['bond_code']+'_issuance.html'
                and request['url'] == row['url'], 'Issuance request must copy the entire literal saved URL')
        identities.append(dict(bond_code=row['bond_id'], issuer=row['issuer'], issuer_name=row['issuer_name'],
            report_row_number=number, url=row['url'], query_pairs=row['query_pairs']))
    return dict(identities=identities, returned_report_records=389, original_put_population_count=29,
                requests=3, identity_before_IO_verified=True, whole_URLs_copied_without_reencoding=True,
                complete_original29_contract_coverage_verified=False, source_gate_passed=False,
                historical_pit_verified=False)


def verified_report(spec):
    package = strict_json(Path(spec['package_path']).read_bytes())
    transfer = strict_json(Path(package['transfer_receipt']).read_bytes())
    require(package['sha256'] == transfer['sha256'] == spec['archive_sha256']
            and transfer.get('roundtrip_verified') is True, 'Report archive lacks its pinned readback')
    body = Path(package['retrieved']).read_bytes()
    require(hashlib.sha256(body).hexdigest() == spec['archive_sha256'], 'Report archive SHA drift')
    with zipfile.ZipFile(Path(package['retrieved'])) as archive:
        names = archive.namelist()
        manifest = strict_json(archive.read('manifest.json'))
        require(len(names) == len(set(names)) and archive.testzip() is None
                and set(names) == set(manifest) | {'manifest.json'}
                and package['manifest_files'] == len(manifest), 'Report archive CRC/manifest population drift')
        for name, expected in manifest.items():
            require(hashlib.sha256(archive.read(name)).hexdigest() == expected, 'Report archive inner SHA drift')
        body = archive.read(spec['member'])
        require(hashlib.sha256(body).hexdigest() == spec['body_sha256'], 'Report body SHA drift')
        metadata = strict_json(archive.read(spec['member']+'.meta.json'))
        require(metadata.get('http_status') == 200 and metadata.get('exit_code') == 0
                and metadata.get('sha256') == spec['body_sha256']
                and metadata['request'] == {'filename':'all_issuer_report.json','url':'https://www.tpex.org.tw/www/zh-tw/bond/convSearch',
                    'method':'POST','data':'name=bondIssuer&searchNo=&response=json'}, 'Report transport/request binding drift')
    return validate_report(body)


def terms_pointer(body: bytes, control, series: str):
    """Verify the issuance body's identity, then its labelled terms-cell link."""
    body.decode('utf-8', errors='strict')
    tree = html.fromstring(body, parser=html.HTMLParser(encoding='utf-8'))
    require(not tree.xpath('//base[@href]'), 'Issuance base URL needs explicit review')
    cells = tree.xpath('//tr[not(.//tr)]/td')
    def field(label):
        matches = [cell for cell in cells if cell.text_content().strip().startswith(label)]
        require(len(matches) == 1, 'Missing/duplicate issuance body field: '+label)
        cell = matches[0]
        return cell, cell.text_content().strip()[len(label):].strip()
    _, code = field('債券代碼：')
    _, name = field('債券中文名稱：')
    _, period = field('債券期別：')
    match = re.fullmatch(r'第\s*([0-9]+)\s*期\s*券', period)
    require(code == control['bond_code'] and name == control['bond_name']
            and name.startswith(control['issuer_name']) and match is not None
            and match.group(1) == series, 'Issuance body code/company/name/series mismatch')
    cell, _ = field('發行辦法之內容：')
    links = cell.xpath('./a[@href]')
    require(len(links) == 1, 'Missing/duplicate labelled issuance-terms anchor')
    href = links[0].get('href')
    parts = urlsplit(href)
    require(not parts.scheme and not parts.netloc and not parts.query and not parts.fragment
            and parts.path.startswith('/nas/t56/t56bondb/') and '..' not in Path(parts.path).parts,
            'Labelled terms anchor is outside the exact official terms directory')
    url = urljoin(control['issuance_url'], href)
    require(urlsplit(url).scheme == 'https' and urlsplit(url).netloc == 'mopsov.twse.com.tw',
            'Terms anchor resolved outside the issuance host')
    return dict(bond_code=code,issuer=control['issuer'],issuer_name=control['issuer_name'],
        bond_name=name,series=match.group(1),literal_href=href,url=url,
        anchor_text=links[0].text_content().strip(),label='發行辦法之內容：',
        body_sha256=hashlib.sha256(body).hexdigest(),response_is_PDF_verified=False,
        filename_date_meaning_inferred=False,source_gate_passed=False)


def verified_issuance_archive(spec):
    package = strict_json(Path(spec['package_path']).read_bytes())
    transfer = strict_json(Path(package['transfer_receipt']).read_bytes())
    require(package['sha256'] == transfer['sha256'] == spec['archive_sha256']
            and transfer.get('roundtrip_verified') is True, 'Issuance archive lacks its pinned readback')
    require(hashlib.sha256(Path(package['retrieved']).read_bytes()).hexdigest() == spec['archive_sha256'],
            'Issuance archive SHA drift')
    with zipfile.ZipFile(Path(package['retrieved'])) as archive:
        names = archive.namelist()
        manifest = strict_json(archive.read('manifest.json'))
        require(len(names) == len(set(names)) and archive.testzip() is None
                and set(names) == set(manifest) | {'manifest.json'}
                and package['manifest_files'] == len(manifest) == spec['manifest_files'],
                'Issuance archive CRC/manifest population drift')
        members = {name:archive.read(name) for name in names}
        require(all(hashlib.sha256(members[name]).hexdigest() == expected
                    for name,expected in manifest.items()), 'Issuance archive inner SHA drift')
    return members


def select_terms(members, initial_selection, original_selection, terms_selection, requests):
    require(terms_selection['controls_bond_codes'] == initial_selection['controls_bond_codes'] == CONTROL_CODES
            and [item['bond_code'] for item in terms_selection['controls']] == CONTROL_CODES
            and len(requests) == 3, 'Exactly three unchanged terms controls are required')
    proofs = []
    for control, original, selected, request in zip(initial_selection['controls'],original_selection['controls'],
                                                  terms_selection['controls'],requests):
        member = 'raw/'+control['request_filename']
        body = members[member]
        metadata = strict_json(members[member+'.meta.json'])
        require(metadata.get('http_status') == 200 and metadata.get('exit_code') == 0
                and metadata.get('sha256') == selected['source_body_sha256'] == hashlib.sha256(body).hexdigest()
                and metadata['request'] == dict(filename=control['request_filename'],url=control['issuance_url'],method='GET')
                and selected['source_member'] == member, 'Terms source issuance body/transport binding drift')
        proof = terms_pointer(body,control,original['metadata_20261020_original']['SeriesNumber'])
        require(selected['identity_and_pointer'] == proof, 'Frozen terms identity/literal pointer evidence drift')
        require(request == dict(filename=control['bond_code']+'_terms.pdf',url=proof['url'],method='GET'),
                'Terms request must copy the exact labelled original href')
        proofs.append(proof)
    return dict(controls=proofs,requests=3,issuer_identities_before_IO_verified=True,
        actual_terms_or_PDF_content_verified=False,source_gate_passed=False,historical_pit_verified=False)


def module():
    frontier_sources.ROOT, frontier_sources.OUT, frontier_sources.POLICY = ROOT, OUT, POLICY
    return frontier_sources


def validate_phase_policy(policy):
    require('pending_prior_checkpoint' not in policy and policy.get('draft', False) is False
            and policy.get('is_draft', False) is False
            and not str(policy.get('status', '')).startswith('draft'), 'Draft/pending route checkpoint cannot authorize IO')
    route_sha = policy.get('prior_checkpoints', {}).get(ROUTE_CHECKPOINT)
    require(isinstance(route_sha, str) and re.fullmatch(r'[0-9a-f]{64}', route_sha),
            'Frozen route checkpoint must be explicitly pinned before IO')
    require(policy['max_saved_requests'] == 9 and policy['max_source_batches'] == 3
            and policy['workers'] == 2 and policy['automatic_retries'] == 0, 'CB document phase allocation drift')
    old, new = policy['prior_CB_allocations'], policy['new_allocation']
    expected_old = dict(first_discovery_cap=12,first_discovery_actual=12,contract_route_cap=4,
        contract_route_actual=3,contract_route_batches_actual=3,contract_route_batch_cap=3,
        cumulative_CB_requests_before_phase=15,cumulative_CB_request_cap_after_phase=24)
    expected_new = dict(maximum_requests=9,maximum_batches=3,initial_issuance_GETs=3,
        maximum_contract_pointer_requests=3,maximum_actual_file_transfers=3)
    require(all(type(old.get(key)) is int and old[key] == value for key,value in expected_old.items())
            and old.get('one_unused_contract_route_request_is_not_reused') is True
            and all(type(new.get(key)) is int and new[key] == value for key,value in expected_new.items())
            and new.get('all_failed_requests_count') is True, 'CB cumulative15plus9 ledger/old-unused-request rule drift')


def plan(batch='issuance'):
    shared = module()
    policy = shared.read(POLICY)
    validate_phase_policy(policy)
    result = shared.plan(batch)
    route = shared.read(ROUTE_CHECKPOINT)
    require(isinstance(route.get('prior_checkpoints'), dict)
            and all(policy['prior_checkpoints'].get(path) == expected
                    for path,expected in route['prior_checkpoints'].items()),
            'New phase must retain every pinned route prior checkpoint')
    require(route.get('source_requests_this_phase') == route.get('source_batches_this_phase') == 3
            and route.get('cumulative_CB_source_requests') == 15
            and route.get('original_request_cap') == 4 and route.get('original_batch_cap') == 3,
            'Pinned prior route actual request/batch ledger mismatch')
    require(batch in {'issuance','terms'}, 'Later document pointers need their own reviewed source-bound guard before IO')
    require(result[1]['allowed_hosts'] == ['mopsov.twse.com.tw'], 'Initial issuance source host drift')
    selected = policy['selection']
    original = policy['original_selection']
    require(shared.sha256(selected['path']) == selected['sha256']
            and shared.sha256(original['path']) == original['sha256'], 'Frozen document/original selection SHA drift')
    report = verified_report(policy['report_source_evidence'])
    selection = shared.read(selected['path'])
    require(selection['source_original_selection_sha256'] == original['sha256'], 'Original selection lineage mismatch')
    original_selection = shared.read(original['path'])
    initial_requests = shared.read(policy['batches']['issuance']['path'])['requests']
    select_issuance(report, selection, initial_requests,original_selection=original_selection)
    if batch == 'issuance':
        require(result[1]['requests'] == initial_requests, 'Initial issuance request drift')
    else:
        require(result[3] is not None, 'Terms batch needs its own immutable freeze')
        freeze = shared.read(result[3])
        terms_ref = freeze['terms_selection']
        require(shared.sha256(terms_ref['path']) == terms_ref['sha256'], 'Terms selection SHA drift')
        terms_selection = shared.read(terms_ref['path'])
        require(terms_selection['initial_selection_sha256'] == selected['sha256']
                and terms_selection['source_issuance_archive_sha256'] == freeze['issuance_source_evidence']['archive_sha256'],
                'Terms selection initial/archive lineage drift')
        members = verified_issuance_archive(freeze['issuance_source_evidence'])
        select_terms(members,selection,original_selection,terms_selection,result[1]['requests'])
    return result


def execute(stage, batch='issuance'):
    plan(batch)
    getattr(module(), stage)(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['plan','acquire','package','verify'])
    parser.add_argument('--batch', default='issuance')
    args = parser.parse_args()
    if args.stage == 'plan':
        path, cfg, _, _ = plan(args.batch)
        print(json.dumps(dict(batch=args.batch,requests_path=str(path),requests=len(cfg['requests']),source_IO_performed=False)))
    else:
        execute(args.stage,args.batch)
