"""Frozen as-of credit increment on the observed price/flow/revenue common pool."""
from __future__ import annotations
import json
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from audit_institutional_increment import dataset,PRICE_FEATURES,FLOW_FEATURES
from audit_revenue_proxy import evaluate_day,paired_summary,verify_flow
from twse_history.revenue_proxy import attach_features,REVENUE_FEATURES,sha
from twse_history.margin_features import build_features,MARGIN_FEATURES


def run(years=None,prepare_only=False):
    config=json.loads(Path('configs/margin_protocol.json').read_text())
    years=years or config['years']
    if any(y not in config['years'] for y in years):raise ValueError('Year outside frozen protocol')
    last_year=max(years)
    base=json.loads(Path(config['revenue_protocol']).read_text())
    if sha(base['prices'])!=base['expected_prices_sha256']:raise ValueError('Frozen price checksum mismatch')
    verify_flow(base['flows'],base['expected_flows_sha256'],base['reconstructed_flows_csv_sha256'])
    frames=[];input_hashes={}
    for year in range(config['start_year'],last_year+1):
        p=Path(f'inputs/margin/margin_twse_{year}.csv.gz')
        a=json.loads(Path(f'deliverables/margin/acquisition_{year}.json').read_text())
        if sha(p)!=a['normalized_sha256']:raise ValueError('Credit input checksum mismatch')
        f=pd.read_csv(p,dtype={'symbol':str,'date':str},keep_default_na=False)
        f['date']=pd.to_datetime(f.date)
        if f.date.nunique()!=a['days'] or len(f)!=a['raw_security_rows']:raise ValueError('Credit source coverage mismatch')
        frames.append(f);input_hashes[str(year)]=sha(p)
    flows=pd.concat(frames,ignore_index=True)
    _,_,_,full=dataset(base['prices'],base['flows'],pd.Timestamp('2025-12-31'),base['commission'],
                      base['sell_tax'],base['slippage_each_side'],2023,2026,return_candidates=True,label_read_end=base['asof'])
    full=full[full.date.le(base['asof'])].copy();days=pd.DatetimeIndex(full.date.unique()).sort_values()
    expected_days=days[days.year<=last_year]
    if not pd.DatetimeIndex(flows.date.unique()).sort_values().equals(expected_days):raise ValueError('Credit dates differ from market clock')
    monthly_path=Path('inputs/revenue_proxy/monthly_features.csv.gz')
    a=json.loads(Path('deliverables/revenue_proxy/acquisition.json').read_text())
    if sha(monthly_path)!=a['features_sha256']:raise ValueError('Revenue input checksum mismatch')
    monthly=pd.read_csv(monthly_path,dtype={'symbol':str},parse_dates=['month_end'])
    full=attach_features(full,monthly,days,config['revenue_lag'],base['max_age_calendar_days'])
    credit=build_features(flows,days)
    output=Path('deliverables/margin');output.mkdir(exist_ok=True,parents=True)
    credit_path=Path(f'inputs/margin/features_2023_{last_year}.csv.gz')
    credit.to_csv(credit_path,index=False,compression={'method':'gzip','mtime':0})
    full=full.merge(credit,on=['date','symbol'],how='left',validate='one_to_one')
    existing=full.eligible & np.isfinite(full[PRICE_FEATURES+FLOW_FEATURES+REVENUE_FEATURES]).all(axis=1)
    complete=existing & np.isfinite(full[MARGIN_FEATURES]).all(axis=1)
    common=full[complete].copy()
    columns=dict(price=PRICE_FEATURES,all=PRICE_FEATURES+FLOW_FEATURES+REVENUE_FEATURES,
                 price_margin=PRICE_FEATURES+MARGIN_FEATURES,
                 all_margin=PRICE_FEATURES+FLOW_FEATURES+REVENUE_FEATURES+MARGIN_FEATURES)
    scores=list(columns)+['vol20']
    input_hashes.update(prices=sha(base['prices']),flows=sha(base['flows']),revenue=sha(monthly_path),
                        credit_features=sha(credit_path),protocol=sha('configs/margin_protocol.json'))
    # Owned, hash-verified cache only; never load externally supplied pickle files.
    cache=Path(f'inputs/margin/common_2023_{last_year}.pkl.gz')
    cols=list(dict.fromkeys(columns['all_margin']+['date','symbol','revenue_month','proxy_available_date',
        'month_end','endpoint_target','label_window_end','margin_source_date']))
    common=common[common.date.dt.year.le(last_year)][cols].copy()
    pending=cache.with_name(cache.name+'.pending')
    common.to_pickle(pending,compression='gzip');pending.replace(cache)
    cache_meta=dict(cache=str(cache),cache_sha256=sha(cache),input_sha256=input_hashes,rows=len(common))
    (output/f'common_cache_{last_year}.json').write_text(json.dumps(cache_meta,indent=2)+'\n')
    if prepare_only:
        print(json.dumps(cache_meta),flush=True);return
    summaries=[]
    for year in years:
        cutoff=pd.Timestamp(f'{year-1}-12-31')
        train=common[common.date.le(cutoff)&common.label_window_end.le(cutoff)&np.isfinite(common.endpoint_target)]
        test=common[common.date.dt.year.eq(year)].copy()
        if len(train)<1000 or train.label_window_end.max()>cutoff:raise ValueError('Invalid training scope/purge')
        models={}
        for name,cols in columns.items():
            model=make_pipeline(StandardScaler(),Ridge(alpha=config['ridge_alpha']))
            model.fit(train[cols],train.endpoint_target);test[name]=model.predict(test[cols])
            sc,rg=model.steps[0][1],model.steps[1][1]
            models[name]=dict(features=cols,scaler_mean=sc.mean_.tolist(),scaler_scale=sc.scale_.tolist(),
                              coefficients=rg.coef_.tolist(),intercept=float(rg.intercept_))
        rows=[];tops=[]
        for _,g in test.groupby('date',sort=True):
            if len(g)<config['min_pool_size']:continue
            row,top=evaluate_day(g,config['top_fraction'],scores);rows.append(row);tops.append(top)
        daily=pd.DataFrame(rows)
        daily.to_csv(output/f'daily_{year}.csv',index=False)
        pd.concat(tops,ignore_index=True).to_csv(output/f'top_selections_{year}.csv.gz',index=False,compression={'method':'gzip','mtime':0})
        (output/f'models_{year}.json').write_text(json.dumps(dict(input_sha256=input_hashes,train_cutoff=str(cutoff.date()),models=models),indent=2)+'\n')
        primary=paired_summary(daily,'all_margin','all',config['uncertainty'])
        secondary=paired_summary(daily,'price_margin','price',config['uncertainty'])
        validyear=full.date.dt.year.eq(year)
        result=dict(year=year,train_rows=len(train),train_last_label_end=str(train.label_window_end.max().date()),
                    previous_common_rows=int((existing&validyear).sum()),common_rows=len(test),
                    credit_incomplete_rows=int((existing&~complete&validyear).sum()),scored_dates=len(daily),
                    primary=primary,secondary=secondary,input_sha256=input_hashes,methods={})
        for name in scores:
            col=name+'_top_net_relative'
            result['methods'][name]=dict(mean_relative_quote_proxy=float(daily[col].mean()),known_top_dates=int(daily[col].notna().sum()),
              unknown_top_rows=int(daily[name+'_unknown'].sum()),rank_ic_observed=float(daily[name+'_rank_ic_observed'].mean()))
        (output/f'summary_{year}.json').write_text(json.dumps(result,indent=2)+'\n');summaries.append(result)
        print(json.dumps(dict(year=year,common_rows=len(test),credit_increment=primary['mean'],primary_interval=primary['intervals']['20'])),flush=True)
    previous=output/'crossyear_summary.json'
    prior=json.loads(previous.read_text())['summaries'] if previous.exists() else []
    observed={s['year']:s for s in prior};observed.update({s['year']:s for s in summaries})
    combined=dict(config=config,summaries=[observed[y] for y in sorted(observed)],status='exploratory_quote_proxy_not_independent_holdout')
    (output/'crossyear_summary.json').write_text(json.dumps(combined,indent=2)+'\n')
    report(combined,output)


def report(x,output):
    lines=['# 融資融券增量：固定跨年研究','','前市場日信用餘額與已公告次一營業日狀態，加入量價＋法人＋45 日延遲營收代理。',
    '固定 Ridge alpha=1000；當時完整共同池選 Top10%，未知未來端點不補零或替換。成本、20 市場日持有及 expanding purged 年度切分沿用月營收固定研究。',
    '融資／融券每日餘額變化先除以前日餘額＋1 再取完整 1／5／20 日平均；利用率除以已公告限額＋1，比例固定截值；所有特徵延後一市場日。缺列不推斷信用資格。',
    '', '| 年度 | 當時共同池列數 | 信用特徵缺列 | 配對已知日 | 信用增量（百分點） | 20 日區塊 95% 區間（百分點） |',
    '|---|---:|---:|---:|---:|---:|']
    for s in x['summaries']:
        a=s['primary'];ci=a['intervals']['20']
        lines.append(f"| {s['year']} | {s['common_rows']:,} | {s['credit_incomplete_rows']:,} | {a['observed_paired_dates']} | {a['mean']*100:+.3f} | [{ci['lower_95']*100:+.3f}, {ci['upper_95']*100:+.3f}] |")
    lines+=['','| 年度 | 方法 | 平均成本後相對代理（%） | 已知完整選股日 | 已知端點子池 IC |','|---|---|---:|---:|---:|']
    for s in x['summaries']:
        for name,m in s['methods'].items():lines.append(f"| {s['year']} | {name} | {m['mean_relative_quote_proxy']*100:+.3f} | {m['known_top_dates']} | {m['rank_ic_observed']:+.4f} |")
    lines+=['','各方法已知日可能不同，結論用同日配對。次比較 price_margin−price 與完整 10／20／40 日區塊敏感度見 JSON。',
      '原始来源、schema、餘額恒等式、hash、日曆與缺列在取得時檢查。信用交易不是借券交易，資料不證明限價成交。',
      '歷史營收可能修訂、信用來源不是完整修訂軌跡；日選股窗口重疊、完整結果日篩選、時間缺口與 circular bootstrap 邊界連接都限制推論。',
      '2024–2026 已研究；本結果不是年度 NAV、實盤效益、校準飆股機率或新的獨立留出。30 萬仍為虛擬本金。',
      '', '下一個方法決定：是否維持短期 20 市場日研究，或改成較長持有期重新固定標籤與換股規則；不能只挑當前結果較好的設定。', '']
    (output/'report.md').write_text('\n'.join(lines))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--year',type=int,choices=[2024,2025,2026])
    p.add_argument('--prepare-only',action='store_true')
    a=p.parse_args();run([a.year] if a.year else None,a.prepare_only)
