"""Replay selected rankings and verify chronological labels and cash accounting."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from medium_term_research import OUT,CONFIG
from twse_history.revenue_proxy import sha


def run():
    c=json.loads(CONFIG.read_text());meta=json.loads((OUT/'matrix.json').read_text())
    if sha(meta['path'])!=meta['sha256']:raise ValueError('Cache changed')
    common=pd.read_pickle(meta['path'],compression='gzip');studies=[]
    for year in c['years']:
        s=json.loads((OUT/f'summary_{year}.json').read_text());test=common[common.score_year.eq(year)]
        if pd.Timestamp(s['train_last_label_end'])>test.date.min():raise ValueError('Training lookahead')
        # Last label date must be exactly the 60th market date after signal.
        calendar=pd.DatetimeIndex(pd.read_csv(c['prices'],usecols=['date']).date.unique()).sort_values()
        endmap=pd.Series(calendar,index=calendar).shift(-c['horizon'])
        mapped=test.date.map(endmap)
        if not ((mapped.eq(test.label_window_end))|(mapped.isna()&test.label_window_end.isna())).all():raise ValueError('Wrong horizon')
        counts=[]
        for kind in ['daily','monthly']:
            path=OUT/f'top_selections_{year}.csv.gz' if kind=='daily' else OUT/f'monthly_selections_{year}.csv'
            top=pd.read_csv(path,dtype={'symbol':str},parse_dates=['date','proxy_available_date','month_end','margin_source_date'])
            daily=pd.read_csv(OUT/f'{kind}_{year}.csv').set_index('date')
            if top.duplicated(['date','model','symbol']).any() or not top.margin_source_date.lt(top.date).all() or not top.proxy_available_date.le(top.date).all():raise ValueError('Selection asof mismatch')
            if not top.proxy_available_date.gt(top.month_end+pd.Timedelta(days=45)).all():raise ValueError('Revenue lag mismatch')
            for (date,model),g in top.groupby(['date','model']):
                d=daily.loc[date.strftime('%Y-%m-%d')]
                if sorted(g['rank'].tolist())!=list(range(1,len(g)+1)) or len(g)!=d.top_count:raise ValueError('Rank mismatch')
                expected=int(np.ceil(d.pool*c['top_fraction'])) if kind=='daily' else c['monthly']['top_n']
                if len(g)!=expected:raise ValueError('Top size mismatch')
                unknown=int((~np.isfinite(g.endpoint_target)).sum())
                if unknown!=d[model+'_unknown']:raise ValueError('Unknown count mismatch')
                mean=g.endpoint_target.mean() if unknown==0 else np.nan
                if not np.isclose(mean,d[model+'_top_net_relative'],equal_nan=True,rtol=0,atol=1e-12):raise ValueError('Mean mismatch')
            counts.append(dict(kind=kind,rows=len(top),sha256=sha(path)))
        monthly=pd.read_pickle(OUT/f'monthly_candidates_{year}.pkl.gz',compression='gzip')
        for name,m in s['models'].items():
            cols=m['features']
            if name.endswith('ridge'):
                pred=((monthly[cols].to_numpy()-np.array(m['scaler_mean']))/np.array(m['scaler_scale']))@np.array(m['coefficients'])+m['intercept']
            else:
                import joblib
                from threadpoolctl import threadpool_limits
                if sha(m['path'])!=m['sha256']:raise ValueError('Estimator changed')
                with threadpool_limits(limits=2):pred=joblib.load(m['path']).predict(monthly[cols])
            if not np.allclose(pred,monthly[name],rtol=0,atol=1e-12):raise ValueError('Score replay mismatch')
        studies.append(dict(year=year,studies=counts,monthly_score_replay=True))
    ledger=pd.read_csv(OUT/'portfolio_daily.csv');events=pd.read_csv(OUT/'portfolio_events.csv')
    if ledger.duplicated(['date','model']).any() or ledger.cash.lt(c['monthly']['reserve_twd']-1e-8).any():raise ValueError('Cash safety mismatch')
    if not np.isfinite(ledger[['cash','unsettled_cash','costs','traded_value']]).all().all():raise ValueError('Nonfinite cash accounting')
    buys=events[events.status.eq('hypothetical_quote_buy')]
    if not buys.planned_shares.eq(buys.whole_shares+buys.odd_shares).all() or not buys.whole_shares.mod(1000).eq(0).all():raise ValueError('Ticket mismatch')
    for model,g in ledger.groupby('model'):
        g=g.sort_values('date');e=events[events.model.eq(model)]
        buy=e[e.status.eq('hypothetical_quote_buy')].groupby('date').apply(lambda x:float((x.gross+x.fee).sum()),include_groups=False)
        sell=e[e.status.eq('hypothetical_quote_sale')].groupby('date').apply(lambda x:float((x.gross*(1-c['sell_tax'])-x.fee).sum()),include_groups=False)
        totals=g.cash+g.unsettled_cash;delta=totals.diff();delta.iloc[0]=totals.iloc[0]-c['monthly']['capital']
        expected=g.date.map(sell).fillna(0).to_numpy()-g.date.map(buy).fillna(0).to_numpy()
        if not np.allclose(delta,expected,rtol=0,atol=1e-7):raise ValueError('Cash conservation violation')
    result=dict(status='all_asof_labels_selections_score_replays_cash_and_tickets_verified',studies=studies,selected_rows=sum(v['rows'] for s in studies for v in s['studies']),portfolio_days=len(ledger),portfolio_events=len(events))
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':run()
