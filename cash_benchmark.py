"""Gross physical ETF accounting; quoted acquisition, not executable performance."""
from decimal import Decimal
from html.parser import HTMLParser
import re

import numpy as np
import pandas as pd

from twse_history.physical_ledger_v9 import PhysicalBook


def csv12_product_matches(a, b, result):
    """Bound multiplication error from the frozen CSV writer's %.12g precision."""
    def half_step(value):
        return .5 * 10. ** (np.floor(np.log10(abs(value))) - 11) if value else 0.
    budget = abs(b) * half_step(a) + abs(a) * half_step(b) + half_step(result)
    return bool(abs(a * b - result) <= budget + 1e-14 * max(1, abs(result)))


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_distributions(body, year):
    html = body.decode('utf-8', errors='strict')
    parser = Tables()
    parser.feed(html)
    header = ['ETF Code', 'ETF Name', 'Ex-dividend Date', 'Dividend Payment Date',
              'Cash Dividend (NT$/Per beneficiary unit)', 'Year Announced']
    if parser.rows.count(header) != 1:
        raise ValueError('Missing/ambiguous dividend table schema')
    rows = []
    for row in parser.rows:
        if not row or row[0] != '0050':
            continue
        if len(row) != 6 or row[1] != 'Yuanta/P-shares Taiwan Top 50 ETF':
            raise ValueError('Wrong security or dividend table width')
        ex, pay = [pd.to_datetime(v, format='%Y/%m/%d', errors='raise') for v in row[2:4]]
        amount = float(row[4])
        if ex.year != year or int(row[5]) != year or pay < ex or not np.isfinite(amount) or amount <= 0:
            raise ValueError('Invalid dividend year/date/amount')
        rows.append(dict(ex_date=str(ex.date()), payment_date=str(pay.date()), cash_per_unit=amount))
    if len(rows) != 2 or len({r['ex_date'] for r in rows}) != len(rows):
        raise ValueError('Incomplete/duplicate full-year distributions')
    return sorted(rows, key=lambda r: r['ex_date'])


def parse_split(body):
    # Narrow fixed-event parser: require explicit ratio and date evidence, not price inference.
    parser = Tables()
    parser.feed(body.decode('utf-8', errors='strict'))
    text = re.sub(r'\s+', '', ''.join(''.join(r) for r in parser.rows))
    if '證券代碼0050' not in text or '分割比率（分割後受益權單位數/分割前受益權單位數）：4' not in text:
        raise ValueError('Missing explicit 0050 split ratio')
    if '(6)新受益憑證上市(櫃)買賣日：114年6月18日' not in text or '停止交易期間：114年6月11日至114年6月17日' not in text:
        raise ValueError('Split resumption/halt date differs')
    return dict(date='2025-06-18', ratio=4,
                halt_dates=pd.date_range('2025-06-11', '2025-06-17').strftime('%Y-%m-%d').tolist())


def validate_inputs(frame, distributions, split, start, end, units):
    p = frame.copy()
    p['date'] = pd.to_datetime(p.date)
    if p.date.duplicated().any() or not p.date.is_monotonic_increasing or p.empty:
        raise ValueError('Invalid market clock')
    if not np.isfinite(units) or units <= 0 or pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError('Invalid initial units or accounting dates')
    if not np.isfinite(split['ratio']) or split['ratio'] <= 0:
        raise ValueError('Invalid split ratio')
    ex_dates = set()
    for r in distributions:
        ex, pay = pd.Timestamp(r['ex_date']), pd.Timestamp(r['payment_date'])
        amount = r['cash_per_unit']
        if ex in ex_dates or ex == pd.Timestamp(split['date']) or pay < ex or not np.isfinite(amount) or amount <= 0:
            raise ValueError('Ambiguous/invalid entitlement')
        ex_dates.add(ex)
    relevant = p.date.between(start, end)
    p = p[relevant].set_index('date')
    if p.empty or pd.Timestamp(start) not in p.index or pd.Timestamp(end) not in p.index:
        raise ValueError('Missing boundary market session')
    present = p['close'].notna()
    cols = ['open', 'close', 'adj_open', 'adj_close', 'causal_factor']
    missing_cells = p[cols].isna()
    if (missing_cells.any(axis=1) & ~missing_cells.all(axis=1)).any():
        raise ValueError('Partially missing quote')
    values = p.loc[present, cols].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Invalid raw/adjusted quote')
    for raw, adjusted in [('open', 'adj_open'), ('close', 'adj_close')]:
        if not all(csv12_product_matches(a, b, value) for a, b, value in zip(p.loc[present, raw], p.loc[present, 'causal_factor'], p.loc[present, adjusted])):
            raise ValueError('Frozen causal factor identity differs')
    missing = set(p.index[~present].strftime('%Y-%m-%d'))
    if not missing.issubset(set(split['halt_dates'])):
        raise ValueError('Unknown missing market quote')
    if not present.iloc[0] or not present.iloc[-1]:
        raise ValueError('Missing boundary valuation')
    for date in [pd.Timestamp(split['date']), *ex_dates]:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end) and (date not in p.index or not present.loc[date]):
            raise ValueError('Corporate action without market quote')
    return p


def physical_ledger(frame, distributions, split, start, end, units):
    p = validate_inputs(frame, distributions, split, start, end, units)
    first_open = float(p.iloc[0].open)
    initial = units * first_open
    book = PhysicalBook(initial)
    events = {pd.Timestamp(r['ex_date']): r for r in distributions}
    rows, claims = [], []
    last_close, last_adjusted, quote_date = None, None, None
    for date in pd.date_range(start, end):
        if date == pd.Timestamp(split['date']):
            book.split('0050', split['ratio'])
        if date in events:
            event = events[date]
            before_open_units = book.shares['0050']
            amount = book.ex_cash('0050', date, pd.Timestamp(event['payment_date']), event['cash_per_unit'])
            claims.append(dict(**event, entitled_units=before_open_units, gross_claim=amount))
        paid = float(book.pay(date))
        if date == pd.Timestamp(start):
            book.buy('0050', units, first_open, commission=0, slippage=0)
        has_quote = date in p.index and pd.notna(p.loc[date, 'close'])
        if has_quote:
            last_close = float(p.loc[date, 'close'])
            last_adjusted = float(p.loc[date, 'adj_close'])
            quote_date = date
        nav = book.nav({'0050': last_close})
        rows.append(dict(date=str(date.date()), market_session=date in p.index,
                         stale_market_quote=date in p.index and not has_quote,
                         last_quote_date=str(quote_date.date()), raw_close=last_close,
                         physical_units=book.shares['0050'], settled_cash=book.cash,
                         dividend_receivable=book.receivable, paid_today=paid, gross_wealth=nav,
                         gross_nav=nav / initial,
                         frozen_adjusted_quote_ratio=last_adjusted / float(p.iloc[0].adj_open)))
    return pd.DataFrame(rows), claims, initial


def audit_ledger(frame, distributions, split, start, end, units, daily, claims):
    """Independent direct entitlement sums with Decimal, not PhysicalBook replay."""
    p = validate_inputs(frame, distributions, split, start, end, units)
    if daily.date.tolist() != pd.date_range(start, end).strftime('%Y-%m-%d').tolist():
        raise ValueError('Incomplete calendar-day accounting')
    D = lambda v: Decimal(str(v))
    initial = D(units) * D(p.iloc[0].open)
    entitlement = []
    for r in distributions:
        ex = pd.Timestamp(r['ex_date'])
        if not pd.Timestamp(start) <= ex <= pd.Timestamp(end):
            continue
        held = D(units) if ex > pd.Timestamp(start) else D(0)
        if pd.Timestamp(start) < pd.Timestamp(split['date']) <= ex:
            held *= D(split['ratio'])
        entitlement.append(dict(**r, entitled_units=float(held), gross_claim=float(held * D(r['cash_per_unit']))))
    if claims != entitlement:
        raise ValueError('Independent entitlement table differs')
    worst, money_error, nav_error, quoted = 0., 0., 0., None
    for row in daily.itertuples(index=False):
        date = pd.Timestamp(row.date)
        held = D(units) * (D(split['ratio']) if pd.Timestamp(start) < pd.Timestamp(split['date']) <= date else D(1))
        cash = sum((D(r['gross_claim']) for r in entitlement if pd.Timestamp(r['payment_date']) <= date), D(0))
        receivable = sum((D(r['gross_claim']) for r in entitlement if pd.Timestamp(r['ex_date']) <= date < pd.Timestamp(r['payment_date'])), D(0))
        paid = sum((D(r['gross_claim']) for r in entitlement if pd.Timestamp(r['payment_date']) == date), D(0))
        if date in p.index and pd.notna(p.loc[date, 'close']):
            quoted = date
        raw_close = D(p.loc[quoted, 'close'])
        expected = dict(physical_units=held, raw_close=raw_close, settled_cash=cash,
                        dividend_receivable=receivable, paid_today=paid,
                        gross_wealth=held * raw_close + cash + receivable,
                        gross_nav=(held * raw_close + cash + receivable) / initial,
                        frozen_adjusted_quote_ratio=D(p.loc[quoted, 'adj_close']) / D(p.iloc[0].adj_open))
        if row.last_quote_date != str(quoted.date()) or bool(row.market_session) != (date in p.index) or bool(row.stale_market_quote) != (date in p.index and date != quoted):
            raise ValueError('Independent quote clock differs')
        for key, value in expected.items():
            error = abs(float(value) - getattr(row, key))
            if not np.isfinite(error) or error > 1e-8:
                raise ValueError('Independent daily account differs: ' + key)
            worst = max(worst, error)
            if key in ('settled_cash', 'dividend_receivable', 'paid_today', 'gross_wealth'):
                money_error = max(money_error, error)
            if key in ('gross_nav', 'frozen_adjusted_quote_ratio'):
                nav_error = max(nav_error, error)
    return dict(status='passed', calendar_days=len(daily), claims=len(claims), max_field_absolute_error=worst,
                max_money_error_twd=money_error, max_nav_ratio_error=nav_error,
                method='Decimal direct held-units times per-unit amount; independent paid-to-date/receivable sums')
