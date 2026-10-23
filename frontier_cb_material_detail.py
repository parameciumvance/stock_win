"""Keep all corporate rows; derive exact detail submissions from saved buttons."""
import hashlib,json,re
from urllib.parse import urlencode,urljoin
from lxml import html
from cash_merger_document_lookup import inventory_html
from frontier_cb_major_forms import mask_comments

def require(v,m):
    if not v:raise ValueError(m)

TOPICS=('賣回','贖回','收回','終止','到期','轉換辦法','發行辦法','更正')

def listing(body,code):
    full,_=inventory_html(body);tree=html.fromstring(body.decode('utf-8',errors='strict'))
    forms=tree.xpath('//form[@name="t05st01_fm"]');require(len(forms)==1,'Detail form missing');f=forms[0]
    require(f.get('method')=='post' and f.get('action')=='/mops/web/ajax_t05st01','Detail form action differs')
    controls=[(e.get('name'),e.get('value','')) for e in f.xpath('.//input[@type="hidden"]')]
    require(controls==[('firstin','true'),('b_date',''),('e_date',''),('TYPEK',''),('year','115'),('month','all'),('type',''),('co_id',''),('spoke_date',''),('spoke_time',''),('seq_no',''),('MEETING_STEP',''),('MODEL',''),('ITEM',''),('e_month','all'),('step','2'),('off','1')],'Detail default controls drift')
    require(not tree.xpath('//base[@href]'),'Unexpected base')
    rows=[];selected=[]
    for number,tr in enumerate(tree.xpath('//tr'),1):
        cells=[''.join(e.text_content().split()) for e in tr.xpath('./td')]
        buttons=tr.xpath('./td//input[@type="button"]')
        if not buttons:continue
        require(len(cells)==6 and len(buttons)==1 and cells[0]==code[:-1],'Returned corporate row identity/shape drift')
        row=dict(raw_row_number=number,cells=cells,button_attributes=dict(buttons[0].attrib))
        rows.append(row)
        if code not in cells[4] or not any(topic in cells[4] for topic in TOPICS):continue
        onclick=buttons[0].get('onclick');parts=onclick.split(';');assignments=[]
        require(parts[-1]=='' and parts[-2]=="openWindow(this.form ,'')",'Unsupported detail submit handler')
        for part in parts[:-2]:
            m=re.fullmatch(r"document\.t05st01_fm\.(action|seq_no|spoke_time|spoke_date|co_id|TYPEK)(\.value)?='([^']*)'",part)
            require(m is not None,'Unsupported detail assignment');key,suffix,value=m.groups()
            require((key=='action' and suffix is None) or (key!='action' and suffix=='.value'),'Detail assignment shape differs')
            assignments.append((key,value))
        values=dict(assignments)
        require(len(assignments)==6 and len(values)==6 and values['action']=='ajax_t05st01'
                and values['co_id']==cells[0] and values['TYPEK'] in ('sii','otc')
                and re.fullmatch('[0-9]+',values['seq_no'])
                and values['spoke_time']==cells[3].replace(':',''),'Detail click identity differs')
        y,m,d=map(int,cells[2].split('/'));require(values['spoke_date']==f'{y+1911:04}{m:02}{d:02}','Row date/detail date differs')
        submitted=[(k,values.get(k,v)) for k,v in controls]
        selected.append(dict(bond_code=code,source_body_sha256=full['body_sha256'],row=row,original_controls=controls,assignments=assignments,submitted_controls=submitted,
            request=dict(filename=code+'_notice_'+values['spoke_date']+'_'+values['seq_no']+'.html',url='https://mopsov.twse.com.tw/mops/web/ajax_t05st01',method='POST',data='encodeURIComponent=1&'+urlencode(submitted)),source_gate_passed=False))
    return dict(bond_code=code,source_body_sha256=full['body_sha256'],returned_company_rows=rows,selected_details=selected,returned_company_row_count=len(rows),selected_detail_count=len(selected),coverage_complete_verified=False,absence_of_put_notice_proven=False,source_gate_passed=False),full


def verify_openwindow(script):
    active=mask_comments(script.decode('utf-8',errors='strict'))
    start=active.find('function openWindow(form1,specs,title)');end=active.find('function openWindowAction(',start)
    require(start>=0 and end>start,'Actual openWindow declaration absent')
    text=active[start:end]
    for lit in ["var input = form1.querySelectorAll('input');","var action = form1.action;",'var ivalue = input[i].value;',"form01.setAttribute(\"method\",'post');","parameter.setAttribute(\"value\", ivalue);",'ajax1(document.querySelector(']:
        require(lit in text,'openWindow cloning/AJAX declaration drift')
    return dict(script_sha256=hashlib.sha256(script).hexdigest(),active_openwindow_source_offset=start,active_openwindow_source_end=end,source_gate_passed=False)
