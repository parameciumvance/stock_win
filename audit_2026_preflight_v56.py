"""Read-only schema/health audit for a not-yet-validated 2026 quote table.

Does not compute outcomes, adjust prices, fit a model, or inspect labels.
Official source calendar, daily raw responses, and corporate actions are still
required before a prospective-looking evaluation can proceed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


EXPECTED = ["date", "symbol", "name", "open", "high", "low", "close",
            "volume", "trades", "turnover_twd", "pe_ratio"]


def audit(quotes_path: Path, as_of: str, previous_quotes: Path):
    quotes = pd.read_csv(quotes_path, dtype={"symbol": str, "name": str},
                         parse_dates=["date"])
    if list(quotes.columns) != EXPECTED:
        raise ValueError(f"Unexpected quote columns: {list(quotes.columns)}")
    cutoff = pd.Timestamp(as_of)
    if quotes.empty or quotes.date.min().year != cutoff.year or quotes.date.max() != cutoff:
        raise ValueError("Missing the named cutoff date or unexpected first year")
    if quotes.date.gt(cutoff).any() or quotes.date.isna().any():
        raise ValueError("Invalid quote date")
    price = quotes[["open", "high", "low", "close"]]
    complete = price.notna().all(axis=1)
    partial = price.notna().any(axis=1) & ~complete
    bad_range = complete & (quotes.high.lt(price.max(axis=1)) |
                            quotes.low.gt(price.min(axis=1)))
    numeric = ["open", "high", "low", "close", "volume", "trades",
               "turnover_twd", "pe_ratio"]
    missing_required = quotes[["volume", "trades", "turnover_twd"]].isna().any(axis=1)
    negative = quotes[numeric].lt(0).any(axis=1)
    duplicate = quotes.duplicated(["date", "symbol"])
    if partial.any() or bad_range.any() or missing_required.any() or negative.any() or duplicate.any():
        raise ValueError(dict(partial_price=int(partial.sum()),
                              invalid_ohlc=int(bad_range.sum()),
                              missing_required=int(missing_required.sum()),
                              negative=int(negative.sum()), duplicates=int(duplicate.sum())))
    earlier = pd.read_csv(previous_quotes, dtype={"symbol": str}, usecols=["symbol"])
    dates = pd.DatetimeIndex(sorted(quotes.date.unique()))
    counts = quotes.groupby("date").size()
    benchmark_days = quotes.loc[quotes.symbol.eq("0050"), "date"].nunique()
    if benchmark_days != len(dates):
        raise ValueError("0050 is missing from one or more observed quote dates")
    return dict(sha256=hashlib.sha256(quotes_path.read_bytes()).hexdigest(),
                as_of=as_of, first_date=str(dates.min().date()),
                last_date=str(dates.max().date()), observed_dates=len(dates),
                quote_rows=len(quotes), distinct_symbols=quotes.symbol.nunique(),
                monthly_observed_dates={str(k):int(v) for k,v in
                                        quotes.groupby(quotes.date.dt.to_period("M")).date.nunique().items()},
                complete_ohlc_rows=int(complete.sum()), all_ohlc_missing_rows=int((~complete).sum()),
                min_rows_per_date=int(counts.min()), max_rows_per_date=int(counts.max()),
                benchmark_0050_dates=int(benchmark_days),
                symbols_not_seen_2025=len(set(quotes.symbol)-set(earlier.symbol)),
                symbols_2025_not_seen=len(set(earlier.symbol)-set(quotes.symbol)),
                duplicates=0, invalid_ohlc=0, negative_numeric_rows=0,
                official_calendar_checked=False, raw_response_hashes_checked=False,
                corporate_actions_checked=False, surge_labels_opened=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quotes", type=Path, required=True)
    p.add_argument("--as-of", default="2026-10-02")
    p.add_argument("--previous-quotes", type=Path,
                   default=Path("inputs/quotes_twse_2025.csv.gz"))
    p.add_argument("--output", type=Path,
                   default=Path("deliverables/preflight_2026_v56.json"))
    args = p.parse_args()
    result = audit(args.quotes, args.as_of, args.previous_quotes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
