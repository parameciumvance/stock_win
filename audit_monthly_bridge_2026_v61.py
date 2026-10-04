"""Bridge fixed v57 daily rankings to the original monthly rebalance calendar.

Only label ranking and membership churn are measured; no orders or NAV.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


METHODS = ('logistic', 'mom60_skip5')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path,
                   default=Path('twse_history/output_multiyear_2023_2026_asof_20261002'))
    p.add_argument('--output', type=Path, default=Path('deliverables'))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    score = pd.read_csv(a.output/'holdout_scores_2026_v57.csv.gz', dtype={'symbol': str},
                        parse_dates=['date', 'label_window_end'])
    labels = pd.read_csv(a.source/'surge_labels_adjusted_2023_2026.csv.gz',
                         usecols=['date', 'symbol', 'surge_adjusted', 'surge_next_open',
                                  'entry_open_next_adj'], dtype={'symbol': str}, parse_dates=['date'])
    raw = pd.read_csv(a.source/'prices_adjusted_2023_2026.csv.gz',
                      usecols=['date', 'symbol', 'adj_open'],
                      dtype={'symbol': str}, parse_dates=['date'])
    calendar = pd.DatetimeIndex(sorted(raw.date.unique()))
    current = calendar[(calendar.year == 2026) & (calendar <= pd.Timestamp('2026-10-02'))]
    next_month = current[1:][current[1:].month != current[:-1].month]
    signals = [(calendar[calendar.get_loc(day)-1], day) for day in next_month]
    valid_signal_dates = set(pd.Timestamp(d) for d in score.date.unique())
    signals = [(s, f) for s, f in signals if s in valid_signal_dates]
    if len(signals) != 8 or [f.month for _,f in signals] != list(range(2,10)):
        raise ValueError('Unexpected monthly signal/fill calendar')
    scored = score.merge(labels,on=['date','symbol'],validate='one_to_one',
                         suffixes=('_scored',''))
    if (len(scored) != len(score) or not scored.surge_adjusted_scored.eq(scored.surge_adjusted).all()
            or scored.duplicated(['date','symbol']).any()):
        raise ValueError('v57 scores and labels differ')
    fill_quotes = raw.rename(columns={'date':'fill_date','adj_open':'fill_adj_open'})
    selected, daily = [], []
    previous = {m: set() for m in METHODS}
    for signal, fill in signals:
        frame = scored[scored.date.eq(signal)].copy()
        if frame.empty or frame.label_window_end.max() > pd.Timestamp('2026-10-02'):
            raise ValueError('Incomplete 20 market-day target')
        k = math.ceil(len(frame) * .1)
        for method in METHODS:
            winner = frame.sort_values([method,'symbol'],ascending=[False,True]).head(k).copy()
            winner['fill_date'] = fill
            winner = winner.merge(fill_quotes,on=['fill_date','symbol'],how='left',
                                  validate='one_to_one')
            if not np.isclose(winner.entry_open_next_adj, winner.fill_adj_open,
                              equal_nan=True).all():
                raise ValueError('Label next-open price does not match actual fill date')
            symbols = set(winner.symbol)
            new = symbols - previous[method]
            sold = previous[method] - symbols
            winner['method'] = method
            winner['new_since_previous_month'] = winner.symbol.isin(new)
            selected.append(winner[['date','fill_date','method','symbol','surge_adjusted',
                                    'surge_next_open','new_since_previous_month',
                                    'label_window_end','entry_open_next_adj']])
            daily.append(dict(signal_date=signal.date().isoformat(),
                              fill_date=fill.date().isoformat(),method=method,
                              candidate_count=len(frame),top_count=k,
                              candidate_positive_rate=float(frame.surge_adjusted.mean()),
                              top_positive_rate=float(winner.surge_adjusted.mean()),
                              top_next_open_positive_rate=float(winner.surge_next_open.mean()),
                              valid_next_open=int(winner.fill_adj_open.gt(0).sum()),
                              name_overlap_count=len(symbols & previous[method]),
                              new_names=len(new),retired_names=len(sold),
                              new_names_fraction=float(len(new)/k)))
            previous[method] = symbols
    selection = pd.concat(selected,ignore_index=True)
    monthly = pd.DataFrame(daily)
    if len(selection) != int(monthly.top_count.sum()) or monthly.valid_next_open.ne(monthly.top_count).any():
        raise ValueError('Missing next-open for one of the selected names')
    summary = []
    for method, group in monthly.groupby('method',sort=True):
        after_first=group.iloc[1:]
        summary.append(dict(method=method,months=len(group),
                            total_selected_stock_months=int(group.top_count.sum()),
                            mean_candidate_positive_rate=float(group.candidate_positive_rate.mean()),
                            mean_top_positive_rate=float(group.top_positive_rate.mean()),
                            mean_top_next_open_positive_rate=float(group.top_next_open_positive_rate.mean()),
                            subsequent_months=len(after_first),
                            mean_new_names_fraction_excluding_first=float(after_first.new_names_fraction.mean()),
                            min_new_names_fraction_excluding_first=float(after_first.new_names_fraction.min()),
                            max_new_names_fraction_excluding_first=float(after_first.new_names_fraction.max())))
    summary = pd.DataFrame(summary)
    selection.to_csv(a.output/'monthly_selections_2026_v61.csv',index=False)
    monthly.to_csv(a.output/'monthly_signal_audit_2026_v61.csv',index=False)
    summary.to_csv(a.output/'monthly_summary_2026_v61.csv',index=False)
    meta=dict(training_cutoff='2025-12-31',scores_from='v57 frozen 2026 test',
              first_fill=str(signals[0][1].date()),last_fill=str(signals[-1][1].date()),
              number_of_months=len(signals),rank_fraction=.1,
              initial_rebalance_excluded_from_churn_average=True,
              no_trading_nav_or_fill_assertion=True)
    (a.output/'monthly_meta_2026_v61.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(monthly.to_string(index=False))
    print(summary.to_string(index=False))


if __name__=='__main__':
    main()
