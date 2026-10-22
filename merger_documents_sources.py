"""Known-form document retrieval after the unchanged eight-request discovery.

Only separately frozen requests use the existing two-worker source machinery.
The initial request copies the archived official form, with its declared button
update and the fixed issuer/year; JavaScript is never executed.
"""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qs
import zipfile

import frontier_sources
from source_checkpoint import readback


ROOT = Path('inputs/cash_merger_documents_20261022')
OUT = Path('deliverables/cash_merger_documents_20261022')
POLICY = Path('configs/cash_merger_documents_protocol_20261022.json')
QUERY_CONFIG = Path('configs/cash_merger_documents_query_sources_20261022.json')
SELECTION = OUT / 'selection.json'
FORM_OUT = Path('deliverables/cash_merger_current_followthrough_20261022')
FORM_MEMBER = 'raw/official_meeting_book_form.html'
FORM_ARCHIVE_SHA256 = '22c703e01eba0fc056718079a2838ca518ab8b90ac5354536b6c1f22667c7720'
FORM_BODY_SHA256 = '971a2e2bf71415a9a31321ba7498e51e4c93b427bd1c9599c6d673c449a656de'
REQUIRED_CHECKPOINT = FORM_OUT / 'checkpoint.json'
QUERY_URL = 'https://mopsov.twse.com.tw/mops/web/ajax_t57sb01_q5'


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def _bound_file(reference, path):
    body = path.read_bytes()
    if (not isinstance(reference, dict) or reference.get('path') != str(path)
            or reference.get('sha256') != _digest(body)):
        raise ValueError('Document phase configuration/selection binding drift')
    return body


class _Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == 'form':
            self.current = dict(attributes=fields, inputs=[])
            self.forms.append(self.current)
        elif tag == 'input' and self.current is not None and fields.get('name'):
            self.current['inputs'].append(fields)

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


def _prior_saved_count(policy):
    """Reconcile saved requests, including failures, to their retrieved bundles."""
    total, form_body = 0, None
    seen = set()
    for reference in policy['source_ledger']['prior_batches']:
        key = (reference['out'], reference['batch'])
        if key in seen:
            raise ValueError('Duplicate prior source batch in document ledger')
        seen.add(key)
        package, _ = readback(Path(reference['out']), reference['batch'])
        if package['sha256'] != reference['archive_sha256']:
            raise ValueError('Prior source archive ledger drift')
        with zipfile.ZipFile(package['retrieved']) as archive:
            request_body = archive.read('requests.json')
            requests = json.loads(request_body)['requests']
            results = json.loads(archive.read('raw/results.json'))
            records = results.get('requests')
            if (len(requests) != reference['requests'] or not isinstance(records, list)
                    or len(records) != len(requests)
                    or results.get('config_sha256') != _digest(request_body)
                    or [record.get('request') for record in records] != requests):
                raise ValueError('Prior saved-request count/transport ledger mismatch')
            total += len(requests)
            if key == (str(FORM_OUT), 'ebook_form'):
                if package['sha256'] != FORM_ARCHIVE_SHA256:
                    raise ValueError('Official form archive differs from the known source')
                form_body = archive.read(FORM_MEMBER)
    if form_body is None:
        raise ValueError('Known official form absent from the saved ledger')
    return total, form_body


def validate_query_plan():
    """Validate the known official form and fixed issuer/year without live IO."""
    policy = json.loads(POLICY.read_bytes())
    ledger = policy.get('source_ledger', {})
    if (policy.get('max_saved_requests') != 4 or policy.get('max_source_batches') != 4
            or ledger.get('completed_saved_requests') != 8
            or ledger.get('new_saved_request_ceiling') != 4
            or ledger.get('combined_request_ceiling') != 12
            or ledger.get('old_discovery_phases_retired') is not True):
        raise ValueError('Document phase must explicitly preserve eight plus four equals twelve')
    checkpoint = policy.get('prior_checkpoints', {}).get(str(REQUIRED_CHECKPOINT))
    if not isinstance(checkpoint, str) or not re.fullmatch(r'[0-9a-f]{64}', checkpoint):
        raise ValueError('Awaiting pinned completed discovery checkpoint')
    count, body = _prior_saved_count(policy)
    if count != 8 or _digest(body) != FORM_BODY_SHA256:
        raise ValueError('Known form body or eight saved discovery requests drifted')
    source = policy.get('source_form', {})
    expected_source = dict(out=str(FORM_OUT), batch='ebook_form',
                           archive_sha256=FORM_ARCHIVE_SHA256, member=FORM_MEMBER,
                           body_sha256=FORM_BODY_SHA256)
    if source != expected_source:
        raise ValueError('Official document query source locator drift')
    parser = _Form()
    parser.feed(body.decode('utf-8-sig', errors='strict'))
    forms = [form for form in parser.forms if form['attributes'].get('name') == 'form1']
    if len(forms) != 1:
        raise ValueError('Missing/ambiguous official document form')
    form = forms[0]
    fields = [(field['name'], field.get('value', '')) for field in form['inputs']]
    expected_fields = [('step', '1'), ('firstin', 'ture'), ('off', '1'), ('TYPEK', 'all'),
                       ('keyword4', ''), ('code1', ''), ('TYPEK2', ''), ('checkbtn', ''),
                       ('queryName', 'co_id'), ('inpuType', 'co_id'), ('co_id', ''), ('year', '')]
    if (form['attributes'].get('action') != '/mops/web/ajax_t57sb01_q5'
            or form['attributes'].get('method') != 'post' or fields != expected_fields
            or "document.form1.firstin.value='1';" not in body.decode('utf-8-sig')):
        raise ValueError('Official form action/fields/button declaration drift')
    selection = json.loads(_bound_file(policy.get('selection_manifest'), SELECTION))
    expected_selection = dict(source_form_sha256=FORM_BODY_SHA256, issuer='6674',
                              roc_year='115', book_type_filter=None,
                              query_filename='meeting_books_6674_115.html')
    if selection != expected_selection:
        raise ValueError('Document query issuer/year/book-type selection drift')
    reference = policy.get('batches', {}).get('query')
    cfg = json.loads(_bound_file(reference, QUERY_CONFIG))
    if (reference.get('requests') != 1
            or cfg.get('output_directory') != str(ROOT / 'raw_query')
            or cfg.get('allowed_hosts') != ['mopsov.twse.com.tw']
            or len(cfg.get('requests', [])) != 1):
        raise ValueError('Unexpected single-query document configuration')
    request = cfg['requests'][0]
    expected_query = {name: [value] for name, value in expected_fields}
    expected_query.update(firstin=['1'], co_id=['6674'], year=['115'])
    if (set(request) != {'filename', 'url', 'method', 'data'}
            or request['filename'] != selection['query_filename']
            or request['url'] != QUERY_URL or request['method'] != 'POST'
            or parse_qs(request['data'], keep_blank_values=True, strict_parsing=True) != expected_query):
        raise ValueError('Document query differs from the declared form and fixed issuer/year')
    return cfg


def _source_module():
    validate_query_plan()
    frontier_sources.ROOT = ROOT
    frontier_sources.OUT = OUT
    frontier_sources.POLICY = POLICY
    return frontier_sources


def plan(batch='query'):
    module = _source_module()
    result = module.plan(batch)
    if batch == 'attachments':
        validate_attachment_plan(result[1], result[3])
    return result


def validate_attachment_plan(cfg, freeze):
    """Bind both PDFs to the retrieved catalogue/form before native IO."""
    from cash_merger_document_catalogue import parse_catalogue, validate_download_requests
    from cash_merger_document_lookup import require_successful_query
    from tender_preflight import verified_records
    if freeze is None:
        raise ValueError('Attachments require a separately frozen source selection')
    batch = json.loads(Path(freeze).read_bytes())
    selection = json.loads(_bound_file(batch.get('selection_manifest'), OUT / 'attachments_selection.json'))
    source = selection['source_catalogue']
    if source.get('out') != str(OUT) or source.get('batch') != 'catalogue' or source.get('encoding') != 'big5':
        raise ValueError('Attachments must use the frozen local Big5 catalogue')
    package, _ = readback(OUT, 'catalogue')
    if package['sha256'] != source.get('archive_sha256'):
        raise ValueError('Selected catalogue archive differs')
    with zipfile.ZipFile(package['retrieved']) as archive:
        requests_body = archive.read('requests.json')
        results = json.loads(archive.read('raw/results.json'))
        if results['config_sha256'] != _digest(requests_body):
            raise ValueError('Archived catalogue request configuration differs')
        records = verified_records(json.loads(requests_body), results, lambda name: archive.read('raw/' + name))
        require_successful_query(records)
        member = 'raw/' + records[0]['request']['filename']
        if source.get('member') != member:
            raise ValueError('Selected catalogue member differs from saved request')
        full, _ = parse_catalogue(archive.read(member), archive.read(member + '.headers'))
    validate_download_requests(full, selection, cfg)


def acquire(batch='query'):
    plan(batch)
    return _source_module().acquire(batch)


def package(batch='query'):
    plan(batch)
    return _source_module().package(batch)


def verify(batch='query'):
    plan(batch)
    return _source_module().verify(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='query')
    args = parser.parse_args()
    globals()[args.stage](args.batch)
