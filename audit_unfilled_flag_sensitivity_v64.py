"""Diagnostic zero-credit sensitivity for near-10% one-price new buys.

This post-trade flagging is not an executable strategy or a true NAV backtest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('deliverables'))
    a=p.parse_args()
    selected=pd.read_csv(a.output/'monthly_selections_2026_v62.csv',dtype={'symbol':str})
    orders=pd.read_csv(a.output/'monthly_proposed_orders_2026_v63.csv',dtype={'symbol':str})
    buys=orders[orders.side.eq('buy')][['method','fill_date','symbol',
                                      'one_price_up_near_10pct','one_price_session']]
    joined=selected.merge(buys,on=['method','fill_date','symbol'],how='left',validate='one_to_one')
    if len(joined)!=1232 or joined.duplicated(['method','fill_date','symbol']).any():
        raise ValueError('Expected v62 selections')
    # Retained names have no new entry attempt this month; missing merge = no flag.
    joined['flag_unfilled']=joined.one_price_up_near_10pct.eq(True)
    if int(joined.flag_unfilled.sum())!=7:
        raise ValueError('Unexpected one-price-up buy count')
    joined['credit_close']=joined.surge_adjusted & ~joined.flag_unfilled
    joined['credit_next_open']=joined.surge_next_open & ~joined.flag_unfilled
    monthly=joined.groupby(['method','fill_date'],as_index=False).agg(
        selected_names=('symbol','size'),flagged_unfilled=('flag_unfilled','sum'),
        original_close_hit=('surge_adjusted','mean'),
        zero_credit_close_hit=('credit_close','mean'),
        original_next_open_hit=('surge_next_open','mean'),
        zero_credit_next_open_hit=('credit_next_open','mean'))
    if len(monthly)!=18 or not monthly.selected_names.between(59,75).all():
        raise ValueError('Unexpected month coverage')
    summary=monthly.groupby('method',as_index=False).agg(
        months=('fill_date','size'),selected_stock_months=('selected_names','sum'),
        flagged_unfilled=('flagged_unfilled','sum'),
        original_close_hit=('original_close_hit','mean'),
        zero_credit_close_hit=('zero_credit_close_hit','mean'),
        original_next_open_hit=('original_next_open_hit','mean'),
        zero_credit_next_open_hit=('zero_credit_next_open_hit','mean'))
    summary['close_drop_pp']=100*(summary.original_close_hit-summary.zero_credit_close_hit)
    summary['next_open_drop_pp']=100*(summary.original_next_open_hit-summary.zero_credit_next_open_hit)
    monthly.to_csv(a.output/'monthly_unfilled_sensitivity_daily_2026_v64.csv',index=False)
    summary.to_csv(a.output/'monthly_unfilled_sensitivity_summary_2026_v64.csv',index=False)
    meta=dict(assumption='Every one-price new buy >=9.5% above prior raw close gets zero label credit',
              other_selections_unchanged=True,denominator_kept_at_full_top10=True,
              missed_orders_are_not_replaced=True,cash_and_exits_not_simulated=True,
              flag_uses_fill_day_ohlcv_after_the_signal=True,
              not_tradeable_nav=True)
    (a.output/'monthly_unfilled_sensitivity_meta_2026_v64.json').write_text(
        json.dumps(meta,indent=2)+'\n')
    print(summary.to_string(index=False))


if __name__=='__main__':
    main()
