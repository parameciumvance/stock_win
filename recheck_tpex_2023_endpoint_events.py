"""Recheck pinned 2023 event-report values against frozen crossyear quotes."""
import bisect,hashlib,json
from pathlib import Path
import pandas as pd
from research_runtime import atomic_json

def main():
 source=Path('deliverables/tpex_2023/event_coverage.json');doc=json.loads(source.read_text());frames=[];hashes={}
 for y in (2022,2023):
  p=Path(f'deliverables/tpex_{y}/quotes_with_type_{y}.csv.gz');h=hashlib.sha256(p.read_bytes()).hexdigest()
  if h!=json.loads(p.with_name('annual_verification.json').read_text())['output_sha256']:raise ValueError('Quote input drift')
  frames.append(pd.read_csv(p,dtype={'code':str,'date':str}));hashes[str(p)]=h
 q=pd.concat(frames);q['numeric_close']=pd.to_numeric(q.close.astype(str).str.replace(',','',regex=False),errors='coerce')
 prices={(r.date,r.code):r.numeric_close for r in q.itertuples() if pd.notna(r.numeric_close)};days=sorted(q.date.unique())
 for e in doc['records']:
  i=bisect.bisect_left(days,e['event_date']);before=next(((d,prices[(d,e['code'])]) for d in reversed(days[:i]) if (d,e['code']) in prices),None)
  status='last_close_matches' if before and before[1]==e['official_last_close'] else ('missing_prior_quote' if before is None else 'last_close_mismatch')
  if e['event_date'] not in days:status='event_date_outside_market_calendar'
  if status!=e['status']:raise ValueError('Pinned event status changed: '+e['code']+' '+e['event_date'])
 doc['summary']['prior_year_source_hashes']=hashes
 doc['summary']['pinned_report_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
 doc['summary']['evidence_boundary']='Pinned Git event report rechecked against 2022-2023 quote bytes; raw 2023 event responses were not replayed in this run'
 out=Path('deliverables/tpex_bridge_long_history_2023');out.mkdir(exist_ok=True)
 atomic_json(out/'event_coverage.json',doc);atomic_json(out/'event_coverage_summary.json',doc['summary']);print('1029 pinned 2023 report records rechecked; no status changes')
if __name__=='__main__':main()
