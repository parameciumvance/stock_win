"""Describe causal turnover of daily Top 10% candidates on the 2025 holdout."""
import argparse
import math
from pathlib import Path

import pandas as pd


METHODS = ('logistic', 'hist_gradient_boosting', 'mom60_skip5', 'mom20')


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
    feat = pd.read_csv(a.features, usecols=['date', 'symbol', 'turnover20',
        'mom60_skip5', 'mom20'], dtype={'symbol': str})
    data = pred.merge(feat, on=['date', 'symbol'], validate='one_to_one', indicator=True)
    if (len(data) != 139487 or data.date.nunique() != 223 or
        not data['_merge'].eq('both').all() or data.turnover20.lt(10_000_000).any() or
        data[['turnover20', *METHODS]].isna().any().any()):
        raise ValueError('Unexpected eligible population or missing causal turnover')
    selections, daily = [], []
    for date, group in data.groupby('date', sort=True):
        k = math.ceil(len(group)*.1)
        for method in METHODS:
            top = group.nlargest(k, method)
            selections.append(top[['date', 'symbol', 'turnover20', 'surge_adjusted']].assign(method=method))
            daily.append(dict(date=date, method=method, precision=top.surge_adjusted.mean(),
                              median_turnover20=top.turnover20.median()))
    selected = pd.concat(selections, ignore_index=True)
    by_day = pd.DataFrame(daily)
    reference = pd.read_csv(a.reference)
    for method in METHODS:
        check = by_day[by_day.method.eq(method)].sort_values('date')
        if not (check.date.to_numpy() == reference.date.to_numpy()).all() or not (
            abs(check.precision.to_numpy()-reference[method].to_numpy()) < 1e-12).all():
            raise ValueError(f'Top 10% reference mismatch: {method}')
    summary = []
    for method, frame in [('eligible_pool', data), *[(m, selected[selected.method.eq(m)]) for m in METHODS]]:
        v = frame.turnover20
        summary.append(dict(method=method, stock_days=len(frame), median_turnover20=v.median(),
                            p10_turnover20=v.quantile(.1), below_30m=(v<30_000_000).mean(),
                            below_100m=(v<100_000_000).mean(),
                            precision=by_day.loc[by_day.method.eq(method), 'precision'].mean()
                            if method!='eligible_pool' else float('nan')))
    out = pd.DataFrame(summary)
    a.output.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output/'selection_liquidity_summary_v54.csv', index=False)
    by_day.to_csv(a.output/'selection_liquidity_daily_v54.csv', index=False)
    lines = []
    for r in out.itertuples():
        lines.append(f'| {r.method} | {r.stock_days:,} | {r.median_turnover20/1e6:.1f} | '
                     f'{r.p10_turnover20/1e6:.1f} | {r.below_30m:.1%} | '
                     f'{r.below_100m:.1%} | {"—" if pd.isna(r.precision) else format(r.precision, ".2%")} |')
    report = f'''# 2025 選股訊號的流動性分布

以**訊號日以前及當日可得**的過去 20 市場日平均成交額（`turnover20`，新台幣）衡量。全部比較固定為封存 2025 年 223 個可評估日、同一合格股票池、每日最高分前 10%；候選股票日因相鄰日重複而非獨立樣本。分位數是合併股票日的描述值。

## Tasks

- [x] 核對 139,487 個合格股票日的 20 日平均成交額均達既定 1,000 萬元門檻。
- [x] 將四種排序的逐日標籤正例率與先前封存結果逐日核對一致。
- [x] 比較入選名單的成交額中位數、下十分位與低於 3,000 萬／1 億元的比例。
- [ ] 未來實股回測時依委託金額和參與率限制驗證滑價及可成交性；目前沒有委託量與逐筆撮合資料。

| 名單 | 股票日 | 成交額中位數（百萬元） | 下十分位（百萬元） | <3,000 萬 | <1 億 | 前 10% 正例率 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(lines)}

Logistic 入選股的成交額中位數低於 60 日去近 5 日動能規則，低於 3,000 萬元的比例也較高。即使 2025 飆股標籤排序較好，這種流動性組成仍須在實際下單金額與成本下檢查；上表不能推算可投入資金額度或成交滑價。既定篩選只保證**過去 20 日平均**成交額達 1,000 萬元，並不保證下單當日有足夠深度。

## 下一步規劃

取得 2023 年以前免費資料後確認這個分布在其他年份是否相似，並在實股帳閉合時加入與委託量相關的流動性限制。證書與整股／畸零結算仍維持 pending。

重算：`python3 audit_selection_liquidity_v54.py`；逐日與總表保留 CSV。
'''
    (a.output/'selection_liquidity_report_v54.md').write_text(report)


if __name__ == '__main__':
    main()
