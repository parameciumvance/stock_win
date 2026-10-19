import copy
import json
from fractions import Fraction as F
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ipo_replication import analytical_funding, calculate, cohort, match, summarize
from ipo_source_consistency import differences, html_rows, require_consistency
from ipo_screen import FIELDS


def row():
    fields=['1','114/01/08','測試','1234','初上市','114/01/02','114/01/06','1000','1000','100','100','114/01/10','券商','1000','100000','1000','0.1','']
    return cohort([fields],2025,'初上市')[0]


class ReplicationTests(unittest.TestCase):
    def test_exact_category_not_changed_to_rescue_results(self):
        r=list(row()['reported_fields'].values());foreign=r.copy();foreign[3]='5678';foreign[4]='外國初上市'
        self.assertEqual(len(cohort([r,foreign],2025,'初上市')),1)

    def test_duplicate_or_wrong_year_fails(self):
        r=list(row()['reported_fields'].values())
        for rows,year in [([r,r],2025),([r],2024)]:
            with self.assertRaises(ValueError):cohort(rows,year,'初上市')

    def matched(self):
        r=row();r.update(terms=dict(individually_affordable=True,reservation_scenario_twd='100070',issues=[],offer_price='100',lot_size='1000',allocation_probability='0.001'),raw_listing_quote=dict(open='200'),eligible_for_calculation=True)
        return r

    def p(self):return dict(sale_drag_scenarios=['0','0.005'],application_fee_scenario='20',winner_fee_scenario='50')

    def test_missing_affordable_case_blocks_aggregate_no_partial_success(self):
        good=self.matched();missing=copy.deepcopy(good);missing['symbol']='5678';missing['eligible_for_calculation']=False;missing['terms']['issues']=['missing_exact_listing_quote']
        details,s=summarize([good,missing],self.p())
        self.assertIsNone(s['exploratory_resource_gate_passed']);self.assertFalse(s['whole_affordable_cohort_coverage'])
        self.assertIsNone(s['scenarios'][0]['whole_eligible_cohort_sum_twd']);self.assertGreater(F(s['scenarios'][0]['partial_sum_twd']),0)

    def test_negative_case_retained_can_fail_original_gate(self):
        r=self.matched();r['raw_listing_quote']['open']='80'
        details,s=summarize([r],self.p());self.assertFalse(s['exploratory_resource_gate_passed']);self.assertEqual(len(details),2)

    def test_unknown_budget_case_also_blocks_aggregate(self):
        unknown=self.matched();unknown['eligible_for_calculation']=False;unknown['terms']['individually_affordable']=False;unknown['terms']['reservation_scenario_twd']=None
        _,s=summarize([self.matched(),unknown],self.p());self.assertIsNone(s['exploratory_resource_gate_passed'])

    def test_cash_bound_matches_brute_force_winners_and_losers(self):
        rows=[self.matched()];days=['2025-01-06','2025-01-07','2025-01-08','2025-01-09','2025-01-10','2025-01-13','2025-01-14']
        f=analytical_funding(rows,days,F('0.005'),F(20),F(50))
        self.assertEqual(F(f['maximum_required_initial_cash_exact']),100070);self.assertTrue(f['within_300k'])
        self.assertEqual(f['dates'][0]['sale_if_win'],'2025-01-14')

    def test_unfundable_case_not_silently_removed(self):
        rows=[self.matched(),self.matched(),self.matched()];days=['2025-01-06','2025-01-07','2025-01-08','2025-01-09','2025-01-10','2025-01-13','2025-01-14']
        result=analytical_funding(rows,days,F(0),F(20),F(50))
        self.assertEqual(F(result['maximum_required_initial_cash_exact']),300210);self.assertFalse(result['within_300k']);self.assertEqual(len(result['dates']),3)

    def test_missing_next_year_calendar_is_failure_not_date_clipping(self):
        with self.assertRaisesRegex(ValueError,'calendar'):analytical_funding([self.matched()],['2025-01-06','2025-01-08','2025-01-10'],F(0),F(20),F(50))

    def test_majority_cannot_override_one_conflicting_representation(self):
        a=[list(row()['reported_fields'].values())];b=copy.deepcopy(a);b[0][9]='0.01'
        with self.assertRaisesRegex(ValueError,'conflict'):require_consistency([a,a,b])

    def test_noncohort_discrepancy_is_not_filtered_away(self):
        a=[list(row()['reported_fields'].values())];a[0][4]='上市增資';b=copy.deepcopy(a);b[0][9]='0.01'
        self.assertEqual(len(differences(a,b)),1)
        with self.assertRaises(ValueError):require_consistency([a,b,a])

    def test_missing_row_or_changed_identity_fails_alignment(self):
        a=[list(row()['reported_fields'].values())];b=copy.deepcopy(a);b[0][3]='5678'
        for other in [[],b]:
            with self.assertRaises(ValueError):differences(a,other)

    def test_nul_or_excel_formula_is_not_silently_normalized(self):
        a=[list(row()['reported_fields'].values())]
        for value in ['99\x00568','=\"100\"']:
            b=copy.deepcopy(a);b[0][9]=value
            self.assertEqual(differences(a,b)[0]['fields'][0]['right'],value)
            with self.assertRaises(ValueError):require_consistency([a,b,a])

    def test_html_requires_exact_year_and_headers(self):
        headers='<tr>'+''.join('<th>'+f+'</th>' for f in FIELDS)+'</tr>'
        values='<tr>'+''.join('<td>'+f+'</td>' for f in row()['reported_fields'].values())+'</tr>'
        self.assertEqual(len(html_rows((headers+values).encode(),2025)),1)
        with self.assertRaises(ValueError):html_rows((headers+values).encode(),2024)
        with self.assertRaises(ValueError):html_rows(values.encode(),2025)

    def test_source_failure_blocks_quotes_and_even_stale_calculation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'source_receipt.json').write_text(json.dumps(dict(sha_crc_manifest_verified=True,semantic_consistency_passed=False)))
            (folder/'matched_cases.json').write_text('stale invalid local artifact must not be opened')
            with patch('ipo_replication.OUT',folder),patch('ipo_replication.policy',return_value={}),patch('ipo_replication.verified_bundle') as market:
                for operation in [match,calculate]:
                    with self.assertRaisesRegex(ValueError,'consistency|inconsistency'):operation()
                market.assert_not_called()


if __name__=='__main__':unittest.main()
