"""Replay saved official form controls; never execute returned JavaScript."""
import hashlib
from pathlib import Path
from urllib.parse import urljoin,urlencode
import zipfile
from lxml import html
from research_runtime import atomic_json
from source_checkpoint import readback

OUT=Path('deliverables/frontier_cb_notices_20261023')

def require(v,m):
    if not v:raise ValueError(m)

def query_proof(body, source_url, issuer):
    tree=html.fromstring(body.decode('utf-8',errors='strict'))
    require(not tree.xpath('//base[@href]'),'Unexpected HTML base')
    forms=tree.xpath('//form[@name="form1"]');require(len(forms)==1,'Need one actual query form')
    f=forms[0];require(f.get('method').lower()=='post' and f.get('action')=='/mops/web/ajax_t108sb08','Actual action drift')
    require(tree.xpath('//form[@name="fh"]//input[@name="funcName"]/@value')==['t108sb08'],'Function identity drift')
    fields=[];choices={}
    for el in f.xpath('.//input[@name]|.//select[@name]'):
        name=el.get('name');require(name not in dict(fields),'Duplicate control')
        if el.tag=='select':
            opts=[dict(value=o.get('value',''),text=o.text_content()) for o in el.xpath('./option')]
            require(opts,'Empty select');choices[name]=opts
            selected=el.xpath('./option[@selected]');value=(selected[0] if selected else el.xpath('./option')[0]).get('value','')
        else:
            require(el.get('type','text') in ('hidden','text'),'Unsupported successful control')
            value=el.get('value','')
        fields.append((name,value))
    require([k for k,v in fields]==['step','firstin','off','keyword4','code1','TYPEK2','checkbtn','queryName','inpuType','TYPEK','isnew','co_id','year','month','b_date','e_date'],'Form population changed')
    require(dict(fields)==dict(step='1',firstin='ture',off='1',keyword4='',code1='',TYPEK2='',checkbtn='',queryName='co_id',inpuType='co_id',TYPEK='all',isnew='true',co_id='',year='',month='',b_date='',e_date=''),'Default control values changed')
    require(any(o==dict(value='false',text='歷史資料') for o in choices['isnew']) and choices['month'][0]==dict(value='',text='全年度'),'Historical full-year option changed')
    scripts=[s.text or '' for s in tree.xpath('//script[not(@src)]')]
    js='\n'.join(scripts)
    for literal in ["document.form1.step.value='1';","document.form1.firstin.value='1';","document.form1.action='/mops/web/ajax_'+name;"]:
        require(literal in js,'doAction mutation missing')
    require(f.xpath('.//input[@type="button" and contains(@onclick,"doAction();ajax1(document.form1,")]'),'Actual query button missing')
    require(issuer in ('9958','6835','6874'),'Not a frozen issuer')
    overrides=dict(step='1',firstin='1',isnew='false',co_id=issuer,year='115')
    submitted=[(k,overrides.get(k,v)) for k,v in fields]
    return dict(source_body_sha256=hashlib.sha256(body).hexdigest(),source_url=source_url,
        form_action=f.get('action'),method='POST',url=urljoin(source_url,f.get('action')),
        original_controls=fields,select_options=choices,inline_script_sha256=[hashlib.sha256(s.encode()).hexdigest() for s in scripts],
        submitted_controls=submitted,data=urlencode(submitted),query_scope='ROC115/full year as of actual observation; no month/day restriction',issuer=issuer,
        javascript_executed=False,notice_verified=False,source_gate_passed=False)

def inventory():
    p,_=readback(OUT,'forms')
    with zipfile.ZipFile(p['retrieved']) as z:
        rows=[]
        for name in ('pre_maturity_announcements_form.html','convertible_announcements_form.html'):
            b=z.read('raw/'+name);tree=html.fromstring(b.decode('utf-8',errors='strict'))
            rows.append(dict(filename=name,body_sha256=hashlib.sha256(b).hexdigest(),forms=[dict(name=f.get('name'),method=f.get('method'),action=f.get('action'),controls=[dict(e.attrib,options=[dict(o.attrib,text=o.text_content()) for o in e.xpath('./option')]) for e in f.xpath('.//input|.//select')]) for f in tree.xpath('//form')],external_scripts=tree.xpath('//script[@src]/@src')))
        body=z.read('raw/convertible_announcements_form.html')
        proofs=[query_proof(body,'https://mopsov.twse.com.tw/mops/web/t108sb08',issuer) for issuer in ('9958','6835','6874')]
    result=dict(source_archive_sha256=p['sha256'],forms=rows,query_proofs=proofs,source_gate_passed=False,all_returned_controls_preserved=True)
    atomic_json(OUT/'forms_inventory.json',result);return result

if __name__=='__main__':
    r=inventory();print('forms',len(r['forms']),'source-bound queries',len(r['query_proofs']))
