"""Synthetic strict scopes and exact month comparisons; no market outcomes."""
import copy
import hashlib
import json
import unittest

from frontier_cb_calendar import FIELDS, parse_calendar, reconcile_month


ROWS = [['14364', '原名稱', '115/10/08', '103.0225', '1.5000'],
        ['33466', '原名稱二', '115/11/03', '100.5000', '0.2500'],
        ['99588', '原名稱三', '115/11/08', '100.5000', '0.2500'],
        ['140201', '原名稱四', '116/04/25', '100.0000', '0.0000']]


def payload(rows=None, *, narrow=False):
    roc = '115/11/01~115/11/30' if narrow else '115/10/01~116/04/30'
    rows = copy.deepcopy(ROWS[1:3] if narrow else ROWS) if rows is None else rows
    return dict(tables=[dict(title=roc + '轉(交)換公司債賣回權資料統計表', date=roc,
                             fields=FIELDS, data=rows, totalCount=len(rows), notes=[], summary=[])],
                date='20261101~20261130' if narrow else '20261001~20270430', stat='ok')


def body(value):
    return json.dumps(value, ensure_ascii=False).encode()


def narrow(value=None):
    return parse_calendar(body(payload(narrow=True) if value is None else value), '2026-11-01', '2026-11-30')


class FrontierCBCalendarTests(unittest.TestCase):
    def test_declared_full_months_preserve_rows_outside_requested_days(self):
        source = body(payload())
        result = parse_calendar(source)
        self.assertEqual(result['source_sha256'], hashlib.sha256(source).hexdigest())
        self.assertEqual(result['record_count'], 4)
        self.assertEqual(result['declared_range'], {'start': '2026-10-01', 'end': '2027-04-30'})
        self.assertEqual(result['requested_range'], {'start': '2026-10-20', 'end': '2027-04-20'})
        self.assertEqual(len(result['records_outside_requested_days']), 2)
        self.assertEqual([r['original_fields'] for r in result['records']], ROWS)
        self.assertTrue(result['whole_month_normalization_applied'])
        self.assertFalse(result['day_range_filter_applied'])

    def test_exact_november_subset_agrees_independent_of_row_order(self):
        wide = parse_calendar(body(payload()))
        result = reconcile_month(wide, narrow(payload(list(reversed(ROWS[1:3])), narrow=True)))
        self.assertTrue(result['current_snapshot_month_agreement'])
        self.assertEqual(result['wide_subset_count'], 2)
        self.assertEqual(result['narrow_count'], 2)
        self.assertFalse(result['records_merged'])

    def test_missing_new_and_changed_values_are_retained_not_patched(self):
        wide = parse_calendar(body(payload()))
        changed = copy.deepcopy(ROWS[1:3])
        changed[0][3] = '101.0000'
        changed[1] = ['68351', '新記錄', '115/11/04', '100.0000', '0.0000']
        result = reconcile_month(wide, narrow(payload(changed, narrow=True)))
        self.assertFalse(result['current_snapshot_month_agreement'])
        self.assertEqual(len(result['differences']['missing_from_narrow']), 1)
        self.assertEqual(len(result['differences']['new_in_narrow']), 1)
        self.assertEqual(result['differences']['changed_original_fields'][0]['wide'], ROWS[1])
        self.assertEqual(wide['records'][1]['original_fields'], ROWS[1])

    def test_duplicate_json_nonfinite_and_truncated_count_are_rejected(self):
        duplicate = body(payload()).replace(b'"stat": "ok"', b'"stat": "ok", "stat": "ok"')
        mismatch = payload()
        mismatch['tables'][0]['totalCount'] = 100
        boolean = payload()
        boolean['tables'][0]['totalCount'] = True
        for value in (duplicate, b'{"tables":NaN}', b'{', body(mismatch), body(boolean)):
            with self.subTest(value=value[:70]), self.assertRaises(ValueError):
                parse_calendar(value)

    def test_bad_scope_roc_dates_duplicate_keys_and_numeric_fields_fail(self):
        for failure in ('top_range', 'table_range', 'bad_date', 'out_of_scope', 'duplicate', 'numeric', 'code'):
            value = payload()
            table = value['tables'][0]
            if failure == 'top_range':
                value['date'] = '20261020~20270420'
            elif failure == 'table_range':
                table['date'] = '115/10/20~116/04/20'
            elif failure == 'bad_date':
                table['data'][0][2] = '115/11/31'
            elif failure == 'out_of_scope':
                table['data'][0][2] = '115/09/30'
            elif failure == 'duplicate':
                table['data'].append(copy.deepcopy(table['data'][0])); table['totalCount'] += 1
            elif failure == 'numeric':
                table['data'][0][4] = 'Infinity'
            else:
                table['data'][0][0] = 'CODE'
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                parse_calendar(body(value))

    def test_zero_amount_weekend_and_reported_yield_never_grant_eligibility(self):
        rows = copy.deepcopy(ROWS)
        rows[2][3] = '0.0000'
        result = parse_calendar(body(payload(rows)))
        self.assertEqual(result['records'][2]['reported_put_amount'], '0.0000')
        self.assertEqual(result['records'][2]['contract_reported_put_yield'], '0.2500')
        self.assertIn('nonpositive_put_amount_unresolved', {i['kind'] for i in result['issues']})
        self.assertIn('weekend_nominal_put_date_no_shift', {i['kind'] for i in result['issues']})
        self.assertEqual(result['records'][2]['put_date'], '2026-11-08')
        for flag in ('reported_put_yield_is_holder_future_return', 'business_day_shifts_applied',
                     'notice_window_verified', 'payment_date_verified', 'holder_put_eligibility_verified',
                     'current_tradability_verified', 'complete_population_verified',
                     'historical_pit_verified', 'source_gate_passed'):
            self.assertFalse(result[flag], flag)

    def test_schema_shape_and_original_string_types_are_strict(self):
        for failure in ('extra_field', 'wrong_labels', 'four_columns', 'number_type', 'error_status'):
            value = payload()
            table = value['tables'][0]
            if failure == 'extra_field':
                table['unexpected'] = 'not observed'
            elif failure == 'wrong_labels':
                table['fields'] = FIELDS[::-1]
            elif failure == 'four_columns':
                table['data'][0].pop()
            elif failure == 'number_type':
                table['data'][0][3] = 100
            else:
                value['stat'] = 'error'
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                parse_calendar(body(value))

    def test_reconcile_requires_exact_requested_month_scope(self):
        wide = parse_calendar(body(payload()))
        for month in ('2026-1', '2026-13', '2026-12', '2027-11'):
            with self.subTest(month=month), self.assertRaises(ValueError):
                reconcile_month(wide, narrow(), month)


if __name__ == '__main__':
    unittest.main()
