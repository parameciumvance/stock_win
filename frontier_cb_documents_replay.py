"""Replay three saved CB issuance interfaces without following any pointer.

Identity and every HTML row/control are byte-bound evidence. A filename ending
in PDF is not proof that the document was obtained or that a cash claim passed.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
import zipfile

from lxml import html

from cash_merger_document_lookup import decode_html, inventory_html
import frontier_cb_documents_sources as sources
from research_runtime import atomic_json, sha256
from tender_preflight import verified_records


ROOT = Path('inputs/frontier_cb_documents_20261023')
OUT = Path('deliverables/frontier_cb_documents_20261023')
ISSUANCE_ARCHIVE_SHA256 = 'b44941466b27c510e6f6295af3e8c3cab59e38666cc7caea66ec7999d94a8979'
DOCUMENT_LABELS = ('發行辦法之內容','受託契約內容')


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def compact(value):
    return re.sub(r'\s+','',value)


def _text(node):
    return ''.join(node.itertext())


def inspect_issuance(body: bytes, control: dict, effective_url: str, headers=None):
    """Verify the exact selected identity, retain full HTML, list actual links."""
    require(isinstance(control,dict) and all(isinstance(control.get(key),str) and control[key]
            for key in ('bond_code','issuer','issuer_name','bond_name','listed_date','issuance_url')),
            'Missing selected issuance identity')
    require(effective_url == control['issuance_url'],'Effective issuance URL differs from selected original URL')
    pairs = sources._pointer(effective_url,control['issuer'])
    query = dict(pairs)
    require(query['bond_id'] == control['bond_code'],'URL bond_id differs from selected bond')
    require(control['bond_name'].startswith(control['issuer_name']), 'Selected bond/issuer names disagree')
    full,_ = inventory_html(body,'utf-8',headers)
    text,_,_ = decode_html(body,'utf-8',headers)
    tree = html.document_fromstring(text)
    require(not tree.xpath('//base[@href]'),'Base href needs separate resolution review')
    leaves = tree.xpath('//td[not(.//table)]|//th[not(.//table)]')
    evidence = {}
    for label in ('債券代碼','債券中文名稱','債券期別','掛牌日期'):
        found = [node for node in leaves if re.match('^'+label+'[：:]',compact(_text(node)))]
        require(len(found) == 1,'Missing/ambiguous issuance identity label: '+label)
        node = found[0]
        literal = _text(node)
        value = re.split('[：:]',compact(literal),maxsplit=1)[1]
        evidence[label] = dict(value=value,original_text=literal,html_line=node.sourceline,
                               text_sha256=digest(literal.encode('utf-8')))
    require(evidence['債券代碼']['value'] == control['bond_code'],'Saved issuance bond code mismatch')
    require(evidence['債券中文名稱']['value'] == compact(control['bond_name']), 'Saved issuance bond name mismatch')
    series_match = re.fullmatch(r'第([0-9]+)期.*',evidence['債券期別']['value'])
    require(series_match is not None and series_match[1] == query['bond_yrn'],'Saved issuance series mismatch')
    require(evidence['掛牌日期']['value'] == control['listed_date'],'Saved issuance listing date mismatch')
    document_pointers = []
    for label in DOCUMENT_LABELS:
        cells = [node for node in leaves if re.match('^'+label+'[：:]',compact(_text(node)))]
        require(len(cells) <= 1,'Ambiguous document label: '+label)
        for cell in cells:
            for anchor in cell.xpath('.//a[@href]'):
                value = anchor.get('href')
                candidates = [pointer for pointer in full['pointers'] if pointer['tag'] == 'a'
                              and pointer['attribute'] == 'href' and pointer['value'] == value
                              and pointer['html_line'] == anchor.sourceline]
                require(len(candidates) == 1,'Ambiguous actual document anchor occurrence')
                pointer = candidates[0]
                resolved = urljoin(effective_url,value) if value else None
                if resolved:
                    parsed = urlsplit(resolved)
                    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
                        resolved = None
                document_pointers.append(dict(label=label,value=value,
                    source_literal=pointer['source_literal'],resolved_url=resolved,
                    html_line=anchor.sourceline,anchor_text=_text(anchor),
                    followup_authorized=False,document_content_verified=False,PDF_verified=False))
    source_text = []
    labels = ('債券賣回權條件','賣回權收益率','債券買回權條件','買回權收益率',
              '下一次賣回權日期','下一次賣回權價格','備註')
    for node in leaves:
        literal = _text(node)
        if any(re.match('^'+label+'[：:]',compact(literal)) for label in labels):
            source_text.append(dict(html_line=node.sourceline,original_text=literal,
                                    text_sha256=digest(literal.encode('utf-8'))))
    identity = dict(bond_code=control['bond_code'],issuer=control['issuer'],
                    issuer_name=control['issuer_name'],bond_name=control['bond_name'],
                    series=series_match[1],listed_date=control['listed_date'],identity_verified=True,
                    evidence=evidence)
    full.update(identity=identity,issuance_url=effective_url,decoded_query=query,
                document_pointers=document_pointers,relevant_source_text=source_text)
    summary = dict(status='saved_cb_issuance_identity_and_actual_document_pointers_replayed',
        body_sha256=full['body_sha256'],size_bytes=len(body),identity=identity,
        issuance_url=effective_url,decoded_query=query,source_encoding=full['source_encoding'],
        charset_declarations=full['charset_declarations'],html_table_count=len(full['tables']),
        html_row_count=len(full['rows']),form_count=len(full['forms']),pointer_count=len(full['pointers']),
        scripted_attribute_count=len(full['scripted_attributes']),document_pointers=document_pointers,
        relevant_source_text=source_text,
        all_returned_html_rows_preserved=True,all_returned_form_controls_preserved=True,
        all_href_src_occurrences_preserved=True,javascript_executed=False,pointers_followed=False,
        document_population_complete=False,linked_documents_acquired=False,
        holder_put_application_window_verified=False,actual_payment_date_verified=False,
        current_contract_version_verified=False,holder_put_contract_verified=False,
        cash_claim_source_gate_passed=False,source_gate_passed=False,historical_pit_verified=False,
        market_prices_or_returns_read=False,orders_authorized=False)
    return full,summary


def replay_issuances(controls, bodies, records, headers=None):
    require(isinstance(controls,list) and len(controls) == 3,'Retain exactly all three selected controls')
    names = [control.get('request_filename') for control in controls]
    require(all(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]+',name) for name in names)
            and len(set(names)) == 3 and len({control['bond_code'] for control in controls}) == 3,
            'Duplicate/missing selected issuance identity or filename')
    require(isinstance(bodies,dict) and set(bodies) == set(names)
            and isinstance(records,list) and len(records) == 3,'Selected issuance/body population mismatch')
    by_name = {record['request']['filename']:record for record in records}
    require(set(by_name) == set(names) and len(by_name) == 3,'Saved issuance request population mismatch')
    require(headers is None or isinstance(headers,dict) and set(headers) == set(names),'Saved issuance header population mismatch')
    fulls,summaries = [],[]
    for control in controls:
        name = control['request_filename']
        record,body = by_name[name],bodies[name]
        require(type(record.get('http_status')) is int and record['http_status'] == 200
                and type(record.get('exit_code')) is int and record['exit_code'] == 0,
                'Issuance transport failure is not an empty document population')
        require(record['request'] == dict(filename=name,url=control['issuance_url'],method='GET')
                and record['sha256'] == digest(body), 'Issuance request/body differs from selected source')
        full,summary = inspect_issuance(body,control,record['curl']['url_effective'],
                                       headers[name] if headers is not None else None)
        full['filename'] = summary['filename'] = name
        times = {key:record[key] for key in ('request_started_at','observed_at') if key in record}
        if times:
            require(set(times) == {'request_started_at','observed_at'},'Incomplete issuance timestamps')
            started,observed = map(datetime.fromisoformat,(times['request_started_at'],times['observed_at']))
            require(started.tzinfo is not None and observed.tzinfo is not None and started <= observed,
                    'Invalid issuance source timestamps')
            times['observed_at_taipei'] = observed.astimezone(ZoneInfo('Asia/Taipei')).isoformat()
        full['source_timestamps'] = summary['source_timestamps'] = times
        fulls.append(full)
        summaries.append(summary)
    return fulls,summaries


def run():
    module = sources.module()
    requests_path,cfg,_,freeze = sources.plan('issuance')
    policy = json.loads(sources.POLICY.read_bytes())
    selection_ref = policy['selection']
    require(sha256(selection_ref['path']) == selection_ref['sha256'],'Frozen issuance selection drift')
    selection = json.loads(Path(selection_ref['path']).read_bytes())
    package,transfer = module.archived('issuance',requests_path,freeze)
    require(package['sha256'] == ISSUANCE_ARCHIVE_SHA256,'Unexpected issuance source archive')
    with zipfile.ZipFile(package['retrieved']) as archive:
        require(digest(archive.read('protocol.json')) == sha256(sources.POLICY)
                and digest(archive.read('requests.json')) == sha256(requests_path),'Archived policy/request differs')
        results = json.loads(archive.read('raw/results.json'))
        require(results['config_sha256'] == sha256(requests_path),'Saved issuance config SHA differs')
        records = verified_records(cfg,results,lambda name:archive.read('raw/'+name))
        names = [control['request_filename'] for control in selection['controls']]
        bodies = {name:archive.read('raw/'+name) for name in names}
        headers = {name:archive.read('raw/'+name+'.headers') for name in names}
        fulls,summaries = replay_issuances(selection['controls'],bodies,records,headers)
    full_path = ROOT/'issuance_full.json'
    atomic_json(full_path,dict(source_archive_sha256=package['sha256'],documents=fulls))
    summary = dict(status='all_three_frozen_cb_issuance_controls_replayed_documents_unqualified',
        document_count=3,all_selected_identities_verified=True,documents=summaries,
        selection_sha256=selection_ref['sha256'],protocol_sha256=sha256(sources.POLICY),
        request_config_sha256=sha256(requests_path),
        full_inventory=dict(path=str(full_path),sha256=sha256(full_path),all_original_rows_retained=True),
        archive=dict(sha256=package['sha256'],manifest_files=package['manifest_files'],backup=transfer),
        document_pointers_count=sum(len(item['document_pointers']) for item in summaries),
        all_three_cases_retained=True,source_gate_passed=False,cash_claim_source_gate_passed=False,
        historical_pit_verified=False,profit_edge_proven=False,valid_prospective_signal_date=None,
        market_prices_or_returns_read=False,orders_authorized=False,
        boundaries=['The page labels point to issuance rules and trust agreements; linked bytes are not obtained by this replay.',
            'The original monyr_reg202609 URL is retained. Oct23 observation does not establish current contract version or historical first availability.',
            'Nominal next-put dates and prices in the page are quoted source fields, not verified application windows, settlement eligibility or actual payment dates.',
            'All three cases remain; unavailable or conflicting documents must not cause clean-case selection.'])
    atomic_json(OUT/'issuance_replay.json',summary)
    return summary


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = run()
    print(json.dumps(dict(status=result['status'],documents=result['document_count'],
                         document_pointers=result['document_pointers_count'],source_gate_passed=False)))
