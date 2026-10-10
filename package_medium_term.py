"""Package owned model/selection/cash evidence needed for offline replay."""
from pathlib import Path
import hashlib,json,zipfile
from medium_term_research import OUT


def digest(b):return hashlib.sha256(b).hexdigest()

def run():
    v=json.loads((OUT/'verification.json').read_text())
    if not v['status'].startswith('all_asof'):raise ValueError('Unverified studies')
    files=[]
    for year in [2024,2025,2026]:
        for pattern in [f'top_selections_{year}.csv.gz',f'monthly_candidates_{year}.pkl.gz',f'price_tree_{year}.joblib',f'all_tree_{year}.joblib']:
            p=OUT/pattern
            if not p.exists():raise ValueError('Missing replay artifact')
            files.append(p)
    manifest={str(p):digest(p.read_bytes()) for p in files}
    metadata=dict(status='trusted_owned_pickle_and_joblib_only_exploratory_not_fresh_holdout',protocol_sha256=digest(Path('configs/medium_term_protocol.json').read_bytes()),
        matrix=json.loads((OUT/'matrix.json').read_text()),verification_sha256=digest((OUT/'verification.json').read_bytes()),
        git_backed_results={str(p):digest(p.read_bytes()) for p in OUT.glob('*') if p.suffix in ['.json','.csv','.md']})
    target=Path('deliverables/medium_term_60d_2024_2026_replay.zip');temp=target.with_name(target.stem+'.pending.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,str(p))
        z.writestr('SHA256MANIFEST.json',json.dumps(manifest,indent=2)+'\n');z.writestr('SOURCE_SUMMARY.json',json.dumps(metadata,indent=2)+'\n')
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC')
        for name,h in manifest.items():
            if digest(z.read(name))!=h:raise ValueError('Member checksum')
    temp.replace(target)
    result=dict(path=str(target),bytes=target.stat().st_size,sha256=digest(target.read_bytes()),manifest_files=len(files),zip_members=len(files)+2,crc_verified=True)
    (OUT/'checkpoint.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':run()
