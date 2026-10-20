"""Retained board versions cannot be promoted into first-publication proof."""
import copy
import unittest

from buyback_case_replay import link_cases


def annual(*keys):
    return dict(rows=[dict(original_columns=[str(i), issuer, '原名稱', board] + [''] * 16)
                      for i, (issuer, board) in enumerate(keys, 1)])


def document(*, issuer='1210', board='113/03/14', stamp='2024-03-14T17:30:23+08:00',
             sequence=4, subject='董事會決議申請庫藏股買回', form='board_resolution',
             fields=None):
    return dict(event_id=f'M35:{issuer}:{stamp[:10]}:{sequence}', issuer=issuer,
                reported_datetime=stamp, sequence=sequence, subject=subject, document_form=form,
                numbered_fields=(fields if fields is not None else {
                    '1': '1.董事會決議日期:' + board,
                    '4': '4.買回股份總金額上限(元):11,822,719,947',
                    '5': '5.預定買回之期間:113/03/15~113/05/14',
                    '6': '6.預定買回之數量(股):9,000,000',
                    '7': '7.買回區間價格(元):50.00~80.00',
                    '14': '14.原轉讓辦法:長篇原文留在來源包',
                }))


class BuybackCaseReplayTests(unittest.TestCase):
    def assert_closed(self, result):
        self.assertTrue(result['earliest_retained_is_not_first_ever'])
        for field in ('historical_pit_verified', 'first_publication_time_verified',
                      'source_gate_passed', 'profit_edge_proven', 'outcome_based_case_exclusion'):
            self.assertFalse(result[field], field)

    def test_same_day_completion_is_not_the_new_board_record(self):
        closing = document(stamp='2024-03-14T15:00:00+08:00', sequence=2,
                           form='completion', subject='本次執行完畢',
                           fields={'1': '1.原預定買回股份總金額上限(元):100'})
        board = document()
        result = link_cases(annual(('1210', '113/03/14')), [closing, board])
        self.assertEqual(len(result['cases'][0]['versions']), 1)
        self.assertEqual(result['cases'][0]['earliest_retained_record']['event_id'], board['event_id'])
        self.assertEqual(result['non_board_documents'][0]['event_id'], closing['event_id'])
        self.assertEqual(result['completion_linkage_status'], 'not_inferred')
        self.assert_closed(result)

    def test_corrections_allow_quantity_and_price_changes_and_retain_every_version(self):
        first = document()
        correction = document(stamp='2024-03-19T14:44:21+08:00', sequence=2, subject='更正董事會決議')
        correction['numbered_fields'].update({'4': '4.買回股份總金額上限(元):11,779,724,865',
                                             '6': '6.預定買回之數量(股):8,000,000',
                                             '7': '7.買回區間價格(元):49.00~81.00',
                                             '14': '14.原轉讓辦法:修正長篇原文'})
        result = link_cases(annual(('1210', '113/03/14')), [correction, first])
        versions = result['cases'][0]['versions']
        self.assertEqual([v['event_id'] for v in versions], [first['event_id'], correction['event_id']])
        changes = {v['field']: v for v in versions[1]['changes_from_previous']}
        self.assertEqual(set(changes), {'4', '6', '7', '14'})
        self.assertEqual(changes['6']['previous_value'], first['numbered_fields']['6'])
        self.assertEqual(changes['6']['current_value'], correction['numbered_fields']['6'])
        self.assertNotIn('current_value', changes['14'])
        self.assertNotIn('14', versions[1]['numbered_fields'])
        self.assertIn('14', versions[1]['numbered_field_sha256'])
        self.assertFalse(result['cases'][0]['missing_initial_evidence'])
        self.assert_closed(result)

    def test_earliest_correction_or_supplement_remains_missing_initial_evidence(self):
        for subject in ('更正董事會決議', '補充公告董事會決議'):
            result = link_cases(annual(('1210', '113/03/14')), [document(subject=subject)])
            case = result['cases'][0]
            self.assertTrue(case['missing_initial_evidence'])
            self.assertEqual(case['earliest_retained_record']['subject'], subject)
            self.assertFalse(case['earliest_retained_record']['first_ever_publication_verified'])
            self.assertIn('missing_initial_evidence', [i['kind'] for i in case['issues']])

    def test_missing_cases_remain_in_output_without_execution_filtering(self):
        snapshot = annual(('1210', '113/03/14'), ('8070', '113/12/31'))
        snapshot['rows'][1]['original_columns'][15] = '0.00'
        result = link_cases(snapshot, [document()])
        self.assertEqual(result['annual_case_count'], 2)
        self.assertEqual(result['cases_with_retained_board_records'], 1)
        self.assertEqual(result['cases_missing_initial_evidence'], 1)
        self.assertEqual(result['cases'][1]['versions'], [])
        self.assertEqual(result['cases'][1]['issues'][0]['kind'], 'no_retained_board_record')

    def test_cross_year_publication_links_by_board_date_not_publication_day(self):
        record = document(board='113/12/31', stamp='2025-01-02T08:44:13+08:00')
        result = link_cases(annual(('1210', '113/12/31')), [record])
        self.assertEqual(result['cases'][0]['board_date'], '2024-12-31')
        self.assertEqual(result['cases'][0]['earliest_retained_record']['reported_datetime'],
                         '2025-01-02T08:44:13+08:00')
        self.assertEqual(result['unmatched_board_documents'], [])
        self.assert_closed(result)

    def test_correction_changing_board_date_is_unresolved_not_guessed(self):
        initial = document()
        correction = document(board='113/03/15', stamp='2024-03-19T14:44:21+08:00',
                              sequence=2, subject='更正董事會決議日期')
        result = link_cases(annual(('1210', '113/03/14')), [initial, correction])
        self.assertEqual(len(result['cases'][0]['versions']), 1)
        unmatched = result['unmatched_board_documents'][0]
        self.assertEqual(unmatched['issue']['kind'], 'possible_board_date_correction')
        self.assertEqual(unmatched['issue']['reported_board_date'], '2024-03-15')
        self.assertEqual(unmatched['issue']['same_issuer_candidate_case_ids'],
                         [result['cases'][0]['case_id']])
        self.assertFalse(unmatched['issue']['linkage_inferred'])

    def test_duplicate_document_ids_are_retained_and_flagged(self):
        record = document()
        result = link_cases(annual(('1210', '113/03/14')), [record, copy.deepcopy(record)])
        self.assertEqual(result['duplicate_document_ids'], [record['event_id']])
        self.assertEqual(len(result['cases'][0]['versions']), 2)
        self.assertTrue(result['cases'][0]['linkage_ambiguous'])

    def test_ambiguous_annual_key_does_not_choose_or_drop_a_case(self):
        result = link_cases(annual(('1210', '113/03/14'), ('1210', '113/03/14')), [document()])
        self.assertEqual(result['annual_case_count'], 2)
        self.assertEqual(result['ambiguous_case_count'], 2)
        self.assertTrue(all(c['versions'] for c in result['cases']))
        self.assertEqual(result['issues'][0]['kind'], 'ambiguous_annual_case_key')

    def test_purpose_change_and_threshold_cannot_fill_a_missing_board_case(self):
        records = [document(form=form, sequence=i, subject='非首次決議')
                   for i, form in enumerate(('purpose_change', 'threshold', 'completion'), 1)]
        result = link_cases(annual(('1210', '113/03/14')), records)
        self.assertEqual(len(result['non_board_documents']), 3)
        self.assertEqual(result['cases_with_retained_board_records'], 0)
        self.assertTrue(result['cases'][0]['missing_initial_evidence'])

    def test_invalid_board_date_text_is_saved_as_unresolved(self):
        for first in ('1.董事會決議日期:113/02/30',
                      '1.董事會決議日期:113/03/14 或113/03/15',
                      '1.原董事會決議日期:113/03/14'):
            record = document()
            record['numbered_fields']['1'] = first
            result = link_cases(annual(('1210', '113/03/14')), [record])
            self.assertEqual(result['unmatched_board_documents'][0]['issue']['kind'],
                             'unresolved_board_date_field')
            self.assertEqual(result['cases_with_retained_board_records'], 0)

    def test_repeated_unmarked_board_versions_are_ambiguous(self):
        first = document()
        second = document(stamp='2024-03-19T14:44:21+08:00', sequence=2)
        result = link_cases(annual(('1210', '113/03/14')), [second, first])
        self.assertTrue(result['cases'][0]['linkage_ambiguous'])
        self.assertIn('multiple_unmarked_board_records',
                      [i['kind'] for i in result['cases'][0]['issues']])

    def test_field_additions_and_removals_and_same_time_sequence_order(self):
        first = document(sequence=1)
        second = document(sequence=2, subject='更正董事會決議')
        second['numbered_fields'].pop('6')
        second['numbered_fields']['12'] = '12.新增原欄'
        result = link_cases(annual(('1210', '113/03/14')), [second, first])
        versions = result['cases'][0]['versions']
        self.assertEqual([v['sequence'] for v in versions], [1, 2])
        changes = {c['field']: c for c in versions[1]['changes_from_previous']}
        self.assertFalse(changes['6']['current_present'])
        self.assertFalse(changes['12']['previous_present'])

    def test_input_objects_unchanged_and_long_fields_not_copied(self):
        snapshot, records = annual(('1210', '113/03/14')), [document()]
        before = copy.deepcopy((snapshot, records))
        result = link_cases(snapshot, records)
        self.assertEqual((snapshot, records), before)
        version = result['cases'][0]['versions'][0]
        self.assertNotIn('14', version['numbered_fields'])
        self.assertEqual(len(version['numbered_field_sha256']['14']), 64)

    def test_malformed_saved_rows_and_naive_document_time_fail(self):
        for snapshot in ({}, {'rows': [{}]}, {'rows': [{'original_columns': [''] * 20}]}):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                link_cases(snapshot, [])
        record = document(stamp='2024-03-14T17:30:23')
        with self.assertRaises(ValueError):
            link_cases(annual(('1210', '113/03/14')), [record])


if __name__ == '__main__':
    unittest.main()
