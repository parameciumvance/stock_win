"""Frozen expanding Ridge and same-pool rules; no parameter search."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from tpex_rule_comparison import net_quote,benchmark_labels,strict_mean,EXPECTED
ROOT=Path('deliverables/tpex_features')

def intervals(values,block,replicates,seed):
    x=np.asarray(values,float);n=len(x)
    if np.isfinite(x).sum()<=block:return dict(status='insufficient_known_pairs',known=int(np.isfinite(x).sum()))
    rng=np.random.default_rng(seed);starts=rng.integers(n,size=(replicates,int(np.ceil(n/block))))
    indices=(starts[:,:,None]+np.arange(block))%n
    samples=x[indices.reshape(replicates,-1)[:,:n]]
    count=np.isfinite(samples).sum(axis=1);v=np.nansum(samples,axis=1)/np.where(count>0,count,np.nan)
    return dict(lower_95=float(np.nanquantile(v,.025)),upper_95=float(np.nanquantile(v,.975)),known=int(np.isfinite(x).sum()),calendar_positions=n)

def main():
    config=Path('configs/tpex_ridge_protocol.json');c=json.loads(config.read_text());cols=c['features']
    meta=json.loads((ROOT/'summary.json').read_text());source=ROOT/'features_and_gross_labels.csv.gz'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==meta['output_sha256']
    price=Path('benchmark_restore/prices_adjusted_2023_2026.csv.gz');assert hashlib.sha256(price.read_bytes()).hexdigest()==EXPECTED
    allrows=pd.read_csv(source,dtype={'code':str},parse_dates=['date']);days=pd.DatetimeIndex(sorted(allrows.date.unique()))
    data=allrows[np.isfinite(allrows[cols+['breakout60_volume15']]).all(axis=1)].copy()
    p=pd.read_csv(price,usecols=['date','symbol','adj_open','adj_close'],dtype={'symbol':str},parse_dates=['date']);b=p[p.symbol.eq('0050')]
    outputs=[];models=[];selected=[]
    for w in c['horizons']:
        target=net_quote(data[f'gross_quote_return{w}'],c['commission'],c['sell_tax'],c['slippage_each_side'])-data.date.map(benchmark_labels(b,days,w))
        data['target']=target;ends=pd.Series(days,index=days).shift(-w)
        data['label_end']=data.date.map(ends)
        for year in c['score_years']:
            cutoff=pd.Timestamp(f'{year-1}-12-31');train=data[data.date.le(cutoff)&data.label_end.le(cutoff)&data.target.notna()]
            test=data[data.date.dt.year.eq(year)].copy()
            assert len(train)>1000 and train.label_end.max()<test.date.min()
            model=make_pipeline(StandardScaler(),Ridge(alpha=c['ridge_alpha']))
            with threadpool_limits(limits=2):model.fit(train[cols],train.target);test['ridge']=model.predict(test[cols])
            sc,rg=model.steps[0][1],model.steps[1][1]
            models.append(dict(year=year,horizon=w,train_rows=len(train),last_train_label_end=str(train.label_end.max().date()),test_rows=len(test),features=cols,mean=sc.mean_.tolist(),scale=sc.scale_.tolist(),coefficient=rg.coef_.tolist(),intercept=float(rg.intercept_)))
            for date,g in test.groupby('date'):
                if len(g)<100:continue
                for method in c['methods']:
                    chosen=g.sort_values([method,'code'],ascending=[False,True]).head(int(np.ceil(len(g)*c['top_fraction']))) if method!='breakout60_volume15' else g[g[method].eq(1)]
                    known=g.target.notna()
                    ic=g.loc[known,[method,'target']].corr(method='spearman').iloc[0,1] if known.sum()>2 and g.loc[known,method].nunique()>1 else np.nan
                    outputs.append(dict(date=date.strftime('%Y-%m-%d'),year=year,horizon=w,method=method,pool=len(g),selected=len(chosen),unknown=int(chosen.target.isna().sum()),strict_mean=strict_mean(chosen.target),observed_rank_ic=ic))
                    selected.append(chosen[['date','code','target',method]].rename(columns={method:'score'}).assign(method=method,horizon=w,rank=np.arange(1,len(chosen)+1)))
            print(f'year={year} horizon={w} train={len(train)} test={len(test)}',flush=True)
    daily=pd.DataFrame(outputs);daily.to_csv(ROOT/'ridge_daily.csv',index=False)
    pd.concat(selected,ignore_index=True).to_csv(ROOT/'ridge_and_rule_selections.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    summaries=[];pairs=[]
    for (year,w,method),g in daily.groupby(['year','horizon','method']):
        summaries.append(dict(year=int(year),horizon=int(w),method=method,dates=len(g),known_dates=int(g.strict_mean.notna().sum()),unknown_selected=int(g.unknown.sum()),mean_net_relative=float(g.strict_mean.mean()),rank_ic_observed=float(g.observed_rank_ic.mean())))
    for (year,w),g in daily.groupby(['year','horizon']):
        wide=g.pivot(index='date',columns='method',values='strict_mean').reindex(days[days.year==year].strftime('%Y-%m-%d'))
        for baseline in ['vol20','atr20_pct','breakout60_volume15']:
            diff=wide.ridge-wide[baseline]
            pairs.append(dict(year=int(year),horizon=int(w),comparison='ridge-minus-'+baseline,mean=float(diff.mean()),known_pairs=int(diff.notna().sum()),intervals={str(block):intervals(diff,block,c['paired_uncertainty']['replicates'],c['paired_uncertainty']['seed']) for block in c['paired_uncertainty']['block_lengths']}))
    result=dict(protocol_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),feature_sha256=meta['output_sha256'],benchmark_sha256=EXPECTED,summary=summaries,paired=pairs,models=models,limitations=['as-of feature-complete quote-present retrospective evidence pool','proxy adjustments, not shareholder total return','unknown selected endpoints retained; conditional known-date inference','overlapping windows; no portfolio CAGR','already studied years; no fresh holdout'])
    (ROOT/'ridge_summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    lines=['# 上櫃固定 Ridge 基準','','固定 alpha=1000，僅量價特徵；以前一年年底已結束的標籤訓練，再對下一年同一當時特徵完整池排名。不調參，20／60 日分開。成本及0050口徑沿用既有規格。','','| 年度 | 期間 | 方法 | 完整已知日 | 平均相對代理 | 已知子池平均 IC |','|---|---:|---|---:|---:|---:|']
    for r in summaries:lines.append(f"| {r['year']} | {r['horizon']} | {r['method']} | {r['known_dates']}/{r['dates']} | {r['mean_net_relative']*100:+.2f}% | {r['rank_ic_observed']:+.4f} |")
    lines+=['','| 年度 | 期間 | Ridge − 基準 | 已知配對日 | 平均差（pp） | 60日區塊95%區間（pp） |','|---|---:|---|---:|---:|---|']
    for r in pairs:
        ci=r['intervals']['60'];v=f"[{ci['lower_95']*100:+.2f}, {ci['upper_95']*100:+.2f}]" if 'lower_95' in ci else '已知配對不足'
        lines.append(f"| {r['year']} | {r['horizon']} | {r['comparison']} | {r['known_pairs']} | {r['mean']*100:+.2f} | {v} |")
    lines+=['','區塊按完整市場日期位置抽樣，未知配對維持缺值；區間仍只反映可觀測配對的條件均值，缺失不是隨機時不能推論完整母體。IC亦只限已知標籤子池。','', '所有報酬為報價代理；無實際成交、精確公司權益現金帳或新独立留出。每日重疊端點均值不能變成累積投資報酬。']
    (ROOT/'ridge_report.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
