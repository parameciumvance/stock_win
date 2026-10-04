#!/usr/bin/env python3
"""Download public TWSE sources. Cache original bytes with URL/time/SHA-256.

Run from the directory containing twse_history:
    python -m twse_history.fetch_history --year 2025 --quotes input.csv.gz
Historical result tables are used; current-only preannouncement APIs are not.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        if tag == "tr":
            self.rows.append(self.row)


def html_rows(path):
    raw = Path(path).read_bytes()
    for encoding in ("utf-8", "cp950"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Unrecognized encoding: {path}")
    parser = TableParser()
    parser.feed(text)
    return parser.rows


def parse_isin(path, detail=False):
    result = []
    for row in html_rows(path):
        if detail and len(row) == 10 and row[0].isdigit():
            _, isin, symbol, name, market, kind, industry, date, cfi, remark = row
        elif not detail and len(row) == 7 and re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", row[1]):
            code_name, isin, date, market, industry, cfi, remark = row
            symbol, name = re.split(r"\s+", code_name, maxsplit=1)
            kind = ""
        else:
            continue
        result.append(dict(symbol=symbol, name=name, isin=isin, market=market,
                           security_type=kind, industry_snapshot=industry,
                           listed_date_snapshot=date, cfi=cfi, remark=remark,
                           classification_source=Path(path).name))
    if not result:
        raise ValueError(f"No ISIN records parsed: {path}")
    return pd.DataFrame(result)


def download(url, path, delay=3):
    path = Path(path)
    meta = path.with_suffix(".meta.json")
    if path.exists():
        if meta.exists():
            saved = json.loads(meta.read_text())
            if saved["url"] != url:
                raise ValueError(f"Cache URL mismatch: {path}")
            if saved["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError(f"Cache checksum mismatch: {path}")
        else:
            # Existing source fetched earlier in the same session; file mtime is
            # explicitly recorded rather than pretending it was fetched again.
            meta.write_text(json.dumps(dict(url=url,
                fetched_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                timestamp_basis="existing_file_mtime",
                sha256=hashlib.sha256(path.read_bytes()).hexdigest()), indent=2))
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "TWSE-research/0.2"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
            if path.suffix == ".json":
                json.loads(raw)  # Never cache a 200 HTML error as JSON.
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_bytes(raw)
            temp.replace(path)
            meta.write_text(json.dumps(dict(url=url,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                sha256=hashlib.sha256(raw).hexdigest()), indent=2))
            print(f"Saved {path.name}: {len(raw):,} bytes", flush=True)
            time.sleep(delay)
            return path
        except Exception:
            if attempt == 2:
                raise
            time.sleep(delay * (attempt + 1))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--quotes", required=True)
    p.add_argument("--raw", default="twse_history/raw")
    p.add_argument("--delay", type=float, default=3)
    args = p.parse_args()
    raw = Path(args.raw)
    year = args.year
    base = "https://www.twse.com.tw/rwd/zh/"
    for key, route in [("exrights", "exRight/TWT49U"),
                       ("reduction", "reducation/TWTAUU"),
                       ("par_change", "change/TWTB8U"),
                       ("split", "split/TWTCAU")]:
        url = f"{base}{route}?startDate={year}0101&endDate={year}1231&response=json"
        download(url, raw / f"{key}_{year}.json", args.delay)
    # Cover removals from the research year until this master snapshot.
    for y in range(year, datetime.now(timezone.utc).year + 1):
        url = f"{base}company/suspendListing?date={y}0101&response=json"
        download(url, raw / f"delisted_{y}.json", args.delay)
    download(f"{base}company/newlisting?date={year}0101&response=json",
             raw / f"new_listing_{year}.json", args.delay)
    download("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", raw / "list.html", args.delay)
    master = parse_isin(raw / "list.html")
    quotes = pd.read_csv(args.quotes, usecols=["symbol"], dtype=str)
    missing = sorted(set(quotes.symbol) - set(master.symbol))
    for symbol in missing:
        # Exact official lookup for historical common-stock candidates, including
        # companies absent from today's listing master. ETFs etc. remain separate.
        if re.fullmatch(r"[1-9][0-9]{3}", symbol):
            url = f"https://isin.twse.com.tw/isin/class_main.jsp?owncode={symbol}"
            download(url, raw / f"isin_{symbol}.html", args.delay)
    print("Source acquisition complete. Run build_history to validate contents.")


if __name__ == "__main__":
    main()
