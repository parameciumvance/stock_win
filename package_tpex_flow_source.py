"""Publish a replay-verified annual institutional source before longer research jobs."""
import argparse,hashlib,json,zipfile
from pathlib import Path
import pandas as pd
from tpex_flow_pilot import parse
from tpex_event_comparison import file_sha

def main():
 p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);a=p.parse_args()
 root=Path(f'deliverables/tpex_flow_{a.year}');calendar=Path(f'deliverables/tpex_{a.year}/calendar_audit.json')
 acq=json.loads((root/'acquisition.json').read_text());days=[d for m in json.loads(calendar.read_text())['months'] for d in m['dates']]
 normalized=root/f'institutional_tpex_{a.year}.csv.gz'
 assert file_sha(normalized)==acq['normalized_sha256'] and file_sha(calendar)==acq['calendar_sha256']
 frames=[];files=[]
 for day in days:
  source=root/'raw'/f'{day}.json';meta=source.with_suffix('.meta.json');assert file_sha(source)==json.loads(meta.read_text())['sha256']
  frames.append(parse(json.loads(source.read_bytes()),day));files.extend([source,meta])
 original=pd.concat(frames,ignore_index=True);saved=pd.read_csv(normalized,dtype={'code':str})
 pd.testing.assert_frame_equal(saved,original,check_dtype=False)
 assert not saved.duplicated(['date','code']).any() and sorted(saved.date.unique())==days
 replay=dict(year=a.year,days=len(days),rows=len(saved),normalized_source_replay_exact=True)
 (root/'source_replay.json').write_text(json.dumps(replay,indent=2)+'\n')
 files.extend([normalized,root/'acquisition.json',root/'coverage.csv',root/'source_replay.json',calendar])
 manifest={str(f):file_sha(f) for f in files};dest=root/f'tpex_institutional_source_{a.year}_checkpoint.zip';temp=dest.with_suffix('.pending.zip')
 with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
  for f in files:z.write(f,str(f))
  z.writestr('SHA256MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
 with zipfile.ZipFile(temp) as z:
  assert z.testzip() is None
  for name,h in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==h
 temp.replace(dest);info=dict(year=a.year,bytes=dest.stat().st_size,sha256=file_sha(dest),manifest_files=len(manifest),scope='current-year raw institutional snapshots, metadata, calendar, normalized rows and exact source replay; no event performance claim')
 (root/'source_checkpoint.json').write_text(json.dumps(info,indent=2)+'\n');print(info,flush=True)
if __name__=='__main__':main()
