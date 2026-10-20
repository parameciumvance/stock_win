"""Rebuild the full captured census from verified source archives, without prices."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

from buyback_coverage import archived, policy, OUT, ROOT, OLD
from buyback_document_identity import parse_identity
from buyback_case_replay import link_cases
from research_runtime import atomic_json,sha256
from source_checkpoint import readback


def choose_response(record, files, recovery_record, recovery_files, repair):
    name=record['request']['filename']
    if record.get('http_status')==200 and record.get('exit_code')==0:
        return files[name],False
    if (name!=repair['failed_filename'] or record['request']['url']!=repair['url']
            or record.get('http_status')!=502 or record.get('sha256')!=repair['failed_body_sha256']):
        raise ValueError('Undeclared failed response; cannot use recovery')
    if (recovery_record.get('http_status')!=200 or recovery_record.get('exit_code')!=0
            or recovery_record['request']['url']!=repair['url']
            or recovery_record['request']['filename']!=repair['replacement_filename']):
        raise ValueError('Recovery transport/request does not match the declared failure')
    return recovery_files[repair['replacement_filename']],True


def verify_all():
    p=policy();packages=[];failures=[]
    for batch in ['index','originals01','originals02','originals03','originals04','recovery']:
        pkg,transfer,records,_=archived(batch)
        packages.append(dict(batch=batch,archive_sha256=pkg['sha256'],archive_bytes=Path(pkg['archive']).stat().st_size,manifest_files=pkg['manifest_files'],sha_crc_manifest_verified=True,backup=transfer))
        for r in records:
            if r.get('http_status')!=200 or r.get('exit_code')!=0:
                failures.append(dict(batch=batch,filename=r['request']['filename'],http_status=r.get('http_status'),exit_code=r.get('exit_code'),body_sha256=r.get('sha256')))
    repair=json.loads(Path('configs/buyback_coverage_recovery_protocol_20261020.json').read_text())
    if len(failures)!=1 or failures[0]['batch']!=repair['failed_batch'] or failures[0]['filename']!=repair['failed_filename'] or failures[0]['body_sha256']!=repair['failed_body_sha256']:
        raise ValueError('Captured transport failures differ from the separately frozen recovery')
    atomic_json(OUT/'backup_receipt.json',dict(packages=packages,manifest_entries=sum(r['manifest_files'] for r in packages),source_requests_initial=132,separate_recovery_requests=1,failures=failures,reused_originals=7,new_originals=115,old_large_price_packages_retransmitted=0,storage='Windows backup and WSL working copy on same computer; not off-site disaster recovery'))


def replay():
    p=policy()
    partition=json.loads((OUT/'partition_audit.json').read_text())
    if not partition['current_snapshot_partition_agreement']:
        raise ValueError('Current-year partition agreement required')
    baseline=json.loads((OLD/'announcement_index.json').read_text())
    byurl={r['url']:r for r in baseline['rows']}
    selected=json.loads((OUT/'selection.json').read_text())['requests']
    records=[];recovered=[]
    old_selection=json.loads((OLD/'originals_selection.json').read_text())['selected']
    oldcfg=json.loads(Path('configs/buyback_originals_sources_20261020.json').read_text())
    pkg,_=readback(OLD,'originals')
    with zipfile.ZipFile(pkg['retrieved']) as z:
        for row,request in zip(old_selection,oldcfg['requests'],strict=True):
            doc=parse_identity(z.read('raw/'+request['filename']),row)
            doc.update(event_id=byurl[row['HYPERLINK']]['event_id'],url=row['HYPERLINK'],source='original_pilot')
            records.append(doc)
    _,_,repair_records,repair_files=archived('recovery')
    if len(repair_records)!=1:
        raise ValueError('Recovery budget not exactly one source')
    repair=json.loads(Path('configs/buyback_coverage_recovery_protocol_20261020.json').read_text())
    for batch in ['originals01','originals02','originals03','originals04']:
        _,_,rows,files=archived(batch)
        selections={r['filename']:r for r in selected if r['batch']==batch}
        for item in rows:
            name=item['request']['filename'];selection=selections[name]
            if item['request']['url']!=selection['original_fields']['HYPERLINK']:
                raise ValueError('Selected original URL drift')
            body,used_recovery=choose_response(item,files,repair_records[0],repair_files,repair)
            doc=parse_identity(body,selection['original_fields'])
            doc.update(event_id=selection['event_id'],url=selection['original_fields']['HYPERLINK'],source='recovery' if used_recovery else batch)
            records.append(doc)
            if used_recovery:recovered.append(selection['event_id'])
    if len(records)!=122 or {r['event_id'] for r in records}!={r['event_id'] for r in baseline['rows']} or len(recovered)!=1:
        raise ValueError('Full captured original census must cover each of122identities exactly once')
    linked=link_cases(json.loads((OLD/'annual_snapshot.json').read_text()),records)
    atomic_json(ROOT/'documents_full.json',records)
    atomic_json(ROOT/'linked_cases_full.json',linked)
    summary=[]
    for r in records:
        fields=r['numbered_fields']
        summary.append({k:r[k] for k in ['event_id','issuer','reported_datetime','sequence','subject','document_form','source','url','description_sha256','required_schema_known']}|dict(numbered_field_count=len(fields),numbered_field_sha256={k:hashlib.sha256(v.encode()).hexdigest() for k,v in fields.items()}))
    forms=dict(Counter(r['document_form'] for r in records))
    atomic_json(OUT/'documents_summary.json',dict(documents=summary,form_counts=forms,total=122,full_local_document_ledger_sha256=sha256(ROOT/'documents_full.json'),historical_pit_verified=False))
    atomic_json(OUT/'case_replay.json',linked)
    qualified=(not linked['unresolved_case_ids'] and not linked['unmatched_board_documents'] and all(r['required_schema_known'] for r in records))
    atomic_json(OUT/'decision.json',dict(status='current_archive_coverage_and_case_replay_passed_strict_pit_unproven' if qualified else 'current_census_has_unresolved_schema_or_case_links',year_month_partition_agreement=True,documents_verified=122,annual_cases_linked=linked['cases_with_retained_board_records'],unresolved_case_ids=linked['unresolved_case_ids'],known_form_counts=forms,current_vintage_source_gate_passed=qualified,historical_pit_verified=False,first_publication_capture_proven=False,missing_total_is_not_a_missing_data_finding=True,separate_failed502_preserved_and_recovered=recovered,boundary_window='2023Q4 27indexrows;2025Q1 90indexrows; no full post2024 completion-chain claim',decision='Adequate for a separately frozen explicitly conditional descriptive resource diagnostic after independent audit. Not contemporaneous prospective evidence, an actual account or alpha proof.',next_stage='Fixed47case/20session quote diagnostic frozen before outcomes; continue after source checkpoint and independent audit',manual_daily_validation=False,trade_authorized=False,profit_edge_proven=False,valid_prospective_signal_date=None,user_action_required=None))
    print(json.dumps(dict(documents=len(records),forms=forms,cases=len(linked['cases']),unresolved=linked['unresolved_case_ids'],current_source_gate=qualified)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['verify_all','replay']);globals()[p.parse_args().stage]()
