"""Save large selection traces and trusted fitted estimators outside Git."""
from pathlib import Path
import hashlib,json,zipfile

def digest(data):return hashlib.sha256(data).hexdigest()

def run():
    roots=[Path('deliverables/margin'),Path('deliverables/fundamental_tree')]
    files=[]
    for root in roots:
        for year in [2024,2025,2026]:
            path=root/f'top_selections_{year}.csv.gz'
            if not path.exists():raise ValueError('Incomplete studies')
            files.append(path)
            if root.name=='fundamental_tree':
                s=json.loads((root/f'summary_{year}.json').read_text())
                for model in s['models'].values():
                    p=Path(model['path'])
                    if digest(p.read_bytes())!=model['sha256']:raise ValueError('Estimator checksum mismatch')
                    files.append(p)
    manifest={str(p):digest(p.read_bytes()) for p in files}
    target=Path('deliverables/fundamental_research_2024_2026_traces.zip');pending=target.with_name(target.stem+'.pending.zip')
    metadata=dict(status='exploratory_not_independent_holdout',years=[2024,2025,2026],
        asof='2026-10-02',trusted_models_only=True,
        report_paths=['deliverables/margin/report.md','deliverables/fundamental_tree/report.md'],
        protocol_sha256={str(p):digest(p.read_bytes()) for p in [Path('configs/margin_protocol.json'),Path('configs/fundamental_tree_protocol.json')]},
        models_and_cache_sources={str(root/f'summary_{year}.json'):digest((root/f'summary_{year}.json').read_bytes()) for root in roots for year in [2024,2025,2026]})
    with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,str(p))
        z.writestr('SHA256MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
        z.writestr('SOURCE_SUMMARY.json',json.dumps(metadata,indent=2)+'\n')
    with zipfile.ZipFile(pending) as z:
        if z.testzip() is not None:raise ValueError('Invalid ZIP CRC')
        for name,h in manifest.items():
            if digest(z.read(name))!=h:raise ValueError('ZIP member mismatch')
    pending.replace(target)
    result=dict(path=str(target),sha256=digest(target.read_bytes()),bytes=target.stat().st_size,
        manifest_files=len(manifest),zip_members=len(manifest)+2,crc_verified=True)
    Path('deliverables/fundamental_tree/trace_checkpoint.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)

if __name__=='__main__':run()
