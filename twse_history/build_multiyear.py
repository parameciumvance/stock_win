#!/usr/bin/env python3
"""Combine raw years BEFORE adjusting prices and making future-window labels.

Requires all official FMTQIK monthly snapshots through the requested cutoff.
Reuses the single-year engine, but accumulates factors on one common timeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .build_history import (adjust_prices, audit_events, audit_large_moves,
                            audit_listing_coverage, build_labels, build_universe,
                            load_actions, load_table, save_csv)


def validate_calendar(quotes, raw, years, cutoff):
    expected = []
    for year in years:
        for month in range(1, (cutoff.month if year == cutoff.year else 12) + 1):
            table = load_table(Path(raw) / f"calendar_{year}{month:02d}.json", "日期", year)
            if table.empty or not table["日期"].dt.month.eq(month).all():
                raise ValueError("Empty or wrong-month official activity calendar")
            expected.extend(table["日期"].tolist())
    if len(expected) != len(set(expected)):
        raise ValueError("Duplicate official calendar dates")
    expected = pd.DatetimeIndex(sorted(d for d in expected if d <= cutoff))
    observed = pd.DatetimeIndex(sorted(quotes.date.unique()))
    if not expected.equals(observed):
        raise ValueError(dict(missing=expected.difference(observed).astype(str).tolist(),
                              unexpected=observed.difference(expected).astype(str).tolist()))
    return expected


def assign_temporal_roles(labels, holdout_start):
    """Purge training targets that reach the holdout boundary (including equality)."""
    eligible = labels.label_available
    before = labels.date.lt(holdout_start)
    known_before = labels.label_window_end.lt(holdout_start)
    result = labels[["date", "symbol", "label_window_end", "label_available"]].copy()
    result["role"] = np.select(
        [~eligible, before & known_before, before & ~known_before],
        ["unlabeled", "train_eligible", "purged_overlap"], default="test_eligible")
    return result


def boundary_audit(prices, calendar):
    rows = []
    for year in sorted(set(calendar.year))[1:]:
        before_date = calendar[calendar.year == year - 1].max()
        after_date = calendar[calendar.year == year].min()
        before = prices[prices.date.eq(before_date) & prices.close.notna()].set_index("symbol")
        after = prices[prices.date.eq(after_date) & prices.close.notna()].set_index("symbol")
        shared = before.index.intersection(after.index)
        for symbol in shared:
            b, a = before.loc[symbol], after.loc[symbol]
            rows.append(dict(symbol=symbol, name=a["name"], before_date=before_date,
                after_date=after_date, raw_previous_close=b.close, raw_next_close=a.close,
                adj_previous_close=b.adj_close, adj_next_close=a.adj_close,
                factor_before=b.causal_factor, factor_after=a.causal_factor,
                raw_close_return=a.close / b.close - 1,
                adjusted_close_return=a.adj_close / b.adj_close - 1))
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quotes", nargs="+", required=True)
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--end-year", type=int, required=True)
    p.add_argument("--raw", default="twse_history/raw")
    p.add_argument("--output", default="twse_history/output_multiyear")
    p.add_argument("--as-of")
    p.add_argument("--horizon", type=int, default=20)
    p.add_argument("--threshold", type=float, default=0.30)
    p.add_argument("--holdout-start", help="Defaults to January 1 of the final year")
    args = p.parse_args()
    if args.end_year <= args.start_year or args.horizon < 1 or not 0 < args.threshold < float("inf"):
        p.error("At least two years, positive horizon, and finite positive threshold required")
    cutoff = pd.Timestamp(args.as_of or f"{args.end_year}-12-31")
    if not args.start_year <= cutoff.year <= args.end_year:
        p.error("--as-of outside requested years")
    years = list(range(args.start_year, cutoff.year + 1))
    quotes = pd.concat([pd.read_csv(path, dtype={"symbol": str, "name": str}, parse_dates=["date"])
                        for path in args.quotes], ignore_index=True)
    quotes = quotes[quotes.date.between(pd.Timestamp(args.start_year, 1, 1), cutoff)].copy()
    if quotes.duplicated(["symbol", "date"]).any():
        raise ValueError("Repeated quote keys across input files")
    calendar = validate_calendar(quotes, args.raw, years, cutoff)
    master, members, names, delisted = build_universe(quotes, args.raw, calendar)
    new_frames = []
    for year in years:
        new, _ = audit_listing_coverage(quotes, args.raw, year, cutoff, calendar)
        new_frames.append(new)
    new_listings = pd.concat(new_frames, ignore_index=True)
    actions = pd.concat([load_actions(args.raw, year, cutoff) for year in years], ignore_index=True)
    common = set(master.loc[master.security_type.eq("common_stock"), "symbol"])
    prices = adjust_prices(quotes[quotes.symbol.isin(common | {"0050"})], actions, cutoff)
    prices["universe_role"] = np.where(prices.symbol.eq("0050"), "benchmark", "common_stock")
    audit = audit_events(prices, actions)
    labels = build_labels(prices[prices.symbol.isin(common)], members, calendar, args.horizon, args.threshold)
    holdout = pd.Timestamp(args.holdout_start or f"{args.end_year}-01-01")
    split = assign_temporal_roles(labels, holdout)
    boundary = boundary_audit(prices, calendar)
    large_moves = audit_large_moves(prices, new_listings)
    common_actions = actions[actions.symbol.isin(common)]
    valid = labels[labels.label_available]
    year_stats = []
    for year in years:
        part = labels[labels.date.dt.year.eq(year)]
        usable = part[part.label_available]
        q = quotes[quotes.date.dt.year.eq(year)]
        year_stats.append(dict(year=year, market_days=q.date.nunique(), quote_rows=len(q),
            observed_common_symbols=q.loc[q.symbol.isin(common), "symbol"].nunique(),
            membership_rows=len(part), labels_available=len(usable),
            positives=int(usable.surge_adjusted.sum()), positive_rate=float(usable.surge_adjusted.mean()),
            labels_crossing_year=int((usable.label_window_end.dt.year > usable.date.dt.year).sum())))
    year_stats = pd.DataFrame(year_stats)
    summary = dict(start_year=args.start_year, end_year=args.end_year, as_of=str(cutoff.date()),
        market_days=len(calendar), calendar_exact_match=True, raw_quote_rows=len(quotes),
        raw_symbols=quotes.symbol.nunique(), historical_common_symbols=len(common),
        historical_common_quote_rows=int(quotes.symbol.isin(common).sum()),
        membership_rows=len(members), quote_state_counts=members.quote_state.value_counts().to_dict(),
        all_source_events=len(actions), common_stock_events=len(common_actions),
        common_events_by_type=common_actions.event_type.value_counts().to_dict(),
        benchmark_events=int(actions.symbol.eq("0050").sum()), event_audit_states=audit.audit_state.value_counts().to_dict(),
        official_new_listings_checked=len(new_listings), new_listing_mismatches=int((~new_listings.matches).sum()),
        listing_calendar_mismatches=int((~new_listings.matches_market_calendar).sum()),
        listings_scheduled_on_non_market_day=int(new_listings.scheduled_on_non_market_day.sum()),
        labels_available=len(valid), positives=int(valid.surge_adjusted.sum()), positive_rate=float(valid.surge_adjusted.mean()),
        labels_crossing_year=int((valid.label_window_end.dt.year > valid.date.dt.year).sum()),
        censor_reasons=labels.loc[~labels.label_available, "censor_reason"].value_counts().to_dict(),
        holdout_start=str(holdout.date()), temporal_roles=split.role.value_counts().to_dict(),
        adjusted_close_jumps_over_30pct=len(large_moves), boundary_rows=len(boundary),
        years=year_stats.to_dict("records"),
        input_sha256={Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in args.quotes},
        limitations=["Reconstructed classifications, not archived daily security master snapshots.",
                     "Continuous official-reference prices are not a shareholder cash-flow total-return ledger.",
                     "Merger consideration, delisting payoffs, publication history and fill constraints remain incomplete.",
                     "Holdout roles purge overlapping labels; no model has been fitted or evaluated.",
                     "Missing-label censoring may be nonrandom; it is not a loss-free exit assumption."])
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    suffix = f"{args.start_year}_{args.end_year}"
    for data, name in [(master, "security_master"), (members, "universe_daily"), (names, "observed_names"),
                       (delisted, "delistings"), (new_listings, "new_listings_audit"), (actions, "corporate_actions"),
                       (audit, "corporate_action_audit"), (prices, "prices_adjusted"), (labels, "surge_labels_adjusted"),
                       (split, "temporal_split"), (boundary, "year_boundary_audit"), (large_moves, "large_price_moves"),
                       (year_stats, "year_summary")]:
        extension = ".csv.gz" if name in {"universe_daily", "prices_adjusted", "surge_labels_adjusted", "temporal_split"} else ".csv"
        save_csv(data, out / f"{name}_{suffix}{extension}")
    (out / f"summary_{suffix}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
