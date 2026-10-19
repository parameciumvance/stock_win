"""Reconcile captured buyback sources without estimating returns or certifying PIT."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import zipfile

from buyback_announcement_index import parse_index
from research_runtime import atomic_json, sha256
from source_checkpoint import readback
from tender_preflight import Tables

OUT = Path('deliverables/buyback_preflight_20261020')
ROOT = Path('inputs/buyback_preflight_20261020')


def saved(tag, filename):
    package, transfer = readback(OUT, tag)
    with zipfile.ZipFile(package['retrieved']) as z:
        return z.read('raw/' + filename)


def annual_rows(body):
    parser = Tables()
    parser.feed(body.decode('utf-8'))
    rows = [[''.join(c).strip() for c in r] for t in parser.tables for r in t]
    rows = [r for r in rows if len(r) == 20 and re.fullmatch(r'\d+', r[0])]
    if [int(r[0]) for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError('Non-contiguous annual row sequence')
    text = ''.join(body.decode('utf-8').split())
    counts = re.search(r'共計(\d+)家公司[，,、。]?\(?計(\d+)件', text)
    if counts is None:
        # The official page puts companies and cases in separate rows.
        companies = re.search(r'合計[：:]?(\d+)家', text)
        cases = re.search(r'合計[：:]?(\d+)件', text)
        if not companies or not cases:
            raise ValueError('Annual reported counts not found')
        expected = int(companies[1]), int(cases[1])
    else:
        expected = int(counts[1]), int(counts[2])
    if expected != (len({r[1] for r in rows}), len(rows)):
        raise ValueError('Annual declared count mismatch')
    for r in rows:
        if not re.fullmatch(r'\d{4}', r[1]) or not re.fullmatch(r'113/\d{2}/\d{2}', r[3]):
            raise ValueError('Annual issuer or decision date outside fixed scope')
        date(2024, int(r[3][4:6]), int(r[3][7:9]))
    if '最新財報' not in text:
        raise ValueError('Expected legal-cap semantics changed')
    return rows


def audit():
    from buyback_original_document import parse_document
    body = saved('query', 'announcements_2024.json')
    op = json.loads(Path('configs/buyback_originals_protocol_20261020.json').read_text())
    if hashlib.sha256(body).hexdigest() != op['pinned_index_body_sha256']:
        raise ValueError('Original pilot source-index snapshot drift')
    index = parse_index(body)
    annual = annual_rows(saved('discovery', 'annual_2024.html'))
    selected = json.loads((OUT / 'originals_selection.json').read_text())['selected']
    config = json.loads(Path('configs/buyback_originals_sources_20261020.json').read_text())
    documents = []
    for r, req in zip(selected, config['requests'], strict=True):
        body = saved('originals', req['filename'])
        doc = parse_document(body, r)
        # Keep the original long employee-transfer clauses in the raw archive.
        # Git carries selected terms and hashes, not duplicated full documents.
        fields = doc['numbered_fields']
        doc['numbered_field_count'] = len(fields)
        doc['numbered_field_sha256'] = {k: hashlib.sha256(v.encode('utf-8')).hexdigest() for k, v in fields.items()}
        doc['numbered_fields'] = {k: v for k, v in fields.items() if int(k) <= 7}
        doc['reported_fields'].pop('說明')
        doc.update(filename=req['filename'], body_sha256=hashlib.sha256(body).hexdigest(), url=r['HYPERLINK'], selection_reason=r['selection_reason'])
        documents.append(doc)
    old = documents[-2]
    correction = documents[-1]
    if old['issuer'] != correction['issuer'] or old['reported_datetime'] >= correction['reported_datetime']:
        raise ValueError('Correction chronology mismatch')
    a, b = old['numbered_fields'], correction['numbered_fields']
    compact = lambda s: ''.join(s.split())
    if not all(compact(a[k]) == compact(b[k]) for k in ['1', '5', '6', '7']):
        raise ValueError('Selected correction does not match board date/period/quantity/price')
    changed = [k for k in old['numbered_field_sha256'] if old['numbered_field_sha256'][k] != correction['numbered_field_sha256'].get(k)]
    if '4' not in changed:
        raise ValueError('Expected correction control did not preserve different legal-cap fields')
    annual_refs = []
    for row in annual:
        matches = [r['event_id'] for r in index['rows'] if r['original_fields']['COMPANY_ID'] == row[1] and r['original_fields']['CDATE'] == row[3]]
        annual_refs.append(dict(serial=int(row[0]), issuer=row[1], name=row[2], board_date_roc=row[3], matching_same_day_messages=matches, original_columns=row))
    atomic_json(OUT / 'announcement_index.json', index)
    atomic_json(OUT / 'annual_snapshot.json', dict(rows=annual_refs, companies=len({r[1] for r in annual}), cases=len(annual),
        declared_counts_reconciled=True, date_basis='Board resolution date; not the announcement-date population', latest_statement_cap_not_asof_feature=True,
        current_snapshot_only=True, historical_pit_verified=False))
    atomic_json(OUT / 'originals_audit.json', dict(documents=documents, identity_and_reported_times_matched=len(documents),
        correction_control=dict(issuer=old['issuer'], original_reported_datetime=old['reported_datetime'], correction_reported_datetime=correction['reported_datetime'],
            changed_fields=changed, before_field4=a['4'], after_field4=b['4'], both_current_source_versions_preserved=True,
            linkage_scope='Same issuer, board date, planned period, quantity and price; two retained official pages. Not full-year immutable-version proof.'),
        source_gate_passed=False, historical_pit_verified=False))
    atomic_json(OUT / 'decision.json', dict(status='automatic_route_verified_historical_research_gate_unqualified',
        annual_current_snapshot_cases=len(annual), annual_current_snapshot_issuers=len({r[1] for r in annual}), captured_m35_announcements=len(index['rows']),
        annual_cases_with_same_day_message=sum(bool(r['matching_same_day_messages']) for r in annual_refs),
        announcement_api_declared_total=index['declared_total'], announcement_count_reconciled=index['count_reconciliation_passed'],
        original_pages_identity_and_reported_times_matched=len(documents), correction_pair_versions_preserved=True,
        source_gate_passed=False, automatic_source_route_verified=True, historical_population_verified=False,
        historical_original_availability_verified=False, current_index_is_not_first_seen_archive=True,
        remaining_evidence_gaps=['M35 response has no declared total; 122 rows and client limit cannot certify announcement-date completeness, including cross-year board decisions',
            'Annual 47-case list uses board dates and current legal-cap fields; cannot substitute it for original announcement-date features',
            'Only seven fixed original controls were commissioned; full original/correction/cancellation chains and absence of overwritten or withdrawn records have not been verified',
            'Reported publication timestamps match seven current pages; no independent historical first-seen capture proves all fields were available before an assumed entry'],
        decision='Retain working automatic collector and provenance tools. Do not backtest, expand downloads or deploy daily human validation on unqualified historical input. This is not a failed-return finding.',
        market_outcomes_inspected=False, new_model_fitted=False, prior_rules_changed=False, profit_edge_proven=False,
        orders_authorized=False, valid_prospective_signal_date=None, user_action_required=None))


def independent_annual_rows(body):
    from lxml import html
    tree = html.fromstring(body, parser=html.HTMLParser(encoding='utf-8'))
    rows = []
    for tr in tree.xpath('//tr'):
        cells = tr.xpath('./td')
        values = [''.join(c.itertext()).strip() for c in cells]
        if len(values) == 20 and re.fullmatch(r'\d+', values[0]):
            rows.append(values)
    return rows


def independent():
    from lxml import html
    rows = independent_annual_rows(saved('discovery', 'annual_2024.html'))
    annual = json.loads((OUT / 'annual_snapshot.json').read_text())
    compact = lambda r: [''.join(v.split()) for v in r]
    if [compact(r) for r in rows] != [compact(r['original_columns']) for r in annual['rows']]:
        raise ValueError('Independent annual table parser disagrees')
    raw = json.loads(saved('query', 'announcements_2024.json').decode('utf-8-sig'))['data']
    ix = json.loads((OUT / 'announcement_index.json').read_text())
    if [r['original_fields'] for r in ix['rows']] != raw:
        raise ValueError('Index did not preserve all captured fields')
    original = json.loads((OUT / 'originals_audit.json').read_text())
    config = json.loads(Path('configs/buyback_originals_sources_20261020.json').read_text())
    selected = json.loads((OUT / 'originals_selection.json').read_text())['selected']
    for d, req, selected_row in zip(original['documents'], config['requests'], selected, strict=True):
        page = html.fromstring(saved('originals', req['filename']), parser=html.HTMLParser(encoding='utf-8'))
        texts = [''.join(t.itertext()) for t in page.xpath('//table')]
        flat = ''.join(''.join(texts).split())
        for value in [selected_row['COMPANY_ID'], selected_row['CDATE'], selected_row['CTIME'], selected_row['SUBJECT']]:
            if ''.join(value.split()) not in flat:
                raise ValueError('Independent issuer/time/subject mismatch')
        for value in d['numbered_fields'].values():
            if ''.join(value.split()) not in flat:
                raise ValueError('Parsed primary field not in official table')
    atomic_json(OUT / 'independent_audit.json', dict(status='passed_current_snapshot_and_selected_originals_only',
        annual_rows=len(rows), preserved_index_rows=len(raw), original_controls=len(original['documents']),
        methods=['lxml annual table extraction versus standard HTMLParser', 'Direct JSON equality of all captured index rows', 'lxml selected original table identity and exact field containment'],
        historical_population_verified=False, historical_pit_verified=False, no_market_outcomes_inspected=True))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['audit', 'independent'])
    globals()[p.parse_args().stage]()
