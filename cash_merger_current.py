"""Replay the frozen target/buyer M00 indices, without inferring deal status.

Only archived, read-back verified bytes are parsed. Every returned category and
original field stays in ignored inputs; the small output retains every pointer,
subject and reported date. Current eligibility still requires original terms.
"""
import json
from pathlib import Path
import zipfile

from corporate_announcement_index import parse_index
import merger_current_sources
from research_runtime import atomic_json, sha256
from tender_preflight import verified_records

ROOT = Path('inputs/cash_merger_current_20261021')
OUT = Path('deliverables/cash_merger_current_20261021')
START, END = '2026-09-18', '2026-10-21'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def replay_indices(queries, bodies):
    """Pure all-row replay of the two exact frozen issuer/date queries."""
    require(isinstance(queries, list) and len(queries) == 2, 'Expected exactly two frozen issuer queries')
    require({q['issuer'] for q in queries} == {'6674', '2324'}, 'Frozen target/buyer issuer population differs')
    filenames = [q['filename'] for q in queries]
    require(len(set(filenames)) == 2 and set(bodies) == set(filenames), 'Saved index body population differs')
    indices = {}
    for query in queries:
        require((query['category'], query['start'], query['end']) == ('M00', START, END),
                'Frozen all-category/range query differs')
        indices[query['issuer']] = parse_index(bodies[query['filename']], query['issuer'], START, END)
    summary = dict(
        status='target_buyer_all_category_returned_indices_replayed_current_terms_unverified',
        query_start=START, query_end=END, query_category='M00', issuer_count=2,
        query_results=[dict(issuer=query['issuer'], filename=query['filename'],
                           body_sha256=indices[query['issuer']]['body_sha256'],
                           returned_row_count=indices[query['issuer']]['current_response_row_count'],
                           declared_total=indices[query['issuer']]['declared_total'],
                           count_reconciliation_passed=indices[query['issuer']]['count_reconciliation_passed'],
                           observed_categories=indices[query['issuer']]['observed_categories'],
                           observed_market_labels=indices[query['issuer']]['observed_market_labels'],
                           legacy_sequence_collisions=indices[query['issuer']]['legacy_sequence_collisions'])
                       for query in queries],
        returned_announcements=[dict(issuer=issuer, event_id=row['event_id'],
                                     pointer_identity=row['pointer_identity'],
                                     reported_category=row['reported_category'],
                                     reported_timestamp_taipei=row['reported_timestamp_taipei'],
                                     subject=row['original_fields']['SUBJECT'], url=row['url'],
                                     original_document_verified=False)
                                for issuer, index in indices.items() for row in index['rows']],
        all_returned_rows_and_categories_preserved=True, title_filter_performed=False,
        complete_announcement_population_verified=False, no_later_notice_proven=False,
        current_tradability_verified=False, current_transaction_status_verified=False,
        notice_window_verified=False, payment_date_verified=False,
        contractual_cash_claim_verified=False, cash_claim_source_gate_passed=False,
        historical_pit_verified=False, first_publication_time_verified=False,
        source_gate_passed=False, profit_edge_proven=False, valid_prospective_signal_date=None,
        market_prices_or_returns_read=False, orders_authorized=False,
    )
    return indices, summary


def require_successful_indices(records):
    require(len(records) == 2 and all(type(row.get('http_status')) is int and row['http_status'] == 200
            and type(row.get('exit_code')) is int and row['exit_code'] == 0 for row in records),
            'Both index sources require HTTP200 and exit0; failed transport is preserved, not qualified')


def run():
    module = merger_current_sources._source_module()
    batch = 'index'
    requests_path, requests_cfg, _, freeze = merger_current_sources.plan(batch)
    cfg = json.loads(module.POLICY.read_text())
    require(cfg.get('source_batch') == batch, 'Current-status source batch differs')
    queries = cfg['index_queries']
    require(len(queries) == 2 and {q['filename'] for q in queries}
            == {q['filename'] for q in requests_cfg['requests']}, 'Frozen index queries/request plan differ')
    package, transfer = module.archived(batch, requests_path, freeze)
    with zipfile.ZipFile(package['retrieved']) as archive:
        results = json.loads(archive.read('raw/results.json'))
        require(results['config_sha256'] == sha256(requests_path), 'Archived result configuration differs')
        records = verified_records(requests_cfg, results, lambda name: archive.read('raw/' + name))
        require_successful_indices(records)
        bodies = {q['filename']: archive.read('raw/' + q['filename']) for q in queries}
    full, summary = replay_indices(queries, bodies)
    summary.update(protocol_sha256=sha256(module.POLICY), requests_sha256=sha256(requests_path),
                   archive=dict(sha256=package['sha256'], manifest_files=package['manifest_files'], backup=transfer))
    atomic_json(ROOT / 'index_full.json', full)
    atomic_json(OUT / 'index_replay.json', summary)


if __name__ == '__main__':
    run()
