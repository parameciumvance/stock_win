#!/usr/bin/env python3
"""2025 holdout research with a verified, limited merger consideration ledger.

Fractional adjusted-price units and other distributions remain proxy accounting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .build_history import full_window_max

FEATURES = ["mom5", "mom20", "mom60", "mom120", "mom60_skip5",
            "relative20", "ma20_distance", "ma60_distance", "volatility20",
            "atr14", "volume_ratio20", "log_turnover20", "breakout60"]

# Public terms known by the effective dates; ordinary-share holders only.
MERGERS = {
    (pd.Timestamp("2025-07-24"), "2888"): dict(
        shares={"2887": .672, "2887I": .175}, cash_per_share=0., cash_tax=0.,
        source="https://www.tsholdings.com.tw/tsh/relations/major/1752058440000/"),
    (pd.Timestamp("2025-08-15"), "6288"): dict(
        shares={"3717": 1.}, cash_per_share=0., cash_tax=0.,
        source="https://wwwc.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d697fc438f01989dc23d80029a.pdf"),
    (pd.Timestamp("2025-10-01"), "2809"): dict(
        shares={"2890": 1.2375}, cash_per_share=26.75, cash_tax=.003,
        source="https://customer.ktb.com.tw/new/note/c32432b0"),
}


def add_consideration_quotes(prices, raw_quotes):
    """A preferred share is held consideration, never an ordinary-share signal."""
    special = raw_quotes[raw_quotes.symbol.eq("2887I")].copy()
    if len(special) != 110 or special.date.min() != pd.Timestamp("2025-07-24"):
        raise ValueError("Incomplete official preferred-share quotes")
    if special[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("Missing consideration quote")
    for field in ("open", "high", "low", "close"):
        special[f"adj_{field}"] = special[field]
    special["causal_factor"] = 1.
    return pd.concat([prices, special], ignore_index=True)


def feature_panel(prices: pd.DataFrame, calendar: pd.DatetimeIndex,
                  min_turnover: float = 10_000_000) -> pd.DataFrame:
    """Only current and earlier raw/causally adjusted quote fields are used."""
    benchmark = prices[prices.symbol.eq("0050")].set_index("date").reindex(calendar)
    # Last *known* ETF quote may be stale over its split suspension. Never backfill.
    bm = benchmark.adj_close.ffill()
    bench20 = bm / bm.shift(20) - 1
    frames = []
    for symbol, source in prices[prices.symbol.ne("0050")].groupby("symbol", sort=True):
        g = source.set_index("date").reindex(calendar).copy()
        a, high, low = g.adj_close, g.adj_high, g.adj_low
        c = g.close
        g["mom5"] = a / a.shift(5) - 1
        g["mom20"] = a / a.shift(20) - 1
        g["mom60"] = a / a.shift(60) - 1
        g["mom120"] = a / a.shift(120) - 1
        g["mom60_skip5"] = a.shift(5) / a.shift(60) - 1
        g["relative20"] = g.mom20 - bench20
        g["ma20_distance"] = a / a.rolling(20, min_periods=20).mean() - 1
        g["ma60_distance"] = a / a.rolling(60, min_periods=60).mean() - 1
        g["volatility20"] = np.log(a / a.shift()).rolling(20, min_periods=20).std()
        tr = pd.concat([high - low, (high - a.shift()).abs(),
                        (low - a.shift()).abs()], axis=1).max(axis=1, skipna=False)
        g["atr14"] = tr.rolling(14, min_periods=14).mean() / a
        g["volume_ratio20"] = g.volume / g.volume.rolling(20, min_periods=20).mean()
        g["turnover20"] = g.turnover_twd.rolling(20, min_periods=20).mean()
        g["log_turnover20"] = np.log1p(g.turnover20)
        g["breakout60"] = a / high.shift().rolling(60, min_periods=60).max() - 1
        # The full 120 market-day window must have an actual positive close.
        g["history_complete120"] = a.gt(0).rolling(120, min_periods=120).sum().eq(120)
        g["signal_eligible"] = (g.history_complete120 & c.ge(10) &
                                  g.volume.gt(0) & g.turnover20.ge(min_turnover) &
                                  np.isfinite(g[FEATURES]).all(axis=1))
        # Secondary relative-return target. Require every future stock market day.
        future_complete = np.isfinite(full_window_max(a.to_numpy(float), 20))
        g["relative_return20"] = (a.shift(-20) / a - bm.shift(-20) / bm).where(future_complete)
        g["symbol"] = symbol
        g["date"] = calendar
        frames.append(g[["date", "symbol", "signal_eligible", "history_complete120",
                         "turnover20", "relative_return20", *FEATURES]])
    return pd.concat(frames, ignore_index=True)


def training_frame(features, labels, roles, exceptional_actions):
    keys = ["date", "symbol"]
    data = features.merge(labels[keys + ["surge_adjusted", "label_available", "label_window_end"]],
                          on=keys, how="left", validate="one_to_one")
    data = data.merge(roles[keys + ["role"]], on=keys, how="left", validate="one_to_one")
    # The known rights-issue auction/reference-price discontinuity can contaminate
    # training labels even though the full-window rule is satisfied.
    data["quarantined_label"] = False
    for symbol, event_date in exceptional_actions:
        mask = (data.symbol.eq(symbol) & data.date.lt(event_date) &
                data.label_window_end.ge(event_date))
        data.loc[mask, "quarantined_label"] = True
    return data


def select_training_rows(data, holdout=pd.Timestamp("2025-01-01")):
    train = data[data.role.eq("train_eligible") & data.signal_eligible &
                 ~data.quarantined_label].copy()
    if train.label_window_end.ge(holdout).any() or train.date.ge(holdout).any():
        raise ValueError("Training target touches the holdout period")
    test = data[data.role.eq("test_eligible") & data.signal_eligible &
                ~data.quarantined_label].copy()
    for frame in (train, test):
        if not frame.label_available.eq(True).all() or not np.isfinite(frame[FEATURES]).all().all():
            raise ValueError("Invalid training/evaluation row")
    return train, test


def rank_metrics(frame, probability):
    y = frame.surge_adjusted.astype(int).to_numpy()
    selected = []
    for _, group in frame.assign(score=probability).groupby("date", sort=True):
        k = max(1, int(np.ceil(len(group) * .10)))
        selected.append(group.nlargest(k, "score").surge_adjusted.astype(int).mean())
    return dict(rows=len(frame), positive_rate=float(y.mean()),
                pr_auc=float(average_precision_score(y, probability)),
                roc_auc=float(roc_auc_score(y, probability)),
                brier=float(brier_score_loss(y, probability)),
                precision_top_decile_mean_by_day=float(np.mean(selected)),
                lift_top_decile_vs_prevalence=float(np.mean(selected) / y.mean()))


def monthly_signals(calendar):
    dates = pd.Series(calendar)
    result = []
    for month in range(1, 13):
        day = dates[(dates.dt.year.eq(2025)) & dates.dt.month.eq(month)].iloc[0]
        prior = dates[dates.lt(day)].iloc[-1]
        result.append((pd.Timestamp(prior), pd.Timestamp(day)))
    return result


def candidate_lists(scored, calendar):
    selections, candidate_counts = {}, []
    for signal, fill in monthly_signals(calendar):
        day = scored[scored.date.eq(signal) & scored.signal_eligible].copy()
        if not len(day):
            raise ValueError(f"No eligible signals at {signal.date()}")
        # Rights-issue discrepancy affects features until a complete new history.
        day = day[~(day.symbol.eq("2429") & day.date.le(pd.Timestamp("2024-12-31")))]
        n = max(1, int(np.ceil(len(day) * .10)))
        selections[fill] = {"equal": day.symbol.tolist(),
                            "momentum_60_skip5": day.nlargest(n, "mom60_skip5").symbol.tolist(),
                            "logistic": day.nlargest(n, "logistic").symbol.tolist(),
                            "hist_gradient_boosting": day.nlargest(n, "hist_gradient_boosting").symbol.tolist(),
                            "0050_hold": ["0050"] if fill == pd.Timestamp("2025-01-02") else None}
        candidate_counts.append(dict(signal_date=signal, fill_date=fill, candidates=len(day), top_k=n))
    return selections, pd.DataFrame(candidate_counts)


def limit_locked(today, previous_close, side):
    """Conservative OHLC proxy; exact auction reference and order queue unknown."""
    if today is None or not all(np.isfinite(today.get(k, np.nan)) for k in ("open", "high", "low", "volume")):
        return True
    if today["open"] <= 0 or today["volume"] <= 0:
        return True
    if not np.isfinite(previous_close) or previous_close <= 0:
        return False
    flat = abs(today["high"] - today["low"]) < 1e-8
    adjusted_open = today["adj_open"]
    if side == "buy":
        return bool(flat and adjusted_open >= previous_close * 1.095)
    return bool(flat and adjusted_open <= previous_close * .905)


def simulate(prices, calendar, selections, delistings, *, commission=.001425,
             sell_tax=.003, etf_sell_tax=.001, slippage=.001, mergers=MERGERS):
    """Fractional adjusted units; merger entitlements enter after opening orders."""
    if min(commission, sell_tax, etf_sell_tax, slippage) < 0:
        raise ValueError("Costs cannot be negative")
    keep = prices[prices.date.dt.year.eq(2025)].copy()
    quote_map = {(r.date, r.symbol): r._asdict() for r in keep.itertuples(index=False)}
    prior_close = {}
    for symbol, group in prices.sort_values("date").groupby("symbol"):
        prior_close[symbol] = group.set_index("date").adj_close.ffill().shift().to_dict()
    delist_map = {(r.delisted_date, r.symbol) for r in delistings.itertuples()
                  if pd.notna(r.delisted_date)}
    last_factor = {}
    for symbol, group in prices[prices.symbol.isin({sym for _, sym in mergers})].sort_values("date").groupby("symbol"):
        last_factor[symbol] = group.set_index("date").causal_factor.ffill().to_dict()
    methods = ["0050_hold", "equal", "momentum_60_skip5", "logistic", "hist_gradient_boosting"]
    portfolios = {m: dict(cash=1.0, units={}, marks={}, realized_zero=0., stale_days=0,
                          merger_cash=0.) for m in methods}
    nav_rows, orders, rights = [], [], []
    for date in calendar[calendar.year == 2025]:
        for method, book in portfolios.items():
            units, marks = book["units"], book["marks"]
            for symbol in list(units):
                q = quote_map.get((date, symbol))
                if q and np.isfinite(q["adj_open"]) and q["adj_open"] > 0:
                    marks[symbol] = q["adj_open"]
            target = selections.get(date, {}).get(method) if date in selections else None
            if target is not None:
                equity_open = book["cash"] + sum(quantity * marks.get(sym, 0) for sym, quantity in units.items())
                target_value = equity_open / len(target)
                target_set = set(target)
                # Sell before buys; an unfilled sell leaves its position in the book.
                for sym in list(units):
                    q = quote_map.get((date, sym))
                    old = prior_close[sym].get(date, np.nan)
                    desired = target_value if sym in target_set else 0.
                    price = q["adj_open"] if q else np.nan
                    excess = units[sym] * price - desired if np.isfinite(price) else 0.
                    if excess <= 1e-12:
                        continue
                    if limit_locked(q, old, "sell"):
                        orders.append(dict(date=date, method=method, symbol=sym, side="sell", notional=excess, status="blocked"))
                        continue
                    quantity = min(units[sym], excess / price)
                    gross = quantity * price * (1 - slippage)
                    tax = etf_sell_tax if sym == "0050" else sell_tax
                    book["cash"] += gross * (1 - commission - tax)
                    units[sym] -= quantity
                    if units[sym] < 1e-12:
                        units.pop(sym)
                        marks.pop(sym, None)
                    orders.append(dict(date=date, method=method, symbol=sym, side="sell", notional=quantity * price, status="filled"))
                for sym in target:
                    q = quote_map.get((date, sym))
                    old = prior_close[sym].get(date, np.nan)
                    held = units.get(sym, 0.)
                    price = q["adj_open"] if q else np.nan
                    gap = target_value - held * price if np.isfinite(price) else target_value
                    if gap <= 1e-12:
                        continue
                    if limit_locked(q, old, "buy"):
                        orders.append(dict(date=date, method=method, symbol=sym, side="buy", notional=gap, status="blocked"))
                        continue
                    execution = price * (1 + slippage)
                    spend = min(gap * (1 + slippage + commission), book["cash"])
                    if spend <= 1e-12:
                        continue
                    quantity = spend / (execution * (1 + commission))
                    units[sym] = held + quantity
                    marks[sym] = price
                    book["cash"] -= spend
                    orders.append(dict(date=date, method=method, symbol=sym, side="buy", notional=quantity * price, status="filled"))
            # Allocation/delivery on effective date is not assumed available at
            # opening auction. Credited cash is usable from the next open only.
            for sym in list(units):
                if (date, sym) not in delist_map:
                    continue
                quantity = units.pop(sym)
                old_mark = marks.pop(sym, np.nan)
                event = mergers.get((date, sym))
                if event is None:
                    book["realized_zero"] += quantity * old_mark
                    orders.append(dict(date=date, method=method, symbol=sym, side="delisted_zero",
                                       notional=quantity * old_mark, status="unresolved_payoff"))
                    continue
                earlier = [day for day in last_factor[sym] if day < date]
                if not earlier:
                    raise ValueError(f"No predecessor factor: {sym}")
                old_factor = last_factor[sym][max(earlier)]
                physical_old_shares = quantity * old_factor
                if not np.isfinite(old_factor) or old_factor <= 0:
                    raise ValueError(f"Invalid predecessor factor: {sym}")
                child = {}
                for successor, ratio in event["shares"].items():
                    q = quote_map.get((date, successor))
                    if not q or not np.isfinite(q["adj_close"]) or q["adj_close"] <= 0:
                        raise ValueError(f"No successor quote on effective date: {successor}")
                    factor = q["causal_factor"]
                    if not np.isfinite(factor) or factor <= 0:
                        raise ValueError(f"No successor factor: {successor}")
                    synthetic_units = physical_old_shares * ratio / factor
                    units[successor] = units.get(successor, 0.) + synthetic_units
                    marks[successor] = q["adj_close"]
                    child[successor] = physical_old_shares * ratio
                gross_cash = physical_old_shares * event["cash_per_share"]
                credited_cash = gross_cash * (1 - event["cash_tax"])
                book["cash"] += credited_cash
                book["merger_cash"] += credited_cash
                rights.append(dict(date=date, method=method, predecessor=sym,
                                   predecessor_synthetic_units=quantity,
                                   predecessor_last_adjusted_mark=old_mark,
                                   predecessor_causal_factor=old_factor,
                                   predecessor_physical_shares=physical_old_shares,
                                   successor_physical_shares=json.dumps(child, sort_keys=True),
                                   gross_cash=gross_cash, cash_tax=gross_cash - credited_cash,
                                   credited_cash=credited_cash, source=event["source"]))
            for sym in units:
                q = quote_map.get((date, sym))
                if q and np.isfinite(q["adj_close"]) and q["adj_close"] > 0:
                    marks[sym] = q["adj_close"]
                else:
                    book["stale_days"] += 1
            nav = book["cash"] + sum(qty * marks[sym] for sym, qty in units.items())
            nav_rows.append(dict(date=date, method=method, nav_proxy=nav,
                                 cash=book["cash"], positions=len(units),
                                 stale_position_days_cumulative=book["stale_days"],
                                 delisted_zero_value_cumulative=book["realized_zero"],
                                 merger_cash_credited_cumulative=book["merger_cash"]))
    return pd.DataFrame(nav_rows), pd.DataFrame(orders), pd.DataFrame(rights)


def performance(nav, orders):
    rows = []
    for method, group in nav.groupby("method"):
        group = group.sort_values("date")
        # 243 observed market days in the holdout. Start with uninvested NAV 1.
        daily = group.nav_proxy.to_numpy() / np.r_[1., group.nav_proxy.to_numpy()[:-1]] - 1
        wealth = group.nav_proxy.to_numpy()
        high = np.maximum.accumulate(np.r_[1., wealth])[1:]
        trades = orders[(orders.method == method) & orders.status.eq("filled")]
        rows.append(dict(method=method, final_nav_proxy=float(wealth[-1]),
                         total_return_proxy=float(wealth[-1] - 1),
                         cagr_proxy=float(wealth[-1] ** (252 / len(group)) - 1),
                         sharpe_proxy=float(np.sqrt(252) * daily.mean() / daily.std(ddof=1)) if daily.std(ddof=1) > 0 else np.nan,
                         max_drawdown_proxy=float(np.min(wealth / high - 1)),
                         turnover_notional_over_initial_nav=float(trades.notional.sum()),
                         filled_orders=len(trades), blocked_orders=int(((orders.method == method) & orders.status.eq("blocked")).sum()),
                         delisting_zero_events=int(((orders.method == method) & orders.status.eq("unresolved_payoff")).sum()),
                         stale_position_days=int(group.stale_position_days_cumulative.iloc[-1])))
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="twse_history/output_multiyear")
    parser.add_argument("--output", default="twse_history/output_research_v5")
    parser.add_argument("--raw-quotes", default="inputs/quotes_twse_2025.csv.gz")
    parser.add_argument("--v4-output", default="twse_history/output_research_v4")
    parser.add_argument("--slippage", type=float, default=.001)
    parser.add_argument("--minimum-turnover", type=float, default=10_000_000)
    args = parser.parse_args()
    source, out = Path(args.input), Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "_2024_2025"
    prices = pd.read_csv(source / f"prices_adjusted{suffix}.csv.gz", dtype={"symbol": str}, parse_dates=["date"])
    labels = pd.read_csv(source / f"surge_labels_adjusted{suffix}.csv.gz", dtype={"symbol": str}, parse_dates=["date", "label_window_end"])
    roles = pd.read_csv(source / f"temporal_split{suffix}.csv.gz", dtype={"symbol": str}, parse_dates=["date"])
    delistings = pd.read_csv(source / f"delistings{suffix}.csv", dtype={"symbol": str}, parse_dates=["delisted_date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    if len(calendar) != 485 or calendar.min() != pd.Timestamp("2024-01-02"):
        raise ValueError("Expected verified 2024–2025 calendar")
    features = feature_panel(prices, calendar, args.minimum_turnover)
    data = training_frame(features, labels, roles, [("2429", pd.Timestamp("2024-07-02"))])
    train, test = select_training_rows(data)
    if not len(train) or not len(test):
        raise ValueError("Empty temporal model split")
    y = train.surge_adjusted.astype(int)
    models = {"logistic": make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)),
              "hist_gradient_boosting": HistGradientBoostingClassifier(
                  learning_rate=.06, max_iter=100, max_leaf_nodes=15,
                  min_samples_leaf=100, l2_regularization=1., early_stopping=False,
                  random_state=2025)}
    for name, model in models.items():
        model.fit(train[FEATURES], y)
        test[name] = model.predict_proba(test[FEATURES])[:, 1]
        joblib.dump(model, out / f"model_{name}.joblib", compress=3)
    metrics = {"prevalence": float(test.surge_adjusted.mean()),
               "random_pr_auc_baseline": float(test.surge_adjusted.mean())}
    for name in models:
        metrics[name] = rank_metrics(test, test[name].to_numpy())
    # Score every eligible monthly signal, including 2024-12-31, without labels.
    signals = {d for d, _ in monthly_signals(calendar)}
    monthly = data[data.date.isin(signals) & data.signal_eligible].copy()
    for name, model in models.items():
        monthly[name] = model.predict_proba(monthly[FEATURES])[:, 1]
    selections, candidates = candidate_lists(monthly, calendar)
    raw = pd.read_csv(args.raw_quotes, dtype={"symbol": str}, parse_dates=["date"])
    valuation_prices = add_consideration_quotes(prices, raw)
    nav, orders, rights = simulate(valuation_prices, calendar, selections, delistings,
                                   slippage=args.slippage)
    perf = performance(nav, orders)
    no_cost_nav, no_cost_orders, _ = simulate(valuation_prices, calendar, selections,
                                              delistings, commission=0, sell_tax=0,
                                              etf_sell_tax=0, slippage=0)
    sensitivity = pd.concat([
        perf.assign(scenario="verified_mergers_with_costs"),
        performance(no_cost_nav, no_cost_orders).assign(scenario="verified_mergers_no_trading_costs")],
        ignore_index=True)
    old_perf = pd.read_csv(Path(args.v4_output) / "performance_proxy.csv")
    comparison = perf.merge(old_perf[["method", "total_return_proxy"]], on="method",
                            suffixes=("_v5", "_v4"), validate="one_to_one")
    comparison["delta_percentage_points"] = 100 * (
        comparison.total_return_proxy_v5 - comparison.total_return_proxy_v4)
    if len(rights) != 5 or set(rights.predecessor) != {"2888", "6288", "2809"}:
        raise ValueError("Expected all five formerly zero-valued held merger events")
    if orders.status.eq("unresolved_payoff").any():
        raise ValueError("Unexpected unverified held delisting")
    predicted = test[["date", "symbol", "surge_adjusted", "logistic",
                      "hist_gradient_boosting", "relative_return20"]]
    prediction_path = out / "holdout_predictions_2025.csv.gz"
    predicted.to_csv(prediction_path, index=False, compression="gzip")
    if len(pd.read_csv(prediction_path)) != len(predicted):
        raise ValueError("Holdout prediction file failed round-trip validation")
    features.to_csv(out / "causal_features_2024_2025.csv.gz", index=False, compression="gzip")
    monthly[["date", "symbol", "mom60_skip5", "logistic", "hist_gradient_boosting"]].to_csv(
        out / "monthly_signal_scores.csv.gz", index=False, compression="gzip")
    for name, frame in [("monthly_candidate_counts", candidates), ("trade_log", orders),
                        ("daily_nav_proxy", nav), ("performance_proxy", perf),
                        ("sensitivity_scenarios", sensitivity),
                        ("merger_rights_ledger", rights), ("comparison_v4_v5", comparison)]:
        frame.to_csv(out / f"{name}.csv", index=False)
    summary = dict(training_rows=len(train), train_dates=[str(train.date.min().date()), str(train.date.max().date())],
                   training_positives=int(y.sum()), evaluation_rows=len(test),
                   evaluation_positives=int(test.surge_adjusted.sum()),
                   quarantined_label_rows=int(data.quarantined_label.sum()),
                   eligible_signal_rows=int(data.signal_eligible.sum()),
                   feature_names=FEATURES, monthly_rebalances=len(selections),
                   costs=dict(commission_per_side=.001425, stock_sell_tax=.003,
                              etf_sell_tax=.001, slippage_per_side=args.slippage),
                   minimum_turnover_twd=args.minimum_turnover,
                   sklearn_version=sklearn.__version__,
                   source_sha256={name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                  for name in [f"prices_adjusted{suffix}.csv.gz",
                                               f"surge_labels_adjusted{suffix}.csv.gz",
                                               f"temporal_split{suffix}.csv.gz",
                                               f"delistings{suffix}.csv"]},
                   raw_quotes_sha256=hashlib.sha256(Path(args.raw_quotes).read_bytes()).hexdigest(),
                   merger_terms=[dict(date=str(date.date()), predecessor=sym, **terms)
                                 for (date, sym), terms in MERGERS.items()],
                   applied_merger_events=len(rights),
                   metrics=metrics, performance=perf.to_dict("records"),
                   comparison_v4_v5=comparison[["method", "delta_percentage_points"]].to_dict("records"),
                   sensitivity_final_nav=sensitivity[["method", "scenario", "final_nav_proxy"]].to_dict("records"),
                   limitations=["One 2025 holdout; no multi-regime stability claim.",
                     "Fractional adjusted units are proxy wealth, not full physical-share accounting.",
                     "Only three held merger conversions and one known cash tax are ledgered; other cash distributions and fractional-share settlement are not.",
                     "Successor shares and merger cash credited after effective-day opening orders; stale holdings use last quote.",
                     "Fractional fills, no minimum fee/board-lot or auction queue reconstruction.",
                     "Limit-lock heuristic uses OHLC and prior adjusted close, not official auction reference."])
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
