"""Preserve HTTP200 empty shells as unresolved evidence, never empty event sets."""
import hashlib,json,zipfile
from pathlib import Path
from lxml import html
from cash_merger_document_lookup import inventory_html
from source_checkpoint import readback
from tender_preflight import verified_records
from research_runtime import atomic_json,sha256
OUT=Path('deliverables/frontier_cb_major_20261023');ROOT=Path('inputs/frontier_cb_major_20261023')

def classify_html(body):
    full,_=inventory_html(body);t=html.fromstring(body.decode('utf-8',errors='strict'))
    divs=t.xpath('//*[@id="div01"]');auto=t.xpath('//form[@name="autoForm"]')
    shell=bool(divs) and not ''.join(divs[0].text_content().split()) and not divs[0].xpath('.//input[not(@type="hidden")]|.//select|.//textarea|.//a|.//tr')
    return full,dict(body_sha256=full['body_sha256'],empty_div01_shell=shell,pending_declared_auto_form=bool(auto),declared_auto_forms=[dict(attributes=dict(f.attrib),controls=[dict(e.attrib) for e in f.xpath('.//input')]) for f in auto],explicit_no_data_message='查無資料' in full['page_text'],returned_row_count=len(full['rows']),form_count=len(full['forms']),usable_event_listing=False,absence_of_events_proven=False,source_gate_passed=False)

def inventory():
    docs=[];fulls=[];count=0
    for batch in ['form','queries','script','ajax_queries','corporate']:
        p,_=readback(OUT,batch)
        with zipfile.ZipFile(p['retrieved']) as z:
            cfg=json.loads(z.read('requests.json'));res=json.loads(z.read('raw/results.json'));assert res['config_sha256']==hashlib.sha256(z.read('requests.json')).hexdigest()
            rs=verified_records(cfg,res,lambda n:z.read('raw/'+n));count+=len(rs)
            for r in rs:
                assert r['http_status']==200 and r['exit_code']==0
                name=r['request']['filename'];b=z.read('raw/'+name);item=dict(batch=batch,filename=name,body_sha256=hashlib.sha256(b).hexdigest(),request=r['request'],request_started_at=r['request_started_at'],observed_at=r['observed_at'])
                if name.endswith('.html'):
                    full,small=classify_html(b);item.update(small);fulls.append(dict(filename=name,inventory=full))
                else:fulls.append(dict(filename=name,text=b.decode('utf-8',errors='strict')))
                docs.append(item)
    assert count==9
    shells=[d for d in docs if d.get('empty_div01_shell')];assert len(shells)==6
    old={d['filename'][:5]:d['body_sha256'] for d in docs if d['batch']=='queries'};new={d['filename'][:5]:d['body_sha256'] for d in docs if d['batch']=='ajax_queries'}
    assert old==new
    atomic_json(ROOT/'all_responses_full.json',fulls)
    result=dict(documents=docs,requests=9,batches=5,empty_shells=6,active_ajax_prefix_correction_changed_body=False,cause_of_empty_shells_verified=False,declared_next_request_present=True,next_source_requirement='Follow each saved autoForm POST to ajax_t113sb04 with actual step12 and unchanged dates/issuer; first response is not final event listing.',source_gate_passed=False,holder_put_notice_verified=False,absence_of_public_notices_proven=False,full_inventory_sha256=sha256(ROOT/'all_responses_full.json'),corporate_form_observed=True,valid_prospective_signal_date=None,orders_authorized=False)
    atomic_json(OUT/'inventory.json',result);return result

if __name__=='__main__':
    r=inventory();print(json.dumps(dict(requests=r['requests'],empty_shells=r['empty_shells'],source_gate_passed=False)))
