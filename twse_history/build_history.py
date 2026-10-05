#!/usr/bin/env python3
"""Reconstruct a TWSE common-stock panel and auditable price adjustments.

The adjustment series removes official reference-price discontinuities. It is
NOT a shareholder total-return ledger. Historical classifications are recovered
from current ISIN records plus exact lookups of departed companies; original
point-in-time ISIN snapshots and announcement publication histories are absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .fetch_history import parse_isin


def date_value(value):
    parts = re.findall(r"\d+", str(value))
    if len(parts) == 1 and len(parts[0]) == 8:
        return pd.to_datetime(parts[0], format="%Y%m%d")
    if len(parts) != 3:
        raise ValueError(f"Invalid date: {value}")
    y, m, d = map(int, parts)
    if y < 1911:
        y += 1911
    return pd.Timestamp(y, m, d)


def number(value):
    return pd.to_numeric(str(value).replace(",", "").strip(), errors="coerce")


def load_table(path, date_column, year):
    path = Path(path)
    meta = path.with_suffix(".meta.json")
    if meta.exists():
        expected = json.loads(meta.read_text())["sha256"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source checksum mismatch: {path}")
    data = json.loads(path.read_text())
    status = str(data.get("stat", data.get("status", ""))).lower()
    if status != "ok":
        raise ValueError(f"Unexpected source status {status!r}: {path}")
    table = pd.DataFrame(data["data"], columns=data["fields"])
    if table.empty:
        return table
    table[date_column] = table[date_column].map(date_value)
    if not table[date_column].dt.year.eq(year).all():
        raise ValueError(f"API ignored the requested historical year: {path}")
    return table


def load_delistings(raw):
    frames = []
    for path in sorted(Path(raw).glob("delisted_*.json")):
        if path.name.endswith(".meta.json"):
            continue
        year = int(path.stem.split("_")[-1])
        table = load_table(path, "終止上市日期", year)
        if not table.empty:
            frames.append(table.rename(columns={"上市編號": "symbol", "公司名稱": "name",
                                                "終止上市日期": "delisted_date"}))
    if not frames:
        raise ValueError("No official delisting snapshots")
    table = pd.concat(frames, ignore_index=True)
    table["symbol"] = table.symbol.str.strip()
    if table.symbol.duplicated().any():
        raise ValueError("Repeated delisting ticker requires an identity/spell review")
    return table


def classify_security(symbol, cfi, delisted_symbols, observed_name=""):
    if cfi.startswith("ES"):
        return "common_stock", "official_isin_cfi"
    if cfi.startswith("ED"):
        return "depository_receipt", "official_isin_cfi"
    if cfi.startswith("EP") or cfi.startswith("EF"):
        return "preferred_or_other_equity", "official_isin_cfi"
    if cfi:
        return "fund_note_or_other", "official_isin_cfi"
    # Retired depositary receipts may be absent from today's ISIN master.
    # Both four- and six-digit 9xxx tickers existed in historical quotes.
    # Check the official quote name BEFORE the four-digit delisted-issuer rule.
    if re.fullmatch(r"9(?:[0-9]{3}|[0-9]{5})", symbol) and str(observed_name).upper().endswith("-DR"):
        return "depository_receipt", "official_quote_name_dr_and_ticker_format"
    # Older delisting feeds/quote names omit -DR. These exact retired codes
    # are documented as TDRs by TWSE (2010 annual report, 2012 fact book)
    # or the depositary bank; do not infer all six-digit codes are TDRs.
    # https://www.twse.com.tw/downloads/zh/about/company/annual_99.pdf
    # https://www.twse.com.tw/downloads/zh/about/company/factbook/2012/1.06.htm
    # https://www.feib.com.tw/UpFiles/wealthmanagement/pdf/HA_TDR-letter.pdf
    if symbol in {"910069", "911609", "911612", "913889"} and symbol in delisted_symbols:
        return "depository_receipt", "documented_legacy_dr"
    # A historical issuer on the official company delisting list with a normal
    # four-digit ticker can be retained even if its ISIN has been retired.
    if re.fullmatch(r"[1-9][0-9]{3}", symbol) and symbol in delisted_symbols:
        return "common_stock", "official_delisted_issuer_and_ticker_format"
    if symbol.startswith("00"):
        return "fund", "ticker_format_fallback"
    # Retired REIT / real-estate trust certificates can disappear from the
    # current ISIN master; e.g. 01003T traded in 2023 but is absent in 2026.
    # The surviving 01xxxT peers have official CBCIXU (non-equity) CFI codes.
    if re.fullmatch(r"01[0-9]{3}T", symbol):
        return "fund", "historical_reit_ticker_format_fallback"
    if symbol.startswith("02"):
        return "note", "ticker_format_fallback"
    if re.fullmatch(r"[1-9][0-9]{3}[A-Z][0-9]?", symbol):
        return "non_common_equity", "ticker_format_fallback"
    return "unresolved", "unresolved"


def build_universe(quotes, raw, calendar):
    master = parse_isin(Path(raw) / "list.html")
    lookup = master.set_index("symbol")
    if lookup.index.duplicated().any():
        raise ValueError("Duplicate symbols in ISIN master")
    for path in sorted(Path(raw).glob("isin_[0-9]*.html")):
        symbol = path.stem.split("_")[-1]
        try:
            matches = parse_isin(path, detail=True)
        except ValueError:
            continue
        matches = matches[matches.symbol.eq(symbol)]
        if len(matches) == 1 and symbol not in lookup.index:
            lookup = pd.concat([lookup, matches.set_index("symbol")])
    delisted = load_delistings(raw)
    delisted_map = delisted.set_index("symbol").delisted_date
    records, daily, names = [], [], []
    for symbol, group in quotes.groupby("symbol", sort=True):
        group = group.sort_values("date")
        ref = lookup.loc[symbol] if symbol in lookup.index else pd.Series(dtype=object)
        cfi = str(ref.get("cfi", ""))
        kind, evidence = classify_security(symbol, cfi, set(delisted_map.index),
                                           group.name.iloc[-1])
        start, end = group.date.min(), group.date.max()
        delist = delisted_map.get(symbol, pd.NaT)
        if pd.notna(delist) and (group.date >= delist).any():
            raise ValueError(f"Quote on/after official delisting: {symbol}")
        begin = start
        # Current ISIN dates can inherit a predecessor's listing date (e.g.
        # 3717 in 2025). NEVER backfill membership from today's master date.
        # This observed-history universe starts at its first quote in the sample.
        if ref.get("classification_source") == "list.html":
            listed = date_value(ref["listed_date_snapshot"])
        else:
            listed = pd.NaT
        record = dict(symbol=symbol, name_last_observed=group.name.iloc[-1],
                      security_type=kind, classification_basis=evidence,
                      classification_source=ref.get("classification_source", ""),
                      cfi_snapshot=cfi, isin_snapshot=ref.get("isin", ""),
                      market_snapshot=ref.get("market", ""),
                      first_observed_date=start, last_observed_date=end,
                      listed_date_snapshot=listed, delisted_date=delist,
                      membership_start=begin, membership_end_exclusive=delist,
                      membership_start_basis="first_historical_quote_in_sample",
                      quote_rows=len(group), priced_rows=int(group.close.notna().sum()))
        records.append(record)
        if kind != "common_stock":
            continue
        dates = calendar[calendar >= begin]
        if pd.notna(delist):
            dates = dates[dates < delist]
        member = pd.DataFrame({"date": dates, "symbol": symbol, "is_member": True})
        cols = ["date", "name", "open", "high", "low", "close", "volume"]
        member = member.merge(group[cols].assign(quote_present=True), on="date", how="left", validate="one_to_one")
        member["quote_present"] = member.quote_present.eq(True)
        member["has_ohlc"] = member[["open", "high", "low", "close"]].gt(0).all(axis=1)
        member["eligible_price_signal"] = member.has_ohlc & member.volume.gt(0)
        member["quote_state"] = np.select(
            [~member.quote_present, ~member.has_ohlc],
            ["missing_or_suspended", "present_without_full_ohlc"], default="observed")
        # Historical API responses may themselves contain today's names.
        # Names are display-only; forward propagation is not a rename history.
        member["name"] = member.name.ffill()
        daily.append(member[["date", "symbol", "name", "is_member", "quote_present",
                             "has_ohlc", "eligible_price_signal", "quote_state"]])
        changes = group.loc[group.name.ne(group.name.shift()), ["date", "symbol", "name"]].copy()
        changes["event"] = "name_change_in_retrieved_quotes"
        changes.iloc[0, changes.columns.get_loc("event")] = "initial_name_in_sample"
        names.append(changes)
    security_master = pd.DataFrame(records)
    unresolved = security_master[security_master.security_type.eq("unresolved")]
    if len(unresolved):
        raise ValueError(f"Unclassified securities: {unresolved.symbol.tolist()}")
    return security_master, pd.concat(daily, ignore_index=True), pd.concat(names, ignore_index=True), delisted


def collapse_identical_action_rows(result):
    """Use one factor for duplicate rows, with a narrow reference-field priority."""
    keep = []
    for _, group in result.groupby(["symbol", "effective_date"], sort=False):
        if len(group) == 1:
            keep.append(group.iloc[0].copy())
            continue
        common = ["event_type", "event_subtype", "official_previous_close"]
        if any(group[field].nunique(dropna=False) != 1 for field in common):
            raise ValueError("Same-symbol same-day actions require composite-event review; not multiplied automatically")
        if group.source_file.nunique() != 1:
            raise ValueError("Same-symbol same-day actions have different sources")
        economics = ["official_reference", "adjustment_factor", "selected_reference_field"]
        if all(group[field].nunique(dropna=False) == 1 for field in economics):
            selected = group.sort_values("source_row_1based").iloc[-1].copy()
            resolution = "identical_economics"
        else:
            corrected = group[group.selected_reference_field.eq("除權參考價")]
            uncorrected = group[group.selected_reference_field.eq("恢復買賣參考價")]
            if (group.event_type.iloc[0] != "reduction" or corrected.empty or
                    len(corrected) + len(uncorrected) != len(group) or
                    corrected.official_reference.nunique() != 1 or
                    uncorrected.official_reference.nunique() != 1 or
                    corrected.adjustment_factor.nunique() != 1):
                raise ValueError("Same-symbol same-day actions require composite-event review; not multiplied automatically")
            # The reduction feed may retain a preliminary resumption reference
            # and a later row with the explicit ex-right reference. The latter
            # already has priority in load_actions; never multiply both.
            selected = corrected.sort_values("source_row_1based").iloc[0].copy()
            resolution = "official_exrights_reference_over_resumption"
        selected["duplicate_source_rows_1based"] = ",".join(map(str, sorted(group.source_row_1based)))
        selected["duplicate_resolution"] = resolution
        keep.append(selected)
    return pd.DataFrame(keep).reset_index(drop=True)


def load_actions(raw, year, cutoff):
    specs = [
        ("exrights", "資料日期", "股票代號", "股票名稱", "除權息前收盤價", "除權息參考價"),
        ("reduction", "恢復買賣日期", "股票代號", "名稱", "停止買賣前收盤價格", "恢復買賣參考價"),
        ("par_change", "恢復買賣日期", "股票代號", "名稱", "停止買賣前收盤價格", "恢復買賣參考價"),
        ("split", "恢復買賣日期", "ETF代號", "名稱", "停止買賣前收盤價格", "恢復買賣參考價"),
    ]
    records = []
    for kind, date_col, code_col, name_col, before_col, ref_col in specs:
        path = Path(raw) / f"{kind}_{year}.json"
        table = load_table(path, date_col, year)
        meta = json.loads(path.with_suffix(".meta.json").read_text())
        for index, row in table.iterrows():
            effective = row[date_col]
            if effective > cutoff:
                continue
            before, reference = number(row[before_col]), number(row[ref_col])
            selected_ref_field = ref_col
            if kind == "reduction" and pd.notna(number(row.get("除權參考價"))):
                reference = number(row["除權參考價"])
                selected_ref_field = "除權參考價"
            if not np.isfinite(before) or not np.isfinite(reference) or min(before, reference) <= 0:
                raise ValueError(f"Invalid adjustment prices: {path.name} row {index + 1}")
            symbol = row[code_col].strip()
            factor = reference / before
            records.append(dict(event_id=f"{kind}:{symbol}:{effective:%Y%m%d}",
                symbol=symbol, name=row[name_col], event_type=kind,
                event_subtype=row.get("權/息", row.get("減資原因", row.get("分割(反分割)", ""))),
                effective_date=effective, official_previous_close=before,
                official_reference=reference, selected_reference_field=selected_ref_field,
                reference_factor=factor, adjustment_factor=factor,
                factor_basis="official_reference_ratio", confirmed_share_ratio=np.nan,
                ratio_source_url="", source_file=path.name, source_row_1based=index + 1,
                source_url=meta["url"], retrieved_at=meta["fetched_at"],
                source_sha256=meta["sha256"], announcement_published_at=""))
    result = pd.DataFrame(records)
    supplemental = Path(raw) / "verified_supplemental_actions.json"
    if supplemental.exists():
        additional = []
        for item in json.loads(supplemental.read_text()):
            effective = date_value(item["effective_date"])
            if effective.year != year or effective > cutoff:
                continue
            for key in ("source_file", "relisting_source_file"):
                source = Path(raw) / item[key]
                metadata = json.loads(source.with_suffix(".meta.json").read_text())
                if hashlib.sha256(source.read_bytes()).hexdigest() != metadata["sha256"]:
                    raise ValueError(f"Supplemental evidence checksum mismatch: {source}")
                if metadata["url"] != item[key.replace("_file", "_url")]:
                    raise ValueError("Supplemental evidence URL mismatch")
            source_meta = json.loads((Path(raw) / item["source_file"]).with_suffix(".meta.json").read_text())
            ratio = float(item["new_shares_per_old_share"])
            before = float(item["previous_quote_close"])
            if not np.isfinite(ratio) or not 0 < ratio < 1 or not np.isfinite(before) or before <= 0:
                raise ValueError("Invalid supplemental loss-reduction terms")
            if date_value(item["announcement_published_at"]) > effective:
                raise ValueError("Supplemental action publication after effective date")
            additional.append(dict(event_id=item["event_id"], symbol=item["symbol"],
                name=item["name"], event_type="reduction", event_subtype="loss_absorption",
                effective_date=effective, official_previous_close=before,
                official_reference=before / ratio,
                selected_reference_field="derived_from_confirmed_share_ratio",
                reference_factor=1 / ratio, adjustment_factor=1 / ratio,
                factor_basis="confirmed_share_ratio_with_official_previous_quote",
                confirmed_share_ratio=ratio, ratio_source_url=source_meta["url"],
                source_file=item["source_file"], source_row_1based=item["source_page_1based"],
                source_url=source_meta["url"], retrieved_at=source_meta["fetched_at"],
                source_sha256=source_meta["sha256"],
                announcement_published_at=item["announcement_published_at"],
                relisting_source_url=item["relisting_source_url"]))
        if additional:
            result = pd.concat([result, pd.DataFrame(additional)], ignore_index=True)
    overrides = Path(raw) / "verified_share_ratios.json"
    if overrides.exists():
        for item in json.loads(overrides.read_text()):
            mask = result.event_id.eq(item["event_id"])
            if not mask.any():
                continue
            if mask.sum() != 1:
                raise ValueError("Ratio override has ambiguous event identity")
            if result.loc[mask, "event_type"].iloc[0] not in ("split", "par_change"):
                raise ValueError("Share-ratio override only applies to pure splits")
            ratio = float(item["new_shares_per_old_share"])
            if ratio <= 0 or not np.isfinite(ratio):
                raise ValueError("Invalid confirmed split ratio")
            exact = result.loc[mask, "official_previous_close"] / ratio
            if (abs(exact - result.loc[mask, "official_reference"]) > 0.010001).any():
                raise ValueError("Confirmed split ratio conflicts with reference price")
            result.loc[mask, "adjustment_factor"] = 1 / ratio
            result.loc[mask, "factor_basis"] = "confirmed_share_ratio"
            result.loc[mask, "confirmed_share_ratio"] = ratio
            result.loc[mask, "ratio_source_url"] = item["source_url"]
            result.loc[mask, "announcement_published_at"] = item.get("published_at", "")
    result = collapse_identical_action_rows(result)
    return result.sort_values(["symbol", "effective_date"]).reset_index(drop=True)


def adjust_prices(quotes, actions, cutoff):
    """Causal series uses only events already effective on each row's date.

    backward_factor includes later events through cutoff and is for charts only.
    An event on d affects causal prices at d and backward prices strictly before d.
    """
    quotes = quotes.loc[quotes.date.le(cutoff)].copy()
    actions = actions.loc[actions.effective_date.le(cutoff)].copy()
    if actions.duplicated(["symbol", "effective_date"]).any():
        raise ValueError("Duplicate/composite corporate action")
    if not np.isfinite(actions.adjustment_factor).all() or actions.adjustment_factor.le(0).any():
        raise ValueError("All adjustment factors must be finite and positive")
    groups = {symbol: group.sort_values("effective_date") for symbol, group in actions.groupby("symbol")}
    frames = []
    for symbol, group in quotes.groupby("symbol", sort=False):
        group = group.sort_values("date").copy()
        events = groups.get(symbol)
        cumulative = np.ones(len(group))
        terminal = 1.0
        if events is not None:
            products = np.r_[1.0, np.cumprod(events.adjustment_factor.to_numpy(float))]
            indices = np.searchsorted(events.effective_date.to_numpy(), group.date.to_numpy(), side="right")
            cumulative = products[indices]
            terminal = products[-1]
        group["causal_factor"] = 1.0 / cumulative
        group["backward_factor"] = terminal / cumulative
        for field in ("open", "high", "low", "close"):
            group[f"adj_{field}"] = group[field] * group.causal_factor
        group["back_adj_close"] = group.close * group.backward_factor
        frames.append(group)
    return pd.concat(frames, ignore_index=True)


def full_window_max(values, horizon):
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    values = np.asarray(values, dtype=float)
    maximum = np.full(len(values), np.nan)
    if len(values) > horizon:
        windows = np.lib.stride_tricks.sliding_window_view(values[1:], horizon)
        valid = np.isfinite(windows).all(axis=1) & (windows > 0).all(axis=1)
        maxima = np.max(np.where(np.isfinite(windows), windows, -np.inf), axis=1)
        maximum[:len(windows)] = np.where(valid, maxima, np.nan)
    return maximum


def build_labels(prices, members, calendar, horizon=20, threshold=0.30):
    out = []
    member_dates = {symbol: pd.DatetimeIndex(group.date)
                    for symbol, group in members.groupby("symbol", sort=False)}
    for symbol, group in prices.groupby("symbol", sort=False):
        valid_dates = member_dates.get(symbol, pd.DatetimeIndex([]))
        if valid_dates.empty:
            continue
        panel = group.set_index("date").reindex(calendar)
        raw_high = full_window_max(panel.high.to_numpy(), horizon)
        adj_high = full_window_max(panel.adj_high.to_numpy(), horizon)
        future_days = len(calendar) - 1 - np.arange(len(calendar))
        current_valid = panel.close.gt(0).to_numpy() & np.isfinite(panel.close.to_numpy())
        complete = np.isfinite(adj_high)
        panel["label_available"] = complete & current_valid
        # Target metadata, never input features. Needed for chronological purging.
        panel["label_window_end"] = pd.Series(calendar, index=calendar).shift(-horizon)
        panel["entry_market_date"] = pd.Series(calendar, index=calendar).shift(-1)
        panel["censor_reason"] = np.select(
            [~current_valid, future_days < horizon, ~complete],
            ["missing_signal_close", "insufficient_market_horizon", "missing_future_high"], default="")
        panel["future_adj_high_max"] = adj_high
        panel["adj_max_return"] = adj_high / panel.adj_close - 1
        panel["raw_max_return"] = raw_high / panel.close - 1
        panel["entry_open_next_raw"] = panel.open.shift(-1)
        panel["entry_open_next_adj"] = panel.adj_open.shift(-1)
        panel["next_open_max_return"] = adj_high / panel.entry_open_next_adj - 1
        for name, returns, eligible in [
            ("surge_adjusted", "adj_max_return", panel.label_available),
            ("surge_raw_same_window", "raw_max_return", panel.label_available),
            ("surge_next_open", "next_open_max_return", panel.label_available & panel.entry_open_next_adj.gt(0)),
        ]:
            panel[name] = pd.Series(pd.NA, index=panel.index, dtype="boolean")
            panel.loc[eligible, name] = panel.loc[eligible, returns].ge(threshold - 1e-12)
        panel["symbol"] = symbol
        panel = panel.loc[panel.index.isin(valid_dates)]
        out.append(panel[["symbol", "name", "close", "adj_close", "label_available", "censor_reason",
                          "label_window_end", "entry_market_date",
                          "future_adj_high_max", "adj_max_return", "raw_max_return",
                          "entry_open_next_raw", "entry_open_next_adj", "next_open_max_return",
                          "surge_adjusted", "surge_raw_same_window", "surge_next_open"]]
                   .rename_axis("date").reset_index())
    return pd.concat(out, ignore_index=True)


def audit_events(prices, actions):
    groups = {s: g.sort_values("date") for s, g in prices.groupby("symbol")}
    rows = []
    for _, event in actions.iterrows():
        if event.symbol not in groups:
            continue
        group = groups[event.symbol]
        before = group[group.date.lt(event.effective_date) & group.close.notna()]
        after = group[group.date.ge(event.effective_date) & group.close.notna()]
        record = event.to_dict()
        if before.empty or after.empty:
            record["audit_state"] = "no_quote_on_one_side_in_sample"
        else:
            b, a = before.iloc[-1], after.iloc[0]
            record.update(observed_before_date=b.date, observed_after_date=a.date,
                          observed_before_close=b.close, observed_after_close=a.close,
                          previous_close_difference=b.close - event.official_previous_close,
                          raw_close_change=a.close / b.close - 1,
                          adjusted_close_change=a.adj_close / b.adj_close - 1,
                          audit_state="matched" if abs(b.close - event.official_previous_close) < 0.010001 else "review_previous_close")
        rows.append(record)
    return pd.DataFrame(rows)


def save_csv(frame, path):
    frame.to_csv(path, index=False, date_format="%Y-%m-%d", float_format="%.12g")


def compare_listing_dates(new, quotes, calendar):
    """Keep the scheduled date and compare first quotes with actual market days."""
    first = quotes.groupby("symbol").date.min().rename("first_quote_date")
    new = new.merge(first, on="symbol", how="left", validate="one_to_one")
    new["matches"] = new.official_listed_date.eq(new.first_quote_date)
    calendar = pd.DatetimeIndex(calendar).sort_values()
    positions = calendar.searchsorted(new.official_listed_date)
    new["calendar_expected_first_quote"] = [
        calendar[i] if i < len(calendar) else pd.NaT for i in positions]
    new["matches_market_calendar"] = new.calendar_expected_first_quote.eq(new.first_quote_date)
    new["scheduled_on_non_market_day"] = ~new.official_listed_date.isin(calendar)
    return new


def audit_listing_coverage(quotes, raw, year, cutoff, calendar=None):
    new = load_table(Path(raw) / f"new_listing_{year}.json", "股票上市買賣日期", year)
    new = new[new["股票上市買賣日期"].le(cutoff)].copy()
    new = new[["公司代號", "公司簡稱", "股票上市買賣日期"]].rename(
        columns={"公司代號": "symbol", "公司簡稱": "name", "股票上市買賣日期": "official_listed_date"})
    if calendar is None:
        calendar = pd.DatetimeIndex(sorted(quotes.date.unique()))
    new = compare_listing_dates(new, quotes, calendar)
    current = parse_isin(Path(raw) / "list.html")
    current = current[current.cfi.str.startswith("ES")].copy()
    current["date"] = current.listed_date_snapshot.map(date_value)
    missing = current[current.date.le(cutoff) & ~current.symbol.isin(quotes.symbol)]
    return new, missing[["symbol", "name", "listed_date_snapshot"]]


def audit_large_moves(prices, new_listings):
    p = prices[prices.close.notna()].sort_values(["symbol", "date"]).copy()
    p["previous_quote_date"] = p.groupby("symbol").date.shift()
    p["raw_close_change"] = p.groupby("symbol").close.pct_change(fill_method=None)
    p["adjusted_close_change"] = p.groupby("symbol").adj_close.pct_change(fill_method=None)
    p = p[p.adjusted_close_change.abs().gt(0.30)]
    p = p.merge(new_listings[["symbol", "official_listed_date"]], on="symbol", how="left")
    return p[["date", "symbol", "name", "previous_quote_date", "close",
              "raw_close_change", "adjusted_close_change", "official_listed_date"]]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quotes", required=True)
    p.add_argument("--year", type=int, default=2025)
    p.add_argument("--raw", default="twse_history/raw")
    p.add_argument("--output", default="twse_history/output")
    p.add_argument("--as-of", help="Effective-event and quote cutoff, YYYY-MM-DD")
    p.add_argument("--horizon", type=int, default=20)
    p.add_argument("--threshold", type=float, default=0.30)
    args = p.parse_args()
    if args.horizon < 1 or not np.isfinite(args.threshold) or args.threshold <= 0:
        p.error("horizon >= 1 and a finite positive threshold are required")
    cutoff = pd.Timestamp(args.as_of or f"{args.year}-12-31")
    if cutoff.year != args.year:
        p.error("--as-of must be in --year; build and audit one year at a time")
    quotes = pd.read_csv(args.quotes, dtype={"symbol": str, "name": str}, parse_dates=["date"])
    if quotes.duplicated(["symbol", "date"]).any():
        raise ValueError("Duplicate quotes")
    quotes = quotes[quotes.date.dt.year.eq(args.year) & quotes.date.le(cutoff)].copy()
    if quotes.empty:
        raise ValueError("Empty quote interval")
    calendar = pd.DatetimeIndex(sorted(quotes.date.unique()))
    master, members, names, delisted = build_universe(quotes, args.raw, calendar)
    new_listings, coverage_missing = audit_listing_coverage(quotes, args.raw, args.year, cutoff)
    actions = load_actions(args.raw, args.year, cutoff)
    common = set(master.loc[master.security_type.eq("common_stock"), "symbol"])
    # 0050 is a separately flagged benchmark, never a common-stock candidate.
    included = common | {"0050"}
    prices = adjust_prices(quotes[quotes.symbol.isin(included)], actions, cutoff)
    prices["universe_role"] = np.where(prices.symbol.eq("0050"), "benchmark", "common_stock")
    audit = audit_events(prices, actions)
    large_moves = audit_large_moves(prices, new_listings)
    labels = build_labels(prices[prices.symbol.isin(common)], members, calendar, args.horizon, args.threshold)
    common_actions = actions[actions.symbol.isin(common)]
    valid = labels[labels.label_available]
    next_valid = labels[labels.surge_next_open.notna()]
    removed = valid.surge_raw_same_window.eq(True) & valid.surge_adjusted.eq(False)
    added = valid.surge_raw_same_window.eq(False) & valid.surge_adjusted.eq(True)
    manifest = []
    for path in sorted(Path(args.raw).glob("*.meta.json")):
        manifest.append(dict(file=path.name, **json.loads(path.read_text())))
    summary = dict(year=args.year, as_of=str(cutoff.date()), horizon=args.horizon, threshold=args.threshold,
        calendar_days=len(calendar), historical_common_symbols=len(common),
        security_type_counts=master.security_type.value_counts().to_dict(),
        historical_common_quote_rows=int(master.loc[master.symbol.isin(common), "quote_rows"].sum()),
        common_membership_rows=len(members), quote_state_counts=members.quote_state.value_counts().to_dict(),
        all_source_events=len(actions), common_stock_events=len(common_actions),
        common_events_by_type=common_actions.event_type.value_counts().to_dict(),
        benchmark_events=int(actions.symbol.eq("0050").sum()),
        event_audit_states=audit.audit_state.value_counts().to_dict(),
        official_new_listings_checked=len(new_listings),
        new_listing_date_mismatches=int((~new_listings.matches).sum()),
        current_common_listed_before_cutoff_but_unobserved=len(coverage_missing),
        snapshot_listing_date_before_first_observation=master.loc[
            master.security_type.eq("common_stock") & master.first_observed_date.gt(calendar.min()) &
            master.listed_date_snapshot.lt(master.first_observed_date), "symbol"].tolist(),
        adjusted_close_jumps_over_30pct=len(large_moves),
        delisted_in_research_year=delisted[delisted.delisted_date.dt.year.eq(args.year)].symbol.tolist(),
        historical_common_absent_current_master=master.loc[master.symbol.isin(common) & ~master.classification_source.eq("list.html"), "symbol"].tolist(),
        label_rows=len(labels), labels_available=len(valid), adjusted_positive=int(valid.surge_adjusted.sum()),
        adjusted_positive_rate=float(valid.surge_adjusted.mean()),
        raw_positive_same_eligible_windows=int(valid.surge_raw_same_window.sum()),
        raw_positive_removed_by_adjustment=int(removed.sum()),
        positives_added_by_adjustment=int(added.sum()),
        next_open_labels_available=len(next_valid), next_open_positive=int(next_valid.surge_next_open.sum()),
        next_open_positive_rate=float(next_valid.surge_next_open.mean()),
        censor_reasons=labels.loc[~labels.label_available, "censor_reason"].value_counts().to_dict(),
        last_label_date=str(valid.date.max().date()),
        quote_input_sha256=hashlib.sha256(Path(args.quotes).read_bytes()).hexdigest(),
        limitations=["Classification is retrospectively reconstructed, not archived daily ISIN snapshots.",
                     "Membership includes observed historical common stocks; no pre-sample history is invented.",
                     "Reference-continuity returns are not investor total returns or fill-verified strategy P&L.",
                     "Missing future prices censor labels; this may bias evaluation if treated as random missingness.",
                     "Publication timestamps, complete suspension reasons, mergers and delisting consideration remain incomplete.",
                     "Names in historical API responses may be current names; they are display-only and do not prove rename dates.",
                     "Back-adjusted price levels use future events through cutoff; use causal series for features."])
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    suffix = f"{args.year}"
    for data, filename in [
        (master, f"security_master_{suffix}.csv"),
        (members, f"universe_daily_{suffix}.csv.gz"),
        (names, f"observed_name_history_{suffix}.csv"),
        (delisted, f"delistings_observed_{suffix}.csv"),
        (new_listings, f"new_listings_audit_{suffix}.csv"),
        (coverage_missing, f"universe_coverage_gaps_{suffix}.csv"),
        (actions, f"corporate_actions_{suffix}.csv"),
        (audit, f"corporate_action_audit_{suffix}.csv"),
        (large_moves, f"large_price_moves_{suffix}.csv"),
        (members.groupby("date").agg(common_members=("symbol", "size"),
                                     observed_quotes=("quote_present", "sum"),
                                     eligible_price_signals=("eligible_price_signal", "sum")).reset_index(),
         f"universe_daily_counts_{suffix}.csv"),
        (prices, f"prices_adjusted_{suffix}.csv.gz"),
        (labels, f"surge_labels_adjusted_{suffix}.csv.gz"),
        (valid.loc[removed | added], f"label_changes_{suffix}.csv"),
    ]:
        save_csv(data, output / filename)
    (output / f"summary_{suffix}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (output / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
