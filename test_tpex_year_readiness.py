import contextlib,io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from research_runtime import sha256
from audit_tpex_year_readiness import main
class YearReadinessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name);self.root=Path('deliverables/tpex_2022');self.flow=Path('deliverables/tpex_flow_2022');self.root.mkdir(parents=True);self.flow.mkdir()
  q=pd.DataFrame([dict(date='2022-01-03',code='1001',historical_name='A',primary_pool=True,confirmed_subset=True,type_evidence='confirmed_ordinary'),dict(date='2022-01-03',code='1002',historical_name='B',primary_pool=True,confirmed_subset=False,type_evidence='ordinary_stock_rule_candidate')]);q.to_csv(self.root/'quotes_with_type_2022.csv.gz',index=False)
  pd.DataFrame([dict(date='2022-01-03',code='1001')]).to_csv(self.flow/'institutional_tpex_2022.csv.gz',index=False)
  for dest,doc in [(self.root/'annual_verification.json',{'output_sha256':sha256(self.root/'quotes_with_type_2022.csv.gz')}),(self.flow/'acquisition.json',{'normalized_sha256':sha256(self.flow/'institutional_tpex_2022.csv.gz')}),(self.root/'calendar_audit.json',{'months':[{'dates':['2022-01-03']}]}),(self.root/'event_coverage_summary.json',{'events':0,'by_status':{}})]:dest.write_text(json.dumps(doc))
 def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
 def run_audit(self):
  with patch.object(sys,'argv',['audit','--year','2022']),contextlib.redirect_stdout(io.StringIO()):main()
 def test_missing_institutional_remains_explicit(self):
  self.run_audit();r=json.loads((self.root/'readiness.json').read_text());self.assertEqual(r['primary_institutional_missing_rows'],1);self.assertEqual(r['rule_candidate_rows'],1);self.assertFalse(r['model_training_started'])
  missing=pd.read_csv(self.root/'missing_institutional_primary_rows.csv',dtype={'code':str});self.assertEqual(missing.code.tolist(),['1002'])
 def test_hash_drift_rejected_before_join(self):
  (self.flow/'institutional_tpex_2022.csv.gz').write_bytes(b'corrupt')
  with self.assertRaisesRegex(ValueError,'hash mismatch'):self.run_audit()
if __name__=='__main__':unittest.main()
