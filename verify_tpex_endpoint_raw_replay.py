"""Replay pinned 2023 raw event responses and compare fields used by proxy features."""
import hashlib,json
from pathlib import Path
from audit_tpex_event_coverage import run

def main():
 pilot=Path('deliverables/tpex_pilot');catalog=json.loads((pilot/'history_probe.json').read_text());source_hashes={}
 for item in catalog:
  if item['name'] in ('excal_history','reduction_history','change_history'):
   p=pilot/(item['name']+'.json')
   if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Raw source hash mismatch '+str(p))
   source_hashes[item['name']]=item['sha256']
 if len(source_hashes)!=3:raise ValueError('Incomplete raw event catalog')
 run(2023,True,'deliverables/tpex_bridge_long_history_2023_replay')
 old=Path('deliverables/tpex_bridge_long_history_2023/event_coverage.json');new=Path('deliverables/tpex_bridge_long_history_2023_replay/event_coverage.json')
 cols=['kind','code','event_date','status','official_last_close','official_reference']
 a=json.loads(old.read_text());b=json.loads(new.read_text());x=sorted(tuple(e[k] for k in cols) for e in a['records']);y=sorted(tuple(e[k] for k in cols) for e in b['records'])
 if x!=y:raise ValueError('Raw replay differs from frozen feature input')
 result=dict(raw_event_replay_passed=True,records=len(x),feature_relevant_fields=cols,differences=0,pinned_input_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),raw_replay_sha256=hashlib.sha256(new.read_bytes()).hexdigest(),source_hashes=source_hashes)
 root=Path('deliverables/tpex_features_2015_2023');root.mkdir(exist_ok=True);(root/'endpoint_event_replay.json').write_text(json.dumps(result,indent=2)+'\n');print('Raw replay and pinned report agree for all feature-relevant fields')
if __name__=='__main__':main()
