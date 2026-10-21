"""M11 controls: preserve broad subjects/markets and reject identity ambiguity."""
import hashlib
import json
import unittest

from merger_announcement_index import parse_index


def row(**changes):
    value = dict(CDATE='115/07/01', COMPANY_NAME='甲公司', AN_NAME='發行有價證券、減資、併購或股份轉交換',
                 CODE_NAME='其他業', AN_CODE='M11', CTIME='08:44:13', TYPEK='上市',
                 SUBJECT='董事會決議發行公司債', COMPANY_ID='1234',
                 HYPERLINK='https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1?firstin=true&step=1&stp=1&COMPANY_ID=1234&SPOKE_DATE=20260701&SPOKE_TIME=84413&SEQ_NO=1')
    value.update(changes)
    return value


def body(rows=None, **changes):
    response = dict(data=[row()] if rows is None else rows, status='success', message=['回傳成功'])
    response.update(changes)
    return json.dumps(response, ensure_ascii=False).encode()


class MergerIndexTests(unittest.TestCase):
    def assert_unqualified(self, result):
        for key in ('historical_listing_status_verified', 'complete_announcement_population_verified',
                    'empty_universe_verified', 'historical_pit_verified', 'source_gate_passed',
                    'first_publication_time_verified', 'profit_edge_proven',
                    'semantic_cash_merger_selection_performed'):
            self.assertFalse(result[key], key)
        self.assertIsNone(result['eligible_cash_merger_count'])

    def test_bom_preserves_broad_capital_action_and_original_fields(self):
        source = row(SUBJECT='  現金增資 Ａ−１，公告\n', EXTRA='未改值')
        raw = b'\xef\xbb\xbf\r\n' + body([source])
        result = parse_index(raw)
        self.assertEqual(result['rows'][0]['original_fields'], source)
        self.assertEqual(result['rows'][0]['event_id'], 'M11:1234:2026-07-01:1')
        self.assertEqual(result['rows'][0]['reported_timestamp_taipei'], '2026-07-01T08:44:13+08:00')
        self.assertEqual(result['rows'][0]['reported_timestamp_utc'], '2026-07-01T00:44:13+00:00')
        self.assertEqual(result['body_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertTrue(result['query_market_qualified'])
        self.assertIsNone(result['rows'][0]['eligible_cash_merger'])
        self.assert_unqualified(result)

    def test_other_market_is_retained_and_does_not_qualify_query(self):
        source = row(TYPEK='上櫃', HYPERLINK=row()['HYPERLINK'].replace('SEQ_NO=1', 'SEQ_NO=2'))
        result = parse_index(body([row(), source]))
        self.assertEqual(result['current_response_row_count'], 2)
        self.assertEqual([r['original_fields']['TYPEK'] for r in result['rows']], ['上市', '上櫃'])
        self.assertEqual(result['observed_market_labels'], ['上市', '上櫃'])
        self.assertFalse(result['query_market_qualified'])
        self.assert_unqualified(result)

    def test_wrong_category_or_date_or_clock_fails(self):
        for changes in (dict(AN_CODE='M35'), dict(CDATE='115/06/30'), dict(CDATE='115/10/01'),
                        dict(CDATE='115/09/31'), dict(CTIME='24:00:00'), dict(CTIME='08:44:13Z')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_index(body([row(**changes)]))

    def test_detail_pointer_must_match_local_date_time_and_issuer(self):
        url = row()['HYPERLINK']
        for old, new in (('COMPANY_ID=1234', 'COMPANY_ID=9999'), ('20260701', '20260702'),
                         ('SPOKE_TIME=84413', 'SPOKE_TIME=004413')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_index(body([row(HYPERLINK=url.replace(old, new))]))

    def test_external_or_duplicate_query_key_is_rejected(self):
        url = row()['HYPERLINK']
        for bad in (url.replace('mopsov.twse.com.tw', 'foreign.example'),
                    url.replace('https:', 'http:'), url + '&step=1', url + '&%43OMPANY_ID=1234'):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                parse_index(body([row(HYPERLINK=bad)]))

    def test_same_identity_duplicate_or_changed_time_is_not_a_new_event(self):
        first = row()
        changed = row(CTIME='08:44:14', HYPERLINK=first['HYPERLINK'].replace('84413', '84414'))
        for second in (row(), changed):
            with self.subTest(second=second['CTIME']), self.assertRaises(ValueError):
                parse_index(body([first, second]))

    def test_declared_count_mismatch_and1000_ceiling_fail_closed(self):
        result = parse_index(body(total=1))
        self.assertTrue(result['count_reconciliation_passed'])
        self.assert_unqualified(result)
        for raw in (body(total=2), body(total=True), body([row()] * 1000)):
            with self.assertRaises(ValueError):
                parse_index(raw)

    def test_missing_total_and_zero_rows_are_not_complete_or_qualified_market(self):
        result = parse_index(body([]))
        self.assertIsNone(result['declared_total'])
        self.assertFalse(result['count_reconciliation_passed'])
        self.assertFalse(result['query_market_qualified'])
        self.assertEqual(result['current_response_row_count'], 0)
        self.assert_unqualified(result)

    def test_strict_json_failure_status_and_truncation_fail(self):
        for raw in (body()[:-3], body(status='error'), body(message=['查詢過量']),
                    body().replace('甲公司'.encode(), b'\xff'),
                    b'{"data":[],"data":[],"status":"success","message":[]}',
                    b'{"data":[],"status":"success","message":[],"total":NaN}'):
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                parse_index(raw)


if __name__ == '__main__':
    unittest.main()
