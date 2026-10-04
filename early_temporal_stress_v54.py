"""Fixed-parameter, purged 2024 temporal stress test for the surge signal."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from twse_history.research_v5 import FEATURES, training_frame


FOLDS = [('2024-10-01', '2024-11-01'), ('2024-11-01', '2024-12-04')]
SCORES = ['logistic', 'hist_gradient_boosting', 'mom60_skip5', 'mom20']


def evaluate_daily(test, fold):
    output = []
    for date, day in test.groupby('date', sort=True):
        k = math.ceil(len(day) / 10)
        row = dict(fold=fold, date=date.strftime('%Y-%m-%d'), eligible=len(day),
                   top_n=k, base_rate=float(day.surge_adjusted.mean()))
        for method in SCORES:
            row[method] = float(day.nlargest(k, method).surge_adjusted.mean())
        output.append(row)
    return output


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--features', type=Path, default=Path('twse_history/output_research_v5/causal_features_2024_2025.csv.gz'))
    cli.add_argument('--source', type=Path, default=Path('twse_history/output_multiyear'))
    cli.add_argument('--output', type=Path, default=Path('deliverables'))
    a = cli.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    features = pd.read_csv(a.features, dtype={'symbol': str}, parse_dates=['date'])
    suffix = '_2024_2025.csv.gz'
    labels = pd.read_csv(a.source / ('surge_labels_adjusted' + suffix),
                         dtype={'symbol': str}, parse_dates=['date', 'label_window_end'])
    roles = pd.read_csv(a.source / ('temporal_split' + suffix),
                        dtype={'symbol': str}, parse_dates=['date'])
    data = training_frame(features, labels, roles, [('2429', pd.Timestamp('2024-07-02'))])
    base = data[data.role.eq('train_eligible') & data.signal_eligible &
                data.label_available & ~data.quarantined_label].copy()
    if not np.isfinite(base[FEATURES]).all().all():
        raise ValueError('Nonfinite causal features')
    scored, fold_metrics, daily_rows = [], [], []
    for start, stop in FOLDS:
        cutoff = pd.Timestamp(start)
        train = base[base.date.lt(cutoff) & base.label_window_end.lt(cutoff)].copy()
        test = base[base.date.ge(cutoff) & base.date.lt(pd.Timestamp(stop))].copy()
        if not len(train) or not len(test) or train.label_window_end.max() >= test.date.min():
            raise ValueError('Empty or leaking split')
        if test.label_window_end.ge(pd.Timestamp('2025-01-01')).any():
            raise ValueError('2024 label extends into 2025 holdout')
        models = dict(logistic=make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)),
                      hist_gradient_boosting=HistGradientBoostingClassifier(
                          learning_rate=.06, max_iter=100, max_leaf_nodes=15,
                          min_samples_leaf=100, l2_regularization=1.,
                          early_stopping=False, random_state=2025))
        for name, model in models.items():
            model.fit(train[FEATURES], train.surge_adjusted.astype(int))
            test[name] = model.predict_proba(test[FEATURES])[:, 1]
        fold_metrics.append(dict(start=start, stop_exclusive=stop, train_rows=len(train),
                                 train_dates=train.date.nunique(),
                                 train_first=train.date.min().strftime('%Y-%m-%d'),
                                 train_last=train.date.max().strftime('%Y-%m-%d'),
                                 train_label_last=train.label_window_end.max().strftime('%Y-%m-%d'),
                                 eval_rows=len(test), eval_dates=test.date.nunique(),
                                 eval_positives=int(test.surge_adjusted.sum()),
                                 eval_prevalence=float(test.surge_adjusted.mean())))
        daily_rows.extend(evaluate_daily(test, start))
        scored.append(test[['date', 'symbol', 'surge_adjusted', *SCORES]])
    all_scored = pd.concat(scored, ignore_index=True)
    if all_scored.duplicated(['date', 'symbol']).any():
        raise ValueError('Overlapping out-of-sample folds')
    daily = pd.DataFrame(daily_rows)
    daily.to_csv(a.output / 'early_temporal_daily_v54.csv', index=False)
    pd.DataFrame(fold_metrics).to_csv(a.output / 'early_temporal_folds_v54.csv', index=False)
    summaries = []
    for cohort, frame in [('combined', all_scored),
                          (FOLDS[0][0], scored[0]), (FOLDS[1][0], scored[1])]:
        subset = daily if cohort == 'combined' else daily[daily.fold.eq(cohort)]
        for method in SCORES:
            summaries.append(dict(cohort=cohort, method=method, rows=len(frame),
                                  dates=frame.date.nunique(),
                                  prevalence=float(frame.surge_adjusted.astype(int).mean()),
                                  pr_auc=float(average_precision_score(frame.surge_adjusted.astype(int), frame[method])),
                                  daily_top_decile_precision=float(subset[method].mean())))
    pd.DataFrame(summaries).to_csv(a.output / 'early_temporal_summary_v54.csv', index=False)
    lines = '\n'.join(f'| {r["cohort"]} | {r["method"]} | {r["dates"]} | {r["prevalence"]:.2%} | '
                      f'{r["pr_auc"]:.4f} | {r["daily_top_decile_precision"]:.2%} |'
                      for r in summaries)
    vals = {r['method']: r for r in summaries if r['cohort'] == 'combined'}
    report = f'''# 飆股訊號 2024 早期時間切分壓力測試

這是額外的時間外測試：現成 120 日因果特徵於 2024-07-04 才齊，沿用 v5 的 13 個特徵與**固定** Logistic／HistGradientBoosting 參數。10 月、11 月各重訓一次；每折只用標籤終點早於該折開始日的資料。2024 年測試日不重複；2025 留出集從未進入本次訓練。已沿用原有 2429 特殊標籤隔離規則。

## Tasks

- [x] 2024-10-01／2024-11-01 兩個固定切分，訓練標籤窗口均在測試前結束。
- [x] 相同股票日與 Top 10% 數量比較兩模型、`mom60_skip5`、`mom20`。
- [x] 保留兩折各自結果及逐日清單，不將同年度兩折當作兩個獨立年度。
- [ ] 取得更早年份資料，做具充分訓練期的跨年度 walk-forward。
- [ ] 另驗證交易成本、實股權益與行情後才計算可投資績效。

| 切分 | 方法 | 測試日 | 正例率 | PR-AUC | 逐日 Top 10% 正例率 |
|---|---|---:|---:|---:|---:|
{lines}

訓練明細：10 月折 {fold_metrics[0]['train_rows']:,} 列、{fold_metrics[0]['train_dates']} 日，最後可用訊號 {fold_metrics[0]['train_last']}；11 月折 {fold_metrics[1]['train_rows']:,} 列、{fold_metrics[1]['train_dates']} 日，最後可用訊號 {fold_metrics[1]['train_last']}。合併測試 {len(all_scored):,} 股票日、{daily.shape[0]} 日。Logistic 相對既定 60 日動能的 Top 10% 差額為 {(vals['logistic']['daily_top_decile_precision'] - vals['mom60_skip5']['daily_top_decile_precision'])*100:+.2f} 個百分點。短訓練期、同一個 2024 市場環境與重疊的未來 20 日標籤都限制了解讀。這兩折在已看過 2025 結果後設計，屬回溯壓力測試，不是事前鎖定的獨立驗證；更不是跨年度穩健性或可交易報酬證明。

## 下一步規劃

將 2025 封存留出集保留作既有對照，下一輪擴充 2023 以前的免費歷史與當時股票池，增加真正跨年度切分；不能因這兩折結果再調整參數、重算 2025 並仍稱為未使用的留出集。憑證行情與結算核查保持 pending，暫不影響訊號研究。

重算：`python3 early_temporal_stress_v54.py --features twse_history/output_research_v5/causal_features_2024_2025.csv.gz --source twse_history/output_multiyear --output deliverables`。
'''
    (a.output / 'early_temporal_stress_v54.md').write_text(report)
    print(json.dumps({'folds': fold_metrics, 'summary': summaries}, indent=2))


if __name__ == '__main__':
    main()
