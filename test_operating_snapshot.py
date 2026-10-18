import contextlib
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bounded_public_sources import validate_config,acquire
from operating_snapshot import extract_financials,extract_guidance,arithmetic
from source_checkpoint import package_sources,readback
from research_runtime import sha256

TSMC='''April 18, 2024 TSMC today announced consolidated revenue of NT$592.64 billion, and diluted earnings per share of NT$8.70 for the first quarter ended March 31, 2024. All figures are TIFRS on a consolidated basis. Gross margin for the quarter was 53. 1%. Gross profit margin is expected to be between 51% and 53%.'''
UMC='''UMC Reports Fourth Quarter 2025 Results. 2025 earnings per share of NT$3.34. United Microelectronics Corporation TWSE: 2303 consolidated TIFRS. Fourth Quarter 2025 Overview: Revenue: NT$61.81 billion; Gross margin: 30.7%; Earnings per share: NT$0.81. January 28, 202 6.'''
MANAGEMENT='''TSMC Quarterly Management Report July 20, 2023. Second Quarter 2023. Net revenue was NT$480.84 billion. Gross margin was 54.1%. Net profit margin was 37.8% and diluted EPS was NT$7.01. Amounts are on consolidated basis.'''


class SnapshotTests(unittest.TestCase):
    def test_pdf_layout_spaces_and_sentence_punctuation(self):
        a=extract_financials(TSMC,issuer='2330',quarter='2024Q1')
        b=extract_financials(MANAGEMENT,issuer='2330',quarter='2023Q2',management=True)
        self.assertEqual(a['gross_margin_pct'],53.1);self.assertEqual(b['eps_twd'],7.01)
        self.assertEqual(b['revenue_twd_billions'],480.84)
        self.assertFalse(b['accounting_standard_explicit']);self.assertIn('not stated',b['accounting_basis'])
        self.assertFalse(b['ready_for_historical_model']);self.assertIsNone(b['first_published_at'])

    def test_annual_eps_cannot_replace_quarter_eps(self):
        r=extract_financials(UMC,issuer='2303',quarter='2025Q4')
        self.assertEqual(r['eps_twd'],0.81);self.assertEqual(r['visible_document_date'],'2026-01-28')

    def test_wrong_quarter_company_basis_and_units_fail(self):
        for body,issuer,q in [(TSMC,'2330','2024Q2'),(TSMC,'2303','2024Q1'),(TSMC.replace('TIFRS','GAAP'),'2330','2024Q1'),(TSMC.replace('592.64 billion','592640 million'),'2330','2024Q1')]:
            with self.assertRaises(ValueError):extract_financials(body,issuer=issuer,quarter=q)
        with self.assertRaises(ValueError):extract_financials(MANAGEMENT.replace('consolidated','company-only'),issuer='2330',quarter='2023Q2',management=True)

    def test_conflicting_margin_is_a_gap(self):
        with self.assertRaisesRegex(ValueError,'conflicting'):
            extract_financials(TSMC+' Gross margin for the quarter was 99.0%.',issuer='2330',quarter='2024Q1')

    def test_guidance_interval_and_conditional_lower_bound_are_not_points(self):
        g=extract_guidance(TSMC,'2330','2024Q1');self.assertEqual((g['lower_pct'],g['upper_pct']),(51,53));self.assertIsNone(g['point_forecast'])
        g=extract_guidance('Gross Profit Margin: Will be higher than 25% with 0121 earthquake impact.','2303','2024Q4')
        self.assertIn('higher than 25%',g['excerpt']);self.assertIsNone(g['point_forecast']);self.assertEqual(g['target_quarter'],'2025Q1')

    def fixture(self):
        quarters=[f'{y}Q{q}' for y in [2023,2024,2025] for q in [1,2,3,4]]
        cfg=dict(issuers=['2330','2303'],quarters=quarters,evaluation_quarters=quarters[4:],arithmetic_baselines=['previous_quarter','same_quarter_previous_year'])
        rows=[dict(issuer=i,quarter=q,gross_margin_pct=float(n),ready_for_historical_model=False,accounting_standard_explicit=True) for i in cfg['issuers'] for n,q in enumerate(quarters)]
        return rows,cfg

    def test_baselines_use_same_targets_and_correct_lags(self):
        panel,cfg=self.fixture();errors,summary=arithmetic(panel,cfg)
        self.assertEqual(len(errors),16)
        for r in errors:
            self.assertEqual(r['previous_quarter_abs_error_pp'],1)
            self.assertEqual(r['same_quarter_previous_year_abs_error_pp'],4)
        self.assertTrue(all(r['paired_targets']==8 for r in summary['results']))
        panel[1]['gross_margin_pct']=None
        errors,summary=arithmetic(panel,cfg)
        self.assertEqual([r['paired_targets'] for r in summary['results']],[7,7,8,8])
        self.assertNotIn(('2330','2024Q2'),[(r['issuer'],r['target_quarter']) for r in errors])

    def test_later_value_cannot_change_earlier_baselines(self):
        panel,cfg=self.fixture();before,_=arithmetic(panel,cfg)
        panel[11]['gross_margin_pct']=100
        after,_=arithmetic(panel,cfg)
        self.assertEqual(before[:7],after[:7])
        self.assertNotEqual(before[7]['target_gross_margin_pct'],after[7]['target_gross_margin_pct'])

    def test_basis_uncertainty_retained_in_arithmetic(self):
        panel,cfg=self.fixture();panel[1]['accounting_standard_explicit']=False
        errors,summary=arithmetic(panel,cfg)
        self.assertEqual(summary['accounting_standard_unstated_rows'],1)
        affected=next(r for r in errors if r['issuer']=='2330' and r['target_quarter']=='2024Q2')
        self.assertFalse(affected['accounting_standard_explicit_all_three']);self.assertFalse(summary['ready_for_historical_model'])

    def test_no_duplicate_cohort_or_readiness_promotion(self):
        panel,cfg=self.fixture()
        for bad in [panel[:-1],panel+[panel[0]],panel[:-1]+[panel[0]]]:
            with self.assertRaises(ValueError):arithmetic(bad,cfg)
        panel[0]['ready_for_historical_model']=True
        with self.assertRaises(ValueError):arithmetic(panel,cfg)


class AcquisitionCheckpointTests(unittest.TestCase):
    def test_nonpublic_scheme_credentials_and_path_escape_rejected(self):
        cfg=dict(output_directory='inputs/test',allowed_hosts=['example.com'],requests=[dict(filename='source.pdf',url='https://example.com/file')])
        validate_config(cfg)
        for url in ['http://example.com/file','https://user:password@example.com/file','https://other.com/file']:
            bad=copy.deepcopy(cfg);bad['requests'][0]['url']=url
            with self.assertRaises(ValueError):validate_config(bad)
        for root in ['/tmp/path','inputs/../other']:
            with self.assertRaises(ValueError):validate_config(dict(cfg,output_directory=root))
        bad=copy.deepcopy(cfg);bad['requests'][0]['filename']='../other'
        with self.assertRaises(ValueError):validate_config(bad)

    def test_cached_denial_does_not_trigger_retry_and_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.chdir(tmp):
            root=Path('inputs/probe');root.mkdir(parents=True);item=dict(filename='denied',url='https://example.com/file')
            cfg=dict(output_directory=str(root),allowed_hosts=['example.com'],requests=[item]);Path('cfg.json').write_text(json.dumps(cfg))
            (root/'denied').write_bytes(b'denied')
            meta=dict(request=item,http_status=403,sha256=sha256(root/'denied'))
            (root/'denied.meta.json').write_text(json.dumps(meta))
            with patch('bounded_public_sources.subprocess.run',side_effect=AssertionError('duplicate HTTP request')):
                acquire('cfg.json')
            (root/'denied').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'drift'):acquire('cfg.json')

    def test_checkpoint_stable_and_stale_roundtrip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.chdir(tmp):
            source=Path('original');source.write_bytes(b'unchanged raw source')
            package_sources('inputs/root','out','source',{'raw/file':source});before=Path('out/source_package.json').read_bytes()
            package_sources('inputs/root','out','source',{'raw/file':source});self.assertEqual(before,Path('out/source_package.json').read_bytes())
            Path('inputs/root/source_transfer.json').write_text(json.dumps(dict(sha256='wrong',roundtrip_verified=True)))
            with self.assertRaisesRegex(ValueError,'Stale'):readback('out','source')


if __name__=='__main__':unittest.main()
