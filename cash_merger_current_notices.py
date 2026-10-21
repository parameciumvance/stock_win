"""Replay the three frozen followthrough notices before considering any link.

No link is executed, fetched, guessed or treated as a contractual claim. Original
bodies remain in the source archive; complete descriptions and every href/src
occurrence, including duplicate and non-HTTP values, stay in ignored inputs.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import zipfile

from merger_document import parse_document
import merger_current_followthrough_sources
from research_runtime import atomic_json, sha256
from tender_preflight import verified_records

ROOT = Path('inputs/cash_merger_current_followthrough_20261022')
OUT = Path('deliverables/cash_merger_current_followthrough_20261022')
_ATTR = re.compile(r'''\s*([^\s/>=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]*)))?''')


def require(condition, message):
    if not condition:
        raise ValueError(message)


class _Pointers(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pointers = []

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        opening = re.match(r'<\s*[^\s/>]+', raw)
        tokens = list(_ATTR.finditer(raw, opening.end())) if opening else []
        # Record exact attribute source literals separately from HTML decoding.
        require([match[1].lower() for match in tokens] == [name for name, _ in attrs],
                'Cannot audit original href/src attribute tokenization')
        line, column = self.getpos()
        for index, ((name, value), token) in enumerate(zip(attrs, tokens, strict=True)):
            if name not in ('href', 'src'):
                continue
            self.pointers.append(dict(occurrence=len(self.pointers) + 1, tag=tag, attribute=name,
                attribute_position=index, value=value,
                source_literal=next((item for item in token.groups()[1:] if item is not None), None),
                html_line=line, html_column=column, raw_start_tag=raw,
                resolved_url=None, fetch_authorized=False))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def extract_pointers(body: bytes) -> list[dict]:
    """Return every actual href/src occurrence; do not resolve relative links."""
    require(isinstance(body, bytes), 'Saved HTML must be original bytes')
    parser = _Pointers()
    parser.feed(body.decode('utf-8-sig', errors='strict'))
    parser.close()
    return parser.pointers


def replay_notices(selection, bodies):
    rows = selection['rows']
    require(isinstance(rows, list) and len(rows) == 3, 'Expected exactly the three frozen notices')
    ids, names = [r['event_id'] for r in rows], [r['new_filename'] for r in rows]
    require(len(set(ids)) == len(set(names)) == 3 and set(names) == set(bodies),
            'Notice identity/body population differs')
    full = []
    for row in rows:
        name, original = row['new_filename'], row['index_original_fields']
        require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', name)
                and name not in ('.', '..'), 'Unsafe original notice filename')
        require(original['COMPANY_ID'] == '6674' and original['AN_CODE'] in ('M17', 'M99'),
                'Notice selection differs from target meeting/status categories')
        body = bodies[name]
        document = parse_document(body, original)
        reported = document['reported_datetime']
        event_id = (original['AN_CODE'] + ':' + document['issuer'] + ':' + reported[:10]
                    + ':' + original['CTIME'].replace(':', '') + ':' + str(document['sequence']))
        require(event_id == row['event_id'], 'Selected notice event identity differs from saved document')
        full.append(dict(event_id=event_id, filename=name, index_original_fields=original,
                         disposition=None, pointers=extract_pointers(body), **document))
    summary = dict(status='three_frozen_notice_identities_and_declared_pointers_replayed_terms_unqualified',
        document_count=3, all_selected_original_identities_verified=True,
        documents=[{key: value for key, value in doc.items()
                    if key not in ('description', 'raw_metadata', 'index_original_fields', 'pointers')}
                   | dict(pointers=[{key: value for key, value in pointer.items() if key != 'raw_start_tag'}
                                    for pointer in doc['pointers']]) for doc in full],
        pointer_count=sum(len(doc['pointers']) for doc in full),
        all_href_src_occurrences_preserved=True, linked_documents_acquired=False,
        pointer_resolution_performed=False, transaction_disposition=None,
        current_transaction_status_verified=False, current_tradability_verified=False,
        contractual_cash_claim_verified=False, notice_window_verified=False, payment_date_verified=False,
        source_gate_passed=False, cash_claim_source_gate_passed=False, historical_pit_verified=False,
        first_publication_time_verified=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, market_prices_or_returns_read=False, orders_authorized=False)
    return full, summary


def require_successful_notices(records):
    require(len(records) == 3 and all(type(r.get('http_status')) is int and r['http_status'] == 200
            and type(r.get('exit_code')) is int and r['exit_code'] == 0 for r in records),
            'All three notices require HTTP200 and exit0; failed transport is archived evidence only')


def run():
    module = merger_current_followthrough_sources._source_module()
    requests_path, requests_cfg, _, freeze = merger_current_followthrough_sources.plan('notices')
    cfg = json.loads(module.POLICY.read_text())
    ref = cfg['selection_manifest']
    require(sha256(ref['path']) == ref['sha256'], 'Frozen notice selection differs')
    selection = json.loads(Path(ref['path']).read_text())
    package, transfer = module.archived('notices', requests_path, freeze)
    with zipfile.ZipFile(package['retrieved']) as archive:
        results = json.loads(archive.read('raw/results.json'))
        require(results['config_sha256'] == sha256(requests_path), 'Archived notice configuration differs')
        records = verified_records(requests_cfg, results, lambda name: archive.read('raw/' + name))
        require_successful_notices(records)
        request_map = {r['filename']: r for r in requests_cfg['requests']}
        require(len(request_map) == 3 and set(request_map) == {r['new_filename'] for r in selection['rows']},
                'Selected notice filenames differ from exact request population')
        for row in selection['rows']:
            require(request_map[row['new_filename']]['url'] == row['index_original_fields']['HYPERLINK'],
                    'Requested notice URL differs from selected original pointer')
        bodies = {name: archive.read('raw/' + name) for name in request_map}
    full, summary = replay_notices(selection, bodies)
    summary.update(protocol_sha256=sha256(module.POLICY), selection_sha256=ref['sha256'],
                   request_config_sha256=sha256(requests_path),
                   source_index_archive_sha256=cfg['source_index']['archive_sha256'],
                   source_index_body_sha256=cfg['source_index']['body_sha256'],
                   archive=dict(sha256=package['sha256'], manifest_files=package['manifest_files'], backup=transfer))
    atomic_json(ROOT / 'notices_full.json', full)
    atomic_json(OUT / 'notices_replay.json', summary)


if __name__ == '__main__':
    run()
