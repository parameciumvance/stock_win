"""Observed raw open-to-next-month-open returns for action-free complete paths.

This intentionally omits ambiguous stock-months and does not simulate wealth.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
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
                      usecols=['date','symbol','open','high','low','close','volume',
                               'adj_open','causal_factor'],
                      dtype={'symbol':str},parse_dates=['date'])
    quote=quote[quote.date.dt.year.eq(2026)].copy()
    actions=pd.read_csv(a.source/'corporate_actions_2023_2026.csv',
                        usecols=['symbol','effective_date','event_id'],
                        dtype={'symbol':str},parse_dates=['effective_date'])
    actions=actions[actions.effective_date.dt.year.eq(2026)]
    calendar=pd.DatetimeIndex(sorted(quote.date.unique()))
    fills=[pd.Timestamp(d) for d in sorted(selected.fill_date.unique())]
    if len(fills)!=9 or fills[0]!=pd.Timestamp('2026-01-02'):
        raise ValueError('Unexpected v62 fill dates')
    successor={day: calendar[calendar.get_loc(day)+1:][
        calendar[calendar.get_loc(day)+1:].month!=day.month][0] for day in fills}
    if successor[fills[-1]]!=pd.Timestamp('2026-10-01'):
        raise ValueError('September exit date is not available')
    history=quote.set_index(['symbol','date']).sort_index()
    if history.index.has_duplicates:
        raise ValueError('Duplicate official quote keys')
    events_by_symbol={s:g.set_index('effective_date') for s,g in actions.groupby('symbol')}
    rows=[]
    for row in selected.itertuples(index=False):
        start,end=row.fill_date,successor[row.fill_date]
        days=calendar[(calendar>=start)&(calendar<=end)]
        path=history.reindex(pd.MultiIndex.from_product([[row.symbol],days],names=['symbol','date']))
        valid=path[['open','high','low','close']].notna().all(axis=1)&path.open.gt(0)&path.volume.gt(0)
        missing=int((~valid).sum())
        events=events_by_symbol.get(row.symbol)
        in_window=events[(events.index>=start)&(events.index<=end)] if events is not None else None
        count=0 if in_window is None else len(in_window)
        raw_entry=float(path.iloc[0].open) if pd.notna(path.iloc[0].open) else np.nan
        raw_exit=float(path.iloc[-1].open) if pd.notna(path.iloc[-1].open) else np.nan
        factor_start=float(path.iloc[0].causal_factor)
        factor_end=float(path.iloc[-1].causal_factor)
        factor_drift=(not np.isclose(factor_start,factor_end,rtol=1e-10,atol=1e-10,
                                     equal_nan=True))
        clean=(missing==0 and count==0 and np.isfinite(raw_entry) and
               np.isfinite(raw_exit) and raw_entry>0 and raw_exit>0 and not factor_drift)
        if clean and not np.isclose(path.iloc[-1].adj_open/path.iloc[0].adj_open,
                                    raw_exit/raw_entry,atol=1e-9,rtol=1e-9):
            raise ValueError('Action-free raw and causal price returns differ')
        rows.append(dict(method=row.method,signal_date=row.date,entry_date=start,
                         exit_observation_date=end,symbol=row.symbol,
                         selected_surge_label=bool(row.surge_adjusted),
                         market_days_including_end=len(days),
                         missing_or_nontrade_days=missing,recorded_action_count=count,
                         factor_drift_across_interval=factor_drift,
                         recorded_action_ids='' if count==0 else '|'.join(in_window.event_id),
                         entry_raw_open=raw_entry,exit_raw_open=raw_exit,
                         complete_action_free=clean,
                         open_to_open_price_return=(raw_exit/raw_entry-1) if clean else np.nan))
    detail=pd.DataFrame(rows)
    if len(detail)!=1232 or detail.duplicated(['method','entry_date','symbol']).any():
        raise ValueError('Unexpected selection details')
    by_month=detail.groupby(['method','entry_date','exit_observation_date'],as_index=False).agg(
        selected=('symbol','size'),complete_action_free=('complete_action_free','sum'),
        rows_with_recorded_action=('recorded_action_count',lambda x:int(x.gt(0).sum())),
        rows_with_factor_drift=('factor_drift_across_interval','sum'),
        rows_with_missing_or_nontrade=('missing_or_nontrade_days',lambda x:int(x.gt(0).sum())),
        mean_clean_open_to_open_return=('open_to_open_price_return','mean'))
    # Group-wise clean labels must not be confused with all-selected positives.
    clean=detail[detail.complete_action_free]
    hit=clean.groupby(['method','entry_date','exit_observation_date']).selected_surge_label.mean().rename(
        'clean_label_positive_rate').reset_index()
    by_month=by_month.merge(hit,on=['method','entry_date','exit_observation_date'],
                            how='left',validate='one_to_one')
    by_month['coverage']=by_month.complete_action_free/by_month.selected
    if (by_month.complete_action_free.eq(0).any() or by_month.coverage.gt(1).any() or
            not np.isfinite(clean.open_to_open_price_return).all()):
        raise ValueError('Insufficient complete-case coverage')
    summary=by_month.groupby('method',as_index=False).agg(
        months=('entry_date','size'),selected_stock_months=('selected','sum'),
        complete_action_free=('complete_action_free','sum'),
        rows_with_recorded_action=('rows_with_recorded_action','sum'),
        rows_with_factor_drift=('rows_with_factor_drift','sum'),
        rows_with_missing_or_nontrade=('rows_with_missing_or_nontrade','sum'),
        mean_monthly_coverage=('coverage','mean'),
        mean_clean_open_to_open_return_by_month=('mean_clean_open_to_open_return','mean'),
        median_clean_open_to_open_return_by_month=('mean_clean_open_to_open_return','median'),
        positive_clean_months=('mean_clean_open_to_open_return',lambda x:int(x.gt(0).sum())),
        mean_clean_label_positive_rate_by_month=('clean_label_positive_rate','mean'))
    detail.to_csv(a.output/'clean_monthly_quote_returns_2026_v65.csv',index=False)
    by_month.to_csv(a.output/'clean_monthly_quote_returns_by_month_2026_v65.csv',index=False)
    summary.to_csv(a.output/'clean_monthly_quote_returns_summary_2026_v65.csv',index=False)
    meta=dict(last_data_date='2026-10-02',price_basis='raw_open_at_entry_and_next_month_first_open',
              includes_no_dividends_or_share_entitlements=True,
              excludes_any_recorded_corporate_action_during_closed_interval=True,
              excludes_any_missing_or_nontrading_market_day=True,
              quote_is_not_order_fill=True,fees_taxes_slippage_not_included=True,
              excluded_stock_months_can_be_nonrandom=True,
              not_a_portfolio_nav_or_alpha=True)
    (a.output/'clean_monthly_quote_returns_meta_2026_v65.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(summary.to_string(index=False))
    print(by_month.to_string(index=False))


if __name__=='__main__':
    main()
