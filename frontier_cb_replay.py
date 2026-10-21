"""Replay the bounded CB source pilot; no bond quotes or returns are read."""
import datetime as dt
from decimal import Decimal
import json
from pathlib import Path
import re
import zipfile

from frontier_cb_metadata import parse_metadata
from frontier_cb_calendar import parse_calendar, reconcile_month
from frontier_sources import plan, archived
from research_runtime import atomic_json, sha256

ROOT = Path('inputs/frontier_20261020')
OUT = Path('deliverables/frontier_20261020')


def saved(batch):
    requests, _, _, freeze = plan(batch)
    package, transfer = archived(batch, requests, freeze)
    with zipfile.ZipFile(package['retrieved']) as archive:
        bodies = {name[4:]: archive.read(name) for name in archive.namelist()
                  if name.startswith('raw/') and not name.endswith(('.headers', '.meta.json'))}
    return package, transfer, bodies


def numeric_index(records):
    result = {}
    for row in records:
        if not re.fullmatch(r'[0-9]{5,6}', row['BondCode']):
            continue
        if row['BondCode'] in result:
            raise ValueError('Duplicate numeric bond code; no last-row replacement')
        result[row['BondCode']] = row
    return result


def run():
    bundles, bodies = {}, {}
    for batch in ('discovery', 'scripts', 'route', 'calendar'):
        package, transfer, files = saved(batch)
        bundles[batch] = dict(sha256=package['sha256'], manifest_files=package['manifest_files'],
                              backup=transfer, crc_manifest_verified=True)
        bodies[batch] = files
    old = parse_metadata(bodies['discovery']['cb_issue_metadata.json'])
    new = parse_metadata(bodies['calendar']['cb_issue_metadata_20261021.json'])
    wide = parse_calendar(bodies['calendar']['put_20261020_20270420.json'],
                          start='2026-10-20', end='2027-04-20')
    narrow = parse_calendar(bodies['calendar']['put_202611.json'],
                            start='2026-11-01', end='2026-11-30')
    partition = reconcile_month(wide, narrow, month='2026-11')
    matches = {}
    for label, metadata in [('20261020', old), ('20261021', new)]:
        index = numeric_index(metadata['records'])
        checks = []
        for row in wide['records']:
            source = index.get(row['bond_code'])
            match = bool(source and source['PutOptionDate'] == row['put_date'].replace('-', '')
                         and Decimal(source['PutOptionPrice']) == Decimal(row['reported_put_amount'])
                         and source['ShortName'] == row['name'])
            checks.append(dict(bond_code=row['bond_code'], put_date=row['put_date'],
                               identity_date_amount_name_agree=match))
        matches[label] = dict(all_rows_match=all(r['identity_date_amount_name_agree'] for r in checks),
                              calendar_rows=len(checks), rows=checks)
    old_identity = {tuple(r[k] for k in ('IssuerCode', 'SeriesNumber', 'TrancheNumber', 'IssueDate'))
                    for r in old['records']}
    new_identity = {tuple(r[k] for k in ('IssuerCode', 'SeriesNumber', 'TrancheNumber', 'IssueDate'))
                    for r in new['records']}
    for name, value in [('metadata_20261020.json', old), ('metadata_20261021.json', new),
                         ('calendar_wide.json', wide), ('calendar_november.json', narrow)]:
        atomic_json(ROOT / name, value)
    atomic_json(OUT / 'cb_source_inventory.json', dict(
        status='bounded_source_schema_and_crosschecks_replayed', archives=bundles,
        metadata_vintages={'20261020': old['summary'], '20261021': new['summary']},
        metadata_source_sha256={'20261020': old['source_sha256'], '20261021': new['source_sha256']},
        old_vintage_replaced=False, newly_observed_metadata_identities=[list(k) for k in sorted(new_identity-old_identity)],
        removed_metadata_identities=[list(k) for k in sorted(old_identity-new_identity)],
        calendar_requested_range=wide['requested_range'], calendar_declared_range=wide['declared_range'],
        calendar_rows=len(wide['records']), november_rows=len(narrow['records']),
        month_partition=partition, metadata_calendar_crosschecks=matches,
        trading_unit_reference='Official introduction:100000TWDface; not the purchase cash or a guaranteed payment',
        source_timestamps='MetadataDate is snapshot label; retrieval timestamps are separately preserved. No first-publication claim.',
        publication_window_verified=False, payment_date_verified=False, source_gate_passed=False,
        reported_yield_is_not_used_as_investor_holding_return=True,
        saved_requests=12, automatic_retries=0, manual_download_requests=0,
        market_quote_or_return_rows_read=0, models_fitted=0, historical_pit_verified=False,
        valid_prospective_signal_date=None, profit_edge_proven=False))
    atomic_json(OUT / 'cb_source_decision.json', dict(
        status='discovery_access_passed_complete_cash_claim_source_gate_unqualified',
        verified='Public metadata and nominal put calendar are retrievable, archived and crosschecked; all original rows/vintages retained',
        unresolved=['No original holder-notice/contract revision control acquired in this discovery scope',
                    'Application opening/cutoff, eligibility, broker/TDCC completion and actual cash-payment date not verified',
                    'Weekend handling, actual repayment/default history and live tradability not inferred from nominal dates or status codes'],
        limitation_is_not_a_transport_denial=True,
        no_claim_that_unrequested_contracts_are_unobtainable=True,
        source_gate_passed=False, next_project_action='continue_reserved_cash_merger_source_preflight',
        user_decision_required=False, user_data_or_credentials_required=None,
        frozen_discovery_budget_used=12, manual_daily_validation=False, orders_authorized=False,
        historical_pit_verified=False, profit_edge_proven=False, valid_prospective_signal_date=None,
        source_inventory_sha256=sha256(OUT / 'cb_source_inventory.json')))


if __name__ == '__main__':
    run()
