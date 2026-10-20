"""Independent offline identity/case audit, with no market-outcome inputs.

This verifier uses lxml instead of the production HTMLParser/numbered-schema
parser.  It reads archived announcement bodies, identity-only annual columns,
and the saved replay outputs.  It cannot establish historical completeness or
prove that the earliest retained announcement was the first ever published.
"""
import collections
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
import zipfile

from lxml import html
from pypdf import PdfReader


ROOT = Path('inputs/buyback_coverage_20261020')
OUT = Path('deliverables/buyback_coverage_20261020')
OLD = Path('deliverables/buyback_preflight_20261020')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compact(text):
    return re.sub(r'\s+', '', text)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(path):
    return json.loads(Path(path).read_text())


def archived(directory, batch, verified):
    package = read_json(directory / (batch + '_package.json'))
    path = Path(package['retrieved'])
    require(digest(path.read_bytes()) == package['sha256'], 'Archive hash: ' + str(path))
    with zipfile.ZipFile(path) as z:
        require(z.testzip() is None, 'Archive CRC: ' + str(path))
        manifest = json.loads(z.read('manifest.json'))
        for name, expected in manifest.items():
            require(digest(z.read(name)) == expected, 'Manifest member: ' + name)
        contents = {name: z.read(name) for name in manifest}
    verified.append(dict(path=str(path), sha256=package['sha256'],
                         manifest_files=len(manifest), crc_and_manifest_verified=True))
    return contents


def cell_text(node):
    # Independently walk the HTML tree: explicit <br> boundaries are text lines.
    value = node.text or ''
    for child in node:
        value += '\n' if child.tag == 'br' else cell_text(child)
        value += child.tail or ''
    return value


def tree(body):
    return html.fromstring(body, parser=html.HTMLParser(encoding='utf-8'))


def roc_date(value):
    match = re.fullmatch(r'(\d{3})/(\d{2})/(\d{2})', compact(value))
    require(match is not None, 'Invalid ROC date')
    return dt.date(int(match[1]) + 1911, int(match[2]), int(match[3]))


def independently_parse(body, index):
    page = tree(body)
    providers = re.findall(r'本資料由\s*[（(][^）)]+[）)]\s*(\d{4,6})(?!\d)', page.text_content())
    require(len(providers) == 1, 'Ambiguous issuer in independent HTML tree')
    metadata = {}
    for row in page.xpath('//tr'):
        cells = row.xpath('./th | ./td')
        for i, cell in enumerate(cells[:-1]):
            label = compact(cell_text(cell))
            if label in {'序號', '發言日期', '發言時間', '主旨', '說明'}:
                require(label not in metadata, 'Duplicate metadata label')
                metadata[label] = cell_text(cells[i + 1]).replace('\r\n', '\n').replace('\r', '\n').strip()
    require(set(metadata) == {'序號', '發言日期', '發言時間', '主旨', '說明'}, 'Incomplete metadata')
    issuer, day = providers[0], roc_date(metadata['發言日期'])
    clock = compact(metadata['發言時間'])
    require(re.fullmatch(r'\d{2}:\d{2}:\d{2}', clock) is not None, 'Invalid clock')
    moment = dt.datetime.combine(day, dt.time.fromisoformat(clock)).replace(
        tzinfo=dt.timezone(dt.timedelta(hours=8)))
    sequence_text = compact(metadata['序號'])
    require(re.fullmatch(r'[1-9]\d*', sequence_text) is not None, 'Invalid sequence')
    sequence = int(sequence_text)
    require(issuer == str(index['COMPANY_ID']), 'Index issuer mismatch')
    for label, key in [('發言日期', 'CDATE'), ('發言時間', 'CTIME'), ('主旨', 'SUBJECT')]:
        require(compact(metadata[label]) == compact(index[key]), 'Index metadata mismatch: ' + label)
    url = urlsplit(index['HYPERLINK'])
    require(url.scheme == 'https' and url.netloc == 'mopsov.twse.com.tw'
            and url.path == '/mops/web/ajax_t05sr01_1' and not url.fragment, 'Wrong original endpoint')
    query = parse_qs(url.query, keep_blank_values=True)
    for key, value in {'COMPANY_ID': issuer, 'SEQ_NO': sequence_text,
                       'SPOKE_DATE': day.strftime('%Y%m%d')}.items():
        require(query.get(key) == [value], 'URL identity mismatch: ' + key)
    times = query.get('SPOKE_TIME', [])
    require(len(times) == 1 and re.fullmatch(r'\d{5,6}', times[0]) is not None
            and times[0].zfill(6) == moment.strftime('%H%M%S'), 'URL clock mismatch')
    description = metadata['說明']
    main_lines = [compact(line) for line in description.splitlines()]
    is_board = (bool(main_lines) and re.fullmatch(r'1\.董事會決議日期[:：]\d{3}/\d{2}/\d{2}', main_lines[0])
                and any(line.startswith(('2.買回股份目的:', '2.買回股份目的：')) for line in main_lines))
    board_date = roc_date(re.split(r'[:：]', main_lines[0], maxsplit=1)[1]) if is_board else None
    return dict(issuer=issuer, reported_datetime=moment.isoformat(), sequence=sequence,
                subject=re.sub(r'\s+', ' ', metadata['主旨']).strip(),
                description=description, description_sha256=digest(description.encode()),
                event_id=f'M35:{issuer}:{day.isoformat()}:{sequence}',
                board_date=board_date.isoformat() if board_date else None)


def run():
    archives = []
    documents = read_json(ROOT / 'documents_full.json')
    linked = read_json(ROOT / 'linked_cases_full.json')
    require(len(documents) == 122 and len(linked['cases']) == 47, 'Unexpected census size')
    index_archive = archived(OLD, 'query', archives)
    index_rows = json.loads(index_archive['raw/announcements_2024.json'])['data']
    indices = {row['HYPERLINK']: row for row in index_rows}
    require(len(indices) == len(index_rows) == 122, 'Duplicate or missing raw index rows')

    sources, source_paths, failed = {}, {}, []
    for directory, batch in [(OLD, 'originals')] + [(OUT, f'originals{i:02}') for i in range(1, 5)] + [(OUT, 'recovery')]:
        saved = archived(directory, batch, archives)
        records = json.loads(saved['raw/results.json'])['requests']
        for record in records:
            request = record['request']
            body = saved['raw/' + request['filename']]
            require(digest(body) == record['sha256'], 'Raw source body hash')
            if record.get('http_status') != 200 or record.get('exit_code') != 0:
                failed.append(dict(batch=batch, filename=request['filename'], url=request['url'],
                                   http_status=record.get('http_status'), exit_code=record.get('exit_code'),
                                   sha256=digest(body)))
                continue
            require(request['url'] not in sources, 'Duplicate successful source URL')
            sources[request['url']] = body
            source_paths[request['url']] = batch + '/' + request['filename']
    require(set(sources) == set(indices), 'Successful raw source census differs from index')
    repair = read_json('configs/buyback_coverage_recovery_protocol_20261020.json')
    require(len(failed) == 1 and failed[0]['http_status'] == 502
            and failed[0]['filename'] == repair['failed_filename']
            and failed[0]['sha256'] == repair['failed_body_sha256']
            and failed[0]['url'] == repair['url'], 'Original 502 was not preserved')
    require(repair['url'] in sources and digest(sources[repair['url']]) != failed[0]['sha256'],
            'Separate successful recovery missing')

    parsed, groups = {}, collections.defaultdict(list)
    for number, document in enumerate(documents, 1):
        url = document['url']
        require(url in sources, 'Replay document has no archived source')
        identity = independently_parse(sources[url], indices[url])
        for key in ['issuer', 'reported_datetime', 'sequence', 'subject', 'description',
                    'description_sha256', 'event_id']:
            require(identity[key] == document[key], f'Replay mismatch {key}: {url}')
        require(document['original_url'] == url, 'Original URL field mismatch')
        require(identity['event_id'] not in parsed, 'Duplicate replay event ID')
        identity['source_document_number'] = number
        parsed[identity['event_id']] = identity
        require((identity['board_date'] is not None) == (document['document_form'] == 'board_resolution'),
                'Independent board-form classification differs')
        if identity['board_date']:
            groups[identity['issuer'], identity['board_date']].append(identity)
    require(len(parsed) == 122 and {d['url'] for d in documents} == set(indices), 'Document census mismatch')

    annual_archive = archived(OLD, 'discovery', archives)
    annual = []
    for row in tree(annual_archive['raw/annual_2024.html']).xpath('//tr'):
        cells = row.xpath('./th | ./td')
        if len(cells) == 20 and re.fullmatch(r'\d+', compact(cell_text(cells[0]))):
            # No quantity, execution, performance or price columns are extracted.
            annual.append((compact(cell_text(cells[1])), roc_date(cell_text(cells[3])).isoformat()))
    require(len(annual) == 47 and len(set(annual)) == 47, 'Independent annual keys not unique')
    require(set(groups) == set(annual), 'Board documents and annual issuer/date keys differ')
    case_checks = []
    for number, (key, case) in enumerate(zip(annual, linked['cases']), 1):
        require((case['issuer'], case['board_date']) == key and case['annual_row_number'] == number,
                'Annual case key/order mismatch')
        retained = sorted(groups[key], key=lambda d: (dt.datetime.fromisoformat(d['reported_datetime']),
                                                       d['sequence'], d['event_id'], d['source_document_number']))
        require([d['event_id'] for d in retained] == [v['event_id'] for v in case['versions']],
                'Retained version chronology mismatch')
        first = case['earliest_retained_record']
        for field in ['event_id', 'reported_datetime', 'sequence', 'subject', 'source_document_number']:
            require(first[field] == retained[0][field], 'Earliest retained record mismatch: ' + field)
        require(first['first_ever_publication_verified'] is False, 'Unjustified first-ever claim')
        case_checks.append(dict(annual_row_number=number, issuer=key[0], board_date=key[1],
                               retained_versions=len(retained), earliest_retained_event_id=first['event_id'],
                               earliest_retained_datetime=first['reported_datetime'],
                               first_ever_publication_verified=False))

    policy_archive = archived(OUT, 'index', archives)
    pdf = policy_archive['raw/twse_2017_disclosure_guide.pdf']
    require(digest(pdf) == 'aa6915b877d0af63a9a4a921133bddd25954b31b967709d54e7a09b92ed7c444',
            'Reviewed 2017 PDF changed')
    reader = PdfReader(io.BytesIO(pdf))
    image_buffer = io.BytesIO()
    reader.pages[12].images[4].image.save(image_buffer, format='PNG')
    require(digest(image_buffer.getvalue()) == 'af90e1236fe050f3cebb3c649773a1df71676581d38a909d7d0c1ab151ec88eb',
            'Visually reviewed image changed')
    result = dict(
        status='passed', parser='lxml HTMLParser(encoding=utf-8); independent tree extraction',
        original_identities_verified=len(parsed), annual_case_keys_verified=len(case_checks),
        earliest_retained_chronologies_verified=len(case_checks),
        board_documents_verified=sum(len(v) for v in groups.values()),
        full_description_hashes_verified=len(parsed), archive_checks=archives,
        retained_failed_responses=failed, separate_recovery_verified=True,
        raw_index_sha256=digest(index_archive['raw/announcements_2024.json']),
        documents_sha256=digest((ROOT / 'documents_full.json').read_bytes()),
        linked_cases_sha256=digest((ROOT / 'linked_cases_full.json').read_bytes()),
        case_checks=case_checks,
        manual_image_review=dict(
            source_pdf_sha256=digest(pdf), pdf_page_number=13, printed_slide_number=12,
            embedded_image_number=5, image_png_sha256=digest(image_buffer.getvalue()),
            visual_review_method='pypdf embedded image extraction to /tmp, then view_image; PDF pages 13-15 inspected',
            exact_clause='重大訊息如已發布即無法修改，如欲更正請重新發布，並於主旨敘明為「更正」。',
            location='法人說明會申報作業，作業說明第3點',
            scope='TWSE 2017年3月法說會申報畫面說明；不是2024庫藏股全部原文不可刪改或全集保證',
            adjacent_exception='第5點允許公司自行修改已確認法說會影音資訊連結，不能混同為重大訊息原文',
        ),
        no_market_outcomes_read=True, historical_pit_verified=False,
        first_publication_time_verified=False, source_gate_passed=False,
        limitation='Confirms saved raw-source/replay identities and earliest retained chronology only; no first-ever or historical completeness guarantee.',
    )
    target = OUT / 'independent_audit.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ['status', 'original_identities_verified',
                     'annual_case_keys_verified', 'board_documents_verified',
                     'separate_recovery_verified', 'source_gate_passed']}))


if __name__ == '__main__':
    run()
