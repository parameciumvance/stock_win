"""Package one complete TWSE quote year with original bytes and SHA-256 proof.

The package contains annual quotes, the official calendar, and all downloaded
daily responses. Company-action sources are included when present, but are
not represented as complete merely because this quote package succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from twse_history.build_history import load_table
from twse_history.fetch_history import parse_isin


def package(root: Path, year: int, output: Path) -> dict:
    raw = root / f"data/raw/twse_{year}"
    history = root / "twse_history/raw"
    quote = root / f"inputs/quotes_twse_{year}.csv.gz"
    health = root / f"inputs/health_twse_{year}.json"
    if not quote.is_file() or not health.is_file():
        raise FileNotFoundError("Complete annual quotes and health report required")
    check = json.loads(health.read_text())
    if check.get("year") != year or check.get("expected_market_dates") != check.get("downloaded_market_dates"):
        raise ValueError("Annual health report is not complete")
    expected = []
    calendar_files = []
    for m in range(1, 13):
        path = history / f"calendar_{year}{m:02d}.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        rows = load_table(path, "日期", year)
        if rows.empty or not rows["日期"].dt.month.eq(m).all():
            raise ValueError(f"Invalid calendar month {path}")
        expected.extend(rows["日期"].tolist())
        calendar_files.append(path)
    days = pd.DatetimeIndex(sorted(expected))
    if days.has_duplicates or len(days) != check["expected_market_dates"]:
        raise ValueError("Calendar and health count mismatch")
    quote_dates = pd.to_datetime(pd.read_csv(quote, usecols=["date"]).date.unique())
    if not pd.DatetimeIndex(sorted(quote_dates)).equals(days):
        raise ValueError("Annual quote dates differ from official calendar")
    day_files = [raw / f"mi_index_{day:%Y%m%d}.json" for day in days]
    if any(not p.is_file() for p in day_files):
        raise FileNotFoundError("At least one official market date is missing raw quotes")
    action_keys = ("exrights", "reduction", "par_change", "split", "new_listing")
    annual_sources = [history / f"{key}_{year}.json" for key in action_keys]
    # The historical universe also depends on retrospective ISIN lookups and
    # removals after the research year. Preserve those exact cached snapshots.
    isins = history / "list.html"
    master = parse_isin(isins)
    observed = set(pd.read_csv(quote, usecols=["symbol"], dtype=str).symbol)
    missing_master = observed - set(master.symbol)
    detail = [history / f"isin_{s}.html" for s in sorted(missing_master)
              if len(s) == 4 and s.isdigit() and s[0] != "0"]
    removals = sorted(p for p in history.glob("delisted_*.json")
                      if not p.name.endswith(".meta.json"))
    if not removals or history / f"delisted_{year}.json" not in removals:
        raise FileNotFoundError("Historical delisting cache required")
    sources = [*annual_sources, *removals, isins, *detail]
    if any(not p.is_file() for p in sources):
        raise FileNotFoundError("Company-action or classification source missing")
    files = [quote, health, *calendar_files, *day_files, *sources]
    files_with_meta = []
    for p in files:
        meta = p.with_suffix(".meta.json")
        if p in calendar_files or p in day_files or p in sources:
            if not meta.is_file():
                raise FileNotFoundError(meta)
            expected_sha = json.loads(meta.read_text())["sha256"]
            if hashlib.sha256(p.read_bytes()).hexdigest() != expected_sha:
                raise ValueError(f"Metadata checksum mismatch: {p}")
            files_with_meta.append(meta)
    all_files = files + files_with_meta
    manifest = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size,
                 "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in all_files]
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for p in all_files:
            archive.write(p, str(p.relative_to(root)))
        archive.writestr("SHA256MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    return {"year": year, "market_days": len(days), "files": len(all_files),
            "archive": str(output), "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "company_actions_and_classification_sources": [p.name for p in sources]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.root, args.year, args.output), indent=2))


if __name__ == "__main__":
    main()
