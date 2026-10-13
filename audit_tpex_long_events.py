"""Frozen absolute and paired uncertainty report for long-history event rules."""
import json
from pathlib import Path
import pandas as pd
from tpex_ridge_baseline import intervals
from tpex_event_comparison import atomic_json,file_sha

def main():
 root=Path('deliverables/tpex_long_events');m=json.loads((root/'summary.json').read_text());d=pd.read_csv(root/'daily.csv');rows=[]
 for r in m['summary']:
  calendar=json.loads(Path(f"deliverables/tpex_{r['year']}/calendar_audit.json").read_text());days=[date for month in calendar['months'] for date in month['dates']]
  g=d[(d.year==r['year'])&(d.lag==r['lag'])&(d.horizon==r['horizon'])&(d.method==r['method'])]
  values=g.set_index('date').strict_mean.reindex(days)
  rows.append(dict(r,intervals={str(b):intervals(values,b,5000,20261010) for b in [20,60,80]}))
 atomic_json(root/'absolute_uncertainty.json',dict(daily_sha256=file_sha(root/'daily.csv'),block_lengths=[20,60,80],replicates=5000,seed=20261010,summary=rows))
 replay=json.loads((root/'selection_replay.json').read_text())
 lines=['# 2015～2022 上櫃固定事件規則比較','','採月底後45日延遲代理；60日敏感度另列。營收加速、法人前五市場日均淨買入、突破前60日最高收盤且量大於前20日均量1.5倍，各單獨規則及交集同池比較。成本：單邊手續費0.1425%、賣出稅0.3%、單邊滑價0.5%；0050未扣ETF交易成本。沒有調參或重新訓練模型。','','| 年 | 全條件交集60日相對0050條件均值 | 主要60日區塊95%區間 | 完整已知日／訊號日 | 空選股日 | 60日延遲敏感度均值 |','|---|---:|---|---:|---:|---:|']
 def value(v):return '未知' if v is None else f'{v*100:+.2f}%'
 for r in rows:
  if r['lag']!=45 or r['horizon']!=60 or r['method']!='all_three':continue
  ci=r['intervals']['60'];label=f"{ci['lower_95']*100:+.2f}%～{ci['upper_95']*100:+.2f}%" if 'lower_95' in ci else '已知日不足'
  sensitivity=next(x for x in rows if x['year']==r['year'] and x['lag']==60 and x['horizon']==60 and x['method']=='all_three')
  lines.append(f"| {r['year']} | {value(r['mean_net_relative'])} | {label} | {r['complete_selection_dates']}/{r['dates']} | {r['empty_selection_dates']} | {value(sensitivity['mean_net_relative'])} |")
 lines+=['','全條件交集主要均值僅3／8年為正；原始營收為後來匯出的靜態修訂表，沒有首次公告時刻與完整修正歷史。嚴格當時資訊驗證仍pending。缺法人列不補零；共同池因資料完整要求縮小。任何選中端點未知，整組每日均值即未知；空選股日也不是零報酬。配對區間只使用兩法皆完整已知的日期，不能用兩法各自年度平均直接相減。','','區塊固定20／60／80日、5000次、種子20261010；保留日曆位置及未知值。全段歷史已查看，區間不是獨立留出證據。這是重疊訊號的條件報價代理均值，不是年度投資組合收益、實際成交或NAV。','','## 全方法主要均值','','| 年 | 方法 | 期間 | 平均相對0050代理 | 完整已知日／訊號日 |','|---|---|---:|---:|---:|']
 for r in rows:
  if r['lag']==45:lines.append(f"| {r['year']} | {r['method']} | {r['horizon']} | {value(r['mean_net_relative'])} | {r['complete_selection_dates']}/{r['dates']} |")
 lines+=['',f"逐筆驗收：{replay['selected_rows']:,}筆選股、{replay['daily_values_replayed']:,}組日均值，最大重播差{replay['maximum_absolute_difference']:.3g}；{replay['unknown_daily_values']:,}組未知保留。來源邊界與重複鍵核對通過。",'','## Tasks','','- [x] 早期96個月營收來源、離線重播、400個檔案封存取回驗證。','- [x] 八年法人輸入SHA核對、固定同池事件比較及45／60日敏感度。','- [x] 逐選股時點／未知日均值重播；分年絕對與配對區塊診斷。','- [ ] 等新的市場期間作預先固定規則評估；這段歷史不能當新留出。','- [ ] 嚴格首次公告及修訂歷史、真實停復牌與股東現金帳仍pending。']
 (root/'report.md').write_text('\n'.join(lines)+'\n');print('Reported',len(rows),'year/lag/horizon/method groups')

if __name__=='__main__':main()
