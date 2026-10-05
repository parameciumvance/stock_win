"""Package a complete institutional year and its reproduction inputs.

Every expected market date must have raw bytes and matching metadata. Included
data may be generated inputs; repository code/config/report files are excluded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from twse_history.institutional import market_days_from_cache, normalize_t86


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--calendar-root', default='twse_history/raw')
    parser.add_argument('--include', nargs='*', default=[])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.cache);calendar_root = Path(args.calendar_root)
    days = market_days_from_cache(calendar_root, args.year)
    files = []
    raw_rows = 0
    for day in days:
        path = root / ('t86_' + day + '.json');meta_path = root / ('t86_' + day + '.meta.json')
        raw = path.read_bytes();meta = json.loads(meta_path.read_text())
        if hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise ValueError('Raw checksum mismatch')
        prefix = 'https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=' + day + '&selectType='
        if meta['source_url'] not in {prefix + 'ALL', prefix + 'ALLBUT0999'}:
            raise ValueError('Unexpected source identity')
        raw_rows += len(normalize_t86(json.loads(raw), day))
        files.extend([path, meta_path])
    for month in range(1, 13):
        path = calendar_root / f'calendar_{args.year}{month:02d}.json'
        meta_path = path.with_suffix('.meta.json')
        if hashlib.sha256(path.read_bytes()).hexdigest() != json.loads(meta_path.read_text())['sha256']:
            raise ValueError('Calendar checksum mismatch')
        files.extend([path, meta_path])
    files.extend(Path(p) for p in args.include)
    if len(files) != len(set(files)):
        raise ValueError('Duplicate archive path')
    if any(p.is_absolute() or '..' in p.parts or not p.is_file() for p in files):
        raise ValueError('Included files must be relative regular workspace inputs')
    manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    out = Path(args.output);out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p, str(p))
        z.writestr('SHA256MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
        z.writestr('SOURCE_SUMMARY.json', json.dumps({'year': args.year, 'market_days': len(days),
                       'raw_rows': raw_rows, 'complete_year': True, 'dates': days}, indent=2) + '\n')
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC verification failed')
        for p, expected in manifest.items():
            if hashlib.sha256(z.read(p)).hexdigest() != expected:raise ValueError('Archived bytes mismatch')
    print(json.dumps({'file': str(out), 'bytes': out.stat().st_size, 'sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
                      'market_days': len(days), 'raw_rows': raw_rows, 'members': len(files) + 2}))


if __name__ == '__main__':main()
