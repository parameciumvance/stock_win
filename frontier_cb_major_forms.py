"""Serialize actual bond material-announcement form, retaining every named field."""
import hashlib
from urllib.parse import urlencode,urljoin
from lxml import html

def require(v,m):
    if not v:raise ValueError(m)

def query_proof(body,issuer):
    t=html.fromstring(body.decode('utf-8',errors='strict'))
    require(not t.xpath('//base[@href]'),'Unexpected base')
    fs=t.xpath('//form[@name="form1"]');require(len(fs)==1,'One form1 required');f=fs[0]
    require(f.get('action')=='/mops/web/ajax_t113sb04_q2' and f.get('method')=='post','Historical bond action differs')
    require(t.xpath('//form[@name="fh"]//input[@name="funcName"]/@value')==['t113sb04_q2'],'Function name differs')
    fields=[]
    for e in f.xpath('.//input[@name]'):
        require(e.get('type') in ('hidden','text'),'Unknown successful control')
        fields.append((e.get('name'),e.get('value','')))
    expected=[('step','1'),('firstin','ture'),('off','1'),('keyword4',''),('code1',''),('TYPEK2',''),('checkbtn',''),('queryName','co_id'),('inpuType','co_id'),('TYPEK','all'),('co_id',''),('T1',''),('T2','')]
    require(fields==expected and not f.xpath('.//select[@name]|.//textarea[@name]'),'Complete control/default drift')
    scripts=[s.text or '' for s in t.xpath('//script[not(@src)]')];js='\n'.join(scripts)
    for lit in ["document.form1.step.value='1';","document.form1.firstin.value='1';","document.form1.action='/mops/web/ajax_'+name;"]:
        require(lit in js,'Submit mutation absent')
    require(f.xpath('.//input[@type="button" and contains(@onclick,"doAction();ajax1(document.form1,")]'),'Submit declaration absent')
    require(issuer in ('9958','6835','6874'),'Issuer outside original controls')
    changes=dict(firstin='1',co_id=issuer,T1='20260101',T2='20261023')
    submitted=[(k,changes.get(k,v)) for k,v in fields]
    return dict(source_body_sha256=hashlib.sha256(body).hexdigest(),issuer=issuer,source_url='https://mopsov.twse.com.tw/mops/web/t113sb04_q2',url='https://mopsov.twse.com.tw/mops/web/ajax_t113sb04_q2',method='POST',original_controls=fields,submitted_controls=submitted,data=urlencode(submitted),inline_script_sha256=[hashlib.sha256(s.encode()).hexdigest() for s in scripts],date_range=['2026-01-01','2026-10-23'],date_range_policy='same full current year through observation date for every issuer; all returned rows retained',javascript_executed=False,historical_pit_verified=False,source_gate_passed=False)


def mask_comments(text):
    """Mask JS comments while retaining string literals and byte positions."""
    out=list(text);i=0;quote=None
    while i<len(text):
        c=text[i]
        if quote:
            if c=='\\':i+=2;continue
            if c==quote:quote=None
            i+=1;continue
        if c in ('"',"'",'`'):quote=c;i+=1;continue
        if text.startswith('//',i):
            j=text.find('\n',i);j=len(text) if j<0 else j
            out[i:j]=' '*(j-i);i=j;continue
        if text.startswith('/*',i):
            j=text.find('*/',i+2);require(j>=0,'Unclosed JS comment');j+=2
            for k in range(i,j):
                if text[k]!='\n':out[k]=' '
            i=j;continue
        i+=1
    return ''.join(out)


def wire_query(body,script,issuer):
    import re
    text=script.decode('utf-8',errors='strict');active=mask_comments(text)
    matches=list(re.finditer(r'function\s+ajax1\s*\(form1,targets\)\s*\{',active))
    require(len(matches)==1,'Exactly one uncommented ajax1 definition required')
    start=matches[0].start();end=active.find('function getVersion()',start)
    require(end>start,'ajax1 end boundary changed');segment=active[start:end]
    for literal in ["var str='encodeURIComponent=1';","var es = form1.elements;","str=str+'&'+es[i].name+'='+value1;","var url=form1.action;",'xmlDoc[index].send(str);']:
        require(literal in segment,'Active ajax1 wire declaration differs')
    p=query_proof(body,issuer)
    p.update(data='encodeURIComponent=1&'+p['data'],wire_encoder_script_sha256=hashlib.sha256(script).hexdigest(),active_ajax1_source_offset=start,active_ajax1_source_end=end,active_ajax1_source_sha256=hashlib.sha256(text[start:end].encode()).hexdigest(),commented_backup_ignored=True)
    return p
