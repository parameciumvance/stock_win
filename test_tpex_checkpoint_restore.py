import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from restore_tpex_checkpoint import restore
class TestRestore(unittest.TestCase):
 def test_restore_data_keeps_repo_code(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);z=root/'source.zip';members={'deliverables/data.csv':b'date,value\n2023-01-01,1\n','model.py':b'old code','configs/protocol.json':b'old config'}
   with zipfile.ZipFile(z,'w') as f:
    for n,b in members.items():f.writestr(n,b)
    f.writestr('SHA256MANIFEST.json',json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in members.items()}))
   r=restore(z,hashlib.sha256(z.read_bytes()).hexdigest(),root/'repo');self.assertEqual(r['data_members'],1);self.assertFalse((root/'repo/model.py').exists())
 def test_corrupt_member_publishes_nothing(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);z=root/'source.zip'
   with zipfile.ZipFile(z,'w') as f:
    f.writestr('data.csv','wrong');f.writestr('SHA256MANIFEST.json',json.dumps({'data.csv':hashlib.sha256(b'right').hexdigest()}))
   with self.assertRaises(ValueError):restore(z,hashlib.sha256(z.read_bytes()).hexdigest(),root/'repo')
   self.assertFalse((root/'repo').exists())
if __name__=='__main__':unittest.main()
