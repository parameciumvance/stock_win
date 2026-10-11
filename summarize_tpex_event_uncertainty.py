"""Absolute net-relative uncertainty on the frozen event outputs; no selection changes."""
import argparse,hashlib,json
from pathlib import Path
import pandas as pd
from tpex_ridge_baseline import intervals

def main():
 p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);a=p.parse_args();root=Path('deliverables/tpex_events');path=root/f'daily_through_{a.end_year}.csv';d=pd.read_csv(path,parse_dates=['date']);rows=[]
 for (year,lag,w,method),g in d.groupby(['year','lag','horizon','method']):
  calendar=json.loads(Path(f'deliverables/tpex_{year}/calendar_audit.json').read_text());days=pd.DatetimeIndex([day for m in calendar['months'] for day in m['dates']]);v=g.set_index('date').strict_mean.reindex(days)
  rows.append(dict(year=int(year),lag=int(lag),horizon=int(w),method=method,known_dates=int(v.notna().sum()),mean=float(v.mean()) if v.notna().any() else None,intervals={str(b):intervals(v,b,5000,20261010) for b in [20,60,80]}))
 result=dict(input_daily_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),replicates=5000,seed=20261010,blocks=[20,60,80],primary_block=60,summary=rows,limitations='Conditional known-date quote means; calendar gaps retained in circular resampling; already researched years; multiple planned comparisons, not portfolio alpha proof')
 (root/f'absolute_uncertainty_through_{a.end_year}.json').write_text(json.dumps(result,indent=2)+'\n')
 lines=['# 事件規則對0050之絕對相對代理區間','','主要45日營收延遲，完整已知選股日均值；60日區塊為主。不是相對較差波動策略的改善，而是直接檢查扣成本股票報價是否優於原0050口徑。','','| 年 | 期間 | 方法 | 已知日 | 平均相對代理（%） | 60日區塊95%區間（%） |','|---|---:|---|---:|---:|---|']
 for r in rows:
  if r['lag']!=45:continue
  ci=r['intervals']['60'];interval=f"[{ci['lower_95']*100:+.2f}, {ci['upper_95']*100:+.2f}]" if 'lower_95' in ci else '已知日不足';mean=f"{r['mean']*100:+.2f}" if r['mean'] is not None else '未知'
  lines.append(f"| {r['year']} | {r['horizon']} | {r['method']} | {r['known_dates']} | {mean} | {interval} |")
 lines+=['','完整市場日位置抽區塊，未知日期維持NaN；區間仍只反映可觀測日期條件均值，缺失若非隨機不能推論完整母體。多個事前規則與期間同時比較，沒有宣稱校正後顯著性。','', '營收為修訂靜態代理，端點均值高度重疊；不能相乘為組合報酬，沒有實際成交或精確現金帳。']
 (root/f'absolute_uncertainty_through_{a.end_year}.md').write_text('\n'.join(lines)+'\n');print(dict(end_year=a.end_year,groups=len(rows)))
if __name__=='__main__':main()
