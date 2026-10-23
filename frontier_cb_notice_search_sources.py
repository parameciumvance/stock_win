"""Bounded source-declared dynamic holder-put notice form; no guessed query."""
import argparse,json,importlib.util,hashlib,re,zipfile
from pathlib import Path
from urllib.parse import urlencode,urljoin
from lxml import html
from research_runtime import sha256
from source_checkpoint import readback

ROOT=Path('inputs/frontier_cb_notice_search_20261023')
OUT=Path('deliverables/frontier_cb_notice_search_20261023')
POLICY=Path('configs/frontier_cb_notice_search_protocol_20261023.json')
PREV=Path('deliverables/frontier_cb_notices_20261023')
CHECKPOINT=str(PREV/'checkpoint.json')
POINTER=PREV/'dynamic_form_pointer.json'
FORMS_ARCHIVE='1013c6512d7364bd8729510ef2e5edc0f12cd376905a1a5a90bddb7093fbb117'


def require(v,m):
    if not v:raise ValueError(m)

def read(p):return json.loads(Path(p).read_bytes())

def dynamic_request(body,url):
    t=html.fromstring(body.decode('utf-8',errors='strict'))
    require(not t.xpath('//base[@href]'),'Unexpected HTML base')
    fs=t.xpath('//form[@name="autoForm1"]');require(len(fs)==1,'Unique autoForm1 required')
    f=fs[0]
    require(f.get('method')=='post' and f.get('action')=='/mops/web/ajax_t198sb04','Dynamic POST action differs')
    fields=[(e.get('name'),e.get('value','')) for e in f.xpath('.//input')]
    require(fields==[('run',''),('firstin','true'),('TYPEK','all'),('step','9')],'Dynamic successful controls differ')
    script='\n'.join(e.text or '' for e in t.xpath('//script[not(@src)]'))
    require("ajax1(document.autoForm1,'search');" in script,'Dynamic auto-load declaration absent')
    return dict(filename='pre_maturity_search_controls.html',url=urljoin(url,f.get('action')),method='POST',data=urlencode(fields))

def module():
    spec=importlib.util.spec_from_file_location('_cb_search_shared',Path(__file__).with_name('frontier_sources.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.ROOT,m.OUT,m.POLICY=ROOT,OUT,POLICY;return m

def validate_policy(p):
    require(not any(k in p for k in ('draft','pending_prior_checkpoint')),'Draft policy refused')
    require(re.fullmatch('[a-f0-9]{64}',p.get('prior_checkpoints',{}).get(CHECKPOINT,'')),'Previous checkpoint must be pinned')
    require(all(type(p.get(k)) is int and p[k]==v for k,v in dict(max_saved_requests=7,max_source_batches=3,workers=2,automatic_retries=0).items()),'New allocation drift')
    require(p['request_ledger']==dict(prior_CB_actual_requests=26,new_phase_cap=7,cumulative_CB_cap=33,prior_unused_one_reused=False),'Cumulative allocation drift')
    require(set(p['batches'])=={'controls'},'Unreviewed initial batches refused')

def plan(batch='controls'):
    require(batch in ('controls','routes','general'),'Actual dynamic fields must be read before issuer queries')
    p=read(POLICY);validate_policy(p);result=module().plan(batch)
    previous=read('configs/frontier_cb_notices_protocol_20261023.json')
    require(all(p['prior_checkpoints'].get(k)==v for k,v in previous['prior_checkpoints'].items()),'Prior chain dropped')
    cp=read(CHECKPOINT)
    require(cp['cumulative_CB_source_requests']==26 and cp['files'][str(POINTER)]==sha256(POINTER),'Prior request ledger/pointer drift')
    package,_=readback(PREV,'forms');require(package['sha256']==FORMS_ARCHIVE,'Original forms archive drift')
    with zipfile.ZipFile(package['retrieved']) as z:
        b=z.read('raw/pre_maturity_announcements_form.html');meta=json.loads(z.read('raw/pre_maturity_announcements_form.html.meta.json'))
        require(meta['http_status']==200 and meta['exit_code']==0 and meta['sha256']==hashlib.sha256(b).hexdigest()
                and meta['request']['url']=='https://mopsov.twse.com.tw/mops/web/t198sb04_q1'
                and meta['curl']['url_effective']==meta['request']['url'],'Dynamic parent transport drift')
        request=dynamic_request(b,meta['request']['url'])
    pointer=read(POINTER)
    require(pointer['request']==request and pointer['body_sha256']==hashlib.sha256(b).hexdigest(),'Original dynamic pointer changed')
    selection=read(OUT/'selection.json');ref=p['selection']
    require(ref==dict(path=str(OUT/'selection.json'),sha256=sha256(OUT/'selection.json')),'Search selection drift')
    original=read(PREV/'selection.json')
    for key in ('controls_bond_codes','original_calendar_population_count','original_calendar_fields','original_calendar_rows','controls'):
        require(selection[key]==original[key],'Frozen29/three-control population drift')
    cfg=read(p['batches']['controls']['path'])
    require(cfg==dict(output_directory=str(ROOT/'raw_controls'),allowed_hosts=['mopsov.twse.com.tw'],requests=[request]),'Dynamic controls request differs')
    if batch=='routes':
        from frontier_cb_notice_routes import verify_routes
        verify_routes(result,p)
    elif batch=='general':
        from frontier_cb_notice_routes import verify_general
        verify_general(result)
    return result

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('stage',choices=['plan','acquire','package','verify']);a.add_argument('--batch',default='controls');v=a.parse_args()
    plan(v.batch)
    if v.stage=='plan':print(json.dumps(dict(batch=v.batch,requests=1,source_IO_performed=False)))
    else:getattr(module(),v.stage)(v.batch)
