"""Observe daily quote availability for v62 monthly membership changes.

These are proposed buy/sell names, not orders placed or fills achieved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,
                   default=Path('twse_history/output_multiyear_2023_2026_asof_20261002'))
    p.add_argument('--output',type=Path,default=Path('deliverables'))
    a=p.parse_args()
    selected=pd.read_csv(a.output/'monthly_selections_2026_v62.csv',
                         dtype={'symbol':str},parse_dates=['date','fill_date'])
    quote=pd.read_csv(a.source/'prices_adjusted_2023_2026.csv.gz',
                      dtype={'symbol':str},parse_dates=['date'],
                      usecols=['date','symbol','open','high','low','close','volume','turnover_twd'])
    quote=quote.rename(columns={'date':'fill_date','open':'fill_open','high':'fill_high',
                                'low':'fill_low','close':'fill_close','volume':'fill_volume',
                                'turnover_twd':'fill_turnover_twd'})
    before=quote[['fill_date','symbol','fill_close']].rename(
        columns={'fill_date':'signal_date','fill_close':'signal_close'})
    actions=pd.read_csv(a.source/'corporate_actions_2023_2026.csv',
                        dtype={'symbol':str},usecols=['symbol','effective_date'])
    actions['effective_date']=pd.to_datetime(actions.effective_date)
    actions=actions.drop_duplicates().rename(columns={'effective_date':'fill_date'})
    actions['recorded_corporate_action_on_fill']=True
    if (selected.duplicated(['method','fill_date','symbol']).any() or
            len(selected)!=1232 or selected.fill_date.nunique()!=9):
        raise ValueError('Unexpected v62 monthly membership')
    orders=[]
    for method,group in selected.groupby('method',sort=True):
        previous=set()
        for fill,monthly in group.groupby('fill_date',sort=True):
            current=set(monthly.symbol)
            signal=monthly.date.unique()
            if len(signal)!=1 or not current:
                raise ValueError('Non-unique signal or empty month')
            for side,symbols in [('buy',current-previous),('sell',previous-current)]:
                for symbol in sorted(symbols):
                    orders.append(dict(method=method,signal_date=signal[0],
                                       fill_date=fill,side=side,symbol=symbol))
            previous=current
    orders=pd.DataFrame(orders).merge(quote,on=['fill_date','symbol'],how='left',
                                     validate='many_to_one',indicator=True)
    orders=orders.merge(before,on=['signal_date','symbol'],how='left',
                        validate='many_to_one')
    orders=orders.merge(actions,on=['fill_date','symbol'],how='left',validate='many_to_one')
    orders['recorded_corporate_action_on_fill']=(
        orders.recorded_corporate_action_on_fill.eq(True))
    bought=selected[['method','fill_date','symbol','surge_adjusted']]
    orders=orders.merge(bought,on=['method','fill_date','symbol'],how='left',
                        validate='one_to_one')
    orders['observed_quote']=orders._merge.eq('both')
    orders['valid_open']=orders.observed_quote & orders.fill_open.gt(0) & orders.fill_volume.gt(0)
    orders['one_price_session']=(orders.valid_open & orders.fill_high.eq(orders.fill_low) &
                                 orders.fill_open.eq(orders.fill_high))
    orders['zero_or_missing_volume']=(~orders.fill_volume.gt(0))
    orders['raw_open_change_from_signal_close']=(orders.fill_open/orders.signal_close-1)
    orders['one_price_up_near_10pct']=(orders.one_price_session &
                                        orders.raw_open_change_from_signal_close.ge(.095))
    orders['one_price_down_near_10pct']=(orders.one_price_session &
                                          orders.raw_open_change_from_signal_close.le(-.095))
    orders['one_price_up_buy_positive']=(orders.side.eq('buy') &
                                          orders.one_price_up_near_10pct &
                                          orders.surge_adjusted.eq(True))
    # There is no auction volume or queue information in end-of-day OHLCV.
    result=orders.drop(columns='_merge').sort_values(['fill_date','method','side','symbol'])
    result.to_csv(a.output/'monthly_proposed_orders_2026_v63.csv',index=False)
    daily=result.groupby(['fill_date','method','side'],as_index=False).agg(
        proposed_names=('symbol','size'),observed_quote=('observed_quote','sum'),
        valid_open=('valid_open','sum'),one_price_session=('one_price_session','sum'),
        one_price_up_near_10pct=('one_price_up_near_10pct','sum'),
        one_price_down_near_10pct=('one_price_down_near_10pct','sum'),
        one_price_up_buy_positive=('one_price_up_buy_positive','sum'),
        zero_or_missing_volume=('zero_or_missing_volume','sum'),
        median_full_day_turnover_twd=('fill_turnover_twd','median'))
    daily.to_csv(a.output/'monthly_order_days_2026_v63.csv',index=False)
    summary=result.groupby(['method','side'],as_index=False).agg(
        proposed_names=('symbol','size'),observed_quote=('observed_quote','sum'),
        valid_open=('valid_open','sum'),one_price_session=('one_price_session','sum'),
        one_price_up_near_10pct=('one_price_up_near_10pct','sum'),
        one_price_down_near_10pct=('one_price_down_near_10pct','sum'),
        one_price_up_buy_positive=('one_price_up_buy_positive','sum'),
        zero_or_missing_volume=('zero_or_missing_volume','sum'),
        median_full_day_turnover_twd=('fill_turnover_twd','median'))
    summary.to_csv(a.output/'monthly_order_summary_2026_v63.csv',index=False)
    meta=dict(months=9,first_fill=str(result.fill_date.min().date()),
              last_fill=str(result.fill_date.max().date()),
              open_quote_is_not_guaranteed_fill=True,
              end_of_day_volume_is_not_opening_auction_depth=True,
              one_price_session_is_not_proof_of_limit_lock=True,
              corporate_action_matches_are_from_existing_reconstructed_cache=True,
              no_cash_ledger=True)
    (a.output/'monthly_order_meta_2026_v63.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(summary.to_string(index=False))
    print('unobserved names',result[~result.valid_open][['fill_date','method','side','symbol']].to_dict('records'))
    print('one-price rows',result[result.one_price_session][['fill_date','method','side','symbol']].to_dict('records'))


if __name__=='__main__':
    main()
