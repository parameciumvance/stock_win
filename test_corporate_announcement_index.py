"""All-category controls must retain unrelated actions and issuer boundaries."""
import hashlib
import json
import unittest

from corporate_announcement_index import parse_index


def row(issuer='6674', date='115/09/18', clock='08:44:13', sequence='1', **changes):
    year, month, day = date.split('/')
    value = dict(CDATE=date, COMPANY_NAME='甲公司', AN_NAME='原類別名稱', CODE_NAME='原產業', AN_CODE='M11',
                 CTIME=clock, TYPEK='上市', SUBJECT='  原主旨 Ａ−１\n', COMPANY_ID=issuer,
                 HYPERLINK='https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1'
                 f'?COMPANY_ID={issuer}&SPOKE_DATE={int(year)+1911}{month}{day}'
                 f'&SPOKE_TIME={clock.replace(":", "")}&SEQ_NO={sequence}')
    value.update(changes)
    return value


def body(rows=None, **changes):
    value = dict(data=[row()] if rows is None else rows, status='success', message=['回傳成功'])
    value.update(changes)
    return json.dumps(value, ensure_ascii=False).encode()


class CorporateAnnouncementIndexTests(unittest.TestCase):
    def test_all_categories_and_original_fields_preserved_in_returned_order(self):
        original = [row(sequence=str(n), AN_CODE=code, TYPEK='上櫃' if n == 2 else '上市', EXTRA={'原值': n})
                    for n, code in enumerate(['M11', 'M01', 'M35', 'M99', 'M00'], 1)]
        raw = b'\xef\xbb\xbf' + body(original, total=5)
        result = parse_index(raw)
        self.assertEqual([r['original_fields'] for r in result['rows']], original)
        self.assertEqual(result['observed_categories'], ['M00', 'M01', 'M11', 'M35', 'M99'])
        self.assertEqual(result['observed_market_labels'], ['上市', '上櫃'])
        self.assertEqual(result['body_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['rows'][0]['event_id'], 'M11:6674:2026-09-18:084413:1')
        self.assertEqual(result['rows'][0]['reported_timestamp_utc'], '2026-09-18T00:44:13+00:00')
        self.assertTrue(result['count_reconciliation_passed'])
        for key in ('complete_announcement_population_verified', 'current_tradability_verified',
                    'current_transaction_status_verified', 'contractual_cash_claim_verified',
                    'historical_pit_verified', 'source_gate_passed', 'profit_edge_proven'):
            self.assertFalse(result[key], key)

    def test_each_query_rejects_other_issuer_including_parent_target_mix(self):
        self.assertEqual(parse_index(body([row(issuer='2324')]), '2324')['query_issuer'], '2324')
        for issuer, records in [('6674', [row(issuer='2324')]), ('2324', [row()]),
                                ('6674', [row(), row(issuer='2324')])]:
            with self.subTest(issuer=issuer), self.assertRaisesRegex(ValueError, 'issuer'):
                parse_index(body(records), issuer)

    def test_exact_frozen_date_boundaries_and_time_validation(self):
        self.assertEqual(parse_index(body([row(date='115/10/21')]))['current_response_row_count'], 1)
        for changes in (dict(date='115/09/17'), dict(date='115/10/22'), dict(date='115/09/31'),
                        dict(clock='24:00:00'), dict(clock='08:44:13+08:00')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_index(body([row(**changes)]))

    def test_wrong_official_url_identity_external_url_and_duplicate_query_rejected(self):
        url = row()['HYPERLINK']
        for old, new in [('6674', '2324'), ('20260918', '20260919'), ('084413', '084414'),
                         ('mopsov.twse.com.tw', 'example.org'), ('https:', 'http:')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_index(body([row(HYPERLINK=url.replace(old, new))]))
        with self.assertRaises(ValueError):
            parse_index(body([row(HYPERLINK=url + '&SEQ_NO=1')]))

    def test_same_full_pointer_is_rejected_even_with_different_reported_category(self):
        for other in [row(), row(AN_CODE='M35'), row(SUBJECT='改後主旨')]:
            with self.subTest(other=other), self.assertRaisesRegex(ValueError, 'Duplicate/conflicting'):
                parse_index(body([row(), other]))

    def test_legacy_sequence_collision_preserves_distinct_clock_pointers(self):
        result = parse_index(body([row(), row(clock='08:44:14', SUBJECT='第二公告')]))
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(len(result['legacy_sequence_collisions']), 1)
        self.assertEqual(len(result['legacy_sequence_collisions'][0]['event_ids']), 2)
        self.assertFalse(result['complete_announcement_population_verified'])

    def test_missing_total_and_empty_response_do_not_claim_complete_or_no_events(self):
        for raw in [body(), body([]), body([], total=0)]:
            result = parse_index(raw)
            self.assertFalse(result['complete_announcement_population_verified'])
            self.assertFalse(result['empty_universe_verified'])
        self.assertIsNone(parse_index(body())['declared_total'])
        self.assertFalse(parse_index(body())['count_reconciliation_passed'])

    def test_invalid_category_required_fields_counts_and_ceiling_fail(self):
        missing = row()
        missing.pop('SUBJECT')
        for raw in [body([row(AN_CODE='M1')]), body([row(AN_CODE='m11')]), body([missing]),
                    body([row(COMPANY_ID=6674)]), body(total=True), body(total=2), body([row()] * 1000)]:
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                parse_index(raw)

    def test_duplicate_json_nonfinite_malformed_or_failure_response_fail(self):
        for raw in [b'{"data":[],"data":[],"status":"success","message":["\\u56de\\u50b3\\u6210\\u529f"]}',
                    body().replace(b'"data":', b'"extra": NaN, "data":'),
                    body([row(EXTRA=1.0)]).replace(b'"EXTRA": 1.0', b'"EXTRA": 1e999'),
                    body().replace('甲公司'.encode(), b'\xff'), body()[:-2], body(status='error'),
                    body(message=['查無資料']), body(unknown='schema')]:
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                parse_index(raw)


if __name__ == '__main__':
    unittest.main()
