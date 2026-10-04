"""Compare archived 2025 model and causal momentum rankings at fixed pick sizes."""
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd


NAMES = ('logistic', 'hist_gradient_boosting', 'mom60_skip5', 'mom20')
FRACTIONS = (.05, .10, .20)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions', type=Path,
                   default=Path('restored_v54/twse_history/output_research_v5/holdout_predictions_2025.csv.gz'))
    p.add_argument('--features', type=Path,
                   default=Path('twse_history/output_research_v5/causal_features_2024_2025.csv.gz'))
    p.add_argument('--reference', type=Path,
                   default=Path('deliverables/daily_signal_rule_comparison_v54.csv'))
    p.add_argument('--output', type=Path, default=Path('deliverables'))
    a = p.parse_args()
    pred = pd.read_csv(a.predictions, usecols=['date', 'symbol', 'surge_adjusted',
        'logistic', 'hist_gradient_boosting'], dtype={'symbol': str})
    features = pd.read_csv(a.features, usecols=['date', 'symbol', 'mom60_skip5', 'mom20'],
                           dtype={'symbol': str})
    data = pred.merge(features, on=['date', 'symbol'], validate='one_to_one', indicator=True)
    if (len(data) != 139487 or data.date.nunique() != 223 or
        not data['_merge'].eq('both').all() or data[list(NAMES)].isna().any().any()):
        raise ValueError('Unexpected holdout population or missing scores')
    data.surge_adjusted = data.surge_adjusted.astype(bool)
    daily = []
    for date, group in data.groupby('date', sort=True):
        positives = int(group.surge_adjusted.sum())
        for fraction in FRACTIONS:
            k = math.ceil(len(group)*fraction)
            row = dict(date=date, fraction=fraction, eligible=len(group),
                       top_n=k, positives=positives, base_rate=positives/len(group))
            for name in NAMES:
                row[name] = group.nlargest(k, name).surge_adjusted.mean()
            daily.append(row)
    daily = pd.DataFrame(daily)
    reference = pd.read_csv(a.reference)
    tenth = daily[daily.fraction.eq(.10)].reset_index(drop=True)
    if not tenth.date.eq(reference.date).all():
        raise ValueError('Archived daily date mismatch')
    for name in NAMES:
        if not np.allclose(tenth[name], reference[name], rtol=0, atol=1e-12):
            raise ValueError(f'Archived Top 10% comparison mismatch: {name}')
    summary = daily.groupby('fraction', as_index=False)[['base_rate', *NAMES]].mean()
    summary['logistic_minus_mom60'] = summary.logistic-summary.mom60_skip5
    summary['logistic_minus_mom20'] = summary.logistic-summary.mom20
    summary['hgb_minus_mom60'] = summary.hist_gradient_boosting-summary.mom60_skip5
    summary['mean_top_n'] = daily.groupby('fraction').top_n.mean().to_numpy()
    a.output.mkdir(parents=True, exist_ok=True)
    daily.to_csv(a.output/'selection_fraction_daily_v54.csv', index=False)
    summary.to_csv(a.output/'selection_fraction_summary_v54.csv', index=False)
    lines = '\n'.join(f'| {r.fraction:.0%} | {r.mean_top_n:.1f} | '
        f'{r.logistic:.2%} | {r.hist_gradient_boosting:.2%} | '
        f'{r.mom60_skip5:.2%} | {r.mom20:.2%} | '
        f'{r.logistic_minus_mom60*100:+.2f} | {r.logistic_minus_mom20*100:+.2f} |'
        for r in summary.itertuples())
    gaps = summary.set_index('fraction').logistic_minus_mom60
    report = f'''# 2025 每日選股比例敏感性：前 5%／10%／20%

使用同一批封存模型預測、當時可得量價特徵、139,487 個股票日和 223 個可評估日。每一天對相同股票池取最高分 `ceil(比例 × 當日合格檔數)`，表格是**每日**正例率的等權平均；每日市場平均正例率 {daily[daily.fraction.eq(.10)].base_rate.mean():.2%}（若將股票日直接合併則為 5.29%）。完整標籤仍是未來 20 個市場交易日內還原最高價上漲至少 30%。

## Tasks

- [x] 發現工作區因果特徵快取副本受損；用完整 v54 主封存包中的原版恢復，核對 2025 年前 10% 每日四種分數與先前封存比較逐日一致。
- [x] 固定分數與股票池，計算前 5%、10%、20% 的兩模型與兩種動能規則正例率。
- [ ] 用未使用的額外年份驗證排序與選股比例；不可從本次 2025 結果選出最佳比例，再把 2025 當新樣本外成績。

| 每日選前 | 平均檔數 | Logistic | 梯度樹 | 60 日去近 5 日動能 | 20 日動能 | Logistic − 60 日（百分點） | Logistic − 20 日（百分點） |
|---|---:|---:|---:|---:|---:|---:|---:|
{lines}

前 10% 逐日數值與先前 `daily_signal_rule_comparison_v54.csv` 四方法皆在 1e-12 內一致。這項檢查是**看過 2025 結果後**增加的範圍敏感性分析。2024 早期兩折只保存前 10% 逐日摘要，本報告不以那兩折臆造前 5% 或 20% 的跨年結果。正例率是標籤排序指標，並非能在期間最高價成交的投資報酬；交易成本、額度與憑證實股帳未納入。

## 下一步規劃

待 2023 年以前官方免費資料及當時普通股池可用時，先固定選股比例及模型比較口徑，再按年度向前驗證。權利證書與結算項目維持 pending。

重算：`python3 audit_selection_fraction_v54.py --predictions restored_v54/twse_history/output_research_v5/holdout_predictions_2025.csv.gz --features twse_history/output_research_v5/causal_features_2024_2025.csv.gz`。逐日和摘要原值分別在 `selection_fraction_daily_v54.csv`、`selection_fraction_summary_v54.csv`。
'''
    (a.output/'selection_fraction_report_v54.md').write_text(report)


if __name__ == '__main__':
    main()
