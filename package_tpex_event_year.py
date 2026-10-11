"""Closed, verified incremental raw source and complete-through-year event checkpoint."""
import argparse,hashlib,json,zipfile
from pathlib import Path
import pandas as pd
from tpex_flow_pilot import parse

def main():
 p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);p.add_argument('--code-commit',required=True);a=p.parse_args();year=a.end_year;root=Path(f'deliverables/tpex_flow_{year}');events=Path('deliverables/tpex_events');acq=json.loads((root/'acquisition.json').read_text());frames=[]
 dates=[d for m in json.loads(Path(f'deliverables/tpex_{year}/calendar_audit.json').read_text())['months'] for d in m['dates']]
 for date in dates:
  f=root/'raw'/f'{date}.json';meta=json.loads(f.with_suffix('.meta.json').read_text());assert hashlib.sha256(f.read_bytes()).hexdigest()==meta['sha256'];frames.append(parse(json.loads(f.read_bytes()),date))
 regenerated=pd.concat(frames,ignore_index=True);normalized=pd.read_csv(root/f'institutional_tpex_{year}.csv.gz',dtype={'code':str});pd.testing.assert_frame_equal(normalized,regenerated,check_dtype=False)
 replay=dict(year=year,days=len(dates),rows=len(normalized),source_members=len(dates)*2,normalized_source_replay_exact=True);(root/'source_replay.json').write_text(json.dumps(replay,indent=2)+'\n')
 previous={str(y):json.loads(Path(f'deliverables/tpex_flow_{y}/saved_checkpoint.json').read_text()) for y in range(2023,year)}
 pointers=dict(price_benchmark=json.loads(Path('deliverables/tpex_features/saved_checkpoint.json').read_text()),monthly_raw=json.loads(Path('deliverables/tpex_revenue/saved_checkpoint.json').read_text()),previous_raw_sources=previous)
 (events/f'input_checkpoints_through_{year}.json').write_text(json.dumps(pointers,indent=2)+'\n')
 files=sorted(root.glob('raw/*'))+[root/'coverage.csv',root/'source_replay.json']
 for y in range(2023,year+1):files.extend([Path(f'deliverables/tpex_flow_{y}/institutional_tpex_{y}.csv.gz'),Path(f'deliverables/tpex_flow_{y}/acquisition.json'),Path(f'deliverables/tpex_{y}/calendar_audit.json')])
 # Only completed research artifacts belong in checkpoints; interrupted staging files do not.
 files.extend(p for p in events.iterdir() if p.is_file() and f'through_{year}.' in p.name and p.suffix in ['.csv','.gz','.json','.md'])
 files.extend([Path('deliverables/tpex_revenue/monthly.csv.gz'),Path('deliverables/tpex_revenue/acquisition.json')])
 code_files=['tpex_flow_pilot.py','acquire_tpex_flow_year.py','tpex_event_features.py','tpex_event_comparison.py','audit_tpex_event_comparison.py','summarize_tpex_event_uncertainty.py','make_tpex_event_review.py','package_tpex_event_year.py','configs/tpex_event_rules_protocol.json','requirements_tpex.txt']
 reproduction=events/f'reproduction_environment_through_{year}.json'
 reproduction.write_text(json.dumps(dict(repository='parameciumvance/stock_win',code_commit=a.code_commit,code_sha256={n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in code_files}),indent=2)+'\n');files.append(reproduction)
 if not json.loads((events/f'verification_through_{year}.json').read_text())['all_checks_passed']:raise ValueError('Selection audit not passed')
 files=list(dict.fromkeys(files))
 manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files};dest=root/f'tpex_flow_events_{year}_checkpoint.zip';temp=dest.with_suffix('.pending.zip')
 with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
  for p in files:z.write(p,str(p))
  z.writestr('SHA256MANIFEST.json',json.dumps(manifest,indent=2))
 with zipfile.ZipFile(temp) as z:
  assert z.testzip() is None
  for n,h in manifest.items():assert hashlib.sha256(z.read(n)).hexdigest()==h
 temp.replace(dest);info=dict(bytes=dest.stat().st_size,sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),manifest_files=len(manifest),raw_scope='only current year; prior raw receipt references retained',data_scope='all normalized institutional years and complete-through-year frozen event outputs; feature/benchmark checkpoint separate')
 (root/'checkpoint.json').write_text(json.dumps(info,indent=2)+'\n');print(info,flush=True)
if __name__=='__main__':main()
