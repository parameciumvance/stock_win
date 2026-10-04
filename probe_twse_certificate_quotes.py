"""Inspect official MI_INDEX daily JSON for parent and potential certificate rows.

Examples:
  python3 probe_twse_certificate_quotes.py --dates 20250812 20251002
  python3 probe_twse_certificate_quotes.py --dates 20240812 --raw-dir data/raw/twse_2024

The script inspects response tables without treating an absent code as a zero price.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def scan(payload, *, date, category):
    if payload.get('stat') != 'OK':
        raise ValueError(f'{date} {category}: API stat is not OK')
    rows = []
    for table in payload.get('tables', []):
        fields = table.get('fields') or []
        if '證券代號' not in fields:
            continue
        ix = fields.index('證券代號')
        name_ix = fields.index('證券名稱') if '證券名稱' in fields else None
        close_ix = fields.index('收盤價') if '收盤價' in fields else None
        for values in table.get('data', []):
            code = str(values[ix]).strip()
            name = str(values[name_ix]) if name_ix is not None else ''
            if code.startswith(('2855', '2493')) or '權利證書' in name:
                rows.append(dict(symbol=code, name=values[name_ix] if name_ix is not None else None,
                                 close=values[close_ix] if close_ix is not None else None,
                                 table=table.get('title')))
    return dict(date=date, category=category, matching_rows=rows,
                matching_count=len(rows), tables=len(payload.get('tables', [])))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dates', nargs='+', required=True, help='YYYYMMDD market dates')
    p.add_argument('--raw-dir', type=Path, help='Read cached mi_index_YYYYMMDD.json (ALLBUT0999 only)')
    p.add_argument('--timeout', type=int, default=15, help='Network timeout per request in seconds')
    p.add_argument('--output', type=Path, default=Path('certificate_quote_probe.json'))
    args = p.parse_args()
    results = []
    for day in args.dates:
        if not re.fullmatch(r'20[0-9]{6}', day):
            p.error(f'Invalid YYYYMMDD: {day}')
        categories = ('ALLBUT0999',) if args.raw_dir else ('ALLBUT0999', 'ALL')
        for category in categories:
            source = (args.raw_dir / f'mi_index_{day}.json') if args.raw_dir else (
                'https://www.twse.com.tw/exchangeReport/MI_INDEX?' + urlencode(
                    {'response': 'json', 'date': day, 'type': category}))
            try:
                if args.raw_dir:
                    payload = json.loads(source.read_text())
                else:
                    request = Request(source, headers={'User-Agent': 'Mozilla/5.0 research audit'})
                    with urlopen(request, timeout=args.timeout) as response:
                        payload = json.load(response)
                item = scan(payload, date=day, category=category)
                item['source'] = str(source)
            except Exception as error:
                item = dict(date=day, category=category, source=str(source),
                            error=f'{type(error).__name__}: {error}')
            results.append(item)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    for item in results:
        if 'error' in item:
            print(item['date'], item['category'], 'ERROR', item['error'], 'source', item['source'])
        else:
            print(item['date'], item['category'], 'potential matches', item['matching_count'],
                  item['matching_rows'], 'source', item['source'])
    print('saved', args.output)


if __name__ == '__main__':
    main()
