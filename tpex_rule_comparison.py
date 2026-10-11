"""Fixed-rule net quote proxy comparison; selected unknown outcomes remain unknown."""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
import pandas as pd
ROOT=Path('deliverables/tpex_features')
EXPECTED='871b55052d1398a0edb62e144cf2d6274ec32358d075675583b79f900c65858d'

def net_quote(gross,fee=.001425,tax=.003,slip=.005):
    return (1+gross)*(1-slip)*(1-fee-tax)/((1+slip)*(1+fee))-1

def benchmark_labels(benchmark,days,horizon):
    p=benchmark.set_index('date').reindex(days)
    entry=p.adj_open.shift(-1);end=p.adj_close.shift(-horizon)
    return (end/entry-1).where(entry.gt(0)&end.gt(0))

def strict_mean(values):
    return float(values.mean()) if len(values) and values.notna().all() else np.nan

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(ROOT));parser.add_argument('--benchmark',default='benchmark_restore/prices_adjusted_2023_2026.csv.gz');parser.add_argument('--benchmark-sha256',default=EXPECTED);parser.add_argument('--signal-year',type=int);args=parser.parse_args()
    root=Path(args.root);price=Path(args.benchmark)
    assert hashlib.sha256(price.read_bytes()).hexdigest()==args.benchmark_sha256
    feature=root/'features_and_gross_labels.csv.gz';meta=json.loads((root/'summary.json').read_text())
    assert hashlib.sha256(feature.read_bytes()).hexdigest()==meta['output_sha256']
    data=pd.read_csv(feature,dtype={'code':str},parse_dates=['date'])
    days=pd.DatetimeIndex(sorted(data.date.unique()))
    p=pd.read_csv(price,usecols=['date','symbol','adj_open','adj_close'],dtype={'symbol':str},parse_dates=['date'])
    b=p[p.symbol.eq('0050')].copy();assert not b.date.duplicated().any()
    for w in [20,60]:
        br=benchmark_labels(b,days,w)
        data[f'relative{w}']=net_quote(data[f'gross_quote_return{w}'])-data.date.map(br)
    rows=[]
    for date,g in data.groupby('date',sort=True):
        if args.signal_year is not None and date.year!=args.signal_year:continue
        common=g.dropna(subset=['vol20','atr20_pct','breakout60_volume15'])
        if len(common)<100:continue
        for method in ['vol20','atr20_pct','breakout60_volume15']:
            n=int(np.ceil(len(common)*.1))
            chosen=common.sort_values([method,'code'],ascending=[False,True]).head(n) if method!='breakout60_volume15' else common[common[method].eq(1)]
            row=dict(date=date.strftime('%Y-%m-%d'),method=method,common_pool=len(common),selected=len(chosen))
            for w in [20,60]:
                values=chosen[f'relative{w}'];row[f'unknown{w}']=int(values.isna().sum())
                row[f'strict_net_relative{w}']=strict_mean(values)
                row[f'observed_only_net_relative{w}']=float(values.mean()) if values.notna().any() else None
            rows.append(row)
    daily=pd.DataFrame(rows);daily.to_csv(root/'rule_net_relative_daily.csv',index=False)
    summaries=[]
    for (year,method),g in daily.groupby([daily.date.str[:4], 'method']):
        for w in [20,60]:
            v=g[f'strict_net_relative{w}'];summaries.append(dict(signal_year=int(year),method=method,horizon=w,dates=len(g),known_complete_selection_dates=int(v.notna().sum()),unknown_selected_rows=int(g[f'unknown{w}'].sum()),empty_selection_dates=int(g.selected.eq(0).sum()),mean_net_relative=float(v.mean()) if v.notna().any() else None))
    result=dict(feature_sha256=meta['output_sha256'],benchmark_prices_sha256=args.benchmark_sha256,rows=len(data),market_days=len(days),costs=dict(commission=.001425,sell_tax=.003,slippage_each_side=.005),formula='(1+gross)*(1-slip)*(1-fee-tax)/((1+slip)*(1+fee))-1 - gross0050',pool='same as-of feature-complete pool, >=100 rows; no future-label filter',summary=summaries,limitations=['quote proxy, not fills or shareholder total return','overlapping horizons, daily means are not portfolio CAGR','any unknown selected endpoint makes strict date mean unknown; observed-only diagnostic separate','historical years already researched, not untouched holdout'])
    (root/'rule_comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# 上櫃固定規則：扣成本後相對 0050 報價代理','','同一當時特徵完整池（至少100檔），波動率及ATR各取前10%；突破放量使用事先固定規則。任何選中端點未知，當日整組均值即未知。未按未來結果替換股票。','','| 訊號年 | 方法 | 期間 | 完整已知日／評估日 | 未知選中筆數 | 平均相對代理報酬 |','|---|---|---:|---:|---:|---:|']
    for r in summaries:
        value=f"{r['mean_net_relative']*100:+.2f}%" if r['mean_net_relative'] is not None else '未知'
        lines.append(f"| {r['signal_year']} | {r['method']} | {r['horizon']}日 | {r['known_complete_selection_dates']}/{r['dates']} | {r['unknown_selected_rows']} | {value} |")
    lines+=['','手續費單邊0.1425%、賣出稅0.3%、單邊滑價0.5%，沿用既有 medium_term_protocol；0050使用同一進出端點之未扣成本還原報價。價格來源 SHA-256 已與本次執行明確指定的固定值核對。','', '以上為重疊持有窗口的日訊號平均，不能相乘成累積投資報酬。公司行動採經驗證之參考價銜接代理，不是精確配息、持股及現金帳；此表不是可成交回測，也不是校準飆股機率。','', '下一步：沿用固定區塊長度檢查條件已知日期的不確定性；歷史年份不稱新留出，不擴大調參。']
    (root/'rule_comparison.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result))
if __name__=='__main__':main()
