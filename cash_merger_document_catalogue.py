"""Strict declared-Big5 catalogue replay and source-bound download guards."""
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl
import zipfile

from lxml import html

from cash_merger_document_lookup import decode_html, inventory_html, require_successful_query
import merger_documents_sources
from research_runtime import atomic_json, sha256
from tender_preflight import verified_records

ROOT = Path('inputs/cash_merger_documents_20261022')
OUT = Path('deliverables/cash_merger_documents_20261022')
HEADERS = ['證券代號', '資料年度', '資料類型', '結案類型', '股東會性質', '資料細節說明',
           '備註', '電子檔案', '檔案大小', '上傳日期', '永續專章更(補)正']
FORM_FIELDS = [('colorchg', '1'), ('step', ''), ('kind', ''), ('co_id', ''), ('filename', ''),
               ('DEBUG', ''), ('SKEY1', ''), ('SKEY2', ''), ('YEAR', ''), ('MDATE', ''), ('TYPE', '')]
DOWNLOAD_URL = 'https://doc.twse.com.tw/server-java/t57sb01'
_CALL = re.compile(r'''javascript:readfile2\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*\);?''')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_catalogue(body: bytes, headers: bytes):
    full, summary = inventory_html(body, encoding='big5', headers=headers)
    source, _, _ = decode_html(body, 'big5', headers)
    tree = html.document_fromstring(source)
    tables = [table for table in tree.xpath('//table') if table.xpath('./tr|./tbody/tr')
              and [''.join(cell.itertext()).strip() for cell in table.xpath('./tr|./tbody/tr')[0].xpath('./th|./td')] == HEADERS]
    require(len(tables) == 1, 'Missing/ambiguous catalogue header table')
    rows = []
    for number, row in enumerate(tables[0].xpath('./tr|./tbody/tr')[1:], 1):
        cells = row.xpath('./th|./td')
        require(len(cells) == 11, 'Catalogue row must preserve all eleven reported columns')
        original = [''.join(cell.itertext()) for cell in cells]
        links = cells[7].xpath('.//a')
        hrefs = [link.get('href') for link in links]
        parsed = _CALL.fullmatch(hrefs[0]) if len(hrefs) == 1 and isinstance(hrefs[0], str) else None
        rows.append(dict(catalogue_row_number=number, original_cells=original, hrefs=hrefs,
            source_filename=original[7].strip(),
            declared_download=dict(kind=parsed[1], co_id=parsed[2], filename=parsed[3]) if parsed else None,
            declaration_unparsed=parsed is None))
    full['catalogue_headers'], full['catalogue_rows'] = HEADERS, rows
    summary.update(status='all_declared_big5_catalogue_rows_replayed_content_unqualified',
                   catalogue_headers=HEADERS, catalogue_row_count=len(rows), catalogue_rows=rows,
                   returned_other_year_row_numbers=[r['catalogue_row_number'] for r in rows
                                                   if r['original_cells'][1].strip() != '115 年'],
                   query_year_filter_reapplied=False, returned_years_preserved=True)
    return full, summary


def _readfile2(script):
    matches = list(re.finditer(r'function\s+readfile2\s*\(\s*kind\s*,\s*coid\s*,\s*filename\s*\)\s*\{', script))
    require(len(matches) == 1, 'Missing/ambiguous declared readfile2 function')
    begin, depth, quote, escaped = matches[0].end(), 1, None, False
    for index in range(begin, len(script)):
        char = script[index]
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return script[begin:index]
    raise ValueError('Unclosed declared readfile2 function')


def validate_download_requests(catalogue, selection, requests_cfg):
    """Pure exact-row/fm2/readfile2 binding; never execute JavaScript or fetch."""
    require(catalogue['source_encoding'] == 'big5', 'Catalogue must use its declared Big5 encoding')
    source = selection['source_catalogue']
    require(source['encoding'] == 'big5' and source['body_sha256'] == catalogue['body_sha256'],
            'Selected catalogue source bytes/encoding differ')
    forms = [form for form in catalogue['forms'] if form['attributes'].get('name') == 'fm2']
    require(len(forms) == 1, 'Missing/ambiguous fm2 download form')
    form = forms[0]
    actual = [(c['attributes']['name'], c['attributes'].get('value', '')) for c in form['controls']
              if c['tag'] == 'input' and 'name' in c['attributes']]
    require(form['action'] == '/server-java/t57sb01' and form['method'] == 'post' and actual == FORM_FIELDS,
            'fm2 action or complete eleven-field declaration differs')
    script = _readfile2('\n'.join(item['text'] for item in catalogue['scripts']))
    required = [r'var\s+f\s*=\s*document\.forms\[0\]\s*;', r'f\.step\.value\s*=\s*9\s*;',
                r'f\.kind\.value\s*=\s*kind\s*;', r'f\.co_id\.value\s*=\s*coid\s*;',
                r'f\.filename\.value\s*=\s*filename\s*;', r'f\.submit\(\)\s*;']
    require(all(re.search(pattern, script) for pattern in required), 'Declared readfile2 parameter assignments differ')
    rows, requests = selection['rows'], requests_cfg['requests']
    require(len(rows) == len(requests) == 2 and len({r['source_filename'] for r in rows}) == 2
            and len({r['new_filename'] for r in rows}) == 2, 'Expected exactly two distinct selected source documents')
    require({row['document_type'] for row in rows} == {'議事手冊及會議補充資料', '股東會各項議案參考資料'},
            'Selected document types differ from the two frozen meeting materials')
    require(selection['meeting_label'] == '第一次臨時會' and selection['meeting_date'] == '2026-11-09',
            'Selected meeting identity differs')
    indexed = {r['catalogue_row_number']: r for r in catalogue['catalogue_rows']}
    for selected, request in zip(rows, requests, strict=True):
        row = indexed.get(selected['catalogue_row_number'])
        require(row is not None and selected['original_cells'] == row['original_cells'],
                'Selected complete catalogue row differs')
        cells, params = row['original_cells'], row['declared_download']
        require(params == dict(kind='F', co_id='6674', filename=selected['source_filename'])
                and row['source_filename'] == selected['source_filename']
                and cells[0].strip() == '6674' and cells[1].strip() == '115 年'
                and cells[4].strip() == selection['meeting_label']
                and selected['document_type'] == cells[5].strip()
                and selected['display_size_bytes'] == int(cells[8].strip().replace(',', ''))
                and selected['declared_uploaded_at'] == cells[9].strip(),
                'Selected filename/kind/issuer/type/size/upload differs from actual row declaration')
        fields = dict(FORM_FIELDS, step='9', kind='F', co_id='6674', filename=params['filename'])
        expected = [(name, fields[name]) for name, _ in FORM_FIELDS]
        require(selected['request_fields'] == [dict(name=name, value=value) for name, value in expected],
                'Selected request does not preserve all eleven source-form fields')
        require(set(request) == {'filename', 'url', 'method', 'data'}
                and request['filename'] == selected['new_filename'] and request['url'] == DOWNLOAD_URL
                and request['method'] == 'POST'
                and parse_qsl(request['data'], keep_blank_values=True, strict_parsing=True) == expected,
                'Download request differs from the exact row/fm2/readfile2 declaration')


def run():
    module = merger_documents_sources._source_module()
    requests_path, cfg, _, freeze = merger_documents_sources.plan('catalogue')
    package, transfer = module.archived('catalogue', requests_path, freeze)
    with zipfile.ZipFile(package['retrieved']) as archive:
        results = json.loads(archive.read('raw/results.json'))
        require(results['config_sha256'] == sha256(requests_path), 'Archived catalogue configuration differs')
        records = verified_records(cfg, results, lambda name: archive.read('raw/' + name))
        require_successful_query(records)
        name = records[0]['request']['filename']
        full, summary = parse_catalogue(archive.read('raw/' + name), archive.read('raw/' + name + '.headers'))
    summary.update(protocol_sha256=sha256(module.POLICY), request_config_sha256=sha256(requests_path),
                   request=records[0]['request'],
                   archive=dict(sha256=package['sha256'], manifest_files=package['manifest_files'], backup=transfer))
    atomic_json(ROOT / 'catalogue_full.json', full)
    atomic_json(OUT / 'catalogue_replay.json', summary)


if __name__ == '__main__':
    run()
