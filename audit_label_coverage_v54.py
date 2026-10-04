"""Audit 2025 label censoring and model-eligible coverage from archived inputs."""
import argparse
from pathlib import Path

import pandas as pd


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('twse_history/output_multiyear'))
    p.add_argument('--features', type=Path,
                   default=Path('twse_history/output_research_v5/causal_features_2024_2025.csv.gz'))
    p.add_argument('--output', type=Path, default=Path('deliverables'))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    labels = pd.read_csv(a.source / 'surge_labels_adjusted_2024_2025.csv.gz',
                         usecols=['date', 'symbol', 'label_available', 'censor_reason', 'surge_adjusted'],
                         dtype={'symbol': str}, parse_dates=['date'])
    features = pd.read_csv(a.features, usecols=['date', 'symbol', 'signal_eligible'],
                           dtype={'symbol': str}, parse_dates=['date'])
    all_data = labels.merge(features, on=['date', 'symbol'], how='left', validate='one_to_one', indicator=True)
    if not all_data['_merge'].eq('both').all() or all_data.signal_eligible.isna().any():
        raise ValueError('Label/feature population mismatch')
    crossyear = []
    for year in (2024, 2025):
        year_data = all_data[all_data.date.dt.year.eq(year)]
        for period, group in [('whole_year', year_data),
                              ('jul_nov', year_data[year_data.date.dt.month.between(7, 11)])]:
            valid = group[group.label_available]
            eligible_group = valid[valid.signal_eligible]
            crossyear.append(dict(year=year, period=period, historical_membership_rows=len(group),
                                  label_available_rows=len(valid), model_eligible_rows=len(eligible_group),
                                  model_eligible_share_of_pool=len(eligible_group)/len(group),
                                  eligible_positive_rate=eligible_group.surge_adjusted.mean(),
                                  eligible_dates=eligible_group.date.nunique()))
    crossyear_df = pd.DataFrame(crossyear)
    crossyear_df.to_csv(a.output / 'crossyear_coverage_v54.csv', index=False)
    comparable = crossyear_df[crossyear_df.period.eq('jul_nov')].set_index('year')
    if (int(comparable.loc[2024, 'model_eligible_rows']),
            int(comparable.loc[2025, 'model_eligible_rows'])) != (71329, 64176):
        raise ValueError('Unexpected comparable-period coverage')
    data = all_data[all_data.date.dt.year.eq(2025)].copy()
    available = data[data.label_available].copy()
    grouped = available.groupby('signal_eligible').surge_adjusted.agg(['count', 'sum', 'mean'])
    if (len(data), len(available), int(grouped.loc[True, 'count']),
            int(grouped.loc[True, 'sum'])) != (254096, 225468, 139487, 7379):
        raise ValueError('Unexpected 2025 v54 sample counts')
    data['month'] = data.date.dt.to_period('M').astype(str)
    months = []
    for month, subset in data.groupby('month', sort=True):
        evaluable = subset[subset.label_available]
        eligible = evaluable[evaluable.signal_eligible]
        months.append(dict(month=month, historical_membership_rows=len(subset),
                           label_available_rows=len(evaluable),
                           model_eligible_rows=len(eligible),
                           missing_label_rows=len(subset)-len(evaluable),
                           insufficient_market_horizon=int(subset.censor_reason.eq('insufficient_market_horizon').sum()),
                           missing_future_high=int(subset.censor_reason.eq('missing_future_high').sum()),
                           missing_signal_close=int(subset.censor_reason.eq('missing_signal_close').sum()),
                           available_positive_rate=float(evaluable.surge_adjusted.mean()) if len(evaluable) else float('nan'),
                           eligible_positive_rate=float(eligible.surge_adjusted.mean()) if len(eligible) else float('nan')))
    pd.DataFrame(months).to_csv(a.output / 'label_coverage_monthly_v54.csv', index=False)
    missing = data[~data.label_available].censor_reason.value_counts().to_dict()
    date_count = available.loc[available.signal_eligible, 'date'].nunique()
    report = f'''# 2024–2025 飆股標籤與股票池覆蓋檢查

同一封存資料的 2025 歷史普通股股票池含 {len(data):,} 個股票日；未來 20 交易日標籤可得 {len(available):,} 個，其中符合當時可得 120 日量價歷史、價格與流動性條件者 {int(grouped.loc[True, 'count']):,} 個，涵蓋 {date_count} 個可評估日。這才是前述模型 PR-AUC 和每日 Top 10% precision 的母體。

## Tasks

- [x] 標籤與因果特徵依日期／代號逐列對齊：{len(data):,}/{len(data):,}。
- [x] 分開計算標籤不可得、標籤可得但訊號不合格、模型可評估三層樣本。
- [x] 統計缺標籤原因與月度分布，保留未四捨五入的 CSV。
- [x] 對照 2024 與 2025，另用共同的 7–11 月窗口控制年初特徵暖機與 2025 年末標籤截尾。
- [ ] 補充年份後比較不同市場與篩選條件下的覆蓋率及模型排名。

| 2025 股票日層級 | 列數 | 佔歷史股票池 | 已知正例率 |
|---|---:|---:|---:|
| 歷史普通股池 | {len(data):,} | 100% | 無法對缺標籤列定義 |
| 標籤不可得 | {len(data)-len(available):,} | {(len(data)-len(available))/len(data):.2%} | 不可得 |
| 標籤可得但訊號不合格 | {int(grouped.loc[False, 'count']):,} | {int(grouped.loc[False, 'count'])/len(data):.2%} | {grouped.loc[False, 'mean']:.2%} |
| 模型可評估 | {int(grouped.loc[True, 'count']):,} | {int(grouped.loc[True, 'count'])/len(data):.2%} | {grouped.loc[True, 'mean']:.2%} |

標籤不可得原因：距資料年末不足 20 個交易日 {missing.get('insufficient_market_horizon', 0):,}、未來窗口缺最高價 {missing.get('missing_future_high', 0):,}、訊號當日無收盤價 {missing.get('missing_signal_close', 0):,}。其中 12 月缺標籤 {months[-1]['missing_label_rows']:,} 列。不可得列不能當作未飆漲；也不能把模型只在合格股票池觀察到的 {grouped.loc[True, 'mean']:.2%} 正例率，直接套到所有歷史普通股。標籤可得但訊號不合格列的正例率為 {grouped.loc[False, 'mean']:.2%}，說明流動性及歷史條件改變了評估母體；這不等同於模型本身的預測能力。

## 2024 與 2025 的相同月份對照

| 7–11 月 | 歷史股票日 | 有標籤 | 模型可評估 | 佔股票池 | 合格正例率 |
|---|---:|---:|---:|---:|---:|
| 2024 | {int(comparable.loc[2024, 'historical_membership_rows']):,} | {int(comparable.loc[2024, 'label_available_rows']):,} | {int(comparable.loc[2024, 'model_eligible_rows']):,} | {comparable.loc[2024, 'model_eligible_share_of_pool']:.2%} | {comparable.loc[2024, 'eligible_positive_rate']:.2%} |
| 2025 | {int(comparable.loc[2025, 'historical_membership_rows']):,} | {int(comparable.loc[2025, 'label_available_rows']):,} | {int(comparable.loc[2025, 'model_eligible_rows']):,} | {comparable.loc[2025, 'model_eligible_share_of_pool']:.2%} | {comparable.loc[2025, 'eligible_positive_rate']:.2%} |

2024 年全年的合格比例只有 {crossyear_df.iloc[0].model_eligible_share_of_pool:.2%}，主要因 120 日歷史暖機令 1–6 月完全沒有合格訊號（首次為 2024-07-04）；2025 年末則因檔案止於 12 月而缺未來 20 日標籤。故全年的 {crossyear_df.iloc[0].model_eligible_share_of_pool:.2%} 和 {crossyear_df.iloc[2].model_eligible_share_of_pool:.2%} 不能直接當作年度市場差異。同月比較仍顯示篩選涵蓋率及正例率會變動；不能把 2025 的模型排序結果直接外推到 2024，亦不能僅由正例率變動推斷特徵或模型原因。

## 下一步規劃

後續補入 2023 以前及 2026 的免費歷史資料時，先重建各年的當時股票池、標籤和缺值理由，再作跨年度時間切分。新股權利證書與結算核查保持 pending；本檢查不產出實股 NAV。

重算：`python3 audit_label_coverage_v54.py --source twse_history/output_multiyear --features twse_history/output_research_v5/causal_features_2024_2025.csv.gz --output deliverables`。`label_coverage_monthly_v54.csv` 和 `crossyear_coverage_v54.csv` 保留原始比率。
'''
    (a.output / 'label_coverage_audit_v54.md').write_text(report)
    print({k: (int(v) if isinstance(v, int) else v) for k,v in missing.items()})


if __name__ == '__main__':
    main()
