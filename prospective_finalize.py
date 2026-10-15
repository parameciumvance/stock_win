"""Seal a verified research signal and retrieve-verify the complete local bundle."""
import argparse
import json
from pathlib import Path
import shutil
import zipfile

from prospective_journal import seal, verify
from prospective_sources import verify_archive
from research_runtime import atomic_json, sha256, utcnow


def finalize(root):
    root=root.resolve()
    manifest_path=root/'selection_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    digest=sha256(manifest_path)
    journal=root/'journal'
    target=journal/'manifests'/f'{digest}.json';target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if sha256(target)!=digest:raise ValueError('Existing manifest differs')
    else:
        with target.open('xb') as f:f.write(manifest_path.read_bytes())
    raw_hash=manifest['summary']['archive_sha256'];raw=journal/'raw'/raw_hash;raw.parent.mkdir(exist_ok=True)
    if not raw.exists():
        with raw.open('xb') as f:f.write((root/'sources.retrieved.zip').read_bytes())
    if sha256(raw)!=raw_hash:raise ValueError('Journal archive differs')
    snapshot_key='archive_'+raw_hash
    snapshot_path=journal/'snapshot'/f'{snapshot_key}.json'
    if not snapshot_path.exists():seal(journal,'snapshot',snapshot_key,dict(raw_sha256=raw_hash,size_bytes=raw.stat().st_size,source_filename='sources.retrieved.zip',description='Acquired source versions/timestamps are inside archive metadata'))
    summary=manifest['summary']
    payload=dict(signal_date=summary['signal_date'],status=manifest['results']['45']['status'],protocol_sha256=summary['protocol_sha256'],source_status='raw_replay_verified',selection_manifest_sha256=digest,snapshot_records=[snapshot_key],replay_root=str(root),results=manifest['results'],entry_at=summary['entry_at'],research_only=True)
    if payload['status']!='complete':raise ValueError('Incomplete common pool; no complete signal')
    signal_path=journal/'signal'/f'{summary["signal_date"]}.json'
    if signal_path.exists():
        if verify(signal_path)['payload']!=payload:raise ValueError('Existing sealed signal differs; never overwrite')
    else:seal(journal,'signal',summary['signal_date'],payload)
    files=[root/n for n in ('sources.retrieved.zip','checkpoint.json','feature_summary.json','matrix_45.csv','matrix_60.csv','benchmark.csv','selection_manifest.json')]+[target,snapshot_path,signal_path]
    hashes={str(p.relative_to(root)):sha256(p) for p in files}
    archive=root/'signal_bundle.zip'
    if not archive.exists():
        with zipfile.ZipFile(archive.with_suffix('.pending'),'w',zipfile.ZIP_DEFLATED) as z:
            for p in files:z.write(p,str(p.relative_to(root)))
            z.writestr('manifest.json',json.dumps(hashes,sort_keys=True))
        archive.with_suffix('.pending').replace(archive)
    elif verify_archive(archive,sha256(archive))!=hashes:raise ValueError('Existing signal bundle differs')
    backup=root.parent/'backups'/root.name/'signal_bundle.zip';backup.parent.mkdir(parents=True,exist_ok=True)
    if backup.exists() and sha256(backup)!=sha256(archive):raise ValueError('Backup differs')
    shutil.copyfile(archive,backup)
    retrieved=root/'signal_bundle.retrieved.zip';shutil.copyfile(backup,retrieved)
    verify_archive(retrieved,sha256(archive))
    atomic_json(root/'signal_checkpoint.json',dict(storage_kind='local_persistent_copy',sha256=sha256(archive),backup_path=str(backup),retrieved_path=str(retrieved),roundtrip_verified=True,manifest_files=len(files),verified_at=utcnow(),signal_record_sha256=sha256(signal_path),selection_manifest_sha256=digest,limitation='Same-filesystem backup; no off-host disaster recovery'))
    print(signal_path,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();finalize(a.root)
