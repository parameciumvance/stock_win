"""Fixed nonlinear exploration on the exact credit-study common pool."""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
import joblib,sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from audit_institutional_increment import PRICE_FEATURES,FLOW_FEATURES
from twse_history.revenue_proxy import REVENUE_FEATURES,sha
from twse_history.margin_features import MARGIN_FEATURES
from audit_revenue_proxy import evaluate_day,paired_summary


def run(year):
    protocol=json.loads(Path('configs/fundamental_tree_protocol.json').read_text())
    base=json.loads(Path(protocol['base_protocol']).read_text())
    meta=json.loads(Path(f'deliverables/margin/common_cache_{year}.json').read_text())
    if sha(meta['cache'])!=meta['cache_sha256']:raise ValueError('Owned matrix cache checksum mismatch')
    # This is a generated local cache, never an untrusted downloaded pickle.
    common=pd.read_pickle(meta['cache'],compression='gzip')
    if len(common)!=meta['rows']:raise ValueError('Cache row count mismatch')
    for key,path in [('prices',json.loads(Path(base['revenue_protocol']).read_text())['prices']),
                     ('flows',json.loads(Path(base['revenue_protocol']).read_text())['flows']),
                     ('revenue','inputs/revenue_proxy/monthly_features.csv.gz'),
                     ('protocol',protocol['base_protocol'])]:
        if sha(path)!=meta['input_sha256'][key]:raise ValueError('Changed prerequisite '+key)
    for source_year in range(2023,year+1):
        if sha(f'inputs/margin/margin_twse_{source_year}.csv.gz')!=meta['input_sha256'][str(source_year)]:raise ValueError('Changed credit source')
    cutoff=pd.Timestamp(f'{year-1}-12-31')
    train=common[common.date.le(cutoff)&common.label_window_end.le(cutoff)&np.isfinite(common.endpoint_target)]
    test=common[common.date.dt.year.eq(year)].copy()
    expected=json.loads(Path(f'deliverables/margin/summary_{year}.json').read_text())
    if len(train)!=expected['train_rows'] or len(test)!=expected['common_rows']:raise ValueError('Different Ridge study scope')
    if not test.margin_source_date.lt(test.date).all():raise ValueError('Credit time leakage')
    saved=json.loads(Path(f'deliverables/margin/models_{year}.json').read_text())
    m=saved['models']['all_margin'];cols=m['features']
    test['all_margin_ridge']=((test[cols].to_numpy()-np.array(m['scaler_mean']))/np.array(m['scaler_scale']))@np.array(m['coefficients'])+m['intercept']
    # Verify the same test pool and baseline rankings before examining tree results.
    check=pd.DataFrame([evaluate_day(g,base['top_fraction'],['all_margin_ridge'])[0] for _,g in test.groupby('date') if len(g)>=base['min_pool_size']])
    original=pd.read_csv(f'deliverables/margin/daily_{year}.csv')
    if not check.date.equals(original.date) or not check.pool.equals(original.pool):raise ValueError('Baseline date/pool mismatch')
    if not np.allclose(check.all_margin_ridge_top_net_relative,original.all_margin_top_net_relative,equal_nan=True,atol=1e-12,rtol=0):raise ValueError('Baseline selection mismatch')
    output=Path('deliverables/fundamental_tree');output.mkdir(exist_ok=True,parents=True)
    features=dict(price_tree=PRICE_FEATURES,all_tree=PRICE_FEATURES+FLOW_FEATURES+REVENUE_FEATURES,
                  all_margin_tree=PRICE_FEATURES+FLOW_FEATURES+REVENUE_FEATURES+MARGIN_FEATURES)
    models={}
    with threadpool_limits(limits=2):
        for name,cols in features.items():
            estimator=HistGradientBoostingRegressor(**protocol['parameters'])
            estimator.fit(train[cols],train.endpoint_target)
            test[name]=estimator.predict(test[cols])
            path=output/f'{name}_{year}.joblib';joblib.dump(estimator,path,compress=3)
            models[name]=dict(path=str(path),sha256=sha(path),features=cols,iterations=int(estimator.n_iter_))
            print(f'year={year} model={name} fit_complete train={len(train)} test={len(test)}',flush=True)
    scores=list(features)+['all_margin_ridge','vol20'];rows=[];tops=[]
    for _,g in test.groupby('date',sort=True):
        if len(g)<base['min_pool_size']:continue
        row,top=evaluate_day(g,base['top_fraction'],scores);rows.append(row);tops.append(top)
    daily=pd.DataFrame(rows);daily.to_csv(output/f'daily_{year}.csv',index=False)
    pd.concat(tops,ignore_index=True).to_csv(output/f'top_selections_{year}.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    result=dict(year=year,train_rows=len(train),test_rows=len(test),train_last_label_end=str(train.label_window_end.max().date()),
        matrix=meta,protocol_sha256=sha('configs/fundamental_tree_protocol.json'),sklearn_version=sklearn.__version__,models=models,
        ridge_daily_replay_exact=True,primary=paired_summary(daily,'all_margin_tree','price_tree',protocol['uncertainty']),
        secondary_ridge=paired_summary(daily,'all_margin_tree','all_margin_ridge',protocol['uncertainty']),
        secondary_credit=paired_summary(daily,'all_margin_tree','all_tree',protocol['uncertainty']),methods={})
    for name in scores:
        result['methods'][name]=dict(mean_relative_quote_proxy=float(daily[name+'_top_net_relative'].mean()),
            known_top_dates=int(daily[name+'_top_net_relative'].notna().sum()),unknown_top_rows=int(daily[name+'_unknown'].sum()),
            rank_ic_observed=float(daily[name+'_rank_ic_observed'].mean()))
    (output/f'summary_{year}.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(year=year,primary=result['primary']['mean'],ci=result['primary']['intervals']['20'])),flush=True)
    report(output)


def report(output):
    summaries=[json.loads(p.read_text()) for p in sorted(output.glob('summary_*.json'))]
    lines=['# 固定梯度樹基準','','HistGradientBoostingRegressor，參數於訓練前固定；不搜尋參數、不啟用隨機 early stopping。',
        '與信用 Ridge 使用完全相同的當時共同股票池、次日開盤／20 市場日端點、交易成本及年度 purged 訓練。Ridge 係數重播的日期、股票池及選股代理均值已逐日核對。',
        '', '| 年度 | 全特徵樹−量價樹（百分點） | 20 日區塊 95% 區間 | 全特徵樹−全特徵 Ridge（百分點） |','|---|---:|---|---:|']
    for s in summaries:
        a=s['primary'];ci=a['intervals']['20']
        lines.append(f"| {s['year']} | {a['mean']*100:+.3f} | [{ci['lower_95']*100:+.3f}, {ci['upper_95']*100:+.3f}] | {s['secondary_ridge']['mean']*100:+.3f} |")
    lines+=['','| 年度 | 模型 | 平均成本後相對代理（%） | 已知完整選股日 | 已知端點子池 IC |','|---|---|---:|---:|---:|']
    for s in summaries:
        for name,m in s['methods'].items():
            lines.append(f"| {s['year']} | {name} | {m['mean_relative_quote_proxy']*100:+.3f} | {m['known_top_dates']} | {m['rank_ic_observed']:+.4f} |")
    lines+=['','主要差值使用同日配對；選中未知未來端點不補零、不替換，整組均值標為未知。',
        '月營收為固定延遲靜態代理，來源可能有修訂；信用原始快照沒有完整修訂軌跡。日窗口重疊、已知日期條件及 circular bootstrap 均限制推論。',
        '所有年度已研究，不是新獨立留出、年度 NAV、可證明成交或校準飆股機率。模型檔僅供可信來源重播；不得載入不可信 joblib/pickle。',
        '下一步：依跨年證據决定維持 20 日目標或預先固定新的持有期；不得挑最好年度設定宣稱有效。','']
    (output/'report.md').write_text('\n'.join(lines))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True,choices=[2024,2025,2026]);run(p.parse_args().year)
