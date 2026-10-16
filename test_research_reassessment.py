import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from research_reassessment import decompose, verified_bundle
from operating_source_pilot import candidate_fields_complete, extract_umc_text


class AttributionTests(unittest.TestCase):
    def test_identity_against_independent_stock_returns_and_weights(self):
        gross=np.array([[.2,-.1,.04],[.03,.05,-.02]])
        benchmark=np.array([.04,-.01]);fee=.001425;tax=.003;slip=.005
        # Simulate the frozen entry/exit economics independently of inversion.
        entry=np.ones_like(gross)*(1+slip)*(1+fee)
        exit=(1+gross)*(1-slip)*(1-fee-tax)
        net=exit/entry-1
        pool=net.mean(axis=1)-benchmark
        selected=net[:,[0,2]].mean(axis=1)-benchmark
        selection,universe,cost,residual=decompose(selected,pool,benchmark,fee,tax,slip)
        np.testing.assert_allclose(selection,gross[:,[0,2]].mean(axis=1)-gross.mean(axis=1))
        np.testing.assert_allclose(universe,gross.mean(axis=1)-benchmark)
        np.testing.assert_allclose(cost,gross[:,[0,2]].mean(axis=1)-net[:,[0,2]].mean(axis=1))
        np.testing.assert_allclose(residual,0,atol=1e-14)

    def test_zero_cost_and_negative_return_boundary(self):
        selection,universe,cost,residual=decompose([-.99,.1],[-.5,.03],[0,.02],0,0,0)
        np.testing.assert_allclose(cost,0,atol=1e-14)
        np.testing.assert_allclose(selection+universe,[-.99,.1])

    def test_missing_endpoints_impossible_returns_and_bad_costs_fail(self):
        for args in [(np.nan,0,0,.001,.003,.005),(-2,0,0,0,0,0),(0,0,0,-1,.003,.005),(0,0,0,.7,.5,0)]:
            with self.assertRaises(ValueError):decompose(*args)

    def test_cost_drag_depends_on_return_not_constant(self):
        a=decompose(.1,0,0,.001425,.003,.005)[2]
        b=decompose(-.1,0,0,.001425,.003,.005)[2]
        self.assertGreater(float(a),float(b))

    def test_archive_tamper_rejected_even_if_crc_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'a.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('data',b'changed');z.writestr('SHA256MANIFEST.json',json.dumps({'data':hashlib.sha256(b'original').hexdigest()}))
            with self.assertRaisesRegex(ValueError,'member hash'):verified_bundle(path,hashlib.sha256(path.read_bytes()).hexdigest())


class OperatingSourceTests(unittest.TestCase):
    def test_financial_sample_checks_period_units_and_ambiguity(self):
        text='UMC Reports Fourth Quarter 2024 Results TWSE: 2303 TIFRS January 21, 2025 Gross margin: 30.4% Revenue: NT$60.39 billion Earnings per share: NT$0.68'
        row=extract_umc_text(text)
        self.assertEqual(row['gross_margin_pct'],30.4)
        self.assertEqual(row['revenue_twd_billions'],60.39)
        self.assertEqual(row['eps_twd'],.68)
        for bad in (text.replace('2024 Results','2023 Results'),text.replace('2303','2330'),text+' Gross margin: 31.0%'):
            with self.assertRaises(ValueError):extract_umc_text(bad)

    def record(self):
        return dict(issuer='2330',quarter='2024Q4',gross_margin_pct=59.0,release_document_sha256='a'*64,version_evidence='sec_archived_document_verified',sec_accepted_at='2025-01-16T12:00:00+00:00')

    def test_current_website_date_does_not_complete_candidate_schema(self):
        r=self.record();r['version_evidence']='current_website_observed_now'
        self.assertFalse(candidate_fields_complete(r))

    def test_missing_or_naive_timestamp_and_missing_number_fail(self):
        for key,value in [('sec_accepted_at',None),('sec_accepted_at','2025-01-16'),('gross_margin_pct',None),('gross_margin_pct',101),('release_document_sha256','x'*64)]:
            r=self.record();r[key]=value;self.assertFalse(candidate_fields_complete(r))

    def test_timestamp_evidence_remains_distinct_from_taiwan_publication(self):
        r=self.record();self.assertTrue(candidate_fields_complete(r));self.assertNotIn('taiwan_first_published_at',r)

if __name__=='__main__':unittest.main()
