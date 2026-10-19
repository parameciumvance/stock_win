"""Validate captured M35 announcement index rows, without proving completeness.

The observed endpoint returns data/status/message and no declared total. Preserving
and validating its returned rows must not turn that omission into a complete
historical announcement population or original point-in-time evidence.
"""
import datetime as dt
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo


_TAIPEI = ZoneInfo('Asia/Taipei')
_REQUIRED_FIELDS = frozenset(('CDATE', 'COMPANY_NAME', 'AN_NAME', 'CODE_NAME', 'AN_CODE',
                              'CTIME', 'TYPEK', 'SUBJECT', 'HYPERLINK', 'COMPANY_ID'))
_DETAIL_FIELDS = frozenset(('COMPANY_ID', 'SPOKE_DATE', 'SPOKE_TIME', 'SEQ_NO'))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonstandard JSON constant: ' + value)


def _iso_date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError(label + ' must be an ISO calendar date')
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(label + ' is not a valid calendar date') from error


def _roc_date(value):
    match = re.fullmatch(r'([0-9]{3})/([0-9]{2})/([0-9]{2})', value)
    if not match:
        raise ValueError('CDATE must be the reported three-digit ROC date')
    try:
        return dt.date(int(match[1]) + 1911, int(match[2]), int(match[3]))
    except ValueError as error:
        raise ValueError('CDATE is not a valid calendar date') from error


def _detail_query(url, company_id, day, clock):
    if any(c.isspace() or ord(c) < 32 for c in url) or re.search(r'%(?![0-9A-Fa-f]{2})', url):
        raise ValueError('Detail URL contains whitespace/control or malformed escaping')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'mopsov.twse.com.tw'
                or parsed.port not in (None, 443) or parsed.username is not None
                or parsed.password is not None or parsed.fragment
                or parsed.path != '/mops/web/ajax_t05sr01_1'):
            raise ValueError('Detail URL is not the expected official HTTPS endpoint')
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict')
    except (ValueError, UnicodeError) as error:
        raise ValueError('Invalid official detail URL: ' + str(error)) from error
    query = {}
    for key, value in pairs:
        if key in query:
            raise ValueError('Duplicate URL query key: ' + key)
        query[key] = value
    if not _DETAIL_FIELDS <= query.keys():
        raise ValueError('Detail URL lacks a required event identity field')
    if query['COMPANY_ID'] != company_id:
        raise ValueError('Detail URL company differs from returned row')
    if query['SPOKE_DATE'] != day.strftime('%Y%m%d'):
        raise ValueError('Detail URL date differs from returned row')
    # The captured response represents 08:44:13 as SPOKE_TIME=84413 in
    # one pointer. Permit that observed HMMSS form as well as HHMMSS,
    # explicitly comparing the same local time without rewriting the URL.
    pointer_clock = query['SPOKE_TIME']
    if (not re.fullmatch(r'[0-9]{5,6}', pointer_clock)
            or pointer_clock.zfill(6) != clock.replace(':', '')):
        raise ValueError('Detail URL local time differs from returned row')
    if not re.fullmatch(r'[1-9][0-9]*', query['SEQ_NO']):
        raise ValueError('Detail URL SEQ_NO must be a positive canonical integer')
    return query


def parse_index(body: bytes, start='2024-01-01', end='2024-12-31') -> dict:
    """Strictly validate saved response rows and their official detail pointers.

    Only an explicit integer top-level ``total`` is a declared count. Absence is
    retained as ``None`` and leaves count reconciliation false. Even matching
    totals and fewer than 1,000 returned rows do not prove population coverage.
    All original row fields and their order are preserved under ``original_fields``.
    """
    if not isinstance(body, bytes):
        raise TypeError('body must contain the original response bytes')
    first, last = _iso_date(start, 'start'), _iso_date(end, 'end')
    if first > last:
        raise ValueError('start must not follow end')
    try:
        response = json.loads(body.decode('utf-8-sig', errors='strict'),
                              object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError) as error:
        raise ValueError('Response is not strict UTF-8/BOM JSON: ' + str(error)) from error
    if not isinstance(response, dict) or not {'data', 'status', 'message'} <= response.keys():
        raise ValueError('Expected data/status/message response object')
    if response.keys() - {'data', 'status', 'message', 'total'}:
        raise ValueError('Unknown top-level response schema; inspect saved original')
    if response['status'] != 'success' or response['message'] != ['回傳成功']:
        raise ValueError('Response does not match the observed success status/message')
    data = response['data']
    if not isinstance(data, list):
        raise ValueError('Response data must be a list')
    if len(data) >= 1000:
        raise ValueError('Returned rows reach the 1000-row ceiling; cannot accept possible truncation')
    declared_total = response.get('total')
    if 'total' in response:
        if type(declared_total) is not int or declared_total < 0 or declared_total >= 1000:
            raise ValueError('Declared total must be an integer in [0, 1000)')
        if declared_total != len(data):
            raise ValueError('Declared total differs from the actual returned row count')
    rows, identities = [], set()
    for index, original in enumerate(data, 1):
        if not isinstance(original, dict) or not _REQUIRED_FIELDS <= original.keys():
            raise ValueError('Missing announcement fields at returned row ' + str(index))
        if any(not isinstance(original[key], str) for key in _REQUIRED_FIELDS):
            raise ValueError('Required announcement fields must retain their reported strings')
        if original['TYPEK'] != '上市' or original['AN_CODE'] != 'M35':
            raise ValueError('Returned announcement market/category differs from the fixed query')
        company = original['COMPANY_ID']
        if not re.fullmatch(r'[0-9]{4,6}', company):
            raise ValueError('COMPANY_ID must be the reported four-to-six-digit code')
        day = _roc_date(original['CDATE'])
        if not first <= day <= last:
            raise ValueError('Returned announcement date lies outside the fixed query range')
        clock = original['CTIME']
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]', clock):
            raise ValueError('CTIME must be a valid local HH:MM:SS, without a timezone suffix')
        local = dt.datetime.combine(day, dt.time.fromisoformat(clock), tzinfo=_TAIPEI)
        query = _detail_query(original['HYPERLINK'], company, day, clock)
        # Company, reported date and the endpoint's sequence number identify the
        # announcement. A changed time cannot silently create a second event.
        event_id = 'M35:' + company + ':' + day.isoformat() + ':' + query['SEQ_NO']
        if event_id in identities:
            raise ValueError('Duplicate/conflicting event identity: ' + event_id)
        identities.add(event_id)
        rows.append(dict(returned_row_number=index, event_id=event_id, company_id=company,
                         announcement_date=day.isoformat(), announcement_time=clock,
                         timezone='Asia/Taipei', reported_timestamp_taipei=local.isoformat(),
                         reported_timestamp_utc=local.astimezone(dt.timezone.utc).isoformat(),
                         sequence_no=query['SEQ_NO'], url=original['HYPERLINK'],
                         url_query=query, original_fields=original,
                         announcement_kind=None, original_document_verified=False,
                         historical_pit_verified=False))
    return dict(status='returned_rows_validated', body_sha256=hashlib.sha256(body).hexdigest(),
                size_bytes=len(body), query_start=first.isoformat(), query_end=last.isoformat(),
                response_metadata={k: v for k, v in response.items() if k != 'data'},
                current_response_row_count=len(rows), declared_total=declared_total,
                count_reconciliation_passed='total' in response, returned_row_ceiling=1000,
                rows=rows, returned_rows_and_urls_validated=True,
                complete_announcement_population_verified=False, empty_universe_verified=False,
                historical_pit_verified=False, source_gate_passed=False,
                first_publication_time_verified=False, profit_edge_proven=False)
