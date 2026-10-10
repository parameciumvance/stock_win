"""Fixed 60-market-day forecasts, monthly selections and quote-proxy diagnostics."""
from pathlib import Path
import argparse,gzip,hashlib,json
import numpy as np
import pandas as pd
import joblib,sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from audit_institutional_increment import dataset,PRICE_FEATURES,FLOW_FEATURES
from audit_revenue_proxy import evaluate_day
from audit_institutional_uncertainty import circular_block_intervals
from twse_history.revenue_proxy import attach_features,REVENUE_FEATURES,sha
from twse_history.margin_features import build_features,MARGIN_FEATURES

OUT=Path('deliverables/medium_term');CONFIG=Path('configs/medium_term_protocol.json')
ALL_FEATURES=PRICE_FEATURES+FLOW_FEATURES+REVENUE_FEATURES+MARGIN_FEATURES


def endpoint_labels(prices,days,horizon,fee,tax,slip):
    if horizon<1 or days.has_duplicates or prices.duplicated(['date','symbol']).any():raise ValueError('Invalid label inputs')
    benchmark=prices[prices.symbol.eq('0050')].set_index('date').reindex(days)
    bo=benchmark.adj_open.shift(-1);bc=benchmark.adj_close.shift(-horizon)
    br=(bc/bo-1).where(bo.gt(0)&bc.gt(0))
    result=[]
    for symbol,g in prices[prices.universe_role.eq('common_stock')].groupby('symbol',sort=True):
        p=g.set_index('date').reindex(days);entry=p.adj_open.shift(-1);exit=p.adj_close.shift(-horizon)
        net=exit*(1-slip)*(1-fee-tax)/(entry*(1+slip)*(1+fee))-1
        target=(net-br).where(entry.gt(0)&exit.gt(0))
        f=pd.DataFrame(dict(date=days,symbol=symbol,endpoint_target=target.to_numpy(),
            label_window_end=pd.Series(days).shift(-horizon).to_numpy(),entry_date=pd.Series(days).shift(-1).to_numpy(),
            signal_close=p.close.to_numpy()))
        result.append(f)
    return pd.concat(result,ignore_index=True)


def prepare():
    c=json.loads(CONFIG.read_text());OUT.mkdir(exist_ok=True,parents=True)
    if sha(c['prices'])!=c['expected_prices_sha256']:raise ValueError('Price hash mismatch')
    with gzip.open(c['flows'],'rb') as f:
        h=hashlib.sha256()
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    if h.hexdigest()!=c['expected_flows_csv_sha256']:raise ValueError('Exact frozen flow CSV mismatch')
    source_hashes=dict(prices=sha(c['prices']),flow_csv=h.hexdigest(),protocol=sha(CONFIG))
    _,_,_,full=dataset(c['prices'],c['flows'],pd.Timestamp('2025-12-31'),c['commission'],c['sell_tax'],c['slippage_each_side'],2023,2026,return_candidates=True,label_read_end=c['asof'])
    full=full[full.date.le(c['asof'])].copy();days=pd.DatetimeIndex(full.date.unique()).sort_values()
    full=full[['date','symbol','eligible']+PRICE_FEATURES+FLOW_FEATURES]
    monthly_path=Path('inputs/revenue_proxy/monthly_features.csv.gz');a=json.loads(Path('deliverables/revenue_proxy/acquisition.json').read_text())
    if sha(monthly_path)!=a['features_sha256']:raise ValueError('Revenue hash mismatch')
    monthly=pd.read_csv(monthly_path,dtype={'symbol':str},parse_dates=['month_end'])
    full=attach_features(full,monthly,days,c['revenue_lag'],c['max_revenue_age'])
    flows=[]
    for year in [2023,2024,2025,2026]:
        p=Path(f'inputs/margin/margin_twse_{year}.csv.gz');a=json.loads(Path(f'deliverables/margin/acquisition_{year}.json').read_text())
        if sha(p)!=a['normalized_sha256']:raise ValueError('Credit hash mismatch')
        f=pd.read_csv(p,dtype={'symbol':str},keep_default_na=False);f['date']=pd.to_datetime(f.date.astype(str))
        if len(f)!=a['raw_security_rows'] or f.date.nunique()!=a['days']:raise ValueError('Credit coverage mismatch')
        source_hashes[str(year)]=sha(p);flows.append(f)
    flows=pd.concat(flows,ignore_index=True)
    if not pd.DatetimeIndex(flows.date.unique()).sort_values().equals(days):raise ValueError('Different market clock')
    credit=build_features(flows,days);full=full.merge(credit,on=['date','symbol'],how='left',validate='one_to_one')
    valid=full.eligible&np.isfinite(full[ALL_FEATURES]).all(axis=1);common=full[valid].copy();del full,credit,flows
    prices=pd.read_csv(c['prices'],usecols=['date','symbol','open','close','adj_open','adj_close','universe_role'],dtype={'symbol':str},parse_dates=['date'])
    prices=prices[prices.date.le(c['asof'])&prices.date.ge('2023-01-01')]
    labels=endpoint_labels(prices,days,c['horizon'],c['commission'],c['sell_tax'],c['slippage_each_side'])
    common=common.merge(labels,on=['date','symbol'],how='left',validate='one_to_one')
    if not common.margin_source_date.lt(common.date).all() or not common.proxy_available_date.le(common.date).all():raise ValueError('Feature time leakage')
    common['score_year']=common.entry_date.dt.year;common['mom60']=common.r60
    month_entries=pd.Series(days,index=days).groupby(days.to_period('M')).first()
    common['monthly_signal']=common.entry_date.isin(month_entries.to_numpy())
    path=Path('inputs/medium_term/common.pkl.gz');path.parent.mkdir(exist_ok=True,parents=True)
    temp=path.with_name('common.pending.gz');common.to_pickle(temp,compression={'method':'gzip','compresslevel':1,'mtime':0});temp.replace(path)
    source_hashes['revenue']=sha(monthly_path)
    meta=dict(path=str(path),sha256=sha(path),rows=len(common),input_sha256=source_hashes,market_days=len(days),
        market_calendar_sha256=hashlib.sha256('\n'.join(days.strftime('%Y-%m-%d')).encode()).hexdigest())
    (OUT/'matrix.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta),flush=True)


def paired(daily,lhs,rhs,c):
    a=lhs+'_top_net_relative';b=rhs+'_top_net_relative';known=daily[[a,b]].notna().all(axis=1)
    diff=(daily.loc[known,a]-daily.loc[known,b]).to_numpy();r=dict(observed_paired_dates=int(known.sum()),excluded_unknown_dates=int((~known).sum()),mean=float(diff.mean()) if len(diff) else None,intervals={})
    for block in c['block_lengths']:
        r['intervals'][str(block)]=circular_block_intervals(diff[:,None],block,c['replicates'],c['seed'])[0] if len(diff)>block else dict(status='insufficient_paired_dates',required_more_than=block)
    return r


def run(year):
    c=json.loads(CONFIG.read_text());meta=json.loads((OUT/'matrix.json').read_text())
    if meta['input_sha256']['protocol']!=sha(CONFIG) or sha(meta['path'])!=meta['sha256']:raise ValueError('Cache/protocol mismatch')
    common=pd.read_pickle(meta['path'],compression='gzip');cutoff=pd.Timestamp(f'{year-1}-12-31')
    train=common[common.date.le(cutoff)&common.label_window_end.le(cutoff)&np.isfinite(common.endpoint_target)]
    test=common[common.score_year.eq(year)].copy()
    if len(train)<1000 or test.empty or train.label_window_end.max()>test.date.min():raise ValueError('Invalid training purge')
    models={}
    with threadpool_limits(limits=2):
        for name,cols in [('price_ridge',PRICE_FEATURES),('all_ridge',ALL_FEATURES),('price_tree',PRICE_FEATURES),('all_tree',ALL_FEATURES)]:
            if name.endswith('ridge'):
                model=make_pipeline(StandardScaler(),Ridge(alpha=c['ridge_alpha']));model.fit(train[cols],train.endpoint_target);sc,rg=model.steps[0][1],model.steps[1][1]
                detail=dict(features=cols,scaler_mean=sc.mean_.tolist(),scaler_scale=sc.scale_.tolist(),coefficients=rg.coef_.tolist(),intercept=float(rg.intercept_))
            else:
                model=HistGradientBoostingRegressor(**c['tree_parameters']);model.fit(train[cols],train.endpoint_target)
                path=OUT/f'{name}_{year}.joblib';joblib.dump(model,path,compress=3);detail=dict(features=cols,path=str(path),sha256=sha(path),iterations=int(model.n_iter_))
            test[name]=model.predict(test[cols]);models[name]=detail;print(f'year={year} model={name} fitted train={len(train)} test={len(test)}',flush=True)
    rows=[];tops=[];monthly_rows=[];monthly_tops=[]
    for _,g in test.groupby('date',sort=True):
        if len(g)<c['min_pool_size']:continue
        row,top=evaluate_day(g,c['top_fraction'],c['models']);rows.append(row);tops.append(top)
        if g.monthly_signal.all():
            row,top=evaluate_day(g,c['top_fraction'],c['models'],top_count=c['monthly']['top_n'])
            top['entry_date']=g.entry_date.iloc[0];monthly_rows.append(row);monthly_tops.append(top)
    daily=pd.DataFrame(rows);monthly_daily=pd.DataFrame(monthly_rows)
    daily.to_csv(OUT/f'daily_{year}.csv',index=False);monthly_daily.to_csv(OUT/f'monthly_{year}.csv',index=False)
    pd.concat(tops,ignore_index=True).to_csv(OUT/f'top_selections_{year}.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    pd.concat(monthly_tops,ignore_index=True).to_csv(OUT/f'monthly_selections_{year}.csv',index=False)
    # Scores for monthly portfolio replay do not depend on future outcomes.
    test[test.monthly_signal].to_pickle(OUT/f'monthly_candidates_{year}.pkl.gz',compression={'method':'gzip','compresslevel':1,'mtime':0})
    result=dict(year=year,train_rows=len(train),train_last_label_end=str(train.label_window_end.max().date()),test_rows=len(test),scored_dates=len(daily),first_signal=str(test.date.min().date()),last_signal=str(test.date.max().date()),monthly_signals=len(monthly_daily),input_sha256=meta['input_sha256'],matrix_sha256=meta['sha256'],sklearn_version=sklearn.__version__,models=models,
        primary=paired(daily,'all_tree','price_tree',c['uncertainty']),secondary_ridge=paired(daily,'all_ridge','price_ridge',c['uncertainty']),secondary_model=paired(daily,'all_tree','all_ridge',c['uncertainty']),methods={})
    for name in c['models']:
        result['methods'][name]=dict(mean_relative_60d_proxy=float(daily[name+'_top_net_relative'].mean()),known_top_dates=int(daily[name+'_top_net_relative'].notna().sum()),unknown_selected_rows=int(daily[name+'_unknown'].sum()),rank_ic_observed=float(daily[name+'_rank_ic_observed'].mean()),monthly_mean_relative_60d_proxy=float(monthly_daily[name+'_top_net_relative'].mean()),known_monthly_signals=int(monthly_daily[name+'_top_net_relative'].notna().sum()))
    (OUT/f'summary_{year}.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(year=year,primary=result['primary'])),flush=True)
    report()


def report():
    lines=['# 60 日相對報酬／每月換股研究','','60 是預測端點期間；30 萬 Top15 組合仍每月檢視，續抱入選、落榜退出。兩種持有窗口不混算。',
        '相同當時完整共同池，45 日延遲營收代理、前市场日法人／信用；固定 Ridge alpha1000／固定梯度樹，不搜尋參數。',
        '以前一年年底已結束標籤訓練；一月訊號是上一年最後市場日收盤，訓練最後端點不晚於該訊號。',
        '', '| 年度 | 全特徵樹−量價樹（pp） | 60 日區塊 95% 區間（pp） | 全特徵 Ridge−量價 Ridge（pp） |', '|---|---:|---|---:|']
    summaries=[json.loads(p.read_text()) for p in sorted(OUT.glob('summary_*.json'))]
    for s in summaries:
        a=s['primary'];ci=a['intervals']['60'];interval=f"[{ci['lower_95']*100:+.3f}, {ci['upper_95']*100:+.3f}]" if 'lower_95' in ci else '樣本不足'
        lines.append(f"| {s['year']} | {a['mean']*100:+.3f} | {interval} | {s['secondary_ridge']['mean']*100:+.3f} |")
    lines+=['','| 年度 | 方法 | 日訊號平均 60 日相對代理（%） | 端點已知的 Top10% 日數 | 已知子池 IC | 月訊號 Top15 平均 60 日相對代理（%） | 已知月數 |','|---|---|---:|---:|---:|---:|---:|']
    for s in summaries:
        for n,m in s['methods'].items():lines.append(f"| {s['year']} | {n} | {m['mean_relative_60d_proxy']*100:+.3f} | {m['known_top_dates']} | {m['rank_ic_observed']:+.4f} | {m['monthly_mean_relative_60d_proxy']*100:+.3f} | {m['known_monthly_signals']} |")
    lines+=['','60 日窗口重疊，不能把月訊號端點均值相乘當作組合報酬。月度持股與現金報價代理另見 portfolio_report.md。',
        '選股前不看未來結果；任何選中端點未知均保留、該組均值未知，不補零或替換。區塊 bootstrap 使用已知同日配對，時間缺口及 circular 邊界限制推論，月度僅 10～12 個截點不作可靠顯著性推論。',
        '2024–2026 都已研究；修訂靜態營收不是首次公告快照。此輪不是新獨立留出、校準飆股機率或成交／實股 NAV。','']
    (OUT/'report.md').write_text('\n'.join(lines))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--year',type=int,choices=[2024,2025,2026]);a=p.parse_args()
    if a.prepare:prepare()
    elif a.year:run(a.year)
    else:
        for y in [2024,2025,2026]:run(y)
