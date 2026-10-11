import gzip,hashlib,json,os,sys,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import acquire_tpex_flow_year as acquisition
FIXTURE=Path(__file__).resolve().parent/'tests/fixtures/tpex_institutional_20230103.json.gz'
class FlowResumeTests(unittest.TestCase):
 def setUp(self):
  self.payload=gzip.decompress(FIXTURE.read_bytes());self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name)
  q=Path('deliverables/tpex_2023');q.mkdir(parents=True);(q/'calendar_audit.json').write_text(json.dumps({'months':[{'dates':['2023-01-03']}]}))
  frame=acquisition.parse(json.loads(self.payload),'2023-01-03')[['date','code']];frame['primary_pool']=True;frame.to_csv(q/'quotes_with_type_2023.csv.gz',index=False)
  self.raw=Path('deliverables/tpex_flow_2023/raw');self.raw.mkdir(parents=True)
 def tearDown(self):os.chdir(self.old);self.tmp.cleanup()
 def execute(self,side_effect=None):
  from unittest.mock import MagicMock
  response=MagicMock();response.__enter__.return_value.read.return_value=self.payload
  with patch.object(sys,'argv',['fetch','--year','2023']),patch.object(acquisition.urllib.request,'urlopen',side_effect=side_effect,return_value=response) as fetch,patch.object(acquisition.time,'sleep'):
   acquisition.main();return fetch.call_count
 def test_missing_meta_redownloads_and_cached_pair_skips(self):
  (self.raw/'2023-01-03.json').write_bytes(self.payload)
  self.assertEqual(self.execute(),1);self.assertEqual(self.execute(),0)
  self.assertEqual(json.loads(Path('deliverables/tpex_flow_2023/download_progress.json').read_text())['status'],'complete')
 def test_tampered_cache_fails_without_network(self):
  self.execute();(self.raw/'2023-01-03.json').write_bytes(b'{}')
  with self.assertRaises(AssertionError):self.execute()
 def test_network_failure_retry_is_bounded(self):
  with patch.object(sys,'argv',['fetch','--year','2023']),patch.object(acquisition.urllib.request,'urlopen',side_effect=urllib.error.URLError('fixture')) as fetch,patch.object(acquisition.time,'sleep'):
   with self.assertRaises(urllib.error.URLError):acquisition.main()
   self.assertEqual(fetch.call_count,2)
 def test_schema_failure_is_not_retried(self):
  self.payload=b'{}'
  with patch.object(sys,'argv',['fetch','--year','2023']),patch.object(acquisition.urllib.request,'urlopen') as fetch:
   fetch.return_value.__enter__.return_value.read.return_value=self.payload
   with self.assertRaises((ValueError,KeyError)):acquisition.main()
   self.assertEqual(fetch.call_count,1)
if __name__=='__main__':unittest.main()
