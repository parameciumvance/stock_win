"""Add audited gross cash-dividend entitlements to monthly quote observations.

Cash is accrued at ex-date for an original share, not assumed spendable then.
Rights/share changes and missing quotes remain excluded; this is not NAV.
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
    p.add_argument('--raw',type=Path,default=Path('twse_history/raw/exrights_2026.json'))
    p.add_argument('--output',type=Path,default=Path('deliverables'))
    a=p.parse_args()
    selected=pd.read_csv(a.output/'clean_monthly_quote_returns_2026_v65.csv',
                         dtype={'symbol':str},parse_dates=['entry_date','exit_observation_date'])
    actions=pd.read_csv(a.source/'corporate_actions_2023_2026.csv',
                        dtype={'symbol':str},parse_dates=['effective_date'])
    actions=actions[actions.effective_date.dt.year.eq(2026)]
    raw=json.loads(a.raw.read_text())
    if raw.get('stat')!='OK' or raw['fields'].count('權值+息值')!=1:
        raise ValueError('Unexpected official raw ex-rights data')
    d=pd.DataFrame(raw['data'],columns=raw['fields'])
    cash=d[d['權/息'].eq('息')].copy()
    token=cash['詳細資料'].str.split(',',expand=True)
    cash['symbol']=token[0]
    cash['effective_date']=pd.to_datetime(token[1],format='%Y%m%d',errors='raise')
    for field in ('權值+息值','除權息前收盤價','除權息參考價'):
        cash[field]=pd.to_numeric(cash[field].str.replace(',','',regex=False),errors='raise')
    cash=cash.set_index(['symbol','effective_date'])
    if cash.index.has_duplicates or cash['權值+息值'].le(0).any():
        raise ValueError('Cash ex-dividend keys or values are invalid')
    selected_cash_audit=[]
    history={s:g for s,g in actions.groupby('symbol')}
    detail=[]
    for row in selected.itertuples(index=False):
        start,end=row.entry_date,row.exit_observation_date
        source=history.get(row.symbol)
        within=(source[(source.effective_date.gt(start))&
                       (source.effective_date.le(end))] if source is not None else
                actions.iloc[:0])
        entry_actions=(source[source.effective_date.eq(start)] if source is not None else
                       actions.iloc[:0])
        unresolved=within[~(within.event_type.eq('exrights') & within.event_subtype.eq('息'))]
        cash_events=within[(within.event_type.eq('exrights'))&within.event_subtype.eq('息')]
        accrual=0.
        for event in cash_events.itertuples(index=False):
            raw_event=cash.loc[(row.symbol,event.effective_date)]
            cash_value=float(raw_event['權值+息值'])
            ref_delta=float(raw_event['除權息前收盤價']-raw_event['除權息參考價'])
            if abs(ref_delta-cash_value)>.011:
                raise ValueError(f'Cash reference mismatch {row.symbol} {event.effective_date}')
            accrual+=cash_value
            selected_cash_audit.append(dict(symbol=row.symbol,event_date=event.effective_date,
                                            method=row.method,entry_date=start,
                                            official_cash_per_share=cash_value,
                                            reference_delta=ref_delta,
                                            raw_detail_key=f'{row.symbol},{event.effective_date:%Y%m%d}'))
        available=(row.missing_or_nontrade_days==0 and len(unresolved)==0 and
                   np.isfinite(row.entry_raw_open) and np.isfinite(row.exit_raw_open) and
                   row.entry_raw_open>0 and row.exit_raw_open>0)
        gross_return=((row.exit_raw_open+accrual)/row.entry_raw_open-1) if available else np.nan
        if row.complete_action_free and (not available or
                not np.isclose(gross_return,row.open_to_open_price_return,atol=1e-10)):
            raise ValueError('v65 action-free return did not carry forward')
        detail.append(dict(method=row.method,entry_date=start,exit_observation_date=end,
                           symbol=row.symbol,selected_surge_label=row.selected_surge_label,
                           entry_raw_open=row.entry_raw_open,exit_raw_open=row.exit_raw_open,
                           entry_day_action_count=len(entry_actions),
                           in_holding_cash_event_count=len(cash_events),
                           in_holding_unresolved_event_count=len(unresolved),
                           missing_or_nontrade_days=row.missing_or_nontrade_days,
                           gross_cash_per_original_share=accrual,
                           gross_cash_entitlement_proxy_available=available,
                           gross_price_plus_cash_return=gross_return))
    detail=pd.DataFrame(detail)
    audit=pd.DataFrame(selected_cash_audit)
    if len(detail)!=1232 or detail.duplicated(['method','entry_date','symbol']).any():
        raise ValueError('Incomplete monthly selections')
    monthly=detail.groupby(['method','entry_date','exit_observation_date'],as_index=False).agg(
        selected=('symbol','size'),available=('gross_cash_entitlement_proxy_available','sum'),
        cash_event_stock_months=('in_holding_cash_event_count',lambda x:int(x.gt(0).sum())),
        unresolved_stock_months=('in_holding_unresolved_event_count',lambda x:int(x.gt(0).sum())),
        entry_day_action_stock_months=('entry_day_action_count',lambda x:int(x.gt(0).sum())),
        mean_gross_price_plus_cash_return=('gross_price_plus_cash_return','mean'))
    monthly['coverage']=monthly.available/monthly.selected
    summary=monthly.groupby('method',as_index=False).agg(
        months=('entry_date','size'),selected_stock_months=('selected','sum'),
        available=('available','sum'),cash_event_stock_months=('cash_event_stock_months','sum'),
        unresolved_stock_months=('unresolved_stock_months','sum'),
        entry_day_action_stock_months=('entry_day_action_stock_months','sum'),
        mean_monthly_coverage=('coverage','mean'),
        mean_gross_price_plus_cash_return_by_month=('mean_gross_price_plus_cash_return','mean'),
        positive_proxy_months=('mean_gross_price_plus_cash_return',lambda x:int(x.gt(0).sum())))
    detail.to_csv(a.output/'cash_only_monthly_proxy_2026_v66.csv',index=False)
    monthly.to_csv(a.output/'cash_only_monthly_proxy_by_month_2026_v66.csv',index=False)
    summary.to_csv(a.output/'cash_only_monthly_proxy_summary_2026_v66.csv',index=False)
    audit.to_csv(a.output/'cash_only_event_audit_2026_v66.csv',index=False)
    meta=dict(holding_interval='after entry open through exit open',
              entry_ex_date_does_not_entitle_buyer=True,exit_ex_date_entitles_prior_holder=True,
              cash_source='official 2026 TWT49U 權值+息值 for 權/息=息 only',
              cash_is_gross_receivable_not_payment_date_balance=True,
              rights_and_share_changes_excluded=True,complete_daily_prices_required=True,
              quote_is_not_order_fill=True,fees_and_taxes_not_included=True,
              still_not_nav_or_alpha=True)
    (a.output/'cash_only_monthly_proxy_meta_2026_v66.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False)+'\n')
    print(summary.to_string(index=False))
    print(monthly.to_string(index=False))


if __name__=='__main__':
    main()
