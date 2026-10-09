"""Download and normalize official TWSE T86 daily institutional share flows.

Transactions are in shares, not lots or TWD. Missing daily rows stay missing.
Use the next official market day for features; exact release clocks and revision
history are not supplied by this endpoint. Historical foreign column semantics
remain explicit rather than being silently pooled across schema changes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
from pathlib import Path
import re
import time

import pandas as pd

def normalize_t86(payload, expected_date):
    if not re.fullmatch(r"\d{8}", expected_date):
        raise ValueError("Date must be YYYYMMDD")
    date.fromisoformat(expected_date[:4] + '-' + expected_date[4:6] + '-' + expected_date[6:])
    if payload.get("stat") != "OK" or payload.get("date") != expected_date:
        raise ValueError("T86 error/response date mismatch")
    fields = payload.get("fields", [])
    if len(fields) != len(set(fields)) or not payload.get("data"):
        raise ValueError("Duplicate fields or empty daily data")
    modern = "外陸資買賣超股數(不含外資自營商)" in fields
    prefix = "外陸資" if modern else "外資"
    suffix = "(不含外資自營商)" if modern else ""
    aliases = {
        "foreign_buy_shares": prefix + "買進股數" + suffix,
        "foreign_sell_shares": prefix + "賣出股數" + suffix,
        "foreign_net_shares": prefix + "買賣超股數" + suffix,
        "trust_buy_shares": "投信買進股數", "trust_sell_shares": "投信賣出股數",
        "trust_net_shares": "投信買賣超股數", "dealer_net_shares": "自營商買賣超股數",
        "dealer_self_buy_shares": "自營商買進股數(自行買賣)",
        "dealer_self_sell_shares": "自營商賣出股數(自行買賣)",
        "dealer_self_net_shares": "自營商買賣超股數(自行買賣)",
        "dealer_hedge_buy_shares": "自營商買進股數(避險)",
        "dealer_hedge_sell_shares": "自營商賣出股數(避險)",
        "dealer_hedge_net_shares": "自營商買賣超股數(避險)",
        "total_net_shares": "三大法人買賣超股數"}
    if modern:
        aliases.update({"foreign_dealer_buy_shares": "外資自營商買進股數",
                        "foreign_dealer_sell_shares": "外資自營商賣出股數",
                        "foreign_dealer_net_shares": "外資自營商買賣超股數"})
    required = {"證券代號", "證券名稱"} | set(aliases.values())
    if required.difference(fields):
        raise ValueError(f"Missing T86 fields: {sorted(required.difference(fields))}")
    records = []
    seen = set()
    for row in payload["data"]:
        if len(row) != len(fields):
            raise ValueError("Row width differs from declared fields")
        original = dict(zip(fields, row))
        symbol = original["證券代號"].strip()
        if not symbol or symbol in seen:
            raise ValueError("Missing/duplicate symbol")
        seen.add(symbol)
        record = {"date": date.fromisoformat(expected_date[:4] + '-' + expected_date[4:6] + '-' + expected_date[6:]).isoformat(),
                  "symbol": symbol, "name": original["證券名稱"].strip(),
                  "foreign_schema": "excluding_foreign_dealer" if modern else "legacy_foreign"}
        for target, source in aliases.items():
            raw = str(original[source]).strip().replace(",", "")
            if not re.fullmatch(r"[+-]?\d+", raw):
                raise ValueError(f"Noninteger/missing share value: {symbol} {source}")
            record[target] = int(raw)
            if ("_buy_" in target or "_sell_" in target) and record[target] < 0:
                raise ValueError("Negative gross buy/sell shares")
        for role in ("foreign", "trust", "dealer_self", "dealer_hedge") + (("foreign_dealer",) if modern else ()):
            if record[role + "_buy_shares"] - record[role + "_sell_shares"] != record[role + "_net_shares"]:
                raise ValueError(f"Buy/sell/net mismatch: {symbol} {role}")
        if record["dealer_self_net_shares"] + record["dealer_hedge_net_shares"] != record["dealer_net_shares"]:
            raise ValueError("Dealer components mismatch")
        if sum(record[k] for k in ("foreign_net_shares", "trust_net_shares", "dealer_net_shares")) != record["total_net_shares"]:
            raise ValueError("Total institutional mismatch; foreign dealer must not be counted twice")
        # Missing legacy foreign-dealer columns must not be reported as zero.
        for role in ("buy", "sell", "net"):
            record.setdefault("foreign_dealer_" + role + "_shares", None)
        records.append(record)
    return records


def market_days_from_cache(calendar_root, year, asof=None):
    cutoff = date.fromisoformat(asof) if asof else None
    if cutoff and cutoff.year != year:
        raise ValueError('As-of cutoff must belong to requested year')
    days = []
    for month in range(1, (cutoff.month if cutoff else 12) + 1):
        path = calendar_root / f"calendar_{year}{month:02d}.json"
        payload = json.loads(path.read_text())
        if payload.get("stat") != "OK" or not payload.get("data"):
            raise ValueError(f"Empty/error monthly calendar: {path}")
        for row in payload["data"]:
            yy, mm, dd = map(int, row[0].split("/"))
            day = date(yy + 1911, mm, dd)
            if day.year != year or day.month != month:
                raise ValueError("Wrong month in market calendar")
            if not cutoff or day <= cutoff:
                days.append(day.strftime("%Y%m%d"))
    if len(days) != len(set(days)):
        raise ValueError("Duplicate market dates")
    return sorted(days)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--dates", nargs="+")
    scope.add_argument("--year", type=int)
    parser.add_argument("--calendar-root", default="twse_history/raw")
    parser.add_argument("--asof", help="Partial-year cutoff YYYY-MM-DD")
    parser.add_argument("--cache", default="inputs/institutional_pilot")
    parser.add_argument("--output", default="deliverables/institutional_normalized.csv.gz")
    parser.add_argument("--universe", help="Historical CSV[.gz] with date,symbol,is_member; filter after full source validation")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--select-type", choices=["ALL", "ALLBUT0999"], default="ALL")
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    parser.add_argument("--delay", type=float, default=2)
    args = parser.parse_args()
    if args.delay < 1:
        raise ValueError("Keep at least one second between requests per worker")
    if args.asof and args.dates:
        parser.error('--asof applies only to --year')
    dates = args.dates or market_days_from_cache(Path(args.calendar_root), args.year, args.asof)
    if len(dates) != len(set(dates)):
        raise ValueError("Duplicate requested dates")
    root = Path(args.cache)
    members = None
    if args.universe:
        wanted = {day[:4] + '-' + day[4:6] + '-' + day[6:] for day in dates}
        members = {day: set() for day in wanted}
        for chunk in pd.read_csv(args.universe, usecols=["date", "symbol", "is_member"],
                                 dtype={"date": str, "symbol": str}, chunksize=200000):
            if not chunk.is_member.isin([True, False]).all():
                raise ValueError("Universe membership must be boolean")
            selected = chunk[chunk.date.isin(wanted) & chunk.is_member]
            for day, group in selected.groupby("date"):
                if len(group.symbol) != len(set(group.symbol)) or members[day].intersection(group.symbol):
                    raise ValueError("Duplicate date/symbol in historical universe")
                members[day].update(group.symbol)
        if any(not group for group in members.values()):
            raise ValueError("Historical universe missing requested dates")

    def one(day):
        name = "t86_" + day
        url = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=" + day + "&selectType=" + args.select_type
        native = root / (name + ".json")
        meta_path = root / (name + ".meta.json")
        cached = native.exists() and meta_path.exists()
        if not cached and args.fetch:
            import hashlib
            import urllib.request
            import urllib.error
            from datetime import datetime, timezone
            root.mkdir(parents=True, exist_ok=True)
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers={
                            "User-Agent": "stock-win-research/1.0 (historical source validation)"}), timeout=20) as response:
                        raw = response.read()
                        meta = {"source_url": url, "final_url": response.url, "http_status": response.status,
                                "fetched_at": datetime.now(timezone.utc).isoformat(), "bytes": len(raw),
                                "sha256": hashlib.sha256(raw).hexdigest()}
                    break
                except urllib.error.HTTPError as error:
                    if error.code not in (500, 502, 503, 504) or attempt == 2:
                        raise
                    time.sleep(5 * (attempt + 1))
                except (TimeoutError, urllib.error.URLError, ConnectionError):
                    if attempt == 2:
                        raise
                    time.sleep(5 * (attempt + 1))
            if meta["final_url"] != url or meta["http_status"] != 200:
                raise ValueError("T86 source redirected/errored")
            normalize_t86(json.loads(raw), day)  # Do not cache a failure as completed.
            native.write_bytes(raw)
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")
            time.sleep(args.delay)
        import hashlib
        raw = native.read_bytes()
        meta = json.loads(meta_path.read_text())
        if meta["source_url"] != url or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise ValueError("T86 source identity/checksum mismatch")
        if meta.get("final_url", url) != url or meta.get("http_status", 200) != 200:
            raise ValueError("Cached T86 source redirected/errored")
        result = normalize_t86(json.loads(raw), day)
        if members is not None:
            result = [row for row in result if row["symbol"] in members[row["date"]]]
        return result

    rows = []
    pool = ThreadPoolExecutor(max_workers=args.workers)
    futures = {pool.submit(one, day): day for day in dates}
    try:
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
            except Exception as error:
                raise RuntimeError(f"T86 source failed on {futures[future]}: {error}") from error
            rows.extend(result)
            if i % 5 == 0 or i == len(dates):
                print(f"completed={i}/{len(dates)} rows={len(rows)}", flush=True)
    except BaseException:
        for future in futures:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["date", "symbol"]).to_csv(path, index=False)
    print(f"saved={path} days={len(dates)} rows={len(rows)}", flush=True)


if __name__ == "__main__":
    main()

