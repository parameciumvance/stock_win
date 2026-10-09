"""Build daily institutional features using only prior market-day records.

Absent T86 rows and zero/missing quote volume remain missing. Ratios use raw
shares divided by raw daily quote volume; they are not holdings percentages.
Use this retrospective endpoint with explicit revision/publication-clock limits.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .institutional import market_days_from_cache


FLOW_ROLES = ("foreign", "trust", "total")


def build_features(prices, flows, market_days):
    days = pd.DatetimeIndex(pd.to_datetime(market_days)).normalize().sort_values()
    if len(days) == 0 or days.has_duplicates or days.tz is not None:
        raise ValueError("Need distinct, local market dates")
    p = prices[["date", "symbol", "volume"]].copy()
    f = flows[["date", "symbol", "foreign_schema"] + [r + "_net_shares" for r in FLOW_ROLES]].copy()
    for frame in (p, f):
        frame["date"] = pd.to_datetime(frame.date, errors="raise")
        frame["symbol"] = frame.symbol.astype(str)
        if frame.date.dt.tz is not None or not frame.date.dt.normalize().eq(frame.date).all():
            raise ValueError("Dates must be local market dates")
        if frame.duplicated(["date", "symbol"]).any() or not frame.date.isin(days).all():
            raise ValueError("Duplicate/off-calendar input date/symbol")
    p["volume"] = pd.to_numeric(p.volume, errors="raise")
    if p.volume.lt(0).any():
        raise ValueError("Negative quote volume")
    if not f.foreign_schema.eq("excluding_foreign_dealer").all():
        raise ValueError("Do not pool unharmonized legacy foreign schema in features")
    for role in FLOW_ROLES:
        f[role + "_net_shares"] = pd.to_numeric(f[role + "_net_shares"], errors="raise")
    if not np.isfinite(f[[r + "_net_shares" for r in FLOW_ROLES]]).all().all():
        raise ValueError("Nonfinite observed flow value")
    merged = p.merge(f, on=["date", "symbol"], how="left", validate="one_to_one")
    result = []
    for symbol, group in merged.groupby("symbol", sort=True):
        indexed = group.set_index("date").reindex(days)
        ratio = indexed[[r + "_net_shares" for r in FLOW_ROLES]].div(
            indexed.volume.where(indexed.volume.gt(0)), axis=0)
        output = pd.DataFrame({"date": days, "symbol": symbol})
        source_dates = pd.Series(days, index=days).where(indexed.foreign_schema.notna())
        output["institutional_source_date"] = source_dates.shift(1).to_numpy()
        for role in FLOW_ROLES:
            values = ratio[role + "_net_shares"]
            output[role + "_net_volume_ratio_1d"] = values.shift(1).to_numpy()
            for window in (5, 20):
                output[role + f"_net_volume_ratio_{window}d"] = values.rolling(
                    window, min_periods=window).mean().shift(1).to_numpy()
        result.append(output)
    if not result:
        raise ValueError("Empty prices")
    return pd.concat(result, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--year", type=int)
    scope.add_argument("--years", type=int, nargs="+")
    parser.add_argument("--prices", required=True)
    parser.add_argument("--flows", required=True, nargs="+")
    parser.add_argument("--calendar-root", default="twse_history/raw")
    parser.add_argument("--asof", help="Partial final year cutoff YYYY-MM-DD")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    years = args.years or [args.year]
    if len(set(years)) != len(years) or sorted(years) != list(range(min(years), max(years) + 1)):
        raise ValueError("Need distinct contiguous years")
    if args.asof and pd.Timestamp(args.asof).year != max(years):
        raise ValueError('As-of cutoff must belong to final year')
    days = pd.to_datetime([day for year in sorted(years) for day in
                          market_days_from_cache(Path(args.calendar_root), year, args.asof if year == max(years) else None)], format="%Y%m%d")
    pieces = []
    for chunk in pd.read_csv(args.prices, usecols=["date", "symbol", "volume", "universe_role"],
                             dtype={"symbol": str}, chunksize=200000):
        in_scope = chunk.date.str[:4].isin([str(y) for y in years]) & chunk.universe_role.eq("common_stock")
        if args.asof:
            in_scope &= chunk.date.le(args.asof)
        pieces.append(chunk[in_scope])
    prices = pd.concat(pieces, ignore_index=True)
    flows = pd.concat([pd.read_csv(path, dtype={"symbol": str}) for path in args.flows], ignore_index=True)
    output = build_features(prices, flows, days)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False)
    print(f"rows={len(output)} symbols={output.symbol.nunique()} complete_5d={output.foreign_net_volume_ratio_5d.notna().sum()}")


if __name__ == "__main__":
    main()

