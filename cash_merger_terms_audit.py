"""Independently replay PDF/page/image bindings in the two human term readings.

This audit verifies saved evidence and time-zone labels. It does not verify the
legal interpretation, image authenticity, current deal status or an entry gate.
No production document parser, network client or market-price reader is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
import zipfile

from lxml import html
import PIL
import pypdf
from pypdf import PdfReader


OUT = Path('deliverables/cash_merger_pdf_transfer_20261022')
ARCHIVE_SHA256 = '8dfc037a92837c34536f0b65bd488d47d47ceb92992939dfeb5cfa408b1f4dad'
PDFS = {
    'raw/2026_6674_20261109F02.pdf': ('32aed2a5102f40a7a28fa35f38df7c50d73fc7f9c529d7cb5962a90541402134', 1187933, 61),
    'raw/2026_6674_20261109F13.pdf': ('bb5404d58693eed814a9c578cae296c53eb8321042b14e03d0856fe7d4e59e4c', 190821, 4),
}
CATALOGUE_ARCHIVE_SHA256 = '2dc775a28540045d30bcf244209c0d07bb2ea8b8aac06bd2e7372f468816f406'
CATALOGUE_BODY_SHA256 = 'd9f2d635e7e7263997afdbf974ea300a1c0d24b50c6a4235d20e4b5f51fb06dd'
TAIPEI = ZoneInfo('Asia/Taipei')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def compact(value):
    return re.sub(r'\s+', '', value)


def strict_json(body):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError('Nonfinite JSON value: '+value)
    return json.loads(body, object_pairs_hook=pairs, parse_constant=bad_constant)


def verify_archive(body: bytes, expected_sha: str) -> dict[str, bytes]:
    require(sha256(body) == expected_sha, 'Archive SHA mismatch')
    with zipfile.ZipFile(BytesIO(body)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and archive.testzip() is None,
                'Archive duplicate member or CRC failure')
        require('manifest.json' in names, 'Archive manifest absent')
        manifest = strict_json(archive.read('manifest.json'))
        require(isinstance(manifest, dict) and manifest
                and set(names) == set(manifest) | {'manifest.json'}, 'Archive manifest population mismatch')
        members = {name: archive.read(name) for name in names}
        for name, expected in manifest.items():
            require(isinstance(name, str) and not Path(name).is_absolute() and '..' not in Path(name).parts,
                    'Unsafe archive member')
            require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected)
                    and sha256(members[name]) == expected, 'Archive inner member SHA mismatch')
    return members


def extract_document(body: bytes, member: str, metadata: dict, image_pages=()) -> dict:
    require(body.startswith(b'%PDF-'), 'Saved body is not a PDF')
    reader = PdfReader(BytesIO(body))
    require(not reader.is_encrypted, 'Encrypted PDF is not independently replayed')
    selected = set(image_pages)
    require(all(type(page) is int and 1 <= page <= len(reader.pages) for page in selected),
            'Image page outside PDF')
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ''
        images = [dict(name=item.name, sha256=sha256(item.data),
                       width=item.image.width, height=item.image.height)
                  for item in page.images] if number in selected else []
        pages.append(dict(text=text, text_sha256=sha256(text.encode('utf-8')), images=images))
    return dict(member=member, sha256=sha256(body), size_bytes=len(body),
                physical_pages=len(pages), pages=pages, metadata=metadata)


def _page(doc, number):
    require(type(number) is int and 1 <= number <= doc['physical_pages'], 'Physical page outside bound PDF')
    page = doc['pages'][number-1]
    require(page['text_sha256'] == sha256(page['text'].encode('utf-8')), 'Extracted page text hash drift')
    return page


def _printed_page(page, label):
    if label is None:
        return
    require(isinstance(label, (int, str)) and not isinstance(label, bool)
            and re.fullmatch(r'[0-9]+', str(label)), 'Invalid printed page label')
    pattern = re.compile(r'-?'+re.escape(str(label))+r'-?')
    require(any(pattern.fullmatch(compact(line)) for line in page['text'].splitlines()),
            'Printed page label absent from its bound physical page')


def _anchors(page, quotes):
    require(isinstance(quotes, list) and quotes
            and all(isinstance(quote, str) and compact(quote) for quote in quotes), 'Missing annotation anchors')
    for quote in quotes:
        require(compact(quote) in compact(page['text']), 'Annotation anchor absent or numeric/punctuation drift')
    return len(quotes)


def _utc(value):
    require(isinstance(value, str), 'Actual UTC timestamp must be text')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0),
            'Timestamp labelled UTC has a non-UTC/missing offset')
    return parsed


def _source_time(doc):
    meta = doc['metadata']
    require(meta.get('sha256') == doc['sha256'] and meta.get('size_bytes') == doc['size_bytes']
            and type(meta.get('http_status')) is int and meta['http_status'] == 200
            and type(meta.get('exit_code')) is int and meta['exit_code'] == 0
            and meta['request']['filename'] == Path(doc['member']).name,
            'PDF transport/body metadata mismatch')
    start, observed = _utc(meta['request_started_at']), _utc(meta['observed_at'])
    require(start <= observed, 'Observation precedes its request')
    return start, observed


def verify_annotations(documents: dict, semantic: dict, terms: dict, *,
                       archive_sha256: str, catalogue: dict | None = None) -> dict:
    """Verify every supplied page/anchor/image reference, not its interpretation."""
    require(documents and all(key == doc['member'] for key, doc in documents.items()), 'Ambiguous PDF mapping')
    require(terms.get('historical_pit_verified', False) is False
            and semantic.get('research_state', {}).get('historical_pit_verified', False) is False,
            'Human readings must not promote source labels to verified PIT')
    require(semantic['source_archive']['sha256'] == terms['source_archive_sha256'] == archive_sha256,
            'Annotation archive binding mismatch')
    semantic_sources = {item['member']: item for item in semantic['source_documents']}
    term_sources = {item['archive_member']: item for item in terms['source_files']}
    require(len(semantic_sources) == len(semantic['source_documents'])
            and len(term_sources) == len(terms['source_files'])
            and set(semantic_sources) == set(term_sources) == set(documents), 'Annotation PDF population mismatch')
    timestamps = []
    for member, doc in documents.items():
        first, second = semantic_sources[member], term_sources[member]
        start, observed = _source_time(doc)
        require(first['sha256'] == second['pdf_sha256'] == doc['sha256']
                and first['size_bytes'] == doc['size_bytes']
                and first['physical_pages'] == second['pdf_page_count'] == doc['physical_pages']
                and second['archive_sha256'] == archive_sha256
                and second['filename'] == Path(member).name, 'Annotation source PDF SHA/size/page binding drift')
        require(first['official_request_url'] == doc['metadata']['request']['url'], 'Source request URL drift')
        require(_utc(first['request_started_at_utc']) == _utc(second['actual_request_started_at_utc']) == start
                and _utc(first['observed_at_utc']) == _utc(second['actual_observed_at_utc']) == observed,
                'UTC timestamp annotation drift')
        local = observed.astimezone(TAIPEI)
        require(first['observation_window_taipei'] == local.strftime('%Y-%m-%d %H:%M'), 'Taipei minute-window drift')
        require(second['actual_observation_taipei'] == local.isoformat(timespec='seconds'),
                'Taipei timestamp is not the source UTC instant converted to UTC+08')
        require(second.get('reported_upload_is_first_public_availability_verified') is False,
                'Reported upload label must not be promoted to verified PIT')
        if 'catalogue_reported_upload_taipei' in second:
            require(catalogue is not None and catalogue['upload_labels'].get(second['filename'])
                    == second['catalogue_reported_upload_taipei'], 'Reported upload label not bound to catalogue')
        timestamps.append(dict(member=member,actual_observed_at_utc=doc['metadata']['observed_at'],
                               actual_observed_at_taipei=local.isoformat(),reported_label_is_not_pit=True))
    if 'catalogue_source' in terms:
        require(catalogue is not None and terms['catalogue_source'] == catalogue['source_reference'],
                'Catalogue source reference mismatch')
    if 'reviewed_at_utc' in semantic:
        require(_utc(semantic['reviewed_at_utc']) >= max(_source_time(doc)[1] for doc in documents.values()),
                'Human review timestamp precedes the saved source observation')
    semantic_count = terms_count = negative_pages = 0
    ids = []
    for note in semantic['readings']:
        ids.append(note['id'])
        evidence = note.get('evidence')
        require(isinstance(evidence, list) and evidence, 'Semantic reading lacks evidence')
        for item in evidence:
            require(item['source_pdf'] in documents, 'Semantic reference to unknown PDF')
            doc = documents[item['source_pdf']]
            require(item['source_pdf_sha256'] == doc['sha256'], 'Semantic PDF SHA mismatch')
            page = _page(doc, item['physical_page'])
            require(item['extracted_page_text_sha256'] == page['text_sha256'], 'Semantic page text SHA mismatch')
            _printed_page(page, item.get('printed_page'))
            semantic_count += _anchors(page, [item['exact_anchor']])
    require(ids and len(ids) == len(set(ids)), 'Missing/duplicate semantic reading IDs')
    require(semantic['validation']['anchor_count'] == semantic_count, 'Semantic declared anchor count drift')
    topics = []
    by_filename = {Path(member).name: doc for member, doc in documents.items()}
    for note in terms['terms']:
        topics.append(note['topic'])
        evidence = note.get('evidence')
        require(isinstance(evidence, list) and evidence, 'Term reading lacks evidence')
        for item in evidence:
            require(item['filename'] in by_filename, 'Term reference to unknown PDF')
            doc = by_filename[item['filename']]
            require(item['pdf_sha256'] == doc['sha256'], 'Term PDF SHA mismatch')
            page = _page(doc, item['pdf_page_number'])
            require(item['page_text_sha256'] == page['text_sha256'], 'Term page text SHA mismatch')
            _printed_page(page, item.get('printed_page_label'))
            terms_count += _anchors(page, item['exact_anchors'])
        if 'negative_finding_scope' in note:
            scope = note['negative_finding_scope']
            require(scope['filename'] in by_filename, 'Negative finding references unknown PDF')
            doc = by_filename[scope['filename']]
            refs = scope['page_text_sha256s']
            require([ref['pdf_page_number'] for ref in refs] == scope['pdf_pages']
                    and len(scope['pdf_pages']) == len(set(scope['pdf_pages'])) and refs,
                    'Negative finding page coverage drift')
            for item in refs:
                require(_page(doc,item['pdf_page_number'])['text_sha256'] == item['page_text_sha256'],
                        'Negative finding page SHA drift')
                negative_pages += 1
    require(topics and len(topics) == len(set(topics)), 'Missing/duplicate human term topics')
    images_verified = 0
    if 'signature_visual_review' in semantic:
        visual = semantic['signature_visual_review']
        require(visual['source_pdf'] in documents, 'Image reference to unknown PDF')
        doc = documents[visual['source_pdf']]
        require(visual['source_pdf_sha256'] == doc['sha256'], 'Image PDF SHA mismatch')
        page = _page(doc, visual['physical_page'])
        _printed_page(page, visual.get('printed_page'))
        images = {item['name']: item for item in page['images']}
        refs = visual['images']
        require(len(images) == len(page['images']) == visual['embedded_images_observed'] == len(refs)
                and len({ref['xobject_export_name'] for ref in refs}) == len(refs), 'Image reference coverage/duplicates drift')
        for ref in refs:
            actual = images.get(ref['xobject_export_name'])
            require(actual is not None and ref['pypdf_exported_image_sha256'] == actual['sha256']
                    and ref['width'] == actual['width'] and ref['height'] == actual['height'], 'Image hash/dimensions drift')
            images_verified += 1
    return dict(semantic_readings=len(ids),semantic_anchors=semantic_count,terms_readings=len(topics),
                terms_anchors=terms_count,negative_finding_pages=negative_pages,signature_images=images_verified,
                timestamp_bindings=timestamps,all_evidence_bindings_verified=True,
                reported_upload_labels_are_not_verified_pit=True,semantic_interpretation_automatically_verified=False,
                source_gate_passed=False,cash_claim_source_gate_passed=False,historical_pit_verified=False,
                current_execution_gate_passed=False,profit_edge_proven=False,valid_prospective_signal_date=None)


def _readback_members(root, out, batch, expected):
    package = strict_json((root/out/(batch+'_package.json')).read_bytes())
    transfer = strict_json((root/Path(package['transfer_receipt'])).read_bytes())
    require(package['sha256'] == transfer['sha256'] == expected and transfer.get('roundtrip_verified') is True,
            'Missing pinned successful archive readback')
    members = verify_archive((root/Path(package['retrieved'])).read_bytes(),expected)
    require(package['manifest_files'] == len(members)-1, 'Package manifest count drift')
    return members,package


def audit(root: Path | str = '.') -> dict:
    root = Path(root)
    members,package = _readback_members(root,OUT,'files',ARCHIVE_SHA256)
    require(len(members)-1 == 9, 'Expected PDF archive manifest differs')
    documents = {}
    for member,(expected,size,pages) in PDFS.items():
        require(sha256(members[member]) == expected and len(members[member]) == size, 'Pinned PDF bytes drift')
        documents[member] = extract_document(members[member],member,strict_json(members[member+'.meta.json']),
                                              image_pages=(32,) if member.endswith('F02.pdf') else ())
        require(documents[member]['physical_pages'] == pages, 'Pinned PDF page count drift')
    catalogue_members,_ = _readback_members(root,Path('deliverables/cash_merger_documents_20261022'),
                                            'catalogue',CATALOGUE_ARCHIVE_SHA256)
    catalogue_name = 'raw/company6674_year115_catalogue.html'
    body = catalogue_members[catalogue_name]
    require(sha256(body) == CATALOGUE_BODY_SHA256, 'Pinned catalogue body drift')
    text = body.decode('big5',errors='strict')
    require(re.search(r'charset\s*=\s*big5',text,re.I), 'Missing catalogue Big5 declaration')
    labels = {}
    for row in html.fromstring(text).xpath('//tr'):
        cells = row.xpath('./td')
        if len(cells) == 11 and cells[0].text_content().strip() == '6674':
            name = cells[7].text_content().strip()
            require(name not in labels, 'Ambiguous catalogue filename')
            labels[name] = cells[9].text_content().strip()
    catalogue = dict(source_reference=dict(archive_sha256=CATALOGUE_ARCHIVE_SHA256,member=catalogue_name,
                         body_sha256=CATALOGUE_BODY_SHA256,encoding='big5'),upload_labels=labels)
    semantic_body = (root/OUT/'contract_semantic_review.json').read_bytes()
    terms_body = (root/OUT/'notice_or_contract_terms_annotation.json').read_bytes()
    result = verify_annotations(documents,strict_json(semantic_body),strict_json(terms_body),
                                  archive_sha256=ARCHIVE_SHA256,catalogue=catalogue)
    result.update(schema_version=1,status='saved_annotation_page_anchor_image_and_timezone_bindings_verified',
                  source_archive=dict(path=package['retrieved'],sha256=ARCHIVE_SHA256,crc_verified=True,manifest_files=9),
                  annotation_sha256s=dict(contract_semantic_review=sha256(semantic_body),
                                           notice_or_contract_terms_annotation=sha256(terms_body)),
                  runtime=dict(pypdf=pypdf.__version__,Pillow=PIL.__version__),
                  all_pdf_page_text_sha256s={member:[dict(physical_page=n,text_sha256=page['text_sha256'])
                                                   for n,page in enumerate(doc['pages'],1)]
                                                for member,doc in documents.items()},
                  meaning='Evidence bindings and source observation instants only; human reading, signature authenticity, deal completion and PIT are not promoted.')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root',default='.')
    parser.add_argument('--output',default=str(OUT/'terms_audit.json'))
    args = parser.parse_args()
    result = audit(args.root)
    dest = Path(args.output)
    if not dest.is_absolute():
        dest = Path(args.root)/dest
    dest.parent.mkdir(parents=True,exist_ok=True)
    pending = dest.with_suffix(dest.suffix+'.pending')
    pending.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    pending.replace(dest)
    print(json.dumps({key:result[key] for key in ('status','semantic_anchors','terms_anchors','signature_images',
                                                'negative_finding_pages','source_gate_passed')},ensure_ascii=False))
