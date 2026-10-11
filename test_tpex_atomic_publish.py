"""Regression coverage for closed-stream publication after the observed truncated gzip."""
import csv,gzip,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from tpex_event_comparison import atomic_csv

class TestAtomicPublish(unittest.TestCase):
 def test_multiline_rows_roundtrip(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'matrix.csv.gz'
   atomic_csv(pd.DataFrame({'value':['two\nlines','one']}),path)
   with gzip.open(path,'rt',encoding='utf-8',newline='') as stream:rows=list(csv.reader(stream))
   self.assertEqual(rows,[['value'],['two\nlines'],['one']])
 def test_truncated_stream_keeps_previous_verified_file(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'matrix.csv.gz';original=gzip.compress(b'value\n9\n',mtime=0);path.write_bytes(original)
   def truncated(target,**kwargs):Path(target).write_bytes(gzip.compress(b'value\n1\n',mtime=0)[:-8])
   with patch.object(pd.DataFrame,'to_csv',side_effect=truncated):
    with self.assertRaises(EOFError):atomic_csv(pd.DataFrame({'value':[1]}),path)
   self.assertEqual(path.read_bytes(),original)
if __name__=='__main__':unittest.main()
