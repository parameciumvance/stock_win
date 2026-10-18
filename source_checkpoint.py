"""Deterministic source bundles, with explicit external backup/readback boundary."""
import json
from pathlib import Path
import zipfile
from prospective_sources import verify_archive
from research_runtime import atomic_json,sha256,utcnow


def package_sources(root, out, tag, entries):
    root,out=Path(root),Path(out);out.mkdir(parents=True,exist_ok=True);root.mkdir(parents=True,exist_ok=True)
    manifest={name:sha256(Path(p)) for name,p in entries.items()}
    archive=root/(tag+'.zip')
    with zipfile.ZipFile(archive.with_suffix('.pending'),'w') as z:
        for name,p in sorted(entries.items()):
            z.writestr(zipfile.ZipInfo(name,(1980,1,1,0,0,0)),Path(p).read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(zipfile.ZipInfo('manifest.json',(1980,1,1,0,0,0)),json.dumps(manifest,sort_keys=True),compress_type=zipfile.ZIP_DEFLATED)
    archive.with_suffix('.pending').replace(archive);digest=sha256(archive);verify_archive(archive,digest)
    receipt=out/(tag+'_package.json')
    if receipt.exists() and json.loads(receipt.read_text())['sha256']==digest:return
    atomic_json(receipt,dict(archive=str(archive),sha256=digest,manifest_files=len(manifest),created_at=utcnow(),retrieved=str(root/(tag+'.retrieved.zip')),transfer_receipt=str(root/(tag+'_transfer.json')),backup_label=out.name+'_'+tag))


def readback(out,tag):
    package=json.loads((Path(out)/(tag+'_package.json')).read_text());transfer=json.loads(Path(package['transfer_receipt']).read_text())
    if transfer.get('sha256')!=package['sha256'] or transfer.get('roundtrip_verified') is not True:raise ValueError('Stale/unverified backup readback')
    verify_archive(Path(package['retrieved']),package['sha256'])
    return package,transfer
