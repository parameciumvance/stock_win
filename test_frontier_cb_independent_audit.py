"""Independent reference tamper checks with synthetic PDF bytes."""
from copy import deepcopy
import unittest
from frontier_cb_independent_audit import verify_independent
from frontier_cb_pdf_replay import replay_terms, ARCHIVE_SHA256
from test_frontier_cb_pdf_replay import fixture


def references():
    controls, bodies, records, shas = fixture()
    for r in records:
        r.update(request_started_at='2026-10-23T01:00:00+00:00', observed_at='2026-10-23T01:00:01+00:00')
    fulls, docs = replay_terms(controls, bodies, records, shas)
    a = dict(source_archive=dict(sha256=ARCHIVE_SHA256), cases=[],
             source_gate_passed=False, cash_claim_source_gate_passed=False,
             historical_pit_verified=False, profit_edge_proven=False, orders_authorized=False,
             valid_prospective_signal_date=None, validation=dict(extracted_text_anchor_count=3))
    for d in docs:
        n=d['filename']; t=d['actual_source_timestamps']; im=d['image_refs'][0]
        ref=dict(archive_member='raw/'+n, pdf_sha256=d['body_sha256'], physical_page=1,
                 page_text_sha256=d['pages'][0]['text_sha256'],
                 evidence_mode='pypdf_extracted_text', exact_anchors=['conditional terms'])
        visual=dict(ref, evidence_mode='embedded_image_manually_viewed', exact_anchors=[],
                    manual_view_performed=True, transcription_automatically_verified=False,
                    manual_visual_transcriptions=['synthetic red pixel'],
                    embedded_image=dict(name=im['name'],sha256=im['data_sha256']))
        a['cases'].append(dict(bond_code=d['bond_code'],
            source_pdf=dict(member='raw/'+n, sha256=d['body_sha256'], size_bytes=d['size_bytes'],
                physical_pages=d['extracted_page_count'], official_request=dict(filename=n,url=d['url'],method='GET'),
                request_started_at_utc=t['request_started_at'],observed_at_utc=t['observed_at']),
            notes=[dict(evidence=[ref,visual])], cash_claim_source_gate_passed=False,
            current_exercise_eligibility_verified=False, actual_net_proceeds_verified=False,signal_valid=False))
    return a,fulls,docs


class IndependentReferenceTests(unittest.TestCase):
    def test_preserves_coverage_and_does_not_approve_semantics(self):
        a,f,d=references(); r=verify_independent(a,f,d)
        self.assertEqual((r['documents'],r['text_anchors_verified'],r['cited_image_bytes_references_verified']),(3,3,3))
        self.assertFalse(r['semantic_interpretation_automatically_verified'])
        self.assertFalse(r['cash_claim_source_gate_passed'])

    def test_rejects_identity_request_and_time_changes(self):
        a,f,d=references()
        for field,value in [('sha256','0'*64),('physical_pages',99),('observed_at_utc','backdated'),
                             ('official_request',dict(filename='x',url='https://example.invalid',method='GET'))]:
            b=deepcopy(a); b['cases'][0]['source_pdf'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError): verify_independent(b,f,d)

    def test_rejects_wrong_page_hash_or_invented_text(self):
        a,f,d=references()
        for field,value in [('physical_page',2),('page_text_sha256','0'*64),('exact_anchors',['invented'])]:
            b=deepcopy(a); b['cases'][0]['notes'][0]['evidence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError): verify_independent(b,f,d)

    def test_visual_binding_and_claim_cannot_be_promoted(self):
        a,f,d=references()
        for mutate in [lambda r:r['embedded_image'].update(sha256='0'*64),
                       lambda r:r.update(transcription_automatically_verified=True),
                       lambda r:r.update(exact_anchors=['OCR not reviewed']),
                       lambda r:r.update(manual_view_performed=False)]:
            b=deepcopy(a); mutate(b['cases'][0]['notes'][0]['evidence'][1])
            with self.assertRaises(ValueError):verify_independent(b,f,d)

    def test_population_or_gate_or_count_drift(self):
        a,f,d=references()
        for mutate in [lambda x:x['cases'].pop(),lambda x:x.update(source_gate_passed=True),
                       lambda x:x.update(valid_prospective_signal_date='2026-10-23'),
                       lambda x:x['validation'].update(extracted_text_anchor_count=2),
                       lambda x:x['cases'][0].update(signal_valid=True)]:
            b=deepcopy(a);mutate(b)
            with self.assertRaises(ValueError):verify_independent(b,f,d)

if __name__=='__main__':unittest.main()
