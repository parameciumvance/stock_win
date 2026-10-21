"""Pure parsing and monthly reconciliation of retained nominal CB put calendars."""
import calendar
import datetime as dt
from decimal import Decimal
import hashlib
import json
import re


FIELDS = ['代號', '名稱', '賣回日期', '賣回金額', '賣回收益率(%)']


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def _constant(value):
    raise ValueError('Nonstandard or nonfinite JSON constant: ' + value)


def _iso(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('Requested range must use canonical ISO days')
    return dt.date.fromisoformat(value)


def _roc(value):
    match = re.fullmatch(r'([0-9]{3})/([0-9]{2})/([0-9]{2})', value)
    if not match:
        raise ValueError('Calendar rows must retain canonical ROC dates')
    return dt.date(int(match[1]) + 1911, int(match[2]), int(match[3]))


def parse_calendar(body: bytes, start='2026-10-20', end='2027-04-20') -> dict:
    """Preserve all rows in the explicitly declared normalized MONTH range.

    Declared total reconciles only the returned response, not historical market
    completeness.  Reported yield is a contract field, never a holder's future
    investment return.  Zero amounts remain unresolved records, not free puts.
    """
    if not isinstance(body, bytes):
        raise TypeError('Calendar must be the original response bytes')
    first, last = _iso(start), _iso(end)
    if first > last:
        raise ValueError('Requested start follows end')
    declared_first = first.replace(day=1)
    declared_last = last.replace(day=calendar.monthrange(last.year, last.month)[1])
    try:
        response = json.loads(body.decode('utf-8-sig'), object_pairs_hook=_object, parse_constant=_constant)
    except (UnicodeError, ValueError) as error:
        raise ValueError('Invalid strict calendar JSON: ' + str(error)) from error
    if (not isinstance(response, dict) or set(response) != {'tables', 'date', 'stat'}
            or response['stat'] != 'ok' or not isinstance(response['tables'], list)
            or len(response['tables']) != 1):
        raise ValueError('Unexpected successful calendar response schema')
    top_date = f'{declared_first:%Y%m%d}~{declared_last:%Y%m%d}'
    roc_date = '~'.join(f'{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}'
                        for day in (declared_first, declared_last))
    table = response['tables'][0]
    if (response['date'] != top_date or not isinstance(table, dict)
            or set(table) != {'title', 'date', 'fields', 'data', 'totalCount', 'notes', 'summary'}
            or table['date'] != roc_date or table['title'] != roc_date + '轉(交)換公司債賣回權資料統計表'
            or table['fields'] != FIELDS or not isinstance(table['data'], list)
            or type(table['totalCount']) is not int or table['totalCount'] != len(table['data'])
            or not isinstance(table['notes'], list) or not isinstance(table['summary'], list)):
        raise ValueError('Declared month range, table schema or row count differs')
    records, identities, issues, outside = [], set(), [], []
    for number, values in enumerate(table['data'], 1):
        if (not isinstance(values, list) or len(values) != 5
                or any(not isinstance(value, str) for value in values)
                or not re.fullmatch(r'[0-9]{5,6}', values[0])):
            raise ValueError('Unexpected five-string row or bond code')
        day = _roc(values[2])
        if not declared_first <= day <= declared_last:
            raise ValueError('Put date outside the declared full-month response range')
        for value in values[3:]:
            if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', value) or not Decimal(value).is_finite():
                raise ValueError('Invalid finite contract amount or reported yield')
        identity = 'put:' + values[0] + ':' + day.isoformat()
        if identity in identities:
            raise ValueError('Duplicate nominal put event key: ' + identity)
        identities.add(identity)
        records.append(dict(row_number=number, event_id=identity, bond_code=values[0], name=values[1],
                            put_date=day.isoformat(), reported_put_amount=values[3],
                            contract_reported_put_yield=values[4], original_fields=values))
        if Decimal(values[3]) <= 0:
            issues.append(dict(event_id=identity, kind='nonpositive_put_amount_unresolved'))
        if day.weekday() >= 5:
            issues.append(dict(event_id=identity, kind='weekend_nominal_put_date_no_shift'))
        if not first <= day <= last:
            outside.append(identity)
    return dict(status='declared_month_calendar_rows_checked', source_sha256=hashlib.sha256(body).hexdigest(),
                requested_range=dict(start=start, end=end),
                declared_range=dict(start=declared_first.isoformat(), end=declared_last.isoformat()),
                whole_month_normalization_applied=(first != declared_first or last != declared_last),
                day_range_filter_applied=False, records_outside_requested_days=outside,
                response_metadata={key: value for key, value in response.items() if key != 'tables'},
                table_metadata={key: value for key, value in table.items() if key != 'data'},
                records=records, record_count=len(records), declared_count_reconciled=True, issues=issues,
                reported_put_yield_is_holder_future_return=False, reported_amount_units_verified=False,
                business_day_shifts_applied=False, notice_window_verified=False, payment_date_verified=False,
                holder_put_eligibility_verified=False, current_tradability_verified=False,
                complete_population_verified=False, historical_pit_verified=False, source_gate_passed=False)


def reconcile_month(wide, narrow, month='2026-11'):
    """Compare exact original five fields; never merge or fill the responses."""
    if not isinstance(month, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}', month):
        raise ValueError('Expected a canonical ISO month')
    first = _iso(month + '-01')
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    expected_scope = dict(start=first.isoformat(), end=last.isoformat())
    if (narrow['declared_range'] != expected_scope or wide['declared_range']['start'] > first.isoformat()
            or wide['declared_range']['end'] < last.isoformat()):
        raise ValueError('Reconciliation month is not covered by the declared scopes')
    subset = [row for row in wide['records'] if row['put_date'][:7] == month]
    before = {row['event_id']: row for row in subset}
    after = {row['event_id']: row for row in narrow['records']}
    if len(before) != len(subset) or len(after) != len(narrow['records']):
        raise ValueError('Duplicate reconciliation event identity')
    differences = dict(missing_from_narrow=[before[key] for key in sorted(before.keys() - after.keys())],
                       new_in_narrow=[after[key] for key in sorted(after.keys() - before.keys())],
                       changed_original_fields=[dict(event_id=key, wide=before[key]['original_fields'],
                                                      narrow=after[key]['original_fields'])
                                                for key in sorted(before.keys() & after.keys())
                                                if before[key]['original_fields'] != after[key]['original_fields']])
    return dict(month=month, current_snapshot_month_agreement=not any(differences.values()),
                wide_subset_count=len(before), narrow_count=len(after), differences=differences,
                wide_source_sha256=wide['source_sha256'], narrow_source_sha256=narrow['source_sha256'],
                records_merged=False, complete_population_verified=False, historical_pit_verified=False,
                notice_window_verified=False, payment_date_verified=False, holder_put_eligibility_verified=False,
                source_gate_passed=False)
