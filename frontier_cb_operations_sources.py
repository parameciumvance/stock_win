"""Bounded calendar and depository-operation evidence for the unchanged CB controls."""
import argparse,importlib.util,json,re
from pathlib import Path
from research_runtime import sha256
ROOT=Path('inputs/frontier_cb_operations_20261023');OUT=Path('deliverables/frontier_cb_operations_20261023');POLICY=Path('configs/frontier_cb_operations_protocol_20261023.json');PREV='deliverables/frontier_cb_material_rows_20261023/checkpoint.json'
REQUESTS=[
 dict(filename='twse_calendar.html',url='https://www.twse.com.tw/zh/trading/holiday.html',method='GET'),
 dict(filename='tdcc_redemption.html',url='https://www.tdcc.com.tw/portal/zh/equity/redemption',method='GET'),
 dict(filename='tpex_bond_operations.html',url='https://www.tpex.org.tw/zh-tw/bond/service/introduction/tpex-bond.html',method='GET'),
 dict(filename='kgi_service_closures.html',url='https://www.kgieworld.com.tw/index/news_mtrade.aspx?nsid=12907',method='GET'),
 dict(filename='landbank_service_closures.html',url='https://stock.landbank.com.tw/Index_CH/Index_Detail.aspx?ct=1&id=P0066&n=P0054&open=5025',method='GET')]
HOSTS=['www.twse.com.tw','www.tdcc.com.tw','www.tpex.org.tw','www.kgieworld.com.tw','stock.landbank.com.tw']

def require(v,m):
    if not v:raise ValueError(m)

def read(p):return json.loads(Path(p).read_bytes())

def module():
    s=importlib.util.spec_from_file_location('_cb_ops_shared',Path(__file__).with_name('frontier_sources.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT,m.OUT,m.POLICY=ROOT,OUT,POLICY;return m

def plan(batch='pages'):
    require(batch in ('pages','artifacts','config_script'),'Attachments require actual archived source pointers before IO')
    p=read(POLICY)
    require(all(type(p.get(k)) is int and p[k]==v for k,v in dict(max_saved_requests=8,max_source_batches=3,workers=2,automatic_retries=0).items()),'Operations allocation drift')
    require(re.fullmatch('[a-f0-9]{64}',p.get('prior_checkpoints',{}).get(PREV,'')) and set(p['batches'])=={'pages'}
            and not any(k in p for k in ('draft','pending_prior_checkpoint')),'Completed prior checkpoint required')
    require(p['ledger']==dict(prior_CB_raw_requests=51,new_cap=8,cumulative_raw_cap=59,cumulative_web_search_queries=12,prior_unused_one_reused=False),'Operations ledger drift')
    r=module().plan(batch);prior=read('configs/frontier_cb_material_protocol_20261023.json')
    require(all(p['prior_checkpoints'].get(k)==v for k,v in prior['prior_checkpoints'].items()),'Prior chain dropped')
    ref=p['selection'];require(ref==dict(path=str(OUT/'selection.json'),sha256=sha256(OUT/'selection.json')),'Selection SHA drift')
    selected=read(ref['path']);original=read('deliverables/frontier_cb_notices_20261023/selection.json')
    for key in ('controls_bond_codes','original_calendar_population_count','original_calendar_fields','original_calendar_rows','controls'):
        require(selected[key]==original[key],'Original three controls/29rows drift')
    pagescfg=read(p['batches']['pages']['path'])
    require(pagescfg==dict(output_directory=str(ROOT/'raw_pages'),allowed_hosts=HOSTS,requests=REQUESTS),'Only exact official/calendar/provider operation pages required')
    if batch=='artifacts':verify_artifacts(r)
    elif batch=='config_script':verify_config_script(r)
    return r

def verify_artifacts(result):
    from frontier_cb_operations_artifacts import pointers
    proofs=pointers();freeze=read(OUT/'artifacts_freeze.json');selection=read(OUT/'artifacts_selection.json')
    require(freeze['selection']==dict(path=str(OUT/'artifacts_selection.json'),sha256=sha256(OUT/'artifacts_selection.json'))
            and selection['proofs']==proofs,'Operations artifact proof drift')
    require(result[1]==dict(output_directory=str(ROOT/'raw_artifacts'),allowed_hosts=['m.tdcc.com.tw','www.twse.com.tw'],requests=[p['request'] for p in proofs]),'Artifact GETs must copy exact source pointers')


def verify_config_script(result):
    import zipfile
    from lxml import html
    from source_checkpoint import readback
    p,_=readback(OUT,'pages');require(p['sha256']=='04c522f8683c9be95a6ac2fb64f4f9598076349ff01018fed50d30f1a66326e0','Calendar parent differs')
    with zipfile.ZipFile(p['retrieved']) as z:
        t=html.fromstring(z.read('raw/twse_calendar.html').decode('utf-8',errors='strict'))
        require(t.xpath('//script[@src="/res/js/main.js?cRmf"]'),'Exact calendar config script absent')
    require(result[1]==dict(output_directory=str(ROOT/'raw_config_script'),allowed_hosts=['www.twse.com.tw'],requests=[dict(filename='twse_main.js',url='https://www.twse.com.tw/res/js/main.js?cRmf',method='GET')]),'Calendar config GET differs')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['plan','acquire','package','verify']);p.add_argument('--batch',default='pages');a=p.parse_args();plan(a.batch)
    if a.stage=='plan':print(json.dumps(dict(requests=5,source_IO_performed=False)))
    else:getattr(module(),a.stage)(a.batch)
