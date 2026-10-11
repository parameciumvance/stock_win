"""Conservative as-of TPEx event rule interfaces; no source absence imputation."""
import numpy as np
import pandas as pd

def institutional_five_days(frame,days):
 if frame.duplicated(['date','code']).any():raise ValueError('Duplicate source date/code')
 out=[]
 for code,g in frame.groupby('code'):
  q=g.set_index('date').reindex(days);values=q.total_net.shift(1)
  count=values.rolling(5,min_periods=5).count();positive=values.gt(0).astype(float).where(values.notna())
  rule=positive.rolling(5,min_periods=5).sum().eq(5).astype(float).where(count.eq(5))
  out.append(pd.DataFrame(dict(date=days,code=code,institutional_five_days=rule.to_numpy(),flow_source_date=pd.Series(days).shift(1).to_numpy())))
 return pd.concat(out,ignore_index=True)

def revenue_acceleration(monthly):
 if monthly.duplicated(['month','code']).any():raise ValueError('Duplicate monthly source')
 out=[]
 for code,g in monthly.groupby('code'):
  q=g.copy();q.index=pd.PeriodIndex(q.month,freq='M');q=q.reindex(pd.period_range(q.index.min(),q.index.max(),freq='M'))
  ratio=(q.revenue_thousands/q.previous_year_thousands).where(q.previous_year_thousands.gt(0)&q.revenue_thousands.ge(0))
  previous=ratio.shift(1);rule=ratio.gt(previous).astype(float).where(ratio.notna()&previous.notna())
  f=pd.DataFrame(dict(code=code,month_end=q.index.to_timestamp(how='end').normalize(),revenue_acceleration=rule.to_numpy(),revenue_yoy=(ratio-1).to_numpy()))
  out.append(f[q.month.notna().to_numpy()])
 return pd.concat(out,ignore_index=True)

def attach_revenue(candidates,monthly_rules,days,lag):
 f=monthly_rules.copy();bound=f.month_end+pd.Timedelta(days=lag);indices=days.searchsorted(bound,side='right');valid=indices<len(days);f=f[valid].copy();f['proxy_available_date']=days[indices[valid]]
 f=f.sort_values(['code','proxy_available_date','month_end']).drop_duplicates(['code','proxy_available_date'],keep='last')
 out=pd.merge_asof(candidates.sort_values(['date','code']),f.sort_values(['proxy_available_date','code']),left_on='date',right_on='proxy_available_date',by='code',direction='backward')
 out.loc[(out.date-out.month_end).dt.days.gt(100),'revenue_acceleration']=np.nan
 known=out.proxy_available_date.notna();assert out.loc[known,'proxy_available_date'].le(out.loc[known,'date']).all()
 return out
