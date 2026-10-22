"""Adversarial synthetic evidence tests; no saved research inputs are read."""
import copy
import hashlib
from io import BytesIO
import json
import unittest
import zipfile

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

import cash_merger_terms_audit as audit


def digest(body):
    return hashlib.sha256(body).hexdigest()


def pdf_bytes():
    writer = PdfWriter()
    for text in ('Cash 18.50 per share\n-11-', 'After 7 business days\n-12-'):
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): writer._add_object(font)})})
        image = StreamObject()
        image.set_data(b'\xff\x00\x00')
        image.update({NameObject('/Type'): NameObject('/XObject'),
                      NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): NumberObject(1),
                      NameObject('/Height'): NumberObject(1),
                      NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                      NameObject('/BitsPerComponent'): NumberObject(8)})
        resources[NameObject('/XObject')] = DictionaryObject({
            NameObject('/Seal'): writer._add_object(image)})
        page[NameObject('/Resources')] = resources
        stream = StreamObject()
        first, second = text.split('\n')
        stream.set_data(('BT /F1 12 Tf 10 250 Td ('+first+') Tj 0 -20 Td ('+
                         second+') Tj ET q 10 0 0 10 20 20 cm /Seal Do Q').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def archive_bytes(members, manifest=None):
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as saved:
        for name, body in members.items():
            saved.writestr(name, body)
        saved.writestr('manifest.json', json.dumps(
            manifest if manifest is not None else {n: digest(b) for n, b in members.items()}))
    return out.getvalue()


def fixture():
    body = pdf_bytes()
    member = 'raw/synthetic.pdf'
    meta = dict(request=dict(filename='synthetic.pdf', url='https://doc.twse.com.tw/pdf/synthetic.pdf'),
                request_started_at='2026-10-21T22:43:50+00:00',
                observed_at='2026-10-21T22:43:57+00:00',
                sha256=digest(body), size_bytes=len(body), http_status=200, exit_code=0)
    doc = audit.extract_document(body, member, meta, image_pages=(1,))
    semantic = dict(source_archive=dict(sha256='a'*64), source_documents=[dict(
        member=member, sha256=digest(body), size_bytes=len(body), physical_pages=2,
        official_request_url=meta['request']['url'], request_started_at_utc=meta['request_started_at'],
        observed_at_utc=meta['observed_at'], observation_window_taipei='2026-10-22 06:43')],
        readings=[dict(id='cash', evidence=[dict(source_pdf=member, source_pdf_sha256=digest(body),
            physical_page=1, printed_page=11, extracted_page_text_sha256=doc['pages'][0]['text_sha256'],
            exact_anchor='Cash 18.50 per share')])], validation=dict(anchor_count=1))
    terms = dict(source_archive_sha256='a'*64, source_files=[dict(filename='synthetic.pdf',
        pdf_sha256=digest(body), pdf_page_count=2, archive_sha256='a'*64, archive_member=member,
        actual_request_started_at_utc=meta['request_started_at'], actual_observed_at_utc=meta['observed_at'],
        actual_observation_taipei='2026-10-22T06:43:57+08:00',
        reported_upload_is_first_public_availability_verified=False)], terms=[dict(topic='payment',
        evidence=[dict(filename='synthetic.pdf', pdf_sha256=digest(body), pdf_page_number=2,
            printed_page_label=12, page_text_sha256=doc['pages'][1]['text_sha256'],
            exact_anchors=['After 7 business days'])])])
    return {member: doc}, semantic, terms


class ArchiveTests(unittest.TestCase):
    def test_whole_archive_and_exact_manifest(self):
        body = archive_bytes({'raw/a.pdf': b'%PDF-synthetic'})
        result = audit.verify_archive(body, digest(body))
        self.assertEqual(result['raw/a.pdf'], b'%PDF-synthetic')

    def test_rehashed_outer_archive_does_not_hide_inner_drift(self):
        body = archive_bytes({'raw/a.pdf': b'changed'}, {'raw/a.pdf': digest(b'original')})
        with self.assertRaisesRegex(ValueError, 'inner member SHA'):
            audit.verify_archive(body, digest(body))

    def test_unmanifested_member_and_wrong_outer_hash_fail(self):
        body = archive_bytes({'raw/a.pdf': b'a', 'extra': b'b'}, {'raw/a.pdf': digest(b'a')})
        with self.assertRaisesRegex(ValueError, 'population'):
            audit.verify_archive(body, digest(body))
        with self.assertRaisesRegex(ValueError, 'Archive SHA'):
            audit.verify_archive(body, '0'*64)

    def test_unsafe_member_is_rejected_even_with_correct_hash(self):
        body = archive_bytes({'../a.pdf': b'a'})
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            audit.verify_archive(body, digest(body))


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.documents, self.semantic, self.terms = fixture()

    def run_audit(self):
        return audit.verify_annotations(self.documents, self.semantic, self.terms, archive_sha256='a'*64)

    def test_real_synthetic_pdf_page_binding_and_source_time(self):
        result = self.run_audit()
        self.assertEqual(result['semantic_anchors'], 1)
        self.assertEqual(result['terms_anchors'], 1)
        self.assertEqual(result['timestamp_bindings'][0]['actual_observed_at_taipei'],
                         '2026-10-22T06:43:57+08:00')
        self.assertFalse(result['semantic_interpretation_automatically_verified'])
        self.assertFalse(result['cash_claim_source_gate_passed'])

    def test_numeric_anchor_drift_fails(self):
        self.semantic['readings'][0]['evidence'][0]['exact_anchor'] = 'Cash 18.51 per share'
        with self.assertRaisesRegex(ValueError, 'anchor absent'):
            self.run_audit()

    def test_whitespace_only_anchor_variation_passes(self):
        self.semantic['readings'][0]['evidence'][0]['exact_anchor'] = 'Cash\n18.50 per\tshare'
        self.assertTrue(self.run_audit()['all_evidence_bindings_verified'])

    def test_correct_text_on_wrong_page_is_rejected(self):
        evidence = self.semantic['readings'][0]['evidence'][0]
        evidence.update(physical_page=2, printed_page=12,
                        extracted_page_text_sha256=self.documents['raw/synthetic.pdf']['pages'][1]['text_sha256'])
        with self.assertRaisesRegex(ValueError, 'anchor absent'):
            self.run_audit()

    def test_wrong_printed_page_is_not_accepted_from_physical_position(self):
        self.terms['terms'][0]['evidence'][0]['printed_page_label'] = 2
        with self.assertRaisesRegex(ValueError, 'Printed page label absent'):
            self.run_audit()

    def test_pdf_hash_and_page_hash_are_both_bound(self):
        for key in ('pdf_sha256', 'page_text_sha256'):
            with self.subTest(key=key):
                original = copy.deepcopy(self.terms)
                self.terms['terms'][0]['evidence'][0][key] = '0'*64
                with self.assertRaisesRegex(ValueError, 'SHA mismatch'):
                    self.run_audit()
                self.terms = original

    def test_taipei_label_cannot_be_source_utc_or_current_evening(self):
        self.terms['source_files'][0]['actual_observation_taipei'] = '2026-10-22T20:43:57+08:00'
        with self.assertRaisesRegex(ValueError, 'Taipei timestamp'):
            self.run_audit()

    def test_http_failure_and_reversed_observation_fail(self):
        meta = self.documents['raw/synthetic.pdf']['metadata']
        meta['http_status'] = 403
        with self.assertRaisesRegex(ValueError, 'transport/body'):
            self.run_audit()
        meta['http_status'] = 200
        meta['observed_at'] = '2026-10-21T21:43:57+00:00'
        with self.assertRaisesRegex(ValueError, 'precedes its request'):
            self.run_audit()

    def test_reported_upload_label_cannot_promote_to_pit(self):
        self.terms['source_files'][0]['reported_upload_is_first_public_availability_verified'] = True
        with self.assertRaisesRegex(ValueError, 'promoted to verified PIT'):
            self.run_audit()

    def test_missing_pdf_population_and_duplicate_notes_fail(self):
        self.semantic['source_documents'] *= 2
        with self.assertRaisesRegex(ValueError, 'population'):
            self.run_audit()
        self.semantic['source_documents'] = self.semantic['source_documents'][:1]
        self.terms['terms'] *= 2
        with self.assertRaisesRegex(ValueError, 'duplicate human term'):
            self.run_audit()

    def test_negative_findings_require_every_declared_page_hash(self):
        doc = self.documents['raw/synthetic.pdf']
        self.terms['terms'][0]['negative_finding_scope'] = dict(filename='synthetic.pdf', pdf_pages=[1, 2],
            page_text_sha256s=[dict(pdf_page_number=n, page_text_sha256=p['text_sha256'])
                              for n, p in enumerate(doc['pages'], 1)])
        self.assertEqual(self.run_audit()['negative_finding_pages'], 2)
        self.terms['terms'][0]['negative_finding_scope']['page_text_sha256s'].pop()
        with self.assertRaisesRegex(ValueError, 'coverage drift'):
            self.run_audit()

    def test_mixed_text_image_hash_is_bound_without_authentication_claim(self):
        doc = self.documents['raw/synthetic.pdf']
        image = doc['pages'][0]['images'][0]
        self.semantic['signature_visual_review'] = dict(source_pdf=doc['member'], source_pdf_sha256=doc['sha256'],
            physical_page=1, printed_page=11, embedded_images_observed=1,
            images=[dict(xobject_export_name=image['name'], pypdf_exported_image_sha256=image['sha256'],
                         width=image['width'], height=image['height'])])
        self.assertEqual(self.run_audit()['signature_images'], 1)
        self.semantic['signature_visual_review']['images'][0]['pypdf_exported_image_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Image hash/dimensions'):
            self.run_audit()

    def test_html_body_and_out_of_bounds_image_request_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not a PDF'):
            audit.extract_document(b'<html>HTTP 200, not PDF</html>', 'raw/a.pdf', {})
        with self.assertRaisesRegex(ValueError, 'Image page outside'):
            audit.extract_document(pdf_bytes(), 'raw/a.pdf', {}, image_pages=(3,))


if __name__ == '__main__':
    unittest.main()
