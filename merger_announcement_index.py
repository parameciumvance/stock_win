"""Strict M11 index validation without classifying cash-merger eligibility.

M11 includes unrelated capital actions. Returned rows and current market labels
are preserved in full; successful parsing does not establish a merger population,
historical listing status, original availability, or a contractual cash claim.
"""
import datetime as dt
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from buyback_announcement_index import (
    _detail_query, _invalid_constant, _iso_date, _REQUIRED_FIELDS, _roc_date, _unique_object,
)


_TAIPEI = ZoneInfo('Asia/Taipei')


def parse_index(body: bytes, start='2026-07-01', end='2026-09-30') -> dict:
    """Validate M11 returned rows against a caller's frozen calendar interval.

    Shares the frozen API's strict JSON/date/detail-pointer helpers. No source
    field is rewritten and no market or subject is filtered. An observed market
    mismatch leaves returned rows available for audit and qualifies no market.
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
        raise ValueError('Unknown top-level response schema; inspect the saved original')
    if response['status'] != 'success' or response['message'] != ['回傳成功']:
        raise ValueError('Response does not match the observed API success status/message')
    data = response['data']
    if not isinstance(data, list):
        raise ValueError('Response data must be a list')
    if len(data) >= 1000:
        raise ValueError('Returned rows reach the1000-row ceiling; possible truncation')
    declared_total = response.get('total')
    if 'total' in response:
        if type(declared_total) is not int or not 0 <= declared_total < 1000:
            raise ValueError('Declared total must be an integer in[0,1000)')
        if declared_total != len(data):
            raise ValueError('Declared total differs from actual returned rows')
    rows, identities, legacy_groups = [], set(), {}
    for index, original in enumerate(data, 1):
        if not isinstance(original, dict) or not _REQUIRED_FIELDS <= original.keys():
            raise ValueError('Missing announcement fields at returned row ' + str(index))
        if any(not isinstance(original[key], str) for key in _REQUIRED_FIELDS):
            raise ValueError('Required announcement fields must preserve reported strings')
        if original['AN_CODE'] != 'M11':
            raise ValueError('Returned announcement category differs from fixedM11 query')
        company, clock = original['COMPANY_ID'], original['CTIME']
        if not re.fullmatch(r'[0-9]{4,6}', company):
            raise ValueError('COMPANY_ID must be the reported four-to-six-digit code')
        day = _roc_date(original['CDATE'])
        if not first <= day <= last:
            raise ValueError('Returned announcement date lies outside fixed query range')
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]', clock):
            raise ValueError('CTIME must be valid localHH:MM:SS without timezone suffix')
        query = _detail_query(original['HYPERLINK'], company, day, clock)
        # M11's captured API response reuses(company,date,SEQ_NO) for records
        # with different clocks and subjects. Unlike the frozenM35 namespace,
        # retain the complete required detail-pointer identity, including its
        # already verified local clock. Do not infer independent deal identity.
        legacy_key = 'M11:' + company + ':' + day.isoformat() + ':' + query['SEQ_NO']
        event_id = ('M11:' + company + ':' + day.isoformat() + ':'
                    + clock.replace(':', '') + ':' + query['SEQ_NO'])
        if event_id in identities:
            raise ValueError('Duplicate/conflicting event identity: ' + event_id)
        identities.add(event_id)
        local = dt.datetime.combine(day, dt.time.fromisoformat(clock), tzinfo=_TAIPEI)
        rows.append(dict(returned_row_number=index, event_id=event_id, legacy_key=legacy_key,
                         company_id=company,
                         announcement_date=day.isoformat(), announcement_time=clock,
                         observed_typek=original['TYPEK'], timezone='Asia/Taipei',
                         reported_timestamp_taipei=local.isoformat(),
                         reported_timestamp_utc=local.astimezone(dt.timezone.utc).isoformat(),
                         sequence_no=query['SEQ_NO'], url=original['HYPERLINK'], url_query=query,
                         original_fields=original, transaction_form=None, eligible_cash_merger=None,
                         original_document_verified=False, historical_pit_verified=False))
        legacy_groups.setdefault(legacy_key, []).append(dict(
            returned_row_number=index, event_id=event_id, announcement_time=clock,
            url=original['HYPERLINK'], subject=original['SUBJECT']))
    collisions = [dict(legacy_key=key, records=group,
                       resolution='Unverified distinct reported pointers; original forms required, not independent case proof')
                  for key, group in sorted(legacy_groups.items()) if len(group) > 1]
    markets = sorted({row['observed_typek'] for row in rows})
    qualified = bool(rows) and markets == ['上市']
    return dict(status='returned_m11_rows_validated', body_sha256=hashlib.sha256(body).hexdigest(),
                size_bytes=len(body), query_start=first.isoformat(), query_end=last.isoformat(),
                expected_category='M11', observed_market_labels=markets,
                query_market_qualified=qualified,
                query_market_qualification_basis='Nonempty returned rows all reportTYPEK上市; not historical listing evidence',
                historical_listing_status_verified=False,
                response_metadata={k: v for k, v in response.items() if k != 'data'},
                current_response_row_count=len(rows), declared_total=declared_total,
                count_reconciliation_passed='total' in response, returned_row_ceiling=1000,
                pointer_identity_basis='M11/COMPANY_ID/local_date/local_clock/SEQ_NO, with clock checked against official detailURL',
                full_pointer_identity_unique_in_response=True,
                legacy_key_collisions=collisions, legacy_key_collision_group_count=len(collisions),
                legacy_key_collision_row_count=sum(len(group['records']) for group in collisions),
                identity_namespace_unverified=True, independent_event_cases_verified=False,
                rows=rows, returned_rows_and_urls_validated=True,
                semantic_cash_merger_selection_performed=False, eligible_cash_merger_count=None,
                complete_announcement_population_verified=False, empty_universe_verified=False,
                historical_pit_verified=False, source_gate_passed=False,
                first_publication_time_verified=False, profit_edge_proven=False)
