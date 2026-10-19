"""Parse archived MOPS buyback originals without inferring historical availability.

The three supported numbered forms are the 2024 board resolution, completion and
threshold forms.  Their exact labels distinguish main fields from numbered
clauses inside the employee-transfer rules or board minutes.  The caller owns
version pairing; a board-resolution form can itself be a later correction.
"""
import datetime as dt
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit


_BOARD = [
    '董事會決議日期', '買回股份目的', '買回股份種類', '買回股份總金額上限(元)',
    '預定買回之期間', '預定買回之數量(股)', '買回區間價格(元)', '買回方式',
    '預定買回股份占公司已發行股份總數之比率(%)',
    '申報時已持有本公司股份之累積股數(股)', '申報前三年內買回公司股份之情形',
    '已申報買回但未執行完畢之情形', '董事會決議買回股份之會議紀錄',
    '「上市上櫃公司買回本公司股份辦法」第十條規定之轉讓辦法',
    '「上市上櫃公司買回本公司股份辦法」第十一條規定之轉換或認股辦法',
    '董事會已考慮公司財務狀況，不影響公司資本維持之聲明',
    '會計師或證券承銷商對買回股份價格之合理性評估意見', '其他證期局所規定之事項',
]
_COMPLETION = [
    '原預定買回股份總金額上限(元)', '原預定買回之期間', '原預定買回之數量(股)',
    '原預定買回區間價格(元)', '本次實際買回期間', '本次已買回股份數量(股)',
    '本次已買回股份總金額(元)', '本次平均每股買回價格(元)',
    '累積已持有自己公司股份數量(股)', '累積已持有自己公司股份數量占公司已發行股份總數之比率(%)',
    '本次未執行完畢之原因', '其他應敘明事項',
]
_THRESHOLD = [
    '本次買回股份數量累積達公司已發行股份總額百分之二或金額達新台幣三億元以上之日期',
    '本次買回股份數量(股)', '本次買回股份總金額(元)', '本次平均每股買回價格(元)',
    '於買回期間內累積已持有自己公司股份數量(股)',
    '於買回期間內累積已持有自己公司股份數量占公司已發行股份總數之比率(%)', '其他應敘明事項',
]


class _Tables(HTMLParser):
    """Keep table/cell boundaries and explicit line breaks, including in pre."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            table = []
            self.tables.append(table)
            self.stack.append({'table': table, 'row': None, 'cell': None})
        elif self.stack:
            s = self.stack[-1]
            if tag == 'tr':
                s['row'] = []
                s['table'].append(s['row'])
                s['cell'] = None
            elif tag in ('td', 'th') and s['row'] is not None:
                s['cell'] = []
                s['row'].append(s['cell'])
            elif tag == 'br' and s['cell'] is not None:
                s['cell'].append('\n')

    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell'].append(data)

    def handle_endtag(self, tag):
        if tag == 'table' and self.stack:
            self.stack.pop()
        elif self.stack and tag in ('td', 'th'):
            self.stack[-1]['cell'] = None
        elif self.stack and tag == 'tr':
            self.stack[-1]['row'] = self.stack[-1]['cell'] = None


def _compact(value):
    """Ignore display whitespace only; retain every non-whitespace character."""
    return re.sub(r'\s+', '', value)


def _text(value):
    return value.replace('\r\n', '\n').replace('\r', '\n').strip()


def _numbered(description):
    first = re.match(r'1\.([^\n:：]+)[:：]', description)
    if not first:
        raise ValueError('Missing first numbered buyback field')
    forms = [('board_resolution', _BOARD), ('completion', _COMPLETION), ('threshold', _THRESHOLD)]
    found = [(name, labels) for name, labels in forms if _compact(first[1]) == labels[0]]
    if len(found) != 1:
        raise ValueError('Unsupported buyback numbered form')
    name, labels = found[0]
    # Match the exact label as well as its number. Subclauses such as 1.依據…,
    # 4.1轉讓期間 and (1)… remain inside the containing original field.
    starts = []
    for match in re.finditer(r'(?m)^(\d{1,2})\.([^\n:：]+)[:：]', description):
        number = int(match[1])
        if 1 <= number <= len(labels) and _compact(match[2]) == labels[number - 1]:
            starts.append((number, match.start()))
    if [n for n, _ in starts] != list(range(1, len(labels) + 1)):
        raise ValueError('Missing, duplicate or out-of-order numbered buyback fields')
    return name, {
        str(number): description[start:starts[i + 1][1] if i + 1 < len(starts) else len(description)].strip()
        for i, (number, start) in enumerate(starts)
    }


def parse_document(body: bytes, index_row: dict) -> dict:
    """Return original text segments only after document/index/URL identities agree.

    ``numbered_fields`` maps string field numbers to complete original segments,
    including the number and label.  Newlines are standardized to LF; numbers,
    punctuation, prices and internal clause text are not rewritten.  The boolean
    identifies a form, not a first version or point-in-time availability claim.
    """
    if not isinstance(body, bytes):
        raise TypeError('Original document must be bytes')
    parser = _Tables()
    parser.feed(body.decode('utf-8-sig'))
    parser.close()
    tables = [[[_text(''.join(c)) for c in row] for row in t] for t in parser.tables]
    providers = []
    for table in tables:
        for row in table:
            for cell in row:
                match = re.search(r'本資料由\s*[（(][^）)]+[）)]\s*(\d{4,6})(?!\d)', cell)
                if match:
                    providers.append(match[1])
    if len(providers) != 1:
        raise ValueError('Missing or ambiguous document issuer')
    issuer = providers[0]
    records = []
    for table in tables:
        metadata = {}
        for row in table:
            for i, cell in enumerate(row[:-1]):
                label = _compact(cell)
                if label in ('序號', '發言日期', '發言時間', '主旨', '說明'):
                    if label in metadata:
                        raise ValueError('Duplicate document metadata label: ' + label)
                    metadata[label] = row[i + 1]
        if set(metadata) == {'序號', '發言日期', '發言時間', '主旨', '說明'}:
            records.append(metadata)
    if len(records) != 1:
        raise ValueError('Missing or ambiguous original announcement table')
    fields = records[0]
    if issuer != str(index_row['COMPANY_ID']):
        raise ValueError('Document issuer differs from index COMPANY_ID')
    date, time = _compact(fields['發言日期']), _compact(fields['發言時間'])
    if date != _compact(str(index_row['CDATE'])) or time != _compact(str(index_row['CTIME'])):
        raise ValueError('Document reported datetime differs from index')
    if _compact(fields['主旨']) != _compact(str(index_row['SUBJECT'])):
        raise ValueError('Document subject differs from index')
    m = re.fullmatch(r'(\d{3})/(\d{2})/(\d{2})', date)
    if not m or not re.fullmatch(r'\d{2}:\d{2}:\d{2}', time):
        raise ValueError('Invalid document ROC date or clock time')
    timestamp = dt.datetime.fromisoformat(f'{int(m[1]) + 1911:04d}-{m[2]}-{m[3]}T{time}')
    timestamp = timestamp.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    raw_sequence = _compact(fields['序號'])
    if not re.fullmatch(r'[1-9]\d*', raw_sequence):
        raise ValueError('Invalid original announcement sequence')
    sequence = int(raw_sequence)
    location = urlsplit(index_row['HYPERLINK'])
    if (location.scheme != 'https' or location.netloc != 'mopsov.twse.com.tw'
            or location.path != '/mops/web/ajax_t05sr01_1' or location.fragment):
        raise ValueError('Original URL is not the official HTTPS announcement endpoint')
    query = parse_qs(location.query, keep_blank_values=True)
    expected = {'SEQ_NO': str(sequence), 'COMPANY_ID': issuer,
                'SPOKE_DATE': timestamp.strftime('%Y%m%d')}
    for key, value in expected.items():
        if query.get(key) != [value]:
            raise ValueError('Original URL identity differs: ' + key)
    url_times = query.get('SPOKE_TIME', [])
    # MOPS sometimes omits the leading hour zero (08:44:13 -> 84413).
    # Normalize only for comparison; keep the caller's original URL untouched.
    if (len(url_times) != 1 or not re.fullmatch(r'[0-9]{5,6}', url_times[0])
            or url_times[0].zfill(6) != timestamp.strftime('%H%M%S')):
        raise ValueError('Original URL identity differs: SPOKE_TIME')
    form, numbered = _numbered(fields['說明'])
    return {'issuer': issuer, 'reported_datetime': timestamp.isoformat(), 'sequence': sequence,
            'subject': re.sub(r'\s+', ' ', fields['主旨']).strip(), 'reported_fields': fields,
            'numbered_fields': numbered, 'document_form': form,
            'first_field_is_board_resolution': form == 'board_resolution'}
