"""Bounded TPEx historical quote pilot. No training or stock classification inference."""
import argparse, datetime, hashlib, json, math, pathlib, urllib.request


def fetch(url, path):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'stock-win-research/1.0'}), timeout=20) as response:
        body = response.read()
        status = response.status
    path.write_bytes(body)
    meta = {'url': url, 'status': status, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(), 'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    path.with_suffix(path.suffix + '.meta.json').write_text(json.dumps(meta, indent=2))
    return json.loads(body)


def validate_quotes(document, requested):
    tables = document.get('tables', [])
    if not tables or not tables[0].get('data'):
        raise ValueError('No quote rows; failure must not be classified as a holiday')
    table = tables[0]
    target = datetime.date.fromisoformat(requested)
    expected = f'{target.year-1911}/{target.month:02}/{target.day:02}'
    if table.get('date') != expected:
        raise ValueError('Returned date differs from requested date')
    fields = [str(x).replace('<br>', '').strip() for x in table['fields']]
    required = ['代號', '收盤', '開盤', '最高', '最低', '成交股數', '成交金額(元)']
    if not all(x in fields for x in required):
        raise ValueError('Unrecognized schema')
    rows = table['data']
    codes = [r[fields.index('代號')] for r in rows]
    if len(codes) != len(set(codes)):
        raise ValueError('Duplicate securities')
    priced = 0
    for row in rows:
        if len(row) != len(fields):
            raise ValueError('Row width mismatch')
        for k in ['成交股數', '成交金額(元)']:
            value=str(row[fields.index(k)]).replace(',', '').strip()
            if value in ['', '-', '--', '---', 'N/A']:continue
            value=float(value)
            if not math.isfinite(value) or value<0:raise ValueError('Invalid volume or transaction amount')
        values = [str(row[fields.index(k)]).replace(',', '') for k in ['收盤', '開盤', '最高', '最低']]
        try:
            c, o, h, l = map(float, values)
        except ValueError:
            # Missing prices remain unknown, never replaced with zero.
            continue
        if not all(math.isfinite(x) for x in [c,o,h,l]) or not 0 < l <= min(c, o) <= max(c, o) <= h:
            raise ValueError('OHLC inconsistency')
        priced += 1
    return {'requested_date': requested, 'returned_date': expected, 'rows': len(rows), 'priced_rows': priced, 'duplicate_codes': 0, 'ohlc_errors': 0, 'ordinary_classification': 'pending; never use present-day membership to remove historical securities', 'volume_unit': 'shares', 'amount_unit': 'TWD'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='deliverables/tpex_pilot')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for date in ['2023-01-03', '2024-01-02', '2025-01-02']:
        path = output / ('quotes_' + date.replace('-', '') + '.json')
        if args.offline:
            document = json.loads(path.read_bytes())
        else:
            document = fetch('https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=' + date.replace('-', '/') + '&type=EW&response=json', path)
        results.append(validate_quotes(document, date))
    (output / 'validation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False))

if __name__ == '__main__':
    main()
