"""Resumable TPEx institutional daily reports, verified against official calendar."""
import argparse,datetime,hashlib,json,urllib.parse,urllib.request,concurrent.futures
from pathlib import Path
import pandas as pd
from tpex_flow_pilot import parse

def main():
 p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);a=p.parse_args();root=Path(f'deliverables/tpex_flow_{a.year}');raw=root/'raw';raw.mkdir(parents=True,exist_ok=True)
 calendar=Path(f'deliverables/tpex_{a.year}/calendar_audit.json');days=[d for m in json.loads(calendar.read_text())['months'] for d in m['dates']]
 def get(date):
  path=raw/f'{date}.json';mp=path.with_suffix('.meta.json');url='https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?'+urllib.parse.urlencode(dict(date=date.replace('-','/'),type='Daily',response='json'))
  if path.exists():
   meta=json.loads(mp.read_text());assert meta['url']==url and hashlib.sha256(path.read_bytes()).hexdigest()==meta['sha256'];return parse(json.loads(path.read_bytes()),date)
  sample=Path(f'deliverables/tpex_flow_pilot/raw/{date}.json')
  if sample.exists():
   payload=sample.read_bytes();meta=json.loads(sample.with_suffix('.meta.json').read_text());assert hashlib.sha256(payload).hexdigest()==meta['sha256']
  else:
   for attempt in range(2):
    try:
     with urllib.request.urlopen(url,timeout=25) as response:payload=response.read()
     parse(json.loads(payload),date);break
    except Exception:
     if attempt:raise
   meta=dict(url=url,retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(payload).hexdigest())
  frame=parse(json.loads(payload),date)
  mp.write_text(json.dumps(meta,indent=2)+'\n');temp=path.with_suffix('.pending.json');temp.write_bytes(payload);temp.replace(path)
  return frame
 frames=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  for start in range(0,len(days),2):
   batch=list(pool.map(get,days[start:start+2]));frames.extend(batch)
   i=len(frames)
   if i%10==0 or i==len(days):print(f'{a.year}: {i}/{len(days)} dates verified',flush=True)
 result=pd.concat(frames,ignore_index=True);assert not result.duplicated(['date','code']).any();assert sorted(result.date.unique())==days
 dest=root/f'institutional_tpex_{a.year}.csv.gz';temp=root/'normalized.pending.gz';result.to_csv(temp,index=False,compression={'method':'gzip','mtime':0})
 restored=pd.read_csv(temp,dtype={'code':str});pd.testing.assert_frame_equal(restored,result,check_dtype=False);temp.replace(dest)
 q=pd.read_csv(f'deliverables/tpex_{a.year}/quotes_with_type_{a.year}.csv.gz',dtype={'code':str});q=q[q.primary_pool]
 coverage=q[['date','code']].merge(result[['date','code']],on=['date','code'],how='left',indicator=True,validate='one_to_one');cov=coverage.assign(present=coverage._merge.eq('both')).groupby('date').present.agg(['size','sum','mean']);cov.to_csv(root/'coverage.csv')
 summary=dict(year=a.year,date_start=days[0],date_end=days[-1],coverage_type='partial_year_asof' if days[-1][5:7]!='12' else 'full_year',days=len(days),rows=len(result),covered_primary_rows=int(cov['sum'].sum()),primary_rows=len(q),mean_daily_coverage=float(cov['mean'].mean()),normalized_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),calendar_sha256=hashlib.sha256(calendar.read_bytes()).hexdigest(),limitation='Absent report row remains unknown; institutional report source day must precede signal day; historical revised snapshot not original publication time')
 (root/'acquisition.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary,flush=True)
if __name__=='__main__':main()
