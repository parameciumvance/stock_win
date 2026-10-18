import copy
import hashlib
import io
import json
import unittest
import zipfile
from operating_guidance import extract_guidance,interval_diagnostics,compare
from operating_guidance_run import render_review
from operating_snapshot_sources import verified_members

TSMC='''TSMC management expects the overall performance for second quarter 2024 to be as follows: Revenue is expected to be US$19.6 billion; based on 1 US dollar to 32.3 NT dollars, Gross profit margin is expected to be between 51% and 53%.'''
UMC='''Page 11 UMC First Quarter 2025 Outlook & Guidance Quarter-over-Quarter Guidance: ⚫ Gross Profit Margin: Will be higher than 25% with 0121 earthquake impact ⚫ Capacity Utilization: approximately 70% ⚫ CAPEX: US$1.8 billion'''


def stamp(record):
    return dict(record,source_sha256='sourcehash',source_url='https://example.com/source.pdf')


class GuidanceTests(unittest.TestCase):
    def test_closed_interval_fx_and_next_quarter(self):
        g=extract_guidance([TSMC],'2330','2024Q1')
        self.assertEqual((g['lower_pct'],g['upper_pct']),(51,53))
        self.assertEqual(g['target_quarter'],'2024Q2');self.assertEqual(g['assumed_fx_twd_per_usd'],32.3)
        self.assertIsNone(g['point_forecast']);self.assertFalse(g['condition_realization_verified'])

    def test_wrong_closest_target_and_duplicate_guidance_rejected(self):
        wrong=TSMC.replace('second quarter 2024','second quarter 2024 then third quarter 2024')
        with self.assertRaisesRegex(ValueError,'target quarter'):extract_guidance([wrong],'2330','2024Q1')
        with self.assertRaisesRegex(ValueError,'Multiple'):extract_guidance([TSMC,TSMC],'2330','2024Q1')

    def test_inverted_interval_and_conflicting_fx_rejected(self):
        with self.assertRaisesRegex(ValueError,'Invalid printed'):extract_guidance([TSMC.replace('51% and 53%','54% and 53%')],'2330','2024Q1')
        with self.assertRaisesRegex(ValueError,'Ambiguous FX'):extract_guidance([TSMC.replace('Gross profit','1 US dollar to 31.0 NT dollars; Gross profit')],'2330','2024Q1')

    def test_umc_statement_ends_before_next_metric_and_preserves_condition(self):
        g=extract_guidance(['cover',UMC],'2303','2024Q4')
        self.assertEqual(g['source_page'],2);self.assertEqual(g['kind'],'strict_lower_bound')
        self.assertEqual(g['lower_pct'],25);self.assertFalse(g['lower_inclusive'])
        self.assertEqual(g['conditions'],'with 0121 earthquake impact')
        self.assertNotIn('70%',g['statement']);self.assertNotIn('CAPEX',g['statement'])
        self.assertFalse(g['finite_interval_diagnostics_eligible']);self.assertIsNone(g['upper_pct'])

    def test_approximate_range_and_fx_reference_cannot_become_points(self):
        for phrase in ['Will be approximately 30%','Will be close to 30%','Will be in the mid-30% range','Will be approximately Q2 gross margin subject to FX effect']:
            text=UMC.replace('Will be higher than 25% with 0121 earthquake impact',phrase)
            g=extract_guidance([text],'2303','2024Q4')
            self.assertIsNone(g['point_forecast']);self.assertIsNone(g['lower_pct']);self.assertIsNone(g['upper_pct'])
            self.assertFalse(g['finite_interval_diagnostics_eligible'])
        self.assertIn('subject to FX',g['conditions'])

    def test_missing_guidance_not_zero_and_wrong_umc_target_rejected(self):
        self.assertEqual(extract_guidance(['financials without outlook'],'2330','2023Q2')['kind'],'unavailable')
        with self.assertRaisesRegex(ValueError,'target quarter'):extract_guidance([UMC],'2303','2024Q3')
        with self.assertRaisesRegex(ValueError,'Unterminated'):extract_guidance([UMC.split(' ⚫ Capacity')[0]],'2303','2024Q4')

    def test_inclusive_boundary_and_strict_threshold_are_distinct(self):
        self.assertTrue(interval_diagnostics(53,51,53)['contained'])
        self.assertTrue(interval_diagnostics(51,51,53)['contained'])
        self.assertEqual(interval_diagnostics(53.2,51,53)['distance_pp'],0.2)
        self.assertEqual(interval_diagnostics(50.7,51,53)['below_pp'],0.3)
        self.assertEqual(interval_diagnostics(51,51,51)['width_pp'],0)
        for args in [(1,2,1),(float('nan'),1,2),(1,1,float('inf'))]:
            with self.assertRaises(ValueError):interval_diagnostics(*args)

    def fixture(self):
        protocol=dict(issuers=['2303'],origin_quarters=['2024Q4','2025Q1'],comparison_targets=['2025Q1'])
        panel=[dict(issuer='2303',quarter=q,gross_margin_pct=v,ready_for_historical_model=False,accounting_standard_explicit=True) for q,v in [('2024Q4',30.4),('2025Q1',25.0)]]
        guidance=[stamp(extract_guidance([UMC],'2303','2024Q4')),stamp(extract_guidance(['no outlook'],'2303','2025Q1'))]
        return panel,guidance,protocol

    def test_condition_bound_excluded_and_equality_fails_strict_predicate(self):
        panel,guidance,p=self.fixture();rows,summary=compare(panel,guidance,p)
        self.assertFalse(rows[0]['threshold_predicate_satisfied']);self.assertIsNone(rows[0]['distance_pp'])
        self.assertEqual(summary['results'][0]['unscored_targets'],1)
        self.assertIsNone(summary['results'][0]['realized_containment_fraction'])
        self.assertFalse(summary['forecast_skill_established']);self.assertFalse(summary['point_mae_comparison_valid'])
        panel[1]['gross_margin_pct']=26.7
        self.assertTrue(compare(panel,guidance,p)[0][0]['threshold_predicate_satisfied'])

    def test_no_future_guidance_substitution_and_no_missing_row_drop(self):
        panel,guidance,p=self.fixture()
        for change in ['duplicate','misaligned','invented_point','fake_publication','fake_condition']:
            g=copy.deepcopy(guidance)
            if change=='duplicate':g.append(copy.deepcopy(g[0]))
            if change=='misaligned':g[0]['target_quarter']='2025Q2'
            if change=='invented_point':g[0]['point_forecast']=25
            if change=='fake_publication':g[0]['first_published_at']='2025-01-21T17:00:00+08:00'
            if change=='fake_condition':g[0]['condition_realization_verified']=True
            with self.assertRaises(ValueError):compare(panel,g,p)
        missing=copy.deepcopy(guidance);missing[0]=stamp(extract_guidance(['missing'],'2303','2024Q4'))
        rows,summary=compare(panel,missing,p)
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['contained']);self.assertEqual(summary['total_requested_targets'],1)

    def test_interval_comparison_uses_prior_document_and_keeps_boundary_contract(self):
        p=dict(issuers=['2330'],origin_quarters=['2024Q1','2024Q2'],comparison_targets=['2024Q2'])
        panel=[dict(issuer='2330',quarter=q,gross_margin_pct=v,ready_for_historical_model=False,accounting_standard_explicit=True) for q,v in [('2024Q1',53.1),('2024Q2',53.2)]]
        g=[stamp(extract_guidance([TSMC],'2330','2024Q1')),stamp(extract_guidance(['no outlook'],'2330','2024Q2'))]
        rows,summary=compare(panel,g,p)
        self.assertEqual(rows[0]['direction'],'above');self.assertEqual(rows[0]['distance_pp'],0.2)
        self.assertEqual(summary['results'][0]['finite_intervals'],1)
        self.assertFalse(summary['point_mae_comparison_valid'])
        g[0]['upper_inclusive']=False
        with self.assertRaisesRegex(ValueError,'boundary mismatch'):compare(panel,g,p)

    def test_wider_intervals_reduce_distance_without_skill_claim(self):
        tight=interval_diagnostics(54,51,53);wide=interval_diagnostics(54,50,54)
        self.assertGreater(tight['distance_pp'],wide['distance_pp']);self.assertGreater(wide['width_pp'],tight['width_pp'])

    def test_review_escapes_statements_and_has_no_remote_resources(self):
        panel,g,p=self.fixture();rows,_=compare(panel,g,p);rows[0]['guidance_statement']='<img src=x onerror=alert(1)>'
        page=render_review(rows)
        self.assertIn('&lt;img',page);self.assertNotIn('<img src=x',page);self.assertNotIn('<script src=',page)
        rows[0]['guidance_source_url']='javascript:alert(1)'
        with self.assertRaisesRegex(ValueError,'Unsafe'):render_review(rows)

    def test_nested_source_manifest_hash_checked_before_use(self):
        def make(body):
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:
                z.writestr('raw/source',body);z.writestr('manifest.json',json.dumps({'raw/source':hashlib.sha256(b'original').hexdigest()}))
            return stream.getvalue()
        data=make(b'original');self.assertEqual(verified_members(data)['raw/source'],b'original')
        with self.assertRaisesRegex(ValueError,'member digest'):verified_members(make(b'changed'))
        with self.assertRaisesRegex(ValueError,'digest mismatch'):verified_members(data,'wrong archive SHA')


if __name__=='__main__':unittest.main()
