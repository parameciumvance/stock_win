"""Reuse frozen calendar-block diagnostics; never optimize rules."""
from pathlib import Path
import hashlib,json
import pandas as pd
from tpex_ridge_baseline import intervals

def main():
    root=Path('deliverables/tpex_features_2022');config=Path('configs/tpex_ridge_protocol.json');c=json.loads(config.read_text())['paired_uncertainty']
    daily=pd.read_csv(root/'rule_net_relative_daily.csv');calendar=json.loads(Path('deliverables/tpex_2022/calendar_audit.json').read_text());days=sorted(d for m in calendar['months'] for d in m['dates']);rows=[]
    for method,g in daily.groupby('method'):
        for w in [20,60]:
            x=g.set_index('date')[f'strict_net_relative{w}'].reindex(days)
            rows.append({'method':method,'horizon':w,'conditional_mean':float(x.mean()),'known_dates':int(x.notna().sum()),'intervals':{str(block):intervals(x,block,c['replicates'],c['seed']) for block in c['block_lengths']}})
    result={'protocol_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'calendar_positions':len(days),'summary':rows,'limitations':['calendar-position circular bootstrap; unknown windows retained','conditional known-date means, not full-year portfolio return','2022 retrospective research, not new holdout','0050 cash-dividend theoretical proxy; official split audit pending']}
    (root/'uncertainty.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# 2022 上櫃固定規則初步驗證','','不調參；共同完整特徵116,580列，最早2022-04-11。5筆未知事件跨窗遮罩；24筆減資／面額變更之20日成交股數跨單位窗口沒有進入共同池。','','| 方法 | 期間 | 已知日 | 相對0050條件均值 | 60日區塊95%區間 |','|---|---:|---:|---:|---:|']
    for r in rows:
        ci=r['intervals']['60'];lines.append(f"| {r['method']} | {r['horizon']} | {r['known_dates']}/246 | {r['conditional_mean']*100:+.2f}% | {ci['lower_95']*100:+.2f}%～{ci['upper_95']*100:+.2f}% |")
    lines+=['','本表是扣固定成本後的報價代理、重疊日訊號條件均值，不是投資組合累積報酬；未知日期不可推論成已知。0050為246日官方行情與兩次官方現金配息所建之前向理論代理，分割等完整事件核對尚待完成；不能把初步正均值當作穩定優勢。','', '下一步：補2021暖機與跨年端點、核對0050事件完整性，再延伸同一固定規則；2022法人資料已備妥，營收2022-11之前缺少來源，三事件交集仍pending。']
    (root/'review.md').write_text('\n'.join(lines)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
