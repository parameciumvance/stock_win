import gzip,unittest
from pathlib import Path
from acquire_tpex_revenue import parse
class TestRevenueSource(unittest.TestCase):
 def setUp(self):self.raw=gzip.decompress(Path('tests/fixtures/tpex_revenue_202301_0.html.gz').read_bytes())
 def test_validated_historical_source(self):
  f=parse(self.raw,'2023-01',0);self.assertGreater(len(f),700);self.assertFalse(f.code.duplicated().any())
 def test_wrong_market(self):
  raw=self.raw.decode('cp950').replace('上櫃公司112年1月份','上市公司112年1月份').encode('cp950')
  with self.assertRaises(ValueError):parse(raw,'2023-01',0)
 def test_wrong_month_or_company_group(self):
  with self.assertRaises(ValueError):parse(self.raw,'2023-02',0)
  with self.assertRaises(ValueError):parse(self.raw,'2023-01',1)
if __name__=='__main__':unittest.main()
