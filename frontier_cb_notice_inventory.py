"""Neutral full replay of notice responses; conversion notices are not holder puts."""
import json,hashlib,zipfile
from pathlib import Path
from lxml import html
from source_checkpoint import readback
from tender_preflight import verified_records
from cash_merger_document_lookup import inventory_html
from research_runtime import atomic_json,sha256
from frontier_cb_notice_forms import inventory as forms_inventory

OUT=Path('deliverables/frontier_cb_notices_20261023')

def inventory():
    forms_inventory()
    p,_=readback(OUT,'queries');allrows=[];fulls=[]
    with zipfile.ZipFile(p['retrieved']) as z:
        cfg=json.loads(z.read('requests.json'));results=json.loads(z.read('raw/results.json'))
        assert results['config_sha256']==hashlib.sha256(z.read('requests.json')).hexdigest()
        records=verified_records(cfg,results,lambda n:z.read('raw/'+n))
        for code,record in zip(('99587','68351','68741'),records,strict=True):
            assert record['http_status']==200 and record['exit_code']==0
            name=record['request']['filename'];b=z.read('raw/'+name);full,_=inventory_html(b,headers=z.read('raw/'+name+'.headers'))
            tree=html.fromstring(b.decode('utf-8',errors='strict'))
            labels=[e.text_content().strip() for e in tree.xpath('//center/font')]
            issuer=code[:-1]
            assert '公司代號：'+issuer in ''.join(tree.text_content().split())
            notices=[dict(raw_row_number=r['occurrence'],cells=r['cells']) for r in full['rows'] if len(r['cells'])==4 and r['cells'][0]['tag']=='td']
            row=dict(bond_code=code,issuer=issuer,filename=name,body_sha256=full['body_sha256'],observed_at=record['observed_at'],
                returned_section_labels=labels,all_notices=notices,detail_buttons=tree.xpath('//input[@type="button"]/@onclick'),
                missing_sections_as_returned=tree.xpath('//h4/text()'),all_html_rows_sha256=hashlib.sha256(json.dumps(full['rows'],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                holder_put_notice_verified=False,absence_of_holder_puts_proven=False,source_gate_passed=False)
            allrows.append(row);fulls.append(dict(filename=name,inventory=full))
    root=Path('inputs/frontier_cb_notices_20261023');atomic_json(root/'queries_full.json',fulls)
    result=dict(source_archive_sha256=p['sha256'],documents=allrows,full_inventory_sha256=sha256(root/'queries_full.json'),
        meaning='All response categories/rows preserved, including other issues; this interface is not proof of holder-put notice availability or absence.',
        source_gate_passed=False,cash_claim_source_gate_passed=False,valid_prospective_signal_date=None,profit_edge_proven=False,orders_authorized=False)
    atomic_json(OUT/'queries_inventory.json',result);return result

if __name__=='__main__':
    r=inventory();print(json.dumps(dict(documents=3,returned_notices=[len(x['all_notices']) for x in r['documents']],source_gate_passed=False)))
