#!/usr/bin/env python3
"""Fetch one TWSE year, or a dated prefix, using official market activity.

An expected market date that fails to return quotes is an error, not a holiday.
Successful raw responses are cached for restart, with URL/time/SHA-256 metadata.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

import pandas as pd

from .build_history import date_value, load_table
from .fetch_history import download


def market_calendar(year, raw, workers=2, delay=3, as_of=None):
    cutoff = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(year, 12, 31)
    def month(m):
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={year}{m:02d}01&response=json"
        path = download(url, Path(raw) / f"calendar_{year}{m:02d}.json", delay)
        data = load_table(path, "日期", year)
        if data.empty or not data["日期"].dt.month.eq(m).all():
            raise ValueError(f"Invalid monthly market calendar: {path}")
        return data["日期"].tolist()
    dates = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(month, range(1, cutoff.month + 1)):
            dates.extend(result)
    if len(dates) != len(set(dates)):
        raise ValueError("Duplicate calendar dates")
    return pd.DatetimeIndex(sorted(d for d in dates if d <= cutoff))


def normalize_quotes(payload, date):
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        raise ValueError(f"Expected market date has no valid quotes: {date:%Y-%m-%d}")
    if "date" in payload and date_value(payload["date"]) != date:
        raise ValueError("MI_INDEX response date does not match request")
    tables = [t for t in payload.get("tables", []) if "證券代號" in (t.get("fields") or [])]
    if len(tables) != 1:
        raise ValueError("Missing or ambiguous quote table")
    table = tables[0]
    result = pd.DataFrame(table["data"], columns=table["fields"])
    columns = {"證券代號": "symbol", "證券名稱": "name", "開盤價": "open",
               "最高價": "high", "最低價": "low", "收盤價": "close",
               "成交股數": "volume", "成交筆數": "trades", "成交金額": "turnover_twd", "本益比": "pe_ratio"}
    if not set(columns).issubset(result.columns) or result.empty:
        raise ValueError("Quote schema changed or quote table empty")
    result = result[list(columns)].rename(columns=columns)
    for col in result.columns:
        result[col] = result[col].astype(str).str.strip()
        if col not in ("symbol", "name"):
            result[col] = pd.to_numeric(result[col].str.replace(",", "", regex=False), errors="coerce")
    result.insert(0, "date", date)
    if result.symbol.duplicated().any():
        raise ValueError("Duplicate quote symbols on one market date")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--as-of", help="Inclusive YYYY-MM-DD cutoff for an incomplete year")
    p.add_argument("--raw", default="data/raw")
    p.add_argument("--calendar-raw", default="twse_history/raw")
    p.add_argument("--output", default="inputs")
    p.add_argument("--workers", type=int, choices=[1, 2, 3, 4], default=2)
    p.add_argument("--delay", type=float, default=3)
    args = p.parse_args()
    if args.delay < 0:
        p.error("delay must be nonnegative")
    cutoff = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp(args.year, 12, 31)
    if cutoff.year != args.year:
        p.error("--as-of must fall within --year")
    tag = f"_asof_{cutoff:%Y%m%d}" if args.as_of else ""
    raw = Path(args.raw) / f"twse_{args.year}"
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    calendar = market_calendar(args.year, args.calendar_raw, args.workers, args.delay, cutoff)
    if calendar.empty:
        raise ValueError("No official market days on or before cutoff")
    print(f"Official calendar: {len(calendar)} market dates", flush=True)
    frames, failed = [], []

    def get_day(date):
        url = ("https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date="
               f"{date:%Y%m%d}&type=ALLBUT0999")
        path = download(url, raw / f"mi_index_{date:%Y%m%d}.json", args.delay)
        return normalize_quotes(json.loads(path.read_text()), date)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(get_day, day): day for day in calendar}
        for index, future in enumerate(as_completed(futures), 1):
            day = futures[future]
            try:
                frames.append(future.result())
            except Exception as error:
                failed.append(dict(date=str(day.date()), error=str(error)))
                print(f"FAILED {day.date()}: {error}", flush=True)
            if index % 10 == 0 or index == len(calendar):
                progress = dict(year=args.year, expected_dates=len(calendar),
                                successful_dates=len(frames), failed=failed)
                (output / f"download_progress_{args.year}{tag}.json").write_text(json.dumps(progress, indent=2))
                print(f"Progress {index}/{len(calendar)}; success={len(frames)}, failed={len(failed)}", flush=True)
    if failed:
        raise RuntimeError(f"{len(failed)} expected market dates failed. Re-run to resume; no quote file written.")
    result = pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"])
    actual = pd.DatetimeIndex(sorted(result.date.unique()))
    if not actual.equals(calendar):
        raise ValueError("Quote calendar does not exactly match official activity calendar")
    price = result[["open", "high", "low", "close"]]
    complete = price.notna().all(axis=1)
    bad_ohlc = complete & (result.high.lt(price.max(axis=1)) | result.low.gt(price.min(axis=1)))
    negative = result[["open", "high", "low", "close", "volume", "trades", "turnover_twd"]].lt(0).any(axis=1)
    if bad_ohlc.any() or negative.any():
        raise ValueError("Price/volume health check failed")
    path = output / f"quotes_twse_{args.year}{tag}.csv.gz"
    result.to_csv(path, index=False, date_format="%Y-%m-%d")
    summary = dict(year=args.year, as_of=str(cutoff.date()), expected_market_dates=len(calendar), downloaded_market_dates=len(actual),
                   rows=len(result), symbols=result.symbol.nunique(), duplicate_keys=0,
                   complete_ohlc_rows=int(complete.sum()), bad_ohlc=int(bad_ohlc.sum()),
                   negative_rows=int(negative.sum()), path=str(path))
    (output / f"health_twse_{args.year}{tag}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
