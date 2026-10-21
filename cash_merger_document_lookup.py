"""Inventory every saved meeting-book lookup row and declared interaction.

This is a byte-bound HTML inventory, not a document-completion or contractual
qualification parser. No JavaScript runs and no returned pointer is followed.
"""
import hashlib
import json
from pathlib import Path
import zipfile

from lxml import html

from cash_merger_current_notices import extract_pointers
import merger_documents_sources
from research_runtime import atomic_json, sha256
from tender_preflight import verified_records

ROOT = Path('inputs/cash_merger_documents_20261022')
OUT = Path('deliverables/cash_merger_documents_20261022')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(node):
    return ''.join(node.itertext())


def inventory_html(body: bytes):
    """Preserve all source rows, form controls and exact declared link values."""
    require(isinstance(body, bytes) and bool(body), 'Expected nonempty original HTML bytes')
    source = body.decode('utf-8-sig', errors='strict')
    require('<' in source and '>' in source, 'Saved query response is not HTML')
    tree = html.document_fromstring(source)
    tables = tree.xpath('//table')
    table_positions = {table: number for number, table in enumerate(tables, 1)}
    rows = []
    for number, row in enumerate(tree.xpath('//tr'), 1):
        ancestor = row.xpath('ancestor::table[1]')
        rows.append(dict(occurrence=number, html_line=row.sourceline,
                         table=table_positions[ancestor[0]] if ancestor else None,
                         attributes=dict(row.attrib), text=_text(row),
                         cells=[dict(tag=cell.tag, attributes=dict(cell.attrib), text=_text(cell))
                                for cell in row.xpath('./th|./td')]))
    forms = []
    for number, form in enumerate(tree.xpath('//form'), 1):
        forms.append(dict(occurrence=number, html_line=form.sourceline, attributes=dict(form.attrib),
                          action=form.get('action'), method=form.get('method'),
                          controls=[dict(tag=node.tag, html_line=node.sourceline, attributes=dict(node.attrib),
                                         text=_text(node), options=[dict(attributes=dict(option.attrib), text=_text(option))
                                                                   for option in node.xpath('.//option')])
                                    for node in form.xpath('.//input|.//select|.//textarea|.//button')]))
    interactions = [dict(tag=node.tag, html_line=node.sourceline, attribute=key, value=value)
                    for node in tree.iter() if isinstance(node.tag, str)
                    for key, value in node.attrib.items() if key.lower().startswith('on')]
    scripts = [dict(html_line=node.sourceline, attributes=dict(node.attrib), text=_text(node))
               for node in tree.xpath('//script')]
    full = dict(body_sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body),
                html_text_policy='UTF8/BOM decoded; HTML entities decoded; original response bytes remain archived',
                page_text=_text(tree), rows=rows,
                tables=[dict(occurrence=table_positions[table], html_line=table.sourceline,
                             attributes=dict(table.attrib)) for table in tables],
                forms=forms, pointers=extract_pointers(body), scripted_attributes=interactions,
                scripts=scripts)
    summary = dict(status='saved_meeting_book_lookup_html_inventoried_content_unqualified',
        body_sha256=full['body_sha256'], size_bytes=len(body),
        html_table_count=len(tables), html_row_count=len(rows), form_count=len(forms),
        pointer_count=len(full['pointers']), scripted_attribute_count=len(interactions),
        returned_rows=[dict(occurrence=row['occurrence'], table=row['table'],
                            cells=[cell['text'] for cell in row['cells']]) for row in rows],
        forms=forms, scripted_attributes=interactions,
        scripts=[dict(html_line=script['html_line'], attributes=script['attributes'],
                      text_sha256=hashlib.sha256(script['text'].encode()).hexdigest()) for script in scripts],
        pointers=[{key: value for key, value in pointer.items() if key != 'raw_start_tag'}
                  for pointer in full['pointers']],
        all_returned_html_rows_preserved=True, all_returned_form_controls_preserved=True,
        all_href_src_occurrences_preserved=True, book_type_filter_applied=False,
        query_issuer='6674', query_roc_year='115', returned_company_year_identity_verified=False,
        specific_document_selected=False, linked_documents_acquired=False,
        document_population_complete=False, no_documents_proven=False,
        javascript_executed=False, pointers_followed=False,
        transaction_disposition=None, current_transaction_status_verified=False,
        contractual_cash_claim_verified=False, source_gate_passed=False,
        cash_claim_source_gate_passed=False, historical_pit_verified=False,
        profit_edge_proven=False, valid_prospective_signal_date=None,
        market_prices_or_returns_read=False, orders_authorized=False)
    return full, summary


def require_successful_query(records):
    require(len(records) == 1 and type(records[0].get('http_status')) is int
            and records[0]['http_status'] == 200 and type(records[0].get('exit_code')) is int
            and records[0]['exit_code'] == 0, 'Saved query requires one HTTP200/exit0 response')


def run():
    module = merger_documents_sources._source_module()
    requests_path, cfg, _, freeze = merger_documents_sources.plan('query')
    policy = json.loads(module.POLICY.read_text())
    package, transfer = module.archived('query', requests_path, freeze)
    with zipfile.ZipFile(package['retrieved']) as archive:
        results = json.loads(archive.read('raw/results.json'))
        require(results['config_sha256'] == sha256(requests_path), 'Saved query configuration differs')
        records = verified_records(cfg, results, lambda name: archive.read('raw/' + name))
        require_successful_query(records)
        filename = records[0]['request']['filename']
        full, summary = inventory_html(archive.read('raw/' + filename))
    summary.update(protocol_sha256=sha256(module.POLICY), request_config_sha256=sha256(requests_path),
                   request=records[0]['request'], source_form=policy['source_form'],
                   archive=dict(sha256=package['sha256'], manifest_files=package['manifest_files'], backup=transfer))
    atomic_json(ROOT / 'query_full.json', full)
    atomic_json(OUT / 'query_replay.json', summary)


if __name__ == '__main__':
    run()
