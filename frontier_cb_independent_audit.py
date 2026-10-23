"""Replay independent human references; interpretation and eligibility stay unverified."""
import argparse
import json
from pathlib import Path

from frontier_cb_pdf_replay import audit, ARCHIVE_SHA256, compact, require
from research_runtime import atomic_json, sha256

OUT = Path('deliverables/frontier_cb_documents_20261023')


def verify_independent(annotation, fulls, summaries):
    require(annotation['source_archive']['sha256'] == ARCHIVE_SHA256,
            'Independent annotation archive differs')
    for key in ('source_gate_passed', 'cash_claim_source_gate_passed', 'historical_pit_verified',
                'profit_edge_proven', 'orders_authorized'):
        require(annotation.get(key) is False, 'Independent annotation cannot promote gates')
    require(annotation.get('valid_prospective_signal_date') is None, 'Unexpected signal date')
    docs = {d['filename']: d for d in summaries}
    texts = {d['filename']: d for d in fulls}
    cases = annotation['cases']
    require(len(cases) == 3 and len({c['bond_code'] for c in cases}) == 3
            and {c['bond_code'] for c in cases} == {d['bond_code'] for d in summaries},
            'Independent annotation must preserve three controls')
    anchors = images = 0
    pages = {}
    for case in cases:
        source = case['source_pdf']
        name = source['member'].removeprefix('raw/')
        require(source['member'] == 'raw/' + name and name in docs, 'Unknown independent PDF')
        doc = docs[name]
        require(case['bond_code'] == doc['bond_code'] and source['sha256'] == doc['body_sha256']
                and source['size_bytes'] == doc['size_bytes']
                and source['physical_pages'] == doc['extracted_page_count'], 'Independent PDF identity drift')
        require(source['official_request'] == dict(filename=name, url=doc['url'], method='GET'),
                'Independent request URL drift')
        times = doc['actual_source_timestamps']
        require(source['request_started_at_utc'] == times['request_started_at']
                and source['observed_at_utc'] == times['observed_at'], 'Independent UTC source time differs')
        require(case.get('cash_claim_source_gate_passed') is False
                and case.get('current_exercise_eligibility_verified') is False
                and case.get('actual_net_proceeds_verified') is False
                and case.get('signal_valid') is False, 'Independent case gate promoted')
        require(case['notes'], 'Independent case lacks findings')
        pages[name] = [dict(physical_page=n, text_sha256=p['text_sha256'])
                       for n, p in enumerate(doc['pages'], 1)]
        for note in case['notes']:
            require(note.get('evidence'), 'Independent finding lacks references')
            for ref in note['evidence']:
                n = ref['physical_page']
                require(type(n) is int and 1 <= n <= len(doc['pages']), 'Independent page outside PDF')
                require(ref['archive_member'] == source['member'] and ref['pdf_sha256'] == doc['body_sha256']
                        and ref['page_text_sha256'] == doc['pages'][n-1]['text_sha256'],
                        'Independent page/PDF hash drift')
                mode = ref['evidence_mode']
                if mode == 'pypdf_extracted_text':
                    quotes = ref['exact_anchors']
                    text = texts[name]['pages'][n-1]['text']
                    require(quotes and all(isinstance(q, str) and compact(q)
                            and compact(q) in compact(text) for q in quotes), 'Independent exact anchor absent')
                    anchors += len(quotes)
                elif mode == 'embedded_image_manually_viewed':
                    image = ref['embedded_image']
                    require(ref['exact_anchors'] == [] and ref['manual_view_performed'] is True
                            and ref['transcription_automatically_verified'] is False
                            and ref['manual_visual_transcriptions'], 'Visual reading cannot become extracted text')
                    matches = [im for im in doc['image_refs'] if im['physical_page'] == n
                               and im['name'] == image['name'] and im['data_sha256'] == image['sha256']]
                    require(len(matches) == 1, 'Independent image bytes/name/page differ')
                    images += 1
                else:
                    raise ValueError('Unsupported independent evidence mode')
    require(anchors == annotation['validation']['extracted_text_anchor_count'], 'Independent declared anchor count differs')
    return dict(status='independent_human_reference_bindings_verified', documents=3,
        text_anchors_verified=anchors, cited_image_bytes_references_verified=images,
        physical_page_hashes=pages, source_archive_sha256=ARCHIVE_SHA256,
        semantic_interpretation_automatically_verified=False, visual_transcriptions_automatically_verified=False,
        printed_page_labels_and_image_dimensions_automatically_verified=False,
        source_gate_passed=False, cash_claim_source_gate_passed=False, historical_pit_verified=False,
        profit_edge_proven=False, valid_prospective_signal_date=None, orders_authorized=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotation', type=Path, default=OUT/'put_terms_independent_annotation.json')
    args = parser.parse_args()
    fulls, result = audit()
    answer = verify_independent(json.loads(args.annotation.read_bytes()), fulls, result['documents'])
    answer.update(annotation_path=str(args.annotation), annotation_sha256=sha256(args.annotation),
                  verifier_sha256=sha256(Path(__file__)))
    atomic_json(OUT/'independent_annotation_audit.json', answer)
    print(json.dumps(dict(documents=3, text_anchors=answer['text_anchors_verified'],
                          image_refs=answer['cited_image_bytes_references_verified'], source_gate_passed=False)))
