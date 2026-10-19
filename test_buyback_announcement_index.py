"""Announcement pointer checks do not promote returned rows to historical PIT."""
import copy
import hashlib
import json
import unittest

from buyback_announcement_index import parse_index


def row(**changes):
    value = dict(CDATE='113/12/31', COMPANY_NAME='燁輝', AN_NAME='庫藏股', CODE_NAME='鋼鐵工業',
                 AN_CODE='M35', CTIME='16:49:49', TYPEK='上市',
                 SUBJECT='公告本公司董事會通過第十五次買回庫藏股', COMPANY_ID='2023',
                 HYPERLINK='https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1?firstin=true&stp=1&step=1&SEQ_NO=2&SPOKE_TIME=164949&SPOKE_DATE=20241231&COMPANY_ID=2023')
    value.update(changes)
    return value


def response(rows=None, **changes):
    value = dict(data=[row()] if rows is None else rows, status='success', message=['回傳成功'])
    value.update(changes)
    return json.dumps(value, ensure_ascii=False).encode()


class AnnouncementIndexTests(unittest.TestCase):
    def assert_closed(self, value):
        for key in ('complete_announcement_population_verified', 'empty_universe_verified',
                    'historical_pit_verified', 'source_gate_passed', 'first_publication_time_verified',
                    'profit_edge_proven'):
            self.assertFalse(value[key], key)

    def test_observed_schema_has_success_and_no_declared_total(self):
        # The archived 122-row response uses this exact metadata shape. Counting
        # locally is not a server-declared total or a completeness certificate.
        url = row()['HYPERLINK']
        records = [row(HYPERLINK=url.replace('SEQ_NO=2', 'SEQ_NO=' + str(i)))
                   for i in range(1, 123)]
        result = parse_index(response(records))
        self.assertEqual(result['current_response_row_count'], 122)
        self.assertIsNone(result['declared_total'])
        self.assertFalse(result['count_reconciliation_passed'])
        self.assertTrue(result['returned_rows_and_urls_validated'])
        self.assert_closed(result)

    def test_bom_whitespace_original_fields_and_local_time_preserved(self):
        original = row(SUBJECT='  Ａ−１，庫藏股\n', EXTRA_ORIGINAL_FIELD='未改值')
        body = b'\xef\xbb\xbf\r\n\r\n\t' + response([original])
        result = parse_index(body)
        actual = result['rows'][0]
        self.assertEqual(actual['original_fields'], original)
        self.assertEqual(actual['reported_timestamp_taipei'], '2024-12-31T16:49:49+08:00')
        self.assertEqual(actual['reported_timestamp_utc'], '2024-12-31T08:49:49+00:00')
        self.assertEqual(actual['timezone'], 'Asia/Taipei')
        self.assertEqual(actual['event_id'], 'M35:2023:2024-12-31:2')
        self.assertEqual(result['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertIsNone(actual['announcement_kind'])
        self.assert_closed(result)

    def test_declared_total_reconciles_only_response_count(self):
        result = parse_index(response(total=1))
        self.assertEqual(result['declared_total'], 1)
        self.assertTrue(result['count_reconciliation_passed'])
        self.assert_closed(result)
        for total in (0, 2, -1, 1000, True, '1', None):
            with self.subTest(total=total), self.assertRaises(ValueError):
                parse_index(response(total=total))

    def test_truncated_json_and_declared_data_truncation_rejected(self):
        with self.assertRaises(ValueError):
            parse_index(response()[:-8])
        with self.assertRaises(ValueError):
            parse_index(response(total=122))
        with self.assertRaises(ValueError):
            parse_index(response([row()] * 1000))

    def test_strict_json_rejects_duplicate_keys_constants_and_invalid_utf8(self):
        for body in (b'{"data":[],"data":[],"status":"success","message":[]}',
                     b'{"data":[],"status":"success","message":[],"total":NaN}',
                     response().replace('燁輝'.encode(), b'\xff'), response() + b'trailing'):
            with self.subTest(body=body[:60]), self.assertRaises(ValueError):
                parse_index(body)

    def test_wrong_response_status_message_or_schema_fails(self):
        for changes in (dict(status='error'), dict(message=['查詢過量']), dict(data={}),
                        dict(totalCount=1)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_index(response(**changes))
        with self.assertRaises(ValueError):
            parse_index(b'[]')

    def test_wrong_market_or_event_category_fails(self):
        for changes in (dict(TYPEK='上櫃'), dict(AN_CODE='M34'), dict(COMPANY_ID=2023)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_index(response([row(**changes)]))

    def test_invalid_or_out_of_range_roc_dates_fail(self):
        for date in ('113/02/30', '112/12/31', '114/01/01', '24/12/31', '2024-12-31'):
            with self.subTest(date=date), self.assertRaises(ValueError):
                parse_index(response([row(CDATE=date)]))

    def test_invalid_time_or_timezone_suffix_fails(self):
        for clock in ('24:00:00', '16:60:00', '16:49:60', '16:49:49+08:00', '１６:49:49', '8:00:00'):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                parse_index(response([row(CTIME=clock)]))

    def test_url_time_is_local_not_utc_and_all_identity_fields_must_agree(self):
        original = row()
        for before, after in (('164949', '084949'), ('20241231', '20241230'),
                              ('COMPANY_ID=2023', 'COMPANY_ID=2467')):
            bad = {**original, 'HYPERLINK': original['HYPERLINK'].replace(before, after)}
            with self.subTest(before=before), self.assertRaises(ValueError):
                parse_index(response([bad]))

    def test_observed_url_hmmss_form_matches_local_time_without_rewriting(self):
        # The actual 4571 113/02/07 row reports 08:44:13 and SPOKE_TIME=84413.
        source = row(COMPANY_ID='4571', CDATE='113/02/07', CTIME='08:44:13')
        source['HYPERLINK'] = (source['HYPERLINK'].replace('COMPANY_ID=2023', 'COMPANY_ID=4571')
                               .replace('20241231', '20240207').replace('164949', '84413'))
        actual = parse_index(response([source]))['rows'][0]
        self.assertEqual(actual['url'], source['HYPERLINK'])
        self.assertEqual(actual['url_query']['SPOKE_TIME'], '84413')
        self.assertEqual(actual['reported_timestamp_taipei'], '2024-02-07T08:44:13+08:00')

    def test_url_must_be_the_expected_https_host_path_without_credentials(self):
        original = row()['HYPERLINK']
        for url in (original.replace('https:', 'http:'),
                    original.replace('mopsov.twse.com.tw', 'foreign.example'),
                    original.replace('mopsov.twse.com.tw', 'mopsov.twse.com.tw.evil.example'),
                    original.replace('mopsov.twse.com.tw', 'user@mopsov.twse.com.tw'),
                    original.replace('mopsov.twse.com.tw', 'mopsov.twse.com.tw:444'),
                    original.replace('ajax_t05sr01_1', 'ajax_t05sr01_2'), original + '#fragment'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_index(response([row(HYPERLINK=url)]))

    def test_duplicate_url_keys_including_percent_encoded_key_fail(self):
        original = row()['HYPERLINK']
        for addition in ('&COMPANY_ID=2023', '&%43OMPANY_ID=2023', '&step=1'):
            with self.subTest(addition=addition), self.assertRaises(ValueError):
                parse_index(response([row(HYPERLINK=original + addition)]))

    def test_missing_identity_blank_sequence_and_malformed_escaping_fail(self):
        original = row()['HYPERLINK']
        for url in (original.replace('&COMPANY_ID=2023', ''), original.replace('SEQ_NO=2', 'SEQ_NO='),
                    original.replace('SEQ_NO=2', 'SEQ_NO=02'), original + '&x=%ZZ'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_index(response([row(HYPERLINK=url)]))

    def test_duplicate_event_id_fails_even_if_order_of_url_parameters_changes(self):
        original = row()
        duplicate = copy.deepcopy(original)
        base, query = duplicate['HYPERLINK'].split('?')
        duplicate['HYPERLINK'] = base + '?' + '&'.join(reversed(query.split('&')))
        with self.assertRaises(ValueError):
            parse_index(response([original, duplicate]))

    def test_same_company_date_sequence_with_changed_time_is_conflict(self):
        original = row()
        changed = row(CTIME='16:49:50', HYPERLINK=original['HYPERLINK'].replace('164949', '164950'))
        with self.assertRaises(ValueError):
            parse_index(response([original, changed]))

    def test_distinct_sequences_retained_without_subject_classification(self):
        original = row()
        changed = row(SUBJECT='買回庫藏股期間屆滿及執行情形',
                      HYPERLINK=original['HYPERLINK'].replace('SEQ_NO=2', 'SEQ_NO=3'))
        result = parse_index(response([original, changed]))
        self.assertEqual(len(result['rows']), 2)
        self.assertTrue(all(r['announcement_kind'] is None for r in result['rows']))
        self.assert_closed(result)

    def test_empty_success_is_only_zero_returned_rows(self):
        result = parse_index(response([]))
        self.assertEqual(result['current_response_row_count'], 0)
        self.assertIsNone(result['declared_total'])
        self.assertFalse(result['count_reconciliation_passed'])
        self.assert_closed(result)

    def test_original_bytes_and_valid_query_boundaries_required(self):
        with self.assertRaises(TypeError):
            parse_index(response().decode())
        for start, end in (('2024-1-1', '2024-12-31'), ('2024-12-31', '2024-01-01'),
                           ('2024-01-01', '2024-02-30')):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                parse_index(response(), start=start, end=end)


if __name__ == '__main__':
    unittest.main()
