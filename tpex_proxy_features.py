"""Causal ratio features and gross quote labels; no actual fills or cash ledger."""
import argparse,gzip,hashlib,json,pathlib
import numpy as np
import pandas as pd

def event_clock(days,events):
    factors=np.ones(len(days));unknown=np.zeros(len(days),dtype=int);groups={}
    for e in events:groups.setdefault(e['event_date'],[]).append(e)
    for date,group in groups.items():
        i=days.searchsorted(pd.Timestamp(date))
        if i==len(days):continue
        e=group[0];last=e['official_last_close'];ref=e['official_reference']
        known=len(group)==1 and e['status']=='last_close_matches' and date==days[i].strftime('%Y-%m-%d') and last is not None and ref is not None and np.isfinite(last) and np.isfinite(ref) and min(last,ref)>0
        if known:factors[i]=last/ref
        else:unknown[i]=1
    return np.cumprod(factors),np.cumsum(unknown)

def features(frame,days,events):
    q=frame.set_index('date').reindex(days).copy()
    for c in ['open','high','low','close','volume_shares']:
        q[c]=pd.to_numeric(q[c].astype(str).str.replace(',','',regex=False),errors='coerce')
        if c!='volume_shares':q[c]=q[c].where(q[c]>0)
    factor,unknown=event_clock(days,events);u=pd.Series(unknown,index=days)
    prices=q[['open','high','low','close']].mul(factor,axis=0);close=prices['close'];out=q[['code','primary_pool','confirmed_subset','type_evidence']].copy()
    for w in [1,5,20,60]:
        out[f'mom{w}']=(close/close.shift(w)-1).where(u-u.shift(w)==0)
    r=np.log(close/close.shift(1)).where(u-u.shift(1)==0)
    out['vol20']=r.rolling(20,min_periods=20).std(ddof=1)
    tr=pd.concat([prices['high']-prices['low'],(prices['high']-close.shift()).abs(),(prices['low']-close.shift()).abs()],axis=1).max(axis=1,skipna=False)
    tr=tr.where(u-u.shift()==0)
    out['atr20_pct']=tr.rolling(20,min_periods=20).mean()/close
    prior_volume=q['volume_shares'].shift().rolling(20,min_periods=20).mean()
    out['volume_ratio20']=q['volume_shares']/prior_volume.where(prior_volume>0)
    prior_high=close.shift().rolling(60,min_periods=60).max()
    valid=close.notna()&prior_high.notna()&out['volume_ratio20'].notna()&(u-u.shift(60)==0)
    out['breakout60_volume15']=((close>prior_high)&(out['volume_ratio20']>1.5)).astype(float).where(valid)
    for w in [20,60]:
        entry=prices['open'].shift(-1);end=close.shift(-w)
        clean=u.shift(-w)-u==0
        out[f'gross_quote_return{w}']=(end/entry-1).where(clean&(entry>0)&(end>0))
        out[f'label_unknown{w}']=out[f'gross_quote_return{w}'].isna()
    out['date']=days.strftime('%Y-%m-%d');out['unverified_event_transition']=np.diff(np.r_[0,unknown])>0
    return out.loc[out['primary_pool'].eq(True)].reset_index(drop=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--start-year',type=int,default=2023);p.add_argument('--end-year',type=int,default=2026);p.add_argument('--output',default='deliverables/tpex_features');p.add_argument('--event-override',action='append',default=[],help='YEAR=event_coverage.json; preserves original event audit');a=p.parse_args()
    if a.start_year>a.end_year:p.error('start-year must not exceed end-year')
    root=pathlib.Path(a.output);root.mkdir(parents=True,exist_ok=True);frames=[];dates=[];events=[];hashes={}
    protocol=pathlib.Path('configs/tpex_proxy_protocol.json');hashes[str(protocol)]=hashlib.sha256(protocol.read_bytes()).hexdigest()
    overrides={}
    for item in a.event_override:
        year,path=item.split('=',1);year=int(year)
        if year in overrides or not a.start_year<=year<=a.end_year:p.error('duplicate or out-of-range event override')
        overrides[year]=pathlib.Path(path)
    for year in range(a.start_year,a.end_year+1):
        r=pathlib.Path(f'deliverables/tpex_{year}');q=r/f'quotes_with_type_{year}.csv.gz';e=overrides.get(year,r/'event_coverage.json')
        h=hashlib.sha256(q.read_bytes()).hexdigest()
        if h!=json.loads((r/'annual_verification.json').read_text())['output_sha256']:raise ValueError('Input quote hash mismatch')
        hashes[str(q)]=h;hashes[str(e)]=hashlib.sha256(e.read_bytes()).hexdigest()
        event_doc=json.loads(e.read_text())
        if event_doc['summary']['year']!=year or any(not row['event_date'].startswith(f'{year}-') for row in event_doc['records']):raise ValueError('Wrong event source year')
        for name,expected_hash in event_doc['summary'].get('prior_year_source_hashes',{}).items():
            if hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()!=expected_hash:raise ValueError('Event audit prior-year input drift')
        frames.append(pd.read_csv(q,dtype={'code':str,'date':str}));events.extend(event_doc['records'])
        dates.extend(d for m in json.loads((r/'calendar_audit.json').read_text())['months'] for d in m['dates'])
    days=pd.DatetimeIndex(sorted(set(dates)));data=pd.concat(frames,ignore_index=True);data['date']=pd.to_datetime(data['date'])
    if data.duplicated(['date','code']).any():raise ValueError('Duplicate input keys')
    grouped={}
    for e in events:grouped.setdefault(e['code'],[]).append(e)
    output=[]
    for code,f in data.groupby('code',sort=True):
        if f['primary_pool'].any():output.append(features(f,days,grouped.get(code,[])))
    result=pd.concat(output,ignore_index=True).sort_values(['date','code'])
    expected=int(data['primary_pool'].sum())
    if len(result)!=expected or result.duplicated(['date','code']).any():raise ValueError('As-of pool rows lost or duplicated')
    path=root/'features_and_gross_labels.csv.gz';temp=path.with_suffix('.pending.gz');result.to_csv(temp,index=False,compression='gzip')
    with gzip.open(temp,'rt') as f:
        if sum(1 for _ in f)-1!=expected:raise ValueError('Closed output row count differs')
    temp.replace(path)
    daily=[]
    for date,all_rows in result.groupby('date'):
        common=all_rows.dropna(subset=['vol20','atr20_pct','breakout60_volume15'])
        for method in ['vol20','atr20_pct','breakout60_volume15']:
            count=max(1,int(np.ceil(len(common)*.1)))
            chosen=common.sort_values([method,'code'],ascending=[False,True]).head(count) if method!='breakout60_volume15' else common[common[method]==1]
            row={'date':date,'method':method,'asof_primary_rows':len(all_rows),'common_feature_rows':len(common),'selected':len(chosen)}
            for w in [20,60]:
                values=chosen[f'gross_quote_return{w}'];row[f'unknown{w}']=int(values.isna().sum());row[f'mean_gross_quote_return{w}']=float(values.mean()) if values.notna().any() else None
            daily.append(row)
    pd.DataFrame(daily).to_csv(root/'rule_daily_diagnostics.csv',index=False)
    summary={'rows':len(result),'market_days':len(days),'source_hashes':hashes,'output_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rule_definition':'close > prior 60 market-day maximum close AND volume > 1.5 * prior 20 market-day mean volume; windows exclude today','gross_labels':'next market-day open to day t+20/t+60 close; missing endpoints/event transitions unknown; no future-result pool filter','not_completed':['0050 relative benchmark','transaction-cost and fill rules','strategy backtest','model training','exact corporate-action cash ledger'],'limitations':['official last/reference forward multiplier is a quote proxy, not shareholder total return','unverified events are not adjusted; crossing windows unknown','current type evidence is retrospective metadata, not historical announcement snapshot']}
    (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='source_hashes'}))

if __name__=='__main__':main()
