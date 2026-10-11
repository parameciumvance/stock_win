"""Audit fixed 2022 proxy outputs and archive their exact source dependencies."""
from pathlib import Path
import hashlib,json,zipfile
import pandas as pd
from research_runtime import atomic_json

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    r=Path('deliverables/tpex_features_2022');s=json.loads((r/'summary.json').read_text());p=r/'features_and_gross_labels.csv.gz';assert sha(p)==s['output_sha256']
    for name,h in s['source_hashes'].items():assert sha(Path(name))==h
    d=pd.read_csv(p,dtype={'code':str},parse_dates=['date']);assert len(d)==195840 and not d.duplicated(['date','code']).any()
    common=d.dropna(subset=['vol20','atr20_pct','breakout60_volume15']);cal=pd.DatetimeIndex(sorted(d.date.unique()));ev=json.loads(Path('deliverables/tpex_2022/event_coverage.json').read_text())['records'];bad=set();count=0
    for e in ev:
        if e['kind'] in ['capital_reduction','face_value_change']:
            count+=1;i=cal.searchsorted(pd.Timestamp(e['event_date']));bad.update((day,e['code']) for day in cal[i:i+20])
    affected=sum((x.date,x.code) in bad for x in common.itertuples());assert affected==0
    audit={'rows':len(d),'common_feature_rows':len(common),'first_common_date':str(common.date.min().date()),'last_date':str(d.date.max().date()),'unknown_transition_rows':int(d.unverified_event_transition.sum()),'unknown_labels':{str(w):int(d[f'label_unknown{w}'].sum()) for w in [20,60]},'share_unit_events':count,'common_rows_crossing_share_unit_20day_window':affected,'fixed_rules':True,'benchmark_2022_available':True,'not_backtest':True}
    atomic_json(r/'audit.json',audit)
    files=[x for x in r.iterdir() if x.suffix in ['.json','.gz','.csv','.md'] and x.name not in ['saved_checkpoint.json','research_saved_checkpoint.json','research_checkpoint.json','SHA256MANIFEST.json','SHA256MANIFEST_RESEARCH.json']]
    files+=list(Path('deliverables/benchmark_2022').rglob('*'));files=[x for x in files if x.is_file()]
    manifest={str(x):sha(x) for x in files};atomic_json(r/'SHA256MANIFEST_RESEARCH.json',manifest)
    dest=r/'tpex_rules_2022_research_checkpoint.zip';temp=dest.with_suffix('.pending.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for x in files+[r/'SHA256MANIFEST_RESEARCH.json']:z.write(x,str(x))
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
        for n,h in manifest.items():assert hashlib.sha256(z.read(n)).hexdigest()==h
    temp.replace(dest);atomic_json(r/'research_checkpoint.json',{'sha256':sha(dest),'bytes':dest.stat().st_size,'manifest_files':len(manifest),'prior_quote_source_receipt':'deliverables/tpex_2022/saved_checkpoint.json','contains':'derived fixed rules and all new official 0050 raw responses; annual TPEx input restored separately'})
    print(json.dumps(audit))
if __name__=='__main__':main()
