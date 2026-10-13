"""Year-by-year circular-block diagnostics using the frozen uncertainty configuration."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from tpex_ridge_baseline import intervals

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();root=Path(a.root)
 config=Path('configs/tpex_ridge_protocol.json');protocol=json.loads(config.read_text());c=protocol['paired_uncertainty']
 daily=pd.read_csv(root/'rule_net_relative_daily.csv');rows=[]
 for year in sorted(daily.date.str[:4].astype(int).unique()):
  calendar=json.loads(Path(f'deliverables/tpex_{year}/calendar_audit.json').read_text());days=[d for m in calendar['months'] for d in m['dates']]
  subset=daily[daily.date.str.startswith(str(year))]
  for method,g in subset.groupby('method'):
   if g.date.duplicated().any():raise ValueError('Duplicate method/date')
   for horizon in protocol['horizons']:
    x=g.set_index('date')[f'strict_net_relative{horizon}'].reindex(days)
    mean=float(x.mean()) if x.notna().any() else None
    rows.append(dict(signal_year=int(year),method=method,horizon=horizon,conditional_mean=mean,known_dates=int(x.notna().sum()),calendar_positions=len(days),intervals={str(b):intervals(x,b,c['replicates'],c['seed']) for b in c['block_lengths']}))
 result=dict(protocol_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),daily_sha256=hashlib.sha256((root/'rule_net_relative_daily.csv').read_bytes()).hexdigest(),block_lengths=c['block_lengths'],replicates=c['replicates'],seed=c['seed'],summary=rows,limitations=['Known-date conditional means, not portfolio returns','Calendar-position resampling preserves unknown/absent signals; no zero filling','Historical years already inspected; no untouched holdout or parameter search'])
 (root/'long_uncertainty.json').write_text(json.dumps(result,indent=2)+'\n')
 lines=['# 2015–2022 固定規則：成本後相對0050代理與區塊診斷','','2023僅供進出場端點，不列為本輪評估年。沿用既有成本、規則與20／60／80日區塊，5000次、固定種子20261010。','','| 年 | 方法 | 期間 | 已知日／全年市場日 | 條件平均相對報酬 | 60日區塊95%區間 |','|---|---|---:|---:|---:|---|']
 for r in rows:
  value='未知' if r['conditional_mean'] is None else f"{r['conditional_mean']*100:+.2f}%"
  ci=r['intervals']['60'];label=f"{ci['lower_95']*100:+.2f}%～{ci['upper_95']*100:+.2f}%" if 'lower_95' in ci else '已知日不足'
  lines.append(f"| {r['signal_year']} | {r['method']} | {r['horizon']} | {r['known_dates']}/{r['calendar_positions']} | {value} | {label} |")
 replay_path=root/'endpoint_event_replay.json';replayed=replay_path.exists() and json.loads(replay_path.read_text()).get('raw_event_replay_passed') is True
 evidence='2023原始事件已重播，六項影響特徵的欄位與固定報告逐筆一致。' if replayed else '2023事件使用固定Git驗收報告並重新核對跨年前收，本輪未播放其原始事件回應。'
 lines+=['','價格為官方參考價前向倍率代理，不是股東現金帳或成交回測；單邊手續費0.1425%、賣出稅0.3%、單邊滑價0.5%，0050比較基準未扣ETF成本。任何選中標籤未知，當日整組嚴格均值即未知；上表只描述剩餘已知日期。重疊日訊號均值不是年報酬率或NAV。','', evidence+'股票分類為回溯證據，候選保留。全段歷史已進入研究，不能稱獨立留出。']
 (root/'long_review.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'groups':len(rows),'known_complete_group_means':sum(r['conditional_mean'] is not None for r in rows)}))
if __name__=='__main__':main()
