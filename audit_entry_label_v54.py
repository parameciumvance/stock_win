"""Evaluate fixed surge rankings using signal-close and next-open reference prices."""
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd


SCORES=('logistic','hist_gradient_boosting','mom60_skip5','mom20')
TARGETS=('surge_adjusted','surge_next_open')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions',type=Path,
        default=Path('restored_v54/twse_history/output_research_v5/holdout_predictions_2025.csv.gz'))
    p.add_argument('--early',type=Path,default=Path('deliverables/early_temporal_scored_v54.csv.gz'))
    p.add_argument('--features',type=Path,
        default=Path('twse_history/output_research_v5/causal_features_2024_2025.csv.gz'))
    p.add_argument('--source',type=Path,default=Path('twse_history/output_multiyear'))
    p.add_argument('--output',type=Path,default=Path('deliverables'))
    a=p.parse_args()
    pred2025=pd.read_csv(a.predictions,dtype={'symbol':str})
    rules=pd.read_csv(a.features,usecols=['date','symbol','mom60_skip5','mom20'],dtype={'symbol':str})
    pred2025=pred2025.merge(rules,on=['date','symbol'],validate='one_to_one')
    pred2024=pd.read_csv(a.early,dtype={'symbol':str})
    labels=pd.read_csv(a.source/'surge_labels_adjusted_2024_2025.csv.gz',
        usecols=['date','symbol',*TARGETS,'entry_open_next_adj','label_available'],dtype={'symbol':str})
    outputs=[]
    for year,pred,reference in ((2024,pred2024,a.output/'early_temporal_daily_v54.csv'),
                                 (2025,pred2025,a.output/'daily_signal_rule_comparison_v54.csv')):
        merged=pred.merge(labels,on=['date','symbol'],validate='one_to_one',suffixes=('_pred',''),indicator=True)
        if ('surge_adjusted_pred' not in merged or not merged['_merge'].eq('both').all() or
            not merged.surge_adjusted_pred.eq(merged.surge_adjusted).all() or
            not merged.label_available.all() or merged[list(TARGETS)].isna().any().any() or
            not merged.entry_open_next_adj.gt(0).all()):
            raise ValueError(f'{year} label alignment failed')
        if (year==2024 and (len(merged)!=28613 or merged.date.nunique()!=42)) or (
            year==2025 and (len(merged)!=139487 or merged.date.nunique()!=223)):
            raise ValueError('Unexpected dated test population')
        daily=[]
        for date,group in merged.groupby('date',sort=True):
            k=math.ceil(len(group)/10)
            for target in TARGETS:
                row=dict(year=year,date=date,target=target,eligible=len(group),top_n=k,
                         base_rate=group[target].mean())
                for method in SCORES:
                    row[method]=group.nlargest(k,method)[target].mean()
                daily.append(row)
        daily=pd.DataFrame(daily)
        original=daily[daily.target.eq('surge_adjusted')].reset_index(drop=True)
        archived=pd.read_csv(reference).reset_index(drop=True)
        if not original.date.eq(archived.date).all():
            raise ValueError(f'{year} archived dates mismatch')
        for col in ['eligible','top_n','base_rate',*SCORES]:
            if not np.allclose(original[col],archived[col],rtol=0,atol=1e-12):
                raise ValueError(f'{year} archived top-decile mismatch: {col}')
        outputs.append((year,merged,daily))
    days=pd.concat([x[2] for x in outputs],ignore_index=True)
    summary=days.groupby(['year','target'],as_index=False).agg(
        days=('date','nunique'),daily_base_rate=('base_rate','mean'),
        **{name:(name,'mean') for name in SCORES})
    summary['logistic_minus_mom60']=summary.logistic-summary.mom60_skip5
    summary['logistic_minus_mom20']=summary.logistic-summary.mom20
    mismatches={year:dict(disagree=int(merged.surge_adjusted.ne(merged.surge_next_open).sum()),
                           total=len(merged),next_open_positive=int(merged.surge_next_open.sum()))
                for year,merged,_ in outputs}
    a.output.mkdir(parents=True,exist_ok=True)
    days.to_csv(a.output/'entry_label_daily_v54.csv',index=False)
    summary.to_csv(a.output/'entry_label_summary_v54.csv',index=False)
    lines='\n'.join(f'| {r.year} | {"當日收盤" if r.target=="surge_adjusted" else "隔日開盤"} | '
                    f'{r.days} | {r.daily_base_rate:.2%} | {r.logistic:.2%} | '
                    f'{r.mom60_skip5:.2%} | {r.logistic_minus_mom60*100:+.2f} | '
                    f'{r.mom20:.2%} | {r.hist_gradient_boosting:.2%} |'
                    for r in summary.itertuples())
    report=f'''# 飆股標籤的進場基準價敏感性

模型分數、股票池和每日前 10% 名單全部固定；只把標籤的分母，從訊號日調整後收盤價改為**下一交易日調整後開盤價**。兩者都問接下來 20 個市場交易日內的調整後盤中最高價是否至少高 30%；隔日開盤標籤需有有效開盤價。2024 的 42 個日期沿用既有清除重疊訓練標籤的兩折模型分數，2025 的 223 日沿用封存預測。這是標籤定義的回溯敏感性檢查。

## Tasks

- [x] 2024 的 28,613 與 2025 的 139,487 股票日均有有效隔日開盤標籤；訊號日收盤標籤與原封存逐日四種方法數值一致。
- [x] 固定同一批每日 Top 10% 入選股票，比較兩種基準價的正例率與模型－規則差額。
- [ ] 將來在完整實股權益及交易日誌中核查買入開盤價可成交性、隔日停牌／漲跌停、滑價與賣出路徑；此標籤不等同交易獲利。

| 測試段 | 標籤分母 | 日數 | 日均正例率 | Logistic | 60 日去近 5 日動能 | 差額（百分點） | 20 日動能 | 梯度樹 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{lines}

標籤是否翻轉：2024 有 {mismatches[2024]['disagree']:,}/{mismatches[2024]['total']:,} 股票日；2025 有 {mismatches[2025]['disagree']:,}/{mismatches[2025]['total']:,}。隔日開盤只改變事件門檻的參考價格，不代表能在未來區間最高價賣出，也沒有處理公司行動現金流。2024 兩折訓練期短、為事後回溯安排；不能從本分析選較好標籤再宣稱獨立樣本外。

## 下一步規劃

取得 2023 年免費原始資料後，事前固定標籤分母及評估口徑，進行真正跨年度驗證；權利證書與實股 NAV 仍 pending。

重算：`python3 audit_liquidity_screen_v54.py` 產生隔離訓練的 2024 分數；`python3 audit_entry_label_v54.py` 比對兩種標籤。逐日和摘要結果保留 CSV。
'''
    (a.output/'entry_label_report_v54.md').write_text(report)


if __name__=='__main__':
    main()
