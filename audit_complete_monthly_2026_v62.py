"""Complete January-to-September 2026 monthly labels with a Dec-2025 signal.

Refits the frozen v57 Logistic training fold, verifies the 2026-01-02 scores,
then adds 2025-12-31 to the v61 monthly signals. No fill/NAV is asserted.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from twse_history.research_v5 import FEATURES, feature_panel, training_frame


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,
                   default=Path('twse_history/output_multiyear_2023_2026_asof_20261002'))
    p.add_argument('--output',type=Path,default=Path('deliverables'))
    a=p.parse_args()
    name='_2023_2026.csv.gz'
    prices=pd.read_csv(a.source/('prices_adjusted'+name),dtype={'symbol':str},parse_dates=['date'])
    labels=pd.read_csv(a.source/('surge_labels_adjusted'+name),dtype={'symbol':str},
                       parse_dates=['date','label_window_end'])
    roles=pd.read_csv(a.source/('temporal_split'+name),dtype={'symbol':str},parse_dates=['date'])
    calendar=pd.DatetimeIndex(sorted(prices.date.unique()))
    if len(calendar)!=905 or calendar[calendar.year == 2026][0]!=pd.Timestamp('2026-01-02'):
        raise ValueError('Unexpected official calendar')
    features=feature_panel(prices,calendar)
    panel=training_frame(features,labels,roles,[('2429',pd.Timestamp('2024-07-02'))])
    start=pd.Timestamp('2026-01-01')
    train=panel[panel.signal_eligible & panel.label_available.eq(True) &
                ~panel.quarantined_label & panel.date.lt(start) &
                panel.label_window_end.lt(start)].copy()
    if len(train)!=381756 or train.label_window_end.max()!=pd.Timestamp('2025-12-31'):
        raise ValueError('Frozen v57 train fold differs')
    model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500))
    model.fit(train[FEATURES],train.surge_adjusted.astype(int))
    checked=panel[panel.date.eq(pd.Timestamp('2026-01-02'))].copy()
    old=pd.read_csv(a.output/'holdout_scores_2026_v57.csv.gz',dtype={'symbol':str},
                    parse_dates=['date'])
    old=old[old.date.eq(pd.Timestamp('2026-01-02'))][['symbol','logistic']]
    check=checked.merge(old,on='symbol',validate='one_to_one')
    new_score=model.predict_proba(check[FEATURES])[:,1]
    max_delta=float(np.max(np.abs(new_score-check.logistic.to_numpy())))
    if len(check)<500 or max_delta>1e-12:
        raise ValueError(f'Frozen model score reproduction failed: n={len(check)} delta={max_delta}')
    signal=pd.Timestamp('2025-12-31')
    fill=pd.Timestamp('2026-01-02')
    jan=panel[panel.date.eq(signal)&panel.signal_eligible].copy()
    if jan.empty or jan.label_window_end.max()>pd.Timestamp('2026-10-02'):
        raise ValueError('Incomplete January label')
    jan['logistic']=model.predict_proba(jan[FEATURES])[:,1]
    jan['mom60_skip5']=jan.mom60_skip5.astype(float)
    jan['surge_next_open']=labels[labels.date.eq(signal)].set_index('symbol').reindex(jan.symbol).surge_next_open.to_numpy()
    jan['entry_open_next_adj']=labels[labels.date.eq(signal)].set_index('symbol').reindex(jan.symbol).entry_open_next_adj.to_numpy()
    k=math.ceil(.1*len(jan))
    if jan[['surge_next_open','entry_open_next_adj']].isna().any().any():
        raise ValueError('Missing January next-open labels')
    fill_open=prices[prices.date.eq(fill)].set_index('symbol').adj_open
    rows=[]
    month=[]
    jan_symbols={}
    for method in ('logistic','mom60_skip5'):
        winner=jan.sort_values([method,'symbol'],ascending=[False,True]).head(k).copy()
        if not np.isclose(winner.entry_open_next_adj,fill_open.reindex(winner.symbol)).all():
            raise ValueError('January next-open does not match market opening quote')
        jan_symbols[method]=set(winner.symbol)
        winner['fill_date']=fill
        winner['method']=method
        winner['new_since_previous_month']=True
        rows.append(winner[['date','fill_date','method','symbol','surge_adjusted',
                            'surge_next_open','new_since_previous_month',
                            'label_window_end','entry_open_next_adj']])
        month.append(dict(signal_date=str(signal.date()),fill_date=str(fill.date()),
                          method=method,candidate_count=len(jan),top_count=k,
                          candidate_positive_rate=float(jan.surge_adjusted.mean()),
                          top_positive_rate=float(winner.surge_adjusted.mean()),
                          top_next_open_positive_rate=float(winner.surge_next_open.mean()),
                          valid_next_open=k,name_overlap_count=0,
                          new_names=k,retired_names=0,new_names_fraction=1.0))
    saved_selection=pd.read_csv(a.output/'monthly_selections_2026_v61.csv',
                                dtype={'symbol':str},parse_dates=['date','fill_date','label_window_end'])
    saved_month=pd.read_csv(a.output/'monthly_signal_audit_2026_v61.csv')
    if len(saved_month)!=16 or len(saved_selection)!=1114:
        raise ValueError('Unexpected v61 monthly base')
    # February's prior portfolio now comes from the reconstructed January signal.
    for method in ('logistic','mom60_skip5'):
        feb_symbols=set(saved_selection[(saved_selection.fill_date.eq(pd.Timestamp('2026-02-02')))&
                                        saved_selection.method.eq(method)].symbol)
        common=len(feb_symbols & jan_symbols[method])
        mask=saved_month.fill_date.eq('2026-02-02')&saved_month.method.eq(method)
        saved_month.loc[mask,'name_overlap_count']=common
        saved_month.loc[mask,'new_names']=len(feb_symbols)-common
        saved_month.loc[mask,'retired_names']=len(jan_symbols[method])-common
        saved_month.loc[mask,'new_names_fraction']=(len(feb_symbols)-common)/len(feb_symbols)
        smask=saved_selection.fill_date.eq(pd.Timestamp('2026-02-02'))&saved_selection.method.eq(method)
        saved_selection.loc[smask,'new_since_previous_month']=(
            ~saved_selection.loc[smask,'symbol'].isin(jan_symbols[method]))
    monthly=pd.concat([pd.DataFrame(month),saved_month],ignore_index=True)
    selection=pd.concat([*rows,saved_selection],ignore_index=True)
    summary=[]
    for method,group in monthly.groupby('method',sort=True):
        later=group.iloc[1:]
        summary.append(dict(method=method,months=len(group),
                            total_selected_stock_months=int(group.top_count.sum()),
                            mean_candidate_positive_rate=float(group.candidate_positive_rate.mean()),
                            mean_top_positive_rate=float(group.top_positive_rate.mean()),
                            mean_top_next_open_positive_rate=float(group.top_next_open_positive_rate.mean()),
                            subsequent_months=len(later),
                            mean_new_names_fraction_excluding_first=float(later.new_names_fraction.mean()),
                            min_new_names_fraction_excluding_first=float(later.new_names_fraction.min()),
                            max_new_names_fraction_excluding_first=float(later.new_names_fraction.max())))
    summary=pd.DataFrame(summary)
    if (len(monthly)!=18 or not monthly.valid_next_open.eq(monthly.top_count).all() or
            len(selection)!=monthly.top_count.sum()):
        raise ValueError('Incomplete January-to-September monthly evaluation')
    monthly.to_csv(a.output/'monthly_signal_audit_2026_v62.csv',index=False)
    selection.to_csv(a.output/'monthly_selections_2026_v62.csv',index=False)
    summary.to_csv(a.output/'monthly_summary_2026_v62.csv',index=False)
    meta=dict(train_rows=len(train),train_label_max='2025-12-31',
              verified_january_2_score_rows=len(check),max_reproduction_delta=max_delta,
              january_signal=str(signal.date()),january_fill=str(fill.date()),
              january_candidates=len(jan),january_top_k=k,
              months=9,still_no_order_or_nav_proof=True)
    (a.output/'monthly_meta_2026_v62.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2))
    print(summary.to_string(index=False))


if __name__=='__main__':
    main()
