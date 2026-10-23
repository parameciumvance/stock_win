"""Finite historical bond material-announcement source acquisition."""
import argparse,json,importlib.util,zipfile,re
from pathlib import Path
from lxml import html
from research_runtime import sha256
from source_checkpoint import readback
ROOT=Path('inputs/frontier_cb_major_20261023');OUT=Path('deliverables/frontier_cb_major_20261023')
POLICY=Path('configs/frontier_cb_major_protocol_20261023.json')
PREV='deliverables/frontier_cb_notice_search_20261023/checkpoint.json'

def require(v,m):
    if not v:raise ValueError(m)

def read(p):return json.loads(Path(p).read_bytes())

def module():
    s=importlib.util.spec_from_file_location('_cb_major_shared',Path(__file__).with_name('frontier_sources.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT,m.OUT,m.POLICY=ROOT,OUT,POLICY;return m

def plan(batch='form'):
    require(batch in ('form','queries','script','ajax_queries','corporate'),'Actual form controls must be reviewed before adaptive requests')
    p=read(POLICY)
    require(all(type(p.get(k)) is int and p[k]==v for k,v in dict(max_saved_requests=10,max_source_batches=6,workers=2,automatic_retries=0).items()),'Source allocation drift')
    require(re.fullmatch('[a-f0-9]{64}',p.get('prior_checkpoints',{}).get(PREV,'')),'Completed routing checkpoint must be pinned')
    require(p['request_ledger']==dict(prior_CB_raw_requests=31,prior_search_discovery_queries=3,new_raw_cap=10,cumulative_raw_cap=41,prior_unused_two_reused=False),'Separate source/search ledger drift')
    require(set(p['batches'])=={'form'} and not any(k in p for k in ('draft','pending_prior_checkpoint')),'Unreviewed initial batch/draft refused')
    result=module().plan(batch)
    previous=read('configs/frontier_cb_notice_search_protocol_20261023.json')
    require(all(p['prior_checkpoints'].get(k)==v for k,v in previous['prior_checkpoints'].items()),'Prior checkpoint chain omitted')
    selection=read(OUT/'selection.json');original=read('deliverables/frontier_cb_notices_20261023/selection.json')
    require(p['selection']==dict(path=str(OUT/'selection.json'),sha256=sha256(OUT/'selection.json')),'Selection SHA differs')
    for key in ('controls_bond_codes','original_calendar_population_count','original_calendar_fields','original_calendar_rows','controls'):
        require(selection[key]==original[key],'Frozen population drift')
    package,_=readback('deliverables/frontier_cb_documents_20261023','issuance')
    require(package['sha256']=='b44941466b27c510e6f6295af3e8c3cab59e38666cc7caea66ec7999d94a8979','Issuance archive drift')
    with zipfile.ZipFile(package['retrieved']) as z:
        for code in ('99587','68351','68741'):
            t=html.fromstring(z.read('raw/'+code+'_issuance.html').decode('utf-8',errors='strict'))
            links=t.xpath('//a[@href="t113sb04_q2"]')
            require(len(links)==1 and links[0].text_content()=='歷史重大訊息查詢' and not t.xpath('//base[@href]'),'Actual historical route changed')
    formcfg=read(p['batches']['form']['path'])
    require(formcfg==dict(output_directory=str(ROOT/'raw_form'),allowed_hosts=['mopsov.twse.com.tw'],requests=[dict(filename='historical_bond_material_form.html',url='https://mopsov.twse.com.tw/mops/web/t113sb04_q2',method='GET')]),'Historical form GET must copy actual navigation')
    if batch=='queries':verify_queries(result)
    elif batch=='script':verify_script(result)
    elif batch=='ajax_queries':verify_wire_queries(result)
    elif batch=='corporate':verify_corporate(result)
    return result

def verify_queries(result):
    from frontier_cb_major_forms import query_proof
    package,_=readback(OUT,'form')
    require(package['sha256']=='070ab9ff5bb849a8d7e48f0eda7d93aac3593519b5a2014b130e9cb5bd915752','Major form archive differs')
    with zipfile.ZipFile(package['retrieved']) as z:
        body=z.read('raw/historical_bond_material_form.html')
        meta=json.loads(z.read('raw/historical_bond_material_form.html.meta.json'))
        require(meta['http_status']==200 and meta['exit_code']==0 and meta['sha256']==__import__('hashlib').sha256(body).hexdigest()
                and meta['curl']['url_effective']=='https://mopsov.twse.com.tw/mops/web/t113sb04_q2','Form transport differs')
    proofs=[query_proof(body,issuer) for issuer in ('9958','6835','6874')]
    selected=read(OUT/'queries_selection.json');freeze=read(OUT/'queries_freeze.json')
    require(freeze['selection']==dict(path=str(OUT/'queries_selection.json'),sha256=sha256(OUT/'queries_selection.json'))
            and selected['source_archive_sha256']==package['sha256'] and selected['query_proofs']==json.loads(json.dumps(proofs)),'Source-bound query selection differs')
    reqs=[dict(filename=code+'_major_115.html',url=p['url'],method='POST',data=p['data']) for code,p in zip(('99587','68351','68741'),proofs,strict=True)]
    require(result[1]==dict(output_directory=str(ROOT/'raw_queries'),allowed_hosts=['mopsov.twse.com.tw'],requests=reqs),'All original controls and complete date range required')


def verify_script(result):
    package,_=readback(OUT,'form')
    require(package['sha256']=='070ab9ff5bb849a8d7e48f0eda7d93aac3593519b5a2014b130e9cb5bd915752','Script parent archive differs')
    with zipfile.ZipFile(package['retrieved']) as z:
        t=html.fromstring(z.read('raw/historical_bond_material_form.html').decode('utf-8',errors='strict'))
        require(t.xpath('//script[@src="js/mops2.js"]'),'Exact ajax script missing')
    require(result[1]==dict(output_directory=str(ROOT/'raw_script'),allowed_hosts=['mopsov.twse.com.tw'],requests=[dict(filename='mops2.js',url='https://mopsov.twse.com.tw/mops/web/js/mops2.js',method='GET')]),'Script GET must follow actual declaration')


def verify_wire_queries(result):
    from frontier_cb_major_forms import wire_query
    package,_=readback(OUT,'form');script_package,_=readback(OUT,'script')
    require(package['sha256']=='070ab9ff5bb849a8d7e48f0eda7d93aac3593519b5a2014b130e9cb5bd915752'
            and script_package['sha256']=='81c27caee5ad2b10fde954571672fee6712f2562e56ba724bfe696a1c946a174','AJAX source archives differ')
    with zipfile.ZipFile(package['retrieved']) as z:body=z.read('raw/historical_bond_material_form.html')
    with zipfile.ZipFile(script_package['retrieved']) as z:script=z.read('raw/mops2.js')
    proofs=[wire_query(body,script,issuer) for issuer in ('9958','6835','6874')]
    selected=read(OUT/'ajax_queries_selection.json');freeze=read(OUT/'ajax_queries_freeze.json')
    require(freeze['selection']==dict(path=str(OUT/'ajax_queries_selection.json'),sha256=sha256(OUT/'ajax_queries_selection.json'))
            and selected['query_proofs']==json.loads(json.dumps(proofs)),'AJAX query proof differs')
    reqs=[dict(filename=code+'_major_ajax_115.html',url=p['url'],method='POST',data=p['data']) for code,p in zip(('99587','68351','68741'),proofs,strict=True)]
    require(result[1]==dict(output_directory=str(ROOT/'raw_ajax_queries'),allowed_hosts=['mopsov.twse.com.tw'],requests=reqs),'Active AJAX complete query differs')


def verify_corporate(result):
    from frontier_cb_major_forms import mask_comments
    p,_=readback(OUT,'script');f,_=readback(OUT,'form')
    require(p['sha256']=='81c27caee5ad2b10fde954571672fee6712f2562e56ba724bfe696a1c946a174','Menu script differs')
    with zipfile.ZipFile(p['retrieved']) as z:text=z.read('raw/mops2.js').decode('utf-8',errors='strict')
    text=mask_comments(text)
    require("document.fh2.action=\"/mops/web/\"+fileName;" in text
            and "document.fh2.usually.value=usually;" in text
            and "document.fh2.submit();" in text
            and r"menuAction(\'t05st01\' , \'Y\');" in text,'Actual corporate historical menu declaration absent')
    with zipfile.ZipFile(f['retrieved']) as z:
        t=html.fromstring(z.read('raw/historical_bond_material_form.html').decode('utf-8'))
        fs=t.xpath('//form[@name="fh2"]')
        require(len(fs)==1 and fs[0].get('method')=='post' and [dict(e.attrib) for e in fs[0].xpath('.//input')]==[dict(type='hidden',name='usually',id='usually',value='')],'Actual menu form differs')
    require(result[1]==dict(output_directory=str(ROOT/'raw_corporate'),allowed_hosts=['mopsov.twse.com.tw'],requests=[dict(filename='corporate_historical_form.html',url='https://mopsov.twse.com.tw/mops/web/t05st01',method='POST',data='usually=Y')]),'Corporate form must copy actual menu submission')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['plan','acquire','package','verify']);p.add_argument('--batch',default='form');a=p.parse_args();plan(a.batch)
    if a.stage=='plan':print(json.dumps(dict(batch=a.batch,source_IO_performed=False)))
    else:getattr(module(),a.stage)(a.batch)
