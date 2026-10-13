"""Frozen 2015-2022 same-pool event rules; no fitting or threshold search."""
import json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from tpex_event_features import institutional_five_days, revenue_acceleration, attach_revenue
from tpex_event_comparison import atomic_csv, atomic_json, file_sha
from tpex_rule_comparison import net_quote, benchmark_labels, strict_mean
from tpex_ridge_baseline import intervals

ROOT=Path('deliverables/tpex_long_events')
FEATURES=['mom1','mom5','mom20','mom60','vol20','atr20_pct','volume_ratio20']

def verified(path,expected):
 if file_sha(path)!=expected:raise ValueError('Input hash mismatch '+str(path))
 return pd.read_csv(path,dtype={'code':str},parse_dates=['date'])

def main():
 ROOT.mkdir(parents=True,exist_ok=True)
 cfg=Path('configs/tpex_event_rules_protocol.json');c=json.loads(cfg.read_text());hashes={str(cfg):file_sha(cfg)}
 fp=Path('deliverables/tpex_features_2015_2023/features_and_gross_labels.csv.gz')
 meta=json.loads(fp.with_name('summary.json').read_text());full=verified(fp,meta['output_sha256']);hashes[str(fp)]=meta['output_sha256']
 days=pd.DatetimeIndex(sorted(full.date.unique()));prices=full[full.date.dt.year.le(2022)].copy();del full
 sources=[]
 for year in range(2015,2023):
  path=Path(f'deliverables/tpex_flow_{year}/institutional_tpex_{year}.csv.gz');m=json.loads(path.with_name('acquisition.json').read_text())
  f=verified(path,m['normalized_sha256']);hashes[str(path)]=m['normalized_sha256']
  if f.date.nunique()!=m['days']:raise ValueError('Source day count mismatch')
  sources.append(f[['date','code','total_net']])
 flow=institutional_five_days(pd.concat(sources,ignore_index=True),days[days.year<=2022]);del sources
 prices=prices.merge(flow,on=['date','code'],how='left',validate='one_to_one');del flow
 monthly=[]
 for directory in ['tpex_revenue_2015_pilot','tpex_revenue_2016_202210','tpex_revenue']:
  path=Path('deliverables')/directory/'monthly.csv.gz';m=json.loads(path.with_name('acquisition.json').read_text())
  if file_sha(path)!=m['sha256']:raise ValueError('Revenue source hash mismatch')
  hashes[str(path)]=m['sha256'];monthly.append(pd.read_csv(path,dtype={'code':str}))
 revenue=revenue_acceleration(pd.concat(monthly,ignore_index=True));del monthly
 bp=Path('deliverables/benchmark_long_history/prices_adjusted_2015_2023.csv.gz');bs=json.loads(bp.with_name('summary.json').read_text())
 if file_sha(bp)!=bs['sha256']:raise ValueError('Benchmark hash mismatch')
 hashes[str(bp)]=bs['sha256'];b=pd.read_csv(bp,parse_dates=['date'])
 for w in c['horizons_market_days']:prices[f'target{w}']=net_quote(prices[f'gross_quote_return{w}'])-prices.date.map(benchmark_labels(b,days,w))
 daily=[];traces=[];coverage=[]
 methods=[m for m in c['methods'] if m!='ridge']
 for lag in c['revenue_proxy_lags_calendar_days']:
  joined=attach_revenue(prices,revenue,days,lag);joined['all_three']=joined[['revenue_acceleration','institutional_five_days','breakout60_volume15']].min(axis=1,skipna=False)
  known=np.isfinite(joined[FEATURES+['revenue_acceleration','institutional_five_days','breakout60_volume15']]).all(axis=1)
  for year,g in joined.groupby(joined.date.dt.year):
   coverage.append(dict(year=int(year),lag=lag,price_rows=len(g),revenue_unknown=int(g.revenue_acceleration.isna().sum()),flow_unknown=int(g.institutional_five_days.isna().sum()),common_rows=int(known.loc[g.index].sum())))
  common=joined[known].copy();del joined
  if not common.flow_source_date.lt(common.date).all():raise ValueError('Flow leakage')
  if not common.proxy_available_date.le(common.date).all():raise ValueError('Revenue leakage')
  for date,g in common.groupby('date'):
   if len(g)<c['min_common_pool']:continue
   for method in methods:
    rule=method in ['revenue_acceleration','institutional_five_days','breakout60_volume15','all_three']
    chosen=g[g[method].eq(1)] if rule else g.sort_values([method,'code'],ascending=[False,True]).head(int(np.ceil(len(g)*c['top_fraction_baselines'])))
    trace=chosen[['date','code','target20','target60','flow_source_date','proxy_available_date','month_end',method]].rename(columns={method:'rule_or_score'}).copy()
    trace['lag']=lag;trace['method']=method;traces.append(trace)
    for w in c['horizons_market_days']:
     target=chosen[f'target{w}'];daily.append(dict(date=date.strftime('%Y-%m-%d'),year=date.year,lag=lag,horizon=w,method=method,common_pool=len(g),selected=len(chosen),unknown_selected=int(target.isna().sum()),strict_mean=strict_mean(target)))
  del common
 d=pd.DataFrame(daily);atomic_csv(d,ROOT/'daily.csv');atomic_csv(pd.concat(traces,ignore_index=True),ROOT/'selections.csv.gz');del traces
 summaries=[];pairs=[]
 for (year,lag,w,method),g in d.groupby(['year','lag','horizon','method']):
  v=g.strict_mean;summaries.append(dict(year=int(year),lag=int(lag),horizon=int(w),method=method,dates=len(g),mean_selected=float(g.selected.mean()),complete_selection_dates=int(v.notna().sum()),empty_selection_dates=int(g.selected.eq(0).sum()),unknown_selected_rows=int(g.unknown_selected.sum()),mean_net_relative=float(v.mean()) if v.notna().any() else None))
 for (year,lag,w),g in d.groupby(['year','lag','horizon']):
  wide=g.pivot(index='date',columns='method',values='strict_mean').reindex(days[days.year==year].strftime('%Y-%m-%d'))
  for method in ['revenue_acceleration','institutional_five_days','breakout60_volume15','all_three']:
   diff=wide[method]-wide.vol20;pairs.append(dict(year=int(year),lag=int(lag),horizon=int(w),comparison=method+'-minus-vol20',mean=float(diff.mean()) if diff.notna().any() else None,known_pairs=int(diff.notna().sum()),intervals={str(block):intervals(diff,block,5000,20261010) for block in [20,60,80]}))
 atomic_json(ROOT/'summary.json',dict(summary=summaries,paired=pairs,coverage=coverage,input_hashes=hashes,output_hashes={name:file_sha(ROOT/name) for name in ['daily.csv','selections.csv.gz']},limitations=['Static revised revenue proxy, not original publication PIT','No early-year frozen Ridge coefficients; seven unfitted rules/baselines only','Same as-of complete pool; no future target filtering','Unknown selected outcome makes whole daily mean unknown','Overlapping conditional means are not portfolio returns; historical data is not untouched holdout']))
 print('Completed',len(d),'daily groups',flush=True)

if __name__=='__main__':main()
