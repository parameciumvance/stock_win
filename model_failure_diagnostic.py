"""Bounded diagnosis of frozen forecasts; no acquisition, fitting or strategy search."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research_reassessment import verified_bundle
from research_runtime import atomic_json, sha256, utcnow

CONFIG = Path('configs/model_failure_diagnostic_20261023.json')
OUT = Path('deliverables/model_failure_diagnostic_20261023')
LOCAL = Path('inputs/model_failure_diagnostic_20261023')
MODELS = ['price_ridge', 'all_ridge', 'price_tree', 'all_tree']
BASELINES = ['mom60', 'vol20']
FEATURES = ['vol20', 'turnover20', 'r60']
SCENARIOS = {'gross': (0., 0., 0.), 'fees_tax': (.001425, .003, 0.),
             'frozen': (.001425, .003, .005)}


def config():
    c = json.loads(CONFIG.read_text())
    original = json.loads(Path('configs/medium_term_protocol.json').read_text())
    if c['horizon'] != original['horizon'] or c['top_n'] != original['monthly']['top_n'] or c['methods'] != original['models']:
        raise ValueError('Diagnostic scope differs from frozen model protocol')
    if c['scenarios'] != {key: list(value) for key, value in SCENARIOS.items()}:
        raise ValueError('Cost definitions differ from frozen diagnostic')
    return c


def require_hashes(expected):
    for name, digest in expected.items():
        if sha256(name) != digest:
            raise ValueError('Frozen input hash mismatch: ' + name)


def strict_mean(values):
    a = np.asarray(values, dtype=float)
    return float(a.mean()) if len(a) and np.isfinite(a).all() else None


def relative_return(ratio, benchmark, scenario):
    fee, tax, slip = SCENARIOS[scenario]
    return ratio * (1-slip) * (1-fee-tax) / ((1+slip)*(1+fee)) - 1 - benchmark


def cutpoints(frame, cutoff):
    train = frame[frame.date.le(pd.Timestamp(cutoff)) & frame.eligible]
    if train.empty or not np.isfinite(train[FEATURES]).all().all():
        raise ValueError('Invalid pre-evaluation reference observations')
    return {key: np.quantile(train[key], [1/3, 2/3]).tolist() for key in FEATURES}


def bin_values(values, cuts):
    a = np.asarray(values, dtype=float)
    if len(cuts) != 2 or not np.isfinite(cuts).all() or cuts[0] > cuts[1]:
        raise ValueError('Invalid frozen group boundaries')
    return np.where(~np.isfinite(a), 'unknown',
                    np.where(a <= cuts[0], 'low', np.where(a <= cuts[1], 'mid', 'high')))


def price_panel(prices, horizon):
    if prices.duplicated(['date', 'symbol']).any() or prices.date.isna().any():
        raise ValueError('Duplicate/missing price key')
    days = pd.DatetimeIndex(prices.date.unique()).sort_values()
    benchmark = prices[prices.symbol.eq('0050')].set_index('date').reindex(days)
    bo = benchmark.adj_open.shift(-1)
    bc = benchmark.adj_close.shift(-horizon)
    br = (bc/bo-1).where(bo.gt(0) & bc.gt(0))
    regime = benchmark.adj_close / benchmark.adj_close.shift(60)-1
    rows = []
    for symbol, g in prices[prices.universe_role.eq('common_stock')].groupby('symbol'):
        g = g.set_index('date').reindex(days)
        close = g.adj_close.where(g.adj_close.gt(0))
        turnover = g.turnover_twd.rolling(20, min_periods=20).mean()
        vol = np.log(close/close.shift(1)).rolling(20, min_periods=20).std()
        r60 = close/close.shift(60)-1
        entry = g.adj_open.shift(-1)
        exit_price = close.shift(-horizon)
        ratio = (exit_price/entry).where(entry.gt(0) & exit_price.gt(0))
        rows.append(pd.DataFrame(dict(date=days, symbol=symbol, vol20=vol.to_numpy(),
            turnover20=turnover.to_numpy(), r60=r60.to_numpy(),
            eligible=(close.rolling(120, min_periods=120).count().eq(120) &
                      g.close.ge(10) & g.volume.gt(0) & turnover.ge(1e7)).to_numpy(),
            ratio=ratio.to_numpy(), benchmark=br.to_numpy(), market_r60=regime.to_numpy(),
            replay_entry=pd.Series(days).shift(-1).to_numpy(),
            replay_end=pd.Series(days).shift(-horizon).to_numpy())))
    return pd.concat(rows, ignore_index=True), days


def validate_selections(selected, methods, top_n):
    if selected.duplicated(['date', 'model', 'symbol']).any():
        raise ValueError('Duplicate selected key')
    for date, g in selected.groupby('date'):
        if set(g.model) != set(methods):
            raise ValueError('Missing selected method on ' + str(date))
        for _, top in g.groupby('model'):
            if len(top) != top_n or sorted(top['rank']) != list(range(1, top_n+1)):
                raise ValueError('Selection count/rank differs')
    if selected.empty or selected[['date', 'entry_date']].isna().any().any():
        raise ValueError('Missing selection dates')
    if not selected.proxy_available_date.le(selected.date).all() or not selected.margin_source_date.lt(selected.date).all():
        raise ValueError('Future feature source')


def verify_inputs():
    c = config()
    require_hashes(c['inputs'])
    archive = c['source_archive']
    manifest = verified_bundle(archive['path'], archive['sha256'])
    if manifest[c['prices']] != c['inputs'][c['prices']]:
        raise ValueError('Source manifest price mismatch')
    for name in archive['saved_copies']:
        if verified_bundle(name, archive['sha256']) != manifest:
            raise ValueError('Backup readback differs')
    OUT.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT/'source_receipt.json', dict(status='passed', verified_at=utcnow(),
        protocol_sha256=sha256(CONFIG), input_sha256=c['inputs'], archive_sha256=archive['sha256'],
        archive_manifest_files=len(manifest), saved_copies=archive['saved_copies'],
        sha_crc_manifest_readback_verified=True, storage='Persistent local original, backup and readback; same filesystem, not offsite',
        scope='Frozen prices and Git-backed selections/daily outputs only; full candidate matrix and estimators absent; no full score replay claimed'))


def replay():
    c = config()
    require_hashes(c['inputs'])
    receipt = json.loads((OUT/'source_receipt.json').read_text())
    if receipt['protocol_sha256'] != sha256(CONFIG) or receipt['status'] != 'passed':
        raise ValueError('Unverified source receipt')
    prices = pd.read_csv(c['prices'], dtype={'symbol': str}, parse_dates=['date'],
        usecols=['date', 'symbol', 'close', 'volume', 'turnover_twd', 'adj_open', 'adj_close', 'universe_role'])
    panel, days = price_panel(prices, c['horizon'])
    cuts = cutpoints(panel, c['group_reference_cutoff'])
    frames = []
    for year in c['years']:
        top = pd.read_csv(f'deliverables/medium_term/monthly_selections_{year}.csv', dtype={'symbol': str},
            parse_dates=['date', 'entry_date', 'label_window_end', 'proxy_available_date', 'margin_source_date'])
        validate_selections(top, c['methods'], c['top_n'])
        summary = json.loads(Path(f'deliverables/medium_term/summary_{year}.json').read_text())
        if pd.Timestamp(summary['train_last_label_end']) > top.date.min():
            raise ValueError('Frozen training label overlaps signal')
        if not top.entry_date.dt.year.eq(year).all():
            raise ValueError('Wrong entry year')
        f = top.merge(panel, on=['date', 'symbol'], how='left', validate='many_to_one')
        if f.eligible.isna().any() or not f.eligible.all():
            raise ValueError('Selected stock outside price eligibility')
        if not f.entry_date.eq(f.replay_entry).all() or not (f.label_window_end.eq(f.replay_end) | (f.label_window_end.isna() & f.replay_end.isna())).all():
            raise ValueError('Endpoint calendar mismatch')
        for name in SCENARIOS:
            f[name] = relative_return(f.ratio, f.benchmark, name)
        if not np.allclose(f.frozen, f.endpoint_target, equal_nan=True, rtol=0, atol=1e-10):
            raise ValueError('Frozen selected endpoint mismatch')
        for feature in FEATURES:
            f[feature+'_group'] = bin_values(f[feature], cuts[feature])
        if not np.isfinite(f.market_r60).all():
            raise ValueError('Unknown prior market regime')
        f['market_group'] = np.where(f.market_r60.gt(0), 'up', 'nonpositive')
        f['year'] = year
        frames.append(f)
    selected = pd.concat(frames, ignore_index=True)
    path = LOCAL/'selected_replay.csv.gz'
    selected.to_csv(path, index=False, compression={'method': 'gzip', 'mtime': 0})
    atomic_json(OUT/'replay.json', dict(status='passed', rows=len(selected),
        selected_sha256=sha256(path), boundaries=cuts, group_reference_cutoff=c['group_reference_cutoff'],
        group_reference='2023 eligible price-pool stock-days; not the original feature-complete common pool; boundaries never fit to later returns',
        signal_range=[str(selected.date.min().date()), str(selected.date.max().date())],
        price_range=[str(days.min().date()), str(days.max().date())],
        selected_unknown_rows=int(selected.frozen.isna().sum()), full_score_replay=False))


def paired_months(frame, model, baseline, value='frozen'):
    means = frame.groupby(['date', 'model'])[value].agg(strict_mean).unstack('model')
    if model not in means or baseline not in means:
        return pd.Series(dtype=float)
    return (means[model]-means[baseline]).dropna()


def overlap_pair(a, b):
    if len(a) != len(b) or a.symbol.duplicated().any() or b.symbol.duplicated().any():
        raise ValueError('Need equal distinct selections')
    shared = set(a.symbol) & set(b.symbol)
    left = a[~a.symbol.isin(shared)]
    right = b[~b.symbol.isin(shared)]
    ma, mb = strict_mean(a.frozen), strict_mean(b.frozen)
    difference = ma-mb if ma is not None and mb is not None else None
    identity = None
    if difference is not None:
        identity = 0. if not len(left) else len(left)/len(a)*(strict_mean(left.frozen)-strict_mean(right.frozen))
        if not np.isclose(identity, difference, rtol=0, atol=1e-12):
            raise ValueError('Exclusive selection identity differs')
    return dict(overlap=len(shared), exclusive_each=len(left), difference=difference,
                exclusive_identity=identity, exclusive_model=strict_mean(left.frozen),
                exclusive_baseline=strict_mean(right.frozen))


def load_replay():
    meta = json.loads((OUT/'replay.json').read_text())
    path = LOCAL/'selected_replay.csv.gz'
    if sha256(path) != meta['selected_sha256']:
        raise ValueError('Replay artifact changed')
    return pd.read_csv(path, dtype={'symbol': str}, parse_dates=['date']), meta


def diagnose():
    c = config()
    require_hashes(c['inputs'])
    f, meta = load_replay()
    costs, pairs, groups, overlaps, exposures = [], [], [], [], []
    for year, y in f.groupby('year'):
        for method, g in y.groupby('model'):
            bydate = g.groupby('date')
            for scenario in SCENARIOS:
                means = bydate[scenario].agg(strict_mean)
                costs.append(dict(year=int(year), method=method, scenario=scenario,
                    known_months=int(means.notna().sum()), total_months=len(means),
                    mean=float(means.dropna().mean()) if means.notna().any() else None))
            for feature in FEATURES:
                for label in ['low', 'mid', 'high']:
                    exposures.append(dict(year=int(year), method=method, feature=feature, group=label,
                        selected_fraction=float(g[feature+'_group'].eq(label).mean())))
        daily = pd.read_csv(f'deliverables/medium_term/daily_{year}.csv', parse_dates=['date'])
        columns = [n+'_top_net_relative' for n in MODELS+BASELINES]
        common = daily[columns].notna().all(axis=1)
        for model in MODELS:
            for baseline in BASELINES:
                diff = daily.loc[common, model+'_top_net_relative']-daily.loc[common, baseline+'_top_net_relative']
                mdiff = paired_months(y, model, baseline)
                pairs.append(dict(year=int(year), model=model, baseline=baseline,
                    daily_common_dates=int(common.sum()), daily_total_dates=len(daily),
                    daily_difference=float(diff.mean()) if len(diff) else None,
                    daily_positive_fraction=float(diff.gt(0).mean()) if len(diff) else None,
                    monthly_paired_dates=len(mdiff), monthly_difference=float(mdiff.mean()) if len(mdiff) else None,
                    monthly_positive_dates=int(mdiff.gt(0).sum())))
                for date, month in y.groupby('date'):
                    o = overlap_pair(month[month.model.eq(model)], month[month.model.eq(baseline)])
                    overlaps.append(dict(year=int(year), date=date.strftime('%Y-%m-%d'), model=model, baseline=baseline, **o))
                for feature, labels in [(x+'_group', ['low', 'mid', 'high']) for x in FEATURES]+[('market_group', ['up', 'nonpositive'])]:
                    for label in labels:
                        cell = y[y[feature].eq(label)]
                        d = paired_months(cell, model, baseline)
                        groups.append(dict(year=int(year), model=model, baseline=baseline, feature=feature, group=label,
                            paired_months=len(d), difference=float(d.mean()) if len(d) else None,
                            positive_months=int(d.gt(0).sum()),
                            selected_model_rows=int(cell.model.eq(model).sum()), selected_baseline_rows=int(cell.model.eq(baseline).sum())))
    for name, rows in [('costs', costs), ('pairs', pairs), ('groups', groups), ('overlap', overlaps), ('exposures', exposures)]:
        pd.DataFrame(rows).to_csv(OUT/(name+'.csv'), index=False)
    atomic_json(OUT/'summary.json', dict(status='completed_exploratory_diagnostic_no_refit',
        monthly_signals=int(f.date.nunique()), selected_rows=len(f), original_methods=c['methods'],
        model_baseline_pairs=pairs, protocol_sha256=sha256(CONFIG), replay_sha256=meta['selected_sha256'],
        fit_count=0, new_source_requests=0, trading_orders=0,
        limitations=c['limitations']))


def audit():
    c = config()
    require_hashes(c['inputs'])
    f, meta = load_replay()
    # Independent scalar lookup, rather than the replay's per-symbol shift implementation.
    prices = pd.read_csv(c['prices'], dtype={'symbol': str}, parse_dates=['date'],
        usecols=['date', 'symbol', 'adj_open', 'adj_close'])
    dates = sorted(prices.date.unique())
    clock = {date: i for i, date in enumerate(dates)}
    lookup = {(r.date, r.symbol): (r.adj_open, r.adj_close) for r in prices.itertuples(index=False)}
    maximum = 0.
    for row in f.itertuples(index=False):
        index = clock[row.date]
        def valid_ratio(symbol):
            if index+c['horizon'] >= len(dates):
                return np.nan
            entry = lookup.get((dates[index+1], symbol), (np.nan, np.nan))[0]
            exit_price = lookup.get((dates[index+c['horizon']], symbol), (np.nan, np.nan))[1]
            return exit_price/entry if entry > 0 and exit_price > 0 else np.nan
        stock, benchmark = valid_ratio(row.symbol), valid_ratio('0050')
        for name, (fee, tax, slip) in SCENARIOS.items():
            # Independently express cash spent/received for one synthetic adjusted unit.
            expected = stock*(1-slip)*(1-fee-tax)/((1+slip)*(1+fee))-benchmark
            actual = getattr(row, name)
            if not np.isclose(expected, actual, equal_nan=True, rtol=0, atol=1e-10):
                raise ValueError('Independent scalar endpoint/cost failure')
            if np.isfinite(expected):
                maximum = max(maximum, abs(expected-actual))
    for year in c['years']:
        old = pd.read_csv(f'deliverables/medium_term/monthly_{year}.csv', parse_dates=['date']).set_index('date')
        for (date, method), g in f[f.year.eq(year)].groupby(['date', 'model']):
            mean = strict_mean(g.frozen)
            prior = old.loc[date, method+'_top_net_relative']
            if not np.isclose(np.nan if mean is None else mean, prior, equal_nan=True, rtol=0, atol=1e-10):
                raise ValueError('Frozen monthly cohort mismatch')
    # Audit every published aggregate against independently enumerated rows.
    costs = pd.read_csv(OUT/'costs.csv')
    for r in costs.itertuples(index=False):
        g = f[(f.year == r.year) & f.model.eq(r.method)]
        values = [strict_mean(x[r.scenario]) for _, x in g.groupby('date')]
        known = [v for v in values if v is not None]
        expected = sum(known)/len(known) if known else np.nan
        if len(known) != r.known_months or not np.isclose(expected, r.mean, equal_nan=True, atol=1e-10, rtol=0):
            raise ValueError('Cost summary mismatch')
    groups = pd.read_csv(OUT/'groups.csv')
    for r in groups.itertuples(index=False):
        g = f[(f.year == r.year) & f[r.feature].eq(r.group)]
        values = []
        for _, month in g.groupby('date'):
            left = strict_mean(month[month.model.eq(r.model)].frozen)
            right = strict_mean(month[month.model.eq(r.baseline)].frozen)
            if left is not None and right is not None:
                values.append(left-right)
        mean = sum(values)/len(values) if values else np.nan
        if len(values) != r.paired_months or not np.isclose(mean, r.difference, equal_nan=True, atol=1e-10, rtol=0):
            raise ValueError('Group summary mismatch')
    pairs = pd.read_csv(OUT/'pairs.csv')
    for r in pairs.itertuples(index=False):
        daily = pd.read_csv(f'deliverables/medium_term/daily_{r.year}.csv')
        columns = [method+'_top_net_relative' for method in MODELS+BASELINES]
        differences = [row[r.model+'_top_net_relative']-row[r.baseline+'_top_net_relative']
                       for row in daily.to_dict('records') if all(np.isfinite(row[k]) for k in columns)]
        months = []
        for _, month in f[f.year.eq(r.year)].groupby('date'):
            left = strict_mean(month[month.model.eq(r.model)].frozen)
            right = strict_mean(month[month.model.eq(r.baseline)].frozen)
            if left is not None and right is not None:
                months.append(left-right)
        if len(differences) != r.daily_common_dates or len(months) != r.monthly_paired_dates:
            raise ValueError('Paired date counts differ')
        if not np.isclose(sum(differences)/len(differences), r.daily_difference, rtol=0, atol=1e-10) or not np.isclose(sum(months)/len(months), r.monthly_difference, rtol=0, atol=1e-10):
            raise ValueError('Paired mean differs')
    overlaps = pd.read_csv(OUT/'overlap.csv', parse_dates=['date'])
    for r in overlaps.itertuples(index=False):
        month = f[f.date.eq(r.date)]
        a = dict(zip(month[month.model.eq(r.model)].symbol, month[month.model.eq(r.model)].frozen))
        b = dict(zip(month[month.model.eq(r.baseline)].symbol, month[month.model.eq(r.baseline)].frozen))
        if len(set(a)&set(b)) != r.overlap:
            raise ValueError('Overlap count differs')
        known = all(np.isfinite(v) for v in list(a.values())+list(b.values()))
        expected = sum(a.values())/len(a)-sum(b.values())/len(b) if known else np.nan
        if not np.isclose(expected, r.difference, rtol=0, atol=1e-10, equal_nan=True) or not np.isclose(expected, r.exclusive_identity, rtol=0, atol=1e-10, equal_nan=True):
            raise ValueError('Overlap identity differs')
    exposures = pd.read_csv(OUT/'exposures.csv')
    for r in exposures.itertuples(index=False):
        selected = f[(f.year == r.year) & f.model.eq(r.method)]
        expected = sum(value == r.group for value in selected[r.feature+'_group'])/len(selected)
        if not np.isclose(expected, r.selected_fraction, rtol=0, atol=1e-12):
            raise ValueError('Exposure summary differs')
    atomic_json(OUT/'audit.json', dict(status='passed', scalar_rows=len(f),
        max_endpoint_error=maximum, frozen_monthly_cohorts_verified=True,
        cost_aggregates=len(costs), group_aggregates=len(groups), paired_aggregates=len(pairs), overlap_month_pairs=len(overlaps), exposure_aggregates=len(exposures),
        unknown_selected_rows=int(f.frozen.isna().sum()),
        outputs_sha256={str(OUT/name): sha256(OUT/name) for name in ['costs.csv', 'pairs.csv', 'groups.csv', 'overlap.csv', 'exposures.csv', 'summary.json']}))


def report():
    audit_record = json.loads((OUT/'audit.json').read_text())
    if audit_record['status'] != 'passed':
        raise ValueError('Audit not passed')
    require_hashes(audit_record['outputs_sha256'])
    summary = json.loads((OUT/'summary.json').read_text())
    replay_meta = json.loads((OUT/'replay.json').read_text())
    costs = pd.read_csv(OUT/'costs.csv')
    lines = ['# 既有模型失敗診斷：停止擴充來源，使用凍結資料', '',
        '本輪沒有抓新資料、重訓或調參。使用截至2026-10-02的原價格、原七法月度Top15與逐日結果，診斷四個模型相對動能／波動基準的增量。這是已看過歷史的描述性比較，不是新留出驗證。', '',
        f"原價格範圍 {replay_meta['price_range']}；月訊號 {summary['monthly_signals']} 個、選股列 {summary['selected_rows']}，未知結果列 {replay_meta['selected_unknown_rows']}。原始包、備份取回的SHA／CRC／manifest核對通過；選股端點與成本另由獨立逐筆查價核對。", '',
        '## 1. 相同日期比較模型與簡單基準', '',
        '下表是每日Top10%之60日相對端點代理的模型減基準，百分點。每年共同使用六法結果皆完整的日期，避免不同方法缺值樣本不一致。不是年度報酬；不以勝出日期比例作顯著性檢定。', '',
        '| 年度 | 模型 | 對動能 | 對波動 | 共同日／原日 |', '|---|---|---:|---:|---:|']
    pairs = pd.read_csv(OUT/'pairs.csv')
    for (year, model), g in pairs.groupby(['year', 'model'], sort=False):
        a = g.set_index('baseline')
        lines.append(f"| {year} | {model} | {a.loc['mom60','daily_difference']*100:+.3f} | {a.loc['vol20','daily_difference']*100:+.3f} | {a.iloc[0].daily_common_dates:.0f}／{a.iloc[0].daily_total_dates:.0f} |")
    lines += ['', '## 2. 月度Top15：毛相對、費稅、原成本', '',
        '三欄均減同期間0050毛報酬；同一批原選股，只改列示成本分解，沒有重新選股。費稅欄含原手續費與股票稅；原成本再含每邊0.5%價格偏移。任何選中結果未知，整個月均值維持未知，沒有刪股或補零。', '',
        '| 年 | 方法 | 毛相對% | 費稅後% | 原成本後% | 已知／全部月 |', '|---|---|---:|---:|---:|---:|']
    for (year, method), g in costs.groupby(['year', 'method'], sort=False):
        a = g.set_index('scenario')
        lines.append(f"| {year} | {method} | {a.loc['gross','mean']*100:+.3f} | {a.loc['fees_tax','mean']*100:+.3f} | {a.loc['frozen','mean']*100:+.3f} | {a.loc['frozen','known_months']:.0f}／{a.loc['frozen','total_months']:.0f} |")
    lines += ['', '同比例費用下，同一配對日期模型減基準的差只乘正的成本係數，不能靠移除這項成本顛倒模型排名。成本影響是否跑贏0050；不能單獨解釋模型為何輸給簡單排序。最低費、換手、實際撮合與權益現金流不在這個端點分析內。', '',
        '## 3. 股票群與重疊選股', '',
        '流動性（20日成交金額）、波動與60日動能，皆依2023年價格合格池的股票日分布固定三等分邊界，再套到2024–2026原選股。不是依未來報酬挑群；沒有產業／市值資料，因此不冒充產業或規模歸因。市場分組只用訊號當時0050過去60日漲跌。', '',
        'groups.csv保留所有群、全部四模型×兩基準×三年比較及配對月數；exposures.csv列選股集中度。群內比較只用兩方法都選到該群且結果完整的同月，是條件診斷，未證明控制曝險後的獨立Alpha。', '',
        'overlap.csv逐月列交集、各自獨有股與差異貢獻；等權同15檔時，整體差異＝獨有比例×獨有股報酬差。共同持股的報酬會相消。末端未知仍保留；不把既有候選全集或模型分數重播說成已完成。', '',
        '## 邊界與結案條件', '',
        '34個月訊號的60日窗口重疊，每年只有7–12個成熟月；本輪不報可靠顯著性、不挑最好群當新策略。日表也有重疊窗口與缺價造成的共同日期限制。營收是45日延遲修訂代理；原資料與股票池偏誤仍保留。完整候選矩陣／樹模型不在本地，因此本輪驗證原選股與端點，沒有重播全部候選分數。', '',
        '診斷完成即停止本輪，不自動新增來源或依結果調參。只有一個可事先寫明、與已試方法有實質差異的假說，才值得另外凍結新實驗。七規則每日人工驗證維持停止，沒有有效訊號或實際訂單。', '',
        '機器結果：summary.json、pairs.csv、costs.csv、groups.csv、overlap.csv、exposures.csv；來源與重播：source_receipt.json、replay.json、audit.json。']
    groups = pd.read_csv(OUT/'groups.csv')
    findings = ['', '以下以全特徵樹對動能為固定展示，單位為百分點（配對月數）；其他三個模型與波動基準的完整結果皆保留，沒有用本表選新策略。', '',
        '| 特徵群 | 2024 | 2025 | 2026 |', '|---|---:|---:|---:|']
    labels = [('vol20_group', '波動'), ('turnover20_group', '成交金額'), ('r60_group', '動能'), ('market_group', '市場過去60日')]
    for feature, title in labels:
        levels = ['up', 'nonpositive'] if feature == 'market_group' else ['low', 'mid', 'high']
        for level in levels:
            cells = []
            for year in config()['years']:
                r = groups[(groups.model == 'all_tree') & (groups.baseline == 'mom60') &
                           (groups.year == year) & groups.feature.eq(feature) & groups.group.eq(level)].iloc[0]
                cells.append(f'{r.difference*100:+.2f}（{r.paired_months}）' if r.paired_months else '無配對')
            findings.append('| '+title+'／'+level+' | '+' | '.join(cells)+' |')
    overlaps = pd.read_csv(OUT/'overlap.csv')
    shared = overlaps[(overlaps.model == 'all_tree') & (overlaps.baseline == 'mom60')].overlap.mean()
    findings += ['', '## 4. 這次診斷改變了什麼判斷', '',
        '四模型在2024共同日期都勝過兩種簡單排序，2025卻全數落後；2026樹模型改善而Ridge較弱。這支持「效果依年份／市場條件改變」，不支持已有一個跨年穩定勝出的模型，也不能把三年比較稱三次全新驗證。', '',
        '成本並非主要且唯一解釋：2025全特徵樹月度Top15在零成本時仍落後0050約12.11個百分點，原成本後約13.65個百分點；動能零成本時約落後0.03個百分點。2026全特徵樹原成本後約領先3.33個百分點，只有7個成熟月；不能只採用這一段。這些都是平均60日端點差，不是年度損益。', '',
        '粗分股票群沒有消除年度反覆：全特徵樹對動能在高成交金額群的2024／2025／2026差為約−6.18／−6.65／+15.12個百分點；高波動群亦由2025負轉2026正。2025市場過去60日上漲群仍落後，2026同類群改善，因此只用這個市場漲跌開關也不足以解釋。這不是群內風險相同或因果結論。', '',
        f'全特徵樹與動能每月平均僅共享{shared:.2f}／15檔，表示模型確實選了不同股票；不同本身沒有帶來跨年穩定增量。低流動性2026看似很高的群內差只有2個配對月，不能變成推薦門檻。', '',
        '本輪結論是保留既有模型作研究基準，停止擴充資料與無目標換演算法。若另做實驗，必須有不同於「換模型就會賺」的明確預測；不能從本輪最好年份或子群直接反向選規則。']
    index = lines.index('## 邊界與結案條件')
    lines[index:index] = findings+['']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')
    atomic_json(OUT/'next_tasks.json', dict(status='completed_bounded_diagnosis', completed=['frozen input verification', 'independent endpoint replay', 'same-date model/baseline contrasts', 'cost and fixed pre-evaluation stock-group diagnostics'],
        automatically_acquire_more_data=False, automatically_tune_models=False, valid_signal_date=None,
        next_research_gate='One distinct falsifiable hypothesis and frozen finite comparison; no recycled year called fresh holdout'))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['verify_inputs', 'replay', 'diagnose', 'audit', 'report'])
    globals()[p.parse_args().stage]()
