import json,unittest,copy,gzip
from pathlib import Path
from tpex_flow_pilot import parse
class TestFlow(unittest.TestCase):
 def setUp(self):self.doc=json.loads(gzip.decompress(Path('tests/fixtures/tpex_institutional_20230103.json.gz').read_bytes()))
 def test_validated_total(self):
  f=parse(self.doc,'2023-01-03');self.assertEqual(len(f),719)
 def test_wrong_date(self):
  with self.assertRaises(ValueError):parse(self.doc,'2023-01-04')
 def test_bad_sum(self):
  self.doc['tables'][0]['data'][0][-1]='0'
  with self.assertRaises(ValueError):parse(self.doc,'2023-01-03')
 def test_duplicate(self):
  self.doc['tables'][0]['data'].append(copy.deepcopy(self.doc['tables'][0]['data'][0]))
  with self.assertRaises(ValueError):parse(self.doc,'2023-01-03')
if __name__=='__main__':unittest.main()
