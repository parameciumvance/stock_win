"""Frozen delayed-revenue increment study; as-of selections retain unknown exits.

Uses the existing price/flow dataset interface but selects before seeing future
quote validity. Endpoint targets are exploratory adjusted quote proxies only.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from audit_institutional_increment import dataset, PRICE_FEATURES, FLOW_FEATURES
from audit_institutional_uncertainty import circular_block_intervals
from twse_history.revenue_proxy import attach_features, REVENUE_FEATURES, sha

MODEL_FEATURES = {
    'price': PRICE_FEATURES,
    'price_flow': PRICE_FEATURES + FLOW_FEATURES,
    'price_revenue': PRICE_FEATURES + REVENUE_FEATURES,
    'all': PRICE_FEATURES + FLOW_FEATURES + REVENUE_FEATURES,
}
SCORES = list(MODEL_FEATURES) + ['vol20', 'rev_yoy']


def verify_flow(path, expected_gzip, expected_csv):
    if sha(path) == expected_gzip:
        return
    # Compression timestamps are not data. A regenerated file must match the
    # pre-frozen decompressed CSV hash, without changing any values or keys.
    digest = hashlib.sha256()
    with gzip.open(path, 'rb') as source:
        for chunk in iter(lambda:source.read(1024*1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected_csv:
        raise ValueError('Frozen flow data checksum mismatch')


def evaluate_day(group, fraction, scores=SCORES):
    n = int(np.ceil(len(group) * fraction))
    row = dict(date=group.date.iloc[0].strftime('%Y-%m-%d'), pool=len(group), top_count=n,
               known_endpoint_pool=int(group.endpoint_target.notna().sum()))
    selections = []
    for name in scores:
        top = group.sort_values([name, 'symbol'], ascending=[False, True]).head(n).copy()
        known = np.isfinite(top.endpoint_target)
        row[name + '_unknown'] = int((~known).sum())
        row[name + '_top_net_relative'] = float(top.endpoint_target.mean()) if known.all() else np.nan
        observed = group[np.isfinite(group.endpoint_target)]
        row[name + '_rank_ic_observed'] = float(observed[name].rank().corr(observed.endpoint_target.rank())) if len(observed) > 2 else np.nan
        top['model'] = name
        top['rank'] = np.arange(1, n+1)
        top['score'] = top[name]
        cols=['date', 'symbol', 'model', 'rank', 'score', 'revenue_month',
              'proxy_available_date', 'month_end', 'endpoint_target', 'label_window_end']
        if 'margin_source_date' in top:cols.append('margin_source_date')
        selections.append(top[cols])
    return row, pd.concat(selections, ignore_index=True)


def paired_summary(daily, lhs, rhs, config):
    columns = [lhs + '_top_net_relative', rhs + '_top_net_relative']
    observed = daily[columns].notna().all(axis=1)
    difference = (daily.loc[observed, columns[0]] - daily.loc[observed, columns[1]]).to_numpy()
    result = dict(observed_paired_dates=int(observed.sum()), excluded_unknown_dates=int((~observed).sum()),
                  mean=float(difference.mean()), intervals={})
    for block in config['block_lengths']:
        if len(difference) <= block:
            raise ValueError('Insufficient paired dates for frozen blocks')
        result['intervals'][str(block)] = circular_block_intervals(
            difference[:, None], block, config['replicates'], config['seed'])[0]
    monthly = pd.DataFrame({'month':pd.to_datetime(daily.loc[observed, 'date']).dt.strftime('%Y-%m'),
                            'difference':difference}).groupby('month').difference.agg(['mean','count'])
    result['monthly'] = monthly.to_dict(orient='index')
    result['months_improved'] = int(monthly['mean'].gt(0).sum())
    return result


def run(config_path):
    config = json.loads(Path(config_path).read_text())
    if sha(config['prices']) != config['expected_prices_sha256']:
        raise ValueError('Frozen prices checksum mismatch')
    verify_flow(config['flows'], config['expected_flows_sha256'], config['reconstructed_flows_csv_sha256'])
    acquisition = json.loads(Path('deliverables/revenue_proxy/acquisition.json').read_text())
    monthly_path = Path('inputs/revenue_proxy/monthly_features.csv.gz')
    if sha(monthly_path) != acquisition['features_sha256']:
        raise ValueError('Revenue feature checksum mismatch')
    monthly = pd.read_csv(monthly_path, dtype={'symbol':str}, parse_dates=['month_end'])
    # Build all years once. The returned candidate frame has no future filtering.
    _, _, _, full = dataset(config['prices'], config['flows'], pd.Timestamp('2025-12-31'),
                            config['commission'], config['sell_tax'], config['slippage_each_side'],
                            2023, 2026, return_candidates=True, label_read_end=config['asof'])
    full = full[full.date.le(config['asof'])].copy()
    days = pd.DatetimeIndex(full.date.unique()).sort_values()
    output = Path(config['output_directory']); output.mkdir(parents=True, exist_ok=True)
    input_hashes = dict(protocol=sha(config_path), prices=sha(config['prices']), flows=sha(config['flows']),
                        revenue_features=sha(monthly_path))
    summaries = []
    for lag in [config['primary_lag_calendar_days']] + config['sensitivity_lag_calendar_days']:
        joined = attach_features(full, monthly, days, lag, config['max_age_calendar_days'])
        price_valid = joined.eligible & np.isfinite(joined[PRICE_FEATURES]).all(axis=1)
        flow_valid = price_valid & np.isfinite(joined[FLOW_FEATURES]).all(axis=1)
        valid = flow_valid & np.isfinite(joined[REVENUE_FEATURES]).all(axis=1)
        common = joined[valid].copy()
        for year in config['evaluation_years']:
            cutoff = pd.Timestamp(f'{year-1}-12-31')
            train = common[common.date.le(cutoff) & common.label_window_end.le(cutoff)
                           & np.isfinite(common.endpoint_target)].copy()
            test = common[common.date.dt.year.eq(year)].copy()
            if len(train) < 1000 or len(test) < 1000 or train.label_window_end.max() > cutoff:
                raise ValueError('Insufficient data or unpurged training labels')
            models = {}
            for name, columns in MODEL_FEATURES.items():
                model = make_pipeline(StandardScaler(), Ridge(alpha=config['ridge_alpha']))
                model.fit(train[columns], train.endpoint_target)
                test[name] = model.predict(test[columns])
                scaler, ridge = model.steps[0][1], model.steps[1][1]
                models[name] = dict(features=columns, scaler_mean=scaler.mean_.tolist(),
                                    scaler_scale=scaler.scale_.tolist(), coefficients=ridge.coef_.tolist(),
                                    intercept=float(ridge.intercept_))
            rows, tops = [], []
            for _, group in test.groupby('date', sort=True):
                if len(group) < config['min_pool_size']:
                    continue
                row, top = evaluate_day(group, config['top_fraction'])
                rows.append(row); tops.append(top)
            daily = pd.DataFrame(rows)
            if daily.empty:
                raise ValueError('Empty test period')
            suffix = f'{year}_lag{lag}'
            daily.to_csv(output / f'daily_{suffix}.csv', index=False)
            pd.concat(tops, ignore_index=True).to_csv(output / f'top_selections_{suffix}.csv.gz', index=False,
                                                      compression={'method':'gzip', 'mtime':0})
            (output / f'models_{suffix}.json').write_text(json.dumps(dict(
                input_sha256=input_hashes, train_cutoff=cutoff.date().isoformat(), models=models), indent=2)+'\n')
            in_year = joined.date.dt.year.eq(year)
            result = dict(year=year, lag_calendar_days=lag, train_rows=len(train),
                          train_signal_dates=train.date.nunique(), train_last_label_end=train.label_window_end.max().date().isoformat(),
                          asof_price_rows=int((price_valid & in_year).sum()), asof_flow_rows=int((flow_valid & in_year).sum()),
                          common_rows=len(test), revenue_missing_rows=int((flow_valid & ~valid & in_year).sum()),
                          scored_dates=len(daily), scored_first=daily.date.iloc[0], scored_last=daily.date.iloc[-1],
                          input_sha256=input_hashes, daily_sha256=sha(output / f'daily_{suffix}.csv'),
                          methods={})
            for name in SCORES:
                col = name + '_top_net_relative'
                result['methods'][name] = dict(mean_relative_quote_proxy=float(daily[col].mean()),
                                              known_top_dates=int(daily[col].notna().sum()),
                                              unknown_top_rows=int(daily[name+'_unknown'].sum()),
                                              mean_rank_ic_observed=float(daily[name+'_rank_ic_observed'].mean()))
            result['price_revenue_minus_price'] = paired_summary(daily, 'price_revenue', 'price', config['uncertainty'])
            result['all_minus_price_flow'] = paired_summary(daily, 'all', 'price_flow', config['uncertainty'])
            (output / f'summary_{suffix}.json').write_text(json.dumps(result, indent=2)+'\n')
            summaries.append(result)
            print(json.dumps({k:result[k] for k in ('year','lag_calendar_days','train_rows','common_rows','scored_dates')}
                             | {'increment':result['price_revenue_minus_price']['mean'] }), flush=True)
    combined = dict(protocol=config, summaries=summaries,
                    limitations=['Current static snapshots can contain later corrections; delay is not proof of original availability.',
                                 'Common pool requires observed price/flow/revenue features; excludes missing fundamentals without imputation.',
                                 'Top selections precede future quote filtering; unknown endpoint results are retained and daily means withheld.',
                                 'Rank IC uses only known endpoint outcomes and is a conditional diagnostic.',
                                 'Bootstrap uses paired fully observable selection dates; gaps compress time and circular wrap is approximate.',
                                 'Overlapping adjusted daily quote proxies with costs are not annual NAV, proven fills, or surge probabilities.',
                                 '2024–2026 already researched; fixed settings do not create an independent holdout.'])
    (output / 'crossyear_summary.json').write_text(json.dumps(combined, ensure_ascii=False, indent=2)+'\n')
    report(combined, output)


def report(combined, output):
    p = combined['protocol']
    lines = ['# 月營收延遲代理：固定跨年增量比較', '',
             '官方歷史靜態表加固定延遲，僅作探索研究；目前下載版本不能保證當年的原始公布數值。', '',
             f"固定時間：{p['protocol_frozen_at']}；主分析月底後 45 個日曆日的下一市場日，60 日為預先列出的敏感度。",
             '三年度採前一年年底前已完成標籤的 expanding 訓練，StandardScaler 僅在訓練池擬合；Ridge alpha=1000、Top10%、同日共同股票池。',
             '五個營收特徵：單月年增、月增、連續三月合計年增、年增相對三月前變化、正營收對數；比例固定截至 −1～5。缺月不跨越、不補零，月末距訊號超過 100 日視為過期。',
             '成本：買賣各 0.1425% 手續費、賣出 0.3% 稅、兩側各 0.5% 滑價；次市場日還原開盤進場、第 20 市場日還原收盤出場，相對 0050 同期端點毛報酬。',
             '市場日採所有報價日期聯集；與舊法人的未來 20 日完整報價篩選口徑不同，不能直接歸因比較兩份報告數字。', '',
             '## 主分析：45 日延遲', '',
             '| 年度 | 當時共同池列數 | 評分日 | 配對已知日 | 營收增量（百分點） | 20 日區塊 95% 區間（百分點） |',
             '|---|---:|---:|---:|---:|---:|']
    for s in combined['summaries']:
        if s['lag_calendar_days'] != 45: continue
        inc=s['price_revenue_minus_price']; b=inc['intervals']['20']
        lines.append(f"| {s['year']} | {s['common_rows']:,} | {s['scored_dates']} | {inc['observed_paired_dates']} | {inc['mean']*100:+.3f} | [{b['lower_95']*100:+.3f}, {b['upper_95']*100:+.3f}] |")
    lines += ['', '## 各方法已知完整選股日的平均相對報價代理', '',
              '下表每種方法的可評估日期可能不同；主增量結論以同日配對為準。均值不是年度投資報酬。', '',
              '| 年度 | 方法 | 相對 0050（%） | 已知選股日 | 未知選中列 | 已知結果子池 rank IC |',
              '|---|---|---:|---:|---:|---:|']
    names=dict(price='量價', price_flow='量價＋法人', price_revenue='量價＋營收', all='三者合併', vol20='波動排序', rev_yoy='營收年增排序')
    for s in combined['summaries']:
        if s['lag_calendar_days'] != 45: continue
        for name,m in s['methods'].items():
            lines.append(f"| {s['year']} | {names[name]} | {m['mean_relative_quote_proxy']*100:+.3f} | {m['known_top_dates']} | {m['unknown_top_rows']} | {m['mean_rank_ic_observed']:+.4f} |")
    lines += ['', '## 固定敏感度與加入法人後的營收增量', '',
              '| 延遲日 | 年度 | 營收−量價（百分點） | 三者−量價法人（百分點） | 後者 20 日區塊區間（百分點） |',
              '|---|---|---:|---:|---:|']
    for s in combined['summaries']:
        a=s['price_revenue_minus_price'];b=s['all_minus_price_flow'];ci=b['intervals']['20']
        lines.append(f"| {s['lag_calendar_days']} | {s['year']} | {a['mean']*100:+.3f} | {b['mean']*100:+.3f} | [{ci['lower_95']*100:+.3f}, {ci['upper_95']*100:+.3f}] |")
    lines += ['', '## 覆蓋與未知結果', '',
              '| 延遲日 | 年度 | 法人完整、營收不完整列 | 營收／量價配對未知日 |', '|---|---|---:|---:|']
    for s in combined['summaries']:
        lines.append(f"| {s['lag_calendar_days']} | {s['year']} | {s['revenue_missing_rows']:,} | {s['price_revenue_minus_price']['excluded_unknown_dates']} |")
    lines += ['', '2026 來源截至 10/02，最後 20 個訊號日未完成未來窗口，仍保留評分與選股；沒有以較低名次的已知股票替換。',
              '每份 top_selections 保存營收月份、假設可用日、排名、分數與未知端點，供查核。', '', '## 解讀與下一步', '',
              '45 日延遲的三年營收增量點估計為正，但三年 20 日區塊區間均涵蓋零；60 日延遲未形成穩定改善證據。營收模型的已知選股日平均成本後相對代理仍落後 0050。',
              '逐年配對增量、區塊區間與兩種固定延遲須合併判讀；任何單一年份改善均不足以將代理升為正式實盤排名。',
              '下一步按固定口徑檢查免費融資融券資料的覆蓋与增量；嚴格首次公告時間及原始修訂歷史繼續 pending。', '', '## 限制', '']
    consistency = json.loads((output / 'value_consistency.json').read_text())
    lines += [f"同版本相鄰月對照 {consistency['compared_prior_month_pairs']:,} 組均一致；但當頁去年同月值與下載的前一年當月表相比，{consistency['compared_prior_year_pairs']:,} 組中有 {consistency['different_previous_year_values']:,} 組不同，可能涉及重編或申報定義，未自行改值。代理不能據此證明當年首次公布版本。", '']
    lines += ['- '+x for x in combined['limitations']]
    lines += ['', '## 重跑', '', '```bash', 'make revenue-proxy-fetch', 'make revenue-proxy-diagnostics', 'make test-revenue-proxy', '```',
              '', '先依 docs/INSTITUTIONAL_RESUME.md 恢復凍結價格與四年法人特徵。已封存營收來源可離線執行 `python3 -m twse_history.revenue_proxy`；`--fetch` 只補缺檔。', '']
    (output / 'report.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/revenue_proxy_protocol.json')
    run(p.parse_args().config)
