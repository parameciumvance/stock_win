"""Synthetic meeting-clock and source-anchor controls; no source/quote IO."""
from html import escape
import unittest

from cash_merger_current_notices_independent import (
    compare_meetings, digest, read_notice, verify_annotation,
)


def source():
    return dict(CDATE='115/09/18', COMPANY_NAME='甲公司', AN_NAME='股東會召集',
                CODE_NAME='原產業', AN_CODE='M17', CTIME='20:25:33', TYPEK='上市',
                SUBJECT='召開股東臨時會', COMPANY_ID='6674',
                HYPERLINK='https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1?firstin=true&stp=1&step=1'
                          '&SEQ_NO=4&SPOKE_TIME=202533&SPOKE_DATE=20260918&COMPANY_ID=6674')


def meeting(venue='原址', day='115/11/09', closure='115/10/11'):
    return (f'1.董事會決議日期：115/09/18\n2.股東臨時會召開日期：{day}\n3.地點：{venue}\n'
            '4.召開方式：實體\n5.報告事項\n(1)審議報告\n6.討論事項：股份轉換\n'
            f'7.臨時動議：\n8.停止過戶起始日期：{closure}\n9.停止過戶截止日期：115/11/09\n'
            '10.電子表決期間：115/10/25至115/11/06')


def document(description, extra=''):
    s = source()
    return ('<html><head><link href="css/css2.css"><script src="js/mops2.js"></script>' + extra
            + '</head><table><tr><td>本資料由 (上市公司) 6674 甲公司 公司提供</td></tr>'
            '<tr><th>序號</th><td>4</td><th>發言日期</th><td>115/09/18</td>'
            '<th>發言時間</th><td>20:25:33</td></tr><tr><th>主旨</th><td>' + s['SUBJECT']
            + '</td></tr><tr><th>說明</th><td><pre>' + escape(description)
            + '</pre></td></tr></table></html>').encode()


class IndependentNoticeReadingTests(unittest.TestCase):
    def test_only_venue_change_does_not_turn_meeting_bookclosure_into_cash_record_date(self):
        compared = compare_meetings(meeting(), meeting(venue='新址'))
        self.assertEqual(compared['changed_numbered_fields'], [3])
        self.assertTrue(compared['venue_only_change'])
        self.assertFalse(compared['shareholder_meeting_bookclosure_is_cash_record_date'])

    def test_changed_meeting_date_or_registration_window_is_not_venue_only(self):
        for changed in (meeting(venue='新址', day='115/11/10'),
                        meeting(venue='新址', closure='115/10/12')):
            with self.subTest(changed=changed):
                compared = compare_meetings(meeting(), changed)
                self.assertFalse(compared['venue_only_change'])
                self.assertFalse(compared['shareholder_meeting_bookclosure_is_cash_record_date'])

    def test_missing_or_duplicate_field_cannot_pass_complete_meeting_comparison(self):
        for bad in (meeting().replace('9.停止過戶截止日期：115/11/09\n', ''),
                    meeting() + '\n3.第二個地點：含糊'):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                compare_meetings(meeting(), bad)

    def test_full_description_and_all_declared_pointers_preserved_without_execution(self):
        text = meeting()
        raw = document(text, '<a href="https://official.example/contract.pdf?x=1&amp;y=2">附件</a>')
        doc, retained = read_notice(raw, source())
        self.assertEqual(retained, text)
        self.assertEqual(doc['body_sha256'], digest(raw))
        self.assertEqual(doc['description_sha256'], digest(text.encode()))
        self.assertEqual([p['value'] for p in doc['pointers']],
                         ['css/css2.css', 'js/mops2.js', 'https://official.example/contract.pdf?x=1&y=2'])

    def test_identity_mismatch_or_duplicate_notice_record_fails(self):
        raw = document(meeting())
        for bad in (raw.replace(b'20:25:33', b'20:25:34'), raw + raw,
                    raw.replace(b'6674', b'2324')):
            with self.subTest(body=bad[:40]), self.assertRaises(ValueError):
                read_notice(bad, source())
        changed = source() | {'HYPERLINK': source()['HYPERLINK'].replace('202533', '202534')}
        with self.assertRaises(ValueError):
            read_notice(raw, changed)

    def test_annotation_rejects_source_or_numbered_anchor_drift(self):
        doc, description = read_notice(document(meeting()), source())
        base = dict(event_id=doc['event_id'], body_sha256=doc['body_sha256'],
                    description_sha256=doc['description_sha256'], anchors=['股東臨時會召開日期：115/11/09'])
        self.assertIsNone(verify_annotation(dict(rows=[base]), [doc], {doc['event_id']: description}))
        for changed in (base | {'body_sha256': '0' * 64},
                        base | {'anchors': ['股東臨時會召開日期：115/11/10']}, base | {'anchors': []}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                verify_annotation(dict(rows=[changed]), [doc], {doc['event_id']: description})
        with self.assertRaises(ValueError):
            verify_annotation(dict(rows=[base]), [doc], {doc['event_id']: description + '\n未封存的新條款'})


if __name__ == '__main__':
    unittest.main()
