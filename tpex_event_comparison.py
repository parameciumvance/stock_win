"""Frozen same-pool TPEx revenue, institutional and price event comparisons."""
from pathlib import Path
import argparse,hashlib,json,csv,gzip
import numpy as np
import pandas as pd
from tpex_event_features import institutional_five_days,revenue_acceleration,attach_revenue
from tpex_rule_comparison import net_quote,benchmark_labels,strict_mean,EXPECTED
from tpex_ridge_baseline import intervals
ROOT=Path('deliverables/tpex_events')

def file_sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def atomic_csv(frame,path):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name(path.name+'.pending');compressed=path.name.endswith('.gz')
 frame.to_csv(temp,index=False,compression={'method':'gzip','mtime':0} if compressed else None)
 opener=gzip.open if compressed else open
 with opener(temp,'rt',encoding='utf-8',newline='') as stream:
  rows=sum(1 for _ in csv.reader(stream))-1
 if rows!=len(frame):raise ValueError('Closed CSV row count differs: '+str(path))
 temp.replace(path)

def atomic_json(path,value):
 path=Path(path);temp=path.with_name(path.name+'.pending')
 temp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
 temp.replace(path)

def main():
 p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);a=p.parse_args()
 ROOT.mkdir(exist_ok=True);state=ROOT/f'run_state_through_{a.end_year}.json';atomic_json(state,dict(status='running',end_year=a.end_year));cfg=Path('configs/tpex_event_rules_protocol.json');c=json.loads(cfg.read_text());hashes={str(cfg):hashlib.sha256(cfg.read_bytes()).hexdigest()}
 fp=Path('deliverables/tpex_features/features_and_gross_labels.csv.gz');assert hashlib.sha256(fp.read_bytes()).hexdigest()==json.loads(Path('deliverables/tpex_features/summary.json').read_text())['output_sha256'];hashes[str(fp)]=hashlib.sha256(fp.read_bytes()).hexdigest()
 full=pd.read_csv(fp,dtype={'code':str},parse_dates=['date']);days=pd.DatetimeIndex(sorted(full.date.unique()));prices=full[full.date.dt.year.le(a.end_year)].copy();del full
 sources=[]
 for y in range(2023,a.end_year+1):
  p=Path(f'deliverables/tpex_flow_{y}/institutional_tpex_{y}.csv.gz');m=json.loads(p.with_name('acquisition.json').read_text());assert hashlib.sha256(p.read_bytes()).hexdigest()==m['normalized_sha256'];hashes[str(p)]=m['normalized_sha256'];f=pd.read_csv(p,dtype={'code':str},parse_dates=['date']);assert f.date.nunique()==m['days'];sources.append(f)
 flows=institutional_five_days(pd.concat(sources,ignore_index=True),days[days.year<=a.end_year]);prices=prices.merge(flows,on=['date','code'],how='left',validate='one_to_one');del flows,sources
 rp=Path('deliverables/tpex_revenue/monthly.csv.gz');ra=json.loads(rp.with_name('acquisition.json').read_text());assert hashlib.sha256(rp.read_bytes()).hexdigest()==ra['sha256'];hashes[str(rp)]=ra['sha256'];monthly=revenue_acceleration(pd.read_csv(rp,dtype={'code':str}))
 bp=Path('benchmark_restore/prices_adjusted_2023_2026.csv.gz');assert hashlib.sha256(bp.read_bytes()).hexdigest()==EXPECTED;hashes[str(bp)]=EXPECTED
 b=pd.read_csv(bp,usecols=['date','symbol','adj_open','adj_close'],dtype={'symbol':str},parse_dates=['date']);b=b[b.symbol.eq('0050')]
 for w in [20,60]:prices[f'target{w}']=net_quote(prices[f'gross_quote_return{w}'])-prices.date.map(benchmark_labels(b,days,w))
 mp=Path('deliverables/tpex_features/ridge_summary.json');modeldata=json.loads(mp.read_text());assert modeldata['feature_sha256']==hashes[str(fp)] and modeldata['benchmark_sha256']==EXPECTED;hashes[str(mp)]=hashlib.sha256(mp.read_bytes()).hexdigest();models={(m['year'],m['horizon']):m for m in modeldata['models']};cols=models[(2024,20)]['features'];daily=[];selections=[];matrices=[]
 for lag in c['revenue_proxy_lags_calendar_days']:
  joined=attach_revenue(prices,monthly,days,lag);joined['all_three']=joined[['revenue_acceleration','institutional_five_days','breakout60_volume15']].min(axis=1,skipna=False)
  mask=np.isfinite(joined[cols+['revenue_acceleration','institutional_five_days','breakout60_volume15']]).all(axis=1);common=joined[mask].copy();common['lag']=lag;matrices.append(common)
  if not common.flow_source_date.lt(common.date).all():raise ValueError('Institutional leakage')
  for (year,date),g in common.groupby([common.date.dt.year,'date']):
   if len(g)<100:continue
   for w in [20,60]:
    g=g.copy();m=models.get((int(year),w))
    if m:g['ridge']=((g[cols].to_numpy()-np.array(m['mean']))/np.array(m['scale']))@np.array(m['coefficient'])+m['intercept']
    for method in c['methods']:
     if method=='ridge' and m is None:continue
     rule=method in ['revenue_acceleration','institutional_five_days','breakout60_volume15','all_three']
     chosen=g[g[method].eq(1)] if rule else g.sort_values([method,'code'],ascending=[False,True]).head(int(np.ceil(len(g)*.1)))
     target=chosen[f'target{w}'];daily.append(dict(date=date.strftime('%Y-%m-%d'),year=int(year),lag=lag,horizon=w,method=method,common_pool=len(g),selected=len(chosen),unknown_selected=int(target.isna().sum()),strict_mean=strict_mean(target)))
     selections.append(chosen[['date','code',f'target{w}',method,'flow_source_date','proxy_available_date','month_end']].rename(columns={f'target{w}':'target',method:'rule_or_score'}).assign(horizon=w,method=method,lag=lag))
 d=pd.DataFrame(daily);atomic_csv(d,ROOT/f'daily_through_{a.end_year}.csv');selection_rows=sum(len(s) for s in selections);atomic_csv(pd.concat(selections,ignore_index=True),ROOT/f'selections_through_{a.end_year}.csv.gz');del selections
 common_rows=sum(len(m) for m in matrices);atomic_csv(pd.concat(matrices,ignore_index=True),ROOT/f'common_matrix_through_{a.end_year}.csv.gz');del matrices
 summaries=[];pairs=[]
 for (year,lag,w,method),g in d.groupby(['year','lag','horizon','method']):
  v=g.strict_mean;summaries.append(dict(year=int(year),lag=int(lag),horizon=int(w),method=method,dates=len(g),mean_selected=float(g.selected.mean()),median_selected=float(g.selected.median()),complete_selection_dates=int(v.notna().sum()),empty_selection_dates=int(g.selected.eq(0).sum()),unknown_selected_rows=int(g.unknown_selected.sum()),mean_net_relative=float(v.mean()) if v.notna().any() else None))
 for (year,lag,w),g in d.groupby(['year','lag','horizon']):
  wide=g.pivot(index='date',columns='method',values='strict_mean').reindex(days[days.year==year].strftime('%Y-%m-%d'))
  for method in ['revenue_acceleration','institutional_five_days','breakout60_volume15','all_three']:
   diff=wide[method]-wide.vol20;pairs.append(dict(year=int(year),lag=int(lag),horizon=int(w),comparison=method+'-minus-vol20',mean=float(diff.mean()) if diff.notna().any() else None,known_pairs=int(diff.notna().sum()),intervals={str(block):intervals(diff,block,5000,20261010) for block in [20,60,80]}))
 output_paths=[ROOT/f'daily_through_{a.end_year}.csv',ROOT/f'selections_through_{a.end_year}.csv.gz',ROOT/f'common_matrix_through_{a.end_year}.csv.gz']
 result=dict(end_year=a.end_year,output_sha256={str(p):file_sha(p) for p in output_paths},output_counts=dict(daily=len(d),selection=selection_rows,common=common_rows),input_hashes=hashes,summary=summaries,paired=pairs,limitations=['same as-of feature-complete subset only; institutional coverage lower than price pool','45/60-day retrospective revenue proxy, not original-publication PIT','2023 exploratory rule diagnostics without trained Ridge; 2024-26 reuse previously frozen Ridge coefficients','missing selected endpoints make whole selection unknown','daily overlapping-window means are not portfolio performance'])
 atomic_json(ROOT/f'summary_through_{a.end_year}.json',result)
 lines=['# 上櫃固定事件規則比較','','45日為主要營收延遲代理；60日敏感度另列JSON。所有方法在同一當時特徵完整子池比較，不按未來結果排除。法人來源日嚴格落後訊號日；缺列不補零。','','| 年 | 期間 | 方法 | 完整已知日／訊號日 | 平均檔數 | 空選股日 | 未知選中筆 | 平均相對代理 |','|---|---:|---|---:|---:|---:|---:|---:|']
 for r in summaries:
  if r['lag']!=45:continue
  v=f"{r['mean_net_relative']*100:+.2f}%" if r['mean_net_relative'] is not None else '未知'
  lines.append(f"| {r['year']} | {r['horizon']} | {r['method']} | {r['complete_selection_dates']}/{r['dates']} | {r['mean_selected']:.2f} | {r['empty_selection_dates']} | {r['unknown_selected_rows']} | {v} |")
 lines+=['','區塊配對結果、完整來源雜湊及未知數見 summary JSON。仍是重疊窗口報價代理、修訂靜態營收；沒有實際成交或嚴格公告PIT。此資料並非新獨立留出。']
 (ROOT/f'report_through_{a.end_year}.md').write_text('\n'.join(lines)+'\n');atomic_json(state,dict(status='complete',end_year=a.end_year,output_sha256=result['output_sha256']));print(dict(end_year=a.end_year,daily_rows=len(d),common_rows=common_rows),flush=True)
if __name__=='__main__':main()
