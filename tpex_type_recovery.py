"""Recover exact single-query types; expose formal-rule candidates separately from confirmed CFI."""
import csv, hashlib, json, pathlib, re
from html import unescape
ROOT=pathlib.Path('deliverables/tpex_pilot/classification')
RULE_URL='https://www.twse.com.tw/staticFiles/announcement/announcement/1090007509-2.pdf'

def parse_single(raw):
    # Single-result tables use CP950; the input form is UTF-8.
    text=raw.decode('cp950');out={}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>',text,re.S|re.I):
        cells=[unescape(re.sub('<[^>]+>','',s)).strip() for s in re.findall(r'<td[^>]*>(.*?)</td>',tr,re.S|re.I)]
        if len(cells)==10 and cells[0].isdigit():
            code=cells[2]
            if code in out:raise ValueError('Duplicate exact code')
            out[code]={'isin':cells[1],'code':code,'name':cells[3],'market':cells[4],'issue_type':cells[5],'date':cells[7],'cfi':cells[8],'remark':cells[9]}
    return out

def candidate_from_formal_rule(code):
    # Does not fabricate ISIN/CFI or infer historical announcement availability.
    if re.fullmatch(r'[0-9]{4}',code):return 'ordinary_stock_rule_candidate'
    if re.fullmatch(r'[0-9]{4}[A-W]',code):return 'preferred_stock_rule_candidate'
    return 'nonfour_digit_security_type_unresolved'

def run():
    evidence=ROOT/'unknown_single_query.html';exact=parse_single(evidence.read_bytes())
    requested=set(json.loads((ROOT/'unknown_query_meta.json').read_text())['requested_codes'])
    if not set(exact)<=requested:raise ValueError('Unexpected returned code')
    input_rows=list(csv.DictReader((ROOT/'historical_type_evidence.csv').open()))
    summary=[];output=[]
    for row in input_rows:
        r=dict(row);c=r['code'];r['formal_rule_candidate']='';r['formal_rule_source']='';r['exact_issue_type']='';r['exact_query_sha256']=''
        if r['type_group']=='unknown' and c in exact:
            e=exact[c];r['exact_issue_type']=e['issue_type'];r['exact_query_sha256']=hashlib.sha256(evidence.read_bytes()).hexdigest()
            if e['issue_type']=='普通股' and e['cfi'].startswith('ES'):
                r['type_group']='股票';r['ordinary_type_supported']='True';r['cfi']=e['cfi'];r['type_evidence']='official_exact_single_query'
        if r['type_group']=='unknown':
            r['formal_rule_candidate']=candidate_from_formal_rule(c);r['formal_rule_source']=RULE_URL
        output.append(r)
    for date in sorted({r['signal_date'] for r in output}):
        rows=[r for r in output if r['signal_date']==date];unknown=[r for r in rows if r['type_group']=='unknown']
        summary.append({'signal_date':date,'all_rows':len(rows),'confirmed_ordinary':sum(r['type_group']=='股票' for r in rows),'exact_query_recovered':sum(r['type_evidence']=='official_exact_single_query' for r in rows),'remaining_unknown':len(unknown),'ordinary_rule_candidates':[r['code'] for r in unknown if r['formal_rule_candidate']=='ordinary_stock_rule_candidate'],'other_unresolved':[r['code'] for r in unknown if r['formal_rule_candidate']!='ordinary_stock_rule_candidate'],'limitation':'rule candidates not automatically included in strict stock pool'})
    with (ROOT/'recovered_type_evidence.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    (ROOT/'recovery_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (ROOT/'exact_type_records.json').write_text(json.dumps(exact,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':run()
