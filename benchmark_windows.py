"""Fail-closed fresh-purchase benchmark windows on an exact saved cash dataset."""
from decimal import Decimal
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from cash_benchmark import physical_ledger
from research_runtime import sha256
from source_checkpoint import readback


class WindowUnavailable(ValueError):
    """Explicitly unavailable; never a zero-return substitute."""


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise WindowUnavailable('Dates must be plain YYYY-MM-DD calendar dates')
    try:
        return pd.Timestamp(value)
    except ValueError as error:
        raise WindowUnavailable('Invalid calendar date') from error


def load_verified(checkpoint_path, expected_sha256):
    """Pin the old checkpoint externally, then verify every file and raw readback."""
    checkpoint_path = Path(checkpoint_path)
    if sha256(checkpoint_path) != expected_sha256:
        raise ValueError('Pinned source checkpoint differs')
    checkpoint = json.loads(checkpoint_path.read_text())
    for path, digest in checkpoint['files'].items():
        if sha256(path) != digest:
            raise ValueError('Pinned accounting dependency differs: ' + path)
    readback(checkpoint_path.parent, 'sources')
    source = json.loads((checkpoint_path.parent / 'source_ledger.json').read_text())
    market = Path('inputs/benchmark_cash_20261019/market.csv.gz')
    if not source['roundtrip_verified'] or source['status'] != 'passed_for_realized_gross_accounting' or sha256(market) != source['extracted_market_sha256']:
        raise ValueError('Unverified benchmark source')
    benchmark = CashWindowBenchmark(pd.read_csv(market), source['distributions'], source['split'])
    benchmark._provenance = dict(checkpoint_sha256=expected_sha256, market_sha256=sha256(market),
                                 source_archive_sha256=source['archive_sha256'])
    return benchmark


class CashWindowBenchmark:
    """One validated immutable data snapshot, reused over many date windows."""
    def __init__(self, frame, distributions, split):
        self._frame = frame.copy(deep=True)
        self._frame['date'] = pd.to_datetime(self._frame.date)
        self._distributions = json.loads(json.dumps(distributions))
        self._split = json.loads(json.dumps(split))
        self._provenance = None
        # Reuse the fully checked full-span accounting once to validate the snapshot.
        first = self._frame.date.min().strftime('%Y-%m-%d')
        last = self._frame.date.max().strftime('%Y-%m-%d')
        physical_ledger(self._frame, self._distributions, self._split, first, last, 1000)
        self._indexed = self._frame.set_index('date')
        self.clock = tuple(self._indexed.index)

    def dates(self, entry, horizon):
        start = calendar_date(entry)
        if type(horizon) is not int or horizon <= 0:
            raise WindowUnavailable('Horizon must be a positive integer')
        if start not in self.clock:
            raise WindowUnavailable('Entry is not a covered market session')
        index = self.clock.index(start) + horizon - 1
        if index >= len(self.clock):
            raise WindowUnavailable('Insufficient covered market sessions')
        return self.clock[index].strftime('%Y-%m-%d')

    def window(self, entry, exit_, symbol='0050'):
        if symbol != '0050':
            raise WindowUnavailable('Only verified 0050 accounting is supported')
        start, end = calendar_date(entry), calendar_date(exit_)
        if start > end:
            raise WindowUnavailable('Exit precedes entry')
        if start not in self._indexed.index or end not in self._indexed.index:
            raise WindowUnavailable('Boundary outside covered market sessions')
        if not np.isfinite(self._indexed.loc[start, 'open']) or not np.isfinite(self._indexed.loc[end, 'close']):
            raise WindowUnavailable('Unquoted endpoint; endpoint is not shifted')
        daily, claims, initial = physical_ledger(self._frame, self._distributions, self._split, entry, exit_, 1000)
        last = daily.iloc[-1]
        return dict(symbol=symbol, entry=entry, exit=exit_,
                    market_sessions=len(self._indexed.loc[start:end]),
                    initial_units=1000, initial_quote_cost=initial,
                    ending_units=float(last.physical_units), raw_entry_open=float(self._indexed.loc[start, 'open']),
                    raw_exit_close=float(last.raw_close), settled_cash=float(last.settled_cash),
                    dividend_receivable=float(last.dividend_receivable), gross_wealth=float(last.gross_wealth),
                    gross_change=float(last.gross_nav - 1),
                    stale_market_sessions=int(daily.stale_market_quote.sum()),
                    entitlements=[r for r in claims if r['gross_claim'] > 0],
                    accounting_basis='fresh-purchase gross raw-close mark; cash not reinvested',
                    hypothetical_quote_acquisition=True, actual_fill_verified=False,
                    historical_pit_verified=False, profit_edge_proven=False,
                    source_verified=self._provenance is not None,
                    provenance=dict(self._provenance) if self._provenance is not None else None)


def direct_account(frame, distributions, split, entry, exit_):
    """Independent terminal formula; no PhysicalBook, ledger or window method calls."""
    start, end = pd.Timestamp(entry), pd.Timestamp(exit_)
    indexed = frame.copy()
    indexed['date'] = pd.to_datetime(indexed.date)
    indexed = indexed.set_index('date')
    D = lambda value: Decimal(str(value))
    split_day = pd.Timestamp(split['date'])
    shares = D(1000) * (D(split['ratio']) if start < split_day <= end else 1)
    cash, pending, rights = D(0), D(0), []
    for event in distributions:
        ex, pay = pd.Timestamp(event['ex_date']), pd.Timestamp(event['payment_date'])
        if start < ex <= end:
            entitled = D(1000) * (D(split['ratio']) if start < split_day <= ex else 1)
            value = entitled * D(event['cash_per_unit'])
            if pay <= end:
                cash += value
            else:
                pending += value
            rights.append(dict(**event, entitled_units=float(entitled), gross_claim=float(value)))
    initial = D(1000) * D(indexed.loc[start, 'open'])
    wealth = shares * D(indexed.loc[end, 'close']) + cash + pending
    return dict(initial_quote_cost=float(initial), ending_units=float(shares),
                settled_cash=float(cash), dividend_receivable=float(pending),
                gross_wealth=float(wealth), gross_change=float(wealth / initial - 1), entitlements=rights)
