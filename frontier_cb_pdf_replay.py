"""Byte/page-bound replay of three archived CB issuance-rule PDFs.

The frozen PDF extractor supplies text and identity candidates only. This module
does not calculate returns, settlement eligibility, or a cash payment deadline.
"""
import argparse
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
import zipfile

from pypdf import PdfReader

from cash_merger_pdf_replay import replay_pdf
import frontier_cb_documents_sources as sources
from research_runtime import atomic_json, sha256
from tender_preflight import verified_records

ROOT = Path('inputs/frontier_cb_documents_20261023')
OUT = Path('deliverables/frontier_cb_documents_20261023')
ARCHIVE_SHA256 = '8566db22cad7ffa2619f27b71152b21784c27e1334be861d148374c927b3a266'
BODY_SHA256 = {
    '99587_terms.pdf':'56885bffa85b9e05f5cff1f5dad34e605b80d60cd3f3071d7b07e65434c129d1',
    '68351_terms.pdf':'0ecc755545fb3d68922a77f051e3b9187c4805e2936953532e6ae79c9dd6f23c',
    '68741_terms.pdf':'58e884ad34e5b91ea3f4c30e35e9756deac4674814f30134ea9e429477ddd9b3',
}
PAGE_COUNTS = {'99587_terms.pdf':7,'68351_terms.pdf':6,'68741_terms.pdf':7}


def require(value,message):
    if not value:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def compact(text):
    return re.sub(r'\s+','',text)


def replay_terms(controls,bodies,records,expected_shas,expected_pages=None):
    """Keep all three controls, and never turn missing text into an identity pass."""
    require(isinstance(controls,list) and len(controls) == 3,'Exactly all three CB terms controls required')
    names = [row['filename'] for row in controls]
    require(len(set(names)) == 3 and len({row['bond_code'] for row in controls}) == 3,
            'Duplicate CB terms control')
    require(set(bodies) == set(expected_shas) == set(names)
            and (expected_pages is None or set(expected_pages) == set(names)), 'CB PDF byte/hash/page population differs')
    require(isinstance(records,list) and len(records) == 3,'All three PDF transport records required')
    by_name = {record['request']['filename']:record for record in records}
    require(len(by_name) == 3 and set(by_name) == set(names),'PDF transport identity population differs')
    fulls,summaries = [],[]
    for control in controls:
        name = control['filename']
        record,body = by_name[name],bodies[name]
        require(type(record.get('http_status')) is int and record['http_status'] == 200
                and type(record.get('exit_code')) is int and record['exit_code'] == 0,
                'PDF transport failed; this is not an empty/no-contract result')
        require(record['request'] == dict(filename=name,url=control['url'],method='GET')
                and record['curl']['url_effective'] == control['url'], 'Saved PDF request/effective URL differs')
        require(record['sha256'] == expected_shas[name] == digest(body),'Saved PDF body SHA differs')
        full,summary = replay_pdf(body,expected_shas[name],control['identity_terms'],
                                  expected_pages[name] if expected_pages else None)
        image_refs = []
        reader = PdfReader(BytesIO(body),strict=True)
        for page_number,page in enumerate(reader.pages,1):
            for image_number,item in enumerate(page.images,1):
                image_refs.append(dict(physical_page=page_number,image_number=image_number,
                    name=item.name,data_sha256=digest(item.data),size_bytes=len(item.data)))
        summary.update(filename=name,bond_code=control['bond_code'],url=control['url'],image_refs=image_refs,
                       current_contract_version_verified=False,holder_put_contract_verified=False,
                       cash_claim_source_gate_passed=False,historical_pit_verified=False,
                       broker_or_settlement_eligibility_verified=False,
                       actual_notice_or_payment_verified=False)
        times = {key:record[key] for key in ('request_started_at','observed_at') if key in record}
        if times:
            require(set(times) == {'request_started_at','observed_at'},'Incomplete PDF source timestamps')
            started,observed = map(datetime.fromisoformat,(times['request_started_at'],times['observed_at']))
            require(started.tzinfo is not None and observed.tzinfo is not None and started <= observed,
                    'Invalid PDF source timestamps')
            times['observed_at_taipei'] = observed.astimezone(ZoneInfo('Asia/Taipei')).isoformat()
        summary['actual_source_timestamps'] = times
        full.update(filename=name,bond_code=control['bond_code'],body_sha256=digest(body))
        fulls.append(full)
        summaries.append(summary)
    return fulls,summaries


def verify_annotation(annotation,fulls,summaries):
    """Verify every cited page/anchor/image against source, not its interpretation."""
    require(isinstance(annotation,dict) and annotation.get('source_archive_sha256') == ARCHIVE_SHA256,
            'Annotation source archive differs')
    require(all(annotation.get(key) is False for key in ('source_gate_passed','cash_claim_source_gate_passed',
            'historical_pit_verified','profit_edge_proven','orders_authorized')),
            'Annotation cannot promote unverified research/trading gates')
    docs = annotation.get('documents')
    by_name = {row['filename']:row for row in summaries}
    full_by_name = {row['filename']:row for row in fulls}
    require(isinstance(docs,list) and len(docs) == 3
            and len({row['filename'] for row in docs}) == 3
            and {row['filename'] for row in docs} == set(by_name),'Annotation must retain all three PDFs')
    anchor_count,image_count = 0,0
    for document in docs:
        name = document['filename']
        summary,full = by_name[name],full_by_name[name]
        require(document['body_sha256'] == summary['body_sha256']
                and document['bond_code'] == summary['bond_code']
                and document['physical_page_count'] == summary['extracted_page_count'], 'Annotation PDF identity/count differs')
        require(document.get('source_observed_at') == summary['actual_source_timestamps'],
                'Annotation source observation timestamps differ')
        require(document['all_physical_pages_read'] == list(range(1,summary['extracted_page_count']+1)),
                'Annotation whole-document review coverage differs')
        require(isinstance(document.get('findings'),list) and document['findings'],'No page-bound terms findings')
        for finding in document['findings']:
            refs = finding.get('references')
            require(isinstance(refs,list) and refs,'Every semantic finding requires source page references')
            for ref in refs:
                page_number = ref['physical_page']
                require(type(page_number) is int and 1 <= page_number <= len(full['pages']),'Annotation page out of range')
                page = summary['pages'][page_number-1]
                require(ref['page_text_sha256'] == page['text_sha256'],'Annotation page text SHA differs')
                anchors = ref.get('exact_anchors')
                require(isinstance(anchors,list) and anchors and all(isinstance(value,str) and compact(value)
                        for value in anchors),'Every text reference requires meaningful exact anchors')
                text = full['pages'][page_number-1]['text']
                require(all(compact(value) in compact(text) for value in anchors),'Annotation exact anchor absent/wrong page')
                anchor_count += len(anchors)
        for visual in document.get('visual_review',[]):
            ref = {key:visual[key] for key in ('physical_page','image_number','name','data_sha256','size_bytes')}
            require(ref in summary['image_refs'] and visual.get('actually_viewed') is True
                    and isinstance(visual.get('observation'),str) and visual['observation'].strip(),
                    'Annotation visual image hash/reference differs')
            image_count += 1
        require(document.get('source_gate_passed') is False and document.get('current_contract_version_verified') is False,
                'Annotation cannot promote unverified current cash-claim gate')
    return dict(status='all_pdf_annotation_page_anchors_and_image_references_verified',
                documents=3,text_anchors_verified=anchor_count,image_references_verified=image_count,
                semantic_interpretation_automatically_approved=False,source_gate_passed=False,
                cash_claim_source_gate_passed=False,historical_pit_verified=False)


def audit():
    module = sources.module()
    requests_path,cfg,_,freeze = sources.plan('terms')
    package,transfer = module.archived('terms',requests_path,freeze)
    require(package['sha256'] == ARCHIVE_SHA256,'Unexpected saved CB terms archive')
    selection_ref = sources.strict_json(Path(freeze).read_bytes())['terms_selection']
    require(sha256(selection_ref['path']) == selection_ref['sha256'],'Frozen terms selection differs')
    selection = json.loads(Path(selection_ref['path']).read_bytes())
    names_by_bond = {request['filename'].split('_',1)[0]:request['filename'] for request in cfg['requests']}
    controls = []
    for row in selection['controls']:
        pointer = row['identity_and_pointer']
        require(row['bond_code'] in names_by_bond,'Selected terms bond lacks frozen request')
        series = '國內第七次' if row['bond_code'] == '99587' else '國內第一次'
        controls.append(dict(filename=names_by_bond[row['bond_code']],bond_code=row['bond_code'],url=pointer['url'],
                             identity_terms=dict(issuer_name=[pointer['issuer_name']],series=[series])))
    with zipfile.ZipFile(package['retrieved']) as archive:
        require(digest(archive.read('protocol.json')) == sha256(sources.POLICY)
                and digest(archive.read('requests.json')) == sha256(requests_path),'Archived PDF policy/config differs')
        results = json.loads(archive.read('raw/results.json'))
        require(results['config_sha256'] == sha256(requests_path),'Archived PDF config SHA differs')
        records = verified_records(cfg,results,lambda name:archive.read('raw/'+name))
        bodies = {control['filename']:archive.read('raw/'+control['filename']) for control in controls}
        fulls,summaries = replay_terms(controls,bodies,records,BODY_SHA256,PAGE_COUNTS)
    full_path = ROOT/'pdf_text_full.json'
    atomic_json(full_path,dict(documents=fulls))
    result = dict(status='all_three_cb_rule_PDFs_page_extracted_identity_candidates_only',
        documents=summaries,document_count=3,all_selected_controls_retained=True,
        physical_pages=sum(row['extracted_page_count'] for row in summaries),
        archive=dict(sha256=package['sha256'],manifest_files=package['manifest_files'],backup=transfer),
        protocol_sha256=sha256(sources.POLICY),request_config_sha256=sha256(requests_path),
        terms_selection_sha256=selection_ref['sha256'],source_issuance_archive_sha256=selection['source_issuance_archive_sha256'],
        full_text_saved_only_in_ignored_inputs=True,full_inventory=dict(path=str(full_path),sha256=sha256(full_path)),
        text_identity_is_legal_or_issuer_verification=False,source_gate_passed=False,
        cash_claim_source_gate_passed=False,historical_pit_verified=False,profit_edge_proven=False,
        valid_prospective_signal_date=None,market_prices_or_returns_read=False,orders_authorized=False,
        boundaries=['Identity candidates can be absent on scanned pages; blank extraction never proves an absent issuer or unsigned document.',
            'Physical page and full text hashes are mechanical evidence, not current notice/payment or broker/T+2 settlement eligibility.',
            'Source filenames and file dates do not establish contract amendment chronology or historical first publication.',
            'The parent HTML monyr_reg202609 on-time-repayment field is a monthly reported field, not proof of payment today.'])
    atomic_json(OUT/'pdf_replay.json',result)
    return fulls,result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-annotation',type=Path)
    args = parser.parse_args()
    fulls,result = audit()
    if args.audit_annotation:
        annotation = json.loads(args.audit_annotation.read_bytes())
        verified = verify_annotation(annotation,fulls,result['documents'])
        verified.update(annotation_path=str(args.audit_annotation),annotation_sha256=sha256(args.audit_annotation),
                        pdf_replay_sha256=sha256(OUT/'pdf_replay.json'))
        atomic_json(OUT/'terms_annotation_audit.json',verified)
    print(json.dumps(dict(status=result['status'],documents=3,physical_pages=result['physical_pages'],source_gate_passed=False)))
