"""Replay frozen broad M11 sources and six controls, without prices or returns."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

from merger_announcement_index import parse_index
from merger_document import parse_document
import merger_sources
from research_runtime import atomic_json, sha256

ROOT = Path('inputs/cash_merger_20261021')
OUT = Path('deliverables/cash_merger_20261021')


def saved(batch):
    module = merger_sources._source_module()
    requests, _, _, freeze = module.plan(batch)
    package, transfer = module.archived(batch, requests, freeze)
    with zipfile.ZipFile(package['retrieved']) as archive:
        bodies = {name[4:]: archive.read(name) for name in archive.namelist()
                  if name.startswith('raw/') and not name.endswith(('.headers', '.meta.json'))}
    return package, transfer, bodies


def partition(quarter, months):
    a = {row['event_id']: row['original_fields'] for row in quarter['rows']}
    b = {}
    for month in months:
        for row in month['rows']:
            if row['event_id'] in b:
                raise ValueError('Monthly partitions overlap or duplicate a document pointer')
            b[row['event_id']] = row['original_fields']
    return dict(missing_from_months=sorted(a.keys()-b.keys()),
                extra_in_months=sorted(b.keys()-a.keys()),
                changed_original_fields=sorted(k for k in a.keys() & b.keys() if a[k] != b[k]),
                current_response_partition_agreement=a == b,
                quarter_rows=len(a), monthly_rows=len(b),
                historical_completeness_proven=False)


def run():
    package, transfer, files = saved('discovery')
    quarter = parse_index(files['m11_2026q3.json'])
    months = [parse_index(files[name], start, end) for name, start, end in [
        ('m11_202607.json', '2026-07-01', '2026-07-31'),
        ('m11_202608.json', '2026-08-01', '2026-08-31'),
        ('m11_202609.json', '2026-09-01', '2026-09-30')]]
    agreement = partition(quarter, months)
    if not agreement['current_response_partition_agreement']:
        raise ValueError('Quarter/month returned original fields differ')
    control_pkg, control_transfer, original_files = saved('controls')
    selection = json.loads((OUT / 'controls_selection.json').read_text())
    by_url = {row['url']: row for row in quarter['rows']}
    controls = []
    source_config = json.loads(Path('configs/cash_merger_controls_sources_20261021.json').read_text())
    for item, chosen in zip(source_config['requests'], selection['rows'], strict=True):
        source = chosen['original_fields']
        if source != by_url[item['url']]['original_fields'] or item['url'] != source['HYPERLINK']:
            raise ValueError('Frozen control selection differs from source index')
        document = parse_document(original_files[item['filename']], source)
        controls.append(dict(filename=item['filename'], role=chosen['role'],
                             index_event_id=by_url[item['url']]['event_id'], **document))
    pair = [row for row in controls if row['role'] == 'legacy_sequence_collision_control']
    if (len(pair) != 2 or pair[0]['sequence'] != pair[1]['sequence']
            or pair[0]['issuer'] != pair[1]['issuer']
            or pair[0]['reported_datetime'] == pair[1]['reported_datetime']
            or pair[0]['description_sha256'] == pair[1]['description_sha256']):
        raise ValueError('Selected legacy collision control did not retain distinct originals')
    # This is a disclosed title universe, not all statutory cash transactions.
    pattern = re.compile(r'合併|股份轉換|股份轉交換|\bmerg(?:er|e|ing)\b|\bshare\s+(?:swap|exchange)\b', re.I)
    title_cohort = [row for row in quarter['rows'] if pattern.search(row['original_fields']['SUBJECT'])]
    atomic_json(ROOT / 'quarter_index_full.json', quarter)
    atomic_json(ROOT / 'monthly_indices_full.json', months)
    atomic_json(ROOT / 'controls_full.json', controls)
    atomic_json(OUT / 'index_replay.json', dict(
        status='current_m11_indices_and_six_controls_replayed',
        quarter_rows=len(quarter['rows']), month_rows=[len(m['rows']) for m in months],
        quarter_source_sha256=quarter['body_sha256'], partition=agreement,
        query_market_qualified=quarter['query_market_qualified'],
        legacy_key_collisions=quarter['legacy_key_collisions'],
        controls=[{k:v for k,v in row.items() if k not in ('description', 'raw_metadata', 'index_original_fields')}
                  for row in controls],
        collision_pair_distinct_retained_descriptions=True,
        explicit_merger_title_cohort_count=len(title_cohort),
        explicit_merger_title_cohort=[dict(event_id=r['event_id'], company_id=r['company_id'],
            reported_timestamp_taipei=r['reported_timestamp_taipei'], subject=r['original_fields']['SUBJECT'],
            original_document_in_six_controls=r['url'] in {c['source_url'] for c in controls}) for r in title_cohort],
        archives=[dict(sha256=p['sha256'], manifest_files=p['manifest_files'], backup=t)
                  for p,t in [(package,transfer),(control_pkg,control_transfer)]],
        all_eligible_cash_mergers_known=False, historical_pit_verified=False,
        source_gate_passed=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, market_prices_or_returns_read=False))
    atomic_json(OUT / 'next_tasks.json', dict(
        status='index_and_controls_replayed_explicit_title_census_pending',
        next_project_action='Freeze and acquire the finite remaining original documents of the explicit19title census, reusing archived controls; no new hypothesis or outcome search',
        qualification_source_gate_passed=False,
        source_gap='Only six controls read; broad M11 and title subset are not a complete eligible cash-claim census',
        no_claim_unrequested_sources_unobtainable=True,
        user_decision_required=False, user_data_or_credentials_required=None,
        historical_pit_verified=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, orders_authorized=False,
        replay_sha256=sha256(OUT / 'index_replay.json')))


if __name__ == '__main__':
    run()
