"""Dependent source followups within the unchanged combined eight-request cap.

The old current-index phase remains immutable and its unused adaptive branch is
retired. Every stage checks the two saved old requests before using the six
remaining requests through the existing native checkpoint machinery.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
import zipfile

import frontier_sources
from source_checkpoint import readback


ROOT = Path('inputs/cash_merger_current_followthrough_20261022')
OUT = Path('deliverables/cash_merger_current_followthrough_20261022')
POLICY = Path('configs/cash_merger_current_followthrough_protocol_20261022.json')
NOTICE_CONFIG = Path('configs/cash_merger_current_followthrough_notices_sources_20261022.json')
SELECTION = OUT / 'selection.json'
INDEX_OUT = Path('deliverables/cash_merger_current_20261021')
INDEX_REQUESTS = Path('configs/cash_merger_current_index_sources_20261021.json')
INDEX_CHECKPOINT = INDEX_OUT / 'checkpoint.json'
NOTICE_IDENTITIES = (
    ('M17:6674:2026-09-21:155000:1', 'meeting_amendment_6674_20260921.html'),
    ('M17:6674:2026-09-18:202533:4', 'meeting_original_6674_20260918.html'),
    ('M99:6674:2026-09-18:194028:2', 'delisting_proposal_6674_20260918.html'),
)


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def _bound_file(reference, path):
    body = path.read_bytes()
    if (not isinstance(reference, dict) or reference.get('path') != str(path)
            or reference.get('sha256') != _digest(body)):
        raise ValueError('Followthrough configuration/selection binding drift')
    return body


def validate_notice_plan():
    """Verify the immutable spent ledger and exact three notice allocations."""
    policy = json.loads(POLICY.read_bytes())
    ledger = policy.get('source_ledger', {})
    if (policy.get('max_saved_requests') != 6 or policy.get('max_source_batches') != 6
            or ledger.get('completed_saved_requests') != 2
            or ledger.get('remaining_saved_requests') != 6
            or ledger.get('combined_request_ceiling') != 8
            or ledger.get('old_unused_adaptive_branch_retired') is not True):
        raise ValueError('Combined saved-request ledger must remain two plus six equals eight')
    prior = policy.get('prior_checkpoints', {}).get(str(INDEX_CHECKPOINT))
    if not isinstance(prior, str) or not re.fullmatch(r'[0-9a-f]{64}', prior):
        raise ValueError('Awaiting pinned current-index checkpoint')
    old_reference = ledger.get('prior_requests')
    old_body = _bound_file(old_reference, INDEX_REQUESTS)
    old_requests = json.loads(old_body)['requests']
    if old_reference.get('requests') != 2 or len(old_requests) != 2:
        raise ValueError('Prior phase must account for exactly two saved requests')
    if any(path.name != 'index_package.json' for path in INDEX_OUT.glob('*_package.json')):
        raise ValueError('Retired old adaptive branch has another saved source batch')
    source = policy.get('source_index', {})
    if (source.get('out') != str(INDEX_OUT) or source.get('batch') != 'index'
            or source.get('member') != 'raw/target_6674_m00.json'):
        raise ValueError('Unexpected prior index source locator')
    package, _ = readback(INDEX_OUT, 'index')
    if package['sha256'] != source.get('archive_sha256'):
        raise ValueError('Prior index archive differs from frozen source ledger')
    with zipfile.ZipFile(package['retrieved']) as archive:
        archived_requests = archive.read('requests.json')
        results = json.loads(archive.read('raw/results.json'))
        records = results.get('requests')
        if (archived_requests != old_body or results.get('config_sha256') != _digest(old_body)
                or not isinstance(records, list) or len(records) != 2
                or [record.get('request') for record in records] != old_requests):
            raise ValueError('Saved prior requests do not reconcile to the spent ledger')
        for record in records:
            name = record['request']['filename']
            if json.loads(archive.read('raw/'+name+'.meta.json')) != record:
                raise ValueError('Prior transport metadata drift')
        raw_index = archive.read(source['member'])
    if _digest(raw_index) != source.get('body_sha256'):
        raise ValueError('Prior target index body drift')
    index_rows = json.loads(raw_index)['data']
    selected = json.loads(_bound_file(policy.get('selection_manifest'), SELECTION))
    rows = selected.get('rows')
    if (selected.get('source_index_sha256') != _digest(raw_index)
            or not isinstance(rows, list)
            or [(row.get('event_id'), row.get('new_filename')) for row in rows] != list(NOTICE_IDENTITIES)):
        raise ValueError('Three exact index notice pointers must remain allocated')
    config_reference = policy.get('batches', {}).get('notices')
    cfg = json.loads(_bound_file(config_reference, NOTICE_CONFIG))
    if (config_reference.get('requests') != 3
            or cfg.get('output_directory') != str(ROOT / 'raw_notices')
            or cfg.get('allowed_hosts') != ['mopsov.twse.com.tw']
            or len(cfg.get('requests', [])) != 3):
        raise ValueError('Unexpected initial followthrough notice configuration')
    for selected_row, request in zip(rows, cfg['requests']):
        original = selected_row.get('index_original_fields')
        if (original not in index_rows or original.get('COMPANY_ID') != '6674'
                or set(request) != {'filename', 'url'}
                or request['filename'] != selected_row['new_filename']
                or request['url'] != original['HYPERLINK']):
            raise ValueError('Notice request differs from its complete saved index row')
        day = original['CDATE'].split('/')
        expected_day = str(int(day[0])+1911)+'-'+day[1]+'-'+day[2]
        event = selected_row['event_id'].split(':')
        query = parse_qs(urlparse(original['HYPERLINK']).query, keep_blank_values=True)
        if (len(event) != 5
                or event[:4] != [original['AN_CODE'], '6674', expected_day,
                                original['CTIME'].replace(':', '')]
                or query.get('SEQ_NO') != [event[4]]):
            raise ValueError('Notice event identity differs from the saved row')
    return cfg


def _source_module():
    validate_notice_plan()
    # Separate pipeline processes only; the parent serializes old/new phases.
    frontier_sources.ROOT = ROOT
    frontier_sources.OUT = OUT
    frontier_sources.POLICY = POLICY
    return frontier_sources


def plan(batch='notices'):
    return _source_module().plan(batch)


def acquire(batch='notices'):
    return _source_module().acquire(batch)


def package(batch='notices'):
    return _source_module().package(batch)


def verify(batch='notices'):
    return _source_module().verify(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='notices')
    arguments = parser.parse_args()
    globals()[arguments.stage](arguments.batch)
