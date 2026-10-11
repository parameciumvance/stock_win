"""TPEx historical institutional source pilot with dates and accounting checks."""
from pathlib import Path
import datetime,hashlib,json,urllib.request,urllib.parse
import pandas as pd
ROOT=Path('deliverables/tpex_flow_pilot')
FIELDS=['代號','名稱']+['買進股數','賣出股數','買賣超股數']*7+['三大法人買賣超股數合計']
def parse(doc,date):
 if doc.get('stat')!='ok' or doc.get('date')!=date.replace('-',''):raise ValueError('Wrong source date/status')
 tables=doc['tables'];t=tables[0]
 if not tables or any(extra for extra in tables[1:]) or t['fields']!=FIELDS:raise ValueError('Unexpected institutional schema')
 rows=[];seen=set()
 for r in t['data']:
  if len(r)!=24 or r[0] in seen:raise ValueError('Row width/duplicate')
  seen.add(r[0]);v=[int(s.replace(',','')) for s in r[2:]]
  for i in range(0,21,3):
   if v[i]-v[i+1]!=v[i+2]:raise ValueError('Buy-sell mismatch')
  # Foreign subtotal=foreign excluding dealers+foreign dealers; dealer subtotal=own+hedge.
  for offset in [0,1,2]:
   if v[offset]+v[3+offset]!=v[6+offset] or v[12+offset]+v[15+offset]!=v[18+offset]:raise ValueError('Subtotal mismatch')
  if v[8]+v[11]+v[20]!=v[21]:raise ValueError('Total mismatch')
  rows.append(dict(date=date,code=r[0],name=r[1],foreign_net=v[8],trust_net=v[11],dealer_net=v[20],total_net=v[21]))
 if len(rows)!=t['totalCount']:raise ValueError('Incomplete source count')
 return pd.DataFrame(rows)

def main():
 ROOT.mkdir(exist_ok=True);(ROOT/'raw').mkdir(exist_ok=True);summaries=[]
 for date in ['2023-01-03','2024-01-02','2025-01-02','2026-01-02']:
  url='https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?'+urllib.parse.urlencode(dict(date=date.replace('-','/'),type='Daily',response='json'))
  p=ROOT/'raw'/f'{date}.json';mp=p.with_suffix('.meta.json')
  if p.exists():
   meta=json.loads(mp.read_text());assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']
  else:
   with urllib.request.urlopen(url,timeout=25) as r:payload=r.read()
   doc=json.loads(payload);parse(doc,date);p.write_bytes(payload)
   mp.write_text(json.dumps(dict(url=url,retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(payload).hexdigest()),indent=2)+'\n')
  f=parse(json.loads(p.read_bytes()),date);q=pd.read_csv(f'deliverables/tpex_{date[:4]}/quotes_with_type_{date[:4]}.csv.gz',dtype={'code':str})
  pool=q[q.date.eq(date)&q.primary_pool];codes=set(pool.code);present=codes&set(f.code)
  missing=sorted(codes-set(f.code))
  summaries.append(dict(date=date,source_rows=len(f),asof_primary_pool=len(codes),covered=len(present),coverage=len(present)/len(codes),missing_codes=missing,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
  f.to_csv(ROOT/f'normalized_{date}.csv',index=False);print(summaries[-1],flush=True)
 (ROOT/'summary.json').write_text(json.dumps(dict(samples=summaries,limitation='same-day reports must be lagged to next market day for features; absent security reports remain unknown, not zero; not yet full annual acquisition'),indent=2)+'\n')
if __name__=='__main__':main()
