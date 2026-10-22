"""Hash-bound pending-case replay; no source acquisition or status promotion."""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

from cash_merger_claim_clock import evaluate_claim, REQUIRED_FACTS
from research_runtime import atomic_json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError('Nonfinite JSON constant: ' + value)


def _float(value):
    result = float(value)
    require(math.isfinite(result), 'Nonfinite JSON number')
    return result


def decode(body):
    return json.loads(body.decode('utf-8-sig', errors='strict'), object_pairs_hook=_object,
                      parse_constant=_bad_constant, parse_float=_float)


def bound(reference):
    require(isinstance(reference, dict) and isinstance(reference.get('path'), str)
            and isinstance(reference.get('sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', reference['sha256']), 'Expected exact path/SHA reference')
    body = Path(reference['path']).read_bytes()
    require(digest(body) == reference['sha256'], 'Frozen reference drift: ' + reference['path'])
    return body


def validate_citation(entry, annotations, label):
    require(isinstance(entry, dict) and entry.get('annotation_path') in annotations,
            'Unbound source-rule annotation: ' + label)
    reference, annotation = annotations[entry['annotation_path']]
    require(entry.get('annotation_sha256') == reference['sha256'],
            'Source-rule annotation SHA differs: ' + label)
    pages, hashes, pdfs = (entry.get(key) for key in ('physical_pages', 'page_text_sha256', 'pdf_sha256'))
    require(isinstance(pages, list) and bool(pages) and all(type(page) is int and page > 0 for page in pages)
            and isinstance(hashes, list) and isinstance(pdfs, list)
            and len(pages) == len(hashes) == len(pdfs)
            and all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes + pdfs),
            'Source-rule page/PDF/hash shape differs: ' + label)
    terms = annotation.get('terms') if isinstance(annotation, dict) else None
    require(isinstance(terms, list) and isinstance(entry.get('topic'), str),
            'Source-rule topic must refer to bound annotation terms: ' + label)
    matches = [term for term in terms if isinstance(term, dict) and term.get('topic') == entry['topic']]
    require(len(matches) == 1 and isinstance(matches[0].get('evidence'), list),
            'Missing/ambiguous bound source-rule topic: ' + label)
    allowed = {(row.get('pdf_sha256'), row.get('pdf_page_number'), row.get('page_text_sha256'))
               for row in matches[0]['evidence'] if isinstance(row, dict)}
    require(all((pdf, page, text) in allowed for pdf, page, text in zip(pdfs, pages, hashes, strict=True)),
            'Source-rule topic/PDF/page/text SHA not present in bound annotation: ' + label)


def validate_pending_case(case):
    require(isinstance(case, dict) and case.get('actual_inputs_state') == 'pending',
            'This frozen replay requires an explicitly pending actual case')
    require(isinstance(case.get('facts'), dict) and set(case['facts']) == set(REQUIRED_FACTS),
            'Pending case must preserve every required actual-input gap')
    for name, fact in case['facts'].items():
        require(isinstance(fact, dict) and fact.get('value') is None
                and (fact.get('verified') is None or fact.get('verified') is False),
                'Pending actual case cannot promote known/provisional facts: ' + name)
    require(case.get('business_calendar') is None and case.get('written_extension') is None,
            'Pending calendar or extension cannot be silently supplied')
    observation = case['source_observation_taipei']
    require(isinstance(observation, str), 'Source observation timestamp must be explicit')
    timestamp = dt.datetime.fromisoformat(observation)
    require(timestamp.tzinfo is not None and timestamp.utcoffset() == dt.timedelta(hours=8),
            'Source observation must retain the explicit Taipei UTC+08 offset')
    require(case.get('evening_current_status_verified') is False,
            'Morning source observation must not become evening current status')
    annotations = case.get('annotation_references')
    require(isinstance(annotations, list) and bool(annotations), 'Source annotations must be explicitly bound')
    known = {}
    for reference in annotations:
        body = bound(reference)
        annotation = decode(body)  # Exact membership still is not semantic approval.
        require(reference['path'] not in known, 'Duplicate annotation reference')
        known[reference['path']] = (reference, annotation)
    for name, fact in case['facts'].items():
        evidence = fact.get('evidence')
        require(isinstance(evidence, list) and bool(evidence), 'Pending gap needs source-rule citation: ' + name)
        for entry in evidence:
            validate_citation(entry, known, name)
    provisional = case.get('provisional_terms')
    if provisional is not None:
        require(isinstance(provisional, dict) and isinstance(provisional.get('evidence'), list)
                and bool(provisional['evidence']), 'Provisional context requires bound source-rule evidence')
        for entry in provisional['evidence']:
            validate_citation(entry, known, 'provisional_terms')


def replay(protocol_path):
    protocol_body = Path(protocol_path).read_bytes()
    protocol = decode(protocol_body)
    freeze = decode(Path(protocol['freeze_path']).read_bytes())
    require(freeze['protocol_sha256'] == digest(protocol_body), 'Frozen claim protocol drift')
    prior = protocol['prior_checkpoints']
    require(isinstance(prior, dict) and bool(prior), 'At least one pinned prior checkpoint is required')
    member_count = 0
    for path, expected in prior.items():
        checkpoint = decode(bound(dict(path=path, sha256=expected)))
        members = checkpoint['files']
        require(isinstance(members, dict) and bool(members), 'Pinned checkpoint lacks frozen members')
        for member, wanted in members.items():
            bound(dict(path=member, sha256=wanted))
            member_count += 1
    terms_body = bound(protocol['terms_audit'])
    decode(terms_body)
    case_body = bound(protocol['case_config'])
    case = decode(case_body)
    validate_pending_case(case)
    result = evaluate_claim(case)
    require(result['calculation_ready'] is False and result['cash'] is None and result['payment_date'] is None,
            'Pending actual case unexpectedly produced a payable claim')
    return dict(status='frozen_pending_actual_case_replayed', case_id=case['case_id'],
        protocol_sha256=digest(protocol_body), case_config_sha256=digest(case_body),
        terms_audit_sha256=digest(terms_body), terms_audit_path=protocol['terms_audit']['path'],
        prior_checkpoints=prior, frozen_prior_member_checks=member_count,
        source_observation_taipei=case['source_observation_taipei'],
        observation_scope=case['observation_scope'], evening_current_status_verified=False,
        source_hashes=case['source_hashes'], gaps=result['reasons'], claim=result,
        hash_validation_is_semantic_approval=False, source_acquisition_performed=False,
        user_holdings_requested=False, source_gate_passed=False, cash_claim_source_gate_passed=False,
        historical_pit_verified=False, profit_edge_proven=False, valid_prospective_signal_date=None,
        market_prices_or_returns_read=False, orders_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.protocol)
    atomic_json(args.output, result)
    print(json.dumps(dict(output=str(args.output), cash=result['claim']['cash'],
                          payment_date=result['claim']['payment_date'], gap_count=len(result['gaps']))))


if __name__ == '__main__':
    main()
