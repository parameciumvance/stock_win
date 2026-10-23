"""Separate bounded notice-interface acquisition; no issuer parameters guessed.

Only the two generic forms are currently authorized by this implementation.
Their returned controls must be read back before a later query guard is added.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urljoin
import zipfile

from lxml import html

from research_runtime import sha256
from source_checkpoint import readback
from tender_preflight import verified_records

ROOT = Path('inputs/frontier_cb_notices_20261023')
OUT = Path('deliverables/frontier_cb_notices_20261023')
POLICY = Path('configs/frontier_cb_notices_protocol_20261023.json')
FORM_CONFIG = Path('configs/frontier_cb_notices_forms_sources_20261023.json')
SELECTION = OUT / 'selection.json'
DOC_OUT = Path('deliverables/frontier_cb_documents_20261023')
DOC_POLICY = Path('configs/frontier_cb_documents_protocol_20261023.json')
DOC_CHECKPOINT = str(DOC_OUT / 'checkpoint.json')
EVIDENCE = DOC_OUT / 'notice_route_evidence.json'
ARCHIVES = dict(issuance='b44941466b27c510e6f6295af3e8c3cab59e38666cc7caea66ec7999d94a8979',
                terms='8566db22cad7ffa2619f27b71152b21784c27e1334be861d148374c927b3a266')
BODY_SHAS = dict(zip(('99587','68351','68741'), (
    '53b54e4b4533590227007ebefdf644ffdaf35b1c062457f2fab586351a196ffa',
    '50a2d772aac8449b0dabfd960a0ba548732ffed9a02d5d38ecf8bd15ac749da0',
    'b12551fe356cacc88ffb2fe290fe43cd5760dd6bdf8eb8262696de8391613810')))
ROUTES = [dict(filename='pre_maturity_announcements_form.html', literal_href='t198sb04_q1',
               exact_label='債券到期前變動各項公告查詢作業'),
          dict(filename='convertible_announcements_form.html', literal_href='t108sb08',
               exact_label='轉換(附認股權)公司債公告(94.5.5起適用)')]
HOST_BASE = 'https://mopsov.twse.com.tw/mops/web/'


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
    def constant(value):
        raise ValueError('Nonfinite JSON: ' + value)
    return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)


def validate_phase_policy(policy):
    require(not any(key in policy for key in ('pending_prior_checkpoint', 'draft', 'is_draft'))
            and not str(policy.get('status', '')).startswith('draft'),
            'Draft/pending document checkpoint cannot authorize IO')
    require(re.fullmatch(r'[0-9a-f]{64}', str(policy.get('prior_checkpoints', {}).get(DOC_CHECKPOINT, ''))),
            'Completed document checkpoint must be explicitly pinned before IO')
    fixed = dict(max_saved_requests=6, max_source_batches=3, workers=2, automatic_retries=0)
    require(all(type(policy.get(k)) is int and policy[k] == v for k, v in fixed.items()),
            'Notice phase allocation drift')
    require(policy['prior_CB_allocations'] == dict(first_discovery_actual=12, contract_route_actual=3,
        documents_actual=6, cumulative_CB_requests_before_phase=21,
        cumulative_CB_request_cap_after_phase=27, documents_unused_three_requests_reused=False,
        contract_route_unused_one_request_reused=False), 'CB21plus6 ledger/unused-allocation drift')
    require(policy['new_allocation'] == dict(initial_generic_form_GETs=2, remaining_request_cap=4,
        remaining_batch_cap=2, all_failed_requests_count=True), 'Notice new allocation drift')
    require(set(policy['batches']) == {'forms'}, 'Unreviewed adaptive notice batch is not authorized')


def select_forms(members, selection, requests, evidence, original, document_selection):
    """Recheck exact nav anchors and full frozen population from saved bytes."""
    require(selection['controls_bond_codes'] == ['99587','68351','68741']
            == original['controls_bond_codes'] == document_selection['controls_bond_codes']
            and selection['original_calendar_population_count'] == original['original_calendar_population_count']
            == document_selection['original_calendar_population_count'] == 29
            and selection['original_calendar_fields'] == original['original_calendar_fields']
            == document_selection['original_calendar_fields']
            and selection['original_calendar_rows'] == original['original_calendar_rows']
            == document_selection['original_calendar_rows']
            and selection['controls'] == document_selection['controls'], 'Frozen29/three-control population drift')
    require(selection['routes'] == ROUTES and len(requests) == 2, 'Exactly two frozen generic routes required')
    require(evidence['source_archive']['sha256'] == ARCHIVES['issuance'], 'Route receipt archive differs')
    for route, request in zip(ROUTES, requests, strict=True):
        require(request == dict(filename=route['filename'], url=HOST_BASE+route['literal_href'], method='GET'),
                'Generic form GET must copy the exact literal route without query parameters')
        saved = [row for row in evidence['routes'] if row['literal_href'] == route['literal_href']]
        require(len(saved) == 1 and saved[0]['exact_label'] == route['exact_label']
                and saved[0]['resolved_url'] == request['url'], 'Route receipt label/resolution drift')
        require({row['source_member'] for row in saved[0]['evidence']}
                == {'raw/'+code+'_issuance.html' for code in BODY_SHAS}, 'All three route evidences required')
        for code, expected_sha in BODY_SHAS.items():
            member = 'raw/'+code+'_issuance.html'
            body = members[member]
            require(hashlib.sha256(body).hexdigest() == expected_sha, 'Issuance body SHA drift')
            meta = strict_json(members[member+'.meta.json'])
            expected_request = next(row for row in document_selection['controls'] if row['bond_code'] == code)
            require(type(meta.get('http_status')) is int and meta['http_status'] == 200
                    and type(meta.get('exit_code')) is int and meta['exit_code'] == 0
                    and meta['sha256'] == expected_sha
                    and meta['request'] == dict(filename=code+'_issuance.html',
                        url=expected_request['issuance_url'], method='GET')
                    and meta['curl']['url_effective'] == expected_request['issuance_url'],
                    'Issuance transport/request identity drift')
            text = body.decode('utf-8', errors='strict')
            tree = html.fromstring(text)
            require(not tree.xpath('//base[@href]'), 'Source base needs explicit review')
            anchors = tree.xpath('//a[@href=$value]', value=route['literal_href'])
            require(len(anchors) == 1 and re.sub(r'\s+', '', anchors[0].text_content()) == route['exact_label']
                    and urljoin(meta['curl']['url_effective'], route['literal_href']) == request['url'],
                    'Actual generic nav label/literal/resolved URL differs')
            proofs = [row for row in saved[0]['evidence'] if row['source_member'] == member]
            require(len(proofs) == 1, 'Duplicate nav evidence')
            proof = proofs[0]
            number = proof['raw_line_number']
            lines = text.splitlines(keepends=True)
            require(type(number) is int and 1 <= number <= len(lines)
                    and lines[number-1] == proof['raw_line_utf8']
                    and hashlib.sha256(lines[number-1].encode()).hexdigest() == proof['raw_line_sha256']
                    and proof['source_body_sha256'] == expected_sha
                    and proof['source_literal'] == route['literal_href']
                    and proof['raw_start_tag'] in lines[number-1], 'Route raw-line evidence differs')
    return dict(generic_forms_only=True, issuer_query_parameters_guessed=False, requests=2,
                original_population_count=29, source_gate_passed=False, holder_put_notice_verified=False)


def module():
    spec = importlib.util.spec_from_file_location('_cb_notices_frontier', Path(__file__).with_name('frontier_sources.py'))
    shared = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shared)
    shared.ROOT, shared.OUT, shared.POLICY = ROOT, OUT, POLICY
    return shared


def verified_prior_members():
    members, count = {}, 0
    for batch, expected_sha in ARCHIVES.items():
        package, _ = readback(DOC_OUT, batch)  # SHA/CRC/manifest readback before parsing.
        require(package['sha256'] == expected_sha, 'Prior document archive differs')
        with zipfile.ZipFile(package['retrieved']) as archive:
            cfg_body = archive.read('requests.json')
            cfg = strict_json(cfg_body)
            require(archive.read('protocol.json') == DOC_POLICY.read_bytes(), 'Prior document protocol differs')
            result = strict_json(archive.read('raw/results.json'))
            require(result['config_sha256'] == hashlib.sha256(cfg_body).hexdigest()
                    and len(cfg['requests']) == 3, 'Prior actual request ledger differs')
            records = verified_records(cfg, result, lambda name: archive.read('raw/'+name))
            require(len(records) == 3, 'Prior saved request population differs')
            count += len(records)
            if batch == 'issuance':
                members = {name: archive.read(name) for name in archive.namelist() if name.startswith('raw/')}
    require(count == 6, 'Prior documents must account for exactly six saved requests')
    return members


def plan(batch='forms'):
    require(batch in ('forms','queries'), 'Only reviewed form/query batches are authorized')
    shared = module()
    policy = strict_json(POLICY.read_bytes())
    validate_phase_policy(policy)
    require(not list(OUT.glob('*_freeze.json')) or all(path.name in ('protocol_freeze.json','queries_freeze.json')
            for path in OUT.glob('*_freeze.json')), 'Unreviewed adaptive freeze refused')
    result = shared.plan(batch)  # Frozen protocol, every prior checkpoint/member, config, budget and shared lock path.
    prior = strict_json(DOC_POLICY.read_bytes())
    require(all(policy['prior_checkpoints'].get(path) == value for path, value in prior['prior_checkpoints'].items()),
            'Every prior document checkpoint must remain pinned')
    cp = strict_json(Path(DOC_CHECKPOINT).read_bytes())
    require(cp['files'].get(str(DOC_POLICY)) == sha256(DOC_POLICY), 'Document policy must be a pinned checkpoint member')
    for key, required_path in [('selection', SELECTION), ('route_evidence', EVIDENCE)]:
        ref = policy[key]
        require(ref['path'] == str(required_path) and sha256(ref['path']) == ref['sha256'], 'Notice selection/evidence SHA drift')
    require(policy['original_selection'] == prior['original_selection']
            and policy['document_selection'] == prior['selection'], 'Prior population selection lineage differs')
    for key in ('original_selection', 'document_selection'):
        require(sha256(policy[key]['path']) == policy[key]['sha256'], 'Prior frozen selection SHA drift')
    forms_cfg = strict_json(FORM_CONFIG.read_bytes())
    if batch == 'forms':
        require(Path(result[0]) == FORM_CONFIG and result[1]['allowed_hosts'] == ['mopsov.twse.com.tw']
                and result[1]['output_directory'] == str(ROOT/'raw_forms'), 'Forms config route/path drift')
    else:
        verify_queries(result)
    select_forms(verified_prior_members(), strict_json(SELECTION.read_bytes()), forms_cfg['requests'],
                 strict_json(EVIDENCE.read_bytes()), strict_json(Path(policy['original_selection']['path']).read_bytes()),
                 strict_json(Path(policy['document_selection']['path']).read_bytes()))
    return result


def verify_queries(result):
    from frontier_cb_notice_forms import query_proof
    package, _ = readback(OUT, 'forms')
    require(package['sha256'] == '1013c6512d7364bd8729510ef2e5edc0f12cd376905a1a5a90bddb7093fbb117', 'Forms archive drift')
    with zipfile.ZipFile(package['retrieved']) as archive:
        body = archive.read('raw/convertible_announcements_form.html')
        meta = strict_json(archive.read('raw/convertible_announcements_form.html.meta.json'))
        require(meta['http_status'] == 200 and meta['exit_code'] == 0
                and meta['sha256'] == hashlib.sha256(body).hexdigest()
                and meta['request']['url'] == HOST_BASE+'t108sb08'
                and meta['curl']['url_effective'] == HOST_BASE+'t108sb08', 'Actual query form transport differs')
    path = OUT/'queries_selection.json'
    frozen = strict_json((OUT/'queries_freeze.json').read_bytes())
    require(frozen['selection'] == dict(path=str(path),sha256=sha256(path)), 'Query selection drift')
    selected = strict_json(path.read_bytes())
    proofs = [query_proof(body, HOST_BASE+'t108sb08', code) for code in ('9958','6835','6874')]
    require(selected['source_archive_sha256'] == package['sha256']
            and selected['query_proofs'] == strict_json(json.dumps(proofs)), 'Actual query form proof drift')
    cfg = result[1]
    expected = [dict(filename=code+'_notices_115.html',url=p['url'],method='POST',data=p['data'])
                for code,p in zip(('99587','68351','68741'),proofs,strict=True)]
    require(Path(result[0]) == Path('configs/frontier_cb_notices_queries_sources_20261023.json')
            and cfg == dict(output_directory=str(ROOT/'raw_queries'),allowed_hosts=['mopsov.twse.com.tw'],requests=expected),
            'All three complete-year query requests must match actual forms')


def execute(stage, batch='forms'):
    plan(batch)
    getattr(module(), stage)(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['plan', 'acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='forms')
    args = parser.parse_args()
    if args.stage == 'plan':
        path, cfg, _, _ = plan(args.batch)
        print(json.dumps(dict(requests=2, batch=args.batch, path=str(path), source_IO_performed=False)))
    else:
        execute(args.stage, args.batch)
