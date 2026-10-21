"""Document identity is independent of M11 form or cash-merger semantics."""
import copy
import hashlib
from html import escape
import unittest

from merger_document import parse_document


DESCRIPTION = '''1.董事會決議日期:115/08/13
2.發行期間:主管機關核准後辦理
3.認股權人條件:
1.員工資格與年資。
2.其他應敘明事項：
(1)每股價格：１２３．４５元。
4.1內部條款：−１，原字不改。
4.其他應敘明事項:完整保留'''


def fixture(description=DESCRIPTION, *, issuer='6472', date='115/08/13', clock='20:06:54',
            sequence='1', subject='本公司董事會決議發行員工認股權憑證'):
    provider = f'<table><tr><td><b>本資料由　\n(上市公司) {issuer}\n甲公司提供</b></td></tr></table>'
    record = (f'<table><tr><th>序號</th><td>{sequence}</td><th>發言日期</th><td>{date}</td>'
              f'<th>發言時間</th><td>{clock}</td></tr>'
              f'<tr><th>主旨</th><td>{escape(subject)}</td></tr>'
              f'<tr><th>說明</th><td><pre>{escape(description)}</pre></td></tr></table>')
    body = ('<html>' + provider + record + '</html>').encode()
    year, month, day = date.split('/')
    url_date = f'{int(year) + 1911:04d}{month}{day}'
    original = dict(COMPANY_ID=issuer, CDATE=date, CTIME=clock, SUBJECT=subject,
                    HYPERLINK='https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1'
                    f'?COMPANY_ID={issuer}&SPOKE_DATE={url_date}&SPOKE_TIME={clock.replace(":", "")}'
                    f'&SEQ_NO={sequence}')
    return body, original


class MergerDocumentTests(unittest.TestCase):
    def assert_no_semantics(self, value):
        self.assertIsNone(value['transaction_form'])
        self.assertIsNone(value['eligible_cash_merger'])
        for flag in ('cash_claim_source_gate_passed', 'independent_deal_identity_verified',
                     'historical_pit_verified', 'first_publication_time_verified', 'source_gate_passed'):
            self.assertFalse(value[flag], flag)

    def test_m11_board_date_first_label_keeps_every_nested_clause(self):
        raw, original = fixture()
        result = parse_document(raw, original)
        self.assertEqual(result['issuer'], '6472')
        self.assertEqual(result['reported_datetime'], '2026-08-13T20:06:54+08:00')
        self.assertEqual(result['sequence'], 1)
        self.assertEqual(result['subject'], original['SUBJECT'])
        self.assertEqual(result['description'], DESCRIPTION)
        self.assertEqual(result['raw_metadata']['說明'], DESCRIPTION)
        self.assertEqual(result['description_sha256'], hashlib.sha256(DESCRIPTION.encode()).hexdigest())
        self.assertEqual(result['body_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertTrue(result['metadata_identity_verified'])
        self.assert_no_semantics(result)

    def test_unknown_numbered_or_unstructured_form_does_not_fail_identity(self):
        for text in ('本次公告之自由格式全文，不含編號。', '1.未知表單標籤:未判斷\n99.原始條款:仍保留'):
            with self.subTest(text=text):
                result = parse_document(*fixture(text))
                self.assertEqual(result['description'], text)
                self.assert_no_semantics(result)

    def test_m11_same_legacy_sequence_distinct_clocks_have_distinct_description_text(self):
        first = parse_document(*fixture())
        second = parse_document(*fixture('1.事實發生日:115/08/13\n2.增資基準日:115/08/28',
                                        clock='16:58:56', subject='員工認股權憑證轉換普通股之增資基準日'))
        self.assertEqual(first['issuer'], second['issuer'])
        self.assertEqual(first['sequence'], second['sequence'])
        self.assertNotEqual(first['reported_datetime'], second['reported_datetime'])
        self.assertNotEqual(first['description_sha256'], second['description_sha256'])
        self.assert_no_semantics(first)
        self.assert_no_semantics(second)

    def test_wrong_index_issuer_date_time_and_subject_fail(self):
        raw, original = fixture()
        for key, value in (('COMPANY_ID', '1103'), ('CDATE', '115/08/14'), ('CTIME', '20:06:55'),
                           ('SUBJECT', '相同時間不同公告主旨')):
            changed = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_document(raw, changed)

    def test_incorrect_body_metadata_and_sequence_fail(self):
        raw, original = fixture()
        for before, after in (('6472', '1103'), ('115/08/13', '115/08/14'), ('20:06:54', '20:06:55'),
                              ('<td>1</td>', '<td>2</td>'), (original['SUBJECT'], '不同主旨')):
            with self.subTest(before=before), self.assertRaises(ValueError):
                parse_document(raw.replace(before.encode(), after.encode()), original)

    def test_official_full_url_identity_and_unique_query_keys_required(self):
        raw, original = fixture()
        url = original['HYPERLINK']
        bad_urls = [url.replace('6472', '1103'), url.replace('20260813', '20260814'),
                    url.replace('200654', '200655'), url.replace('SEQ_NO=1', 'SEQ_NO=2'),
                    url.replace('https:', 'http:'), url.replace('mopsov.twse.com.tw', 'foreign.example'),
                    url.replace('ajax_t05sr01_1', 'another_endpoint'), url + '&SEQ_NO=1',
                    url + '&%43OMPANY_ID=6472', url + '&step=1&step=1']
        for bad in bad_urls:
            with self.subTest(url=bad), self.assertRaises(ValueError):
                parse_document(raw, {**original, 'HYPERLINK': bad})

    def test_correction_retains_own_time_subject_and_value_without_backfilling(self):
        first = parse_document(*fixture('1.董事會決議日期:115/08/13\n2.現金對價:100元'))
        correction = parse_document(*fixture('1.董事會決議日期:115/08/13\n2.現金對價:101元',
                                            clock='20:10:00', sequence='2', subject='更正現金對價'))
        self.assertIn('100元', first['description'])
        self.assertNotIn('101元', first['description'])
        self.assertIn('101元', correction['description'])
        self.assertEqual(correction['reported_datetime'], '2026-08-13T20:10:00+08:00')
        self.assertEqual(correction['subject'], '更正現金對價')
        self.assert_no_semantics(correction)

    def test_missing_or_duplicate_record_provider_and_metadata_are_ambiguous(self):
        raw, original = fixture()
        provider_begin = raw.index(b'<table>')
        provider_end = raw.index(b'</table>') + len(b'</table>')
        record = raw[provider_end:raw.rindex(b'</html>')]
        duplicate_metadata = raw.replace('<th>序號</th><td>1</td>'.encode(),
                                         '<th>序號</th><td>1</td><th>序號</th><td>1</td>'.encode())
        for bad in (b'<html>error</html>', raw + raw, raw[:provider_begin] + raw[provider_end:],
                    raw.replace(b'</html>', record + b'</html>'), duplicate_metadata,
                    raw.replace('說明'.encode(), '不是說明'.encode())):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                parse_document(bad, original)

    def test_display_whitespace_ignored_only_for_identity_and_html_breaks_retained(self):
        raw, original = fixture('1.第一項:甲\n2.第二項:乙', subject='分行\n公告主旨')
        raw = raw.replace(b'\n2.', b'<br>2.')
        original['SUBJECT'] = '分行公告主旨'
        result = parse_document(raw, original)
        self.assertEqual(result['description'], '1.第一項:甲\n2.第二項:乙')
        self.assertEqual(result['subject'], '分行\n公告主旨')

    def test_index_original_remains_unchanged_and_five_digit_pointer_time_is_supported(self):
        raw, original = fixture(clock='08:44:13')
        original['HYPERLINK'] = original['HYPERLINK'].replace('SPOKE_TIME=084413', 'SPOKE_TIME=84413')
        saved = copy.deepcopy(original)
        result = parse_document(raw, original)
        self.assertEqual(original, saved)
        self.assertEqual(result['source_url'], saved['HYPERLINK'])
        self.assertEqual(result['reported_datetime'], '2026-08-13T08:44:13+08:00')

    def test_original_bytes_and_valid_calendar_clock_required(self):
        raw, original = fixture()
        with self.assertRaises(TypeError):
            parse_document(raw.decode(), original)
        with self.assertRaises(UnicodeDecodeError):
            parse_document(raw.replace('本資料由'.encode(), b'\xff'), original)
        for changed in ({**original, 'CTIME': '20:06:54+08:00'}, {**original, 'CTIME': '20:06:60'},
                        {**original, 'CDATE': '115/02/30'}, {**original, 'COMPANY_ID': 6472}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                parse_document(raw, changed)


if __name__ == '__main__':
    unittest.main()
