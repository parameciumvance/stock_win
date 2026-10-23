"""One source-declared annual calendar GET; old operating budget remains frozen."""
import argparse,importlib.util,json,re,zipfile
from pathlib import Path
from research_runtime import sha256
from source_checkpoint import readback
from frontier_cb_operations_replay import calendar_request
ROOT=Path('inputs/frontier_cb_calendar_completion_20261023');OUT=Path('deliverables/frontier_cb_calendar_completion_20261023');POLICY=Path('configs/frontier_cb_calendar_completion_protocol_20261023.json');PREV='deliverables/frontier_cb_operations_20261023/checkpoint.json'

def require(v,m):
    if not v:raise ValueError(m)

def read(p):return json.loads(Path(p).read_bytes())

def proof():
    bodies={}
    expected=dict(pages='04c522f8683c9be95a6ac2fb64f4f9598076349ff01018fed50d30f1a66326e0',artifacts='9282da3098b55ab7b6bd9cc4f8869a62fcf8ed79c84908164f60c01d919d16e0',config_script='b4d13d91b58ca33003bb6ce2f2de5259f26aa18677787e13fa20a9266a0654ef')
    for batch,digest in expected.items():
        p,_=readback('deliverables/frontier_cb_operations_20261023',batch);require(p['sha256']==digest,'Calendar route parent archive differs')
        with zipfile.ZipFile(p['retrieved']) as z:
            for name in ('twse_calendar.html','twse_web_report.js','twse_main.js'):
                if 'raw/'+name in z.namelist():bodies[name]=z.read('raw/'+name)
    return calendar_request(bodies['twse_calendar.html'],bodies['twse_web_report.js'],bodies['twse_main.js'])

def module():
    s=importlib.util.spec_from_file_location('_cb_calendar_shared',Path(__file__).with_name('frontier_sources.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT,m.OUT,m.POLICY=ROOT,OUT,POLICY;return m

def plan(batch='calendar'):
    require(batch=='calendar','Only one frozen calendar request authorized');p=read(POLICY)
    require(all(type(p.get(k)) is int and p[k]==v for k,v in dict(max_saved_requests=1,max_source_batches=1,workers=2,automatic_retries=0).items()),'Calendar allocation drift')
    require(re.fullmatch('[a-f0-9]{64}',p.get('prior_checkpoints',{}).get(PREV,'')) and set(p['batches'])=={'calendar'}
            and not any(k in p for k in ('draft','pending_prior_checkpoint')),'Completed operating checkpoint required')
    require(p['ledger']==dict(prior_CB_raw_requests=59,cumulative_raw_cap=60,cumulative_web_search_queries=12,old_budget_reused=False),'Calendar ledger drift')
    result=module().plan(batch);previous=read('configs/frontier_cb_operations_protocol_20261023.json')
    require(all(p['prior_checkpoints'].get(k)==v for k,v in previous['prior_checkpoints'].items()),'Prior chain dropped')
    actual=proof();selected=read(OUT/'selection.json')
    require(p['selection']==dict(path=str(OUT/'selection.json'),sha256=sha256(OUT/'selection.json')) and selected['calendar_request_proof']==actual,'Calendar literal proof differs')
    original=read('deliverables/frontier_cb_notices_20261023/selection.json')
    for key in ('controls_bond_codes','original_calendar_population_count','original_calendar_fields','original_calendar_rows','controls'):
        require(selected[key]==original[key],'Original controls/population drift')
    require(result[1]==dict(output_directory=str(ROOT/'raw_calendar'),allowed_hosts=['www.twse.com.tw'],requests=[actual['request']]),'Only actual declared calendar GET required')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['plan','acquire','package','verify']);a=p.parse_args();plan()
    if a.stage=='plan':print(json.dumps(dict(requests=1,source_IO_performed=False)))
    else:getattr(module(),a.stage)('calendar')
