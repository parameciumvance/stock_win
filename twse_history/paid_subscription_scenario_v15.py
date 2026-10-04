"""Isolated, integer-share paid-rights scenario; never feeds the stock NAV.

An entitlement is based on shares held before the ex-date. Cash is reserved
only on an elected date within the published payment window. New shares stay
pending until a separately verified delivery date is supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR


@dataclass(frozen=True)
class SubscriptionTerms:
    event_id: str
    ex_date: date
    shares_per_1000: Decimal
    price: Decimal
    payment_start: date
    payment_end: date
    delivery_date: date | None = None


@dataclass(frozen=True)
class SubscriptionResult:
    eligible_whole_shares: int
    subscribed_whole_shares: int
    forfeited_whole_shares: int
    cash_reserved: Decimal
    cash_after_payment: Decimal
    pending_shares: int
    delivery_date: date | None
    status: str


def subscribe(terms: SubscriptionTerms, held_whole_shares: int,
              available_cash: Decimal, payment_date: date) -> SubscriptionResult:
    """Evaluate an elected payment; no fractional rights or extra purchases.

    A broker's odd-lot aggregation and actual allocation can differ. The
    returned shares are not available for trading before verified delivery.
    """
    if not terms.event_id or held_whole_shares < 0 or not isinstance(held_whole_shares, int):
        raise ValueError("Invalid pre-ex-date holdings")
    if terms.price <= 0 or terms.shares_per_1000 <= 0 or available_cash < 0:
        raise ValueError("Invalid terms or cash")
    if not (terms.ex_date < terms.payment_start <= payment_date <= terms.payment_end):
        raise ValueError("Payment outside announced window")
    if terms.delivery_date is not None and terms.delivery_date <= payment_date:
        raise ValueError("Delivery must follow payment")
    eligible = int((Decimal(held_whole_shares) * terms.shares_per_1000 / 1000)
                   .to_integral_value(rounding=ROUND_FLOOR))
    affordable = int((available_cash / terms.price).to_integral_value(rounding=ROUND_FLOOR))
    subscribed = min(eligible, affordable)
    reserved = terms.price * subscribed
    return SubscriptionResult(
        eligible_whole_shares=eligible, subscribed_whole_shares=subscribed,
        forfeited_whole_shares=eligible - subscribed,
        cash_reserved=reserved, cash_after_payment=available_cash - reserved,
        pending_shares=subscribed, delivery_date=terms.delivery_date,
        status="awaiting_verified_delivery" if terms.delivery_date is None else "delivery_scheduled")
