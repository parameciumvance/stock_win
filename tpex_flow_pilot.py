"""TPEx historical institutional source pilot with dates and accounting checks."""
from pathlib import Path
import datetime,hashlib,json,urllib.request,urllib.parse
import pandas as pd
ROOT=Path('deliverables/tpex_flow_pilot')
FIELDS=['代號','名稱']+['買進股數','賣出股數','買賣超股數']*7+['三大法人買賣超股數合計']
LEGACY_FIELDS=['代號','名稱','外資及陸資買股數','外資及陸資賣股數','外資及陸資淨買股數','投信買進股數','投信賣股數','投信淨買股數','自營淨買股數','自營商(自行買賣)買股數','自營商(自行買賣)賣股數','自營商(自行買賣)淨買股數','自營商(避險)買股數','自營商(避險)賣股數','自營商(避險)淨買股數','三大法人買賣超股數']
OUTPUT_COLUMNS=['date','code','name','foreign_net','trust_net','dealer_net','total_net']
def source_table(doc,date):
 if doc.get('stat')!='ok' or doc.get('date')!=date.replace('-',''):raise ValueError('Wrong source date/status')
 tables=doc.get('tables')
 if not isinstance(tables,list):raise ValueError('Unexpected institutional tables')
 populated=[t for t in tables if t != {}]
 if len(populated)!=1 or not isinstance(populated[0],dict):raise ValueError('Unexpected institutional schema')
 t=populated[0]
 if t.get('fields') not in [FIELDS,LEGACY_FIELDS]:raise ValueError('Unexpected institutional schema')
 return t

def parse(doc,date):
 t=source_table(doc,date);legacy=t['fields']==LEGACY_FIELDS;rows=[];seen=set()
 for r in t['data']:
  if len(r)!=(16 if legacy else 24) or r[0] in seen:raise ValueError('Row width/duplicate')
  seen.add(r[0]);v=[int(s.replace(',','')) for s in r[2:]]
  if legacy:
   for buy,sell,net in [(0,1,2),(3,4,5),(7,8,9),(10,11,12)]:
    if v[buy]<0 or v[sell]<0 or v[buy]-v[sell]!=v[net]:raise ValueError('Buy-sell mismatch')
   if v[9]+v[12]!=v[6]:raise ValueError('Subtotal mismatch')
   if v[2]+v[5]+v[6]!=v[13]:raise ValueError('Total mismatch')
   foreign,trust,dealer,total=v[2],v[5],v[6],v[13]
  else:
   for i in range(0,21,3):
    if v[i]<0 or v[i+1]<0 or v[i]-v[i+1]!=v[i+2]:raise ValueError('Buy-sell mismatch')
   for offset in [0,1,2]:
    if v[offset]+v[3+offset]!=v[6+offset] or v[12+offset]+v[15+offset]!=v[18+offset]:raise ValueError('Subtotal mismatch')
   if v[8]+v[11]+v[20]!=v[21]:raise ValueError('Total mismatch')
   foreign,trust,dealer,total=v[8],v[11],v[20],v[21]
  rows.append(dict(date=date,code=r[0],name=r[1],foreign_net=foreign,trust_net=trust,dealer_net=dealer,total_net=total))
 if len(rows)!=t['totalCount']:raise ValueError('Incomplete source count')
 return pd.DataFrame(rows,columns=OUTPUT_COLUMNS)

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
