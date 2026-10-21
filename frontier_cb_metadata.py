"""Pure preservation and schema checks for the observed CB issue metadata.

Dates and numeric fields remain source strings.  A nominal put date and amount
do not establish a notice window, an executable purchase or a cash payment date.
No enum dictionary, business-day shift or contract interpretation is inferred.
"""
from collections import Counter
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re


EXPECTED_FIELDS = (
    'Date', 'IssuerCode', 'IssuerName', 'BondCode', 'BondType', 'SeriesNumber',
    'TrancheNumber', 'IssueDate', 'MaturityDate', 'IssueAmount', 'OutstandingAmount',
    'CouponRate', 'InterestBasis', 'CouponFrequency', 'PaidFrequency',
    'BondRatingAgency', 'BondRating', 'IssuerRatingAgency', 'IssuerRating',
    'GuarantorRatingAgency', 'GuarantorRating', 'ListingCountry',
    'PrincipalRepayment', 'PrincipalRepaymentDescription', 'ShortName',
    'ListingDate', 'TenorYear', 'TenorMonth', 'ListingStatus', 'Guaranteed',
    'GuaranteeDescription', 'PutOptionDate', 'PutOptionPrice', 'Underwriter',
    'OutstandingChangeDate', 'OutstandingChangeDescription', 'Currency',
    'OfferingMethod', 'Conversion/ExchangePriceAtIssuance',
    'Conversion/ExchangePeriodStartDate', 'Conversion/ExchangePeriodEndDate', 'Trustee',
)
_REQUIRED_DATES = ('Date', 'IssueDate', 'MaturityDate',
                   'Conversion/ExchangePeriodStartDate', 'Conversion/ExchangePeriodEndDate')
_OPTIONAL_DATES = ('ListingDate', 'PutOptionDate', 'OutstandingChangeDate')
_NUMBERS = ('IssueAmount', 'OutstandingAmount', 'CouponRate', 'PutOptionPrice',
            'TenorYear', 'TenorMonth', 'Conversion/ExchangePriceAtIssuance')
_CODES = ('BondType', 'PrincipalRepayment', 'Guaranteed', 'ListingCountry',
          'ListingStatus', 'Currency', 'OfferingMethod', 'CouponFrequency',
          'PaidFrequency', 'InterestBasis')


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def _constant(value):
    raise ValueError('Nonfinite or nonstandard JSON constant: ' + value)


def _date(value, field):
    if not re.fullmatch(r'[0-9]{8}', value):
        raise ValueError(field + ' must retain a canonical YYYYMMDD date')
    try:
        return dt.date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError as error:
        raise ValueError(field + ' is not a valid calendar date') from error


def _decimal(value, field):
    if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', value):
        raise ValueError(field + ' must retain an observed decimal string')
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(field + ' is not a valid Decimal') from error
    if not result.is_finite():
        raise ValueError(field + ' must be finite')
    return result


def parse_metadata(body: bytes) -> dict:
    """Retain every record and report metadata anomalies without granting rights.

    Exact duplicate canonical identities fail instead of selecting one row.
    Empty/nonstandard bond codes and unresolved date/zero-price combinations
    remain in the complete returned record list.  The parser is not restricted
    to an expected row count; an empty response does not prove an empty market.
    """
    if not isinstance(body, bytes):
        raise TypeError('Metadata must be the original response bytes')
    try:
        records = json.loads(body.decode('utf-8-sig'), object_pairs_hook=_object,
                             parse_constant=_constant)
    except (UnicodeError, ValueError) as error:
        raise ValueError('Invalid strict UTF-8 metadata JSON: ' + str(error)) from error
    if not isinstance(records, list):
        raise ValueError('Expected the observed metadata array')
    identities, identity_rows, anomalies = set(), [], []
    empty_codes, nonstandard_codes, bond_code_rows = [], [], {}
    for number, record in enumerate(records, 1):
        if (not isinstance(record, dict) or set(record) != set(EXPECTED_FIELDS)
                or any(not isinstance(value, str) for value in record.values())):
            raise ValueError('Metadata row ' + str(number) + ' differs from the 42-string-field schema')
        dates = {field: _date(record[field], field) for field in _REQUIRED_DATES}
        dates.update({field: _date(record[field], field) for field in _OPTIONAL_DATES if record[field]})
        numbers = {field: _decimal(record[field], field) for field in _NUMBERS}
        if not record['IssuerCode'] or not record['SeriesNumber']:
            raise ValueError('Canonical issuer and series identity must be nonempty')
        identity = tuple(record[field] for field in ('IssuerCode', 'SeriesNumber', 'TrancheNumber', 'IssueDate'))
        if identity in identities:
            raise ValueError('Duplicate canonical CB identity: ' + repr(identity))
        identities.add(identity)
        row_ref = dict(row_number=number, canonical_identity=list(identity), bond_code=record['BondCode'])
        identity_rows.append(row_ref)
        if not record['BondCode']:
            empty_codes.append(row_ref)
        elif not re.fullmatch(r'[0-9]{5,6}', record['BondCode']):
            nonstandard_codes.append(row_ref)
        if record['BondCode']:
            bond_code_rows.setdefault(record['BondCode'], []).append(number)
        kinds = []
        if 'PutOptionDate' in dates and numbers['PutOptionPrice'] == 0:
            kinds.append('put_date_with_zero_price_unresolved')
        if 'PutOptionDate' not in dates and numbers['PutOptionPrice'] != 0:
            kinds.append('put_price_without_put_date_unresolved')
        if dates['IssueDate'] > dates['Date']:
            kinds.append('issue_date_after_snapshot')
        if 'ListingDate' in dates and dates['ListingDate'] > dates['Date']:
            kinds.append('listing_date_after_snapshot')
        if 'PutOptionDate' in dates and dates['PutOptionDate'].weekday() >= 5:
            kinds.append('nominal_put_date_on_weekend_no_shift')
        for kind in kinds:
            anomalies.append(dict(kind=kind, **row_ref))
    counts = Counter(item['kind'] for item in anomalies)
    return dict(
        status='metadata_schema_checked_only', source_sha256=hashlib.sha256(body).hexdigest(),
        source_size_bytes=len(body), records=records, canonical_identity_rows=identity_rows,
        summary=dict(record_count=len(records), field_count=len(EXPECTED_FIELDS),
                     snapshot_date_counts=dict(Counter(record['Date'] for record in records)),
                     literal_enum_code_counts={field: dict(Counter(record[field] for record in records)) for field in _CODES},
                     anomaly_counts=dict(counts), empty_bond_code_count=len(empty_codes),
                     nonstandard_bond_code_count=len(nonstandard_codes)),
        empty_bond_code_rows=empty_codes, nonstandard_bond_code_rows=nonstandard_codes,
        repeated_nonempty_bond_codes={code: rows for code, rows in bond_code_rows.items() if len(rows) > 1},
        anomalies=anomalies, original_strings_preserved=True,
        business_day_shifts_applied=False, snapshot_date_is_publication_timestamp=False,
        enum_meanings_verified=False, notice_window_verified=False, payment_date_verified=False,
        current_tradability_verified=False, holder_put_eligibility_verified=False,
        complete_population_verified=False, historical_pit_verified=False,
        source_gate_passed=False, profit_edge_proven=False, valid_signal=False,
    )
