"""Identify a saved MOPS announcement and preserve its whole description.

M11 combines many unrelated forms. This parser deliberately does not apply the
frozen buyback numbered-field schemas, classify transactions, or infer first
availability. Its only positive claim is document/index/detail-pointer identity.
"""
import datetime as dt
import hashlib
import re
from zoneinfo import ZoneInfo

from buyback_announcement_index import _detail_query, _roc_date
from buyback_original_document import _Tables, _compact, _text


_TAIPEI = ZoneInfo('Asia/Taipei')
_LABELS = frozenset(('序號', '發言日期', '發言時間', '主旨', '說明'))
_INDEX_FIELDS = frozenset(('COMPANY_ID', 'CDATE', 'CTIME', 'SUBJECT', 'HYPERLINK'))


def parse_document(body: bytes, index_original_fields: dict) -> dict:
    """Validate a single current page against one original index row.

    ``raw_metadata`` contains the five extracted source-text fields. HTML
    entities are decoded, CRLF becomes LF, and outer whitespace is stripped by
    the reused table helpers; internal description text and numbering remain.
    ``description_sha256`` hashes that retained UTF-8 text, while ``body_sha256``
    identifies the original unmodified response bytes. Identity comparisons
    ignore display whitespace only, never punctuation or numeric characters.
    """
    if not isinstance(body, bytes):
        raise TypeError('Original announcement must be bytes')
    if (not isinstance(index_original_fields, dict)
            or not _INDEX_FIELDS <= index_original_fields.keys()
            or any(not isinstance(index_original_fields[key], str) for key in _INDEX_FIELDS)):
        raise ValueError('Original index identity fields must be reported strings')
    expected = index_original_fields
    if not re.fullmatch(r'[0-9]{4,6}', expected['COMPANY_ID']):
        raise ValueError('Invalid index COMPANY_ID')
    day = _roc_date(expected['CDATE'])
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]', expected['CTIME']):
        raise ValueError('Invalid index local HH:MM:SS')
    query = _detail_query(expected['HYPERLINK'], expected['COMPANY_ID'], day, expected['CTIME'])
    parser = _Tables()
    parser.feed(body.decode('utf-8-sig', errors='strict'))
    parser.close()
    tables = [[[_text(''.join(cell)) for cell in row] for row in table]
              for table in parser.tables]
    providers = []
    for table in tables:
        for row in table:
            for cell in row:
                providers.extend(match[1] for match in re.finditer(
                    r'本資料由\s*[（(][^）)]+[）)]\s*([0-9]{4,6})(?![0-9])', cell))
    if len(providers) != 1:
        raise ValueError('Missing or ambiguous original announcement issuer')
    issuer = providers[0]
    if issuer != expected['COMPANY_ID']:
        raise ValueError('Document issuer differs from original index')
    records = []
    for table in tables:
        metadata = {}
        for row in table:
            for position, cell in enumerate(row[:-1]):
                label = _compact(cell)
                if label in _LABELS:
                    if label in metadata:
                        raise ValueError('Duplicate document metadata label: ' + label)
                    metadata[label] = row[position + 1]
        if set(metadata) == _LABELS:
            records.append(metadata)
    if len(records) != 1:
        raise ValueError('Missing or ambiguous original announcement record')
    fields = records[0]
    if (_compact(fields['發言日期']) != expected['CDATE']
            or _compact(fields['發言時間']) != expected['CTIME']):
        raise ValueError('Document reported local date/time differs from original index')
    if _compact(fields['主旨']) != _compact(expected['SUBJECT']):
        raise ValueError('Document subject differs from original index')
    sequence_text = _compact(fields['序號'])
    if not re.fullmatch(r'[1-9][0-9]*', sequence_text) or sequence_text != query['SEQ_NO']:
        raise ValueError('Document sequence differs from official detail pointer')
    timestamp = dt.datetime.combine(day, dt.time.fromisoformat(expected['CTIME']), tzinfo=_TAIPEI)
    description = fields['說明']
    if not description:
        raise ValueError('Missing original announcement description')
    return dict(issuer=issuer, reported_datetime=timestamp.isoformat(), sequence=int(sequence_text),
                subject=fields['主旨'], description=description,
                description_sha256=hashlib.sha256(description.encode('utf-8')).hexdigest(),
                body_sha256=hashlib.sha256(body).hexdigest(), raw_metadata=fields,
                source_url=expected['HYPERLINK'], metadata_identity_verified=True,
                description_text_policy='HTMLdecoded; CRLF/CR converted toLF; outer whitespace stripped; internal text retained',
                transaction_form=None, eligible_cash_merger=None, cash_claim_source_gate_passed=False,
                independent_deal_identity_verified=False, historical_pit_verified=False,
                first_publication_time_verified=False, source_gate_passed=False)
