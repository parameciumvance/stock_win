"""Fixed missingness, evidence-tier and paired-date diagnostics; no stock reselection."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from tpex_event_comparison import file_sha
from tpex_ridge_baseline import intervals
from tpex_rule_comparison import strict_mean

def main():
 p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);a=p.parse_args();root=Path('deliverables/tpex_events');s=json.loads((root/f'summary_through_{a.end_year}.json').read_text());audit=json.loads((root/f'verification_through_{a.end_year}.json').read_text());assert audit['all_checks_passed']
 for n,h in s['output_sha256'].items():assert file_sha(n)==h
 path=root/f'common_matrix_through_{a.end_year}.csv.gz';c=pd.read_csv(path,dtype={'code':str},usecols=['date','code','lag','confirmed_subset','gross_quote_return20','gross_quote_return60','target20','target60']);c=c[c.lag.eq(45)].copy();c['year']=c.date.str[:4].astype(int);assert not c.duplicated(['date','code']).any()
 missing=[]
 for y,g in c.groupby('year'):
  for w in [20,60]:missing.append(dict(year=int(y),horizon=w,common_rows=len(g),confirmed_rows=int(g.confirmed_subset.sum()),candidate_rows=int((~g.confirmed_subset).sum()),unknown_gross_stock=int(g[f'gross_quote_return{w}'].isna().sum()),unknown_net_relative=int(g[f'target{w}'].isna().sum()),stock_known_benchmark_unknown=int((g[f'gross_quote_return{w}'].notna()&g[f'target{w}'].isna()).sum())))
 chosen=pd.read_csv(root/f'selections_through_{a.end_year}.csv.gz',dtype={'code':str},usecols=['date','code','lag','horizon','method','target']);chosen=chosen[chosen.lag.eq(45)&chosen.method.eq('all_three')];chosen=chosen.merge(c[['date','code','confirmed_subset']],on=['date','code'],how='left',validate='many_to_one');assert chosen.confirmed_subset.notna().all();chosen['year']=chosen.date.str[:4].astype(int);tiers=[]
 for (y,w),g in chosen.groupby(['year','horizon']):tiers.append(dict(year=int(y),horizon=int(w),selected_rows=len(g),confirmed_rows=int(g.confirmed_subset.sum()),candidate_rows=int((~g.confirmed_subset).sum()),confirmed_selected_only_daily_mean=float(g[g.confirmed_subset].groupby('date').target.apply(strict_mean).mean())))
 d=pd.read_csv(root/f'daily_through_{a.end_year}.csv');d=d[d.lag.eq(45)];paired=[]
 for (y,w),g in d.groupby(['year','horizon']):
  if y<2024:continue
  cal=json.loads(Path(f'deliverables/tpex_{int(y)}/calendar_audit.json').read_text());days=[day for m in cal['months'] for day in m['dates']];wide=g.pivot(index='date',columns='method',values='strict_mean').reindex(days)
  for method in ['vol20','atr20_pct','mom60','ridge']:
   known=np.isfinite(wide.all_three)&np.isfinite(wide[method]);diff=(wide.all_three-wide[method]).where(known)
   paired.append(dict(year=int(y),horizon=int(w),baseline=method,known_pairs=int(known.sum()),intersection_mean=float(wide.loc[known,'all_three'].mean()),baseline_mean=float(wide.loc[known,method].mean()),difference_mean=float(diff.mean()),difference_interval60=intervals(diff,60,5000,20261010)))
 result=dict(end_year=a.end_year,primary_lag=45,input_sha256=s['output_sha256'],missingness=missing,intersection_evidence_tiers=tiers,paired_known_dates=paired,limitations=['diagnostic only; selection rules unchanged','confirmed selected subset is not a re-ranked confirmed-only portfolio','different methods have different selected counts and unknown endpoint patterns','known-date comparisons do not remove nonrandom missingness or constitute portfolio performance'])
 (root/f'sample_health_through_{a.end_year}.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
 lines=['# 固定事件規則樣本健康檢查','','主要45日延遲，不更動規則／排名。只檢查已驗收輸出的缺失端點、證據分級與共同已知評估日。','','| 年 | 期間 | 共同池列 | 規則候選列 | 股票端點未知 | 相對端點未知 | 股票已知但基準未知 |','|---|---:|---:|---:|---:|---:|---:|']
 for r in missing:lines.append(f"| {r['year']} | {r['horizon']} | {r['common_rows']:,} | {r['candidate_rows']:,} | {r['unknown_gross_stock']:,} | {r['unknown_net_relative']:,} | {r['stock_known_benchmark_unknown']:,} |")
 lines+=['','| 年 | 期間 | 三規則交集選中列 | 已核實列 | 規則候選列 |','|---|---:|---:|---:|---:|']
 for r in tiers:lines.append(f"| {r['year']} | {r['horizon']} | {r['selected_rows']} | {r['confirmed_rows']} | {r['candidate_rows']} |")
 lines+=['','| 年 | 期間 | 排序基準 | 共同已知日 | 交集均值 | 基準均值 | 差額 | 差額60日區塊95%區間 |','|---|---:|---|---:|---:|---:|---:|---|']
 for r in paired:
  ci=r['difference_interval60'];bound='資料不足' if 'lower_95' not in ci else f"[{ci['lower_95']*100:+.2f}%, {ci['upper_95']*100:+.2f}%]";lines.append(f"| {r['year']} | {r['horizon']} | {r['baseline']} | {r['known_pairs']} | {r['intersection_mean']*100:+.2f}% | {r['baseline_mean']*100:+.2f}% | {r['difference_mean']*100:+.2f}% | {bound} |")
 lines+=['','相對排序基準的差額只比較兩者均有完整端點的日期，仍是條件均值、重疊窗口及不等持股數；不能因差額為正就稱有投資優勢。主要跨年報告另列對0050本身的絕對相對區間。','', '來源缺列與端點缺失不補零、不前值填補。已核實股票子集只對原選中股票做證據檢查，沒有重新訓練或重新挑股。']
 (root/f'sample_health_through_{a.end_year}.md').write_text('\n'.join(lines)+'\n');print(dict(end_year=a.end_year,common_rows=len(c),paired_groups=len(paired)))
if __name__=='__main__':main()
