"""Explicit daily-open quote scenarios, not odd-lot fills or real share NAV."""
from pathlib import Path
import json,math
import numpy as np
import pandas as pd
from medium_term_research import CONFIG,OUT


def tickets(shares):
    n=int(max(0,math.floor(shares+1e-9)))
    return [v for v in [n//1000*1000,n%1000] if v]


def fee_for(shares,price,rate,minimum):
    return sum(max(n*price*rate,minimum) for n in tickets(shares))


def plan_shares(reference,budget,c):
    if not np.isfinite(reference) or reference<=0 or budget<=0:return 0
    price=reference*(1+c['monthly']['price_buffer']);lo=0;hi=int(budget//price)+1
    while lo<hi:
        mid=(lo+hi+1)//2;cost=mid*price+fee_for(mid,price,c['commission'],c['monthly']['min_fee_per_ticket'])
        if cost<=budget:lo=mid
        else:hi=mid-1
    return lo


def simulate(prices,signals,method,c):
    days=pd.DatetimeIndex(prices.date.unique()).sort_values();quotes=prices.set_index(['date','symbol']).sort_index()
    cash=float(c['monthly']['capital']);pending=[];holdings={};ledger=[];events=[];missing_marks=0
    schedule={pd.Timestamp(entry):g for entry,g in signals.groupby('entry_date')}
    def quote(day,symbol,col):
        try:v=float(quotes.loc[(day,symbol),col]);return v if np.isfinite(v) and v>0 else np.nan
        except KeyError:return np.nan
    def marked(day,col):
        values=[units*quote(day,s,col) for s,units in holdings.items()]
        return cash+sum(amount for _,amount in pending)+sum(values) if all(np.isfinite(values)) else np.nan
    for i,day in enumerate(days):
        traded=0.;fees=0.;failed=0
        if day in schedule:
            g=schedule[day].sort_values([method,'symbol'],ascending=[False,True]);top=g.head(c['monthly']['top_n']);selected=set(top.symbol)
            signal=pd.Timestamp(g.date.iloc[0]);signal_equity=marked(signal,'adj_close')
            for symbol in sorted(set(holdings)-selected):
                raw=quote(day,symbol,'open');adj=quote(day,symbol,'adj_open')
                if not np.isfinite(raw) or not np.isfinite(adj):
                    failed+=1;events.append(dict(date=str(day.date()),model=method,symbol=symbol,action='sell',status='missing_open_cancel_keep_holding'));continue
                units=holdings.pop(symbol);gross=units*adj*(1-c['slippage_each_side']);equivalent_shares=gross/(raw*(1-c['slippage_each_side']))
                fee=fee_for(equivalent_shares,raw*(1-c['slippage_each_side']),c['commission'],c['monthly']['min_fee_per_ticket'])
                proceeds=gross-fee-gross*c['sell_tax'];pending.append((i+2,proceeds));traded+=gross;fees+=fee+gross*c['sell_tax']
                events.append(dict(date=str(day.date()),model=method,symbol=symbol,action='sell',status='hypothetical_quote_sale',gross=gross,fee=fee,settles_at_market_index=i+2))
            for _,r in top.iterrows():
                symbol=r.symbol
                if symbol in holdings:continue
                reference=float(r.signal_close);budget=min(c['monthly']['per_new_name_budget'],max(0,cash-c['monthly']['reserve_twd']))
                shares=plan_shares(reference,budget,c);raw=quote(day,symbol,'open');adj=quote(day,symbol,'adj_open');limit=reference*(1+c['monthly']['price_buffer'])
                status='hypothetical_quote_buy'
                if not np.isfinite(signal_equity):status='unknown_signal_portfolio_mark'
                elif shares<1:status='cash_or_one_share_gate'
                elif not np.isfinite(raw) or not np.isfinite(adj):status='missing_open'
                elif raw*(1+c['slippage_each_side'])>limit:status='buy_limit_not_met'
                if status!='hypothetical_quote_buy':
                    failed+=1;events.append(dict(date=str(day.date()),model=method,symbol=symbol,action='buy',status=status,planned_shares=shares));continue
                fill=raw*(1+c['slippage_each_side']);gross=shares*fill;fee=fee_for(shares,fill,c['commission'],c['monthly']['min_fee_per_ticket']);cost=gross+fee
                if cost>cash-c['monthly']['reserve_twd']+1e-9:raise ValueError('Cash sizing violation')
                cash-=cost;holdings[symbol]=gross/(adj*(1+c['slippage_each_side']));traded+=gross;fees+=fee
                events.append(dict(date=str(day.date()),model=method,symbol=symbol,action='buy',status=status,planned_shares=shares,whole_shares=shares//1000*1000,odd_shares=shares%1000,gross=gross,fee=fee))
        # T+2 proceeds available at that day's close, never at its assumed open.
        due=sum(amount for index,amount in pending if index<=i);cash+=due;pending=[(index,amount) for index,amount in pending if index>i]
        nav=marked(day,'adj_close');missing_marks+=int(not np.isfinite(nav))
        if cash<c['monthly']['reserve_twd']-1e-8:raise ValueError('Reserve overdraft')
        ledger.append(dict(date=str(day.date()),model=method,cash=cash,unsettled_cash=sum(v for _,v in pending),holdings=len(holdings),quote_proxy_nav=nav,traded_value=traded,costs=fees,failed_candidates=failed))
    return pd.DataFrame(ledger),pd.DataFrame(events)


def run():
    c=json.loads(CONFIG.read_text());frames=[]
    for y in c['years']:
        path=OUT/f'monthly_candidates_{y}.pkl.gz'
        if not path.exists():raise ValueError('Missing owned scored monthly matrix')
        frames.append(pd.read_pickle(path,compression='gzip'))
    signals=pd.concat(frames,ignore_index=True);first=signals.entry_date.min()
    prices=pd.read_csv(c['prices'],usecols=['date','symbol','open','close','adj_open','adj_close'],dtype={'symbol':str},parse_dates=['date'])
    prices=prices[prices.date.ge(first)&prices.date.le(c['asof'])].copy()
    all_daily=[];all_events=[];summary=[]
    for method in c['models']:
        daily,events=simulate(prices,signals,method,c);all_daily.append(daily);all_events.append(events)
        final=daily.quote_proxy_nav.iloc[-1];valid=daily.quote_proxy_nav.notna();returns=daily.quote_proxy_nav.pct_change(fill_method=None)
        # Never label a gapped mark path as complete drawdown/Sharpe evidence.
        dd=float((daily.quote_proxy_nav/daily.quote_proxy_nav.cummax()-1).min()) if valid.all() else None
        result=dict(model=method,final_quote_proxy_value=float(final) if np.isfinite(final) else None,
            cumulative_quote_proxy_return=float(final/c['monthly']['capital']-1) if np.isfinite(final) else None,
            known_mark_days=int(valid.sum()),unknown_mark_days=int((~valid).sum()),max_drawdown_complete_path=dd,
            costs=float(daily.costs.sum()),traded_value=float(daily.traded_value.sum()),buy_limit_failures=int(events.status.eq('buy_limit_not_met').sum()),
            cash_gate_failures=int(events.status.eq('cash_or_one_share_gate').sum()),missing_open_failures=int(events.status.isin(['missing_open','missing_open_cancel_keep_holding']).sum()),
            min_cash=float(daily.cash.min()),last_holdings=int(daily.holdings.iloc[-1]),last_cash=float(daily.cash.iloc[-1]))
        summary.append(result);print(json.dumps(result),flush=True)
    pd.concat(all_daily,ignore_index=True).to_csv(OUT/'portfolio_daily.csv',index=False)
    pd.concat(all_events,ignore_index=True).to_csv(OUT/'portfolio_events.csv',index=False)
    benchmark=prices[prices.symbol.eq('0050')].set_index('date').sort_index()
    bo=benchmark.loc[first,'adj_open'] if first in benchmark.index else np.nan;last=pd.Timestamp(c['asof']);bc=benchmark.loc[last,'adj_close'] if last in benchmark.index else np.nan
    benchmark_return=float(bc/bo-1) if np.isfinite(bo) and np.isfinite(bc) and bo>0 else None
    result=dict(status='synthetic_adjusted_return_daily_open_cash_proxy_not_actual_nav',first_entry=str(first.date()),asof=c['asof'],monthly_signal_count=int(signals.entry_date.nunique()),benchmark_0050_gross_buy_hold=benchmark_return,summaries=summary)
    (OUT/'portfolio_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# 30 萬元每月 Top15：持股與現金報價代理','','60 日模型每月排名；續抱仍入選持股，落榜才退出。不是每月把完整本金再投入另一批 60 日持股。',
        '原始收盤＋1% 做整數委託預算；每新檔上限 19,000 元，5% 初始現金保留，整股與零股分票最低費各 20 元的示意情境。買進每日開盤＋0.5% 僅作假設價格，超過限價就取消、不替補。',
        '賣款採保守 T+2 收盤可用，不先使用未交割賣款。原始／還原價換算合成報酬單位，權益與再投資是代理，無法當作實際股數或零股成交。賣出票數也只是由合成等價股數估算的費用情境。',
        '缺買价取消、缺賣价保留舊持股；持股缺價當日總值未知，不補前值。缺價路徑不報完整最大回撤。未知訊號持股估值不新增買單。',
        '', '| 方法 | 截止日合成代理值（元） | 累計代理（%） | 費用情境（元） | 未知估值日 | 限價取消／現金閘門 |','|---|---:|---:|---:|---:|---|']
    for s in summary:
        nav=f"{s['final_quote_proxy_value']:,.0f}" if s['final_quote_proxy_value'] is not None else '未知';r=f"{s['cumulative_quote_proxy_return']*100:+.2f}" if s['cumulative_quote_proxy_return'] is not None else '未知'
        lines.append(f"| {s['model']} | {nav} | {r} | {s['costs']:,.0f} | {s['unknown_mark_days']} | {s['buy_limit_failures']}／{s['cash_gate_failures']} |")
    br=f'{benchmark_return*100:+.2f}%' if benchmark_return is not None else '未知'
    lines+=['',f'相同首個進場開盤至截止收盤的 0050 還原價買進持有毛報酬：{br}。這是全投入基準，與策略現金／風險曝險不同，不稱同風險 Alpha。',
        '日彙總價格不能证明 9:10 起的盤中零股撮合；券商最低費仍待真實條件。2024–2026 已研究，所有值只是合成報價假設結果，並非 30 萬元可實現盈虧。',
        '原始公司權益與實際股數現金帳仍 pending；這輪先用有限成本與成交假設測試研究方向，不恢復大量逐檔人工權益核對。','']
    (OUT/'portfolio_report.md').write_text('\n'.join(lines))

if __name__=='__main__':run()
