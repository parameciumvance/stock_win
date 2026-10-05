"""Retrospective volatility baseline on continuous TWSE data.

Uses only causal price history at a signal date. Daily top-decile means are
diagnostics over overlapping labels, not an executable portfolio NAV.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from twse_history.build_history import full_window_max

HORIZON = 20
BUY_COMMISSION = SELL_COMMISSION = 0.001425
SELL_TAX = 0.003
ONE_SIDE_SLIPPAGE = 0.005


def evaluate(source: Path, start_year: int = 2015, end_year: int = 2023):
    prices = pd.read_csv(
        source / "prices_adjusted_2015_2026.csv.gz",
        usecols=["date", "symbol", "close", "volume", "turnover_twd",
                 "adj_open", "adj_high", "adj_low", "adj_close"],
        dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    benchmark = prices.loc[prices.symbol.eq("0050")].set_index("date").reindex(calendar)
    bclose = benchmark.adj_close.astype(float)
    bopen = benchmark.adj_open.astype(float)
    bvalid = np.isfinite(full_window_max(bclose.to_numpy(), HORIZON))
    breturn = (bclose.shift(-HORIZON) / bopen.shift(-1) - 1).where(
        bvalid & bopen.shift(-1).gt(0))
    del benchmark

    frames = []
    for symbol, block in prices.loc[prices.symbol.ne("0050")].groupby("symbol", sort=True):
        g = block.set_index("date").reindex(calendar)
        a = g.adj_close.astype(float)
        valid_history = a.gt(0).rolling(120, min_periods=120).sum().eq(120)
        vol = np.log(a / a.shift(1)).rolling(20, min_periods=20).std()
        tr = pd.concat([g.adj_high - g.adj_low,
                        (g.adj_high - a.shift(1)).abs(),
                        (g.adj_low - a.shift(1)).abs()], axis=1).max(axis=1, skipna=False)
        atr = tr.rolling(14, min_periods=14).mean() / a
        turnover = g.turnover_twd.rolling(20, min_periods=20).mean()
        valid = (valid_history & g.close.ge(10) & g.volume.gt(0) &
                 turnover.ge(10_000_000) & np.isfinite(vol) & np.isfinite(atr) &
                 (calendar.year >= start_year) & (calendar.year <= end_year))
        if not valid.any():
            continue
        future_valid = np.isfinite(full_window_max(a.to_numpy(), HORIZON))
        entry = g.adj_open.shift(-1)
        gross = a.shift(-HORIZON) / entry - 1
        net = (a.shift(-HORIZON) * (1 - ONE_SIDE_SLIPPAGE) *
               (1 - SELL_COMMISSION - SELL_TAX) /
               (entry * (1 + ONE_SIDE_SLIPPAGE) * (1 + BUY_COMMISSION)) - 1)
        candidate = pd.DataFrame({
            "date": calendar, "symbol": symbol, "vol20": vol.to_numpy(),
            "gross_relative_0050": (gross - breturn).to_numpy(),
            "net_relative_0050": (net - breturn).to_numpy(),
            "path_valid": future_valid & bvalid & entry.gt(0).to_numpy() &
                          bopen.shift(-1).gt(0).to_numpy()
        })
        frames.append(candidate.loc[valid.to_numpy()])
    del prices
    ranked = pd.concat(frames, ignore_index=True)
    labels = pd.read_csv(
        source / "surge_labels_adjusted_2015_2026.csv.gz",
        usecols=["date", "symbol", "label_available", "surge_adjusted"],
        dtype={"symbol": str}, parse_dates=["date"])
    ranked = ranked.merge(labels, on=["date", "symbol"], how="left", validate="one_to_one")
    ranked = ranked[ranked.label_available.eq(True) & ranked.path_valid &
                    np.isfinite(ranked.net_relative_0050)].copy()

    rows = []
    for date, day in ranked.groupby("date", sort=True):
        if len(day) < 10:
            continue
        k = max(1, math.ceil(len(day) * 0.1))
        top = day.nlargest(k, "vol20")
        rows.append({
            "date": date, "year": date.year, "pool": len(day), "top_n": k,
            "base_hit": day.surge_adjusted.mean(), "vol_hit": top.surge_adjusted.mean(),
            "base_net_relative_0050": day.net_relative_0050.mean(),
            "vol_net_relative_0050": top.net_relative_0050.mean(),
            "vol_gross_relative_0050": top.gross_relative_0050.mean(),
            "rank_ic_net_relative": day.vol20.corr(day.net_relative_0050, method="spearman"),
        })
    daily = pd.DataFrame(rows)
    annual = []
    for year, group in daily.groupby("year"):
        base, selected = group.base_hit.mean(), group.vol_hit.mean()
        annual.append(dict(year=int(year), days=len(group),
                           eligible_stock_days=int(group.pool.sum()),
                           mean_pool=float(group.pool.mean()),
                           base_hit=float(base), top_hit=float(selected),
                           lift=float(selected / base),
                           base_net_relative_0050=float(group.base_net_relative_0050.mean()),
                           top_net_relative_0050=float(group.vol_net_relative_0050.mean()),
                           top_gross_relative_0050=float(group.vol_gross_relative_0050.mean()),
                           mean_daily_rank_ic_net_relative=float(group.rank_ic_net_relative.mean())))
    return daily, annual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("twse_history/output_2015_2026_asof_20261002"))
    parser.add_argument("--out", type=Path, default=Path("deliverables"))
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2023)
    args = parser.parse_args()
    daily, annual = evaluate(args.source, args.start_year, args.end_year)
    args.out.mkdir(parents=True, exist_ok=True)
    daily.to_csv(args.out / "long_volatility_daily_2015_2023.csv", index=False)
    (args.out / "long_volatility_annual_2015_2023.json").write_text(
        json.dumps(annual, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(annual, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
