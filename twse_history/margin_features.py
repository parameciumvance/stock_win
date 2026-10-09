"""Credit balance ratios and announced restrictions, shifted one market day."""
from __future__ import annotations
import numpy as np
import pandas as pd

MARGIN_FEATURES=['finance_utilization','short_utilization']+[f'{r}_balance_change_{w}d'
    for r in ('finance','short') for w in (1,5,20)]+['finance_stopped','short_stopped']


def build_features(flows,days):
    if flows.duplicated(['date','symbol']).any():raise ValueError('Duplicate credit source keys')
    flows=flows.copy();flows['date']=pd.to_datetime(flows.date.astype(str))
    days=pd.DatetimeIndex(days).sort_values().unique()
    out=[]
    for symbol,group in flows.groupby('symbol',sort=True):
        g=group.set_index('date').reindex(days)
        f=pd.DataFrame(index=days)
        for role in ('finance','short'):
            f[role+'_utilization']=(g[role+'_today']/(g[role+'_limit']+1)).clip(0,5)
            # Each day's own previous/current counts share its reported unit.
            # Normalize first, then roll, so a split does not mix lot scales.
            change=((g[role+'_today']-g[role+'_prev'])/(g[role+'_prev']+1)).clip(-1,5)
            for w in (1,5,20):
                f[f'{role}_balance_change_{w}d']=change.rolling(w,min_periods=w).mean()
        flags=g.next_business_day_flags
        f['finance_stopped']=flags.str.contains('O',regex=False).astype(float)
        f['short_stopped']=flags.str.contains('X',regex=False).astype(float)
        f['margin_source_date']=pd.Series(days,index=days).where(g.finance_today.notna())
        f=f.shift(1)
        f['date']=days;f['symbol']=symbol
        out.append(f.reset_index(drop=True))
    result=pd.concat(out,ignore_index=True)
    observed=result[MARGIN_FEATURES].notna().any(axis=1)
    if not result.loc[observed,'margin_source_date'].lt(result.loc[observed,'date']).all():
        raise ValueError('Credit source must precede signal date')
    return result
