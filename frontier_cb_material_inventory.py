"""Audit every saved response and the limited current-month overlap."""
import json,hashlib,zipfile
from pathlib import Path
from cash_merger_document_lookup import inventory_html
from source_checkpoint import readback
from tender_preflight import verified_records
from research_runtime import atomic_json,sha256
from frontier_cb_material_detail import listing
from frontier_cb_put_notice_replay import audit as notice_audit
OUT=Path('deliverables/frontier_cb_material_rows_20261023');ROOT=Path('inputs/frontier_cb_material_rows_20261023')

def inventory():
    fulls=[];docs=[];requests=0
    for batch in ['rows','corporate','details','month']:
        package,_=readback(OUT,batch)
        with zipfile.ZipFile(package['retrieved']) as z:
            cfg=json.loads(z.read('requests.json'));results=json.loads(z.read('raw/results.json'));assert results['config_sha256']==hashlib.sha256(z.read('requests.json')).hexdigest()
            records=verified_records(cfg,results,lambda n:z.read('raw/'+n));requests+=len(records)
            for r in records:
                assert r['http_status']==200 and r['exit_code']==0
                name=r['request']['filename'];b=z.read('raw/'+name);full,_=inventory_html(b)
                item=dict(batch=batch,filename=name,body_sha256=full['body_sha256'],request=r['request'],request_started_at=r['request_started_at'],observed_at=r['observed_at'],source_gate_passed=False)
                if batch=='rows':
                    assert 'MaterialEventsDisclosureforInternationalBondAndForeignBond' in ''.join(full['page_text'].split()) and '無資料可供查詢Nodata' in ''.join(full['page_text'].split())
                    item.update(scope='InternationalBondAndForeignBond',explicit_no_data=True,absence_of_domestic_put_notices_proven=False)
                elif batch=='corporate':
                    small,_=listing(b,name[:5]);item.update(corporate_summary=small)
                elif batch=='month':
                    assert '資料庫中查無需求資料' in full['page_text']
                    item.update(scope='2026-10-01through2026-10-23',explicit_no_data=True,returned_company_rows=[],absence_of_public_notices_proven=False)
                fulls.append(dict(filename=name,inventory=full));docs.append(item)
    assert requests==11
    corporate=[d['corporate_summary'] for d in docs if d['batch']=='corporate'];assert [d['returned_company_row_count'] for d in corporate]==[38,20,18]
    oct_annual=[dict(bond_code=d['bond_code'],october_rows=[row for row in d['returned_company_rows'] if row['cells'][2].startswith('115/10/')]) for d in corporate]
    assert all(not d['october_rows'] for d in oct_annual)
    atomic_json(ROOT/'all_responses_full.json',fulls)
    audit=notice_audit()
    result=dict(source_requests=11,batches=4,documents=docs,company_rows=76,exact_code_cash_right_details=2,original_control_gap=['68741'],current_month_overlap=oct_annual,
        month_response_matches_saved_annual_subset=True,declared_total_count_available=False,complete_current_notice_population_verified=False,
        full_inventory_sha256=sha256(ROOT/'all_responses_full.json'),put_notice_audit_sha256=sha256(OUT/'put_notice_audit.json'),
        source_gate_passed=False,cash_claim_source_gate_passed=False,historical_pit_verified=False,profit_edge_proven=False,valid_prospective_signal_date=None,orders_authorized=False)
    atomic_json(OUT/'inventory.json',result);return result

if __name__=='__main__':
    r=inventory();print(json.dumps(dict(requests=r['source_requests'],company_rows=76,put_notices=2,complete_population=False,source_gate_passed=False)))
