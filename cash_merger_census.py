"""Replay the complete frozen explicit-title census, without cash-claim guesses.

All original descriptions stay in ignored inputs.  The small output contains
document identities, hashes, subjects and archive provenance only.  A complete
title census does not establish all cash deals or an executable cash claim.
"""
import hashlib
import json
from pathlib import Path
import re
import zipfile

from merger_announcement_index import parse_index
from merger_document import parse_document
import merger_census_sources
from research_runtime import atomic_json, sha256
from source_checkpoint import readback
from tender_preflight import verified_records

ROOT = Path('inputs/cash_merger_census_20261021')
OUT = Path('deliverables/cash_merger_census_20261021')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_locator(row):
    old, new = row.get('original_source'), row.get('new_filename')
    require(bool(old) != bool(new), 'Each selected original needs exactly one saved source locator')
    if old:
        require(isinstance(old, dict) and set(old) == {'archive_sha256', 'member'}
                and re.fullmatch(r'[0-9a-f]{64}', old['archive_sha256'])
                and re.fullmatch(r'raw/[A-Za-z0-9_.-]+', old['member']), 'Invalid reused source locator')
        return dict(old)
    require(isinstance(new, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', new)
            and new not in ('.', '..'), 'Unsafe new original filename')
    return dict(new_filename=new)


def _selected_rows(quarter, selection, title_census):
    require(selection['source_quarter_sha256'] == quarter['body_sha256']
            == title_census['quarter_source_sha256'], 'Quarter source snapshot differs')
    expected = [row['event_id'] for row in title_census['explicit_merger_title_cohort']]
    require(len(expected) == title_census['explicit_merger_title_cohort_count'] == len(set(expected)),
            'Pinned title census has duplicate or inconsistent identities')
    selected = selection['rows']
    identities = [row['event_id'] for row in selected]
    require(len(identities) == len(set(identities)) and sorted(identities) == sorted(expected),
            'Selection does not preserve the entire frozen explicit-title census')
    index = {row['event_id']: row for row in quarter['rows']}
    require(len(index) == len(quarter['rows']), 'Duplicate quarter pointer identities')
    for row in selected:
        require(row['event_id'] in index
                and row['index_original_fields'] == index[row['event_id']]['original_fields'],
                'Selected original fields differ from pinned quarter')
        source_locator(row)
    return selected, expected


def validate_selection(cfg, requests_cfg, quarter, selection, title):
    """Bind the finite request plan to every saved pointer before live IO."""
    require((cfg['expected_documents'], cfg['expected_new_requests'], cfg['expected_reused_documents'])
            == (19, 15, 4), 'Fixed census scope must remain19 originals/15 new/4 reused')
    rows, _ = _selected_rows(quarter, selection, title)
    new = [row for row in rows if 'new_filename' in source_locator(row)]
    old = [row for row in rows if 'original_source' in row]
    require((len(rows), len(new), len(old)) == (19, 15, 4), 'Selected19/15/4 census scope differs')
    requests = {item['filename']: item for item in requests_cfg['requests']}
    require(len(requests) == len(requests_cfg['requests']) == 15
            and sorted(row['new_filename'] for row in new) == sorted(requests),
            'New filename selection differs from exact15 request plan')
    for row in new:
        require(requests[row['new_filename']]['url'] == row['index_original_fields']['HYPERLINK'],
                'New requested URL differs from original pointer')
    registered = [spec['archive_sha256'] for spec in cfg['reused_archives']]
    require(len(registered) == len(set(registered))
            and {row['original_source']['archive_sha256'] for row in old} == set(registered),
            'Selected old original lacks exact pinned archive routing')
    locators = [(row['original_source']['archive_sha256'], row['original_source']['member']) for row in old]
    require(len(locators) == len(set(locators)), 'Duplicate reused original routing')


def replay_documents(quarter, selection, title_census, bodies):
    """Pure exact-population and document-identity replay of the pinned census."""
    selected, expected = _selected_rows(quarter, selection, title_census)
    require(set(bodies) == set(expected), 'Saved original body population differs')
    full = []
    for row in selected:
        identity = row['event_id']
        document = parse_document(bodies[identity], row['index_original_fields'])
        full.append(dict(event_id=identity, source_locator=source_locator(row),
                         index_original_fields=row['index_original_fields'], **document))
    summary = dict(
        status='explicit_title_census_identity_replayed_terms_unqualified',
        source_quarter_sha256=quarter['body_sha256'], document_count=len(full),
        new_document_count=sum('new_filename' in row['source_locator'] for row in full),
        reused_document_count=sum('archive_sha256' in row['source_locator'] for row in full),
        frozen_title_event_ids=sorted(expected), all_selected_original_identities_verified=True,
        documents=[{key: value for key, value in row.items()
                    if key not in ('description', 'raw_metadata', 'index_original_fields')}
                   for row in full],
        title_census_is_all_eligible_cash_mergers=False,
        transaction_semantics_classified=False, cash_claim_source_gate_passed=False,
        all_eligible_cash_mergers_known=False, historical_pit_verified=False,
        source_gate_passed=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, market_prices_or_returns_read=False,
        orders_authorized=False,
    )
    return full, summary


def _archive(spec):
    package, transfer = readback(spec['out'], spec['batch'])
    require(package['sha256'] == spec['archive_sha256'], 'Pinned original archive differs')
    return package, transfer


def require_successful_originals(records):
    require(all(type(row.get('http_status')) is int and row['http_status'] == 200
                and type(row.get('exit_code')) is int and row['exit_code'] == 0 for row in records),
            'Original source requires HTTP200 and exit0; failed transport remains archived evidence')


def preflight(module, batch, requests_cfg):
    """Read only verified prior archives; all request bindings precede native IO."""
    cfg = json.loads(module.POLICY.read_text())
    require(batch == cfg.get('source_batch', 'originals'), 'Wrong census source batch')
    selection_ref, title_ref = cfg['selection_manifest'], cfg['title_census']
    for ref in (selection_ref, title_ref):
        require(sha256(ref['path']) == ref['sha256'], 'Frozen selection or title census differs')
    selection = json.loads(Path(selection_ref['path']).read_text())
    title = json.loads(Path(title_ref['path']).read_text())
    quarter_ref = cfg['source_quarter']
    quarter_pkg, quarter_transfer = _archive(quarter_ref)
    require(re.fullmatch(r'raw/[A-Za-z0-9_.-]+', quarter_ref['member']), 'Unsafe quarter archive member')
    with zipfile.ZipFile(quarter_pkg['retrieved']) as archive:
        quarter_body = archive.read(quarter_ref['member'])
    quarter = parse_index(quarter_body, quarter_ref['start'], quarter_ref['end'])
    require(quarter['body_sha256'] == quarter_ref['body_sha256'], 'Frozen quarter body differs')
    validate_selection(cfg, requests_cfg, quarter, selection, title)
    reused = {}
    for spec in cfg['reused_archives']:
        package, transfer = _archive(spec)
        require(package['sha256'] not in reused, 'Duplicate reused archive registration')
        reused[package['sha256']] = (package, transfer)
        with zipfile.ZipFile(package['retrieved']) as archive:
            old_cfg = json.loads(archive.read('requests.json'))
            results = json.loads(archive.read('raw/results.json'))
            require(results['config_sha256'] == hashlib.sha256(archive.read('requests.json')).hexdigest(),
                    'Reused source configuration differs')
            records = verified_records(old_cfg, results, lambda name: archive.read('raw/' + name))
            routes = {r['request']['filename']: r for r in records}
            for row in selection['rows']:
                locator = source_locator(row)
                if locator.get('archive_sha256') != package['sha256']:
                    continue
                name = locator['member'].removeprefix('raw/')
                require(name in routes and routes[name]['request']['url'] == row['index_original_fields']['HYPERLINK'],
                        'Reused original route differs from pinned pointer')
                require_successful_originals([routes[name]])
                parse_document(archive.read(locator['member']), row['index_original_fields'])
    return dict(cfg=cfg, selection=selection, title=title, quarter=quarter,
                quarter_pkg=quarter_pkg, quarter_transfer=quarter_transfer, reused=reused)


def run():
    module = merger_census_sources._source_module()
    batch = json.loads(module.POLICY.read_text()).get('source_batch', 'originals')
    requests_path, requests_cfg, _, freeze = module.plan(batch)
    state = preflight(module, batch, requests_cfg)
    cfg, selection, title, quarter = (state[key] for key in ('cfg', 'selection', 'title', 'quarter'))
    reused = state['reused']
    new_pkg, new_transfer = module.archived(batch, requests_path, freeze)
    with zipfile.ZipFile(new_pkg['retrieved']) as archive:
        results = json.loads(archive.read('raw/results.json'))
        require(results['config_sha256'] == sha256(requests_path), 'New acquisition configuration differs')
        records = verified_records(requests_cfg, results, lambda name: archive.read('raw/' + name))
        require_successful_originals(records)
    bodies = {}
    for row in selection['rows']:
        locator = source_locator(row)
        if 'new_filename' in locator:
            name = locator['new_filename']
            package, member = new_pkg, 'raw/' + name
        else:
            require(locator['archive_sha256'] in reused, 'Selected old original lacks pinned archive')
            package, _ = reused[locator['archive_sha256']]
            member = locator['member']
        require(row['event_id'] not in bodies, 'Duplicate selected event identity')
        with zipfile.ZipFile(package['retrieved']) as archive:
            bodies[row['event_id']] = archive.read(member)
    full, summary = replay_documents(quarter, selection, title, bodies)
    require(summary['document_count'] == 19 and summary['reused_document_count'] == 4,
            'Replayed census count differs')
    summary.update(protocol_sha256=sha256(module.POLICY), selection_manifest_sha256=cfg['selection_manifest']['sha256'],
                   title_census_sha256=cfg['title_census']['sha256'],
                   archives=[dict(sha256=p['sha256'], manifest_files=p['manifest_files'], backup=t)
                             for p, t in [(state['quarter_pkg'], state['quarter_transfer']),
                                          (new_pkg, new_transfer), *reused.values()]])
    atomic_json(ROOT / 'documents_full.json', full)
    atomic_json(OUT / 'replay_summary.json', summary)


if __name__ == '__main__':
    run()
