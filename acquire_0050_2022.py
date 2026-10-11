"""Free official 0050 monthly quotes and forward cash-dividend price proxy."""
from pathlib import Path
import concurrent.futures,hashlib,json,re,urllib.request
import pandas as pd
from research_runtime import atomic_bytes,atomic_json

ROOT=Path('deliverables/benchmark_2022')
def fetch(name,url):
    p=ROOT/'raw'/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        meta=json.loads(p.with_suffix(p.suffix+'.meta.json').read_text())
        assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']
        return p.read_bytes()
    with urllib.request.urlopen(url,timeout=40) as r: b=r.read()
    atomic_bytes(p,b);atomic_json(p.with_suffix(p.suffix+'.meta.json'),{'url':url,'sha256':hashlib.sha256(b).hexdigest()})
    print('saved',name,flush=True);return b
def month(m):
    d=f'2022{m:02d}01';j=json.loads(fetch(f'quotes_{d}.json',f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={d}&stockNo=0050'))
    assert j['stat']=='OK' and j['date']==d and '0050' in j['title']
    assert j['fields'][0]=='日期' and j['fields'][3:7]==['開盤價','最高價','最低價','收盤價']
    rows=[]
    for row in j['data']:
        y,mo,day=map(int,row[0].split('/'));rows.append({'date':f'{y+1911:04d}-{mo:02d}-{day:02d}','symbol':'0050','open':float(row[3].replace(',','')),'close':float(row[6].replace(',',''))})
    return rows
def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: rows=[r for group in pool.map(month,range(1,13)) for r in group]
    p=pd.DataFrame(rows).sort_values('date');assert not p.date.duplicated().any()
    html=fetch('dividends_2022.html','https://www.twse.com.tw/en/ETFortune-institute/dividendList?startDate=2022&endDate=2022&stkNo=0050').decode()
    events=[]
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',html,re.S):
        cells=[re.sub('<[^>]+>','',s).strip() for s in re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S)]
        if cells and cells[0]=='0050':
            assert len(cells)==6 and cells[2].startswith('2022/');events.append((cells[2].replace('/','-'),float(cells[4])))
    assert len(events)==2
    factor=1.;details=[];p['adj_open']=p.open;p['adj_close']=p.close
    for i,row in p.iterrows():
        for date,cash in events:
            if row.date==date:
                prior=p.loc[p.date<date,'close'].iloc[-1];assert prior>cash>0
                factor*=prior/(prior-cash);details.append({'date':date,'prior_close':prior,'cash':cash,'proxy_reference':prior-cash})
        p.loc[i,'adj_open']=row.open*factor;p.loc[i,'adj_close']=row.close*factor
    official=json.loads(Path('deliverables/tpex_2022/calendar_audit.json').read_text());days=sorted(d for m in official['months'] for d in m['dates']);assert list(p.date)==days
    path=ROOT/'prices_adjusted_2022.csv.gz';p.to_csv(path,index=False,compression={'method':'gzip','mtime':0})
    atomic_json(ROOT/'summary.json',{'rows':len(p),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'events':details,'method':'forward theoretical cash-dividend proxy prior_close/(prior_close-cash); not official rounded reference or cash ledger','no_split_evidence':'2022 split audit pending; do not claim complete company-action coverage'})
if __name__=='__main__':main()
