"""Replay every saved event selection from its as-of common pool and frozen scores."""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
import pandas as pd
from tpex_rule_comparison import strict_mean

def main():
 p=argparse.ArgumentParser();p.add_argument('--end-year',type=int,required=True);a=p.parse_args();root=Path('deliverables/tpex_events');summary=json.loads((root/f'summary_through_{a.end_year}.json').read_text())
 for n,h in summary['input_hashes'].items():
  if hashlib.sha256(Path(n).read_bytes()).hexdigest()!=h:raise ValueError('Changed upstream '+n)
 common=pd.read_csv(root/f'common_matrix_through_{a.end_year}.csv.gz',dtype={'code':str},parse_dates=['date','flow_source_date','proxy_available_date','month_end'])
 selection=pd.read_csv(root/f'selections_through_{a.end_year}.csv.gz',dtype={'code':str},parse_dates=['date','flow_source_date','proxy_available_date','month_end'])
 daily=pd.read_csv(root/f'daily_through_{a.end_year}.csv',parse_dates=['date']);assert not common.duplicated(['date','code','lag']).any();assert not selection.duplicated(['date','code','lag','horizon','method']).any()
 for f in [common,selection]:
  assert f.flow_source_date.lt(f.date).all() and f.proxy_available_date.le(f.date).all()
  assert (f.date-f.month_end).dt.days.le(100).all()
 pools={(date,int(lag)):g for (date,lag),g in common.groupby(['date','lag'])};sels={(date,int(lag),int(w),method):g for (date,lag,w,method),g in selection.groupby(['date','lag','horizon','method'])};models={(m['year'],m['horizon']):m for m in json.loads(Path('deliverables/tpex_features/ridge_summary.json').read_text())['models']}
 checked=0
 for r in daily.itertuples(index=False):
  g=pools[(r.date,int(r.lag))].copy();assert len(g)==r.common_pool
  method=r.method
  if method=='ridge':
   m=models[(r.year,r.horizon)];g[method]=((g[m['features']].to_numpy()-np.array(m['mean']))/np.array(m['scale']))@np.array(m['coefficient'])+m['intercept']
  if method in ['revenue_acceleration','institutional_five_days','breakout60_volume15','all_three']:expected=g[g[method].eq(1)]
  else:expected=g.sort_values([method,'code'],ascending=[False,True]).head(int(np.ceil(len(g)*.1)))
  actual=sels.get((r.date,int(r.lag),int(r.horizon),method),selection.iloc[:0]);assert len(expected)==len(actual)==r.selected
  assert set(expected.code)==set(actual.code)
  e=expected.set_index('code').sort_index();v=actual.set_index('code').sort_index();target=e[f'target{r.horizon}']
  np.testing.assert_allclose(target.to_numpy(),v.target.to_numpy(),rtol=1e-10,atol=1e-12,equal_nan=True)
  np.testing.assert_allclose(e[method].to_numpy(),v.rule_or_score.to_numpy(),rtol=1e-10,atol=1e-12,equal_nan=True)
  assert int(target.isna().sum())==r.unknown_selected
  np.testing.assert_allclose(strict_mean(target),r.strict_mean,rtol=1e-10,atol=1e-12,equal_nan=True)
  checked+=len(actual)
 out=dict(end_year=a.end_year,common_rows=len(common),selection_rows=len(selection),replayed_rows=checked,daily_groups=len(daily),all_checks_passed=True,limitations='Replays frozen as-of features and proxy outcomes, not original announcement vintage or actual fills')
 assert checked==len(selection)
 (root/f'verification_through_{a.end_year}.json').write_text(json.dumps(out,indent=2)+'\n');print(out)
if __name__=='__main__':main()
