"""Replay all three routing batches and preserve every returned option/action."""
import json,zipfile,hashlib
from pathlib import Path
from lxml import html
from cash_merger_document_lookup import inventory_html
from source_checkpoint import readback
from tender_preflight import verified_records
from research_runtime import atomic_json,sha256
OUT=Path('deliverables/frontier_cb_notice_search_20261023');ROOT=Path('inputs/frontier_cb_notice_search_20261023')

def inventory():
    fulls=[];summaries=[];count=0
    for batch in ('controls','routes','general'):
        p,_=readback(OUT,batch)
        with zipfile.ZipFile(p['retrieved']) as z:
            cfg=json.loads(z.read('requests.json'));rs=json.loads(z.read('raw/results.json'))
            assert rs['config_sha256']==hashlib.sha256(z.read('requests.json')).hexdigest()
            records=verified_records(cfg,rs,lambda name:z.read('raw/'+name));count+=len(records)
            for r in records:
                assert r['http_status']==200 and r['exit_code']==0
                name=r['request']['filename'];b=z.read('raw/'+name)
                item=dict(batch=batch,filename=name,sha256=hashlib.sha256(b).hexdigest(),request=r['request'],request_started_at=r['request_started_at'],observed_at=r['observed_at'])
                if name.endswith('.js'):
                    text=b.decode('utf-8',errors='strict');item.update(kind='declared_script_not_executed',script_text_sha256=hashlib.sha256(text.encode()).hexdigest(),action_declarations=[line.strip() for line in text.splitlines() if 'form.action=' in line])
                    fulls.append(dict(filename=name,text=text))
                else:
                    full,_=inventory_html(b,headers=z.read('raw/'+name+'.headers'));t=html.fromstring(b.decode('utf-8',errors='strict'))
                    item.update(kind='html',select_options=[dict(name=e.get('name'),options=[dict(o.attrib,text=o.text_content()) for o in e.xpath('./option')]) for e in t.xpath('//select')],forms=full['forms'],controls=[dict(e.attrib) for e in t.xpath('//input')],source_gate_passed=False)
                    fulls.append(dict(filename=name,inventory=full))
                summaries.append(item)
    assert count==5
    atomic_json(ROOT/'routing_full.json',fulls)
    result=dict(requests=count,batches=3,documents=summaries,full_inventory_sha256=sha256(ROOT/'routing_full.json'),current_holder_put_notice_verified=False,absence_of_public_holder_put_notices_proven=False,source_gate_passed=False,valid_prospective_signal_date=None,profit_edge_proven=False,orders_authorized=False,
        next_exact_navigation=dict(source_archive='b44941466b27c510e6f6295af3e8c3cab59e38666cc7caea66ec7999d94a8979',source_member='raw/99587_issuance.html',literal_href='t113sb04_q2',label='歷史重大訊息查詢',raw_line_number=238,url='https://mopsov.twse.com.tw/mops/web/t113sb04_q2'))
    atomic_json(OUT/'routing_inventory.json',result);return result

if __name__=='__main__':
    r=inventory();print(json.dumps(dict(requests=r['requests'],batches=3,source_gate_passed=False)))
