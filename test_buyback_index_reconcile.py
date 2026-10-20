"""Date-partition agreement must preserve disagreements and research limits."""
import copy
import datetime as dt
import json
import unittest

from buyback_index_reconcile import BOUNDARY_SCOPES, MONTHS, reconcile


def row(day='2024-01-02', sequence=1, issuer='2002', **changes):
    date = dt.date.fromisoformat(day)
    value = dict(
        CDATE=f'{date.year - 1911:03d}/{date.month:02d}/{date.day:02d}',
        COMPANY_NAME='原公司', AN_NAME='庫藏股', CODE_NAME='原產業', AN_CODE='M35',
        CTIME='19:36:39', TYPEK='上市', SUBJECT='原公告', COMPANY_ID=issuer,
        HYPERLINK=('https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1'
                   f'?SEQ_NO={sequence}&SPOKE_TIME=193639'
                   f'&SPOKE_DATE={date:%Y%m%d}&COMPANY_ID={issuer}'),
    )
    value.update(changes)
    return value


def response(rows, **metadata):
    return json.dumps(dict(data=rows, status='success', message=['回傳成功'],
                           **metadata), ensure_ascii=False).encode()


def fixture(rows=None):
    rows = [row(), row('2024-02-29', issuer='8070')] if rows is None else rows
    monthly = {month: response([]) for month in MONTHS}
    for month in MONTHS:
        included = [r for r in rows
                    if f'{int(r["CDATE"][:3]) + 1911:04d}-{r["CDATE"][4:6]}' == month]
        monthly[month] = response(included)
    boundaries = {
        '2023Q4': response([row('2023-12-31')]),
        '2025Q1': response([row('2025-01-01')]),
    }
    return response(rows), monthly, boundaries


class BuybackIndexReconcileTests(unittest.TestCase):
    def assert_closed(self, result):
        for key in ('complete_announcement_population_verified',
                    'empty_universe_verified', 'historical_pit_verified',
                    'first_publication_time_verified', 'source_gate_passed',
                    'profit_edge_proven', 'boundary_rows_merged_into_2024'):
            self.assertFalse(result[key], key)

    def test_all_twelve_partitions_agree_without_declared_totals(self):
        annual, monthly, boundaries = fixture()
        result = reconcile(annual, monthly, boundaries)
        self.assertTrue(result['current_snapshot_partition_agreement'])
        self.assertEqual(result['monthly_counts'],
                         {month: int(month in ('2024-01', '2024-02')) for month in MONTHS})
        self.assertEqual(result['monthly_total_returned_rows'], 2)
        self.assertIsNone(result['annual_index']['declared_total'])
        self.assertEqual(result['differences'], dict(missing_from_monthly=[],
                                                    new_in_monthly=[],
                                                    changed_original_fields=[]))
        self.assert_closed(result)

    def test_all_empty_responses_can_agree_without_certifying_empty_universe(self):
        result = reconcile(*fixture([]))
        self.assertTrue(result['current_snapshot_partition_agreement'])
        self.assertEqual(result['monthly_total_returned_rows'], 0)
        self.assert_closed(result)

    def test_missing_and_new_rows_are_retained_without_replacing_annual(self):
        annual, monthly, boundaries = fixture()
        monthly['2024-01'] = response([row('2024-01-03', sequence=2)])
        result = reconcile(annual, monthly, boundaries)
        self.assertFalse(result['current_snapshot_partition_agreement'])
        delta = result['differences']
        self.assertEqual(delta['missing_from_monthly'][0]['event_id'], 'M35:2002:2024-01-02:1')
        self.assertEqual(delta['new_in_monthly'][0]['event_id'], 'M35:2002:2024-01-03:2')
        self.assertEqual(delta['new_in_monthly'][0]['month'], '2024-01')
        self.assertEqual(result['annual_index']['rows'][0]['original_fields'], row())
        self.assertNotIn('M35:2002:2024-01-03:2',
                         [r['event_id'] for r in result['annual_index']['rows']])
        self.assert_closed(result)

    def test_changed_field_keeps_both_exact_original_values(self):
        original = row(SUBJECT=' 原主旨\n', ORIGINAL_EXTRA='舊值')
        annual, monthly, boundaries = fixture([original])
        monthly['2024-01'] = response([row(SUBJECT='新主旨 ', ORIGINAL_EXTRA='新值')])
        result = reconcile(annual, monthly, boundaries)
        self.assertFalse(result['current_snapshot_partition_agreement'])
        changed = result['differences']['changed_original_fields']
        self.assertEqual(len(changed), 1)
        fields = {d['field']: d for d in changed[0]['field_differences']}
        self.assertEqual(fields['SUBJECT']['annual_value'], ' 原主旨\n')
        self.assertEqual(fields['SUBJECT']['monthly_value'], '新主旨 ')
        self.assertEqual(fields['ORIGINAL_EXTRA']['annual_value'], '舊值')
        self.assertEqual(fields['ORIGINAL_EXTRA']['monthly_value'], '新值')
        self.assertEqual(changed[0]['annual_row']['original_fields'], original)

    def test_added_removed_and_null_fields_are_distinct(self):
        annual, monthly, boundaries = fixture([row(OLD=None)])
        monthly['2024-01'] = response([row(NEW=None)])
        result = reconcile(annual, monthly, boundaries)
        fields = {d['field']: d for d in
                  result['differences']['changed_original_fields'][0]['field_differences']}
        self.assertEqual(fields['OLD'], dict(field='OLD', annual_present=True,
                                            monthly_present=False, annual_value=None))
        self.assertEqual(fields['NEW'], dict(field='NEW', annual_present=False,
                                            monthly_present=True, monthly_value=None))

    def test_original_json_types_are_not_collapsed_by_python_equality(self):
        annual, monthly, boundaries = fixture([row(EXTRA={'nested': [False]})])
        monthly['2024-01'] = response([row(EXTRA={'nested': [0]})])
        result = reconcile(annual, monthly, boundaries)
        self.assertFalse(result['current_snapshot_partition_agreement'])
        fields = result['differences']['changed_original_fields'][0]['field_differences']
        self.assertEqual(fields[0]['field'], 'EXTRA')

    def test_row_order_and_original_object_key_order_do_not_create_changes(self):
        first, second = row(sequence=1), row(sequence=2)
        annual, monthly, boundaries = fixture([first, second])
        monthly['2024-01'] = response([dict(reversed(list(second.items()))), first])
        self.assertTrue(reconcile(annual, monthly, boundaries)
                        ['current_snapshot_partition_agreement'])

    def test_monthly_dates_must_match_actual_month_including_leap_day(self):
        annual, monthly, boundaries = fixture()
        monthly['2024-01'] = response([row('2024-02-29')])
        with self.assertRaisesRegex(ValueError, 'month 2024-01'):
            reconcile(annual, monthly, boundaries)
        monthly['2024-01'] = response([row(CDATE='113/02/30')])
        with self.assertRaises(ValueError):
            reconcile(annual, monthly, boundaries)

    def test_exact_month_and_boundary_keys_are_required(self):
        for which in ('monthly', 'boundary'):
            for change in ('remove', 'extra'):
                annual, monthly, boundaries = fixture()
                values = monthly if which == 'monthly' else boundaries
                if change == 'remove':
                    values.pop(next(iter(values)))
                else:
                    values['unexpected'] = response([])
                with self.subTest(which=which, change=change), self.assertRaises(ValueError):
                    reconcile(annual, monthly, boundaries)

    def test_boundary_rows_are_preserved_separately_on_their_own_scopes(self):
        result = reconcile(*fixture())
        self.assertEqual(set(result['boundary_indices']), set(BOUNDARY_SCOPES))
        self.assertEqual(result['boundary_indices']['2023Q4']['rows'][0]
                         ['original_fields']['CDATE'], '112/12/31')
        self.assertEqual(result['boundary_indices']['2025Q1']['rows'][0]
                         ['original_fields']['CDATE'], '114/01/01')
        self.assertEqual(result['annual_index']['current_response_row_count'], 2)
        self.assertEqual(result['monthly_total_returned_rows'], 2)
        self.assert_closed(result)

    def test_boundary_out_of_scope_dates_fail_instead_of_merging(self):
        for label, day in [('2023Q4', '2024-01-01'), ('2023Q4', '2023-09-30'),
                           ('2025Q1', '2024-12-31'), ('2025Q1', '2025-04-01')]:
            annual, monthly, boundaries = fixture()
            boundaries[label] = response([row(day)])
            with self.subTest(label=label, day=day), self.assertRaisesRegex(ValueError, 'boundary ' + label):
                reconcile(annual, monthly, boundaries)

    def test_duplicate_identity_in_any_source_is_rejected(self):
        for source in ('annual', 'monthly', 'boundary'):
            annual, monthly, boundaries = fixture()
            if source == 'annual':
                annual = response([row(), row()])
            elif source == 'monthly':
                monthly['2024-01'] = response([row(), row()])
            else:
                boundaries['2023Q4'] = response([row('2023-12-31')] * 2)
            with self.subTest(source=source), self.assertRaises(ValueError):
                reconcile(annual, monthly, boundaries)

    def test_changed_clock_on_same_identity_is_field_difference(self):
        annual, monthly, boundaries = fixture([row()])
        changed = row(CTIME='19:36:40')
        changed['HYPERLINK'] = changed['HYPERLINK'].replace('193639', '193640')
        monthly['2024-01'] = response([changed])
        result = reconcile(annual, monthly, boundaries)
        self.assertFalse(result['current_snapshot_partition_agreement'])
        self.assertEqual(result['differences']['missing_from_monthly'], [])
        self.assertEqual(result['differences']['new_in_monthly'], [])
        fields = result['differences']['changed_original_fields'][0]['field_differences']
        self.assertEqual([d['field'] for d in fields], ['CTIME', 'HYPERLINK'])

    def test_invalid_json_and_declared_count_mismatch_fail(self):
        for body in (b'{', response([row()], total=2), response([row()] * 1000)):
            annual, monthly, boundaries = fixture()
            monthly['2024-01'] = body
            with self.subTest(body=body[:60]), self.assertRaises(ValueError):
                reconcile(annual, monthly, boundaries)

    def test_inputs_are_not_mutated_and_totals_do_not_promote_pit(self):
        annual, monthly, boundaries = fixture()
        monthly['2024-01'] = response([row()], total=1)
        before = copy.deepcopy((annual, monthly, boundaries))
        result = reconcile(annual, monthly, boundaries)
        self.assertEqual((annual, monthly, boundaries), before)
        self.assertTrue(result['current_snapshot_partition_agreement'])
        self.assertTrue(result['monthly_indices']['2024-01']['count_reconciliation_passed'])
        self.assert_closed(result)


if __name__ == '__main__':
    unittest.main()
