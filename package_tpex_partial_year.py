"""Freeze only completed source months while other months may be downloading."""
import argparse,hashlib,json,zipfile
from pathlib import Path
from research_runtime import atomic_json

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);p.add_argument('--through-month',type=int,required=True);a=p.parse_args()
    if not 1<=a.through_month<=12:p.error('through-month must be 1..12')
    root=Path(f'deliverables/tpex_{a.year}');files=[root/'type_input_hashes.json']+list((root/'classification').iterdir());days=rows=0
    for month in range(1,a.through_month+1):
        m=f'{a.year}{month:02d}';s=root/f'summary_{m}.json';doc=json.loads(s.read_text());q=root/f'quotes_with_type_{m}.csv.gz'
        assert sha(q)==doc['output_sha256'];assert doc['downloaded_validated_days']==doc['comparison_calendar_days']==len(doc['daily'])
        days+=len(doc['daily']);rows+=doc['all_security_rows'];files.extend([s,q])
        raw=[root/'raw'/f'calendar_{m}.json']+[root/'raw'/('quotes_'+r['requested_date'].replace('-','')+'.json') for r in doc['daily']]
        for x in raw:
            meta=x.with_suffix('.json.meta.json');assert sha(x)==json.loads(meta.read_text())['sha256'];files.extend([x,meta])
    manifest={str(x):sha(x) for x in files};dest=root/f'tpex_quotes_{a.year}_partial_01_{a.through_month:02d}_checkpoint.zip';mp=root/f'partial_manifest_01_{a.through_month:02d}.json';atomic_json(mp,manifest)
    temp=dest.with_suffix('.pending.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for x in files+[mp]:z.write(x,str(x))
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
        for n,h in manifest.items():assert hashlib.sha256(z.read(n)).hexdigest()==h
    temp.replace(dest);report={'year':a.year,'through_month':a.through_month,'market_days':days,'quote_rows':rows,'manifest_files':len(manifest),'sha256':sha(dest),'scope':'partial completed months only; independent TPEx calendar/action audit pending','archive':str(dest),'manifest':str(mp)};atomic_json(root/f'partial_checkpoint_01_{a.through_month:02d}.json',report);print(json.dumps(report))
if __name__=='__main__':main()
