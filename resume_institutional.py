"""Resume the frozen institutional comparison after restoring its verified inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

from twse_history.fetch_history import download
from twse_history.institutional import market_days_from_cache

BUNDLE_SHA256 = "2e2654a125e7b33ac284cd5796be151738101b2ecb88f8407fae0f99317c4e94"
CHECKPOINT_2024_SHA256 = "09962d23827ad5be91d3f3ba3424107ab2cf1e3222709d2e2b6b847a9cf1b765"
PRICE_ROOT = Path("twse_history/output_multiyear_2023_2026_asof_20261002")
CALENDAR_ROOT = Path("twse_history/raw")


def restore_archive(path, expected_sha256):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Reproduction archive checksum mismatch")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive member")
        for name in names:
            target = Path(name)
            if target.is_absolute() or ".." in target.parts or "\\" in name:
                raise ValueError("Unsafe archive member")
            if not target.resolve().is_relative_to(Path.cwd().resolve()):
                raise ValueError("Archive member escapes workspace through symlink")
        if archive.testzip() is not None:
            raise ValueError("Archive CRC failure")
        manifest = json.loads(archive.read("SHA256MANIFEST.json"))
        for name, expected in manifest.items():
            target = Path(name)
            if target.is_absolute() or ".." in target.parts:
                raise ValueError("Unsafe archive member")
            raw = archive.read(name)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("Archive member checksum mismatch: " + name)
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError("Existing input differs; preserve it before restoring: " + name)
        # Validate all members before writing any, and preserve matching inputs.
        for name in manifest:
            target = Path(name)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    print(str(path) + " restored and verified", flush=True)


def restore_bundle(path):
    restore_archive(path, BUNDLE_SHA256)


def probe(year):
    day = {2024: '20240105', 2025: '20250106'}[year]
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={day}&selectType=ALLBUT0999"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            from twse_history.institutional import normalize_t86
            if response.status != 200 or response.url != url:
                raise ValueError('T86 source redirected/errored')
            normalize_t86(json.loads(response.read()), day)
    except Exception as error:
        raise RuntimeError("TWSE probe failed; no yearly queue started. Check network access.") from error


def run(*args):
    print("Running: " + " ".join(args), flush=True)
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Verified 2023 reproduction archive")
    parser.add_argument("--checkpoint-2024", type=Path, help="Verified uploaded 2024 source checkpoint")
    parser.add_argument("--year", type=int, choices=[2024, 2025], default=2024)
    parser.add_argument("--fetch", action="store_true", help="Fetch missing official annual inputs")
    parser.add_argument("--probe-only", action="store_true", help="One sample request, no yearly queue or model")
    parser.add_argument("--check-only", action="store_true", help="Validate inputs without downloading or fitting")
    args = parser.parse_args()
    if args.check_only and args.fetch:
        parser.error("--check-only cannot be combined with --fetch")
    if args.probe_only:
        if args.fetch or args.check_only or args.bundle or args.checkpoint_2024:
            parser.error("--probe-only is a standalone connectivity check")
        probe(args.year)
        print("TWSE sample verified; no yearly queue started", flush=True)
        return
    if args.bundle:
        restore_bundle(args.bundle)
    if args.checkpoint_2024:
        restore_archive(args.checkpoint_2024, CHECKPOINT_2024_SHA256)
    year = args.year
    flow_path = Path(f"inputs/institutional_twse_{year}.csv.gz")
    config_path = f"configs/institutional_diagnostic_{year}.json"
    config = json.loads(Path(config_path).read_text())
    prices = Path(config["prices"])
    if not prices.exists() or hashlib.sha256(prices.read_bytes()).hexdigest() != config["expected_prices_sha256"]:
        raise ValueError("Restore the verified price input first")
    universe = PRICE_ROOT / "universe_daily_2023_2026.csv.gz"
    if not universe.exists() or not Path("inputs/institutional_twse_2023.csv.gz").exists():
        raise ValueError("Restore the complete 2023 reproduction archive first")
    prior_flows = [Path(f"inputs/institutional_twse_{y}.csv.gz") for y in range(config.get('start_year', 2023), year)]
    if any(not p.exists() for p in prior_flows):
        raise ValueError("Restore the preceding annual institutional inputs first")
    missing_calendars = [month for month in range(1, 13)
                         if not (CALENDAR_ROOT / f"calendar_{year}{month:02d}.json").exists()]
    if args.check_only:
        print(json.dumps({"price_checksum_verified": True,
                          "year": year, "missing_calendar_months": missing_calendars,
                          "flow_exists": flow_path.exists(),
                          "next_command": f"python3 resume_institutional.py --year {year} --fetch"}, indent=2))
        return
    if args.fetch:
        # One short probe before starting a year-long request queue.
        probe(year)
        for month in range(1, 13):
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={year}{month:02d}01&response=json"
            download(url, CALENDAR_ROOT / f"calendar_{year}{month:02d}.json")
        import pandas as pd
        expected_days = []
        for chunk in pd.read_csv(prices, usecols=['date', 'symbol'], dtype={'symbol': str}, chunksize=200000):
            expected_days.extend(chunk.loc[chunk.date.str.startswith(str(year)), 'date'].str.replace('-', '').tolist())
        if market_days_from_cache(CALENDAR_ROOT, year) != sorted(set(expected_days)):
            raise ValueError("Official year calendar differs from frozen market quote calendar")
        run(sys.executable, "-m", "twse_history.institutional", "--year", str(year),
            "--cache", f"inputs/institutional_{year}", "--universe", str(universe),
            "--output", str(flow_path), "--select-type", "ALLBUT0999", "--fetch")
        run(sys.executable, "audit_institutional_acquisition.py", "--year", str(year))
        # Save raw and normalized data before feature/model computation.
        run(sys.executable, "package_institutional_archive.py", "--year", str(year),
            "--cache", f"inputs/institutional_{year}", "--include", str(flow_path),
            "--output", f"deliverables/institutional_twse_{year}_source_checkpoint.zip")
    if (missing_calendars and not args.fetch) or not flow_path.exists():
        raise ValueError(f"{year} inputs missing. Use --fetch on a host with TWSE access or restore the saved inputs.")
    run(sys.executable, "-m", "twse_history.institutional_features", "--years",
        *[str(y) for y in range(config.get('start_year', 2023), year + 1)],
        "--prices", str(prices), "--flows", *[str(p) for p in prior_flows],
        str(flow_path), "--output", config["features"])
    run(sys.executable, "audit_institutional_increment.py", "--config",
        config_path)


if __name__ == "__main__":
    main()


