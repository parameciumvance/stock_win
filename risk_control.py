"""One frozen exposure experiment on a synthetic forward-reference quote proxy.

Not a shareholder ledger, fill simulator, alpha model or prospective signal.
"""
import argparse
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import statistics
import zipfile

import numpy as np
import pandas as pd

from research_reassessment import verified_bundle
from research_runtime import atomic_json, sha256, utcnow

CONFIG = Path('configs/risk_control_protocol_20261018.json')
FREEZE = Path('deliverables/risk_control_20261018/protocol_freeze.json')
OUT = FREEZE.parent
DATA = Path('inputs/risk_control_20261018/market.csv.gz')
METHODS = ('dynamic', 'calibration_static', 'buy_hold', 'cash')


def protocol():
    c = json.loads(CONFIG.read_text())
    if sha256(CONFIG) != json.loads(FREEZE.read_text())['sha256']:
        raise ValueError('Frozen protocol differs')
    return c


def validate_market(frame):
    f = frame.copy()
    f['date'] = pd.to_datetime(f.date, errors='raise')
    if f.empty or f.date.duplicated().any() or not f.date.is_monotonic_increasing:
        raise ValueError('Empty, duplicate or unordered market calendar')
    cols = ['open', 'close', 'adj_open', 'adj_close', 'causal_factor']
    values = f[cols].to_numpy(float)
    missing = np.isnan(values)
    if not (missing.all(axis=1) | ~missing.any(axis=1)).all():
        raise ValueError('Partially missing quote')
    present = values[~missing.all(axis=1)]
    if not np.isfinite(present).all() or (present <= 0).any():
        raise ValueError('Nonpositive or nonfinite quote')
    for raw, adj in [('open', 'adj_open'), ('close', 'adj_close')]:
        if not np.allclose(f[adj], f[raw] * f.causal_factor, equal_nan=True, rtol=1e-12):
            raise ValueError('Forward factor identity differs')
    if f.adj_close.iloc[0] != f.adj_close.iloc[0]:
        raise ValueError('Initial valuation missing')
    return f


def features(frame, c):
    f = validate_market(frame)
    # Explicit no fill: a suspension invalidates both adjacent return endpoints.
    returns = f.adj_close / f.adj_close.shift(1) - 1
    vol = returns.rolling(c['volatility_lookback'], min_periods=c['volatility_lookback']).std(ddof=1)
    f['prior_vol'] = vol.shift(1) * np.sqrt(c['annualization'])
    f['month_start'] = f.date.dt.to_period('M').ne(f.date.shift(1).dt.to_period('M'))
    return f, returns


def verify_inputs():
    c = protocol()
    receipt = {}
    for key in ['source_archive', 'backup_archive', 'retrieved_archive']:
        manifest = verified_bundle(c[key], c['source_archive_sha256'])
        if manifest[c['price_member']] != c['price_sha256']:
            raise ValueError('Frozen price member differs')
        receipt[key] = {'path': c[key], 'sha256': sha256(c[key]), 'manifest_files': len(manifest)}
    # Parse exact bytes from retrieved archive, never silently prefer a scratch CSV.
    days, pieces = set(), []
    with zipfile.ZipFile(c['retrieved_archive']) as archive, archive.open(c['price_member']) as stream:
        for chunk in pd.read_csv(stream, compression='gzip', dtype={'symbol': str}, chunksize=200000):
            days.update(chunk.date)
            pieces.append(chunk.loc[chunk.symbol.eq(c['symbol']),
                                    ['date', 'open', 'close', 'adj_open', 'adj_close', 'causal_factor']])
    b = pd.concat(pieces, ignore_index=True)
    if b.date.duplicated().any():
        raise ValueError('Duplicate ETF quote')
    f = b.set_index('date').reindex(sorted(days)).rename_axis('date').reset_index()
    f = validate_market(f)
    if str(f.date.min().date()) != c['calibration_start'] or str(f.date.max().date()) != c['evaluation_end']:
        raise ValueError('Unexpected data boundaries')
    missing = f.loc[f.adj_close.isna(), 'date'].dt.strftime('%Y-%m-%d').tolist()
    expected = ['2025-06-11', '2025-06-12', '2025-06-13', '2025-06-16', '2025-06-17']
    if missing != expected:
        raise ValueError('Unreviewed market/ETF quote gap')
    # Pure 4-for-1 split is present in the causal factor, not a -75% loss.
    before = f.loc[f.date.eq('2025-06-10')].iloc[0]
    after = f.loc[f.date.eq('2025-06-18')].iloc[0]
    if not np.isclose(after.causal_factor / before.causal_factor, 4, rtol=0, atol=1e-10):
        raise ValueError('Frozen split factor differs')
    DATA.parent.mkdir(parents=True, exist_ok=True)
    f.to_csv(DATA, index=False, compression={'method': 'gzip', 'mtime': 0}, float_format='%.17g')
    atomic_json(OUT / 'source_receipt.json', dict(
        status='passed', verified_at=utcnow(), archives=receipt,
        source_price_sha256=c['price_sha256'], extracted_market_sha256=sha256(DATA),
        calendar_days=len(f), quoted_days=int(f.adj_close.notna().sum()), missing_dates=missing,
        date_start=str(f.date.min().date()), date_end=str(f.date.max().date()),
        calendar_basis='All dates in the exact frozen multi-security panel; not a newly acquired official calendar',
        roundtrip_verified=True, crc_manifest_verified=True, new_downloads=0, raw_archives_retransmitted=0,
        storage='Existing persistent local original/backup/retrieved copies, same filesystem; no off-host guarantee',
        limitation='Quote proxy only; frozen adjusted factors not independently rebuilt from original actions in this round'))


def rebalance(asset, cash, weight, cost):
    if not all(np.isfinite(x) for x in [asset, cash, weight, cost]) or min(asset, cash) < -1e-12:
        raise ValueError('Invalid portfolio state')
    if not 0 <= weight <= 1 or not 0 <= cost < 1:
        raise ValueError('Invalid weight/cost')
    nav = asset + cash
    delta = (weight * nav - asset) / (1 + weight * cost if weight * nav >= asset else 1 - weight * cost)
    charge = abs(delta) * cost
    new_asset, new_cash = asset + delta, cash - delta - charge
    if min(new_asset, new_cash) < -1e-10 or not np.isclose(new_asset + new_cash, nav - charge, atol=1e-12):
        raise ValueError('Self financing failed')
    return max(0., new_asset), max(0., new_cash), abs(delta), charge


def simulate(frame, c, cost):
    f, returns = features(frame, c)
    calibration = returns[f.date.between(c['calibration_start'], c['calibration_end'])].dropna()
    if len(calibration) < 200:
        raise ValueError('Insufficient calibration')
    sigma = float(calibration.std(ddof=1) * np.sqrt(c['annualization']))
    static = min(1., c['target_annual_volatility'] / sigma) if sigma else 1.
    evaluation = f[f.date.between(c['evaluation_start'], c['evaluation_end'])]
    if evaluation.empty or evaluation.iloc[0].date.strftime('%Y-%m-%d') != c['evaluation_start'] or evaluation.iloc[0].adj_open != evaluation.iloc[0].adj_open:
        raise ValueError('Evaluation must start at its frozen tradable open')
    records = []
    for method in METHODS:
        units, cash, previous_nav, last_close = 0., 1., 1., None
        for number, row in enumerate(evaluation.itertuples(index=False)):
            tradable = bool(np.isfinite(row.adj_open))
            scheduled = number == 0 or (method in ('dynamic', 'calibration_static') and row.month_start)
            target, traded, charge, reason = np.nan, 0., 0., 'hold'
            if scheduled:
                reason = 'missing_quote' if not tradable else 'rebalance'
                if tradable:
                    if method == 'dynamic':
                        if np.isfinite(row.prior_vol):
                            target = min(1., c['target_annual_volatility'] / row.prior_vol) if row.prior_vol else 1.
                        else:
                            reason = 'missing_vol_window'
                    else:
                        target = {'calibration_static': static, 'buy_hold': 1., 'cash': 0.}[method]
                if np.isfinite(target):
                    asset, cash, traded, charge = rebalance(units * row.adj_open, cash, target, cost)
                    units = asset / row.adj_open
            if np.isfinite(row.adj_close):
                last_close = row.adj_close
            if last_close is None:
                raise ValueError('No observed close for valuation')
            asset = units * last_close
            nav = asset + cash
            records.append(dict(date=row.date.strftime('%Y-%m-%d'), method=method, cost_rate=cost,
                                nav=nav, daily_return=nav / previous_nav - 1, units=units, cash=cash,
                                exposure=asset / nav, traded=traded, charge=charge,
                                target=target, reason=reason, carried_valuation=not tradable))
            previous_nav = nav
    return pd.DataFrame(records), dict(calibration_vol=sigma, static_weight=static, calibration_returns=len(calibration))


def metrics(frame, annualization=252):
    r = frame.daily_return.to_numpy()
    n = len(r)
    nav = np.r_[1., frame.nav.to_numpy()]
    volatility = float(np.std(r, ddof=1) * np.sqrt(annualization)) if n > 1 else 0.
    return dict(total_return=float(nav[-1] - 1), cagr=float(nav[-1] ** (annualization / n) - 1),
                annualized_vol=volatility, mean_over_vol=float(np.mean(r) * annualization / volatility) if volatility else None,
                max_drawdown=float(np.min(nav / np.maximum.accumulate(nav) - 1)),
                cumulative_traded_initial_nav_units=float(frame.traded.sum()), cost_initial_nav_units=float(frame.charge.sum()),
                mean_exposure=float(frame.exposure.mean()), ending_exposure=float(frame.exposure.iloc[-1]),
                days=n, missing_valuations=int(frame.carried_valuation.sum()))


def run():
    c = protocol()
    receipt = json.loads((OUT / 'source_receipt.json').read_text())
    if sha256(DATA) != receipt['extracted_market_sha256'] or not receipt['roundtrip_verified']:
        raise ValueError('Unverified source')
    pieces, summaries, years = [], [], []
    for cost in c['one_way_turnover_costs']:
        result, calibration = simulate(pd.read_csv(DATA), c, cost)
        pieces.append(result)
        for method, group in result.groupby('method', sort=False):
            summaries.append(dict(method=method, cost_rate=cost, **metrics(group)))
            for year, part in group.groupby(group.date.str[:4]):
                years.append(dict(method=method, cost_rate=cost, year=int(year),
                                  return_=float(np.prod(1 + part.daily_return) - 1), days=len(part)))
    daily = pd.concat(pieces, ignore_index=True)
    daily.to_csv(OUT / 'daily.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0}, float_format='%.17g')
    daily[daily.reason.ne('hold')].to_csv(OUT / 'decisions.csv', index=False, float_format='%.12g')
    gates = []
    for cost in c['one_way_turnover_costs']:
        d, s = [next(x for x in summaries if x['method'] == method and x['cost_rate'] == cost)
                for method in ['dynamic', 'calibration_static']]
        paired = {m: {x['year']: x['return_'] for x in years if x['cost_rate'] == cost and x['method'] == m}
                  for m in ['dynamic', 'calibration_static']}
        wins = sum(value > paired['calibration_static'][year] for year, value in paired['dynamic'].items())
        gates.append(dict(cost_rate=cost, higher_cagr=d['cagr'] > s['cagr'],
                          no_larger_drawdown=d['max_drawdown'] >= s['max_drawdown'],
                          higher_mean_over_vol=d['mean_over_vol'] is not None and s['mean_over_vol'] is not None and d['mean_over_vol'] > s['mean_over_vol'],
                          at_least_two_year_wins=wins >= 2, year_wins=wins))
    passed = all(all(g[k] for k in ['higher_cagr', 'no_larger_drawdown', 'higher_mean_over_vol', 'at_least_two_year_wins']) for g in gates)
    atomic_json(OUT / 'summary.json', dict(status='exploratory_proxy_only', protocol_sha256=sha256(CONFIG),
                calibration=calibration, summary=summaries, calendar_subperiods=years, gates=gates,
                go_gate_passed=passed, decision='separate_independent_data_proposal_only' if passed else 'close_fixed_rule_no_tuning',
                input_sha256=sha256(DATA), daily_sha256=sha256(OUT / 'daily.csv.gz')))


def independent_audit(frame, daily, c):
    """Independent stdlib statistics + Decimal budget bisection; no rebalance/simulate calls."""
    f = validate_market(frame)
    closes = f.adj_close.to_list()
    returns = [None] + [b / a - 1 if np.isfinite(a) and np.isfinite(b) else None for a, b in zip(closes, closes[1:])]
    cal = [r for d, r in zip(f.date, returns) if c['calibration_start'] <= str(d.date()) <= c['calibration_end'] and r is not None]
    static_sigma = statistics.stdev(cal) * c['annualization'] ** .5
    static = min(1., c['target_annual_volatility'] / static_sigma) if static_sigma else 1.
    max_error = 0.
    checks = 0
    with localcontext() as ctx:
        ctx.prec = 40
        D = lambda v: Decimal(str(v))
        for (cost, method), group in daily.groupby(['cost_rate', 'method'], sort=False):
            units, cash, previous, last = D(0), D(1), D(1), None
            prior_month = None
            source = f[f.date.between(c['evaluation_start'], c['evaluation_end'])]
            if group.date.tolist() != source.date.dt.strftime('%Y-%m-%d').tolist():
                raise ValueError('Independent calendar mismatch')
            for (index, row), saved in zip(source.iterrows(), group.itertuples(index=False)):
                month = row.date.strftime('%Y-%m')
                scheduled = prior_month is None or (method in ('dynamic', 'calibration_static') and month != prior_month)
                weight, reason = None, 'hold'
                if scheduled:
                    reason = 'missing_quote' if pd.isna(row.adj_open) else 'rebalance'
                    if pd.notna(row.adj_open):
                        if method == 'dynamic':
                            window = returns[index - c['volatility_lookback']:index]
                            if len(window) != c['volatility_lookback'] or None in window:
                                reason = 'missing_vol_window'
                            else:
                                sigma = statistics.stdev(window) * c['annualization'] ** .5
                                weight = min(1., c['target_annual_volatility'] / sigma) if sigma else 1.
                        else:
                            weight = {'calibration_static': static, 'buy_hold': 1., 'cash': 0.}[method]
                target_missing = pd.isna(saved.target)
                if saved.reason != reason or (weight is None) != target_missing or (weight is not None and abs(saved.target - weight) > 1e-10):
                    raise ValueError('Independent decision differs')
                traded, charge = D(0), D(0)
                if weight is not None:
                    asset = units * D(row.adj_open)
                    nav, w, rate = asset + cash, D(weight), D(cost)
                    # Solve target fraction after costs by bisection in asset dollars.
                    lo, hi = D(0), nav
                    for _ in range(140):
                        new_asset = (lo + hi) / 2
                        gap = new_asset - w * (nav - abs(new_asset - asset) * rate)
                        if gap > 0:
                            hi = new_asset
                        else:
                            lo = new_asset
                    new_asset = (lo + hi) / 2
                    traded = abs(new_asset - asset)
                    charge = traded * rate
                    cash = nav - new_asset - charge
                    units = new_asset / D(row.adj_open)
                if pd.notna(row.adj_close):
                    last = D(row.adj_close)
                nav = units * last + cash
                expected = dict(nav=nav, daily_return=nav / previous - 1, cash=cash, units=units,
                                traded=traded, charge=charge, exposure=units * last / nav)
                for key, value in expected.items():
                    error = abs(float(value) - getattr(saved, key))
                    if not np.isfinite(error) or error > 1e-10:
                        raise ValueError('Independent ledger differs: ' + key)
                    max_error = max(max_error, error)
                if bool(saved.carried_valuation) != bool(pd.isna(row.adj_close)):
                    raise ValueError('Independent valuation flag differs')
                checks += 1
                previous, prior_month = nav, month
    return dict(status='passed', method='stdlib sample stdev; Decimal 40-digit self-financing bisection', rows=checks,
                max_absolute_error=max_error, calibration_vol=static_sigma, static_weight=static)


def audit_summary(daily, summary, c):
    """Check reported aggregates from ledger endpoints with stdlib arithmetic."""
    counts = 0
    if len(summary['summary']) != len(METHODS) * len(c['one_way_turnover_costs']):
        raise ValueError('Summary cohort differs')
    for saved in summary['summary']:
        group = daily[daily.method.eq(saved['method']) & daily.cost_rate.eq(saved['cost_rate'])]
        if group.empty:
            raise ValueError('Missing summary ledger')
        nav, returns = group.nav.tolist(), group.daily_return.tolist()
        vol = statistics.stdev(returns) * math.sqrt(c['annualization'])
        peak, drawdown = 1., 0.
        for value in nav:
            peak = max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
        expected = dict(total_return=nav[-1] - 1, cagr=nav[-1] ** (c['annualization'] / len(nav)) - 1,
                        annualized_vol=vol, mean_over_vol=statistics.mean(returns) * c['annualization'] / vol if vol else None,
                        max_drawdown=drawdown, cumulative_traded_initial_nav_units=math.fsum(group.traded),
                        cost_initial_nav_units=math.fsum(group.charge), mean_exposure=statistics.mean(group.exposure),
                        ending_exposure=group.exposure.iloc[-1], days=len(nav), missing_valuations=int(group.carried_valuation.sum()))
        for key, value in expected.items():
            actual = saved[key]
            if (value is None) != (actual is None) or (value is not None and (not math.isfinite(actual) or abs(value - actual) > 1e-10)):
                raise ValueError('Independent summary differs: ' + key)
        previous = 1.
        for year, part in group.groupby(group.date.str[:4], sort=False):
            saved_year = [r for r in summary['calendar_subperiods'] if r['method'] == saved['method'] and r['cost_rate'] == saved['cost_rate'] and r['year'] == int(year)]
            if len(saved_year) != 1 or saved_year[0]['days'] != len(part) or abs(saved_year[0]['return_'] - (part.nav.iloc[-1] / previous - 1)) > 1e-10:
                raise ValueError('Independent calendar return differs')
            previous = part.nav.iloc[-1]
        counts += 1
    passed = True
    for cost in c['one_way_turnover_costs']:
        d, s = [next(r for r in summary['summary'] if r['method'] == m and r['cost_rate'] == cost) for m in ('dynamic', 'calibration_static')]
        y = {m: {r['year']: r['return_'] for r in summary['calendar_subperiods'] if r['method'] == m and r['cost_rate'] == cost} for m in ('dynamic', 'calibration_static')}
        wins = sum(r > y['calibration_static'][year] for year, r in y['dynamic'].items())
        expected = dict(cost_rate=cost, higher_cagr=d['cagr'] > s['cagr'], no_larger_drawdown=d['max_drawdown'] >= s['max_drawdown'],
                        higher_mean_over_vol=d['mean_over_vol'] is not None and s['mean_over_vol'] is not None and d['mean_over_vol'] > s['mean_over_vol'], at_least_two_year_wins=wins >= 2, year_wins=wins)
        if [r for r in summary['gates'] if r['cost_rate'] == cost] != [expected]:
            raise ValueError('Independent decision gate differs')
        passed = passed and expected['higher_cagr'] and expected['no_larger_drawdown'] and expected['higher_mean_over_vol'] and expected['at_least_two_year_wins']
    if summary['go_gate_passed'] != passed or summary['decision'] != ('separate_independent_data_proposal_only' if passed else 'close_fixed_rule_no_tuning'):
        raise ValueError('Independent decision differs')
    return counts


def audit():
    c = protocol()
    s = json.loads((OUT / 'summary.json').read_text())
    if s['input_sha256'] != sha256(DATA) or s['daily_sha256'] != sha256(OUT / 'daily.csv.gz'):
        raise ValueError('Replay artifacts drifted')
    daily = pd.read_csv(OUT / 'daily.csv.gz')
    r = independent_audit(pd.read_csv(DATA), daily, c)
    if s['protocol_sha256'] != sha256(CONFIG) or abs(r['calibration_vol'] - s['calibration']['calibration_vol']) > 1e-12 or abs(r['static_weight'] - s['calibration']['static_weight']) > 1e-12:
        raise ValueError('Independent calibration/protocol differs')
    r.update(aggregate_groups_verified=audit_summary(daily, s, c), summary_sha256=sha256(OUT / 'summary.json'),
             protocol_sha256=sha256(CONFIG), daily_sha256=s['daily_sha256'])
    atomic_json(OUT / 'independent_audit.json', r)


def report():
    c = protocol()
    s = json.loads((OUT / 'summary.json').read_text())
    a = json.loads((OUT / 'independent_audit.json').read_text())
    if a['status'] != 'passed' or a['daily_sha256'] != s['daily_sha256'] or a['summary_sha256'] != sha256(OUT / 'summary.json'):
        raise ValueError('Independent audit required')
    lines = ['# 0050／現金：一次性風險控制探索', '',
             '新協定先於策略結果檢視凍結並提交；舊模型及七規則沒有調參或恢復。零新下載、零原始包重傳，重用完整SHA、CRC、manifest與既有本地備份取回均驗證的凍結包。', '',
             '資料為2023-01-03～2026-10-02，共905個市場日、0050有900筆。2023只校準固定比例；2024-01-02～2026-10-02探索比較。這些年份已用於舊研究，不能稱新留出或前瞻證據。', '',
             '單一規則：20個連續市場日收盤報酬的樣本波動率年化，目標10%，持股比例限制0～100%。每月首個市場日開盤依前一日資料調整；中間持有代理單位與零息現金。固定比例比較者使用2023波動率一次校準，同樣每月維持比例；並非事後精確同風險。', '',
             f'2023校準波動率{s["calibration"]["calibration_vol"]:.2%}，固定持股比例{s["calibration"]["static_weight"]:.2%}。兩種成本為每單邊交易額0.1%／0.2%的假設情境，不宣稱真實稅率。初始建倉及每次調整皆扣，期末未強制賣出。', '',
             '| 單邊成本 | 方法 | 年化代理報酬 | 年化波動 | 最大收盤回落 | 平均／波動 | 平均持股 |',
             '|---|---|---:|---:|---:|---:|---:|']
    for r in s['summary']:
        ratio = '—' if r['mean_over_vol'] is None else f'{r["mean_over_vol"]:.3f}'
        lines.append(f'| {r["cost_rate"]:.1%} | {r["method"]} | {r["cagr"]:.2%} | {r["annualized_vol"]:.2%} | {r["max_drawdown"]:.2%} | {ratio} | {r["mean_exposure"]:.2%} |')
    lines += ['', '## 分期間比較', '', '| 單邊成本 | 年（2026非全年） | 動態 | 校準固定比例 |', '|---|---|---:|---:|']
    for cost in c['one_way_turnover_costs']:
        for year in [2024, 2025, 2026]:
            values = {r['method']: r['return_'] for r in s['calendar_subperiods'] if r['cost_rate'] == cost and r['year'] == year}
            lines.append(f'| {cost:.1%} | {year} | {values["dynamic"]:.2%} | {values["calibration_static"]:.2%} |')
    lines += ['', '## 固定投入關卡', '',
              '事先要求兩種成本下均高於校準固定比例的年化報酬與平均／波動、收盤最大回落不更差、三個年度片段至少兩段勝出。不是統計顯著性或獲利保證。', '',
              '**' + ('通過探索關卡：只容許另提獨立資料方案。' if s['go_gate_passed'] else '未通過：本條固定規則收束，不搜尋參數、不延長下載、不啟動每日驗證。') + '**', '',
              '動態法的回落及波動較低，平均／波動比也略高；但三個期間片段的報酬均較校準固定比例低，且兩者實際風險不同。因此這次停止的是本條規則的擴大投入，不是證明所有風險控制無用，也不是證明固定比例適合使用者。若真正目標改為容忍較低報酬以降低回落，必須先另定需求與評估關卡，不能看到結果後替本次改標準。', '',
              '逐成本關卡詳見[summary.json](summary.json)，逐月決定與略過原因見[decisions.csv](decisions.csv)。', '',
              '## 可稽核性與限制', '',
              f'獨立重算以Python標準差及Decimal 40位二分法解交易預算，核對{a["rows"]}列，最大絕對誤差{a["max_absolute_error"]:.3g}；沒有呼叫原模擬器的調整函式。階段輸入輸出SHA由research_pipeline記錄。', '',
              '2025-06-11～17五個市場日0050沒有報價，保留日曆、禁止交易，只以末次報價估值；不把補值放入波動估計。20日視窗不完整就略過該月調整（含2025-07），不預先排入稍後訂單。停牌期間真實資產價值不可觀測，最大收盤回落與日波動可能偏低。分割前後因果因子比值4已核對，不把除以4當成虧損。', '',
              '全部數字是官方參考價調整的合成報價代理；不等同配息現金帳、可成交價或真實投資績效。這輪驗證凍結輸入及因子算術，未重新從原始公司行動獨立重建。現金零息、成本假設、短樣本與偏多市場皆限制推論；未估計統計顯著性。平均／波動以零現金基準計算，不稱已驗證的超額Sharpe。', '',
              '研究動機：[Moreira／Muir原始研究](https://www.nber.org/papers/w22208)；[後續可實現性檢驗](https://doi.org/10.1016/j.jfineco.2020.04.015)提示樣本內效果不保證實際樣本外能力。兩者都不是0050有效性的證據。', '',
              '本輪沒有有效前瞻訊號、實際訂單或新獲利優勢。原始大型資料留在本地持久化目錄及既有備份，未提交Git。']
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n')
    atomic_json(OUT / 'next_tasks.json', dict(status=s['decision'], parameter_search=False,
                manual_daily_validation=False, seven_rule_daily_plan='stopped', external_data_requests=[],
                next_decision='Choose a goal and economic mechanism before any separately frozen new study; do not tune this failed rule' if not s['go_gate_passed'] else 'Only consider independent data after proxy accounting limitations are resolved'))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['verify_inputs', 'run', 'audit', 'report'])
    globals()[p.parse_args().stage]()
