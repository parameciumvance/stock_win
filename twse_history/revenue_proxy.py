"""Free static MOPS revenue snapshots and delayed exploratory features.

These snapshots may contain later revisions. proxy_available_date is an assumed
date, never published_at. The strict asof_revenue ledger is not modified.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

from lxml import html
import numpy as np
import pandas as pd

REVENUE_FEATURES = ['rev_yoy', 'rev_mom', 'rev_3m_yoy', 'rev_yoy_accel', 'log_revenue']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_gzip(frame, path):
    # Publish only closed gzip streams, so an interrupted writer leaves the
    # previous verified checkpoint usable by an independent reader.
    path = Path(path)
    temporary = path.with_name(path.stem + '.pending.gz')
    frame.to_csv(temporary, index=False, compression={'method':'gzip', 'mtime':0})
    temporary.replace(path)


def parse_snapshot(raw, month, kind):
    year, mm = map(int, month.split('-'))
    # Official Big5 pages contain CP950 extension characters; no lossy decoding.
    text = raw.decode('cp950')
    title = f'上市公司{year - 1911}年{mm}月份(累計與當月)營業收入統計表'
    if title not in text or '單位：千元' not in text:
        raise ValueError(f'Wrong source month/unit: {month}/{kind}')
    if ('全部國內上市公司合計' if kind == 0 else '全部國外上市公司合計') not in text:
        raise ValueError('Wrong domestic/foreign page')
    export = re.search(r'出表日期[：:]\s*(\d+/\d+/\d+)', text)
    if not export:
        raise ValueError('Missing export date')
    rows = []
    for tr in html.fromstring(text).xpath('//tr'):
        cells = [' '.join(c.text_content().split()) for c in tr.xpath('./td|./th')]
        if not cells or not re.fullmatch(r'\d{4}', cells[0]):
            continue
        if len(cells) != 11:
            raise ValueError('Unexpected issuer revenue schema')
        def number(value):
            if value in {'-', '--', ''}:
                return np.nan
            return float(value.replace(',', ''))
        rows.append(dict(symbol=cells[0], name=cells[1], revenue_month=month,
                         revenue_twd_thousands=number(cells[2]),
                         previous_month_twd_thousands=number(cells[3]),
                         previous_year_twd_thousands=number(cells[4]),
                         reported_mom_pct=number(cells[5]), reported_yoy_pct=number(cells[6]),
                         source_kind=kind, source_export_date_roc=export[1]))
    result = pd.DataFrame(rows)
    if result.empty or result.symbol.duplicated().any():
        raise ValueError('Empty/duplicate issuer snapshot')
    if not np.isfinite(result.revenue_twd_thousands).all():
        raise ValueError('Nonfinite current revenue')
    return result


def cached_snapshot(root, month, kind, fetch=False):
    year, mm = map(int, month.split('-'))
    url = f'https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_{year-1911}_{mm}_{kind}.html'
    stem = f'revenue_{year}{mm:02d}_{kind}'
    path, meta_path = root / (stem + '.html'), root / (stem + '.meta.json')
    if path.exists() != meta_path.exists():
        raise ValueError(f'Incomplete cache pair: {stem}')
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(stem)
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'stock-win-research/1.0'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    raw = response.read()
                    meta = dict(source_url=url, final_url=response.url, http_status=response.status,
                                fetched_at=datetime.now(timezone.utc).isoformat(), bytes=len(raw),
                                sha256=hashlib.sha256(raw).hexdigest())
                if meta['final_url'] != url or meta['http_status'] != 200:
                    raise ValueError('Redirected/error revenue source')
                parse_snapshot(raw, month, kind)
                root.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                meta_path.write_text(json.dumps(meta, indent=2) + '\n')
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
        time.sleep(.5)
    meta = json.loads(meta_path.read_text())
    if meta['sha256'] != sha(path) or meta['source_url'] != url or meta['final_url'] != url or meta['http_status'] != 200:
        raise ValueError(f'Unverified source: {stem}')
    frame = parse_snapshot(path.read_bytes(), month, kind)
    frame['snapshot_sha256'] = meta['sha256']
    return frame, meta


def build_monthly_features(monthly):
    if monthly.duplicated(['symbol', 'revenue_month']).any():
        raise ValueError('Duplicate symbol/month across domestic/foreign pages')
    output = []
    for symbol, group in monthly.groupby('symbol', sort=True):
        g = group.copy()
        g.index = pd.PeriodIndex(g.revenue_month, freq='M')
        g = g.reindex(pd.period_range(g.index.min(), g.index.max(), freq='M'))
        current = g.revenue_twd_thousands
        previous = g.previous_year_twd_thousands
        positive = current.gt(0)
        f = pd.DataFrame(index=g.index)
        f['rev_yoy'] = (current / previous.where(previous.gt(0)) - 1).clip(-1, 5)
        f['rev_mom'] = (current / g.previous_month_twd_thousands.where(g.previous_month_twd_thousands.gt(0)) - 1).clip(-1, 5)
        c3, p3 = current.rolling(3, min_periods=3).sum(), previous.rolling(3, min_periods=3).sum()
        f['rev_3m_yoy'] = (c3 / p3.where(p3.gt(0)) - 1).clip(-1, 5)
        f['rev_yoy_accel'] = (f.rev_yoy - f.rev_yoy.shift(3)).clip(-1, 5)
        f['log_revenue'] = np.log(current.where(positive))
        f.loc[~positive, REVENUE_FEATURES] = np.nan
        f['symbol'] = symbol
        f['revenue_month'] = f.index.astype(str)
        f['month_end'] = f.index.to_timestamp(how='end').normalize()
        f['snapshot_sha256'] = g.snapshot_sha256
        output.append(f[g.revenue_month.notna()].reset_index(drop=True))
    return pd.concat(output, ignore_index=True)


def value_consistency(monthly):
    m = monthly.copy()
    m['period'] = pd.PeriodIndex(m.revenue_month, freq='M')
    result = dict(monthly_rows=len(m), note='Current snapshot arithmetic only; no original-vintage or first-publication proof.')
    for period, field, label in [(1, 'previous_month_twd_thousands', 'month'),
                                  (12, 'previous_year_twd_thousands', 'year')]:
        previous = m[['symbol', 'period', 'revenue_twd_thousands']].copy()
        previous['period'] += period
        pair = m.merge(previous, on=['symbol', 'period'], how='left', suffixes=('', '_prior_snapshot'), validate='one_to_one')
        observed = pair.revenue_twd_thousands_prior_snapshot.notna()
        result['compared_prior_' + label + '_pairs'] = int(observed.sum())
        result['different_previous_' + label + '_values'] = int((observed & pair[field].ne(pair.revenue_twd_thousands_prior_snapshot)).sum())
    yoy = (m.revenue_twd_thousands / m.previous_year_twd_thousands.where(m.previous_year_twd_thousands.gt(0)) - 1)*100
    result['reported_yoy_disagreements_gt_0051'] = int((yoy - m.reported_yoy_pct).abs().gt(.051).sum())
    return result


def attach_features(candidates, monthly_features, days, lag, max_age=100):
    days = pd.DatetimeIndex(days).sort_values().unique()
    f = monthly_features.copy()
    bound = f.month_end + pd.Timedelta(days=lag)
    idx = days.searchsorted(bound, side='right')
    f = f[idx < len(days)].copy()
    f['proxy_available_date'] = days.take(idx[idx < len(days)])
    # Months available before the calendar starts all map to its first date.
    # Keep the latest month explicitly; merge_asof must not choose a tie at random.
    f = f.sort_values(['symbol', 'proxy_available_date', 'month_end']).drop_duplicates(
        ['symbol', 'proxy_available_date'], keep='last')
    # Never roll back to an older complete month when the latest is incomplete.
    out = pd.merge_asof(candidates.sort_values(['date', 'symbol']),
                        f.sort_values(['proxy_available_date', 'symbol']),
                        left_on='date', right_on='proxy_available_date', by='symbol', direction='backward')
    stale = (out.date - out.month_end).dt.days.gt(max_age)
    out.loc[stale, REVENUE_FEATURES] = np.nan
    observed = out.proxy_available_date.notna()
    if not out.loc[observed, 'proxy_available_date'].le(out.loc[observed, 'date']).all():
        raise ValueError('Future proxy date leaked into feature join')
    return out


def acquire(config, fetch=False):
    root = Path('inputs/revenue_proxy/raw')
    requests = [(str(m), k) for m in pd.period_range(config['source_start'], config['source_end'], freq='M') for k in (0, 1)]
    frames, sources = [], []
    with ThreadPoolExecutor(max_workers=2) as pool:
        def run(item):
            m, k = item
            f, meta = cached_snapshot(root, m, k, fetch)
            return f, dict(meta, revenue_month=m, source_kind=k, rows=len(f))
        for i, (frame, meta) in enumerate(pool.map(run, requests), 1):
            frames.append(frame); sources.append(meta)
            if i % 10 == 0:
                print(f'verified_sources={i}/{len(requests)}', flush=True)
    monthly = pd.concat(frames, ignore_index=True).sort_values(['revenue_month', 'symbol'])
    features = build_monthly_features(monthly)
    output = Path('inputs/revenue_proxy'); output.mkdir(exist_ok=True, parents=True)
    write_gzip(monthly, output / 'monthly.csv.gz')
    write_gzip(features, output / 'monthly_features.csv.gz')
    audit = dict(status='retrospective_static_snapshots_not_original_vintages', source_count=len(sources),
                 months=len(requests)//2, monthly_rows=len(monthly), symbols=monthly.symbol.nunique(),
                 missing_feature_rows=int((~np.isfinite(features[REVENUE_FEATURES]).all(axis=1)).sum()),
                 nonpositive_current_rows=int(monthly.revenue_twd_thousands.le(0).sum()), sources=sources,
                 normalized_sha256=sha(output / 'monthly.csv.gz'), features_sha256=sha(output / 'monthly_features.csv.gz'))
    Path('deliverables/revenue_proxy').mkdir(exist_ok=True, parents=True)
    Path('deliverables/revenue_proxy/acquisition.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n')
    Path('deliverables/revenue_proxy/value_consistency.json').write_text(json.dumps(value_consistency(monthly), indent=2)+'\n')
    print(json.dumps({k:v for k,v in audit.items() if k != 'sources'}, indent=2), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/revenue_proxy_protocol.json')
    p.add_argument('--fetch', action='store_true')
    args = p.parse_args()
    acquire(json.loads(Path(args.config).read_text()), args.fetch)
