"""Raw-share cash/receivable ledger; benchmark parity, no stock NAV claim.

Orders must supply actual raw-price share quantities. A v5 adjusted-price
notional alone is not an authorized physical order or a stock dividend claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from .research_cash_v6 import ETF_DISTRIBUTIONS, SPLIT_DATE, SPLIT_RATIO


class PhysicalBook:
    def __init__(self, cash=1.):
        self.cash = float(cash)
        self.shares = defaultdict(float)
        self.receivable = 0.
        self.pending = []

    def split(self, symbol, ratio):
        if ratio <= 0:
            raise ValueError("Invalid split ratio")
        self.shares[symbol] *= ratio

    def ex_cash(self, symbol, ex_date, payment_date, cash_per_share):
        if payment_date < ex_date or cash_per_share <= 0:
            raise ValueError("Invalid dividend terms")
        amount = self.shares[symbol] * cash_per_share
        self.receivable += amount
        self.pending.append((payment_date, amount))
        return amount

    def pay(self, date):
        due = sum(amount for day, amount in self.pending if day == date)
        self.pending = [(day, amount) for day, amount in self.pending if day != date]
        self.receivable -= due
        self.cash += due
        return due

    def buy(self, symbol, shares, raw_open, *, commission=.001425, slippage=.001):
        if shares <= 0 or raw_open <= 0 or min(commission, slippage) < 0:
            raise ValueError("Invalid buy")
        spend = shares * raw_open * (1 + slippage) * (1 + commission)
        if spend > self.cash + 1e-10:
            raise ValueError("Insufficient cash")
        self.cash -= spend
        self.shares[symbol] += shares

    def sell(self, symbol, shares, raw_open, *, commission=.001425,
             slippage=.001, sell_tax=.003):
        if shares <= 0 or raw_open <= 0 or min(commission, slippage, sell_tax) < 0:
            raise ValueError("Invalid sell")
        if shares > self.shares[symbol] + 1e-10:
            raise ValueError("Cannot sell more physical shares than held")
        self.shares[symbol] -= shares
        self.cash += shares * raw_open * (1 - slippage) * (1 - commission - sell_tax)

    def nav(self, raw_closes):
        if any(symbol not in raw_closes or not np.isfinite(raw_closes[symbol])
               for symbol, shares in self.shares.items() if shares > 1e-12):
            raise ValueError("Missing raw close for held position")
        return self.cash + self.receivable + sum(
            shares * raw_closes[symbol] for symbol, shares in self.shares.items())


def reconcile_0050(prices, existing):
    """Independently reproduce the verified v6 ETF daily physical cash ledger."""
    p = prices[prices.symbol.eq("0050") & prices.date.dt.year.eq(2025)].set_index("date")
    reference = existing.set_index("date").sort_index()
    first = reference.index[0]
    if first not in p.index or not np.isfinite(p.loc[first, "open"]):
        raise ValueError("Missing initial raw opening quote")
    book = PhysicalBook()
    initial_shares = 1 / (float(p.loc[first, "open"]) * 1.001 * 1.001425)
    rows = []
    last_close = np.nan
    for date in reference.index:
        # Rights attach before the day's opening trades. Payment precedes use of
        # cash at the open; none of this benchmark's distributions is reinvested.
        if date == SPLIT_DATE:
            book.split("0050", SPLIT_RATIO)
        if date in ETF_DISTRIBUTIONS:
            per_share, payment = ETF_DISTRIBUTIONS[date]
            book.ex_cash("0050", date, payment, per_share)
        paid = book.pay(date)
        if date == first:
            book.buy("0050", initial_shares, float(p.loc[date, "open"]))
        q = p.loc[date] if date in p.index else None
        if q is not None and np.isfinite(q["close"]):
            last_close = float(q["close"])
        val = book.nav({"0050": last_close})
        rows.append(dict(date=date, method="0050_physical_cash",
                         physical_units=book.shares["0050"], last_raw_close=last_close,
                         uninvested_cash=book.cash, dividend_receivable=book.receivable,
                         cash_received_today=paid, nav=val, stale_quote=q is None))
    result = pd.DataFrame(rows).set_index("date")
    for field in ("physical_units", "last_raw_close", "uninvested_cash",
                  "dividend_receivable", "nav"):
        if not np.allclose(result[field], reference[field], atol=1e-10, rtol=0):
            raise ValueError(f"0050 v6 physical ledger mismatch: {field}")
    if not result.stale_quote.equals(reference.stale_quote):
        raise ValueError("0050 stale-quote mismatch")
    return result.reset_index(), float(np.max(abs(result.nav - reference.nav)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prices", default="twse_history/output_multiyear/prices_adjusted_2024_2025.csv.gz")
    p.add_argument("--v6-ledger", default="twse_history/output_research_v6/etf_0050_daily_physical_nav.csv")
    p.add_argument("--output", default="twse_history/output_research_v9")
    args = p.parse_args()
    prices_path, v6_path, out = map(Path, (args.prices, args.v6_ledger, args.output))
    out.mkdir(parents=True, exist_ok=True)
    prices = pd.read_csv(prices_path, dtype={"symbol": str}, parse_dates=["date"])
    v6 = pd.read_csv(v6_path, parse_dates=["date"])
    daily, maximum = reconcile_0050(prices, v6)
    daily.to_csv(out / "etf_0050_physical_reconciliation.csv", index=False)
    result = dict(market_days=len(daily), final_nav=float(daily.nav.iloc[-1]),
                  max_absolute_daily_nav_difference=maximum,
                  stock_portfolio_nav_produced=False,
                  input_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in (prices_path, v6_path)})
    (out / "physical_ledger_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
