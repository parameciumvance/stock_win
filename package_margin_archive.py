"""Reparse and verify a complete credit-source year before archiving."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import pandas as pd
from twse_history.margin import cached
from twse_history.institutional import market_days_from_cache


def run(year,asof=None):
    days=market_days_from_cache(Path('twse_history/raw'),year,asof)
    root=Path(f'inputs/margin/raw_{year}');parsed=[];files=[]
    for day in days:
        f,meta=cached(root,day);parsed.append(f)
        files.extend([root/f'margin_{day}.json',root/f'margin_{day}.meta.json'])
    source=pd.concat(parsed,ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    path=Path(f'inputs/margin/margin_twse_{year}.csv.gz')
    recorded=pd.read_csv(path,dtype={'date':str,'symbol':str},keep_default_na=False)
    recorded['date']=pd.to_datetime(recorded.date).dt.strftime('%Y-%m-%d')
    recorded=recorded.sort_values(['date','symbol']).reset_index(drop=True)
    pd.testing.assert_frame_equal(source,recorded,check_exact=True)
    universe_path=Path('twse_history/output_multiyear_2023_2026_asof_20261002/universe_daily_2023_2026.csv.gz')
    universe_sha=hashlib.sha256(universe_path.read_bytes()).hexdigest()
    if universe_sha!='bc5bfa1c662944a43c76724a372bb7b119ff00d9bc199d7361e9bd91f9727942':
        raise ValueError('Frozen historical membership checksum mismatch')
    pieces=[]
    for c in pd.read_csv(universe_path,usecols=['date','symbol','is_member'],dtype={'symbol':str},chunksize=200000):
        if not c.is_member.isin([True,False]).all():raise ValueError('Historical membership must be boolean')
        pieces.append(c[c.date.str.startswith(str(year)) & c.is_member])
    universe=pd.concat(pieces,ignore_index=True)
    if asof:universe=universe[universe.date.le(asof)]
    coverage=universe.merge(source[['date','symbol']].assign(credit_present=True),on=['date','symbol'],how='left',validate='one_to_one')
    daily=coverage.groupby('date').credit_present.agg(['count','size'])
    files.append(path)
    for m in range(1,(int(asof[5:7]) if asof else 12)+1):
        files.extend([Path(f'twse_history/raw/calendar_{year}{m:02d}.json'),Path(f'twse_history/raw/calendar_{year}{m:02d}.meta.json')])
    manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    target=Path(f'deliverables/margin_twse_{year}'+(f'_asof_{asof.replace("-","")}' if asof else '')+'_source_checkpoint.zip')
    summary=dict(year=year,asof=asof,days=len(days),raw_rows=len(source),raw_reparse_exact=True,
                 status='verified_credit_daily_sources_not_original_publication_vintages',
                 historical_member_rows=len(coverage),observed_member_rows=int(coverage.credit_present.notna().sum()),
                 missing_member_rows=int(coverage.credit_present.isna().sum()),
                 daily_coverage_mean=float((daily['count']/daily['size']).mean()),
                 historical_membership_sha256=universe_sha)
    pending=target.with_suffix('.pending.zip')
    with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,str(p))
        z.writestr('SHA256MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
        z.writestr('SOURCE_SUMMARY.json',json.dumps(summary,indent=2)+'\n')
    with zipfile.ZipFile(pending) as z:
        if z.testzip() is not None:raise ValueError('Credit ZIP CRC mismatch')
        for name,h in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=h:raise ValueError('Credit ZIP member checksum mismatch')
    pending.replace(target)
    summary.update(path=str(target),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                   manifest_files=len(manifest),zip_members=len(manifest)+2,crc_verified=True)
    p=Path(f'deliverables/margin/checkpoint_{year}.json');p.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--year',type=int,required=True);p.add_argument('--asof')
    a=p.parse_args();run(a.year,a.asof)
