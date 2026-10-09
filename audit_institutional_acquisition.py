"""Verify a cached institutional year against normalized rows and historical membership."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from twse_history.institutional import market_days_from_cache, normalize_t86


UNIVERSE = 'twse_history/output_multiyear_2023_2026_asof_20261002/universe_daily_2023_2026.csv.gz'
UNIVERSE_SHA256 = 'bc5bfa1c662944a43c76724a372bb7b119ff00d9bc199d7361e9bd91f9727942'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', required=True, type=int)
    parser.add_argument('--calendar-root', default='twse_history/raw')
    parser.add_argument('--cache')
    parser.add_argument('--flows')
    parser.add_argument('--universe', default=UNIVERSE)
    parser.add_argument('--expected-universe-sha256', default=UNIVERSE_SHA256)
    parser.add_argument('--select-type', default='ALLBUT0999', choices=['ALL', 'ALLBUT0999'])
    parser.add_argument('--output')
    args = parser.parse_args()
    year = args.year; root = Path(args.cache or f'inputs/institutional_{year}')
    flow_path = Path(args.flows or f'inputs/institutional_twse_{year}.csv.gz')
    if hashlib.sha256(Path(args.universe).read_bytes()).hexdigest() != args.expected_universe_sha256:
        raise ValueError('Frozen historical universe checksum mismatch')
    days = market_days_from_cache(Path(args.calendar_root), year)
    for month in range(1, 13):
        calendar = Path(args.calendar_root) / f'calendar_{year}{month:02d}.json'
        meta = json.loads(calendar.with_suffix('.meta.json').read_text())
        expected_url = f'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={year}{month:02d}01&response=json'
        if meta.get('url') != expected_url or hashlib.sha256(calendar.read_bytes()).hexdigest() != meta['sha256']:
            raise ValueError('Calendar source identity/checksum mismatch')
    members = []
    for chunk in pd.read_csv(args.universe, usecols=['date', 'symbol', 'is_member'], dtype={'symbol': str}, chunksize=200000):
        if not chunk.is_member.isin([True, False]).all():
            raise ValueError('Universe membership must be boolean')
        members.append(chunk[chunk.date.str.startswith(str(year)) & chunk.is_member][['date', 'symbol']])
    members = pd.concat(members, ignore_index=True)
    iso_days = [d[:4] + '-' + d[4:6] + '-' + d[6:] for d in days]
    if members.duplicated(['date', 'symbol']).any() or set(members.date) != set(iso_days):
        raise ValueError('Historical universe calendar/keys invalid')
    rows = []; times = []; raw_hashes = {}
    for day in days:
        path = root / f't86_{day}.json'; meta = json.loads(path.with_suffix('.meta.json').read_text())
        raw = path.read_bytes()
        expected_url = f'https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={day}&selectType={args.select_type}'
        sha = hashlib.sha256(raw).hexdigest()
        if meta.get('source_url') != expected_url or meta.get('final_url', expected_url) != expected_url or meta.get('http_status', 200) != 200 or sha != meta['sha256']:
            raise ValueError(f'Raw source identity/status/checksum mismatch: {day}')
        rows.extend(normalize_t86(json.loads(raw), day))
        times.append(meta['fetched_at']); raw_hashes[day] = sha
    raw_frame = pd.DataFrame(rows)
    selected = raw_frame.merge(members, on=['date', 'symbol'], validate='one_to_one').sort_values(['date', 'symbol']).reset_index(drop=True)
    normalized = pd.read_csv(flow_path, dtype={'symbol': str}).sort_values(['date', 'symbol']).reset_index(drop=True)
    pd.testing.assert_frame_equal(selected, normalized, check_exact=True, check_dtype=False)
    counts = members.groupby('date').size()
    observed = selected.groupby('date').size().reindex(counts.index, fill_value=0)
    coverage = observed / counts
    result = {'year': year, 'market_days': len(days), 'raw_selected_security_rows': len(raw_frame),
        'common_flow_rows': len(selected), 'common_symbols_observed': selected.symbol.nunique(),
        'historical_member_rows': len(members), 'missing_member_rows': len(members) - len(selected),
        'mean_daily_coverage': float(coverage.mean()), 'min_daily_coverage': float(coverage.min()),
        'max_daily_coverage': float(coverage.max()), 'duplicate_keys': int(normalized.duplicated(['date', 'symbol']).sum()),
        'normalized_rows_equal_reparsed_raw': True, 'normalized_sha256': hashlib.sha256(flow_path.read_bytes()).hexdigest(),
        'universe_sha256': args.expected_universe_sha256, 'raw_hashes': raw_hashes,
        'source_fetch_utc_range': [min(times), max(times)],
        'limitations': ['Missing source rows are not zero flows.', 'Historical snapshots fetched now do not establish original publication time or revision history.']}
    out = Path(args.output or f'deliverables/institutional_acquisition_{year}.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'raw_hashes'}, indent=2))


if __name__ == '__main__':
    main()
