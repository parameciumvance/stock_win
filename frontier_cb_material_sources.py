"""Replay the three saved autoForm continuations before acquiring final event rows."""
import argparse,hashlib,importlib.util,json,re,zipfile
from pathlib import Path
from urllib.parse import urlencode,urljoin
from lxml import html
from research_runtime import sha256
from source_checkpoint import readback
ROOT=Path('inputs/frontier_cb_material_rows_20261023');OUT=Path('deliverables/frontier_cb_material_rows_20261023')
POLICY=Path('configs/frontier_cb_material_protocol_20261023.json');PREV='deliverables/frontier_cb_major_20261023/checkpoint.json'
PARENT='deliverables/frontier_cb_major_20261023';ARCHIVE='58bd54ce53c82ebf4e14eb6a6062edd91db1048865ecb98a8c7f9221cd1d4f05'

def require(v,m):
    if not v:raise ValueError(m)

def read(p):return json.loads(Path(p).read_bytes())

def continuation(body,issuer):
    t=html.fromstring(body.decode('utf-8',errors='strict'));require(not t.xpath('//base[@href]'),'Unexpected base')
    fs=t.xpath('//form[@name="autoForm"]');require(len(fs)==1,'Unique actual continuation required');f=fs[0]
    require(f.get('method')=='post' and f.get('action')=='/mops/web/ajax_t113sb04','Actual continuation action differs')
    require(not f.xpath('.//select|.//textarea|.//button|.//input[not(@type="hidden")]'),'Unexpected continuation control')
    fields=[(e.get('name'),e.get('value','')) for e in f.xpath('.//input')]
    require(fields==[('run',''),('step','12'),('id',''),('T1','20260101'),('T2','20261023'),('co_id',issuer),('firstin','true'),('KK','2')],'Continuation issuer/date/default fields differ')
    require(any("ajax1(document.autoForm,'div01');" in (s.text or '') for s in t.xpath('//script[not(@src)]')),'Actual auto-load invocation absent')
    return dict(source_body_sha256=hashlib.sha256(body).hexdigest(),issuer=issuer,controls=fields,method='POST',url='https://mopsov.twse.com.tw/mops/web/ajax_t113sb04',data='encodeURIComponent=1&'+urlencode(fields),source_gate_passed=False)

def module():
    s=importlib.util.spec_from_file_location('_cb_material_shared',Path(__file__).with_name('frontier_sources.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT,m.OUT,m.POLICY=ROOT,OUT,POLICY;return m

def plan(batch='rows'):
    require(batch in ('rows','corporate','details','month'),'Final rows must be read before actual detail requests')
    p=read(POLICY)
    require(all(type(p.get(k)) is int and p[k]==v for k,v in dict(max_saved_requests=12,max_source_batches=4,workers=2,automatic_retries=0).items()),'Source budget drift')
    require(re.fullmatch('[a-f0-9]{64}',p.get('prior_checkpoints',{}).get(PREV,'')) and set(p['batches'])=={'rows'},'Final prior checkpoint/initial batch differs')
    require(p['ledger']==dict(prior_CB_raw_requests=40,cumulative_raw_cap=52,prior_unused_one_reused=False,cumulative_web_search_queries=6),'Request ledger drift')
    result=module().plan(batch);previous=read('configs/frontier_cb_major_protocol_20261023.json')
    require(all(p['prior_checkpoints'].get(k)==v for k,v in previous['prior_checkpoints'].items()),'Old checkpoint chain dropped')
    selection=read(OUT/'selection.json');original=read('deliverables/frontier_cb_notices_20261023/selection.json')
    require(p['selection']==dict(path=str(OUT/'selection.json'),sha256=sha256(OUT/'selection.json')),'Selection SHA differs')
    for key in ('controls_bond_codes','original_calendar_population_count','original_calendar_fields','original_calendar_rows','controls'):
        require(selection[key]==original[key],'Original population drift')
    package,_=readback(PARENT,'ajax_queries');require(package['sha256']==ARCHIVE,'Continuation parent archive differs')
    reqs=[];proofs=[]
    with zipfile.ZipFile(package['retrieved']) as z:
        for code in ('99587','68351','68741'):
            b=z.read('raw/'+code+'_major_ajax_115.html');meta=json.loads(z.read('raw/'+code+'_major_ajax_115.html.meta.json'))
            require(meta['http_status']==200 and meta['exit_code']==0 and meta['sha256']==hashlib.sha256(b).hexdigest() and meta['curl']['url_effective']=='https://mopsov.twse.com.tw/mops/web/ajax_t113sb04_q2','Parent continuation transport differs')
            proof=continuation(b,code[:-1]);proofs.append(proof);reqs.append(dict(filename=code+'_material_rows.html',url=proof['url'],method='POST',data=proof['data']))
    require(selection['continuation_proofs']==json.loads(json.dumps(proofs)),'Continuation proof drift')
    rowscfg=read(p['batches']['rows']['path'])
    require(rowscfg==dict(output_directory=str(ROOT/'raw_rows'),allowed_hosts=['mopsov.twse.com.tw'],requests=reqs),'All3source-declared continuation requests required')
    if batch=='corporate':verify_corporate(result)
    elif batch=='details':verify_details(result)
    elif batch=='month':verify_month(result)
    return result

def verify_corporate(result):
    from frontier_cb_corporate_forms import corporate_query
    p,_=readback(PARENT,'corporate');s,_=readback(PARENT,'script')
    require(p['sha256']=='1b40bf75e946f4bc4fa739d45ced8ee0d966fc89fdfb0025a2cc323aac47346c'
            and s['sha256']=='81c27caee5ad2b10fde954571672fee6712f2562e56ba724bfe696a1c946a174','Corporate source archives drift')
    with zipfile.ZipFile(p['retrieved']) as z:b=z.read('raw/corporate_historical_form.html')
    with zipfile.ZipFile(s['retrieved']) as z:script=z.read('raw/mops2.js')
    proofs=[corporate_query(b,script,i) for i in ('9958','6835','6874')]
    amendment=read(OUT/'corporate_routing_amendment.json');freeze=read(OUT/'corporate_freeze.json')
    require(amendment['protocol_sha256']==sha256(POLICY) and amendment['max_saved_requests']==12 and amendment['max_source_batches']==4
            and freeze['routing_amendment_sha256']==sha256(OUT/'corporate_routing_amendment.json'),'Corporate routing cannot widen caps')
    selection=read(OUT/'corporate_selection.json')
    require(freeze['selection']==dict(path=str(OUT/'corporate_selection.json'),sha256=sha256(OUT/'corporate_selection.json'))
            and selection['query_proofs']==json.loads(json.dumps(proofs)),'Corporate query proof differs')
    requests=[dict(filename=code+'_corporate_115.html',url=p['url'],method='POST',data=p['data']) for code,p in zip(('99587','68351','68741'),proofs,strict=True)]
    require(result[1]==dict(output_directory=str(ROOT/'raw_corporate'),allowed_hosts=['mopsov.twse.com.tw'],requests=requests),'Three complete corporate queries must match actual source')


def verify_details(result):
    from frontier_cb_material_detail import listing,verify_openwindow
    package,_=readback(OUT,'corporate');s,_=readback(PARENT,'script')
    require(package['sha256']=='0b0a679ec7f50b56881b7706e4d735e3c0d58c7d157ecce7fa2cdcc05aa884dc','Corporate listing archive differs')
    with zipfile.ZipFile(s['retrieved']) as z:scriptproof=verify_openwindow(z.read('raw/mops2.js'))
    summaries=[];proofs=[]
    with zipfile.ZipFile(package['retrieved']) as z:
        for code in ('99587','68351','68741'):
            small,_=listing(z.read('raw/'+code+'_corporate_115.html'),code);summaries.append(small);proofs+=small['selected_details']
    selected=read(OUT/'details_selection.json');freeze=read(OUT/'details_freeze.json')
    require(freeze['selection']==dict(path=str(OUT/'details_selection.json'),sha256=sha256(OUT/'details_selection.json'))
            and selected['all_three_summaries']==json.loads(json.dumps(summaries))
            and selected['script_proof']==scriptproof,'All3listing/detail source proofs differ')
    require(1<=len(proofs)<=3 and result[1]==dict(output_directory=str(ROOT/'raw_details'),allowed_hosts=['mopsov.twse.com.tw'],requests=[p['request'] for p in proofs]),'All matching actual pointers required within remaining batch')


def verify_month(result):
    from frontier_cb_corporate_forms import current_month_query
    p,_=readback(PARENT,'corporate');s,_=readback(PARENT,'script')
    require(p['sha256']=='1b40bf75e946f4bc4fa739d45ced8ee0d966fc89fdfb0025a2cc323aac47346c'
            and s['sha256']=='81c27caee5ad2b10fde954571672fee6712f2562e56ba724bfe696a1c946a174','Month source archives differ')
    with zipfile.ZipFile(p['retrieved']) as z:body=z.read('raw/corporate_historical_form.html')
    with zipfile.ZipFile(s['retrieved']) as z:script=z.read('raw/mops2.js')
    proofs=[current_month_query(body,script,i) for i in ('9958','6835','6874')]
    selection=read(OUT/'month_selection.json');freeze=read(OUT/'month_freeze.json');amendment=read(OUT/'month_audit_amendment.json')
    require(freeze['selection']==dict(path=str(OUT/'month_selection.json'),sha256=sha256(OUT/'month_selection.json'))
            and selection['query_proofs']==json.loads(json.dumps(proofs)),'Current month proof differs')
    require(freeze['amendment_sha256']==sha256(OUT/'month_audit_amendment.json')
            and amendment['protocol_sha256']==sha256(POLICY) and amendment['max_saved_requests']==12 and amendment['max_source_batches']==4,'Month overlap cannot widen caps')
    reqs=[dict(filename=code+'_corporate_october.html',url=p['url'],method='POST',data=p['data']) for code,p in zip(('99587','68351','68741'),proofs,strict=True)]
    require(result[1]==dict(output_directory=str(ROOT/'raw_month'),allowed_hosts=['mopsov.twse.com.tw'],requests=reqs),'All3actual-control October overlap queries required')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['plan','acquire','package','verify']);p.add_argument('--batch',default='rows');a=p.parse_args();plan(a.batch)
    if a.stage=='plan':print(json.dumps(dict(batch=a.batch,source_IO_performed=False)))
    else:getattr(module(),a.stage)(a.batch)
