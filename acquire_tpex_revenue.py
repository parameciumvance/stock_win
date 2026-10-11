"""Free retrospective TPEx monthly revenue snapshots, not first announcements."""
from pathlib import Path
import concurrent.futures,datetime,hashlib,json,re,urllib.request
import numpy as np
import pandas as pd
from lxml import html
ROOT=Path('deliverables/tpex_revenue')
def parse(raw,month,kind):
 y,m=map(int,month.split('-'));text=raw.decode('cp950')
 if f'上櫃公司{y-1911}年{m}月份(累計與當月)營業收入統計表' not in text or '單位：千元' not in text:raise ValueError('Wrong month/market/unit')
 if ('全部國內上櫃公司合計' if kind==0 else '全部國外上櫃公司合計') not in text:raise ValueError('Wrong company group')
 export=re.search(r'出表日期[：:]\s*(\d+/\d+/\d+)',text)
 if not export:raise ValueError('Missing snapshot export date')
 rows=[]
 for tr in html.fromstring(text).xpath('//tr'):
  cells=[' '.join(c.text_content().split()) for c in tr.xpath('./td|./th')]
  if not cells or not re.fullmatch(r'\d{4}',cells[0]):continue
  if len(cells)!=11:raise ValueError('Unexpected monthly schema')
  def num(s):return np.nan if s in {'-','--',''} else float(s.replace(',',''))
  rows.append(dict(code=cells[0],name=cells[1],month=month,revenue_thousands=num(cells[2]),previous_month_thousands=num(cells[3]),previous_year_thousands=num(cells[4]),reported_mom_pct=num(cells[5]),reported_yoy_pct=num(cells[6]),source_kind=kind,source_export_date_roc=export[1]))
 f=pd.DataFrame(rows)
 if f.empty or f.code.duplicated().any() or not np.isfinite(f.revenue_thousands).all():raise ValueError('Invalid monthly snapshot')
 return f

def main():
 raw=ROOT/'raw';raw.mkdir(exist_ok=True,parents=True)
 requests=[(str(m),k) for m in pd.period_range('2022-11','2026-07',freq='M') for k in [0,1]]
 def get(item):
  month,kind=item;y,m=map(int,month.split('-'));url=f'https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_{y-1911}_{m}_{kind}.html';p=raw/f'{month}_{kind}.html';mp=p.with_suffix('.meta.json')
  if p.exists():
   meta=json.loads(mp.read_text());payload=p.read_bytes();assert meta['url']==url and hashlib.sha256(payload).hexdigest()==meta['sha256']
  else:
   for attempt in range(2):
    try:
     with urllib.request.urlopen(url,timeout=25) as r:payload=r.read();assert r.url==url
     parse(payload,month,kind);break
    except Exception:
     if attempt:raise
   meta=dict(url=url,retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(payload).hexdigest());mp.write_text(json.dumps(meta,indent=2)+'\n');p.write_bytes(payload)
  f=parse(payload,month,kind);f['snapshot_sha256']=meta['sha256'];return f
 frames=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  for start in range(0,len(requests),2):
   frames.extend(pool.map(get,requests[start:start+2]));i=len(frames)
   if i%10==0 or i==len(requests):print(f'{i}/{len(requests)} snapshots verified',flush=True)
 result=pd.concat(frames,ignore_index=True).sort_values(['month','code']);assert not result.duplicated(['month','code']).any()
 dest=ROOT/'monthly.csv.gz';tmp=ROOT/'monthly.pending.gz';result.to_csv(tmp,index=False,compression={'method':'gzip','mtime':0});restored=pd.read_csv(tmp,dtype={'code':str});pd.testing.assert_frame_equal(restored,result.reset_index(drop=True),check_dtype=False);tmp.replace(dest)
 summary=dict(months=len(requests)//2,source_count=len(requests),rows=len(result),sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),status='retrospective_static_snapshot_not_first_announcement',source_start='2022-11',source_end='2026-07')
 (ROOT/'acquisition.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary,flush=True)
if __name__=='__main__':main()
