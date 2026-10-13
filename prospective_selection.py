"""Seven frozen TPEx methods on one validated, as-of feature matrix.

This module selects candidates only. A separate raw-source replay must create
and verify the feature matrix before this result can become a live signal.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from prospective_journal import verify

FEATURES = ['mom1', 'mom5', 'mom20', 'mom60', 'vol20', 'atr20_pct', 'volume_ratio20']
RULES = ['revenue_acceleration', 'institutional_five_days', 'breakout60_volume15']
METHODS = RULES + ['all_three', 'vol20', 'atr20_pct', 'mom60']
REQUIRED = FEATURES + RULES + ['date', 'code', 'flow_source_date', 'proxy_available_date', 'month_end']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def select(frame, signal_date, protocol):
    """Return a complete same-pool selection or explicit incomplete status."""
    date = pd.Timestamp(signal_date)
    if pd.isna(date) or date.strftime('%Y-%m-%d') != signal_date:
        raise ValueError('Signal date must be ISO day')
    if METHODS != protocol['methods']:
        raise ValueError('Frozen method list differs from implementation')
    source = json.loads(Path('configs/tpex_event_rules_protocol.json').read_text())
    if source['min_common_pool'] != 100 or source['top_fraction_baselines'] != .1:
        raise ValueError('Frozen pool or ranking changed')
    if any(k not in frame for k in REQUIRED):
        raise ValueError('Missing required feature/provenance column')
    if any(k.startswith(('target', 'gross_quote_return', 'label', 'relative')) for k in frame):
        raise ValueError('Future outcome columns forbidden in prospective matrix')
    if frame.duplicated(['date', 'code']).any() or frame.code.isna().any():
        raise ValueError('Duplicate or empty security key')
    if not frame.date.eq(signal_date).all():
        raise ValueError('Mixed dates in daily matrix')
    if frame.empty:
        return dict(signal_date=signal_date, status='missing_inputs', source_rows=0, common_pool=0, selections={})
    values = frame.copy()
    for col in FEATURES + RULES:
        values[col] = pd.to_numeric(values[col], errors='coerce')
    for col in RULES:
        known = values[col].dropna()
        if not known.isin([0, 1]).all():
            raise ValueError('Rule is not 0/1/unknown: ' + col)
    flow = pd.to_datetime(values.flow_source_date, errors='coerce')
    proxy = pd.to_datetime(values.proxy_available_date, errors='coerce')
    month_end = pd.to_datetime(values.month_end, errors='coerce')
    known = np.isfinite(values[FEATURES + RULES].to_numpy(dtype=float)).all(axis=1)
    if (flow[known].isna() | proxy[known].isna() | month_end[known].isna()).any():
        raise ValueError('Known features require dated sources')
    if (flow[known] >= date).any() or (proxy[known] > date).any():
        raise ValueError('Future or same-day institutional source, or future revenue')
    if ((date - month_end[known]).dt.days > 100).any():
        raise ValueError('Stale revenue rule cannot enter common pool')
    if (month_end[known] + pd.Timedelta(days=protocol['primary']['revenue_proxy_lag_calendar_days']) >= proxy[known]).any():
        raise ValueError('Revenue proxy date did not follow frozen lag')
    common = values.loc[known].copy()
    if len(common) < source['min_common_pool']:
        return dict(signal_date=signal_date, status='insufficient_pool', source_rows=len(values), common_pool=len(common), selections={})
    common['all_three'] = common[RULES].min(axis=1)
    count = int(np.ceil(len(common) * source['top_fraction_baselines']))
    selections = {}
    for method in METHODS:
        if method in RULES + ['all_three']:
            chosen = common.loc[common[method].eq(1)].sort_values('code', kind='stable')
        else:
            chosen = common.sort_values([method, 'code'], ascending=[False, True], kind='stable').head(count)
        selections[method] = chosen.code.astype(str).tolist()
    return dict(signal_date=signal_date, status='complete', source_rows=len(values), common_pool=len(common), selections=selections)


def validate_snapshot_refs(root, refs, signal_date):
    if not refs or len(refs) != len(set(refs)):
        raise ValueError('Unique raw snapshot records required')
    for ref in refs:
        if not ref or not all(ch.isascii() and (ch.isalnum() or ch in '_-') for ch in ref):
            raise ValueError('Unsafe snapshot key')
        record = verify(root / 'snapshot' / (ref + '.json'))
        if record['kind'] != 'snapshot':
            raise ValueError('Expected snapshot record')
        observed = pd.Timestamp(record['observed_at'])
        if observed.tz_convert('Asia/Taipei').date() > pd.Timestamp(signal_date).date():
            raise ValueError('Snapshot observed after signal day')
        raw_hash = record['payload']['raw_sha256']
        raw = root / 'raw' / raw_hash
        if digest(raw.read_bytes()) != raw_hash:
            raise ValueError('Raw snapshot hash mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--matrix-sha256', required=True)
    parser.add_argument('--snapshot-key', action='append', required=True)
    parser.add_argument('--journal', type=Path, default=Path('deliverables/prospective_journal'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    protocol_path = Path('configs/tpex_prospective_protocol.json')
    protocol = json.loads(protocol_path.read_text())
    if args.date < protocol['earliest_signal_date']:
        raise ValueError('Before preregistered start')
    matrix_bytes = args.matrix.read_bytes()
    if digest(matrix_bytes) != args.matrix_sha256:
        raise ValueError('Feature matrix hash mismatch')
    validate_snapshot_refs(args.journal, args.snapshot_key, args.date)
    matrix = pd.read_csv(args.matrix, dtype={'code': str, 'date': str})
    result = select(matrix, args.date, protocol)
    result.update(protocol_sha256=digest(protocol_path.read_bytes()), matrix_sha256=args.matrix_sha256,
                  snapshot_records=args.snapshot_key, source_status='derived_matrix_raw_replay_pending')
    if args.out.exists():
        raise FileExistsError(args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as f:
        json.dump(result, f, sort_keys=True, indent=2)
        f.write('\n')
    print(args.out, digest(args.out.read_bytes()))


if __name__ == '__main__':
    main()
