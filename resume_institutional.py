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
PRICE_ROOT = Path("twse_history/output_multiyear_2023_2026_asof_20261002")
CALENDAR_ROOT = Path("twse_history/raw")
FLOW_2024 = Path("inputs/institutional_twse_2024.csv.gz")


def restore_bundle(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != BUNDLE_SHA256:
        raise ValueError("2023 reproduction archive checksum mismatch")
    with zipfile.ZipFile(path) as archive:
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
    print("2023 archive restored and verified", flush=True)


def run(*args):
    print("Running: " + " ".join(args), flush=True)
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Verified 2023 reproduction archive")
    parser.add_argument("--fetch", action="store_true", help="Fetch missing official 2024 inputs")
    parser.add_argument("--check-only", action="store_true", help="Validate inputs without downloading or fitting")
    args = parser.parse_args()
    if args.check_only and args.fetch:
        parser.error("--check-only cannot be combined with --fetch")
    if args.bundle:
        restore_bundle(args.bundle)
    config = json.loads(Path("configs/institutional_diagnostic_2024.json").read_text())
    prices = Path(config["prices"])
    if not prices.exists() or hashlib.sha256(prices.read_bytes()).hexdigest() != config["expected_prices_sha256"]:
        raise ValueError("Restore the verified price input first")
    universe = PRICE_ROOT / "universe_daily_2023_2026.csv.gz"
    if not universe.exists() or not Path("inputs/institutional_twse_2023.csv.gz").exists():
        raise ValueError("Restore the complete 2023 reproduction archive first")
    missing_calendars = [month for month in range(1, 13)
                         if not (CALENDAR_ROOT / f"calendar_2024{month:02d}.json").exists()]
    if args.check_only:
        print(json.dumps({"price_checksum_verified": True,
                          "missing_2024_calendar_months": missing_calendars,
                          "flow_2024_exists": FLOW_2024.exists(),
                          "next_command": "python3 resume_institutional.py --fetch"}, indent=2))
        return
    if args.fetch:
        # One short probe before starting a year-long request queue.
        url = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=20240105&selectType=ALLBUT0999"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                from twse_history.institutional import normalize_t86
                normalize_t86(json.loads(response.read()), "20240105")
        except Exception as error:
            raise RuntimeError("TWSE probe failed; no yearly queue started. Check network access.") from error
        for month in range(1, 13):
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=2024{month:02d}01&response=json"
            download(url, CALENDAR_ROOT / f"calendar_2024{month:02d}.json")
        if len(market_days_from_cache(CALENDAR_ROOT, 2024)) != 242:
            raise ValueError("Expected the previously verified 242 market days in 2024")
        run(sys.executable, "-m", "twse_history.institutional", "--year", "2024",
            "--cache", "inputs/institutional_2024", "--universe", str(universe),
            "--output", str(FLOW_2024), "--select-type", "ALLBUT0999", "--fetch")
        # Save raw and normalized data before feature/model computation.
        run(sys.executable, "package_institutional_archive.py", "--year", "2024",
            "--cache", "inputs/institutional_2024", "--include", str(FLOW_2024),
            "--output", "deliverables/institutional_twse_2024_source_checkpoint.zip")
    if missing_calendars and not args.fetch or not FLOW_2024.exists():
        raise ValueError("2024 inputs missing. Use --fetch on a host with TWSE access or restore the saved inputs.")
    run(sys.executable, "-m", "twse_history.institutional_features", "--years", "2023", "2024",
        "--prices", str(prices), "--flows", "inputs/institutional_twse_2023.csv.gz",
        str(FLOW_2024), "--output", config["features"])
    run(sys.executable, "audit_institutional_increment.py", "--config",
        "configs/institutional_diagnostic_2024.json")


if __name__ == "__main__":
    main()

