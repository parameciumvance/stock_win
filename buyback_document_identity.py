"""Verify MOPS document identity without dropping unsupported numbered forms.

The frozen original parser remains the authority for issuer, publication time,
sequence, subject and official URL checks.  Its explicit unsupported-form error
is recoverable here.  The separately verified 13-field purpose-change schema
shares a first label with the old board form, so only that complete exact schema
can recover its old missing-field error.  Any other missing field or identity
failure is still fatal.  Neither form recognition nor identity proves initial
versions or historical availability.
"""
import datetime as dt
import hashlib
import re

from buyback_original_document import _Tables, _compact, _text, parse_document


_METADATA = {'序號', '發言日期', '發言時間', '主旨', '說明'}
_UNSUPPORTED_FORM = 'Unsupported buyback numbered form'
_DAMAGED_KNOWN_FORM = 'Missing, duplicate or out-of-order numbered buyback fields'
_PURPOSE_CHANGE = [
    '董事會決議日期', '變更後買回股份之目的', '原買回股份種類',
    '原預定買回之期間', '實際買回期間', '申報前三年內買回公司股份之情形',
    '已申報買回但未執行完畢之情形', '董事會決議通過變更原買回股份目的之會議紀錄',
    '「上市上櫃公司買回本公司股份辦法」第十條規定之轉讓辦法',
    '「上市上櫃公司買回本公司股份辦法」第十一條規定之轉讓或認股辦法',
    '董事會已考慮公司財務狀況，不影響公司資本維持之聲明',
    '會計師或證券承銷商對買回股份價格之合理性評估意見', '其他證期局所規定之事項',
]


def _purpose_change_fields(description: str):
    """Recognize only the exact 13-label format observed in archived originals.

    The two 1338 originals dated 2024-11-13 and 2024-11-20 use this format.
    Label 10 really says 轉讓, unlike the old board form's 轉換: retain the
    source wording.  Nested employee-transfer clauses stay in their main field.
    """
    candidates = list(re.finditer(r'(?m)^(\d{1,2})\.([^\n:：]+)[:：]', description))
    if not any(int(m[1]) == 2 and _compact(m[2]) == _PURPOSE_CHANGE[1]
               for m in candidates):
        return None
    starts = [(int(m[1]), m.start()) for m in candidates
              if 1 <= int(m[1]) <= len(_PURPOSE_CHANGE)
              and _compact(m[2]) == _PURPOSE_CHANGE[int(m[1]) - 1]]
    if [n for n, _ in starts] != list(range(1, len(_PURPOSE_CHANGE) + 1)):
        raise ValueError('Missing, duplicate or out-of-order purpose-change fields')
    return {
        str(number): description[start:starts[i + 1][1] if i + 1 < len(starts)
                                 else len(description)].strip()
        for i, (number, start) in enumerate(starts)
    }


def _verified_metadata(body: bytes) -> dict:
    """Recover text only after the original parser has checked its identity.

    This repeats table extraction, not identity validation.  It is reached only
    after ``parse_document`` has verified every document/index/URL identifier
    and rejected the *numbered schema*.  Preserve the same whitespace treatment
    as that parser, including internal numbered clauses and explicit HTML breaks.
    """
    parser = _Tables()
    parser.feed(body.decode('utf-8-sig'))
    parser.close()
    records = []
    for table in parser.tables:
        metadata = {}
        for raw_row in table:
            row = [_text(''.join(cell)) for cell in raw_row]
            for i, cell in enumerate(row[:-1]):
                label = _compact(cell)
                if label in _METADATA:
                    if label in metadata:
                        raise ValueError('Duplicate document metadata label: ' + label)
                    metadata[label] = row[i + 1]
        if set(metadata) == _METADATA:
            records.append(metadata)
    if len(records) != 1:
        raise ValueError('Missing or ambiguous original announcement table')
    return records[0]


def parse_identity(body: bytes, index_row: dict) -> dict:
    """Return verified identity plus full original description and schema status.

    A form can be unknown even when its document identity is verified.  Such a
    form keeps its complete description and has no inferred numbered fields.
    ``required_schema_known`` identifies an explicitly supported original-label
    schema, including purpose changes.  It says nothing about historical
    completeness, availability or first versions.
    """
    try:
        parsed = parse_document(body, index_row)
    except ValueError as error:
        if str(error) not in (_UNSUPPORTED_FORM, _DAMAGED_KNOWN_FORM):
            raise
        fields = _verified_metadata(body)
        if str(error) == _DAMAGED_KNOWN_FORM:
            numbered = _purpose_change_fields(fields['說明'])
            if numbered is None:
                raise
            form, known = 'purpose_change', True
        else:
            form, numbered, known = 'unclassified', {}, False
        date, time = _compact(fields['發言日期']), _compact(fields['發言時間'])
        # The original parser already validated ROC date/time and URL agreement.
        year, month, day = date.split('/')
        timestamp = dt.datetime.fromisoformat(
            f'{int(year) + 1911:04d}-{month}-{day}T{time}'
        ).replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
        parsed = {
            'issuer': str(index_row['COMPANY_ID']),
            'reported_datetime': timestamp.isoformat(),
            'sequence': int(_compact(fields['序號'])),
            'subject': re.sub(r'\s+', ' ', fields['主旨']).strip(),
            'reported_fields': fields,
            'numbered_fields': numbered,
            'document_form': form,
            'first_field_is_board_resolution': False,
        }
    else:
        known = True
    description = parsed['reported_fields']['說明']
    return {
        **parsed,
        'description': description,
        'description_sha256': hashlib.sha256(description.encode('utf-8')).hexdigest(),
        'required_schema_known': known,
        'original_url': index_row['HYPERLINK'],
        'document_identity_verified': True,
    }
