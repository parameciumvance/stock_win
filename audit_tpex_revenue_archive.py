"""Replay every saved revenue response without network and verify normalized output."""
import argparse, hashlib, json
from pathlib import Path
import pandas as pd
from acquire_tpex_revenue import parse
from research_runtime import atomic_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
 root=Path(a.root);summary=json.loads((root/'acquisition.json').read_text())
 frames=[];source_hashes={}
 for month in pd.period_range(summary['source_start'],summary['source_end'],freq='M'):
  for kind in (0,1):
   path=root/'raw'/f'{month}_{kind}.html';payload=path.read_bytes()
   meta=json.loads(path.with_suffix('.meta.json').read_text())
   digest=hashlib.sha256(payload).hexdigest()
   expected=f'https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_{month.year-1911}_{month.month}_{kind}.html'
   if digest!=meta['sha256'] or meta['url']!=expected:raise ValueError('Source metadata mismatch '+str(path))
   f=parse(payload,str(month),kind);f['snapshot_sha256']=digest;frames.append(f)
   source_hashes[path.name]=digest
 replay=pd.concat(frames,ignore_index=True).sort_values(['month','code']).reset_index(drop=True)
 output=root/'monthly.csv.gz';digest=hashlib.sha256(output.read_bytes()).hexdigest()
 if digest!=summary['sha256']:raise ValueError('Normalized source hash mismatch')
 saved=pd.read_csv(output,dtype={'code':str})
 pd.testing.assert_frame_equal(saved,replay,check_dtype=False)
 if len(saved)!=summary['rows'] or len(source_hashes)!=summary['source_count']:raise ValueError('Source counts mismatch')
 if saved.duplicated(['month','code']).any():raise ValueError('Duplicate normalized key')
 report=dict(rows=len(saved),months=summary['months'],source_count=len(source_hashes),normalized_sha256=digest,raw_replay_equal=True,source_hashes=source_hashes,source_export_dates_roc=sorted(saved.source_export_date_roc.unique()),original_publication_time_available=False,revision_history_available=False,use_boundary='Retrospective static snapshot; frozen 45-day proxy and 60-day sensitivity only')
 atomic_json(root/'source_health.json',report);print(json.dumps({k:v for k,v in report.items() if k!='source_hashes'}))

if __name__=='__main__':main()
