"""Guard against wrong-year, navigation-only and hindsight-ready source promotion."""
import hashlib
import json
import unittest

from tender_preflight import FILING_HEADER, parse_case, parse_filings, parse_index, verified_records


def table(header, rows):
    return '<table><tr>' + ''.join('<th>' + c + '</th>' for c in header) + '</tr>' + ''.join(
        '<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows) + '</table>'


def filing_rows(rows=None):
    base = ['1', '113/12/20', '114/01/08', '甲公司', '否', '否', '乙公司(1234)', '券商', '普通股',
            '每股10元', '自有資金', '確認書', '2,500,000股', '1,900,000股', '2,000,000股', '否', '成功', 'NA']
    return base if rows is None else table(FILING_HEADER, rows)


class SourceSemanticsTests(unittest.TestCase):
    def test_http200_navigation_and_refusal_are_not_zero_cases(self):
        for body in ['<h1>安全性問題</h1>', '<a>公開收購統計彙總表</a>']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_index(body, 113)

    def test_wrong_year_rejected_even_with_valid_table(self):
        body = '收購開始年度：114' + table(['序號','公開收購人','被收購公司','被收購公司證券代號','相關檔案','申報日期'],
                                         [['1','甲','乙','1234','','113/12/19']])
        with self.assertRaises(ValueError):
            parse_index(body, 113)

    def test_wrong_schema_rejected(self):
        header = FILING_HEADER[:]
        header[12], header[13] = header[13], header[12]
        with self.assertRaises(ValueError):
            parse_filings(table(header, [filing_rows()]))

    def test_failed_offer_retained(self):
        row = filing_rows()
        row[14], row[16], row[17] = '0股', '失敗', '未達最低數量'
        r = parse_filings(filing_rows([row]))[0]
        self.assertEqual(r['reported_outcome'], '失敗')
        self.assertEqual(r['reported_actual_shares'], 0)
        self.assertFalse(r['quantity_conflict'])

    def test_success_zero_is_conflict_not_successful_return(self):
        row = filing_rows()
        row[14] = '0股'
        r = parse_filings(filing_rows([row]))[0]
        self.assertTrue(r['quantity_conflict'])
        self.assertEqual(r['reported_fields']['實際收購數量'], '0股')
        self.assertEqual(r['reported_outcome'], '成功')

    def test_unknown_quantity_never_zero(self):
        row = filing_rows()
        row[14] = '--'
        r = parse_filings(filing_rows([row]))[0]
        self.assertIsNone(r['reported_actual_shares'])
        self.assertTrue(r['quantity_conflict'])

    def test_crossyear_end_retained(self):
        r = parse_filings(filing_rows([filing_rows()]))[0]
        self.assertEqual((r['start'], r['end']), ('2024-12-20','2025-01-08'))

    def test_bad_date_preserved_without_guessing_century(self):
        row = filing_rows()
        row[2] = '15/09/07'
        r = parse_filings(filing_rows([row]))[0]
        self.assertIsNone(r['end'])
        self.assertEqual(r['reported_fields']['公開收購期間末日'], '15/09/07')
        self.assertIn('invalid_end_date', r['source_issues'])

    def test_duplicates_retained_and_marked(self):
        a = filing_rows()
        b = a[:]
        b[0] = '2'
        rows = parse_filings(filing_rows([a,b]))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all('duplicate_case_identity' in r['source_issues'] for r in rows))

    def test_same_symbol_different_bidder_not_silently_deduplicated(self):
        a = filing_rows()
        b = a[:]
        b[0], b[3] = '2', '丙公司'
        self.assertEqual(len(parse_filings(filing_rows([a,b]))), 2)

    def test_case_pointer_is_not_original_verification_and_revisions_retained(self):
        header = ['公開收購人','被收購公司','被收購公司證券代號','主旨','電子檔案','申報日期']
        rows = [['甲','乙','1234','公開收購說明書(新申報)1','first.pdf','113/12/19 13:00:00'],
                ['甲','乙','1234','公開收購說明書(修正)1','revised.pdf','113/12/21 18:00:00']]
        result = parse_case(table(header, rows), '1234')
        self.assertEqual(len(result), 2)
        self.assertTrue(all(not r['original_bytes_verified'] for r in result))
        self.assertEqual(result[1]['reported_timestamp_taipei'], '2024-12-21T18:00:00+08:00')
        with self.assertRaises(ValueError):
            parse_case(table(header, rows), '9999')


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(filename='body.html',url='https://example.org/')
        self.row = dict(request=self.request,sha256=hashlib.sha256(b'original').hexdigest(),
                        headers_sha256=hashlib.sha256(b'header').hexdigest())
        self.results = dict(workers=2,requests=[self.row])
        self.files = {'body.html':b'original','body.html.headers':b'header','body.html.meta.json':json.dumps(self.row).encode()}

    def test_body_and_header_tampering_rejected(self):
        for name in ['body.html','body.html.headers']:
            files = {**self.files,name:b'replacement'}
            with self.subTest(name=name), self.assertRaises(ValueError):
                verified_records(dict(requests=[self.request]),self.results,files.__getitem__)

    def test_request_cohort_and_metadata_drift_rejected(self):
        for cfg, files in [(dict(requests=[]), self.files),
                           (dict(requests=[self.request]), {**self.files,'body.html.meta.json':b'{}'})]:
            with self.assertRaises(ValueError):
                verified_records(cfg,self.results,files.__getitem__)

    def test_exact_captured_record_passes_without_promoting_pit(self):
        result = verified_records(dict(requests=[self.request]),self.results,self.files.__getitem__)
        self.assertNotIn('historical_pit_verified',result[0])


if __name__ == '__main__':
    unittest.main()
