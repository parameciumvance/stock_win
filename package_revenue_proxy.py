"""Verify and package revenue sources and selection data for offline replay.

Code/config/reports live in git. Price/flow prerequisites remain in their existing
source archives; this checkpoint adds new snapshots and all top selections.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    root=Path('inputs/revenue_proxy')
    audit=json.loads(Path('deliverables/revenue_proxy/acquisition.json').read_text())
    for name in ('monthly.csv.gz','monthly_features.csv.gz'):
        expected=audit['normalized_sha256' if name=='monthly.csv.gz' else 'features_sha256']
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Normalized checkpoint checksum mismatch')
    sources=[]
    for m in audit['sources']:
        year,month=map(int,m['revenue_month'].split('-'))
        stem=f'revenue_{year}{month:02d}_{m["source_kind"]}'
        raw=root/'raw'/(stem+'.html');meta=root/'raw'/(stem+'.meta.json')
        if hashlib.sha256(raw.read_bytes()).hexdigest()!=m['sha256']:
            raise ValueError('Raw snapshot checksum mismatch')
        if json.loads(meta.read_text())['sha256']!=m['sha256']:
            raise ValueError('Raw metadata mismatch')
        sources.extend([raw,meta])
    sources.extend([root/'monthly.csv.gz',root/'monthly_features.csv.gz'])
    sources.extend(sorted(Path('deliverables/revenue_proxy').glob('top_selections_*.csv.gz')))
    if len(sources)!=228:
        raise ValueError('Unexpected source/selection coverage')
    manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    summary=dict(status='exploratory_delayed_current_vintage_not_point_in_time',
                 source_count=audit['source_count'], monthly_rows=audit['monthly_rows'],
                 manifest_files=len(manifest), git_protocol_commit='1aa5f714cde496d12fc43d1a7c1a854b77790e99',
                 prerequisites='Restore frozen 2023–2026 price/flow sources as documented in docs/REVENUE_PROXY.md; rebuild flows and verify frozen decompressed CSV hash.',
                 research_config_sha256=hashlib.sha256(Path('configs/revenue_proxy_protocol.json').read_bytes()).hexdigest())
    target=Path('deliverables/monthly_revenue_proxy_2022_2026_source_checkpoint.zip')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sources:z.write(p,str(p))
        z.writestr('SHA256MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
        z.writestr('SOURCE_SUMMARY.json',json.dumps(summary,indent=2)+'\n')
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC mismatch')
        for name,expected in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=expected:raise ValueError('ZIP source hash mismatch')
    result=dict(path=str(target),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                manifest_files=len(manifest),zip_members=len(manifest)+2,crc_verified=True,all_member_hashes_verified=True)
    Path('deliverables/revenue_proxy/checkpoint_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
