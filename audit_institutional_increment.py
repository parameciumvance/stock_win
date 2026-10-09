"""Frozen, exploratory 2023 Ridge comparison on an identical eligible stock pool.

Train labels must end by August 31; score dates September-December. This is a
chronological diagnostic on already researched history, not a fresh holdout.
Quote return proxies, overlapping daily selections, no portfolio NAV/fill claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


PRICE_FEATURES = ['r1', 'r5', 'r20', 'r60', 'vol20', 'atr14', 'ma5_20',
                  'ma20_60', 'volume5_20', 'log_turnover20']
FLOW_FEATURES = [r + f'_net_volume_ratio_{w}d' for r in ('foreign', 'trust', 'total') for w in (1, 5, 20)]


def dataset(price_path, features_path, cutoff, commission, tax, slippage, start_year=2023, end_year=2023,
            *, return_candidates=False, label_read_end=None):
    pieces = []
    use = ['date', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'turnover_twd',
           'adj_open', 'adj_high', 'adj_low', 'adj_close', 'universe_role']
    for chunk in pd.read_csv(price_path, usecols=use, dtype={'symbol': str}, chunksize=200000):
        pieces.append(chunk[chunk.date.ge(f'{start_year}-01-01') & chunk.date.le(
            label_read_end or f'{end_year + 1}-01-31')])
    prices = pd.concat(pieces, ignore_index=True)
    prices['date'] = pd.to_datetime(prices.date)
    if prices.duplicated(['date', 'symbol']).any():
        raise ValueError('Duplicate price date/symbol')
    benchmark = prices[prices.symbol.eq('0050')].set_index('date').sort_index()
    if benchmark.empty or benchmark.index.has_duplicates:
        raise ValueError('Missing/duplicate benchmark quotes')
    # A suspended benchmark does not turn ordinary market sessions into holidays.
    days = pd.DatetimeIndex(prices.date.unique()).sort_values()
    if len(days) < 250 or not days.is_monotonic_increasing or days.has_duplicates:
        raise ValueError('Insufficient/invalid benchmark calendar')
    benchmark = benchmark.reindex(days)
    benchmark_open = benchmark.adj_open.shift(-1)
    benchmark_close = benchmark.adj_close.shift(-20)
    benchmark_future_valid = benchmark.adj_close.where(benchmark.adj_close.gt(0)).shift(-1).iloc[::-1].rolling(20, min_periods=20).count().iloc[::-1].eq(20)
    benchmark_return = (benchmark_close / benchmark_open - 1).where(
        benchmark_future_valid & benchmark_open.gt(0) & benchmark_close.gt(0))
    output = []
    for symbol, group in prices[prices.universe_role.eq('common_stock')].groupby('symbol'):
        g = group.set_index('date').reindex(days)
        close = g.adj_close.where(g.adj_close.gt(0))
        frame = pd.DataFrame(index=days)
        for period in (1, 5, 20, 60):
            frame['r' + str(period)] = close / close.shift(period) - 1
        frame['vol20'] = np.log(close / close.shift(1)).rolling(20, min_periods=20).std()
        tr = pd.concat([g.adj_high - g.adj_low,
                        (g.adj_high - close.shift(1)).abs(),
                        (g.adj_low - close.shift(1)).abs()], axis=1).max(axis=1)
        frame['atr14'] = tr.rolling(14, min_periods=14).mean() / close
        frame['ma5_20'] = close.rolling(5).mean() / close.rolling(20).mean() - 1
        frame['ma20_60'] = close.rolling(20).mean() / close.rolling(60).mean() - 1
        frame['volume5_20'] = g.volume.rolling(5).mean() / g.volume.rolling(20).mean()
        turnover20 = g.turnover_twd.rolling(20, min_periods=20).mean()
        frame['log_turnover20'] = np.log(turnover20.where(turnover20.gt(0)))
        entry = g.adj_open.shift(-1)
        exit_price = close.shift(-20)
        future_valid = close.shift(-1).iloc[::-1].rolling(20, min_periods=20).count().iloc[::-1].eq(20)
        net = exit_price * (1 - slippage) * (1 - commission - tax) / (entry * (1 + slippage) * (1 + commission)) - 1
        frame['target'] = (net - benchmark_return).where(future_valid & entry.gt(0) & exit_price.gt(0))
        if return_candidates:
            frame['future_quotes_complete'] = future_valid
            frame['endpoint_target'] = (net - benchmark_return).where(entry.gt(0) & exit_price.gt(0))
        frame['label_window_end'] = pd.Series(days, index=days).shift(-20)
        frame['eligible'] = close.rolling(120, min_periods=120).count().eq(120) & g.close.ge(10) & g.volume.gt(0) & turnover20.ge(10000000)
        frame['symbol'] = symbol
        frame['date'] = days
        output.append(frame[frame.date.dt.year.between(start_year, end_year)])
    full = pd.concat(output, ignore_index=True)
    flow = pd.read_csv(features_path, dtype={'symbol': str}, parse_dates=['date'])
    if flow.duplicated(['date', 'symbol']).any():
        raise ValueError('Duplicate feature date/symbol')
    if 'institutional_source_date' in flow:
        source_date = pd.to_datetime(flow.institutional_source_date)
        observed = flow[FLOW_FEATURES].notna().any(axis=1)
        if not source_date[observed].lt(flow.loc[observed, 'date']).all():
            raise ValueError('Institutional feature source must precede signal date')
    merged = full.merge(flow[['date', 'symbol'] + FLOW_FEATURES], on=['date', 'symbol'], how='left', validate='one_to_one')
    before_flows = merged.eligible & np.isfinite(merged[PRICE_FEATURES + ['target']]).all(axis=1)
    complete = before_flows & np.isfinite(merged[FLOW_FEATURES]).all(axis=1)
    selected = merged[complete].copy()
    train = selected[selected.date.le(cutoff) & selected.label_window_end.le(cutoff)].copy()
    test = selected[selected.date.gt(cutoff)].copy()
    result = (train, test, {'eligible_price_label_rows': int(before_flows.sum()), 'complete_flow_rows': int(complete.sum()),
                           'flow_complete_fraction': float(complete.sum() / max(1, before_flows.sum()))})
    return result + (merged,) if return_candidates else result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/institutional_diagnostic_2023.json')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if hashlib.sha256(Path(config['prices']).read_bytes()).hexdigest() != config['expected_prices_sha256']:
        raise ValueError('Frozen price input checksum mismatch')
    train, test, coverage = dataset(config['prices'], config['features'], pd.Timestamp(config['train_cutoff']),
                                     config['commission'], config['sell_tax'], config['slippage_each_side'],
                                     config.get('start_year', 2023), config.get('end_year', 2023))
    if len(train) < 1000 or len(test) < 1000:
        raise ValueError('Insufficient training/test rows')
    fitted_models = {}
    for name, columns in [('price_ridge', PRICE_FEATURES), ('price_flow_ridge', PRICE_FEATURES + FLOW_FEATURES)]:
        model = make_pipeline(StandardScaler(), Ridge(alpha=config['ridge_alpha']))
        model.fit(train[columns], train.target)
        test[name] = model.predict(test[columns])
        scaler, ridge = model.steps[0][1], model.steps[1][1]
        fitted_models[name] = {'features': columns, 'scaler_mean': scaler.mean_.tolist(),
                              'scaler_scale': scaler.scale_.tolist(), 'ridge_coefficients': ridge.coef_.tolist(),
                              'ridge_intercept': float(ridge.intercept_)}
    test['vol20_rank'] = test.vol20
    rows = []
    for day, group in test.groupby('date', sort=True):
        if len(group) < config['min_pool_size']:
            continue
        top_count = int(np.ceil(len(group) * config['top_fraction']))
        row = {'date': day.strftime('%Y-%m-%d'), 'pool': len(group), 'top_count': top_count,
               'pool_net_relative': float(group.target.mean())}
        for score in ('price_ridge', 'price_flow_ridge', 'vol20_rank'):
            # Deterministic tie break, without target information.
            top = group.sort_values([score, 'symbol'], ascending=[False, True]).head(top_count)
            row[score + '_top_net_relative'] = float(top.target.mean())
            row[score + '_rank_ic'] = float(group[score].rank().corr(group.target.rank()))
        rows.append(row)
    daily = pd.DataFrame(rows)
    if daily.empty:
        raise ValueError('No eligible test dates')
    path = Path(config['output_directory']);path.mkdir(parents=True, exist_ok=True)
    suffix = config.get('study_name', '2023')
    if not isinstance(suffix, str) or not all(c.isalnum() or c == '_' for c in suffix):
        raise ValueError('Unsafe study name')
    daily.to_csv(path / f'institutional_increment_daily_{suffix}.csv', index=False)
    summary = {'config': config, 'price_features': PRICE_FEATURES, 'flow_features': FLOW_FEATURES,
               'coverage': coverage, 'train_rows': len(train), 'train_signal_dates': train.date.nunique(),
               'train_first_signal': train.date.min().strftime('%Y-%m-%d'),
               'train_last_signal': train.date.max().strftime('%Y-%m-%d'),
               'train_last_label_end': train.label_window_end.max().strftime('%Y-%m-%d'),
               'test_rows': len(test), 'test_dates': len(daily),
               'test_first': daily.date.iloc[0], 'test_last': daily.date.iloc[-1],
               'daily_mean_metrics': daily.drop(columns=['date']).mean().to_dict(),
               'status': 'exploratory_quote_proxy_already_researched_history_not_fresh_holdout',
               'input_sha256': {key: hashlib.sha256(Path(config[key]).read_bytes()).hexdigest() for key in ('prices', 'features')}}
    (path / f'institutional_increment_summary_{suffix}.json').write_text(json.dumps(summary, indent=2) + '\n')
    (path / f'institutional_ridge_models_{suffix}.json').write_text(json.dumps({
        'status': 'research_diagnostic_not_calibrated_surge_probability', 'train_cutoff': config['train_cutoff'],
        'input_sha256': summary['input_sha256'], 'models': fitted_models}, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

