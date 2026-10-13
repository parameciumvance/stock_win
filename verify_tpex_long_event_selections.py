"""Replay strict means and causal source boundaries from saved selection traces."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from tpex_rule_comparison import strict_mean
from tpex_event_comparison import file_sha,atomic_json

def main():
 root=Path('deliverables/tpex_long_events');meta=json.loads((root/'summary.json').read_text())
 for name,h in meta['output_hashes'].items():
  if file_sha(root/name)!=h:raise ValueError('Output hash mismatch')
 d=pd.read_csv(root/'daily.csv');s=pd.read_csv(root/'selections.csv.gz',dtype={'code':str},parse_dates=['date','flow_source_date','proxy_available_date','month_end'])
 if s.duplicated(['date','code','lag','method']).any():raise ValueError('Duplicate selected key')
 if not s.flow_source_date.lt(s.date).all() or not s.proxy_available_date.le(s.date).all():raise ValueError('Source leakage')
 if not s.proxy_available_date.gt(s.month_end+pd.to_timedelta(s.lag,unit='D')).all():raise ValueError('Revenue availability boundary violation')
 if not (s.date-s.month_end).dt.days.le(100).all():raise ValueError('Stale revenue selected')
 s['date']=s.date.dt.strftime('%Y-%m-%d');groups={(date,int(lag),method):g for (date,lag,method),g in s.groupby(['date','lag','method'])};maximum=0.;unknown=0
 for row in d.itertuples():
  g=groups.get((row.date,row.lag,row.method));v=pd.Series(dtype=float) if g is None else g[f'target{row.horizon}']
  if len(v)!=row.selected or int(v.isna().sum())!=row.unknown_selected:raise ValueError('Selection counts differ')
  value=strict_mean(v)
  if np.isnan(value)!=np.isnan(row.strict_mean):raise ValueError('Unknown daily value was changed')
  if np.isfinite(value):
   difference=abs(value-row.strict_mean);maximum=max(maximum,difference)
   if difference>1e-12:raise ValueError('Strict daily mean differs')
  else:unknown+=1
 result=dict(selected_rows=len(s),daily_values_replayed=len(d),maximum_absolute_difference=maximum,unknown_daily_values=unknown,source_boundaries_passed=True,duplicate_selected_keys=0)
 atomic_json(root/'selection_replay.json',result);print(json.dumps(result))

if __name__=='__main__':main()
