"""Paired circular block bootstrap of daily Top 10% label precision gaps.

This is a sensitivity analysis on an already used 2025 holdout, not a new test.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


PAIRS = [('logistic', 'mom60_skip5'), ('logistic', 'mom20'),
         ('hist_gradient_boosting', 'mom60_skip5')]


def bootstrap_gap(values, *, block, repetitions, seed):
    """Circular moving-block resampling of paired daily gaps."""
    rng = np.random.default_rng(seed)
    n = len(values)
    starts = rng.integers(0, n, size=(repetitions, (n + block - 1)//block))
    offsets = np.arange(block)
    indices = (starts[:, :, None] + offsets[None, None, :]) % n
    draw = values[indices.reshape(repetitions, -1)[:, :n]].mean(axis=1)
    return np.quantile(draw, [0.025, 0.5, 0.975]), float(np.mean(draw <= 0))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--daily', type=Path, default=Path('deliverables/daily_signal_rule_comparison_v54.csv'))
    p.add_argument('--early', type=Path, default=Path('deliverables/early_temporal_daily_v54.csv'))
    p.add_argument('--output', type=Path, default=Path('deliverables'))
    p.add_argument('--repetitions', type=int, default=10000)
    a = p.parse_args()
    daily = pd.read_csv(a.daily, parse_dates=['date']).sort_values('date')
    early = pd.read_csv(a.early, parse_dates=['date']).sort_values('date')
    if len(daily) != 223 or daily.date.duplicated().any() or len(early) != 42:
        raise ValueError('Unexpected archived daily evaluation boundaries')
    if a.repetitions < 1000:
        raise ValueError('At least 1000 draws required')
    rows = []
    for i, (model, rule) in enumerate(PAIRS):
        gaps = (daily[model]-daily[rule]).to_numpy()
        for block in (10, 20, 40):
            quantiles, nonpositive = bootstrap_gap(gaps, block=block,
                repetitions=a.repetitions, seed=20261003+i*100+block)
            rows.append(dict(comparison=f'{model} - {rule}', days=len(daily),
                             block_days=block, repetitions=a.repetitions,
                             observed_gap=float(gaps.mean()),
                             bootstrap_p025=float(quantiles[0]),
                             bootstrap_median=float(quantiles[1]),
                             bootstrap_p975=float(quantiles[2]),
                             fraction_nonpositive=nonpositive))
    result = pd.DataFrame(rows)
    a.output.mkdir(parents=True, exist_ok=True)
    result.to_csv(a.output/'temporal_uncertainty_v54.csv', index=False)
    focus = result[result.block_days.eq(20)]
    lines = []
    for row in focus.itertuples():
        lines.append(f'| {row.comparison} | {row.observed_gap*100:+.2f} | '
                     f'[{row.bootstrap_p025*100:+.2f}, {row.bootstrap_p975*100:+.2f}] | '
                     f'{row.fraction_nonpositive:.2%} |')
    early_gap = (early.logistic-early.mom60_skip5).mean()
    report = f'''# 2025 模型對動能規則的時間區塊敏感性

對同一個交易日、同一股票池的前 10% 飆股標籤正例率取**成對差**。2025 留出集共 {len(daily)} 個可評估日；以連續 {20} 個交易日為區塊，採循環移動區塊重抽樣 {a.repetitions:,} 次（固定亂數種子），保留日與日的部分相關性。表中的區間是抽樣分布第 2.5／97.5 百分位，單位為百分點。

## Tasks

- [x] 使用封存逐日分數的成對差，避免將股票日或相鄰 20 日標籤視為獨立樣本。
- [x] 對 10、20、40 交易日區塊做敏感性比較，CSV 保留所有結果。
- [x] 對照已完成的 2024 早期時間切分結果，不把 2025 留出集重複使用當作新增獨立驗證。
- [ ] 取得 2023 年以前資料後，事前固定評估流程並做真正跨年度測試。

| 2025 成對差 | 觀察值（百分點） | 20 日區塊重抽樣區間 | 重抽樣差額 ≤ 0 |
|---|---:|---:|---:|
{chr(10).join(lines)}

最後一欄是此抽樣設計下的比例，**不是**策略有效的機率或正式檢定 p 值。區間反映 2025 年內不同時間片段的不確定性；年度間市場變化、已看過結果後的研究選擇與持股交易成本均不在其涵蓋範圍。10／20／40 日區塊的原始分位值見 `temporal_uncertainty_v54.csv`。

2024 年另兩折共 42 個測試日，Logistic 對既定 60 日動能規則的觀察差額為 {early_gap*100:+.2f} 個百分點。兩折訓練期很短，且這項回溯檢查是在看過 2025 結果後安排；不能與 2025 區間合併宣稱跨年度優勢。前 10% 正例率也不等於實際成交報酬。

## 下一步規劃

等待 2023 年免費行情與當時普通股池後，固定模型、規則、標籤及逐折清除重疊窗口的方式，做未使用年份的比較。權利證書行情與整股結算維持 pending，四策略全年實股 NAV／Alpha 仍未成立。

重算：`python3 audit_temporal_uncertainty_v54.py --daily deliverables/daily_signal_rule_comparison_v54.csv --early deliverables/early_temporal_daily_v54.csv`。
'''
    (a.output/'temporal_uncertainty_report_v54.md').write_text(report)


if __name__ == '__main__':
    main()
