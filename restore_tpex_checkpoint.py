"""Verify a saved checkpoint completely, then restore data without replacing repo code."""
import argparse,hashlib,json,os,zipfile
from pathlib import Path,PurePosixPath

def restore(archive,expected_sha,destination):
 archive=Path(archive);destination=Path(destination)
 if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected_sha:raise ValueError('Archive SHA-256 mismatch')
 with zipfile.ZipFile(archive) as z:
  names=z.namelist()
  if len(names)!=len(set(names)):raise ValueError('Duplicate archive members')
  manifests=[n for n in names if n in ['SHA256MANIFEST.json','SHA256MANIFEST_YEAR.json']]
  if len(manifests)!=1:raise ValueError('Expected one manifest')
  manifest=json.loads(z.read(manifests[0]));assert set(names)==set(manifest)|set(manifests)
  data=[]
  for name,h in manifest.items():
   path=PurePosixPath(name)
   if path.is_absolute() or '..' in path.parts:raise ValueError('Invalid member path')
   payload=z.read(name)
   if hashlib.sha256(payload).hexdigest()!=h:raise ValueError('Member hash mismatch '+name)
   # Original code/config/test versions stay in Git; only data outputs and raw snapshots are restored.
   if path.parts[0] in ['configs','tests'] or name.endswith(('.py','.md','.joblib')):continue
   target=destination/name
   if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=h:raise ValueError('Existing data differs '+name)
   data.append(name)
  for name in data:
   target=destination/name
   if target.exists():continue
   target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+'.restoring');temp.write_bytes(z.read(name));os.replace(temp,target)
 return dict(verified_members=len(manifest),data_members=len(data),destination=str(destination))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('--sha256',required=True);p.add_argument('--destination',required=True);a=p.parse_args();print(json.dumps(restore(a.archive,a.sha256,a.destination)))
