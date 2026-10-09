"""Verify saved as-of selection traces against daily summaries without refitting."""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
from twse_history.revenue_proxy import sha


def verify(directory):
    root=Path(directory);checks=[]
    for path in sorted(root.glob('top_selections_*.csv.gz')):
        year=int(path.name.split('_')[-1].split('.')[0]);daily_path=root/f'daily_{year}.csv'
        top=pd.read_csv(path,dtype={'symbol':str},parse_dates=['date','proxy_available_date','month_end','label_window_end','margin_source_date'])
        daily=pd.read_csv(daily_path).set_index('date')
        if top.duplicated(['date','model','symbol']).any():raise ValueError('Duplicate selection')
        if not top.margin_source_date.lt(top.date).all():raise ValueError('Credit lookahead')
        if not top.proxy_available_date.le(top.date).all():raise ValueError('Revenue lookahead')
        if not top.proxy_available_date.gt(top.month_end+pd.Timedelta(days=45)).all():raise ValueError('Wrong revenue lag')
        groups=0
        for (date,model),g in top.groupby(['date','model']):
            d=daily.loc[date.strftime('%Y-%m-%d')]
            if sorted(g['rank'].tolist())!=list(range(1,len(g)+1)) or len(g)!=d.top_count:raise ValueError('Rank/size mismatch')
            if len(g)!=int(np.ceil(d.pool*.1)):raise ValueError('Top fraction mismatch')
            unknown=int((~np.isfinite(g.endpoint_target)).sum())
            if unknown!=d[model+'_unknown']:raise ValueError('Unknown count mismatch')
            expected=g.endpoint_target.mean() if unknown==0 else np.nan
            if not np.isclose(expected,d[model+'_top_net_relative'],atol=1e-12,rtol=0,equal_nan=True):raise ValueError('Daily mean mismatch')
            groups+=1
        checks.append(dict(year=year,rows=len(top),groups=groups,selection_sha256=sha(path),daily_sha256=sha(daily_path)))
    result=dict(status='all_asof_selection_traces_verified',studies=checks,rows=sum(c['rows'] for c in checks),
        checks=['unique stocks','contiguous ranks','top10% size','revenue lag and asof','previous-market credit source','unknown outcomes retained','daily full-selection means'])
    (root/'selection_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');verify(p.parse_args().directory)
