import unittest
from sec_submission import acceptance_clock
from sec_filing_index import parse_filing_index, corroborate_index

ACCESSION = '0000950170-25-006966'
BASE = 'https://www.sec.gov/Archives/edgar/data/1033767/000095017025006966/'
URL = BASE+ACCESSION+'-index.html'
HTML = f'''<!-- saved from url=(0098){URL} -->
<html><head><title>EDGAR Filing Documents for {ACCESSION}</title>
<meta http-equiv="Last-Modified" content="Tue, 21 Jan 2025 11:03:58 GMT"></head><body>
<div id="formName"><strong>Form 6-K</strong> - Report</div>
<div id="secNum">SEC Accession No. {ACCESSION}</div>
<span class="companyName">UNITED MICROELECTRONICS CORP (Filer) CIK:
<a href="https://www.sec.gov/cgi-bin/browse-edgar?CIK=0001033767&amp;action=getcompany">0001033767</a></span>
<div><div class="infoHead">Filing Date</div><div class="info">2025-01-21</div>
<div class="infoHead">Accepted</div><div class="info">2025-01-21 06:03:58</div>
<div class="infoHead">Documents</div><div class="info">2</div>
<div class="infoHead">Period of Report</div><div class="info">2025-01-21</div></div>
<table summary="Document Format Files"><tbody>
<tr><td>1</td><td>6-K</td><td><a href="{BASE}primary.htm">primary.htm</a></td><td>6-K</td><td>101</td></tr>
<tr><td>2</td><td>EX-99</td><td><a href="{BASE}release.htm">release.htm</a></td><td>EX-99</td><td>202</td></tr>
<tr><td>&nbsp;</td><td>Complete submission text file</td><td><a href="{BASE}{ACCESSION}.txt">{ACCESSION}.txt</a></td><td>&nbsp;</td><td>500</td></tr>
</tbody></table></body></html>'''
SUBMISSION = dict(accession=ACCESSION, cik='0001033767', company='UNITED MICROELECTRONICS CORP', form='6-K',
                  filed_date='20250121', period_of_report='20250121', document_count=2, source_size_bytes=500,
                  acceptance=acceptance_clock('20250121060358'), documents=[
                      dict(filename='primary.htm', sequence=1, type='6-K', payload_size_bytes=99),
                      dict(filename='release.htm', sequence=2, type='EX-99', payload_size_bytes=199)])


class FilingIndexTests(unittest.TestCase):
    def parse(self, text=HTML, submission=None):
        return parse_filing_index(text.encode(), submission=submission or SUBMISSION, source_url=URL)

    def reject(self, old, new):
        self.assertIn(old, HTML)
        with self.assertRaises(ValueError):
            self.parse(HTML.replace(old, new))

    def test_structural_match_and_sizes_are_distinct_representations(self):
        value = self.parse()
        self.assertTrue(value['index_and_sgml_wallclock_match'])
        self.assertEqual(value['documents'][0]['index_size_bytes'], 101)
        self.assertTrue(value['last_modified_matches_interpreted_acceptance'])
        self.assertFalse(value['source_http_headers_available'])

    def test_wrong_accession(self):
        self.reject('EDGAR Filing Documents for '+ACCESSION, 'EDGAR Filing Documents for 0000950170-25-006967')

    def test_wrong_cik(self):
        self.reject('CIK=0001033767', 'CIK=0001046179')

    def test_wrong_origin(self):
        self.reject('saved from url=(0098)'+URL, 'saved from url=(0098)https://example.com/other')

    def test_duplicate_accepted_rejected_even_if_identical(self):
        self.reject('<div class="infoHead">Documents', '<div class="infoHead">Accepted</div><div class="info">2025-01-21 06:03:58</div><div class="infoHead">Documents')

    def test_mismatched_clock(self):
        self.reject('2025-01-21 06:03:58', '2025-01-21 11:03:58')

    def test_missing_accepted_is_not_replaced_by_last_modified(self):
        self.reject('<div class="infoHead">Accepted</div><div class="info">2025-01-21 06:03:58</div>', '')

    def test_document_url_substitution(self):
        self.reject('href="'+BASE+'release.htm"', 'href="https://example.com/release.htm"')

    def test_document_type_substitution(self):
        self.reject('<td>EX-99</td><td>202</td>', '<td>EX-99.1</td><td>202</td>')

    def test_complete_byte_count(self):
        self.reject('<td>500</td>', '<td>501</td>')

    def test_doc_count(self):
        self.reject('<div class="info">2</div>', '<div class="info">3</div>')

    def test_missing_last_modified_does_not_invalidate_real_accepted(self):
        value = self.parse(HTML.replace('<meta http-equiv="Last-Modified" content="Tue, 21 Jan 2025 11:03:58 GMT">', ''))
        self.assertIsNone(value['last_modified_html_meta_utc'])
        self.assertTrue(value['index_and_sgml_wallclock_match'])

    def test_script_is_not_accepted_evidence(self):
        value = self.parse(HTML.replace('</body>', '<script>throw new Error("not executed");</script></body>'))
        self.assertTrue(value['index_and_sgml_wallclock_match'])

    def test_json_conflict_is_preserved_without_model_promotion(self):
        reported = '2025-01-21T16:03:58.000Z'
        result = corroborate_index(self.parse(), SUBMISSION['acceptance'], reported)
        self.assertEqual(result['json_as_reported'], reported)
        self.assertEqual(result['delta_seconds_json_minus_sgml'], 18000)
        self.assertTrue(result['json_conflict_retained'])
        self.assertEqual(result['canonical_sec_accepted_at'], '2025-01-21T19:03:58+08:00')
        for key in ['public_dissemination_at','taiwan_first_published_at']:
            self.assertIsNone(result[key])
        self.assertFalse(result['ready_for_model'])
        self.assertFalse(result['complete_revision_history_verified'])

    def test_matching_json_still_does_not_verify_publication(self):
        result = corroborate_index(self.parse(), SUBMISSION['acceptance'], '2025-01-21T11:03:58Z')
        self.assertFalse(result['json_conflict_retained'])
        self.assertIsNone(result['public_dissemination_at'])
        self.assertFalse(result['ready_for_model'])

    def test_corroboration_rejects_changed_header(self):
        with self.assertRaises(ValueError):
            corroborate_index(self.parse(), acceptance_clock('20250121070358'), '2025-01-21T16:03:58Z')


if __name__ == '__main__':
    unittest.main()
