"""Validate all returned categories for one frozen issuer query, without filters.

M00 is the request's all-category choice. The reported category remains literal
on every row. Saved rows establish neither complete issuer history nor current
trade status, contractual eligibility, or first availability of their contents.
"""
import datetime as dt
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo

from buyback_announcement_index import (
    _detail_query, _invalid_constant, _iso_date, _REQUIRED_FIELDS, _roc_date, _unique_object,
)

_TAIPEI = ZoneInfo('Asia/Taipei')


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite JSON number')
    return result


def parse_index(body: bytes, issuer='6674', start='2026-09-18', end='2026-10-21') -> dict:
    """Preserve every returned row, checking issuer, range and detail identity."""
    if not isinstance(body, bytes):
        raise TypeError('body must contain the original response bytes')
    if not isinstance(issuer, str) or not re.fullmatch(r'[0-9]{4,6}', issuer):
        raise ValueError('Frozen issuer must be a four-to-six-digit string')
    first, last = _iso_date(start, 'start'), _iso_date(end, 'end')
    if first > last:
        raise ValueError('start must not follow end')
    try:
        response = json.loads(body.decode('utf-8-sig', errors='strict'),
                              object_pairs_hook=_unique_object, parse_constant=_invalid_constant,
                              parse_float=_finite_float)
    except (ValueError, UnicodeError) as error:
        raise ValueError('Response is not strict UTF-8/BOM JSON: ' + str(error)) from error
    if (not isinstance(response, dict) or not {'data', 'status', 'message'} <= response.keys()
            or response.keys() - {'data', 'status', 'message', 'total'}):
        raise ValueError('Unexpected all-category index response schema')
    if response['status'] != 'success' or response['message'] != ['回傳成功']:
        raise ValueError('Response does not match the saved API success status/message')
    data = response['data']
    if not isinstance(data, list) or len(data) >= 1000:
        raise ValueError('Data must be a list below the1000-row ceiling; possible truncation')
    total = response.get('total')
    if 'total' in response and (type(total) is not int or not 0 <= total < 1000 or total != len(data)):
        raise ValueError('Declared total must equal the actual row count below1000')
    rows, pointers, legacy = [], set(), {}
    for number, original in enumerate(data, 1):
        if (not isinstance(original, dict) or not _REQUIRED_FIELDS <= original.keys()
                or any(not isinstance(original[key], str) for key in _REQUIRED_FIELDS)):
            raise ValueError('Missing/nonstring announcement fields at returned row ' + str(number))
        category, clock = original['AN_CODE'], original['CTIME']
        if not re.fullmatch(r'M[0-9]{2}', category):
            raise ValueError('Reported category must retain its declaredMxx code')
        if original['COMPANY_ID'] != issuer:
            raise ValueError('Returned issuer differs from fixed issuer query')
        day = _roc_date(original['CDATE'])
        if not first <= day <= last:
            raise ValueError('Returned date lies outside fixed query range')
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]', clock):
            raise ValueError('CTIME must be valid localHH:MM:SS')
        query = _detail_query(original['HYPERLINK'], issuer, day, clock)
        pointer = issuer + ':' + day.isoformat() + ':' + clock.replace(':', '') + ':' + query['SEQ_NO']
        if pointer in pointers:
            raise ValueError('Duplicate/conflicting full detail-pointer identity: ' + pointer)
        pointers.add(pointer)
        local = dt.datetime.combine(day, dt.time.fromisoformat(clock), tzinfo=_TAIPEI)
        event_id = category + ':' + pointer
        legacy_key = issuer + ':' + day.isoformat() + ':' + query['SEQ_NO']
        rows.append(dict(returned_row_number=number, event_id=event_id, pointer_identity=pointer,
                         legacy_key=legacy_key, company_id=issuer, reported_category=category,
                         announcement_date=day.isoformat(), announcement_time=clock,
                         timezone='Asia/Taipei', reported_timestamp_taipei=local.isoformat(),
                         reported_timestamp_utc=local.astimezone(dt.timezone.utc).isoformat(),
                         sequence_no=query['SEQ_NO'], observed_typek=original['TYPEK'],
                         url=original['HYPERLINK'], url_query=query, original_fields=original,
                         original_document_verified=False, historical_pit_verified=False))
        legacy.setdefault(legacy_key, []).append(event_id)
    return dict(status='returned_all_category_issuer_rows_validated',
                body_sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body),
                query_issuer=issuer, query_category='M00', query_start=first.isoformat(), query_end=last.isoformat(),
                response_metadata={key: value for key, value in response.items() if key != 'data'},
                current_response_row_count=len(rows), declared_total=total,
                count_reconciliation_passed='total' in response, returned_row_ceiling=1000,
                observed_categories=sorted({row['reported_category'] for row in rows}),
                observed_market_labels=sorted({row['observed_typek'] for row in rows}),
                legacy_sequence_collisions=[dict(legacy_key=key, event_ids=ids)
                                            for key, ids in sorted(legacy.items()) if len(ids) > 1],
                rows=rows, all_returned_categories_preserved=True, returned_rows_and_urls_validated=True,
                complete_announcement_population_verified=False, empty_universe_verified=False,
                current_tradability_verified=False, current_transaction_status_verified=False,
                contractual_cash_claim_verified=False, historical_pit_verified=False,
                first_publication_time_verified=False, source_gate_passed=False, profit_edge_proven=False)
