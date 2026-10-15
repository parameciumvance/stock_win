"""Versioned rolling source acquisition; historical research inputs are never touched."""
import argparse
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
from zoneinfo import ZoneInfo

from research_runtime import atomic_bytes, atomic_json, exclusive_lock, sha256, utcnow

TPEX_EVENTS = [('excal', 'exDailyQ'), ('reduction', 'revivt'), ('change', 'pvChgRslt')]
BENCHMARK_EVENTS = [('exrights', 'exRight/TWT49U'), ('reduction', 'reducation/TWTAUU'),
                    ('par_change', 'change/TWTB8U'), ('split', 'split/TWTCAU')]


def warmup_months(date):
    end = dt.date.fromisoformat(date)
    serial = end.year * 12 + end.month - 1
    return [f'{n//12}-{n%12+1:02}' for n in range(serial - 4, serial + 1)]


def annual_sources(first_date, signal_date):
    """Require every event year crossed by the warmup, keeping legacy current-year keys."""
    first = dt.date.fromisoformat(first_date)
    end = dt.date.fromisoformat(signal_date)
    if first > end:
        raise ValueError('Warmup begins after signal date')
    sources = []
    for year in range(first.year, end.year + 1):
        cutoff = min(end, dt.date(year, 12, 31))
        suffix = '' if year == end.year else f'{year}_'
        for kind, route in TPEX_EVENTS:
            key = f'event_{suffix}{kind}.json'
            url = f'https://www.tpex.org.tw/www/zh-tw/bulletin/{route}?startDate={year}/01/01&endDate={cutoff:%Y/%m/%d}&response=json'
            sources.append(dict(key=key, url=url, market='tpex', kind=kind, year=year,
                                cutoff=cutoff.isoformat()))
        for kind, route in BENCHMARK_EVENTS:
            key = f'benchmark_event_{suffix}{kind}.json'
            url = f'https://www.twse.com.tw/rwd/zh/{route}?startDate={year}0101&endDate={cutoff:%Y%m%d}&response=json'
            sources.append(dict(key=key, url=url, market='twse', kind=kind, year=year,
                                cutoff=cutoff.isoformat()))
    return sources


def fetch(root, key, url):
    path = root / 'raw' / key
    meta_path = path.with_name(path.name + '.meta.json')
    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta['url'] != url or meta['sha256'] != sha256(path):
            raise ValueError('Source cache drift: ' + key)
        return meta
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.pending')
    started = utcnow()
    result = subprocess.run(['curl', '--max-time', '60', '--fail', '--silent', '--show-error', url, '-o', str(pending)], capture_output=True, text=True, timeout=65)
    if result.returncode:
        atomic_json(root / 'errors' / (key + '.' + started.replace(':', '') + '.json'), dict(url=url, observed_at=utcnow(), exit_code=result.returncode, stderr=result.stderr))
        raise RuntimeError(result.stderr.strip())
    body = pending.read_bytes()
    if key.endswith('.json'):
        json.loads(body)
    atomic_bytes(path, body)
    meta = dict(url=url, request_started_at=started, observed_at=utcnow(), sha256=sha256(path), size_bytes=len(body))
    atomic_json(meta_path, meta)
    pending.unlink()
    return meta


def calendar_days(raw, month, cutoff):
    doc = json.loads(raw)
    year, mm = map(int, month.split('-'))
    if doc.get('stat') != 'ok' or len(doc.get('tables', [])) != 1:
        raise ValueError('Official calendar unavailable')
    table = doc['tables'][0]
    if table.get('date') != f'{year-1911}/{mm:02}' or table['fields'][0] != '日期':
        raise ValueError('Calendar schema/month differs')
    days = [dt.date.fromisoformat(r[0].replace('/', '-')).isoformat() for r in table['data']]
    if days != sorted(set(days)) or any(not d.startswith(month) for d in days):
        raise ValueError('Calendar duplicate/wrong month')
    return [d for d in days if d <= cutoff]


def acquire(root, date):
    # Four full months plus current month cover >60 sessions and both revenue lags.
    end = dt.date.fromisoformat(date)
    months = warmup_months(date)
    if any((root / 'journal' / 'signal').glob('*.json')):
        raise ValueError('Sealed run cannot reacquire or replace sources; use a new version directory')
    source_cutoff(date)
    with exclusive_lock(root / 'acquisition.lock'):
        def batch(requests):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                for meta in executor.map(lambda item: fetch(root, *item), requests):
                    print(meta['url'], meta['size_bytes'], flush=True)
        batch([(f'calendar_{m}.json', f'https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date={m.replace("-", "/")}/01&response=json') for m in months])
        days = [d for m in months for d in calendar_days((root/'raw'/f'calendar_{m}.json').read_bytes(), m, date)]
        if date not in days or len(days) < 61:
            raise ValueError('Signal not an observed market session or insufficient calendar')
        requests = [(f'quote_{d}.json', f'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={d.replace("-", "/")}&type=EW&response=json') for d in days]
        requests += [(f'flow_{d}.json', f'https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?date={d.replace("-", "/")}&type=Daily&response=json') for d in days[-6:-1]]
        requests += [(f'benchmark_{m}.json', f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={m.replace("-", "")}01&stockNo=0050') for m in months]
        for m in months[:-1]:
            yy, mm = map(int,m.split('-'))
            for kind in (0,1):
                requests.append((f'revenue_{m}_{kind}.html', f'https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_{yy-1911}_{mm}_{kind}.html'))
        requests += [(s['key'], s['url']) for s in annual_sources(days[0], date)]
        # A December signal may enter in January; require both official schedules.
        holiday_years = [end.year, end.year + 1] if end.month == 12 else [end.year]
        requests += [(f'holiday_{year}.json', f'https://www.tpex.org.tw/www/zh-tw/bulletin/tradingDate?date={year}&response=json') for year in holiday_years]
        requests += [('isin_otc.html','https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'),('isin_listed.html','https://isin.twse.com.tw/isin/C_public.jsp?strMode=2')]
        batch(requests)
        atomic_json(root/'acquisition.json',dict(signal_date=date, calendar_days=days, requests=[key for key,_ in requests], source_status='acquired_not_replayed', observed_at=utcnow()))


def source_cutoff(date, *, now=None):
    now = now or dt.datetime.now(ZoneInfo('Asia/Taipei'))
    if now.tzinfo is None:
        raise ValueError('Timezone-aware source clock required')
    local = now.astimezone(ZoneInfo('Asia/Taipei'))
    if date != local.date().isoformat() or local.hour < 15:
        raise ValueError('Acquire only the current signal day after 15:00 Taipei')


def verify_archive(path, expected):
    if sha256(path) != expected:
        raise ValueError('Archive SHA mismatch')
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or z.testzip() is not None:
            raise ValueError('Archive duplicate/CRC failure')
        manifest = json.loads(z.read('manifest.json'))
        if set(names) != set(manifest) | {'manifest.json'}:
            raise ValueError('Archive member set differs')
        import hashlib
        for name, digest in manifest.items():
            if Path(name).is_absolute() or '..' in Path(name).parts or hashlib.sha256(z.read(name)).hexdigest() != digest:
                raise ValueError('Archive member hash/path differs')
    return manifest


def archive(root):
    if any((root / 'journal' / 'signal').glob('*.json')):
        raise ValueError('Sealed run cannot replace archive')
    paths = sorted(p for p in (root/'raw').iterdir() if p.is_file() and not p.name.endswith('.pending'))
    paths += [root/'acquisition.json']
    manifest = {str(p.relative_to(root)):sha256(p) for p in paths}
    path = root/'sources.zip'
    with zipfile.ZipFile(path.with_suffix('.pending'), 'w', zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, str(p.relative_to(root)))
        z.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
    path.with_suffix('.pending').replace(path)
    digest = sha256(path)
    backup = root.parent/'backups'/root.name/'sources.zip'
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, backup)
    retrieved = root/'sources.retrieved.zip'
    shutil.copyfile(backup, retrieved)
    verify_archive(retrieved,digest)
    atomic_json(root/'checkpoint.json',dict(storage_kind='local_persistent_copy', archive=str(path.resolve()), backup_path=str(backup.resolve()), retrieved_path=str(retrieved.resolve()), sha256=digest, roundtrip_verified=True, manifest_files=len(manifest), verified_at=utcnow(), limitation='Local backup on same filesystem; not off-host disaster recovery'))


def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['acquire','archive']);p.add_argument('--root',type=Path,required=True);p.add_argument('--date',required=True);a=p.parse_args()
    if a.stage=='acquire':
        acquire(a.root,a.date)
    else:
        with exclusive_lock(a.root/'acquisition.lock'):
            archive(a.root)

if __name__=='__main__':main()
