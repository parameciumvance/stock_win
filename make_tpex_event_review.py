"""Summarize replay-verified frozen TPEx rules without selecting new parameters."""
import argparse,json
from pathlib import Path
from tpex_event_comparison import file_sha

def main():
 p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);a=p.parse_args();root=Path('deliverables/tpex_events')
 result=json.loads((root/f'summary_through_{a.end_year}.json').read_text());audit=json.loads((root/f'verification_through_{a.end_year}.json').read_text());uncertainty=json.loads((root/f'absolute_uncertainty_through_{a.end_year}.json').read_text())
 assert audit['all_checks_passed'] and audit['common_rows']==result['output_counts']['common'] and audit['selection_rows']==result['output_counts']['selection']
 assert uncertainty['input_daily_sha256']==file_sha(root/f'daily_through_{a.end_year}.csv')
 for n,h in result['output_sha256'].items():assert file_sha(n)==h
 intervals={(r['year'],r['lag'],r['horizon'],r['method']):r for r in uncertainty['summary']}
 lines=['# 上櫃固定事件規則跨年研究總結','','目的：檢查營收加速、前五市場日連續法人買超、價格帶量突破及三者交集，是否比既有波動／動能／量價Ridge基準有較好的扣成本報價代理。沒有新模型調參或門檻搜尋。','','## 資料與驗收','','| 年 | 法人來源日 | 法人全證券筆數 | 普通股探索池覆蓋 |','|---|---:|---:|---:|']
 for y in range(2023,a.end_year+1):
  s=json.loads(Path(f'deliverables/tpex_flow_{y}/acquisition.json').read_text());lines.append(f"| {y} | {s['days']} | {s['rows']:,} | {s['mean_daily_coverage']*100:.2f}% |")
 lines+=['',f"共同池 {audit['common_rows']:,} 列、選股 {audit['selection_rows']:,} 列、每日組合 {audit['daily_groups']:,} 組已逐筆重播。2026截止2026-10-02，並非全年；截至日後的20／60日端點未知。2023是探索規則檢查，尚沒有Ridge年度評估。",'','## 主要45日營收延遲代理','','| 年 | 市場日期間 | 方法 | 完整已知日／訊號日 | 平均選股數 | 相對0050均值 | 60日區塊95%區間 |','|---|---:|---|---:|---:|---:|---|']
 def row(r):
  mean='未知' if r['mean_net_relative'] is None else f"{r['mean_net_relative']*100:+.2f}%"
  ci=intervals[(r['year'],r['lag'],r['horizon'],r['method'])]['intervals']['60'];bounds='資料不足' if 'lower_95' not in ci else f"[{ci['lower_95']*100:+.2f}%, {ci['upper_95']*100:+.2f}%]"
  return f"| {r['year']} | {r['horizon']} | {r['method']} | {r['complete_selection_dates']}/{r['dates']} | {r['mean_selected']:.2f} | {mean} | {bounds} |"
 for r in result['summary']:
  if r['lag']==45 and r['year']>=2024:lines.append(row(r))
 lines+=['','## 三規則交集的延遲敏感度','','| 延遲 | 年 | 市場日期間 | 方法 | 完整已知日／訊號日 | 平均選股數 | 相對0050均值 | 60日區塊95%區間 |','|---:|---|---:|---|---:|---:|---:|---|']
 for r in result['summary']:
  if r['method']=='all_three' and r['year']>=2024:lines.append('| '+str(r['lag'])+' '+row(r))
 lines+=['','## 如何解讀與下一步','','所有方法用同日特徵完整共同池，不按未來端點是否已知篩股。事件規則選全部正例，排序基準選前10%，持股數並不相同；這不是等持股数的組合實驗。任一選中股票端點未知，整日選股均值維持未知。','','數字為完整已知選股日的重疊20／60日報價均值，股票扣既有成本後減原0050毛報酬口徑；不能相乘成策略年報酬、勝率或30萬元實際帳戶損益。區間按完整市場日位置循環抽20／60／80日區塊、5000次固定種子，未知日期保留；它只反映已知日期條件均值，未校正多重比較。','','相對波動基準改善不等於勝過0050。即使單年平均為正，也不足以證明跨年可交易優勢；各年度已被研究過，不稱全新留出。營收是修訂靜態快照加45／60日延遲代理，不是原始公告PIT。法人缺列不補零，使用日前五個市場日。精確公司行動現金帳與成交可得性尚未完成。','','下一步先按已凍結規則做樣本／期間與來源健康分析，保留價格、營收、法人的失效證據；沒有證據前不扩大調參或進入實單。新增方向需另立研究假說與驗證期間。']
 (root/f'crossyear_review_through_{a.end_year}.md').write_text('\n'.join(lines)+'\n');print({'end_year':a.end_year,'review_written':True})
if __name__=='__main__':main()
