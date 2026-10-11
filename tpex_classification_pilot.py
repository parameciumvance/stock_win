"""Retrospective security-type evidence, never a current-membership historical filter."""
import collections, csv, datetime, hashlib, json, pathlib, re
ROOT=pathlib.Path('deliverables/tpex_pilot')

def parse_isin(raw):
    text=raw.decode('cp950');group='';result={}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>',text,re.S|re.I):
        cells=[re.sub('<[^>]+>','',x).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>',tr,re.S|re.I)]
        if len(cells)==1:group=cells[0]
        if len(cells)==7 and '\u3000' in cells[0]:
            code,name=cells[0].split('\u3000',1)
            if code in result:raise ValueError('Duplicate ISIN code')
            result[code]={'name':name,'group':group,'cfi':cells[5],'listing_date':cells[2],'market':cells[3]}
    if not result:raise ValueError('Empty ISIN source')
    return result

def run():
    p=ROOT/'classification'
    otc=parse_isin((p/'isin.raw').read_bytes())
    listed=parse_isin((p/'isin_listed.raw').read_bytes()) if (p/'isin_listed.raw').exists() else {}
    exits={}
    sources=[ROOT/'delisted_history.json']+[p/f'delisted_{y}.raw' for y in [2024,2025,2026]]
    for src in sources:
        j=json.loads(src.read_bytes())
        if j.get('stat')!='ok':raise ValueError('Failed exit query')
        for row in j['tables'][0]['data']:
            roc,mm,dd=map(int,row[2].split('-'));date=datetime.date(roc+1911,mm,dd)
            if date<=datetime.date(2026,10,2):
                exits[row[0]]={'exit_date':date.isoformat(),'name':row[1],'reason':row[3]}
    rows=[];summaries=[]
    for date in ['2023-01-03','2024-01-02','2025-01-02']:
        quotes=json.loads((ROOT/('quotes_'+date.replace('-','')+'.json')).read_bytes())['tables'][0]['data'];counts=collections.Counter()
        for q in quotes:
            code=q[0];e=otc.get(code) or listed.get(code);source='current_otc_isin' if code in otc else ('current_listed_isin' if code in listed else 'unresolved')
            group=e['group'] if e else 'unknown';ordinary=group=='股票' and e['cfi'].startswith('ES') if e else None
            if group=='股票' and not ordinary:group='unresolved_stock_cfi'
            counts[group]+=1
            rows.append({'signal_date':date,'code':code,'historical_quote_name':q[1],'type_group':group,'ordinary_type_supported':ordinary,'cfi':e['cfi'] if e else '', 'type_evidence':source,'later_exit_date':exits.get(code,{}).get('exit_date',''),'later_exit_reason':exits.get(code,{}).get('reason',''),'membership_evidence':'actual historical quote; current ISIN listing date does not remove it','limitation':'retrospective type evidence, not historical announcement snapshot'})
        assert sum(counts.values())==len(quotes)
        summaries.append({'signal_date':date,'all_quotes':len(quotes),'classification_counts':dict(counts),'unresolved_codes':[r['code'] for r in rows if r['signal_date']==date and r['type_group'] in ['unknown','unresolved_stock_cfi']]})
    with (p/'historical_type_evidence.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (p/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2))
    print(json.dumps(summaries,ensure_ascii=False))

if __name__=='__main__':run()
