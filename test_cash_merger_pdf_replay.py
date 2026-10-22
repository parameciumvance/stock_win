"""Binary/page/identity controls using genuinely generated synthetic PDFs."""
from io import BytesIO
import unittest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject

from cash_merger_pdf_replay import digest, replay_pdf


TERMS = dict(issuer=["Issuer6674"], meeting_type=["EGM"], meeting_date=["2026-11-09"])


def pdf_bytes(page_texts, password=None, mixed_image=False):
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_ref = writer._add_object(font)
    for number, text in enumerate(page_texts):
        page = writer.add_blank_page(width=612, height=792)
        if text is not None:
            page[NameObject('/Resources')] = DictionaryObject({
                NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref})})
            stream = DecodedStreamObject()
            literal = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream.set_data(('BT /F1 12 Tf 20 700 Td (' + literal + ') Tj ET').encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
        if mixed_image and number == 0:
            image = DecodedStreamObject()
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                          NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1),
                          NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            image.set_data(b'\xff\x00\x00')
            page['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'): writer._add_object(image)})
            stream.set_data(stream.get_data() + b' q 10 0 0 10 20 20 cm /Im1 Do Q')
    if password is not None:
        writer.encrypt(password)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class PdfReplayTests(unittest.TestCase):
    def test_pages_whole_text_hashes_and_identity_candidate_locations(self):
        raw = pdf_bytes(['Issuer6674 EGM 2026-11-09', 'Conditional cash clause; not a conclusion.'])
        full, small = replay_pdf(raw, digest(raw), TERMS, expected_pages=2)
        self.assertEqual([p['page_number'] for p in full['pages']], [1, 2])
        self.assertIn('Conditional cash clause', full['pages'][1]['text'])
        self.assertEqual(small['extracted_page_count'], 2)
        self.assertEqual(small['full_text_sha256'], digest(full['full_text'].encode()))
        for page, saved in zip(full['pages'], small['pages'], strict=True):
            self.assertEqual(saved['text_sha256'], digest(page['text'].encode()))
        self.assertEqual(small['identity_candidate_matches']['issuer'][0]['page_number'], 1)
        self.assertTrue(small['text_identity_candidates_complete'])
        self.assertFalse(small['text_identity_is_legal_or_issuer_verification'])
        self.assertFalse(small['contractual_cash_claim_verified'])

    def test_http200_html_and_changed_pdf_bytes_cannot_pass_as_pdfs(self):
        html = b'<html>download another link</html>'
        with self.assertRaisesRegex(ValueError, 'PDF magic'):
            replay_pdf(html, digest(html), TERMS)
        raw = pdf_bytes(['Issuer6674 EGM 2026-11-09'])
        with self.assertRaisesRegex(ValueError, 'source SHA'):
            replay_pdf(raw + b'changed', digest(raw), TERMS)

    def test_encrypted_pdf_is_rejected_without_trying_default_credentials(self):
        raw = pdf_bytes(['Issuer6674 EGM 2026-11-09'], password='synthetic-secret')
        with self.assertRaisesRegex(ValueError, 'Encrypted'):
            replay_pdf(raw, digest(raw), TERMS)

    def test_zero_pages_truncated_pdf_and_missing_declared_page_fail(self):
        empty = pdf_bytes([])
        with self.assertRaisesRegex(ValueError, 'missing/zero pages'):
            replay_pdf(empty, digest(empty), TERMS)
        raw = pdf_bytes(['Issuer6674 EGM 2026-11-09'])
        self.assertIn(b'/Count 1', raw)
        changed = raw.replace(b'/Count 1', b'/Count 2', 1)
        with self.assertRaisesRegex(ValueError, 'missing/zero pages'):
            replay_pdf(changed, digest(changed), TERMS)
        truncated = raw[:len(raw) // 2]
        with self.assertRaises(ValueError):
            replay_pdf(truncated, digest(truncated), TERMS)

    def test_expected_page_count_is_separate_from_legitimate_blank_page(self):
        raw = pdf_bytes(['Issuer6674 EGM 2026-11-09', None])
        full, small = replay_pdf(raw, digest(raw), TERMS, expected_pages=2)
        self.assertEqual(len(full['pages']), 2)
        self.assertTrue(small['pages'][1]['empty_extracted_text'])
        self.assertTrue(small['all_declared_pages_extracted'])
        self.assertTrue(small['visual_review_needed'])
        with self.assertRaisesRegex(ValueError, 'expected page count'):
            replay_pdf(raw, digest(raw), TERMS, expected_pages=3)

    def test_wrong_company_or_date_is_missing_identity_and_never_inferred_from_filename(self):
        raw = pdf_bytes(['Issuer9999 EGM 2026-06-22'])
        _, small = replay_pdf(raw, digest(raw), TERMS)
        self.assertEqual(set(small['missing_identity_candidate_fields']), {'issuer', 'meeting_date'})
        self.assertFalse(small['text_identity_candidates_complete'])
        self.assertFalse(small['source_gate_passed'])

    def test_identity_literal_cannot_be_synthesized_across_two_page_boundaries(self):
        raw = pdf_bytes(['EGM 2026-11-09 Issuer66', '74'])
        _, small = replay_pdf(raw, digest(raw), TERMS)
        self.assertEqual(small['identity_candidate_matches']['issuer'], [])
        self.assertIn('issuer', small['missing_identity_candidate_fields'])

    def test_complete_text_does_not_clear_mixed_image_page_for_visual_review(self):
        raw = pdf_bytes(['Issuer6674 EGM 2026-11-09'], mixed_image=True)
        _, small = replay_pdf(raw, digest(raw), TERMS)
        self.assertTrue(small['text_identity_candidates_complete'])
        self.assertFalse(small['pages'][0]['empty_extracted_text'])
        self.assertEqual(small['pages'][0]['embedded_image_count'], 1)
        self.assertTrue(small['pages'][0]['visual_review_needed'])
        self.assertTrue(small['visual_review_needed'])
        self.assertFalse(small['visual_review_completed'])


if __name__ == '__main__':
    unittest.main()
