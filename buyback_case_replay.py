"""Link retained buyback board records by exact issuer and resolution date.

No outcome fields select or exclude cases.  This is a replay of retained source
versions, not a claim that the earliest retained page is the first publication.
Completion, threshold and purpose-change documents remain separate and unlinked.
"""
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import re


def _roc_date(value):
    match = re.fullmatch(r'([0-9]{3})/([0-9]{2})/([0-9]{2})', value)
    if not match:
        raise ValueError('Expected an exact reported ROC date')
    return dt.date(int(match[1]) + 1911, int(match[2]), int(match[3]))


def _board_date(fields):
    text = fields.get('1', '')
    match = re.fullmatch(r'\s*1\.\s*董事會決議日期\s*[:：]\s*'
                         r'([0-9]{3}/[0-9]{2}/[0-9]{2})\s*', text)
    if not match:
        raise ValueError('Board form has no exact first-field resolution date')
    return _roc_date(match[1])


def _summary(document, number):
    fields = document['numbered_fields']
    if (not isinstance(fields, dict) or any(
            not isinstance(key, str) or not re.fullmatch(r'[1-9][0-9]*', key)
            or not isinstance(value, str) for key, value in fields.items())):
        raise ValueError('Document numbered fields must be string-keyed original strings')
    moment = dt.datetime.fromisoformat(document['reported_datetime'])
    if moment.utcoffset() is None:
        raise ValueError('Document reported datetime must include its timezone')
    identity = document['event_id']
    if not isinstance(identity, str) or not identity:
        raise ValueError('Document event_id must be a nonempty string')
    if not isinstance(document['issuer'], str) or not re.fullmatch(r'[0-9]{4,6}', document['issuer']):
        raise ValueError('Document issuer must retain its reported code string')
    if type(document['sequence']) is not int or document['sequence'] <= 0:
        raise ValueError('Document sequence must be a positive integer')
    if not isinstance(document['subject'], str) or not isinstance(document['document_form'], str):
        raise ValueError('Document subject and form must be strings')
    return dict(
        source_document_number=number, event_id=identity, issuer=document['issuer'],
        reported_datetime=document['reported_datetime'], sequence=document['sequence'],
        subject=document['subject'], document_form=document['document_form'],
        explicitly_titled_revision=bool(re.search('更正|補充', document['subject'])),
        numbered_fields={key: value for key, value in fields.items() if int(key) <= 12},
        numbered_field_sha256={key: hashlib.sha256(value.encode('utf-8')).hexdigest()
                               for key, value in fields.items()},
    ), moment


def _changes(previous, current):
    old, new = previous['numbered_field_sha256'], current['numbered_field_sha256']
    result = []
    for field in sorted(old.keys() | new.keys(), key=int):
        if field in old and field in new and old[field] == new[field]:
            continue
        item = dict(field=field, previous_present=field in old, current_present=field in new,
                    previous_sha256=old.get(field), current_sha256=new.get(field))
        if int(field) <= 12:
            if field in old:
                item['previous_value'] = previous['numbered_fields'][field]
            if field in new:
                item['current_value'] = current['numbered_fields'][field]
        result.append(item)
    return result


def link_cases(annual_snapshot: dict, documents: list[dict]) -> dict:
    """Preserve every annual case and its exact-key retained board chronology.

    Annual rows supply only issuer and resolution date for linking.  Quantity,
    price and realized execution never determine inclusion or version identity.
    Corrections changing resolution dates cannot be reliably linked by this
    key: unmatched records and possible links are reported without guessing.
    Duplicate keys or identities and unmarked repeated board records remain
    explicit ambiguities.  No actual historical first-publication gate passes.
    """
    if not isinstance(annual_snapshot, dict) or not isinstance(annual_snapshot.get('rows'), list):
        raise ValueError('Annual snapshot must contain its saved rows list')
    if not isinstance(documents, list):
        raise ValueError('documents must be a list of verified source records')
    cases, by_key, issuer_cases = [], defaultdict(list), defaultdict(list)
    issues = []
    for number, row in enumerate(annual_snapshot['rows'], 1):
        columns = row.get('original_columns') if isinstance(row, dict) else None
        if (not isinstance(columns, list) or len(columns) != 20
                or not isinstance(columns[1], str) or not re.fullmatch(r'[0-9]{4,6}', columns[1])
                or not isinstance(columns[3], str)):
            raise ValueError('Invalid saved annual row at position ' + str(number))
        issuer, board = columns[1], _roc_date(columns[3])
        case = dict(case_id=f'annual:{number}:{issuer}:{board.isoformat()}',
                    annual_row_number=number, issuer=issuer,
                    board_date_roc=columns[3], board_date=board.isoformat(),
                    versions=[], issues=[], earliest_retained_record=None,
                    missing_initial_evidence=False, linkage_ambiguous=False)
        cases.append(case)
        by_key[(issuer, board)].append(case)
        issuer_cases[issuer].append(case)
    for key, group in by_key.items():
        if len(group) > 1:
            issue = dict(kind='ambiguous_annual_case_key', issuer=key[0],
                         board_date=key[1].isoformat(), case_ids=[c['case_id'] for c in group])
            issues.append(issue)
            for case in group:
                case['linkage_ambiguous'] = True
                case['issues'].append(issue)

    summaries = []
    for number, document in enumerate(documents, 1):
        try:
            summary, moment = _summary(document, number)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Invalid verified document at position ' + str(number) + ': ' + str(error)) from error
        summaries.append((summary, moment, document))
    counts = Counter(summary['event_id'] for summary, _, _ in summaries)
    duplicate_ids = sorted(identity for identity, count in counts.items() if count > 1)
    for identity in duplicate_ids:
        issues.append(dict(kind='duplicate_document_event_id', event_id=identity,
                           source_document_numbers=[s['source_document_number']
                                                    for s, _, _ in summaries if s['event_id'] == identity]))

    unmatched, non_board = [], []
    groups = defaultdict(list)
    for summary, moment, document in summaries:
        if summary['document_form'] != 'board_resolution':
            non_board.append(summary)
            continue
        try:
            board = _board_date(document['numbered_fields'])
        except (TypeError, ValueError) as error:
            issue = dict(kind='unresolved_board_date_field', event_id=summary['event_id'],
                         source_document_number=summary['source_document_number'], reason=str(error))
            issues.append(issue)
            unmatched.append(dict(document=summary, issue=issue))
            continue
        key = summary['issuer'], board
        if key not in by_key:
            candidates = [c['case_id'] for c in issuer_cases[summary['issuer']]]
            issue = dict(kind=('possible_board_date_correction' if summary['explicitly_titled_revision']
                               else 'board_date_not_in_annual_snapshot'),
                         event_id=summary['event_id'], source_document_number=summary['source_document_number'],
                         issuer=summary['issuer'], reported_board_date=board.isoformat(),
                         same_issuer_candidate_case_ids=candidates, linkage_inferred=False)
            issues.append(issue)
            unmatched.append(dict(document=summary, issue=issue))
            continue
        groups[key].append((summary, moment))

    for key, annual_cases in by_key.items():
        retained = sorted(groups[key], key=lambda entry: (entry[1], entry[0]['sequence'],
                                                          entry[0]['event_id'],
                                                          entry[0]['source_document_number']))
        versions = []
        for number, (summary, _) in enumerate(retained):
            versions.append(dict(**summary, changes_from_previous=(
                _changes(retained[number - 1][0], summary) if number else [])))
        for case in annual_cases:
            case['versions'] = versions
            if not versions:
                issue = dict(kind='no_retained_board_record', case_id=case['case_id'])
                case['missing_initial_evidence'] = True
                case['issues'].append(issue)
                issues.append(issue)
                continue
            earliest = versions[0]
            case['earliest_retained_record'] = dict(
                event_id=earliest['event_id'], reported_datetime=earliest['reported_datetime'],
                sequence=earliest['sequence'], source_document_number=earliest['source_document_number'],
                subject=earliest['subject'], first_ever_publication_verified=False)
            if earliest['explicitly_titled_revision']:
                issue = dict(kind='missing_initial_evidence', case_id=case['case_id'],
                             earliest_retained_event_id=earliest['event_id'],
                             reason='Earliest retained board record is explicitly titled a correction or supplement')
                case['missing_initial_evidence'] = True
                case['issues'].append(issue)
                issues.append(issue)
            repeated = [v['event_id'] for v in versions if v['event_id'] in duplicate_ids]
            unmarked = [v for v in versions if not v['explicitly_titled_revision']]
            if repeated or len(unmarked) > 1:
                issue = dict(kind=('duplicate_identity_in_case' if repeated else 'multiple_unmarked_board_records'),
                             case_id=case['case_id'], event_ids=repeated or [v['event_id'] for v in unmarked])
                case['linkage_ambiguous'] = True
                case['issues'].append(issue)
                issues.append(issue)

    return dict(
        status='retained_board_key_chronology_replayed',
        annual_case_count=len(cases), cases=cases,
        cases_with_retained_board_records=sum(bool(c['versions']) for c in cases),
        cases_missing_initial_evidence=sum(c['missing_initial_evidence'] for c in cases),
        ambiguous_case_count=sum(c['linkage_ambiguous'] for c in cases),
        duplicate_document_ids=duplicate_ids, unmatched_board_documents=unmatched,
        non_board_documents=non_board, completion_linkage_status='not_inferred',
        issues=issues, unresolved_case_ids=[c['case_id'] for c in cases if c['issues']],
        earliest_retained_is_not_first_ever=True,
        historical_pit_verified=False, first_publication_time_verified=False,
        source_gate_passed=False, profit_edge_proven=False,
        outcome_based_case_exclusion=False,
    )
