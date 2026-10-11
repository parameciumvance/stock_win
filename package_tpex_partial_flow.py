"""Freeze completed institutional months with exact raw replay, not zero-filled rows."""
import argparse,hashlib,json,zipfile
from pathlib import Path
import pandas as pd
from research_runtime import atomic_json
from tpex_flow_pilot import parse

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,required=True);parser.add_argument('--through-month',type=int,required=True);a=parser.parse_args()
    if not 1<=a.through_month<=12:parser.error('through-month must be 1..12')
    root=Path(f'deliverables/tpex_flow_{a.year}');calendar=Path(f'deliverables/tpex_{a.year}/calendar_audit.json');cal=json.loads(calendar.read_text());days=[d for m in cal['months'] for d in m['dates'] if int(d[5:7])<=a.through_month];frames=[];files=[calendar]
    for day in days:
        p=root/'raw'/f'{day}.json';meta=p.with_suffix('.meta.json');assert sha(p)==json.loads(meta.read_text())['sha256'];frames.append(parse(json.loads(p.read_text()),day));files.extend([p,meta])
    data=pd.concat(frames,ignore_index=True);assert not data.duplicated(['date','code']).any() and sorted(data.date.unique())==days
    stem=f'partial_01_{a.through_month:02d}';normalized=root/f'institutional_{stem}.csv.gz';data.to_csv(normalized,index=False,compression={'method':'gzip','mtime':0});pd.testing.assert_frame_equal(pd.read_csv(normalized,dtype={'code':str}),data,check_dtype=False);files.append(normalized)
    manifest={str(p):sha(p) for p in files};mp=root/f'{stem}_manifest.json';atomic_json(mp,manifest);dest=root/f'tpex_institutional_{a.year}_{stem}_checkpoint.zip';temp=dest.with_suffix('.pending.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[mp]:z.write(p,str(p))
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
        for n,h in manifest.items():assert hashlib.sha256(z.read(n)).hexdigest()==h
    temp.replace(dest);report={'year':a.year,'through_month':a.through_month,'days':len(days),'rows':len(data),'sha256':sha(dest),'normalized_sha256':sha(normalized),'manifest_files':len(manifest),'archive':str(dest),'manifest':str(mp),'scope':'partial source only; missing primary rows not inferred as zero; full-year pending'};atomic_json(root/f'{stem}_checkpoint.json',report);print(json.dumps(report))
if __name__=='__main__':main()
