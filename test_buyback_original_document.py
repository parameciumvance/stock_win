import copy
import unittest

from buyback_original_document import parse_document


BOARD = '''1.董事會決議日期:113/03/14
2.買回股份目的:轉讓股份予員工
3.買回股份種類:普通股
4.買回股份總金額上限(元):11,822,719,947
5.預定買回之期間:113/03/15~113/05/14
6.預定買回之數量(股):9,000,000
7.買回區間價格(元):50.00~80.00，公司股價低於區間價格下限，將繼續買回
8.買回方式:自集中交易市場買回
9.預定買回股份占公司已發行股份總數之比率(%):1.01
10.申報時已持有本公司股份之累積股數(股):0
11.申報前三年內買回公司股份之情形:
無買回
12.已申報買回但未執行完畢之情形:
1.109年申報買回500,000股，實際買回0股。
2.111年申報買回400,000股，實際買回300,000股。
13.董事會決議買回股份之會議紀錄:
1.依證券交易法規定辦理。
2.本次計畫如下：
(1)買回股份總金額上限：11,822,719,947元。
14.「上市上櫃公司買回本公司股份辦法」第十條規定之轉讓辦法:
4.1轉讓標的：普通股。
4.5.1依董事會之決議買回本公司股份。
15.「上市上櫃公司買回本公司股份辦法」第十一條規定之轉換或認股辦法:
不適用
16.董事會已考慮公司財務狀況，不影響公司資本維持之聲明:
是,已聲明不影響公司資本維持
17.會計師或證券承銷商對買回股份價格之合理性評估意見:
經會計師評估其買回股份價格具合理性
18.其他證期局所規定之事項:
無'''

COMPLETION = '''1.原預定買回股份總金額上限(元):7,704,859,000
2.原預定買回之期間:112/11/08~113/01/07
3.原預定買回之數量(股):2,000,000
4.原預定買回區間價格(元):21.70~46.00
5.本次實際買回期間:112/11/13~113/01/05
6.本次已買回股份數量(股):2,000,000
7.本次已買回股份總金額(元):68,708,175
8.本次平均每股買回價格(元):34.35
9.累積已持有自己公司股份數量(股):2,000,000
10.累積已持有自己公司股份數量占公司已發行股份總數之比率(%):0.29
11.本次未執行完畢之原因:

12.其他應敘明事項:
無'''

THRESHOLD = '''1.本次買回股份數量累積達公司已發行股份總額百分之二或金額達新台幣三億元以上之日期:113/01/02
2.本次買回股份數量(股):11,700,000
3.本次買回股份總金額(元):316,350,155
4.本次平均每股買回價格(元):27.04
5.於買回期間內累積已持有自己公司股份數量(股):140,526,000
6.於買回期間內累積已持有自己公司股份數量占公司已發行股份總數之比率(%):0.89
7.其他應敘明事項:
無'''


def fixture(description=BOARD, *, subject='董事會決議申請庫藏股買回', date='113/03/14',
            time='17:30:23', sequence=4, issuer='1210'):
    body = f'''<html><table><tr><td><b>本資料由　\n(上市公司) {issuer}\n大成 公司提供</b></td></tr></table>
    <table><tr><th>序號</th><td>{sequence}</td><th>發言日期</th><td>{date}</td>
    <th>發言時間</th><td>{time}</td></tr><tr><th>主旨</th><td>{subject}</td></tr>
    <tr><th>說明</th><td><pre>{description}</pre></td></tr></table></html>'''.encode()
    year, month, day = date.split('/')
    url_date = f'{int(year) + 1911:04d}{month}{day}'
    row = dict(COMPANY_ID=issuer, CDATE=date, CTIME=time, SUBJECT=subject,
               HYPERLINK=f'https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1?SEQ_NO={sequence}'
               f'&COMPANY_ID={issuer}&SPOKE_DATE={url_date}&SPOKE_TIME={time.replace(":", "")}')
    return body, row


class BuybackOriginalDocumentTests(unittest.TestCase):
    def test_board_fields_keep_prices_and_nested_numbered_clauses(self):
        body, row = fixture()
        parsed = parse_document(body, row)
        self.assertEqual(parsed['issuer'], '1210')
        self.assertEqual(parsed['reported_datetime'], '2024-03-14T17:30:23+08:00')
        self.assertEqual(parsed['sequence'], 4)
        self.assertTrue(parsed['first_field_is_board_resolution'])
        self.assertEqual(list(parsed['numbered_fields']), [str(i) for i in range(1, 19)])
        self.assertIn('實際買回0股', parsed['numbered_fields']['12'])
        self.assertIn('(1)買回股份總金額上限', parsed['numbered_fields']['13'])
        self.assertIn('4.5.1依董事會之決議', parsed['numbered_fields']['14'])
        self.assertEqual(parsed['numbered_fields']['7'],
                         '7.買回區間價格(元):50.00~80.00，公司股價低於區間價格下限，將繼續買回')
        self.assertNotIn('point_in_time_verified', parsed)

    def test_correction_keeps_its_own_amount_and_publication_time(self):
        original = parse_document(*fixture())
        corrected = parse_document(*fixture(BOARD.replace('11,822,719,947', '11,779,724,865'),
                                   subject='更正董事會決議申請庫藏股買回', date='113/03/19',
                                   time='14:44:21', sequence=2))
        self.assertEqual(original['numbered_fields']['4'], '4.買回股份總金額上限(元):11,822,719,947')
        self.assertEqual(corrected['numbered_fields']['4'], '4.買回股份總金額上限(元):11,779,724,865')
        self.assertEqual(corrected['reported_datetime'], '2024-03-19T14:44:21+08:00')
        self.assertIn('更正', corrected['subject'])
        self.assertTrue(corrected['first_field_is_board_resolution'])  # A form, not a first-version claim.

    def test_completion_and_threshold_are_not_initial_forms(self):
        for text, subject, form, count in [
            (COMPLETION, '公告買回本公司股份已執行完畢', 'completion', 12),
            (THRESHOLD, '公告本公司買回股份金額達新台幣三億元以上', 'threshold', 7),
        ]:
            with self.subTest(form=form):
                parsed = parse_document(*fixture(text, subject=subject))
                self.assertFalse(parsed['first_field_is_board_resolution'])
                self.assertEqual(parsed['document_form'], form)
                self.assertEqual(len(parsed['numbered_fields']), count)

    def test_wrong_issuer_and_wrong_index_clock_fail(self):
        body, row = fixture()
        for key, value in [('COMPANY_ID', '2002'), ('CTIME', '17:30:24'), ('CDATE', '113/03/15')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(row)
                changed[key] = value
                with self.assertRaises(ValueError):
                    parse_document(body, changed)

    def test_wrong_sequence_or_url_identity_fail(self):
        body, row = fixture()
        for old, new in [('SEQ_NO=4', 'SEQ_NO=5'), ('COMPANY_ID=1210', 'COMPANY_ID=2002'),
                         ('SPOKE_DATE=20240314', 'SPOKE_DATE=20240315'),
                         ('SPOKE_TIME=173023', 'SPOKE_TIME=173024')]:
            with self.subTest(old=old):
                changed = copy.deepcopy(row)
                changed['HYPERLINK'] = changed['HYPERLINK'].replace(old, new)
                with self.assertRaises(ValueError):
                    parse_document(body, changed)
        row['HYPERLINK'] += '&SEQ_NO=4'
        with self.assertRaises(ValueError):
            parse_document(body, row)

    def test_five_and_six_digit_url_times_identify_the_same_clock(self):
        body, row = fixture(time='08:44:13', issuer='4571')
        padded = parse_document(body, row)
        row['HYPERLINK'] = row['HYPERLINK'].replace('SPOKE_TIME=084413', 'SPOKE_TIME=84413')
        original_url = row['HYPERLINK']
        self.assertEqual(parse_document(body, row), padded)
        self.assertEqual(row['HYPERLINK'], original_url)
        for bad in ['84412', '084414', '4413', '0084413', '+84413', '84:413']:
            with self.subTest(time=bad):
                changed = copy.deepcopy(row)
                changed['HYPERLINK'] = original_url.replace('SPOKE_TIME=84413', 'SPOKE_TIME=' + bad)
                with self.assertRaises(ValueError):
                    parse_document(body, changed)

    def test_query_identity_alone_does_not_authorize_an_external_or_wrong_url(self):
        body, row = fixture()
        original_url = row['HYPERLINK']
        for bad in [
            original_url.replace('https://', 'http://'),
            original_url.replace('mopsov.twse.com.tw', 'example.com'),
            original_url.replace('mopsov.twse.com.tw', 'mopsov.twse.com.tw.example.com'),
            original_url.replace('mopsov.twse.com.tw', 'example.com@mopsov.twse.com.tw'),
            original_url.replace('mopsov.twse.com.tw', 'mopsov.twse.com.tw:8443'),
            original_url.replace('/ajax_t05sr01_1?', '/other_endpoint?'),
            original_url + '#unverified-fragment',
        ]:
            with self.subTest(url=bad):
                changed = copy.deepcopy(row)
                changed['HYPERLINK'] = bad
                with self.assertRaises(ValueError):
                    parse_document(body, changed)

    def test_subject_content_mismatch_fails_but_display_whitespace_does_not(self):
        body, row = fixture(subject='董事會決議\n申請庫藏股買回')
        row['SUBJECT'] = '董事會決議申請庫藏股買回'
        parse_document(body, row)
        row['SUBJECT'] = '公告買回本公司股份已執行完畢'
        with self.assertRaises(ValueError):
            parse_document(body, row)

    def test_missing_duplicate_and_reordered_main_fields_fail(self):
        for description in [BOARD.replace('18.其他證期局所規定之事項:\n無', ''),
                            BOARD + '\n18.其他證期局所規定之事項:\n另一段',
                            BOARD.replace('5.預定買回之期間', '6.預定買回之期間')]:
            with self.subTest(description=description[-50:]):
                with self.assertRaises(ValueError):
                    parse_document(*fixture(description))

    def test_error_page_and_multiple_announcements_fail_closed(self):
        body, row = fixture()
        for candidate in [b'<html>query error</html>', body + body]:
            with self.subTest(size=len(candidate)):
                with self.assertRaises(ValueError):
                    parse_document(candidate, row)

    def test_explicit_html_breaks_preserve_field_boundaries(self):
        body, row = fixture()
        body = body.replace(BOARD.encode(), BOARD.replace('\n', '<br>').encode())
        parsed = parse_document(body, row)
        self.assertEqual(len(parsed['numbered_fields']), 18)
        self.assertIn('4.5.1', parsed['numbered_fields']['14'])


if __name__ == '__main__':
    unittest.main()
