import copy
import hashlib
import unittest

from buyback_document_identity import parse_identity
from buyback_original_document import parse_document
from test_buyback_original_document import BOARD, COMPLETION, THRESHOLD, fixture


UNCLASSIFIED = '''1.原董事會決議日期:113/03/14
2.變更買回股份目的:由轉讓員工變更為註銷股份
3.變更原因及其他事項:
1.依董事會決議辦理。
2.原公告內容：轉讓股份予員工。
(1)保留內嵌條款與金額1,234,567元。
4.1不得被切成主欄位。'''

# Minimal values preserve every official main label from the two 1338 originals.
PURPOSE_CHANGE = '''1.董事會決議日期:113/11/13
2.變更後買回股份之目的:轉讓股份予員工
3.原買回股份種類:維護公司信用及股東權益
4.原預定買回之期間:113/08/16~113/10/15
5.實際買回期間:113/08/16~113/10/14
6.申報前三年內買回公司股份之情形:
無
7.已申報買回但未執行完畢之情形:
預定買回2,000,000股，實際買回1,500,000股，期限屆滿未執行股份500,000股
8.董事會決議通過變更原買回股份目的之會議紀錄:
經113年8月15日第3屆第7次董事會決議通過買回股份
9.「上市上櫃公司買回本公司股份辦法」第十條規定之轉讓辦法:
第一條
依據證券交易法第28條之2第1項第1款辦理。
1.內嵌員工辦法不可當主欄位。
10.「上市上櫃公司買回本公司股份辦法」第十一條規定之轉讓或認股辦法:
不適用
11.董事會已考慮公司財務狀況，不影響公司資本維持之聲明:
是，已聲明不影響公司資本維持
12.會計師或證券承銷商對買回股份價格之合理性評估意見:
是，已聲明不影響公司資本維持
13.其他證期局所規定之事項:
無'''


class BuybackDocumentIdentityTests(unittest.TestCase):
    def test_observed_1338_original_purpose_change_is_not_initial_board_form(self):
        body, row = fixture(PURPOSE_CHANGE, issuer='1338', date='113/11/13',
                            time='14:18:02', sequence=2,
                            subject='董事會決議通過變更原買回股份之目的申報')
        parsed = parse_identity(body, row)
        self.assertEqual(parsed['document_form'], 'purpose_change')
        self.assertTrue(parsed['required_schema_known'])
        self.assertFalse(parsed['first_field_is_board_resolution'])
        self.assertEqual(parsed['reported_datetime'], '2024-11-13T14:18:02+08:00')
        self.assertEqual(list(parsed['numbered_fields']), [str(i) for i in range(1, 14)])
        self.assertIn('1.內嵌員工辦法', parsed['numbered_fields']['9'])
        self.assertIn('轉讓或認股辦法', parsed['numbered_fields']['10'])
        self.assertEqual(parsed['description'], PURPOSE_CHANGE)

    def test_observed_1338_supplement_keeps_later_time_and_revised_field_13(self):
        revised = PURPOSE_CHANGE.removesuffix('無') + (
            '依金管會證期局規定擬修正本公司「買回股份轉讓員工辦法」\n'
            '第四條條文，並將提請最近一次董事會決議修訂。')
        body, row = fixture(revised, issuer='1338', date='113/11/20',
                            time='17:46:54', sequence=1,
                            subject='補充公告董事會決議通過變更原買回股份之目的申報\n'
                                    '(依證期局規定擬修正「13.其他證期局所規定之事項」)')
        parsed = parse_identity(body, row)
        self.assertEqual(parsed['document_form'], 'purpose_change')
        self.assertFalse(parsed['first_field_is_board_resolution'])
        self.assertEqual(parsed['reported_datetime'], '2024-11-20T17:46:54+08:00')
        self.assertIn('第四條條文', parsed['numbered_fields']['13'])
        self.assertEqual(parsed['description'], revised)
        self.assertEqual(parsed['description_sha256'], hashlib.sha256(revised.encode()).hexdigest())

    def test_purpose_change_recovery_does_not_accept_missing_duplicate_or_wrong_labels(self):
        for description in [PURPOSE_CHANGE.replace('13.其他證期局所規定之事項:\n無', ''),
                            PURPOSE_CHANGE + '\n13.其他證期局所規定之事項:\n重複',
                            PURPOSE_CHANGE.replace('5.實際買回期間', '6.實際買回期間'),
                            PURPOSE_CHANGE.replace('轉讓或認股辦法', '轉換或認股辦法')]:
            with self.subTest(description=description[-35:]):
                with self.assertRaises(ValueError):
                    parse_identity(*fixture(description))
        body, row = fixture(PURPOSE_CHANGE)
        row['CTIME'] = '17:30:24'
        with self.assertRaises(ValueError):
            parse_identity(body, row)

    def test_supported_forms_keep_every_frozen_parser_field_and_full_description(self):
        for description in [BOARD, COMPLETION, THRESHOLD]:
            with self.subTest(first_line=description.splitlines()[0]):
                body, row = fixture(description)
                old = parse_document(body, row)
                parsed = parse_identity(body, row)
                for key, value in old.items():
                    self.assertEqual(parsed[key], value)
                self.assertEqual(parsed['description'], description)
                self.assertEqual(parsed['description_sha256'],
                                 hashlib.sha256(description.encode()).hexdigest())
                self.assertTrue(parsed['required_schema_known'])
                self.assertTrue(parsed['document_identity_verified'])
                self.assertEqual(parsed['original_url'], row['HYPERLINK'])

    def test_unknown_numbered_form_keeps_identity_and_nested_clauses_without_initial_claim(self):
        body, row = fixture(UNCLASSIFIED, subject='變更買回庫藏股目的')
        parsed = parse_identity(body, row)
        self.assertEqual(parsed['issuer'], '1210')
        self.assertEqual(parsed['reported_datetime'], '2024-03-14T17:30:23+08:00')
        self.assertEqual(parsed['sequence'], 4)
        self.assertEqual(parsed['subject'], '變更買回庫藏股目的')
        self.assertEqual(parsed['description'], UNCLASSIFIED)
        self.assertEqual(parsed['description_sha256'],
                         hashlib.sha256(UNCLASSIFIED.encode()).hexdigest())
        self.assertEqual(parsed['document_form'], 'unclassified')
        self.assertEqual(parsed['numbered_fields'], {})
        self.assertFalse(parsed['required_schema_known'])
        self.assertFalse(parsed['first_field_is_board_resolution'])
        self.assertTrue(parsed['document_identity_verified'])
        self.assertNotIn('point_in_time_verified', parsed)
        self.assertNotIn('is_initial', parsed)

    def test_identity_failures_are_not_swallowed_for_unknown_forms(self):
        body, row = fixture(UNCLASSIFIED)
        for key, value in [('COMPANY_ID', '2002'), ('CDATE', '113/03/15'),
                           ('CTIME', '17:30:24'), ('SUBJECT', '另一則公告')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(row)
                changed[key] = value
                with self.assertRaises(ValueError):
                    parse_identity(body, changed)
        for old, new in [('SEQ_NO=4', 'SEQ_NO=5'), ('COMPANY_ID=1210', 'COMPANY_ID=2002'),
                         ('SPOKE_DATE=20240314', 'SPOKE_DATE=20240315'),
                         ('SPOKE_TIME=173023', 'SPOKE_TIME=173024'),
                         ('mopsov.twse.com.tw', 'example.com')]:
            with self.subTest(url_part=old):
                changed = copy.deepcopy(row)
                changed['HYPERLINK'] = row['HYPERLINK'].replace(old, new)
                with self.assertRaises(ValueError):
                    parse_identity(body, changed)

    def test_missing_metadata_invalid_clock_and_error_pages_still_fail(self):
        body, row = fixture(UNCLASSIFIED)
        for candidate in [body.replace('<th>序號</th>'.encode(), '<th>未知</th>'.encode()),
                          body.replace(b'17:30:23', b'25:30:23'), body + body,
                          b'<html>query error</html>']:
            with self.subTest(candidate=candidate[:45]):
                with self.assertRaises(ValueError):
                    parse_identity(candidate, row)
        with self.assertRaises(TypeError):
            parse_identity(body.decode(), row)

    def test_unknown_forms_support_five_or_six_digit_url_time_without_mutation(self):
        body, row = fixture(UNCLASSIFIED, time='08:44:13', issuer='4571')
        six_digit = parse_identity(body, row)
        row['HYPERLINK'] = row['HYPERLINK'].replace('SPOKE_TIME=084413', 'SPOKE_TIME=84413')
        original_row = copy.deepcopy(row)
        five_digit = parse_identity(body, row)
        self.assertEqual({k: v for k, v in five_digit.items() if k != 'original_url'},
                         {k: v for k, v in six_digit.items() if k != 'original_url'})
        self.assertEqual(row, original_row)
        self.assertEqual(five_digit['original_url'], row['HYPERLINK'])
        for bad in ['4413', '0084413', '84412', '+84413', '84:413']:
            with self.subTest(time=bad):
                changed = copy.deepcopy(row)
                changed['HYPERLINK'] = row['HYPERLINK'].replace('SPOKE_TIME=84413', 'SPOKE_TIME=' + bad)
                with self.assertRaises(ValueError):
                    parse_identity(body, changed)

    def test_known_schema_damage_and_missing_numbered_form_are_fatal(self):
        for description in [BOARD.replace('18.其他證期局所規定之事項:\n無', ''),
                            BOARD + '\n18.其他證期局所規定之事項:\n重複',
                            BOARD.replace('5.預定買回之期間', '6.預定買回之期間'),
                            '這不是編號公告', '1.沒有冒號的欄位']:
            with self.subTest(description=description[-35:]):
                with self.assertRaises(ValueError):
                    parse_identity(*fixture(description))

    def test_html_breaks_preserve_unknown_description_and_hash(self):
        body, row = fixture(UNCLASSIFIED)
        body = body.replace(UNCLASSIFIED.encode(), UNCLASSIFIED.replace('\n', '<br>').encode())
        parsed = parse_identity(body, row)
        self.assertEqual(parsed['description'], UNCLASSIFIED)
        self.assertEqual(parsed['description_sha256'],
                         hashlib.sha256(UNCLASSIFIED.encode()).hexdigest())


if __name__ == '__main__':
    unittest.main()
