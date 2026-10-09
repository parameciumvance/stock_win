"""Audit future-quote and observed-flow selection using frozen fitted models.

No fitting or missing-label imputation. Extended labels are a diagnostic only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_institutional_increment import dataset, PRICE_FEATURES, FLOW_FEATURES


def scores(frame, models):
    result = frame.copy()
    for name, model in models.items():
        x = result[model['features']].to_numpy()
        result[name] = ((x - np.asarray(model['scaler_mean'])) /
                        np.asarray(model['scaler_scale'])) @ np.asarray(model['ridge_coefficients']) + model['ridge_intercept']
    return result


def audit(candidates, models, config, scope, details=None):
    frame = candidates[candidates.date.gt(config['train_cutoff'])].copy()
    frame['asof_price'] = frame.eligible & np.isfinite(frame[PRICE_FEATURES]).all(axis=1)
    frame['asof_common'] = frame.asof_price & np.isfinite(frame[FLOW_FEATURES]).all(axis=1)
    frame['label_available'] = np.isfinite(frame.target)
    rows = []
    for date, group in frame.groupby('date', sort=True):
        common = scores(group[group.asof_common], models)
        count = int(np.ceil(len(common) * config['top_fraction']))
        row = {'scope': scope, 'date': date.strftime('%Y-%m-%d'),
               'asof_price_pool': int(group.asof_price.sum()), 'asof_common_pool': len(common),
               'flow_missing_rows': int((group.asof_price & ~group.asof_common).sum()),
               'future_label_removed': int((~common.label_available).sum()),
               'removed_with_observed_endpoints': int((~common.label_available & np.isfinite(common.endpoint_target)).sum()),
               'label_valid_pool': int(common.label_available.sum())}
        if 'benchmark_label_available' in group:
            row['benchmark_label_available'] = bool(group.benchmark_label_available.iloc[0])
        for name in models:
            top = common.sort_values([name, 'symbol'], ascending=[False, True]).head(count)
            label_valid = common[common.label_available]
            old_count = int(np.ceil(len(label_valid) * config['top_fraction']))
            old_top = label_valid.sort_values([name, 'symbol'], ascending=[False, True]).head(old_count)
            row[name + '_asof_top_count'] = len(top)
            row[name + '_missing_target_in_top'] = int((~top.label_available).sum())
            row[name + '_missing_endpoints_in_top'] = int((~np.isfinite(top.endpoint_target)).sum())
            row[name + '_top_overlap'] = len(set(top.symbol) & set(old_top.symbol))
            # Never discard unknown targets and report the remaining mean as the portfolio result.
            row[name + '_asof_top_mean'] = float(top.target.mean()) if len(top) and top.label_available.all() else np.nan
            row[name + '_endpoint_top_mean'] = float(top.endpoint_target.mean()) if len(top) and np.isfinite(top.endpoint_target).all() else np.nan
            row[name + '_future_filtered_top_mean'] = float(old_top.target.mean()) if len(old_top) else np.nan
            if details is not None:
                for rank, selected in enumerate(top.itertuples(), 1):
                    if not selected.label_available:
                        details.append({'scope': scope, 'date': date.strftime('%Y-%m-%d'),
                            'model': name, 'symbol': selected.symbol, 'rank': rank,
                            'score': getattr(selected, name), 'strict_target_available': False,
                            'endpoint_target': selected.endpoint_target,
                            'benchmark_label_available': getattr(selected, 'benchmark_label_available', None),
                            'stock_future_quotes_complete': getattr(selected, 'future_quotes_complete', None),
                            'label_window_end': str(getattr(selected, 'label_window_end', ''))})
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/institutional_pool_audit_2024.json')
    args = parser.parse_args()
    audit_config = json.loads(Path(args.config).read_text())
    study = str(audit_config.get('study_name', '2024'))
    if not study.isdigit():
        raise ValueError('Study name must be a year')
    config = json.loads(Path(audit_config['config']).read_text())
    if hashlib.sha256(Path(config['prices']).read_bytes()).hexdigest() != config['expected_prices_sha256']:
        raise ValueError('Frozen price checksum mismatch')
    model_bytes = Path(audit_config['models']).read_bytes()
    if hashlib.sha256(model_bytes).hexdigest() != audit_config['expected_model_sha256']:
        raise ValueError('Frozen model checksum mismatch')
    models = json.loads(model_bytes)['models']
    results = []; details = []
    for scope, end in [('original_read_window', None), ('extended_labels_only', audit_config['extended_label_read_end'])]:
        _, _, _, candidates = dataset(config['prices'], config['features'], pd.Timestamp(config['train_cutoff']),
            config['commission'], config['sell_tax'], config['slippage_each_side'],
            config['start_year'], config['end_year'], return_candidates=True, label_read_end=end)
        results.append(audit(candidates, models, config, scope, details))
    daily = pd.concat(results, ignore_index=True)
    summaries = {}
    for scope, group in daily.groupby('scope'):
        complete_benchmark = group.label_valid_pool.gt(0)
        observed = group[complete_benchmark]
        summary = {'signal_dates': len(group), 'dates_with_any_label': len(observed),
            'asof_price_rows': int(group.asof_price_pool.sum()),
            'asof_common_rows': int(group.asof_common_pool.sum()),
            'flow_missing_rows': int(group.flow_missing_rows.sum()),
            'future_label_removed_all_dates': int(group.future_label_removed.sum()),
            'removed_with_observed_endpoints': int(group.removed_with_observed_endpoints.sum()),
            'future_label_removed_on_observed_dates': int(observed.future_label_removed.sum())}
        for name in models:
            summary[name] = {'dates_with_unknown_top_target': int(observed[name + '_missing_target_in_top'].gt(0).sum()),
                'unknown_top_targets': int(observed[name + '_missing_target_in_top'].sum()),
                'missing_top_endpoints': int(observed[name + '_missing_endpoints_in_top'].sum()),
                'unconditional_mean_is_identified': bool(observed[name + '_missing_target_in_top'].eq(0).all())}
        summaries[scope] = summary
    out = Path(audit_config['output_directory']); out.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out / f'institutional_pool_audit_daily_{study}.csv', index=False)
    detail_path = out / f"institutional_pool_unknown_top_{study}.csv{'.gz' if audit_config.get('compress_unknown_top') else ''}"
    pd.DataFrame(details).to_csv(detail_path, index=False,
        compression={'method': 'gzip', 'mtime': 0} if audit_config.get('compress_unknown_top') else None)
    result = {'config': audit_config, 'summary': summaries,
        'features_sha256': hashlib.sha256(Path(config['features']).read_bytes()).hexdigest(),
        'model_sha256': audit_config['expected_model_sha256'],
        'limitations': ['Frozen scores; no retraining or missing-return imputation.',
            'Asof means are left missing whenever any selected target is unknown.',
            'Flow-complete pool excludes missing observed source rows and is not the full historical universe.',
            'Extended labels use later stored quotes for outcomes only, never for predictors.',
            'Observed targets are adjusted quote proxies, not proved executable returns or NAV.']}
    (out / f'institutional_pool_audit_{study}.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = [f'# {study} 股票池與未來報價篩選檢查', '',
        '使用既有模型係數，以當日已知量價與前一市場日法人特徵選股；沒有重新訓練。', '',
        '| 讀取範圍 | 訊號日 | 有標籤日期 | 當時量價合格列 | 法人缺列 | 同池合格列 | 有標籤日期的未來篩除列 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for scope, s in summaries.items():
        lines.append(f"| {scope} | {s['signal_dates']} | {s['dates_with_any_label']} | {s['asof_price_rows']} | {s['flow_missing_rows']} | {s['asof_common_rows']} | {s['future_label_removed_on_observed_dates']} |")
    lines += ['', audit_config.get('label_read_note', f"只延伸讀取標籤到 {audit_config['extended_label_read_end']} 檢查年底資料截尾；特徵仍截至訊號日，模型係數維持原樣。"), '',
        '| 讀取範圍 | 模型 | 已有標籤日期中，Top 10% 仍有未知結果的日期 | 未知 Top 列 | 缺進出場端點 Top 列 |', '|---|---|---:|---:|---:|']
    for scope, s in summaries.items():
        for name in models:
            m = s[name]
            lines.append(f"| {scope} | {name} | {m['dates_with_unknown_top_target']} | {m['unknown_top_targets']} | {m['missing_top_endpoints']} |")
    lines += ['', '未知結果不補零，也不把剩餘股票的平均冒充整個選股組合。',
        '原結果先依未來標籤完整性縮小股票池，因此其均值與 rank IC 是條件式診斷。',
        'CSV 另列進出場端點均有報價的情形；中途缺價與進出場端點缺價分開，仍不能證明成交。',
        '法人缺列也縮小股票池；缺列沒有被當成零買賣超，尚不能代表全體普通股選股效果。',
        '後續評估應先封存當時股票池與排名，再追蹤缺價、停牌、下市與資料截尾；不能因事後結果不可得而換入其他股票。',
        '本次提供問題規模，不宣稱已算出缺失持股的可成交報酬或年度績效。', '']
    (out / f'institutional_pool_audit_report_{study}.md').write_text('\n'.join(lines))
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
