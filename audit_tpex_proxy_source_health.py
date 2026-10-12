"""Independently audit event masks and raw-share unit windows in frozen proxy outputs."""
import argparse,bisect,collections,hashlib,json,math
from pathlib import Path
import pandas as pd
def main():
 p=argparse.ArgumentParser();p.add_argument('--start-year',type=int,required=True);p.add_argument('--end-year',type=int,required=True);p.add_argument('--root',required=True);a=p.parse_args()
 root=Path(a.root);path=root/'features_and_gross_labels.csv.gz';summary=json.loads((root/'summary.json').read_text())
 if hashlib.sha256(path.read_bytes()).hexdigest()!=summary['output_sha256']:raise ValueError('Feature output hash mismatch')
 f=pd.read_csv(path,dtype={'code':str});days=[];events=[];expected=0
 for y in range(a.start_year,a.end_year+1):
  d=Path(f'deliverables/tpex_{y}');v=json.loads((d/'annual_verification.json').read_text());expected+=v['primary_pool_rows']
  days.extend(day for month in json.loads((d/'calendar_audit.json').read_text())['months'] for day in month['dates'])
  events.extend(json.loads(Path(f'deliverables/tpex_bridge_long_history_{y}/event_coverage.json').read_text())['records'])
 days=sorted(set(days));indices={day:i for i,day in enumerate(days)}
 if len(f)!=expected or f.duplicated(['date','code']).any() or sorted(f.date.unique())!=days:raise ValueError('As-of pool/calendar mismatch')
 f['market_index']=f.date.map(indices);grouped=collections.defaultdict(list)
 for e in events:grouped[(e['code'],e['event_date'])].append(e)
 unknown=collections.defaultdict(set);units=collections.defaultdict(set)
 for (code,date),items in grouped.items():
  pos=bisect.bisect_left(days,date)
  if pos==len(days):continue
  e=items[0];values=[e['official_last_close'],e['official_reference']]
  known=len(items)==1 and e['status']=='last_close_matches' and date==days[pos] and all(v is not None and math.isfinite(v) and v>0 for v in values)
  if not known:unknown[code].add(pos)
  if any(x['kind'] in ('capital_reduction','face_value_change') for x in items):units[code].update(range(pos,min(pos+20,len(days))))
 violations={f'mom{w}':0 for w in (1,5,20,60)};violations.update({f'label{w}':0 for w in (20,60)});risk=[]
 for code,g in f.groupby('code'):
  for pos in unknown[code]:
   for w in (1,5,20,60):violations[f'mom{w}']+=int(g.loc[(g.market_index>=pos)&(g.market_index<pos+w),f'mom{w}'].notna().sum())
   for w in (20,60):violations[f'label{w}']+=int(g.loc[(g.market_index<pos)&(g.market_index>=pos-w),f'gross_quote_return{w}'].notna().sum())
  hit=g[g.market_index.isin(units[code])]
  if len(hit):risk.append(hit)
 r=pd.concat(risk) if risk else f.iloc[:0];common=r.dropna(subset=['vol20','atr20_pct','breakout60_volume15'])
 report=dict(start_year=a.start_year,end_year=a.end_year,rows=len(f),market_days=len(days),source_events=len(events),event_statuses=dict(collections.Counter(e['status'] for e in events)),uncertain_event_transitions=sum(map(len,unknown.values())),mask_violations=violations,unit_risk_rows=len(r),unit_risk_common_feature_rows=len(common),unit_risk_breakout_selected=int(common.breakout60_volume15.eq(1).sum()),unknown_labels20=int(f.label_unknown20.sum()),unknown_labels60=int(f.label_unknown60.sum()),feature_sha256=summary['output_sha256'],scope='Source/event/feature health only; no investment performance claim')
 (root/'health_audit.json').write_text(json.dumps(report,indent=2)+'\n')
 if any(violations.values()) or len(common):raise ValueError('Unresolved event or share-unit window entered features; review required')
 print(json.dumps(report))
if __name__=='__main__':main()
