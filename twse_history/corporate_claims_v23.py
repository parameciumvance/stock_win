"""Unsettled foreign cash and bonus shares for a normalized research account.

The FX price visible at a stock opening/close is the previous FX business
day's close. The issuer's actual conversion is usable only on the day after
its after-hours announcement. No cash or stock can be traded before delivery.
"""
from dataclasses import dataclass


@dataclass
class FxCashClaim:
    symbol: str
    shares_at_ex: float
    usd_per_share: float
    payment_date: object
    final_twd_per_share: float
    final_effective_date: object


@dataclass
class BonusClaim:
    symbol: str
    shares: float
    delivery_date: object


class ClaimBook:
    def __init__(self):
        self.fx_cash = []
        self.bonus = []

    def add_fx(self, claim):
        if claim.usd_per_share <= 0 or claim.final_twd_per_share <= 0 or claim.shares_at_ex <= 0:
            raise ValueError('Invalid USD cash claim')
        self.fx_cash.append(claim)

    def add_bonus(self, claim):
        if claim.shares <= 0:
            raise ValueError('Invalid bonus claim')
        self.bonus.append(claim)

    def fx_rate(self, claim, date, available_rates):
        if date >= claim.final_effective_date:
            return claim.final_twd_per_share / claim.usd_per_share
        if date not in available_rates:
            raise ValueError(f'Missing point-in-time FX close for {date}')
        return available_rates[date]

    def fx_value(self, date, available_rates):
        return sum(c.shares_at_ex * c.usd_per_share * self.fx_rate(c, date, available_rates)
                   for c in self.fx_cash)

    def settle_fx(self, book, date):
        due = [c for c in self.fx_cash if c.payment_date == date]
        if any(date < c.final_effective_date for c in due):
            raise ValueError('Unannounced FX settlement')
        paid = sum(c.shares_at_ex * c.final_twd_per_share for c in due)
        book.cash += paid
        self.fx_cash = [c for c in self.fx_cash if c.payment_date != date]
        return paid

    def deliver_bonus(self, book, date):
        due = [c for c in self.bonus if c.delivery_date == date]
        for claim in due:
            book.shares[claim.symbol] += claim.shares
        self.bonus = [c for c in self.bonus if c.delivery_date != date]
        return due

    def bonus_value(self, prices):
        return sum(c.shares * prices[c.symbol] for c in self.bonus)
