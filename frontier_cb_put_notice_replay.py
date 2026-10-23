"""Bind human-reviewed put-notice facts to exact saved HTML and reported dates."""
import hashlib,json,zipfile,re
from pathlib import Path
from lxml import html
from research_runtime import atomic_json,sha256
from source_checkpoint import readback
from tender_preflight import verified_records
from cash_merger_document_lookup import inventory_html
OUT=Path('deliverables/frontier_cb_material_rows_20261023');ROOT=Path('inputs/frontier_cb_material_rows_20261023')

def require(v,m):
    if not v:raise ValueError(m)

def compact(s):return ''.join(s.split())

def verify_annotation(annotation,fulls,records,archive_sha):
    require(annotation['archive_sha256']==archive_sha,'Annotation archive drift')
    require(annotation['original_controls']==['99587','68351','68741'] and annotation['unresolved_controls']==['68741'],'Original control/missing case drift')
    require(annotation.get('source_gate_passed') is False and annotation.get('valid_prospective_signal_date') is None
            and annotation.get('orders_authorized') is False and annotation.get('profit_edge_proven') is False,'Annotation cannot promote gates')
    cases=annotation['cases'];require(len(cases)==2 and {c['bond_code'] for c in cases}=={'99587','68351'},'Exactly two available notices required')
    byname={f['filename']:f for f in fulls};byrecord={r['request']['filename']:r for r in records};anchors=0
    for case in cases:
        name=case['filename'];require(name in byname and name in byrecord,'Unknown original notice')
        full=byname[name]['inventory'];record=byrecord[name]
        require(case['body_sha256']==full['body_sha256']==record['sha256'] and case['observed_at_utc']==record['observed_at'],'Notice source/hash/observation drift')
        require(case['issuer']==case['bond_code'][:-1] and compact(case['bond_code']) in compact(full['page_text']),'Notice control identity absent')
        for fact in case['facts']:
            require(fact['exact_anchors'] and all(compact(q) and compact(q) in compact(full['page_text']) for q in fact['exact_anchors']),'Notice exact anchor absent')
            anchors+=len(fact['exact_anchors'])
        require(case['reported_payment_date_guaranteed'] is False and case['net_amount_verified'] is False
                and case['current_eligibility_verified'] is False and case['historical_first_availability_verified'] is False,'Tentative/source dates cannot become eligibility/net guarantee')
    return dict(status='source_and_human_references_verified',available_notices=2,original_controls=3,unresolved_controls=['68741'],text_anchors_verified=anchors,
        semantic_interpretation_automatically_verified=False,current_notice_coverage_complete_verified=False,source_gate_passed=False,cash_claim_source_gate_passed=False,
        historical_pit_verified=False,profit_edge_proven=False,valid_prospective_signal_date=None,orders_authorized=False)

def audit():
    p,_=readback(OUT,'details');fulls=[]
    with zipfile.ZipFile(p['retrieved']) as z:
        cfg=json.loads(z.read('requests.json'));res=json.loads(z.read('raw/results.json'));require(res['config_sha256']==hashlib.sha256(z.read('requests.json')).hexdigest(),'Detail config SHA differs')
        records=verified_records(cfg,res,lambda name:z.read('raw/'+name))
        for r in records:
            require(r['http_status']==200 and r['exit_code']==0,'Detail transport failure')
            name=r['request']['filename'];full,_=inventory_html(z.read('raw/'+name));fulls.append(dict(filename=name,inventory=full))
    annotation=json.loads((OUT/'put_notice_annotation.json').read_bytes());result=verify_annotation(annotation,fulls,records,p['sha256'])
    atomic_json(ROOT/'put_notices_full.json',fulls)
    result.update(annotation_sha256=sha256(OUT/'put_notice_annotation.json'),full_inventory_sha256=sha256(ROOT/'put_notices_full.json'),source_archive_sha256=p['sha256'])
    atomic_json(OUT/'put_notice_audit.json',result);return result

if __name__=='__main__':print(json.dumps(audit(),ensure_ascii=False))
