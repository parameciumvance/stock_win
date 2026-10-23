"""Source-only routing correction within the existing seven-request ceiling."""
import json,hashlib,zipfile
from urllib.parse import urljoin
from lxml import html
from source_checkpoint import readback
from research_runtime import sha256

OUT='deliverables/frontier_cb_notice_search_20261023'

def require(v,m):
    if not v:raise ValueError(m)

def route_requests():
    package,_=readback('deliverables/frontier_cb_documents_20261023','issuance')
    require(package['sha256']=='b44941466b27c510e6f6295af3e8c3cab59e38666cc7caea66ec7999d94a8979','Issuance archive drift')
    with zipfile.ZipFile(package['retrieved']) as z:
        b=z.read('raw/99587_issuance.html');t=html.fromstring(b.decode())
        a=t.xpath('//a[@href="t127sb00_q2"]');require(len(a)==1 and a[0].text_content()=='各項公告查詢作業','Actual general announcement route missing')
    forms,_=readback('deliverables/frontier_cb_notices_20261023','forms')
    require(forms['sha256']=='1013c6512d7364bd8729510ef2e5edc0f12cd376905a1a5a90bddb7093fbb117','Forms archive drift')
    with zipfile.ZipFile(forms['retrieved']) as z:
        b=z.read('raw/pre_maturity_announcements_form.html');t=html.fromstring(b.decode())
        require(t.xpath('//script[@src="js/outerScript/t198sb04.js"]'),'Actual getslt script pointer missing')
    return [dict(filename='general_announcements_form.html',url='https://mopsov.twse.com.tw/mops/web/t127sb00_q2',method='GET'),dict(filename='t198sb04.js',url='https://mopsov.twse.com.tw/mops/web/js/outerScript/t198sb04.js',method='GET')]


def verify_routes(result,policy):
    from pathlib import Path
    amendment=json.loads(Path(OUT+'/routing_amendment.json').read_bytes())
    require(amendment['original_protocol_sha256']==sha256('configs/frontier_cb_notice_search_protocol_20261023.json') and amendment['max_saved_requests']==7 and amendment['max_source_batches']==3,'Routing amendment cannot widen source limits')
    freeze=json.loads(Path(OUT+'/routes_freeze.json').read_bytes())
    require(freeze['routing_amendment_sha256']==sha256(OUT+'/routing_amendment.json'),'Routing rationale drift')
    require(result[1]==dict(output_directory='inputs/frontier_cb_notice_search_20261023/raw_routes',allowed_hosts=['mopsov.twse.com.tw'],requests=route_requests()),'Routes must be exact actual source declarations')


def general_requests():
    package,_=readback(OUT,'routes')
    require(package['sha256']=='8035777f69c88d9f712c77abb65e5bb75ef3c7e91df0db7a0d48e63f841a2745','Routing source archive drift')
    with zipfile.ZipFile(package['retrieved']) as z:
        b=z.read('raw/general_announcements_form.html');t=html.fromstring(b.decode())
        fs=t.xpath('//form[@name="autoForm1"]');require(len(fs)==1,'General auto-form missing')
        f=fs[0];require(f.get('action')=='/mops/web/ajax_t127sb00' and f.get('method')=='post','General form action drift')
        controls=[(e.get('name'),e.get('value','')) for e in f.xpath('.//input')]
        require(controls==[('run',''),('firstin','true'),('TYPEK','all'),('step','9')],'General form fields drift')
        require(t.xpath('//script[@src="js/outerScript/t127sb00.js"]'),'General getslt script absent')
        require(any("ajax1(document.autoForm1,'search');" in (e.text or '') for e in t.xpath('//script')),'General auto-load absent')
    return [dict(filename='general_search_controls.html',url='https://mopsov.twse.com.tw/mops/web/ajax_t127sb00',method='POST',data='run=&firstin=true&TYPEK=all&step=9'),dict(filename='t127sb00.js',url='https://mopsov.twse.com.tw/mops/web/js/outerScript/t127sb00.js',method='GET')]


def verify_general(result):
    from pathlib import Path
    freeze=json.loads(Path(OUT+'/general_freeze.json').read_bytes())
    amendment=json.loads(Path(OUT+'/routing_followthrough.json').read_bytes())
    require(freeze['routing_followthrough_sha256']==sha256(OUT+'/routing_followthrough.json')
            and amendment['original_protocol_sha256']==sha256('configs/frontier_cb_notice_search_protocol_20261023.json')
            and amendment['max_saved_requests']==7 and amendment['max_source_batches']==3,'General routing cannot widen caps')
    require(result[1]==dict(output_directory='inputs/frontier_cb_notice_search_20261023/raw_general',allowed_hosts=['mopsov.twse.com.tw'],requests=general_requests()),'General source requests differ')
