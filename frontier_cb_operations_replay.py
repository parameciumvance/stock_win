"""Source-bind calendar URL and operating rules without executing JavaScript."""
import hashlib,json,re,zipfile
from pathlib import Path
from urllib.parse import urlencode
from lxml import html
from cash_merger_document_lookup import inventory_html
from cash_merger_pdf_replay import replay_pdf
from source_checkpoint import readback
from tender_preflight import verified_records
from research_runtime import atomic_json,sha256
OUT=Path('deliverables/frontier_cb_operations_20261023');ROOT=Path('inputs/frontier_cb_operations_20261023')

def require(v,m):
    if not v:raise ValueError(m)

def calendar_request(body,report_script,main_script):
    t=html.fromstring(body.decode('utf-8',errors='strict'))
    fs=t.xpath('//form[@id="form"]');require(len(fs)==1 and fs[0].get('data-api')=='/holidaySchedule/holidaySchedule','Actual calendar action differs')
    require(fs[0].xpath('.//input[@name="date"]/@data-date')==['b:2021,e:1,f:Y'],'Actual calendar year field differs')
    require(not t.xpath('//base[@href]'),'Unexpected calendar base')
    report=report_script.decode('utf-8',errors='strict');main=main_script.decode('utf-8',errors='strict')
    for literal in ['$form.data("api")','${cfg.apiHost.rwd}/${cfg.lan}${a}','o.response="json"','$.getJSON(s,o,','String(i.val())+String(v.val()).padStart(2,"0")+String(m.val()).padStart(2,"0")']:
        require(literal in report,'Calendar form/query declaration differs')
    require('let cfg={env:"prod",lan:"zh"' in main and 'apiHost:{rwd:"/rwd",' in main,'Production calendar API prefix/language differs')
    return dict(request=dict(filename='twse_calendar_2026.json',url='https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?'+urlencode([('date','20260101'),('response','json')]),method='GET'),
        source_page_sha256=hashlib.sha256(body).hexdigest(),report_script_sha256=hashlib.sha256(report_script).hexdigest(),main_script_sha256=hashlib.sha256(main_script).hexdigest(),
        declared_api_prefix='/rwd',language='zh',literal_form_api='/holidaySchedule/holidaySchedule',chosen_year=2026,serialized_year_selection='20260101',
        production_hostname='www.twse.com.tw',test_local_accessibility_override_applied=False,javascript_executed=False,source_gate_passed=False)

def verify_annotation(annotation,fulls,summaries):
    expected={'kgi_service_closures.html','landbank_service_closures.html','tpex_bond_operations.html','tdcc_redemption_principles.pdf'}
    require(len(annotation['documents'])==4 and {d['filename'] for d in annotation['documents']}==expected,'Operation reference population differs')
    require(all(annotation.get(k) is False for k in ('source_gate_passed','current_broker_acceptance_verified','calendar_annual_data_verified','actual_net_amount_verified','orders_authorized'))
            and annotation.get('valid_prospective_signal_date') is None,'General operation references cannot promote gates')
    docs={d['filename']:d for d in fulls};metas={d['filename']:d for d in summaries};count=0
    for row in annotation['documents']:
        name=row['filename'];meta=metas[name];require(row['body_sha256']==meta['body_sha256'] and row['observed_at']==meta['observed_at'],'Operation reference hash/observation differs')
        doc=docs[name];text=doc['inventory']['page_text'] if 'inventory' in doc else '\n'.join(p['text'] for p in doc['pdf']['pages'])
        require(row['semantic_interpretation_automatically_verified'] is False and row['facts'],'Operation interpretation cannot be automatically approved')
        for fact in row['facts']:
            require(fact['anchors'] and all(''.join(q.split()) and ''.join(q.split()) in ''.join(text.split()) for q in fact['anchors']),'Operation reference exact anchor absent');count+=len(fact['anchors'])
    return dict(status='human_operation_reference_bindings_verified',text_anchors_verified=count,semantic_interpretation_automatically_verified=False,
                current_broker_acceptance_verified=False,calendar_annual_data_verified=False,actual_net_amount_verified=False,source_gate_passed=False,valid_prospective_signal_date=None,orders_authorized=False)


def replay():
    bodies={};records=[];fulls=[];summaries=[]
    for batch in ['pages','artifacts','config_script']:
        p,_=readback(OUT,batch)
        with zipfile.ZipFile(p['retrieved']) as z:
            cfg=json.loads(z.read('requests.json'));res=json.loads(z.read('raw/results.json'));require(res['config_sha256']==hashlib.sha256(z.read('requests.json')).hexdigest(),'Config SHA differs')
            rs=verified_records(cfg,res,lambda n:z.read('raw/'+n));records+=rs
            for r in rs:
                require(r['http_status']==200 and r['exit_code']==0,'Operation source failed transport')
                name=r['request']['filename'];b=z.read('raw/'+name);bodies[name]=b
                summary=dict(filename=name,body_sha256=r['sha256'],request=r['request'],observed_at=r['observed_at'],request_started_at=r['request_started_at'])
                if name.endswith('.html'):
                    full,_=inventory_html(b);fulls.append(dict(filename=name,inventory=full));summary.update(rows=full['rows'],forms=full['forms'])
                elif name.endswith('.pdf'):
                    full,small=replay_pdf(b,r['sha256'],dict(topic=['作業原則']),expected_pages=1);fulls.append(dict(filename=name,pdf=full));summary.update(pdf=small)
                else:fulls.append(dict(filename=name,text=b.decode('utf-8',errors='strict')))
                summaries.append(summary)
    require(len(records)==8,'Expected8saved sources')
    proof=calendar_request(bodies['twse_calendar.html'],bodies['twse_web_report.js'],bodies['twse_main.js']);atomic_json(OUT/'calendar_route.json',proof)
    atomic_json(ROOT/'all_sources_full.json',fulls)
    result=dict(documents=summaries,requests=8,batches=3,calendar_route_sha256=sha256(OUT/'calendar_route.json'),full_inventory_sha256=sha256(ROOT/'all_sources_full.json'),
        annual_calendar_data_acquired=False,provider_closure_notice_available=True,TDCC_general_form_principles_available=True,account_eligibility_verified=False,
        same_day_delivery_and_broker_acceptance_verified=False,fees_or_quotes_verified=False,source_gate_passed=False,profit_edge_proven=False,valid_prospective_signal_date=None,orders_authorized=False)
    annotation= json.loads((OUT/'operations_annotation.json').read_bytes())
    bound=verify_annotation(annotation,fulls,summaries);bound.update(annotation_sha256=sha256(OUT/'operations_annotation.json'))
    atomic_json(OUT/'operations_annotation_audit.json',bound)
    atomic_json(OUT/'inventory.json',result);return result

if __name__=='__main__':
    r=replay();print(json.dumps(dict(requests=8,annual_data=False,calendar_route=r['calendar_route_sha256'],source_gate_passed=False)))
