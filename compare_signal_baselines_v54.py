"""Compare archived 2025 surge predictions with prespecified causal price rules.

This evaluates the same held-out labels and stock-day rows; it does not model
trades, dividends, queue priority, or portfolio returns.
"""
import argparse
import math
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions', type=Path,
                   default=Path('restored_v54/twse_history/output_research_v5/holdout_predictions_2025.csv.gz'))
    p.add_argument('--features', type=Path,
                   default=Path('twse_history/output_research_v5/causal_features_2024_2025.csv.gz'))
    p.add_argument('--output', type=Path, default=Path('deliverables'))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    pred = pd.read_csv(a.predictions, usecols=['date', 'symbol', 'surge_adjusted', 'logistic',
                                               'hist_gradient_boosting'], dtype={'symbol': str})
    features = pd.read_csv(a.features, usecols=['date', 'symbol', 'mom60_skip5', 'mom20'],
                           dtype={'symbol': str})
    if pred.duplicated(['date', 'symbol']).any() or features.duplicated(['date', 'symbol']).any():
        raise ValueError('Duplicate date-symbol rows')
    data = pred.merge(features, on=['date', 'symbol'], how='left', validate='one_to_one', indicator=True)
    if not data['_merge'].eq('both').all() or data[['mom60_skip5', 'mom20']].isna().any().any():
        raise ValueError('Some held-out rows lack causal rule features')
    if len(data) != 139487 or data['date'].nunique() != 223:
        raise ValueError('Unexpected v54 holdout')
    names = ['logistic', 'hist_gradient_boosting', 'mom60_skip5', 'mom20']
    day_rows = []
    for date, group in data.groupby('date', sort=True):
        n = math.ceil(len(group) / 10)
        row = dict(date=date, eligible=len(group), top_n=n,
                   base_rate=group.surge_adjusted.mean())
        for name in names:
            row[name] = group.nlargest(n, name).surge_adjusted.mean()
        day_rows.append(row)
    daily = pd.DataFrame(day_rows)
    daily['month'] = daily.date.str[:7]
    monthly = daily.groupby('month', as_index=False).agg(
        days=('date', 'size'), base_rate=('base_rate', 'mean'),
        **{name: (name, 'mean') for name in names})
    metrics = {}
    for name in names:
        metrics[name] = dict(pr_auc=average_precision_score(data.surge_adjusted, data[name]),
                             daily_precision=daily[name].mean())
    for name, prior in [('logistic', .15126609469475238),
                        ('hist_gradient_boosting', .128883529427418)]:
        if abs(metrics[name]['daily_precision'] - prior) > 1e-12:
            raise ValueError(f'{name} did not reproduce archived v5 result')
    phase = []
    for offset in range(20):
        cohort = daily.iloc[offset::20]
        phase.append(dict(offset=offset, days=len(cohort),
                          logistic_minus_mom60=(cohort.logistic - cohort.mom60_skip5).mean(),
                          logistic_minus_mom20=(cohort.logistic - cohort.mom20).mean(),
                          hgb_minus_mom60=(cohort.hist_gradient_boosting - cohort.mom60_skip5).mean()))
    phases = pd.DataFrame(phase)
    daily.to_csv(a.output / 'daily_signal_rule_comparison_v54.csv', index=False)
    monthly.to_csv(a.output / 'monthly_signal_rule_comparison_v54.csv', index=False)
    phases.to_csv(a.output / 'nonoverlap_20day_phase_v54.csv', index=False)

    fmt = lambda value: f'{value:.2%}'
    pp = lambda value: f'{100 * value:.2f}'
    overall_lines = '\n'.join(f'| {name} | {metrics[name]["pr_auc"]:.4f} | '
                              f'{fmt(metrics[name]["daily_precision"])} |'
                              for name in names)
    month_lines = '\n'.join(f'| {r.month} | {int(r.days)} | {fmt(r.base_rate)} | '
                            f'{fmt(r.logistic)} | {fmt(r.hist_gradient_boosting)} | '
                            f'{fmt(r.mom60_skip5)} | {fmt(r.mom20)} |'
                            for r in monthly.itertuples())
    wins = {rule: int((monthly.logistic > monthly[rule]).sum()) for rule in ('mom60_skip5', 'mom20')}
    report = f'''# 2025 飆股訊號：模型與簡單量價規則同列比較

資料：封存 v54 對應的 v5 預測、因果特徵；2025 年 {len(data):,} 股票日、{len(daily)} 個可評估日。標籤為訊號後 20 個市場交易日內調整後盤中最高價上漲至少 30%。所有方法使用同一日期、同一股票集合、同一正例標籤；每日期選得分最高的 `ceil(10% × 當日股票數)`。規則 `mom60_skip5` 是研究已使用的 60 日動能去除最近 5 日，`mom20` 另作直觀參照；本次沒有重新訓練模型。

## Tasks

- [x] 對齊預測與事前可得規則特徵：{len(data):,}/{len(data):,} 列有兩個動能分數。
- [x] 重現封存模型的逐日前 10% precision，並比較同一留出標籤的規則。
- [x] 以 20 個相隔 20 交易日的日期相位抽樣，檢查重疊標籤的敏感性。
- [ ] 增加新的年份作獨立 walk-forward；不能以此單年比較挑選新參數再回報同年的樣本外績效。
- [ ] 持股權益和證書原價齊全後，另做含成本與真實可交易性的投資組合回測。

| 排序法 | PR-AUC | 逐日 Top 10% 正例率均值 |
|---|---:|---:|
{overall_lines}

逐日市場平均正例率是 {fmt(daily.base_rate.mean())}。Logistic 較預先使用的 `mom60_skip5` 高 {pp(metrics['logistic']['daily_precision']-metrics['mom60_skip5']['daily_precision'])} 個百分點；梯度樹較同規則高 {pp(metrics['hist_gradient_boosting']['daily_precision']-metrics['mom60_skip5']['daily_precision'])} 個百分點。相對於 `mom20`，梯度樹的前 10% 正例率反而低 {pp(metrics['mom20']['daily_precision']-metrics['hist_gradient_boosting']['daily_precision'])} 個百分點。這是排序標籤比較，不是交易勝率或收益差。

| 月份 | 天數 | 當日正例率 | Logistic | 梯度樹 | 60 日去近 5 日動能 | 20 日動能 |
|---|---:|---:|---:|---:|---:|---:|
{month_lines}

Logistic 在 12 個月份中有 {wins['mom60_skip5']} 個月優於 60 日規則、{wins['mom20']} 個月優於 20 日規則；12 月僅 2 個可評估日。若每隔 20 個交易日取一天，20 種起點對 60 日規則的 Logistic 優勢落在 {pp(phases.logistic_minus_mom60.min())} 至 {pp(phases.logistic_minus_mom60.max())} 個百分點，其中 {int((phases.logistic_minus_mom60 > 0).sum())}/20 起點為正；對 20 日規則則落在 {pp(phases.logistic_minus_mom20.min())} 至 {pp(phases.logistic_minus_mom20.max())} 個百分點，{int((phases.logistic_minus_mom20 > 0).sum())}/20 起點為正。相位結果只是對標籤重疊的敏感性檢查，各相位共用 2025 年市場環境，**不是 20 次獨立的統計驗證**。

## 下一步規劃

先核驗官方歷史 JSON 對 L–Z 權利證書的覆蓋；並延長免費行情年份，再做嚴格時間順序、標籤窗口隔離的 walk-forward。此份比較不解除實股 NAV／Alpha 閘門。

重算：`python3 compare_signal_baselines_v54.py --predictions restored_v54/twse_history/output_research_v5/holdout_predictions_2025.csv.gz --features twse_history/output_research_v5/causal_features_2024_2025.csv.gz --output deliverables`。
'''
    (a.output / 'signal_rule_comparison_v54.md').write_text(report)
    print(report)


if __name__ == '__main__':
    main()
