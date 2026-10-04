"""Audit held corporate-action exposure and value physical 0050 cash flows.

Use the v5 order log for the exposure audit. All strategies other than the
independently calculated 0050 benchmark retain their v5 proxy accounting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


ETF_DISTRIBUTIONS = {
    pd.Timestamp("2025-01-17"): (2.70, pd.Timestamp("2025-02-20")),
    pd.Timestamp("2025-07-21"): (.36, pd.Timestamp("2025-08-08")),
}
ETF_SOURCE = "https://www.twse.com.tw/en/ETFortune-institute/dividendList?endDate=2025&startDate=2025&stkNo=0050"
SPLIT_DATE = pd.Timestamp("2025-06-18")
SPLIT_RATIO = 4


def held_action_inventory(prices, orders, rights, actions, calendar):
    """Replay filled order quantities and post-open mergers to audit exposure."""
    prices = prices[prices.date.dt.year.eq(2025)].copy()
    price_map = {(r.date, r.symbol): r for r in prices.itertuples(index=False)}
    order_map = {(d, m): g for (d, m), g in orders.groupby(["date", "method"])}
    right_map = {(d, m): g for (d, m), g in rights.groupby(["date", "method"])}
    action_map = {d: g for d, g in actions.groupby("effective_date")}
    quote_day_map = {d: g for d, g in prices.groupby("date")}
    methods = sorted(orders.method.unique())
    units = {method: defaultdict(float) for method in methods}
    latest_factor = defaultdict(lambda: 1.)
    inventory = []
    for date in calendar[calendar.year == 2025]:
        events = action_map.get(date)
        # Ex-rights ownership is determined before the morning's orders.
        if events is not None:
            for event in events.itertuples(index=False):
                symbol = event.symbol
                for method in methods:
                    synthetic = units[method].get(symbol, 0.)
                    if synthetic < -1e-9:
                        raise ValueError(f"Negative position: {date}, {method}, {symbol}")
                    if synthetic <= 1e-12:
                        continue
                    inventory.append(dict(date=date, method=method, symbol=symbol,
                        event_id=event.event_id, event_type=event.event_type,
                        event_subtype=event.event_subtype,
                        predecessor_synthetic_units=synthetic,
                        prior_causal_factor=latest_factor[symbol],
                        adjusted_unit_equivalent_shares=synthetic * latest_factor[symbol],
                        payout_amount_verified=bool(symbol == "0050" and
                                                    date in ETF_DISTRIBUTIONS and
                                                    event.event_type == "exrights"),
                        source_url=event.source_url))
        for method in methods:
            group = order_map.get((date, method))
            if group is not None:
                for order in group.itertuples(index=False):
                    if order.status != "filled":
                        continue
                    q = price_map.get((date, order.symbol))
                    if q is None or not np.isfinite(q.adj_open) or q.adj_open <= 0:
                        raise ValueError(f"No open for filled order: {date}, {order.symbol}")
                    change = order.notional / q.adj_open
                    units[method][order.symbol] += change if order.side == "buy" else -change
                    if abs(units[method][order.symbol]) < 1e-12:
                        del units[method][order.symbol]
            group = right_map.get((date, method))
            if group is not None:
                for right in group.itertuples(index=False):
                    old = units[method][right.predecessor]
                    if not np.isclose(old, right.predecessor_synthetic_units, atol=1e-10):
                        raise ValueError(f"Rights/order position mismatch: {date}, {method}")
                    del units[method][right.predecessor]
                    for successor, physical in json.loads(right.successor_physical_shares).items():
                        q = price_map.get((date, successor))
                        factor = q.causal_factor if q is not None else 1.
                        units[method][successor] += physical / factor
        for q in quote_day_map[date].itertuples(index=False):
            latest_factor[q.symbol] = q.causal_factor
    return pd.DataFrame(inventory)


def etf_physical_ledger(prices, calendar, *, commission=.001425,
                        slippage=.001, etf_sell_tax=.001):
    """Physical units, split, dividend receivable, and payment-date cash."""
    if min(commission, slippage, etf_sell_tax) < 0:
        raise ValueError("Invalid costs")
    p = prices[prices.symbol.eq("0050") & prices.date.dt.year.eq(2025)].set_index("date")
    first = calendar[calendar.year == 2025][0]
    if first not in p.index or not np.isfinite(p.loc[first, "open"]):
        raise ValueError("No first-day 0050 opening quote")
    buy_price = p.loc[first, "open"] * (1 + slippage)
    shares = 1 / (buy_price * (1 + commission))
    last_close = np.nan
    receivable, cash = 0., 0.
    claims = []
    rows = []
    for date in calendar[calendar.year == 2025]:
        if date == SPLIT_DATE:
            shares *= SPLIT_RATIO
        if date in ETF_DISTRIBUTIONS:
            amount, payment = ETF_DISTRIBUTIONS[date]
            if date not in p.index:
                raise ValueError("No ex-dividend quote")
            claim = shares * amount
            receivable += claim
            claims.append(dict(ex_date=date, payment_date=payment, amount_per_share=amount,
                               shares=shares, gross_receivable=claim,
                               source_url=ETF_SOURCE))
        for claim in claims:
            if claim["payment_date"] == date:
                receivable -= claim["gross_receivable"]
                cash += claim["gross_receivable"]
        q = p.loc[date] if date in p.index else None
        if q is not None and np.isfinite(q["close"]):
            last_close = float(q["close"])
        if not np.isfinite(last_close):
            raise ValueError("No quote to value benchmark")
        rows.append(dict(date=date, method="0050_physical_cash", physical_units=shares,
                         last_raw_close=last_close, uninvested_cash=cash,
                         dividend_receivable=receivable,
                         nav=shares * last_close + cash + receivable,
                         stale_quote=q is None))
    return pd.DataFrame(rows), pd.DataFrame(claims)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default="twse_history/output_multiyear")
    p.add_argument("--v5-output", default="twse_history/output_research_v5")
    p.add_argument("--raw-quotes", default="inputs/quotes_twse_2025.csv.gz")
    p.add_argument("--output", default="twse_history/output_research_v6")
    args = p.parse_args()
    source, prev, out = Path(args.input), Path(args.v5_output), Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    prices = pd.read_csv(source / "prices_adjusted_2024_2025.csv.gz",
                         dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    actions = pd.read_csv(source / "corporate_actions_2024_2025.csv",
                          dtype={"symbol": str}, parse_dates=["effective_date"])
    orders = pd.read_csv(prev / "trade_log.csv", dtype={"symbol": str}, parse_dates=["date"])
    rights = pd.read_csv(prev / "merger_rights_ledger.csv",
                         dtype={"predecessor": str}, parse_dates=["date"])
    special = pd.read_csv(args.raw_quotes, dtype={"symbol": str},
                          parse_dates=["date"], usecols=["date", "symbol", "open", "close"])
    special = special[special.symbol.eq("2887I")].copy()
    special["adj_open"] = special.open
    special["causal_factor"] = 1.
    all_prices = pd.concat([prices, special], ignore_index=True)
    inventory = held_action_inventory(all_prices, orders, rights, actions, calendar)
    etf_nav, claims = etf_physical_ledger(prices, calendar)
    if len(claims) != 2 or len(inventory[inventory.symbol.eq("0050")]) != 3:
        raise ValueError("Unexpected ETF action coverage")
    old = pd.read_csv(prev / "performance_proxy.csv").set_index("method")
    result = dict(physical_0050_return=float(etf_nav.nav.iloc[-1] - 1),
                  v5_0050_adjusted_price_proxy_return=float(old.loc["0050_hold", "total_return_proxy"]),
                  held_action_rows=len(inventory),
                  held_events_by_type=inventory.groupby("event_type").size().to_dict(),
                  held_events_by_method=inventory.groupby("method").size().to_dict(),
                  etf_paid_cash=float(claims.gross_receivable.sum()),
                  etf_year_end_receivable=float(etf_nav.dividend_receivable.iloc[-1]),
                  inputs_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in [source / "prices_adjusted_2024_2025.csv.gz",
                                   source / "corporate_actions_2024_2025.csv",
                                   prev / "trade_log.csv", prev / "merger_rights_ledger.csv",
                                   Path(args.raw_quotes)]})
    inventory.to_csv(out / "held_corporate_actions_2025.csv", index=False)
    etf_nav.to_csv(out / "etf_0050_daily_physical_nav.csv", index=False)
    claims.to_csv(out / "etf_0050_distribution_ledger.csv", index=False)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
