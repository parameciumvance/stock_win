"""Exact attachment/script pointers from the saved operation pages."""
import json,hashlib,zipfile
from lxml import html
from urllib.parse import urljoin
from source_checkpoint import readback

def require(v,m):
    if not v:raise ValueError(m)

def pointers():
    p,_=readback('deliverables/frontier_cb_operations_20261023','pages');require(p['sha256']=='04c522f8683c9be95a6ac2fb64f4f9598076349ff01018fed50d30f1a66326e0','Operation pages archive drift')
    proofs=[]
    with zipfile.ZipFile(p['retrieved']) as z:
        for member,kind,name,parent in [('tdcc_redemption.html','pdf','tdcc_redemption_principles.pdf','https://www.tdcc.com.tw/portal/zh/equity/redemption'),('twse_calendar.html','script','twse_web_report.js','https://www.twse.com.tw/zh/trading/holiday.html')]:
            body=z.read('raw/'+member);t=html.fromstring(body.decode('utf-8',errors='strict'));require(not t.xpath('//base[@href]'),'Unexpected base')
            if kind=='pdf':
                nodes=t.xpath('//a[normalize-space(.)="附件-作業原則"]');require(len(nodes)==1,'Unique actual TDCC principles pointer required');literal=nodes[0].get('href')
                require(literal=='https://m.tdcc.com.tw/TDCCWEB/upload/4028979687182c920187368f082f0047.pdf','TDCC literal pointer changed')
            else:
                nodes=t.xpath('//script[starts-with(@src,"/res/js/web-report.js?")]');require(len(nodes)==1,'Unique actual TWSE report script required');literal=nodes[0].get('src')
                require(literal=='/res/js/web-report.js?-0I2','TWSE script pointer changed')
            proofs.append(dict(source_member='raw/'+member,source_body_sha256=hashlib.sha256(body).hexdigest(),literal=literal,request=dict(filename=name,url=urljoin(parent,literal),method='GET')))
    return proofs
