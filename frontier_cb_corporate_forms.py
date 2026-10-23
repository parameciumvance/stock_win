"""Actual corporate historical form and active AJAX prefix; same full-year controls."""
import hashlib,re
from urllib.parse import urlencode
from lxml import html
from frontier_cb_major_forms import mask_comments

def require(v,m):
    if not v:raise ValueError(m)

def corporate_query(body,script,issuer):
    t=html.fromstring(body.decode('utf-8',errors='strict'));require(not t.xpath('//base[@href]'),'Unexpected base')
    fs=t.xpath('//form[@name="form1"]');require(len(fs)==1,'Unique corporate form required');f=fs[0]
    require(f.get('method')=='post' and f.get('action')=='/mops/web/ajax_t05st01','Actual corporate action drift')
    require(t.xpath('//form[@name="fh"]//input[@name="funcName"]/@value')==['t05st01'],'Corporate function name drift')
    fields=[];options={}
    for e in f.xpath('.//input[@name]|.//select[@name]'):
        if e.tag=='select':
            opts=[dict(o.attrib,text=o.text_content()) for o in e.xpath('./option')];require(opts,'Empty select');options[e.get('name')]=opts
            require(not e.xpath('./option[@selected]'),'New selected state requires review');value=opts[0].get('value','')
        else:
            require(e.get('type') in ('hidden','text'),'Unexpected named control');value=e.get('value','')
        fields.append((e.get('name'),value))
    require(fields==[('step','1'),('firstin','ture'),('off','1'),('keyword4',''),('code1',''),('TYPEK2',''),('checkbtn',''),('queryName','co_id'),('inpuType','co_id'),('TYPEK','all'),('co_id',''),('year',''),('month',''),('b_date',''),('e_date','')],'All15corporate controls/defaults required')
    require(options['month'][0]==dict(value='',text='全年度'),'Full-year option absent')
    js='\n'.join(s.text or '' for s in t.xpath('//script[not(@src)]'))
    for lit in ["document.form1.step.value='1';","document.form1.firstin.value='1';","document.form1.action='/mops/web/ajax_'+name;"]:
        require(lit in js,'doAction mutation differs')
    require(f.xpath('.//input[@type="button" and contains(@onclick,"doAction();ajax1(document.form1,")]'),'Submit declaration absent')
    active=mask_comments(script.decode('utf-8',errors='strict'));matches=list(re.finditer(r'function\s+ajax1\s*\(form1,targets\)\s*\{',active));require(len(matches)==1,'Unique active ajax1 required')
    start=matches[0].start();end=active.find('function getVersion()',start);require(end>start,'ajax1 boundary drift');segment=active[start:end]
    for lit in ["var str='encodeURIComponent=1';","var es = form1.elements;","str=str+'&'+es[i].name+'='+value1;","var url=form1.action;",'xmlDoc[index].send(str);']:
        require(lit in segment,'Actual AJAX serialization drift')
    require(issuer in ('9958','6835','6874'),'Issuer not original control')
    overrides=dict(firstin='1',co_id=issuer,year='115');submitted=[(k,overrides.get(k,v)) for k,v in fields]
    return dict(source_body_sha256=hashlib.sha256(body).hexdigest(),script_sha256=hashlib.sha256(script).hexdigest(),issuer=issuer,original_controls=fields,submitted_controls=submitted,select_options=options,method='POST',url='https://mopsov.twse.com.tw/mops/web/ajax_t05st01',data='encodeURIComponent=1&'+urlencode(submitted),scope='ROC115 full year as of actual observation; same scope for all3issuers; all rows retained',javascript_executed=False,source_gate_passed=False)


def current_month_query(body,script,issuer):
    p=corporate_query(body,script,issuer)
    require(dict(value='10',text='10') in p['select_options']['month'],'Actual October option missing')
    require(any(o.get('value')=='01' for o in p['select_options']['b_date'])
            and any(o.get('value')=='23' for o in p['select_options']['e_date']),'Actual day bounds missing')
    changes=dict(month='10',b_date='01',e_date='23')
    p['submitted_controls']=[(k,changes.get(k,v)) for k,v in p['submitted_controls']]
    p.update(data='encodeURIComponent=1&'+urlencode(p['submitted_controls']),scope='Independent overlap audit: ROC115 October1through23 for all3issuers; compare all rows to saved full-year listing, no event-outcome selection')
    return p
