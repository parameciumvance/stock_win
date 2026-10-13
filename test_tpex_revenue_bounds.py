"""Protect requested acquisition bounds from batch-index variable shadowing."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import acquire_tpex_revenue as r

class Response:
 def __init__(self,url):self.url=url
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self):return b'mocked monthly response'

class BoundsTest(unittest.TestCase):
 def test_multimonth_summary_retains_requested_bounds(self):
  with tempfile.TemporaryDirectory() as folder:
   def frame(raw,month,kind):
    return pd.DataFrame([dict(code='1111' if kind==0 else '2222',month=month,revenue_thousands=1.5,source_kind=kind,source_export_date_roc='115/09/23')])
   args=['acquire_tpex_revenue.py','--start-month','2015-01','--end-month','2015-02','--output',folder]
   with patch.object(sys,'argv',args),patch.object(r,'ROOT',Path(folder)),patch.object(r.urllib.request,'urlopen',side_effect=lambda url,timeout:Response(url)),patch.object(r,'parse',side_effect=frame):
    r.main()
   saved=json.loads((Path(folder)/'acquisition.json').read_text())
   self.assertEqual((saved['source_start'],saved['source_end']),('2015-01','2015-02'))
   self.assertEqual((saved['months'],saved['source_count'],saved['rows']),(2,4,4))

 def test_bad_schema_is_not_retried_or_published(self):
  with tempfile.TemporaryDirectory() as folder:
   args=['acquire_tpex_revenue.py','--start-month','2015-01','--end-month','2015-01','--output',folder]
   with patch.object(sys,'argv',args),patch.object(r,'ROOT',Path(folder)),patch.object(r.urllib.request,'urlopen',side_effect=lambda url,timeout:Response(url)) as fetch,patch.object(r,'parse',side_effect=ValueError('bad source schema')):
    with self.assertRaisesRegex(ValueError,'bad source schema'):r.main()
   self.assertEqual(fetch.call_count,2)
   self.assertEqual(list((Path(folder)/'raw').glob('*.html')),[])

if __name__=='__main__':unittest.main()
