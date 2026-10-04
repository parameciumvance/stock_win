"""Fixed-score 2026 liquidity and screen sensitivity; no score refitting.

This audit describes past turnover, not order-book depth or executable NAV.
Threshold alternatives are post-hoc diagnostics, not parameter selection.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from twse_history.research_v5 import feature_panel


METHODS = {'logistic': 'logistic', 'mom60_skip5': 'mom60_skip5'}
THRESHOLDS = [10_000_000, 30_000_000, 100_000_000]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
                        default=Path('twse_history/output_multiyear_2023_2026_asof_20261002'))
    parser.add_argument('--output', type=Path, default=Path('deliverables'))
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    prices = pd.read_csv(args.source / 'prices_adjusted_2023_2026.csv.gz',
                         dtype={'symbol': str}, parse_dates=['date'])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    panel = feature_panel(prices, calendar)[['date', 'symbol', 'turnover20', 'signal_eligible']]
    score = pd.read_csv(args.output / 'holdout_scores_2026_v57.csv.gz',
                        dtype={'symbol': str}, parse_dates=['date'])
    joined = score.merge(panel, on=['date', 'symbol'], how='left', validate='one_to_one')
    if (len(joined) != 110932 or joined[['turnover20', 'logistic', 'mom60_skip5']].isna().any().any()
            or not joined.signal_eligible.eq(True).all()
            or not joined.turnover20.ge(THRESHOLDS[0] - .01).all()):
        raise ValueError('The fixed 2026 holdout frame does not match eligible features')
    selected_rows = []
    daily_rows = []
    for threshold in THRESHOLDS:
        eligible = joined[joined.turnover20.ge(threshold)].copy()
        for date, group in eligible.groupby('date', sort=True):
            k = math.ceil(.1 * len(group))
            if not k:
                raise ValueError('No candidates on date')
            for method, column in METHODS.items():
                # Score file order is stable; symbol tie-break makes output repeatable.
                winners = group.sort_values([column, 'symbol'], ascending=[False, True]).head(k).copy()
                winners['threshold_twd'] = threshold
                winners['method'] = method
                selected_rows.append(winners[['date', 'symbol', 'threshold_twd', 'method',
                                               'turnover20', 'surge_adjusted']])
                daily_rows.append(dict(date=date.date().isoformat(), method=method,
                                       threshold_twd=threshold, candidate_count=len(group),
                                       top_count=k,
                                       top_positive_rate=float(winners.surge_adjusted.mean()),
                                       top_median_turnover_twd=float(winners.turnover20.median()),
                                       top_min_turnover_twd=float(winners.turnover20.min()),
                                       top_share_below_30m=float(winners.turnover20.lt(30_000_000).mean()),
                                       top_share_below_100m=float(winners.turnover20.lt(100_000_000).mean())))
    selected = pd.concat(selected_rows, ignore_index=True)
    daily = pd.DataFrame(daily_rows)
    summaries = []
    for (threshold, method), group in selected.groupby(['threshold_twd', 'method'], sort=True):
        d = daily[(daily.threshold_twd == threshold) & (daily.method == method)]
        eligible = joined[joined.turnover20.ge(threshold)]
        summaries.append(dict(threshold_twd=int(threshold), method=method,
                              market_dates=len(d), candidate_stock_days=int(d.candidate_count.sum()),
                              candidate_positive_rate=float(eligible.surge_adjusted.mean()),
                              selected_stock_days=len(group),
                              top_positive_rate_daily_mean=float(d.top_positive_rate.mean()),
                              selected_turnover_median_twd=float(group.turnover20.median()),
                              selected_turnover_q10_twd=float(group.turnover20.quantile(.1)),
                              selected_share_below_30m=float(group.turnover20.lt(30_000_000).mean()),
                              selected_share_below_100m=float(group.turnover20.lt(100_000_000).mean()),
                              min_turnover_median_by_day_twd=float(d.top_min_turnover_twd.median())))
    summary = pd.DataFrame(summaries)
    base = summary[summary.threshold_twd.eq(10_000_000)]
    if (not len(base) == 2 or
            not np.isclose(float(base[base.method.eq('logistic')].top_positive_rate_daily_mean.iloc[0]),
                           .332282, atol=.0001) or
            not np.isclose(float(base[base.method.eq('mom60_skip5')].top_positive_rate_daily_mean.iloc[0]),
                           .286937, atol=.0001)):
        raise ValueError('Fixed baseline daily metrics drifted from v57')
    daily.to_csv(args.output / 'holdout_liquidity_daily_2026_v59.csv', index=False)
    summary.to_csv(args.output / 'holdout_liquidity_summary_2026_v59.csv', index=False)
    info = dict(source='v57 fixed 2026 score file', rows=len(joined), dates=joined.date.nunique(),
                thresholds_twd=THRESHOLDS, thresholds_are_posthoc_diagnostics=True,
                no_refit=True, no_execution_claim=True)
    (args.output / 'holdout_liquidity_meta_2026_v59.json').write_text(json.dumps(info, indent=2))
    print(summary.to_string(index=False))


if __name__ == '__main__':
    main()
