"""One frozen objective comparison on owned price data; no parameter search."""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from audit_institutional_increment import PRICE_FEATURES
from research_reassessment import verified_bundle
from research_runtime import atomic_json, sha256, utcnow

CONFIG = Path('configs/ranking_target_protocol_20261023.json')
OUT = Path('deliverables/ranking_target_20261023')
LOCAL = Path('inputs/ranking_target_20261023')
OBJECTIVES = ['return_tree', 'rank_tree']
METHODS = OBJECTIVES+['mom60', 'vol20']


def config():
    c = json.loads(CONFIG.read_text())
    old = json.loads(Path(c['legacy_protocol']).read_text())
    if sha256(c['legacy_protocol']) != c['legacy_protocol_sha256'] or sha256(c['feature_definition_source']) != c['feature_definition_sha256']:
        raise ValueError('Legacy definition drift')
    if c['tree_parameters'] != old['tree_parameters'] or c['features'] != PRICE_FEATURES:
        raise ValueError('Fixed estimator/features differ')
    if c['methods'] != METHODS or c['horizon'] != old['horizon']:
        raise ValueError('Frozen scope differs')
    if any(c[k] != old[k] for k in ['commission', 'sell_tax', 'slippage_each_side']):
        raise ValueError('Frozen costs differ')
    return c


def load_prices(c):
    if sha256(c['prices']) != c['expected_prices_sha256']:
        raise ValueError('Frozen price checksum mismatch')
    columns = ['date', 'symbol', 'close', 'volume', 'turnover_twd', 'adj_open', 'adj_high', 'adj_low', 'adj_close', 'universe_role']
    p = pd.read_csv(c['prices'], usecols=columns, dtype={'symbol': str}, parse_dates=['date'])
    if p.duplicated(['date', 'symbol']).any() or p.date.isna().any() or p.date.max() > pd.Timestamp(c['asof']):
        raise ValueError('Duplicate, missing or out-of-scope prices')
    return p


def verify_sources():
    c = config()
    if sha256(c['prices']) != c['expected_prices_sha256']:
        raise ValueError('Price drift')
    a = c['source_archive']
    original = verified_bundle(a['path'], a['sha256'])
    if original[c['prices']] != c['expected_prices_sha256']:
        raise ValueError('Price/source manifest mismatch')
    for name in a['saved']:
        if verified_bundle(name, a['sha256']) != original:
            raise ValueError('Saved source readback differs')
    OUT.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT/'source_receipt.json', dict(status='passed', verified_at=utcnow(),
        protocol_sha256=sha256(CONFIG), price_sha256=c['expected_prices_sha256'],
        source_archive_sha256=a['sha256'], manifest_files=len(original),
        saved=a['saved'], sha_crc_manifest_readback_verified=True,
        storage='Existing persistent local original, backup and readback on same filesystem; not offsite',
        source_requests=0))


def feature_matrix(prices, c):
    if prices.duplicated(['date', 'symbol']).any():
        raise ValueError('Duplicate price key')
    days = pd.DatetimeIndex(prices.date.unique()).sort_values()
    if prices[prices.symbol.eq('0050')].empty:
        raise ValueError('Missing benchmark')
    benchmark = prices[prices.symbol.eq('0050')].set_index('date').reindex(days)
    bo, bc = benchmark.adj_open.shift(-1), benchmark.adj_close.shift(-c['horizon'])
    br = (bc/bo-1).where(bo.gt(0) & bc.gt(0))
    calendar = pd.DataFrame(dict(date=days,
        entry_date=pd.Series(days).shift(-1), label_window_end=pd.Series(days).shift(-c['horizon'])))
    calendar['score_year'] = calendar.entry_date.dt.year
    first_entries = pd.Series(days, index=days).groupby(days.to_period('M')).first()
    calendar['monthly_signal'] = calendar.entry_date.isin(first_entries.to_numpy())
    frames = []
    for symbol, group in prices[prices.universe_role.eq('common_stock')].groupby('symbol'):
        g = group.set_index('date').reindex(days)
        close = g.adj_close.where(g.adj_close.gt(0))
        f = pd.DataFrame(index=days)
        for period in [1, 5, 20, 60]:
            f['r'+str(period)] = close/close.shift(period)-1
        f['vol20'] = np.log(close/close.shift(1)).rolling(20, min_periods=20).std()
        tr = pd.concat([g.adj_high-g.adj_low, (g.adj_high-close.shift(1)).abs(),
                        (g.adj_low-close.shift(1)).abs()], axis=1).max(axis=1)
        f['atr14'] = tr.rolling(14, min_periods=14).mean()/close
        f['ma5_20'] = close.rolling(5).mean()/close.rolling(20).mean()-1
        f['ma20_60'] = close.rolling(20).mean()/close.rolling(60).mean()-1
        f['volume5_20'] = g.volume.rolling(5).mean()/g.volume.rolling(20).mean()
        turnover = g.turnover_twd.rolling(20, min_periods=20).mean()
        f['log_turnover20'] = np.log(turnover.where(turnover.gt(0)))
        eligible = close.rolling(120, min_periods=120).count().eq(120) & g.close.ge(10) & g.volume.gt(0) & turnover.ge(1e7)
        eligible &= np.isfinite(f[PRICE_FEATURES]).all(axis=1)
        entry, exit_price = g.adj_open.shift(-1), close.shift(-c['horizon'])
        net = exit_price*(1-c['slippage_each_side'])*(1-c['commission']-c['sell_tax'])/(entry*(1+c['slippage_each_side'])*(1+c['commission']))-1
        f['endpoint_target'] = (net-br).where(entry.gt(0) & exit_price.gt(0))
        f['symbol'] = symbol
        f['date'] = days
        frames.append(f[eligible].reset_index(drop=True))
    f = pd.concat(frames, ignore_index=True).merge(calendar, on='date', validate='many_to_one')
    sizes = f.groupby('date').symbol.transform('size')
    f = f[sizes.ge(c['min_pool_size'])].sort_values(['date', 'symbol']).reset_index(drop=True)
    if f.duplicated(['date', 'symbol']).any():
        raise ValueError('Duplicate matrix key')
    return f, calendar


def prepare():
    c = config()
    receipt = json.loads((OUT/'source_receipt.json').read_text())
    if receipt['protocol_sha256'] != sha256(CONFIG) or receipt['status'] != 'passed':
        raise ValueError('Sources not verified for this protocol')
    matrix, calendar = feature_matrix(load_prices(c), c)
    path = LOCAL/'matrix.pkl.gz'
    matrix.to_pickle(path, compression={'method': 'gzip', 'mtime': 0, 'compresslevel': 1})
    calendar.to_csv(LOCAL/'calendar.csv', index=False)
    atomic_json(OUT/'matrix.json', dict(status='passed', rows=len(matrix),
        price_date_range=[str(calendar.date.min().date()), str(calendar.date.max().date())],
        path=str(path), sha256=sha256(path), calendar_sha256=sha256(LOCAL/'calendar.csv'),
        protocol_sha256=sha256(CONFIG), features=PRICE_FEATURES,
        source_receipt_sha256=sha256(OUT/'source_receipt.json'),
        scope='New explicitly price-only pool; not restored old full-feature matrix'))
    print('prepared price-only rows', len(matrix), flush=True)


def load_matrix():
    c = config()
    meta = json.loads((OUT/'matrix.json').read_text())
    if meta['protocol_sha256'] != sha256(CONFIG) or sha256(meta['path']) != meta['sha256'] or sha256(LOCAL/'calendar.csv') != meta['calendar_sha256']:
        raise ValueError('Matrix/protocol/calendar drift')
    return pd.read_pickle(meta['path'], compression='gzip'), meta, c


def training_rows(matrix, year):
    test = matrix[matrix.score_year.eq(year)].copy()
    if test.empty:
        raise ValueError('Empty evaluation year')
    cutoff = min(pd.Timestamp(f'{year-1}-12-31'), test.date.min())
    train = matrix[matrix.date.le(cutoff) & matrix.label_window_end.le(cutoff) & np.isfinite(matrix.endpoint_target)].copy()
    if train.empty or train.label_window_end.max() > test.date.min():
        raise ValueError('Training purge failed')
    # Calculate percentile labels only after whole-date maturity purge.
    train['rank_target'] = train.groupby('date').endpoint_target.rank(method='average', pct=True)
    return train, test, cutoff


def rows_sha(frame):
    return hashlib.sha256(frame[['date', 'symbol']].to_csv(index=False).encode()).hexdigest()


def fit(year, objective):
    if objective not in OBJECTIVES:
        raise ValueError('Unknown fixed objective')
    matrix, meta, c = load_matrix()
    train, test, cutoff = training_rows(matrix, year)
    if len(train) < 1000 or train.date.nunique() < 20:
        raise ValueError('Too few training observations')
    target = train.endpoint_target if objective == 'return_tree' else train.rank_target
    estimator = HistGradientBoostingRegressor(**c['tree_parameters'])
    print('fit', year, objective, 'train', len(train), 'dates', train.date.nunique(), 'test', len(test), flush=True)
    with threadpool_limits(limits=c['threads']):
        estimator.fit(train[PRICE_FEATURES], target)
        scores = estimator.predict(test[PRICE_FEATURES])
    if not np.isfinite(scores).all():
        raise ValueError('Nonfinite predictions')
    model_path = LOCAL/f'{objective}_{year}.joblib'
    score_path = LOCAL/f'{objective}_{year}.npy'
    joblib.dump(estimator, model_path, compress=3)
    np.save(score_path, scores, allow_pickle=False)
    atomic_json(OUT/f'fit_{objective}_{year}.json', dict(year=year, objective=objective,
        model=str(model_path), model_sha256=sha256(model_path), scores=str(score_path), scores_sha256=sha256(score_path),
        protocol_sha256=sha256(CONFIG), matrix_sha256=meta['sha256'],
        train_rows=len(train), train_dates=int(train.date.nunique()),
        train_date_range=[str(train.date.min().date()), str(train.date.max().date())],
        train_last_label_end=str(train.label_window_end.max().date()), cutoff=str(cutoff.date()),
        test_rows=len(test), first_signal=str(test.date.min().date()), last_signal=str(test.date.max().date()),
        training_keys_sha256=rows_sha(train), test_keys_sha256=rows_sha(test),
        features=PRICE_FEATURES, parameters=estimator.get_params(), iterations=int(estimator.n_iter_),
        sklearn_version=sklearn.__version__, target_mean=float(target.mean()), target_std=float(target.std())))
    print('fitted', year, objective, flush=True)


def strict_mean(values):
    a = np.asarray(values, dtype=float)
    return float(a.mean()) if len(a) and np.isfinite(a).all() else np.nan


def evaluate_day(g, count):
    if g.symbol.duplicated().any() or not 1 <= count <= len(g) or not np.isfinite(g[METHODS]).all().all():
        raise ValueError('Invalid scoring pool/count')
    observed = g[np.isfinite(g.endpoint_target)]
    row = dict(date=str(g.date.iloc[0].date()), entry_date=str(g.entry_date.iloc[0].date()),
        label_window_end=str(g.label_window_end.iloc[0].date()) if pd.notna(g.label_window_end.iloc[0]) else None,
        pool=len(g), top_count=count, observed_pool=len(observed), pool_net_relative=strict_mean(g.endpoint_target))
    selections = []
    for method in METHODS:
        top = g.sort_values([method, 'symbol'], ascending=[False, True]).head(count).copy()
        top['method'] = method
        top['rank'] = np.arange(1, count+1)
        top['score'] = top[method]
        selections.append(top[['date', 'symbol', 'entry_date', 'label_window_end', 'method', 'rank', 'score', 'endpoint_target']])
        row[method+'_unknown'] = int((~np.isfinite(top.endpoint_target)).sum())
        row[method+'_net_relative'] = strict_mean(top.endpoint_target)
        ic = observed[method].rank().corr(observed.endpoint_target.rank()) if len(observed) > 2 and observed[method].nunique() > 1 and observed.endpoint_target.nunique() > 1 else np.nan
        row[method+'_rank_ic_observed'] = ic
    return row, pd.concat(selections, ignore_index=True)


def evaluate(year):
    matrix, meta, c = load_matrix()
    _, test, _ = training_rows(matrix, year)
    fits = {}
    for objective in OBJECTIVES:
        receipt = json.loads((OUT/f'fit_{objective}_{year}.json').read_text())
        if receipt['protocol_sha256'] != sha256(CONFIG) or receipt['matrix_sha256'] != meta['sha256'] or receipt['test_keys_sha256'] != rows_sha(test):
            raise ValueError('Fit scope mismatch')
        if sha256(receipt['scores']) != receipt['scores_sha256'] or sha256(receipt['model']) != receipt['model_sha256']:
            raise ValueError('Score/estimator drift')
        test[objective] = np.load(receipt['scores'], allow_pickle=False)
        fits[objective] = receipt
    if fits['return_tree']['training_keys_sha256'] != fits['rank_tree']['training_keys_sha256']:
        raise ValueError('Objective training rows differ')
    test['mom60'] = test.r60
    daily, monthly, selected, monthly_selected = [], [], [], []
    for _, g in test.groupby('date', sort=True):
        row, top = evaluate_day(g, int(np.ceil(len(g)*c['top_fraction'])))
        daily.append(row)
        selected.append(top)
        if g.monthly_signal.all():
            row, top = evaluate_day(g, c['monthly_top_n'])
            monthly.append(row)
            monthly_selected.append(top)
    pd.DataFrame(daily).to_csv(OUT/f'daily_{year}.csv', index=False)
    pd.DataFrame(monthly).to_csv(OUT/f'monthly_{year}.csv', index=False)
    pd.concat(selected, ignore_index=True).to_csv(LOCAL/f'selected_{year}.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0})
    pd.concat(monthly_selected, ignore_index=True).to_csv(OUT/f'monthly_selected_{year}.csv', index=False)
    test.to_pickle(LOCAL/f'scored_{year}.pkl.gz', compression={'method': 'gzip', 'mtime': 0, 'compresslevel': 1})
    paths = [OUT/f'daily_{year}.csv', OUT/f'monthly_{year}.csv', LOCAL/f'selected_{year}.csv.gz', OUT/f'monthly_selected_{year}.csv', LOCAL/f'scored_{year}.pkl.gz']
    atomic_json(OUT/f'evaluation_{year}.json', dict(year=year, status='complete',
        dates=len(daily), monthly_dates=len(monthly), protocol_sha256=sha256(CONFIG),
        input_fit_sha256={str(OUT/f'fit_{o}_{year}.json'): sha256(OUT/f'fit_{o}_{year}.json') for o in OBJECTIVES},
        output_sha256={str(p): sha256(p) for p in paths}))
    print('evaluated', year, len(daily), 'dates', len(monthly), 'months', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['verify_sources', 'prepare', 'fit', 'evaluate'])
    parser.add_argument('--year', type=int, choices=[2024, 2025, 2026])
    parser.add_argument('--objective', choices=OBJECTIVES)
    args = parser.parse_args()
    if args.stage == 'fit':
        fit(args.year, args.objective)
    elif args.stage == 'evaluate':
        evaluate(args.year)
    else:
        globals()[args.stage]()
