"""Compare a 2026 as-of causal build with the same dates through 2026-10-02.

The prefix build must be prepared with build_multiyear --as-of CUTOFF.
This tests algorithmic prefix invariance, not historical announcement timestamps.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from twse_history.research_v5 import FEATURES, feature_panel


PRICE_FIELDS = ['name', 'open', 'high', 'low', 'close', 'volume', 'trades',
                'turnover_twd', 'causal_factor', 'adj_open', 'adj_high',
                'adj_low', 'adj_close', 'universe_role']
FEATURE_FIELDS = ['signal_eligible', 'history_complete120', 'turnover20', *FEATURES]


def compare(left, right, fields, float_tol=1e-10):
    keys = ['date', 'symbol']
    merged = left[keys + fields].merge(right[keys + fields], on=keys,
                                       suffixes=('_prefix', '_full'), how='outer',
                                       validate='one_to_one', indicator=True)
    if not merged._merge.eq('both').all():
        raise ValueError(f'Missing or extra keys: {merged._merge.value_counts().to_dict()}')
    mismatch = {}
    for field in fields:
        a, b = merged[field+'_prefix'], merged[field+'_full']
        if pd.api.types.is_numeric_dtype(a) and not pd.api.types.is_bool_dtype(a):
            bad = ~np.isclose(a.to_numpy(float), b.to_numpy(float), atol=float_tol,
                              rtol=1e-10, equal_nan=True)
        else:
            bad = ~a.eq(b).fillna(a.isna() & b.isna()).to_numpy(bool)
        if bad.any():
            mismatch[field] = dict(count=int(bad.sum()),
                                   examples=merged.loc[bad, keys].head(3).assign(
                                       date=lambda x: x.date.dt.strftime('%Y-%m-%d')).to_dict('records'))
    return len(merged), mismatch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix', type=Path, default=Path('inputs/prefix_20260630_v60'))
    p.add_argument('--cutoff', default='2026-06-30')
    p.add_argument('--full', type=Path,
                   default=Path('twse_history/output_multiyear_2023_2026_asof_20261002'))
    p.add_argument('--output', type=Path, default=Path('deliverables/asof_prefix_audit_v60.json'))
    a = p.parse_args()
    cutoff = pd.Timestamp(a.cutoff)
    if cutoff.year != 2026 or cutoff > pd.Timestamp('2026-10-02'):
        raise ValueError('Cutoff is outside verified 2026 window')
    name = 'prices_adjusted_2023_2026.csv.gz'
    prefix = pd.read_csv(a.prefix/name, dtype={'symbol': str}, parse_dates=['date'])
    full = pd.read_csv(a.full/name, dtype={'symbol': str}, parse_dates=['date'])
    full = full[full.date.le(cutoff)].copy()
    if prefix.date.max() != cutoff or prefix.date.nunique() != full.date.nunique():
        raise ValueError('Unexpected prefix date or calendar')
    n_price, price_mismatch = compare(prefix, full, PRICE_FIELDS)
    # Both builds' backwards factors are deliberately excluded. They depend on
    # later corporate actions and are not used by the fixed 13-feature models.
    backward = prefix[['date', 'symbol', 'backward_factor']].merge(
        full[['date', 'symbol', 'backward_factor']], on=['date', 'symbol'],
        suffixes=('_prefix', '_full'), validate='one_to_one')
    backward_drift = int((~np.isclose(backward.backward_factor_prefix,
                                     backward.backward_factor_full,
                                     atol=1e-10, rtol=1e-10, equal_nan=True)).sum())
    c1 = pd.DatetimeIndex(sorted(prefix.date.unique()))
    c2 = pd.DatetimeIndex(sorted(full.date.unique()))
    left = feature_panel(prefix, c1)
    right = feature_panel(full, c2)
    left = left[left.date.dt.year.eq(2026)].copy()
    right = right[right.date.dt.year.eq(2026)].copy()
    n_feature, feature_mismatch = compare(left, right, FEATURE_FIELDS)
    summary = dict(prefix_as_of=cutoff.date().isoformat(), full_as_of='2026-10-02',
                   compared_price_rows=n_price, compared_2026_feature_rows=n_feature,
                   retrospective_backward_factor_drift_rows=backward_drift,
                   price_fields=PRICE_FIELDS, feature_fields=FEATURE_FIELDS,
                   price_mismatch=price_mismatch, feature_mismatch=feature_mismatch,
                   caveat='Cannot prove when retrospective source facts were first published.')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('price_fields','feature_fields')},
                     ensure_ascii=False, indent=2))
    if price_mismatch or feature_mismatch:
        raise ValueError('Prefix invariance failed')


if __name__ == '__main__':
    main()
