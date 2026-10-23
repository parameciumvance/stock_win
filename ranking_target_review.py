"""Independent score/selection/endpoint audit and fixed-objective research report."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from threadpoolctl import threadpool_limits

from ranking_target_research import (CONFIG, OUT, LOCAL, METHODS, OBJECTIVES,
    PRICE_FEATURES, config, load_matrix, load_prices, rows_sha, strict_mean, training_rows)
from research_runtime import atomic_json, sha256


def check_hashes(mapping):
    for path, digest in mapping.items():
        if sha256(path) != digest:
            raise ValueError('Artifact drift: '+path)


def calendar_interval(values, block, replicates, seed):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or np.isinf(values).any() or block < 1 or replicates < 100:
        raise ValueError('Invalid block inputs')
    n = len(values)
    known = int(np.isfinite(values).sum())
    result = dict(calendar_positions=n, paired_dates=known, missing_positions=n-known,
        mean=float(np.nanmean(values)) if known else None, block=block)
    if n <= block or known <= block:
        return dict(**result, status='insufficient_paired_dates_no_shortened_block')
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(replicates, int(np.ceil(n/block))))
    indices = ((starts[:, :, None]+np.arange(block)) % n).reshape(replicates, -1)[:, :n]
    draws = values[indices]
    counts = np.isfinite(draws).sum(axis=1)
    invalid = int((counts == 0).sum())
    if invalid:
        return dict(**result, status='undefined_draws_no_interval', undefined_draws=invalid)
    means = np.nansum(draws, axis=1)/counts
    lo, hi = np.quantile(means, [.025, .975])
    return dict(**result, status='descriptive_circular_block_interval',
        lower_95=float(lo), upper_95=float(hi), undefined_draws=0)


def missing_reason(end_date, stock_entry, stock_exit, benchmark_entry, benchmark_exit):
    if pd.isna(end_date):
        return 'not_mature_by_asof'
    reasons = []
    for name, quote in [('stock_entry', stock_entry), ('stock_exit', stock_exit),
                        ('benchmark_entry', benchmark_entry), ('benchmark_exit', benchmark_exit)]:
        if not np.isfinite(quote) or quote <= 0:
            reasons.append(name+'_unavailable')
    return ';'.join(reasons) if reasons else None


def audit():
    matrix, meta, c = load_matrix()
    prices = load_prices(c)
    clock = pd.DatetimeIndex(prices.date.unique()).sort_values()
    positions = {date: i for i, date in enumerate(clock)}
    quotes = {(r.date, r.symbol): (r.adj_open, r.adj_close) for r in prices.itertuples(index=False)}
    studies, monthly_gaps = [], []
    max_score_error, max_endpoint_error, endpoint_rows = 0., 0., 0
    for year in c['years']:
        evaluation = json.loads((OUT/f'evaluation_{year}.json').read_text())
        check_hashes(evaluation['output_sha256'])
        check_hashes(evaluation['input_fit_sha256'])
        train, test, cutoff = training_rows(matrix, year)
        scored = pd.read_pickle(LOCAL/f'scored_{year}.pkl.gz', compression='gzip')
        if not test[['date', 'symbol']].equals(scored[['date', 'symbol']]) or train.label_window_end.max() > min(cutoff, test.date.min()):
            raise ValueError('Train/evaluation chronology mismatch')
        for objective in OBJECTIVES:
            receipt = json.loads((OUT/f'fit_{objective}_{year}.json').read_text())
            if receipt['training_keys_sha256'] != rows_sha(train) or receipt['test_keys_sha256'] != rows_sha(test) or receipt['protocol_sha256'] != sha256(CONFIG) or receipt['matrix_sha256'] != meta['sha256']:
                raise ValueError('Training/evaluation keys differ')
            if sha256(receipt['model']) != receipt['model_sha256']:
                raise ValueError('Estimator differs')
            estimator = joblib.load(receipt['model'])  # hash-verified, self-generated only
            if list(estimator.feature_names_in_) != PRICE_FEATURES or any(estimator.get_params()[k] != v for k, v in c['tree_parameters'].items()):
                raise ValueError('Feature/parameter drift')
            with threadpool_limits(limits=c['threads']):
                pred = estimator.predict(test[PRICE_FEATURES])
            error = float(np.max(np.abs(pred-scored[objective].to_numpy())))
            max_score_error = max(max_score_error, error)
            if error > 1e-12:
                raise ValueError('Independent score replay mismatch')
        selected_all = []
        cohorts = 0
        for kind in ['daily', 'monthly']:
            path = LOCAL/f'selected_{year}.csv.gz' if kind == 'daily' else OUT/f'monthly_selected_{year}.csv'
            top = pd.read_csv(path, dtype={'symbol': str}, parse_dates=['date', 'entry_date', 'label_window_end'])
            if top.duplicated(['date', 'method', 'symbol']).any():
                raise ValueError('Duplicate selected key')
            result = pd.read_csv(OUT/f'{kind}_{year}.csv', parse_dates=['date']).set_index('date')
            subset = scored if kind == 'daily' else scored[scored.monthly_signal]
            expected_cohorts = subset.date.nunique()*len(METHODS)
            if len(top.groupby(['date', 'method'])) != expected_cohorts or set(result.index) != set(subset.date):
                raise ValueError('Missing cohort/date')
            for date, g in subset.groupby('date'):
                n = int(np.ceil(len(g)*c['top_fraction'])) if kind == 'daily' else c['monthly_top_n']
                for method in METHODS:
                    # Independently sort scalar score/symbol tuples, without target information.
                    expected = [symbol for _, symbol in sorted(zip(-g[method], g.symbol))[:n]]
                    chosen = top[top.date.eq(date) & top.method.eq(method)].sort_values('rank')
                    if chosen.symbol.tolist() != expected or chosen['rank'].tolist() != list(range(1, n+1)):
                        raise ValueError('Independent selection/rank mismatch')
                    values = chosen.endpoint_target.to_numpy()
                    unknown = sum(not np.isfinite(v) for v in values)
                    mean = sum(values)/len(values) if not unknown else np.nan
                    if unknown != result.loc[date, method+'_unknown'] or not np.isclose(mean, result.loc[date, method+'_net_relative'], equal_nan=True, rtol=0, atol=1e-12):
                        raise ValueError('Independent cohort aggregation mismatch')
                    observed = g[np.isfinite(g.endpoint_target)]
                    ic = float(spearmanr(observed[method], observed.endpoint_target).statistic) if len(observed) > 2 and observed[method].nunique() > 1 and observed.endpoint_target.nunique() > 1 else np.nan
                    if not np.isclose(ic, result.loc[date, method+'_rank_ic_observed'], equal_nan=True, rtol=0, atol=1e-12):
                        raise ValueError('Independent rank correlation mismatch')
                    cohorts += 1
            selected_all.append(top)
        unique = pd.concat(selected_all, ignore_index=True).drop_duplicates(['date', 'symbol'])
        missing = {}
        for row in unique.itertuples(index=False):
            pos = positions[row.date]
            expected_entry = clock[pos+1]
            expected_end = clock[pos+c['horizon']] if pos+c['horizon'] < len(clock) else pd.NaT
            if row.entry_date != expected_entry or not (row.label_window_end == expected_end or (pd.isna(row.label_window_end) and pd.isna(expected_end))):
                raise ValueError('Independent market-day horizon differs')
            def ratio(symbol):
                if pd.isna(expected_end):
                    return np.nan
                entry = quotes.get((expected_entry, symbol), (np.nan, np.nan))[0]
                exit_price = quotes.get((expected_end, symbol), (np.nan, np.nan))[1]
                return exit_price/entry if entry > 0 and exit_price > 0 else np.nan
            factor = (1-c['slippage_each_side'])*(1-c['commission']-c['sell_tax'])/((1+c['slippage_each_side'])*(1+c['commission']))
            expected = ratio(row.symbol)*factor-ratio('0050')
            if not np.isclose(expected, row.endpoint_target, equal_nan=True, atol=1e-10, rtol=0):
                raise ValueError('Independent price endpoint mismatch')
            if np.isfinite(expected):
                max_endpoint_error = max(max_endpoint_error, abs(expected-row.endpoint_target))
            else:
                missing[(row.date, row.symbol)] = missing_reason(expected_end,
                    quotes.get((expected_entry, row.symbol), (np.nan, np.nan))[0],
                    quotes.get((expected_end, row.symbol), (np.nan, np.nan))[1],
                    quotes.get((expected_entry, '0050'), (np.nan, np.nan))[0],
                    quotes.get((expected_end, '0050'), (np.nan, np.nan))[1])
            endpoint_rows += 1
        for row in selected_all[1][selected_all[1].endpoint_target.isna()].itertuples(index=False):
            monthly_gaps.append(dict(year=year, date=str(row.date.date()), symbol=row.symbol,
                method=row.method, entry_date=str(row.entry_date.date()),
                label_window_end=str(row.label_window_end.date()) if pd.notna(row.label_window_end) else None,
                reason=missing[(row.date, row.symbol)]))
        studies.append(dict(year=year, train_rows=len(train), train_dates=int(train.date.nunique()),
            last_training_endpoint=str(train.label_window_end.max().date()), test_rows=len(test),
            independently_replayed_selection_cohorts=cohorts, unique_selected_endpoints=len(unique)))
    pd.DataFrame(monthly_gaps, columns=['year', 'date', 'symbol', 'method', 'entry_date', 'label_window_end', 'reason']).to_csv(OUT/'monthly_missing.csv', index=False)
    atomic_json(OUT/'audit.json', dict(status='passed', studies=studies, actual_estimators=6,
        protocol_sha256=sha256(CONFIG), matrix_sha256=meta['sha256'],
        max_score_error=max_score_error, max_endpoint_error=max_endpoint_error,
        independently_looked_up_endpoints=endpoint_rows, rank_correlations_independently_checked=True,
        monthly_missing_sha256=sha256(OUT/'monthly_missing.csv'), no_trading_claim=True))
    print('audit passed; endpoint lookups', endpoint_rows, flush=True)


def gate(year_summaries):
    primary = all(s['comparisons']['return_tree']['mean'] is not None and s['comparisons']['return_tree']['mean'] > 0 for s in year_summaries)
    baseline_years = sum(all(s['comparisons'][b]['mean'] is not None and s['comparisons'][b]['mean'] > 0 for b in ['mom60', 'vol20']) for s in year_summaries)
    return dict(passed=bool(len(year_summaries) == 3 and primary and baseline_years >= 2),
        positive_primary_in_all_years=primary, years_beating_both_baselines=baseline_years,
        interpretation='Descriptive predeclared continuation gate on reused history, not independent validation or trading qualification')


def summarize_year(year, c):
    daily = pd.read_csv(OUT/f'daily_{year}.csv', parse_dates=['date'])
    monthly = pd.read_csv(OUT/f'monthly_{year}.csv', parse_dates=['date'])
    calendar = pd.read_csv(LOCAL/'calendar.csv', parse_dates=['date', 'label_window_end'])
    mature = calendar.score_year.eq(year) & calendar.label_window_end.le(pd.Timestamp(c['asof']))
    dates = pd.DatetimeIndex(calendar.loc[mature, 'date'])
    columns = [m+'_net_relative' for m in METHODS]
    common = daily[columns].notna().all(axis=1)
    monthly_common = monthly[columns].notna().all(axis=1)
    comparisons = {}
    for baseline in ['return_tree', 'mom60', 'vol20']:
        difference = (daily.rank_tree_net_relative-daily[baseline+'_net_relative']).where(common)
        on_calendar = pd.Series(difference.to_numpy(), index=daily.date).reindex(dates).to_numpy()
        ci = {str(b): calendar_interval(on_calendar, b, c['uncertainty']['replicates'], c['uncertainty']['seed']) for b in c['uncertainty']['blocks']}
        md = monthly.loc[monthly_common, 'rank_tree_net_relative']-monthly.loc[monthly_common, baseline+'_net_relative']
        comparisons[baseline] = dict(mean=float(difference[common].mean()) if common.any() else None,
            monthly_mean=float(md.mean()) if len(md) else None, intervals=ci)
    methods = {}
    for method in METHODS:
        methods[method] = dict(daily_common_mean=float(daily.loc[common, method+'_net_relative'].mean()) if common.any() else None,
            monthly_common_mean=float(monthly.loc[monthly_common, method+'_net_relative'].mean()) if monthly_common.any() else None,
            daily_own_known_dates=int(daily[method+'_net_relative'].notna().sum()),
            daily_unknown_selected_rows=int(daily[method+'_unknown'].sum()),
            monthly_own_known_dates=int(monthly[method+'_net_relative'].notna().sum()),
            monthly_unknown_selected_rows=int(monthly[method+'_unknown'].sum()),
            rank_ic_common_observed=float(daily.loc[common, method+'_rank_ic_observed'].mean()))
    return dict(year=year, daily_dates=len(daily), mature_calendar_dates=len(dates), daily_common_dates=int(common.sum()),
        excluded_daily_dates=int((~common).sum()), monthly_dates=len(monthly), monthly_common_dates=int(monthly_common.sum()),
        comparisons=comparisons, methods=methods)


def report():
    c = config()
    audit_record = json.loads((OUT/'audit.json').read_text())
    if audit_record['status'] != 'passed' or audit_record['protocol_sha256'] != sha256(CONFIG):
        raise ValueError('Audit not current')
    for year in c['years']:
        check_hashes(json.loads((OUT/f'evaluation_{year}.json').read_text())['output_sha256'])
    years = [summarize_year(year, c) for year in c['years']]
    decision = gate(years)
    status = 'descriptive_gate_passed_requires_new_evidence' if decision['passed'] else 'closed_objective_branch_gate_failed_no_retuning'
    atomic_json(OUT/'summary.json', dict(status=status, protocol_sha256=sha256(CONFIG),
        fits=6, source_requests=0, years=years, continuation_gate=decision,
        limitations=c['limitations'], valid_signal_date=None, orders=0))
    lines = ['# 固定建模實驗：報酬目標與排名目標', '',
        '本輪實際完成六次訓練：兩個相同固定梯度樹、三個年度折，唯一訓練目標差異為60日成本後相對0050報酬或同日未來報酬百分位。使用凍結價量資料，沒有新增來源、特徵或搜尋參數。', '',
        '價格2023-01-03至2026-10-02；十項量價特徵與原樹參數相同。四法共用本輪明定的量價股票池；它不同於舊研究要求基本面完整的池，因此這是本輪控制比較，不宣稱重現舊全特徵模型。', '',
        '## 每日Top10%：共同日期的平均60日成本後相對0050代理', '',
        '單位為百分點，不是年度報酬。所有方法在相同已知日期比較；選股本身不依未來完整性過濾。未知選股仍保留，整個當日均值未知。共同已知子樣本可能非隨機，不外推至全部訊號。', '',
        '| 年 | 報酬樹 | 排名樹 | 動能 | 波動 | 共同／全部日 |', '|---|---:|---:|---:|---:|---:|']
    fmt = lambda x: f'{x*100:+.3f}' if x is not None else '未知'
    for s in years:
        lines.append('| '+str(s['year'])+' | '+' | '.join(fmt(s['methods'][m]['daily_common_mean']) for m in METHODS)+f" | {s['daily_common_dates']}／{s['daily_dates']} |")
    lines += ['', '## 排名樹減報酬樹：主要比較', '',
        '| 年 | 平均差pp | 60日區塊95%描述區間pp | 原成熟市場日位置／已知配對日 |', '|---|---:|---|---:|']
    for s in years:
        p = s['comparisons']['return_tree']
        ci = p['intervals']['60']
        interval = f"[{fmt(ci['lower_95'])}, {fmt(ci['upper_95'])}]" if 'lower_95' in ci else ci['status']
        lines.append(f"| {s['year']} | {fmt(p['mean'])} | {interval} | {ci['calendar_positions']}／{ci['paired_dates']} |")
    lines += ['', '區塊在原成熟市場日位置上取樣，保留缺值，不把有缺口的日期壓成連續日。circular邊界與非平穩市場仍限制推論；20／80日敏感度全列於summary.json，不挑最好區塊。2024–2026已反覆研究，這些區間不是新的獨立確認。', '',
        '## 整體排名相關性與前段報酬並非同一件事', '',
        '下表為相同共同日期、當日端點已知股票子池上的Spearman IC日均值。它衡量整體排序，不能等同前段選股報酬或收益機率；未知端點股票未被移出當時候選或選股。', '',
        '| 年 | 報酬樹IC | 排名樹IC |', '|---|---:|---:|']
    for s in years:
        lines.append(f"| {s['year']} | {s['methods']['return_tree']['rank_ic_common_observed']:+.4f} | {s['methods']['rank_tree']['rank_ic_common_observed']:+.4f} |")
    lines += ['', '本輪三年整體IC均提高，但2026每日Top10%的主要報酬比較反而下降，說明整體排序改善沒有自動變成前段的穩定成本後優勢。月度Top15的改善保留列示，不把它事後改成主要判準。', '',
        '## 月度Top15：相同已知月份', '',
        '| 年 | 報酬樹 | 排名樹 | 動能 | 波動 | 共同／全部月 |', '|---|---:|---:|---:|---:|---:|']
    for s in years:
        lines.append('| '+str(s['year'])+' | '+' | '.join(fmt(s['methods'][m]['monthly_common_mean']) for m in METHODS)+f" | {s['monthly_common_dates']}／{s['monthly_dates']} |")
    gaps = pd.read_csv(OUT/'monthly_missing.csv', dtype={'symbol': str})
    if sha256(OUT/'monthly_missing.csv') != audit_record['monthly_missing_sha256']:
        raise ValueError('Missing-endpoint inventory differs')
    mature_gaps = gaps[~gaps.reason.eq('not_mature_by_asof')]
    lines += ['', '月度也是固定60日端點均值，窗口重疊、每年成熟月數少；沒有模擬可實現組合NAV、最低費、換手及實際權益現金流。未知月份沒有補零或替補。', '',
        f"月度缺口另列monthly_missing.csv：尚未成熟的選股列{int(gaps.reason.eq('not_mature_by_asof').sum())}筆，已到端點但報價不可用的選股列{len(mature_gaps)}筆。2025年2809造成1個月不可共同比較；2026年3454造成3個已成熟月無法共同比較，加上3個未成熟月，故2026只剩4個共同月份。這只描述固定檔的端點缺報價，未查證其公司行動原因，也不編造退出價或現金對價。", '',
        '## 訓練與稽核', '', '| 年 | 訓練股票日 | 訓練訊號日 | 最後訓練端點 | 評估股票日 |', '|---|---:|---:|---|---:|']
    for s in audit_record['studies']:
        lines.append(f"| {s['year']} | {s['train_rows']} | {s['train_dates']} | {s['last_training_endpoint']} | {s['test_rows']} |")
    lines += ['', f"六個自產估計器的完整測試分數重播通過；獨立字串同分排序、選股數、未知結果聚合與{audit_record['independently_looked_up_endpoints']}個唯一選股端點查價通過。最大分數誤差{audit_record['max_score_error']:.3g}，最大端點誤差{audit_record['max_endpoint_error']:.3g}。", '',
        '## 預先固定的決定', '',
        f"三年主要增量皆正：{decision['positive_primary_in_all_years']}；同時勝過動能／波動的年份：{decision['years_beating_both_baselines']}／3；續研資源門檻：{decision['passed']}。", '',
        '排名目標通過本輪描述性資源門檻，仍需獨立的新證據，不能認定可交易優勢。' if decision['passed'] else '排名目標未通過本輪預先固定資源門檻，這條目標支線結束。保留所有年份與六個模型，不更換參數、年份、持有期間或挑子群重試。這不證明其他模型或資料永遠無效。', '',
        '排名樹是對平均同分百分位做平方誤差迴歸，不是pairwise排序器，也不輸出校準報酬或機率。訓練只用成熟標籤；端點缺價的股票無法進訓練標籤，但評估池及選股保留未知結果。模型與舊研究輸入保持分開。', '',
        '來源備份先核對SHA／CRC／manifest，衍生矩陣、估計器及完整分數留本地封存，不提交Git。沒有實際交易、有效前瞻訊號或績效宣稱。']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')
    atomic_json(OUT/'next_tasks.json', dict(status=status, fits_completed=6,
        automatically_tune=False, automatically_fetch_sources=False,
        decision=decision, valid_signal_date=None, orders=0))
    print('resource gate:', decision, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['audit', 'report'])
    globals()[p.parse_args().stage]()
