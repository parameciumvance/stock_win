"""Build a continuous 0050 forward-reference proxy from hash-pinned TWSE archives."""
import argparse,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from twse_history.build_history import load_actions,adjust_prices,audit_events
from research_runtime import atomic_bytes,atomic_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--source-root',required=True);p.add_argument('--output',default='deliverables/benchmark_long_history');a=p.parse_args()
 root=Path(a.output);raw=root/'raw';raw.mkdir(parents=True,exist_ok=True)
 expected={x['local_name']:x for x in json.loads(Path('configs/twse_benchmark_input_checksums.json').read_text())}
 quotes=[];actions=[];source_reports=[];cutoff=pd.Timestamp('2023-12-31')
 for year in range(2015,2024):
  name=f'twse_raw_{year}.zip';matches=list(Path(a.source_root).rglob(name))
  if len(matches)!=1:raise ValueError('Ambiguous or absent archive '+name)
  archive=matches[0];h=hashlib.sha256(archive.read_bytes()).hexdigest()
  if h!=expected[name]['sha256'] or archive.stat().st_size!=expected[name]['bytes']:raise ValueError('Archive hash/size mismatch '+name)
  with zipfile.ZipFile(archive) as z:
   if z.testzip() is not None:raise ValueError('ZIP CRC failure '+name)
   count=0
   if 'SHA256MANIFEST.json' in z.namelist():
    manifest=json.loads(z.read('SHA256MANIFEST.json'))
    for item in manifest:
     body=z.read(item['path'])
     if len(body)!=item['bytes'] or hashlib.sha256(body).hexdigest()!=item['sha256']:raise ValueError('Manifest mismatch '+item['path'])
     count+=1
   qname=f'quotes_twse_{year}.csv.gz';qbytes=z.read('inputs/'+qname)
   if hashlib.sha256(qbytes).hexdigest()!=expected[qname]['sha256']:raise ValueError('Quote hash mismatch '+qname)
   frame=pd.read_csv(io.BytesIO(qbytes),compression='gzip',dtype={'symbol':str},parse_dates=['date']);frame=frame[frame.symbol.eq('0050')].copy()
   if not frame.date.dt.year.eq(year).all() or frame.date.duplicated().any():raise ValueError('Wrong-year/duplicate benchmark quotes')
   if frame[['open','high','low','close']].isna().any().any() or (frame[['open','high','low','close']]<=0).any().any():raise ValueError('Unknown benchmark OHLC')
   for kind in ('exrights','reduction','par_change','split'):
    for suffix in ('.json','.meta.json'):
     n=f'twse_history/raw/{kind}_{year}{suffix}';atomic_bytes(raw/Path(n).name,z.read(n))
    data=raw/f'{kind}_{year}.json';meta=json.loads(data.with_suffix('.meta.json').read_text())
    if hashlib.sha256(data.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('Action metadata mismatch')
   if year<=2022:
    calendar=json.loads(Path(f'deliverables/tpex_{year}/calendar_audit.json').read_text());days=[d for m in calendar['months'] for d in m['dates']]
    if list(frame.date.dt.strftime('%Y-%m-%d'))!=days:raise ValueError('TWSE benchmark / TPEx calendar mismatch')
   annual=load_actions(raw,year,cutoff);annual=annual[annual.symbol.eq('0050')].copy()
   quotes.append(frame);actions.append(annual)
   source_reports.append(dict(year=year,archive_sha256=h,quote_sha256=expected[qname]['sha256'],rows=len(frame),events=len(annual),manifest_files_verified=count,manifest_limit='2023 archive has no manifest; archive SHA/CRC plus needed quote/action source hashes verified' if count==0 else 'full manifest verified'))
 q=pd.concat(quotes,ignore_index=True).sort_values('date');events=pd.concat(actions,ignore_index=True).sort_values('effective_date')
 if q.date.duplicated().any():raise ValueError('Crossyear duplicate dates')
 prices=adjust_prices(q,events,cutoff);audit=audit_events(prices,events)
 if not audit.audit_state.eq('matched').all():raise ValueError('Unverified benchmark action')
 # Only causal columns are exported. Future action factors cannot change a prior prefix.
 prefix=adjust_prices(q[q.date<='2021-12-31'],events,pd.Timestamp('2021-12-31'))
 full=prices[prices.date<='2021-12-31'];np.testing.assert_allclose(prefix.adj_close,full.adj_close,rtol=1e-13,atol=1e-13)
 columns=['date','symbol','open','high','low','close','causal_factor','adj_open','adj_high','adj_low','adj_close'];path=root/'prices_adjusted_2015_2023.csv.gz'
 prices[columns].to_csv(path,index=False,compression={'method':'gzip','mtime':0})
 saved=pd.read_csv(path,dtype={'symbol':str},parse_dates=['date']);pd.testing.assert_frame_equal(saved,prices[columns],check_dtype=False,check_exact=False,rtol=1e-12)
 audit.to_csv(root/'event_audit.csv',index=False)
 summary=dict(start_year=2015,end_year=2023,rows=len(prices),events=len(events),date_start=str(prices.date.min().date()),date_end=str(prices.date.max().date()),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source_reports=source_reports,event_states=audit.audit_state.value_counts().to_dict(),prefix_invariance_passed=True,calendar_2015_2022_exact=True,method='Frozen TWSE build_history.adjust_prices forward official-reference factors, common scale across years; causal columns only',limitations=['Proxy is not shareholder cash ledger or execution return','Historical sources retrieved later; original announcement-time snapshots not established','2023 used as potential endpoint context, not a new untouched holdout'])
 atomic_json(root/'summary.json',summary);print(json.dumps(summary))
if __name__=='__main__':main()
