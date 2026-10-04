"""Post-hoc liquidity screen sensitivity on archived 2025 and purged 2024 folds."""
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from early_temporal_stress_v54 import FOLDS, SCORES
from twse_history.research_v5 import FEATURES, training_frame


THRESHOLDS = (10_000_000, 30_000_000, 100_000_000)


def daily_rows(scored, year, fold=None):
    rows=[]
    for date, whole in scored.groupby('date', sort=True):
        for threshold in THRESHOLDS:
            group=whole[whole.turnover20.ge(threshold)]
            if not len(group):
                raise ValueError(f'No eligible stocks at {date} for {threshold}')
            n=math.ceil(len(group)/10)
            row=dict(year=year, fold=fold or '', date=pd.Timestamp(date).strftime('%Y-%m-%d'),
                     min_turnover20_twd=threshold, eligible=len(group), top_n=n,
                     positives=int(group.surge_adjusted.sum()), base_rate=group.surge_adjusted.mean())
            for method in SCORES:
                row[method]=group.nlargest(n,method).surge_adjusted.mean()
            rows.append(row)
    return rows


def verify(daily, reference, year):
    actual=daily[(daily.year.eq(year)) & (daily.min_turnover20_twd.eq(10_000_000))]
    columns=['date','eligible','top_n','base_rate',*SCORES]
    if year==2024:
        columns=['fold',*columns]
    a=actual[columns].reset_index(drop=True)
    b=reference[columns].reset_index(drop=True)
    if len(a)!=len(b) or not a.date.equals(b.date) or not a.eligible.equals(b.eligible):
        raise ValueError(f'{year} original pool mismatch')
    if year==2024 and not a.fold.equals(b.fold):
        raise ValueError('2024 fold mismatch')
    for col in ['top_n','base_rate',*SCORES]:
        if not np.allclose(a[col],b[col],atol=1e-12,rtol=0):
            raise ValueError(f'{year} archived daily mismatch: {col}')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions',type=Path,default=Path('restored_v54/twse_history/output_research_v5/holdout_predictions_2025.csv.gz'))
    p.add_argument('--features',type=Path,default=Path('twse_history/output_research_v5/causal_features_2024_2025.csv.gz'))
    p.add_argument('--source',type=Path,default=Path('twse_history/output_multiyear'))
    p.add_argument('--output',type=Path,default=Path('deliverables'))
    a=p.parse_args()
    features=pd.read_csv(a.features,dtype={'symbol':str},parse_dates=['date'])
    pred=pd.read_csv(a.predictions,dtype={'symbol':str},parse_dates=['date'])
    test2025=pred.merge(features[['date','symbol','turnover20','mom60_skip5','mom20']],
                        on=['date','symbol'],validate='one_to_one')
    if len(test2025)!=139487 or test2025.date.nunique()!=223:
        raise ValueError('Unexpected 2025 population')
    rows=daily_rows(test2025,2025)
    suffix='_2024_2025.csv.gz'
    labels=pd.read_csv(a.source/('surge_labels_adjusted'+suffix),
                       dtype={'symbol':str},parse_dates=['date','label_window_end'])
    roles=pd.read_csv(a.source/('temporal_split'+suffix),
                      dtype={'symbol':str},parse_dates=['date'])
    panel=training_frame(features,labels,roles,[('2429',pd.Timestamp('2024-07-02'))])
    base=panel[panel.role.eq('train_eligible') & panel.signal_eligible &
               panel.label_available & ~panel.quarantined_label]
    scored2024=[]
    for start,stop in FOLDS:
        cutoff=pd.Timestamp(start)
        train=base[base.date.lt(cutoff) & base.label_window_end.lt(cutoff)]
        test=base[base.date.ge(cutoff) & base.date.lt(pd.Timestamp(stop))].copy()
        if not len(test) or train.label_window_end.max()>=test.date.min() or test.label_window_end.ge(pd.Timestamp('2025-01-01')).any():
            raise ValueError('Invalid 2024 purged fold')
        models=dict(logistic=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500)),
            hist_gradient_boosting=HistGradientBoostingClassifier(
                learning_rate=.06,max_iter=100,max_leaf_nodes=15,min_samples_leaf=100,
                l2_regularization=1.,early_stopping=False,random_state=2025))
        for name,model in models.items():
            model.fit(train[FEATURES],train.surge_adjusted.astype(int))
            test[name]=model.predict_proba(test[FEATURES])[:,1]
        scored2024.append(test[['date','symbol','surge_adjusted','turnover20',*SCORES]].assign(fold=start))
        rows.extend(daily_rows(test,2024,start))
    daily=pd.DataFrame(rows).sort_values(['year','date','min_turnover20_twd']).reset_index(drop=True)
    verify(daily,pd.read_csv(a.output/'daily_signal_rule_comparison_v54.csv'),2025)
    verify(daily,pd.read_csv(a.output/'early_temporal_daily_v54.csv'),2024)
    summary=daily.groupby(['year','min_turnover20_twd'],as_index=False).agg(
        days=('date','nunique'),mean_eligible=('eligible','mean'),base_rate=('base_rate','mean'),
        **{name:(name,'mean') for name in SCORES})
    summary['logistic_minus_mom60']=summary.logistic-summary.mom60_skip5
    summary['logistic_minus_mom20']=summary.logistic-summary.mom20
    summary['hgb_minus_mom60']=summary.hist_gradient_boosting-summary.mom60_skip5
    a.output.mkdir(parents=True,exist_ok=True)
    daily.to_csv(a.output/'liquidity_screen_daily_v54.csv',index=False)
    summary.to_csv(a.output/'liquidity_screen_summary_v54.csv',index=False)
    pd.concat(scored2024,ignore_index=True).to_csv(
        a.output/'early_temporal_scored_v54.csv.gz',index=False,compression='gzip')
    lines='\n'.join(f'| {r.year} | {r.min_turnover20_twd/1e6:.0f} | {r.days} | '
                    f'{r.mean_eligible:.0f} | {r.base_rate:.2%} | {r.logistic:.2%} | '
                    f'{r.mom60_skip5:.2%} | {r.logistic_minus_mom60*100:+.2f} | '
                    f'{r.mom20:.2%} | {r.hist_gradient_boosting:.2%} |'
                    for r in summary.itertuples())
    report=f'''# 歷史成交額入池門檻敏感性（2024 早期折／2025 留出集）

固定既有模型分數及參數，僅在**評估日**按當時可得的過去 20 日平均成交額重新篩股票；門檻為 1,000 萬、3,000 萬、1 億元。於每個過濾後的同日股票池取分數最高的前 10%。2024 仍採原有兩折與標籤窗口隔離；2025 用封存預測。門檻是看到結果後追加的敏感性測試，不能充作事前策略。

## Tasks

- [x] 1,000 萬元原門檻下，逐日對照 2024 的 42 日及 2025 的 223 日既有四方法正例率，容差 1e-12。
- [x] 在 3,000 萬及 1 億元門檻重新評估同日四種排序，不重新訓練或調參。
- [ ] 取得更早的完整免費年份後，先固定門檻和選股比例，再向前測試；實股成本及成交假設仍須另核查。

| 年度／段 | 最低20日平均成交額（百萬元） | 日數 | 日均合格檔 | 日均基準正例率 | Logistic | 60 日去近 5 日動能 | 差額（百分點） | 20 日動能 | 梯度樹 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{lines}

2024 只有 42 日且訓練期短，這些折是看過 2025 結果後建立的回溯壓力測試。不同門檻會同時改變股票池大小與正例率，表中差額僅比較**同年度、同門檻、同一日**的模型及規則。未來最高價飆股標籤不是保證可成交的交易勝率；權益、證書及實股 NAV 閘門維持。

## 下一步規劃

2025 年 Logistic 相對 60 日動能的標籤正例率差額在 1 億元門檻仍為正，故並非只集中於低流動性股票；但 2024 早期兩折三種門檻都沒有相同優勢。下一次跨年度測試需事前固定流動性限制。完整 2023 年原始資料仍是跨年度訓練及驗證的必要輸入；權利證書與結算核查維持 pending。

重算：`python3 audit_liquidity_screen_v54.py`；逐日及摘要原值保留 CSV。
'''
    (a.output/'liquidity_screen_report_v54.md').write_text(report)


if __name__=='__main__':
    main()
