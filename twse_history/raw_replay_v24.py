"""Replay saved monthly stock signals at raw opens; quarantine incomplete rights.

After a held unresolved action, orders are conditional diagnostics under an
explicit no-op assumption. Only pre-blocker shares/cash are a valid ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from .physical_ledger_v9 import PhysicalBook
from .corporate_claims_v24 import BonusClaim, ClaimBook, FxCashClaim

METHODS = ("equal", "momentum_60_skip5", "logistic", "hist_gradient_boosting")
COMMISSION, SLIPPAGE, SELL_TAX = .001425, .001, .003


def load_selections(scores, counts):
    """Use saved prior-day signals, preserving their source row order for ties."""
    selections, rows = {}, []
    assert len(counts) == 12 and counts.fill_date.is_unique
    for c in counts.itertuples():
        day = scores[scores.date.eq(c.signal_date)].copy()
        # v5 explicitly quarantined this anomalous 2024-12-31 signal.
        day = day[~(day.symbol.eq("2429") & day.date.le(pd.Timestamp("2024-12-31")))]
        if len(day) != c.candidates or day.symbol.duplicated().any() or c.signal_date >= c.fill_date:
            raise ValueError("Saved monthly candidate counts or dates disagree")
        if c.top_k != max(1, int(np.ceil(len(day) * .1))):
            raise ValueError("Invalid top decile size")
        selections[c.fill_date] = {}
        for method in METHODS:
            chosen = day if method == "equal" else day.nlargest(c.top_k, "mom60_skip5" if method == "momentum_60_skip5" else method)
            symbols = chosen.symbol.tolist()
            if "0050" in symbols or len(symbols) != len(set(symbols)):
                raise ValueError("Invalid stock selection")
            selections[c.fill_date][method] = symbols
            for rank, row in enumerate(chosen.itertuples(), 1):
                rows.append(dict(signal_date=c.signal_date, fill_date=c.fill_date,
                                 method=method, rank=rank, symbol=row.symbol,
                                 score=np.nan if method == "equal" else getattr(row, "mom60_skip5" if method == "momentum_60_skip5" else method)))
    return selections, pd.DataFrame(rows)


def tradable(q, previous_close, side):
    """OHLC limit proxy; reference-price and actual queue are not known."""
    if q is None or not all(np.isfinite(q[k]) for k in ("open", "high", "low", "volume")):
        return False, "missing_quote"
    if q["open"] <= 0 or q["volume"] <= 0:
        return False, "zero_volume_or_price"
    if np.isfinite(previous_close) and previous_close > 0 and abs(q["high"] - q["low"]) < 1e-8:
        if side == "buy" and q["open"] >= previous_close * 1.095:
            return False, "possible_limit_up"
        if side == "sell" and q["open"] <= previous_close * .905:
            return False, "possible_limit_down"
    return True, "ohlc_proxy_only"


def replay(prices, actions, evidence, delistings, selections, paid_rights=None, withholding=None, par_changes=None,
           combined=None, fx_rates=None, conversions=None, bonus_only=None):
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.date.dt.year.eq(2025), "date"].unique()))
    if len(calendar) != 243:
        raise ValueError("Expected 243 holdout trading days")
    quote = {(r.date, r.symbol): r._asdict() for r in prices[prices.date.dt.year.eq(2025)].itertuples(index=False)}
    action = {(r.effective_date, r.symbol): r._asdict() for r in actions[actions.effective_date.dt.year.eq(2025)].itertuples(index=False)}
    dividends = {(r.ex_date, r.symbol): r._asdict() for r in evidence.itertuples(index=False)}
    paid_rights = {} if paid_rights is None else {(r.ex_date, r.symbol): r._asdict() for r in paid_rights.itertuples(index=False)}
    withholding = {} if withholding is None else {(r.ex_date, r.symbol): r._asdict() for r in withholding.itertuples(index=False)}
    par_changes = {} if par_changes is None else {(r.effective_date, r.symbol): r._asdict() for r in par_changes.itertuples(index=False)}
    combined = {} if combined is None else {(r.ex_date, r.symbol): r._asdict() for r in combined.itertuples(index=False)}
    bonus_only = {} if bonus_only is None else {(r.ex_date, r.symbol): r._asdict() for r in bonus_only.itertuples(index=False)}
    fx_rates = {} if fx_rates is None else dict(zip(fx_rates.available_from_date, fx_rates.ntd_per_usd))
    conversions = {} if conversions is None else {r.conversion_date: r._asdict()
                                               for r in conversions.itertuples(index=False)}
    delisted = {(r.delisted_date, r.symbol) for r in delistings.itertuples(index=False)
                if pd.notna(r.delisted_date) and r.delisted_date.year == 2025}
    previous = {}
    for sym, g in prices.sort_values("date").groupby("symbol"):
        previous[sym] = g.set_index("date").close.ffill().shift().to_dict()
    books = {method: PhysicalBook() for method in METHODS}
    claims = {method: ClaimBook() for method in METHODS}
    marks = {method: {} for method in METHODS}
    first_blocker = {method: None for method in METHODS}
    trades, events, days = [], [], []
    for date in calendar:
        for method in METHODS:
            book, mark, claim_book = books[method], marks[method], claims[method]
            delivered = claim_book.deliver_bonus(book, date)
            for claim in delivered:
                events.append(dict(date=date, method=method, symbol=claim.symbol,
                                   event_id=f'bonus_delivery:{claim.symbol}:{date.date()}', event_type='bonus_delivery',
                                   event_subtype='free_stock', opening_shares=claim.shares,
                                   status='bonus_shares_delivered_tradeable', cash_receivable=np.nan,
                                   cash_receivable_gross=np.nan, withholding_assumed=np.nan,
                                   waived_subscription_shares=np.nan, issue_price_at_ex=np.nan, ratio_status='',
                                   bonus_receivable_shares=0., bonus_delivery_date=date, fx_rate_used=np.nan,
                                   cash_receivable_usd=np.nan, source_url='',
                                   valid_before_unresolved=first_blocker[method] is None))
            conversion = conversions.get(date)
            if conversion is not None and book.shares[conversion['predecessor']] > 1e-12:
                old, new = conversion['predecessor'], conversion['successor']
                if (pd.Timestamp(conversion['announcement_date']) >= date or
                        pd.Timestamp(conversion['successor_listing_date']) != date or
                        pd.Timestamp(conversion['last_predecessor_trade_date']) >= date or
                        conversion['policy'] != 'fractional_research_one_to_one' or
                        float(conversion['successor_per_predecessor']) != 1. or
                        (date, old) not in delisted or (date, new) not in quote or
                        not conversion['conversion_source_url'] or not conversion['listing_source_url']):
                    raise ValueError('Invalid predecessor conversion evidence')
                old_qty = book.shares[old]
                book.shares[old] = 0.
                book.shares[new] += old_qty
                mark.pop(old, None)
                events.append(dict(date=date, method=method, symbol=old,
                                   event_id=conversion['event_id'], event_type='share_conversion',
                                   event_subtype=f'{old}_to_{new}', opening_shares=old_qty,
                                   status='verified_successor_delivered_tradeable', cash_receivable=np.nan,
                                   cash_receivable_gross=np.nan, withholding_assumed=np.nan,
                                   waived_subscription_shares=np.nan, issue_price_at_ex=np.nan, ratio_status='',
                                   bonus_receivable_shares=np.nan, bonus_delivery_date=pd.NaT,
                                   fx_rate_used=np.nan, cash_receivable_usd=np.nan,
                                   source_url=conversion['listing_source_url'],
                                   valid_before_unresolved=first_blocker[method] is None))
            held = [(sym, qty) for sym, qty in book.shares.items() if qty > 1e-12]
            for sym, qty in held:
                event = action.get((date, sym))
                if event is None:
                    continue
                event_type, subtype = event["event_type"], event["event_subtype"]
                status, amount = "unresolved", np.nan
                gross_amount, assumed_withheld = np.nan, np.nan
                waived_shares, price_at_ex, ratio_status = np.nan, np.nan, ""
                bonus_shares, bonus_delivery, fx_used, amount_usd = np.nan, pd.NaT, np.nan, np.nan
                if event_type == 'exrights' and subtype == '權息' and (date, sym) in combined:
                    proof = combined[(date, sym)]
                    if (proof['event_id'] != event['event_id'] or
                            pd.Timestamp(proof['pre_ex_announcement_date']) >= date or
                            pd.Timestamp(proof['cash_payment_date']) <= date or
                            pd.Timestamp(proof['delivery_date']) <= date or
                            pd.Timestamp(proof['delivery_announcement_date']) > pd.Timestamp(proof['delivery_date']) or
                            not proof['issuer_terms_url'] or not proof['delivery_notice_url']):
                        raise ValueError('Invalid combined distribution evidence')
                    bonus_ratio = float(proof['stock_dividend_ntd_per_share']) / float(proof['par_value'])
                    if not 0 < bonus_ratio < 1:
                        raise ValueError('Invalid free stock ratio')
                    bonus_shares = qty * bonus_ratio
                    bonus_delivery = pd.Timestamp(proof['delivery_date'])
                    claim_book.add_bonus(BonusClaim(sym, bonus_shares, bonus_delivery))
                    if sym == '3665':
                        if (not pd.isna(proof['cash_twd_per_share']) or
                                not proof['issuer_rate_revision_url'] or not proof['final_fx_notice_url'] or
                                pd.Timestamp(proof['final_fx_announcement_date']) >= pd.Timestamp(proof['final_fx_effective_date']) or
                                pd.Timestamp(proof['final_fx_effective_date']) >= pd.Timestamp(proof['cash_payment_date'])):
                            raise ValueError('Invalid foreign currency evidence')
                        usd_per_share = float(proof['usd_total']) / float(proof['shares_entitled'])
                        fx_claim = FxCashClaim(sym, qty, usd_per_share,
                                                pd.Timestamp(proof['cash_payment_date']),
                                                float(proof['final_twd_per_share']),
                                                pd.Timestamp(proof['final_fx_effective_date']))
                        claim_book.add_fx(fx_claim)
                        amount_usd = qty * usd_per_share
                        fx_used = claim_book.fx_rate(fx_claim, date, fx_rates)
                        amount = gross_amount = amount_usd * fx_used
                        status = 'foreign_cash_fx_estimated_bonus_pending'
                    else:
                        if not float(proof['cash_twd_per_share']) > 0:
                            raise ValueError('Invalid combined cash rate')
                        amount = book.ex_cash(sym, date, pd.Timestamp(proof['cash_payment_date']),
                                              float(proof['cash_twd_per_share']))
                        gross_amount = amount
                        status = 'cash_receivable_bonus_pending'
                elif event_type == 'exrights' and subtype == '權' and (date, sym) in bonus_only:
                    proof = bonus_only[(date, sym)]
                    if (proof['event_id'] != event['event_id'] or
                            pd.Timestamp(proof['pre_ex_announcement_date']) >= date or
                            pd.Timestamp(proof['delivery_date']) <= date or
                            pd.Timestamp(proof['delivery_announcement_date']) > pd.Timestamp(proof['delivery_date']) or
                            not proof['issuer_terms_url'] or not proof['delivery_notice_url']):
                        raise ValueError('Invalid free bonus evidence')
                    ratio = float(proof['stock_dividend_ntd_per_share']) / float(proof['par_value'])
                    if not 0 < ratio < 1:
                        raise ValueError('Invalid free bonus ratio')
                    bonus_shares = qty * ratio
                    bonus_delivery = pd.Timestamp(proof['delivery_date'])
                    claim_book.add_bonus(BonusClaim(sym, bonus_shares, bonus_delivery))
                    status = 'bonus_only_receivable_pending'
                elif event_type == "exrights" and subtype == "息" and (date, sym) in dividends:
                    proof = dividends[(date, sym)]
                    if pd.Timestamp(proof["announced_date"]) <= date and pd.Timestamp(proof["payment_date"]) >= date and float(proof["cash_per_share"]) > 0:
                        rate = float(proof["cash_per_share"])
                        gross_amount = qty * rate
                        special = proof["evidence_status"] == "issuer_gross_foreign_withholding_scenario"
                        policy = withholding.get((date, sym))
                        if special != (policy is not None):
                            raise ValueError("Special foreign dividend requires matching withholding policy")
                        tax_rate = 0.
                        if special:
                            if (policy["event_id"] != event["event_id"] or
                                    policy["policy"] != "max_rate_stress_case" or
                                    abs(float(policy["gross_cash_per_share"]) - rate) > 1e-10 or
                                    not 0 <= float(policy["withholding_rate_assumed"]) < 1 or
                                    pd.Timestamp(policy["announcement_date"]) > date or
                                    pd.Timestamp(policy["payment_date"]) != pd.Timestamp(proof["payment_date"]) or
                                    not policy["issuer_notice_url"]):
                                raise ValueError("Invalid foreign withholding policy")
                            tax_rate = float(policy["withholding_rate_assumed"])
                        assumed_withheld = gross_amount * tax_rate
                        amount = book.ex_cash(sym, date, pd.Timestamp(proof["payment_date"]), rate * (1 - tax_rate))
                        status = "cash_receivable_withholding_assumed" if special else "cash_receivable_recorded"
                elif event_type == "exrights" and subtype == "權" and (date, sym) in paid_rights:
                    proof = paid_rights[(date, sym)]
                    if (proof["event_id"] != event["event_id"] or proof["policy"] != "waive_paid_subscription" or
                            proof["ratio_status"] not in {"issuer_announced", "issuer_provisional", "issuer_aggregate_only"} or
                            pd.Timestamp(proof["price_announcement_date"]) > date or
                            not float(proof["issue_price_at_ex"]) > 0 or
                            pd.Timestamp(proof["payment_start"]) < date or
                            pd.Timestamp(proof["payment_end"]) < pd.Timestamp(proof["payment_start"]) or
                            not proof["initial_issuer_notice_url"] or not proof["price_notice_url"]):
                        raise ValueError("Invalid paid subscription evidence")
                    ratio = float(proof["paid_subscription_shares_per_1000"])
                    if proof["ratio_status"] == "issuer_aggregate_only":
                        if np.isfinite(ratio):
                            raise ValueError("Aggregate-only rights cannot claim an individual ratio")
                    elif not np.isfinite(ratio) or not 0 < ratio < 1000:
                        raise ValueError("Invalid paid subscription ratio")
                    else:
                        waived_shares = qty * ratio / 1000
                    price_at_ex = float(proof["issue_price_at_ex"])
                    ratio_status = proof["ratio_status"]
                    status = ("paid_subscription_waived_ratio_unverified" if
                              ratio_status == "issuer_aggregate_only" else "paid_subscription_waived")
                elif event_type == "split" and np.isfinite(event["confirmed_share_ratio"]) and event["confirmed_share_ratio"] > 0:
                    book.split(sym, float(event["confirmed_share_ratio"]))
                    status = "verified_split_ratio_applied_fractional_assumption"
                elif event_type == "par_change" and (date, sym) in par_changes:
                    proof = par_changes[(date, sym)]
                    ratio = float(proof["new_shares_per_old"])
                    if (proof["event_id"] != event["event_id"] or
                            proof["policy"] != "fractional_research_share_ratio" or
                            not float(proof["old_par_value"]) > 0 or
                            not float(proof["new_par_value"]) > 0 or
                            abs(ratio - float(proof["old_par_value"]) / float(proof["new_par_value"])) > 1e-10 or
                            pd.Timestamp(proof["announcement_date"]) >= date or
                            pd.Timestamp(proof["delivery_date"]) != date or
                            pd.Timestamp(proof["resume_trade_date"]) != date or
                            not proof["issuer_notice_url"]):
                        raise ValueError("Invalid par-value exchange evidence")
                    book.split(sym, ratio)
                    status = "verified_par_change_fractional_research_shares"
                if status == "unresolved" and first_blocker[method] is None:
                    first_blocker[method] = dict(date=date, event_id=event["event_id"], symbol=sym)
                events.append(dict(date=date, method=method, symbol=sym,
                                   event_id=event["event_id"], event_type=event_type,
                                   event_subtype=subtype, opening_shares=qty,
                                   status=status, cash_receivable=amount,
                                   cash_receivable_gross=gross_amount,
                                   withholding_assumed=assumed_withheld,
                                   waived_subscription_shares=waived_shares,
                                   issue_price_at_ex=price_at_ex,
                                   ratio_status=ratio_status,
                                   bonus_receivable_shares=bonus_shares, bonus_delivery_date=bonus_delivery,
                                   fx_rate_used=fx_used, cash_receivable_usd=amount_usd,
                                   source_url=event["source_url"],
                                   valid_before_unresolved=first_blocker[method] is None))
            # All known payments are on market days; payable cash enters before the open.
            paid = book.pay(date) + claim_book.settle_fx(book, date)
            for sym, qty in [(s, q) for s, q in book.shares.items() if q > 1e-12]:
                q = quote.get((date, sym))
                if q and np.isfinite(q["open"]) and q["open"] > 0:
                    mark[sym] = float(q["open"])
            target = selections.get(date, {}).get(method)
            if target is not None:
                missing = [sym for sym, qty in book.shares.items() if qty > 1e-12 and sym not in mark]
                if missing:
                    raise ValueError(f"Unmarked held position: {missing}")
                # Internal continuation after blocker ignores unresolved action.
                equity_open = (book.cash + book.receivable + claim_book.fx_value(date, fx_rates) +
                               sum(qty * mark[s] for s, qty in book.shares.items() if qty > 1e-12) +
                               claim_book.bonus_value({c.symbol: float(quote[(date, c.symbol)]['open'])
                                                       if (date, c.symbol) in quote and np.isfinite(quote[(date, c.symbol)]['open'])
                                                       else mark[c.symbol] for c in claim_book.bonus}))
                desired = equity_open / len(target)
                target_set = set(target)
                for sym, qty in [(s, q) for s, q in book.shares.items() if q > 1e-12]:
                    q = quote.get((date, sym))
                    raw_open = float(q["open"]) if q and np.isfinite(q["open"]) else np.nan
                    excess = qty * raw_open - (desired if sym in target_set else 0.)
                    if not np.isfinite(excess) or excess <= 1e-12:
                        continue
                    can, reason = tradable(q, previous.get(sym, {}).get(date, np.nan), "sell")
                    n = min(qty, excess / raw_open) if can else 0.
                    before = book.cash
                    if n > 0:
                        book.sell(sym, n, raw_open, commission=COMMISSION, slippage=SLIPPAGE, sell_tax=SELL_TAX)
                    trades.append(dict(date=date, method=method, symbol=sym, side="sell",
                                       status="filled" if n else "blocked", reason=reason,
                                       requested_raw_notional=excess, raw_open=raw_open,
                                       shares=n, gross_raw_notional=n * raw_open if n else 0.,
                                       cash_delta=book.cash-before,
                                       valid_before_unresolved=first_blocker[method] is None))
                for sym in target:
                    q = quote.get((date, sym))
                    raw_open = float(q["open"]) if q and np.isfinite(q["open"]) else np.nan
                    held_qty = book.shares[sym]
                    gap = desired - held_qty * raw_open if np.isfinite(raw_open) else desired
                    if gap <= 1e-12:
                        continue
                    can, reason = tradable(q, previous.get(sym, {}).get(date, np.nan), "buy")
                    # v5 allocation uses a fixed target per selected name and sell-first order.
                    spend = min(gap * (1 + SLIPPAGE + COMMISSION), book.cash) if can else 0.
                    n = spend / (raw_open * (1 + SLIPPAGE) * (1 + COMMISSION)) if spend > 1e-12 else 0.
                    before = book.cash
                    if n > 0:
                        book.buy(sym, n, raw_open, commission=COMMISSION, slippage=SLIPPAGE)
                        mark[sym] = raw_open
                    trades.append(dict(date=date, method=method, symbol=sym, side="buy",
                                       status="filled" if n else "blocked", reason=reason if not can else "cash_exhausted" if not n else reason,
                                       requested_raw_notional=gap, raw_open=raw_open,
                                       shares=n, gross_raw_notional=n * raw_open if n else 0.,
                                       cash_delta=book.cash-before,
                                       valid_before_unresolved=first_blocker[method] is None))
            # Delisted predecessor consideration is not booked without complete
            # delivery, odd-lot, cash and special-share valuation rules.
            for sym, qty in [(s, q) for s, q in book.shares.items() if q > 1e-12 and (date, s) in delisted]:
                if first_blocker[method] is None:
                    first_blocker[method] = dict(date=date, event_id=f"delisting:{sym}:{date.date()}", symbol=sym)
                events.append(dict(date=date, method=method, symbol=sym,
                                   event_id=f"delisting:{sym}:{date.date()}", event_type="delisting",
                                   event_subtype="consideration_unresolved", opening_shares=qty,
                                   status="unresolved", cash_receivable=np.nan, source_url="",
                                   cash_receivable_gross=np.nan, withholding_assumed=np.nan,
                                   waived_subscription_shares=np.nan, issue_price_at_ex=np.nan,
                                   ratio_status="",
                                   bonus_receivable_shares=np.nan, bonus_delivery_date=pd.NaT,
                                   fx_rate_used=np.nan, cash_receivable_usd=np.nan,
                                   valid_before_unresolved=False))
            stale = 0
            for sym, qty in [(s, q) for s, q in book.shares.items() if q > 1e-12]:
                q = quote.get((date, sym))
                if q and np.isfinite(q["close"]) and q["close"] > 0:
                    mark[sym] = float(q["close"])
                else:
                    stale += 1
            complete = first_blocker[method] is None
            bonus_missing = any(c.symbol not in mark for c in claim_book.bonus)
            bonus_value = claim_book.bonus_value(mark) if not bonus_missing else np.nan
            foreign_receivable = claim_book.fx_value(date, fx_rates)
            # No post-blocker amount, share, or NAV is published as a physical ledger.
            days.append(dict(date=date, method=method, accounting_complete=complete,
                             active_positions=sum(q > 1e-12 for q in book.shares.values()),
                             stale_positions=stale, cash_received_today=paid if complete else np.nan,
                             cash_if_complete=book.cash if complete else np.nan,
                             receivable_if_complete=book.receivable + foreign_receivable if complete else np.nan,
                             foreign_receivable_if_complete=foreign_receivable if complete else np.nan,
                             bonus_shares_pending_if_complete=sum(c.shares for c in claim_book.bonus) if complete else np.nan,
                             bonus_value_if_complete=bonus_value if complete else np.nan,
                             nav_if_complete=(book.cash + book.receivable + foreign_receivable + bonus_value +
                                              sum(q * mark[s] for s, q in book.shares.items() if q > 1e-12))
                             if complete and not stale and not bonus_missing else np.nan))
            if book.cash < -1e-9 or book.receivable < -1e-9 or any(q < -1e-9 for q in book.shares.values()):
                raise ValueError("Share/cash conservation violation")
    return pd.DataFrame(trades), pd.DataFrame(events), pd.DataFrame(days), first_blocker


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="twse_history")
    ap.add_argument("--output", default="twse_history/output_research_v24")
    args = ap.parse_args()
    root, out = Path(args.root), Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"prices": root / "output_multiyear/prices_adjusted_2024_2025.csv.gz",
             "actions": root / "output_multiyear/corporate_actions_2024_2025.csv",
             "evidence": root / "dividend_evidence_v24.csv",
             "delistings": root / "output_multiyear/delistings_2024_2025.csv",
             "scores": root / "output_research_v5/monthly_signal_scores.csv.gz",
             "counts": root / "output_research_v5/monthly_candidate_counts.csv",
             "paid_rights": root / "paid_rights_evidence_v24.csv"}
    paths["withholding"] = root / "dividend_withholding_policy_v24.csv"
    paths["par_changes"] = root / "par_change_evidence_v24.csv"
    paths['combined'] = root / 'combined_distribution_evidence_v24.csv'
    paths['fx_rates'] = root / 'fx_usdtwd_cbc_v24.csv'
    paths['conversions'] = root / 'share_conversion_evidence_v24.csv'
    paths['bonus_only'] = root / 'bonus_only_evidence_v24.csv'
    read = lambda key, **kw: pd.read_csv(paths[key], dtype={"symbol": str}, **kw)
    prices = read("prices", parse_dates=["date"])
    actions = read("actions", parse_dates=["effective_date"])
    evidence = read("evidence", parse_dates=["ex_date", "payment_date", "announced_date"])
    delistings = read("delistings", parse_dates=["delisted_date"])
    scores = read("scores", parse_dates=["date"])
    counts = pd.read_csv(paths["counts"], parse_dates=["signal_date", "fill_date"])
    paid_rights = read("paid_rights", parse_dates=["ex_date", "price_announcement_date", "revised_announcement_date", "payment_start", "payment_end"])
    withholding = read("withholding", parse_dates=["ex_date", "payment_date", "announcement_date"])
    par_changes = read("par_changes", parse_dates=["effective_date", "announcement_date", "delivery_date", "resume_trade_date"])
    combined = read('combined', parse_dates=['ex_date', 'cash_payment_date', 'final_fx_announcement_date',
                                             'final_fx_effective_date', 'delivery_date',
                                             'delivery_announcement_date', 'pre_ex_announcement_date'])
    fx_rates = read('fx_rates', parse_dates=['date', 'available_from_date'])
    conversions = pd.read_csv(paths['conversions'], dtype={'predecessor': str, 'successor': str},
                              parse_dates=['conversion_date', 'announcement_date', 'successor_listing_date',
                                           'last_predecessor_trade_date'])
    bonus_only = read('bonus_only', parse_dates=['ex_date', 'pre_ex_announcement_date', 'delivery_date',
                                                 'delivery_announcement_date'])
    if paid_rights.event_id.duplicated().any() or paid_rights[["ex_date", "symbol"]].duplicated().any():
        raise ValueError("Duplicate paid rights evidence")
    if evidence[["ex_date", "symbol"]].duplicated().any():
        raise ValueError("Duplicate cash dividend evidence")
    if withholding.event_id.duplicated().any() or withholding[["ex_date", "symbol"]].duplicated().any():
        raise ValueError("Duplicate foreign withholding policy")
    if par_changes.event_id.duplicated().any() or par_changes[["effective_date", "symbol"]].duplicated().any():
        raise ValueError("Duplicate par-value exchange evidence")
    if combined.event_id.duplicated().any() or combined[['ex_date', 'symbol']].duplicated().any():
        raise ValueError('Duplicate combined distribution evidence')
    if fx_rates.date.duplicated().any() or fx_rates.available_from_date.duplicated().any() or (
            fx_rates.available_from_date <= fx_rates.date).any() or not fx_rates.ntd_per_usd.gt(0).all():
        raise ValueError('Invalid point-in-time FX series')
    if conversions.event_id.duplicated().any() or conversions.conversion_date.duplicated().any():
        raise ValueError('Duplicate predecessor conversion evidence')
    if bonus_only.event_id.duplicated().any() or bonus_only[['ex_date', 'symbol']].duplicated().any():
        raise ValueError('Duplicate free bonus evidence')
    selections, selected = load_selections(scores, counts)
    trades, events, days, blockers = replay(prices, actions, evidence, delistings, selections,
                                            paid_rights, withholding, par_changes, combined, fx_rates, conversions,
                                            bonus_only)
    for name, frame in (("selected_symbols", selected), ("raw_order_diagnostics", trades),
                        ("held_action_audit", events), ("daily_accounting_status", days)):
        frame.to_csv(out / f"{name}.csv", index=False)
    summary = dict(monthly_rebalances=len(selections), selected_rows=len(selected),
                   market_days=int(days.date.nunique()),
                   stock_strategy_nav_produced=False,
                   first_unresolved={m: {k: str(v.date()) if isinstance(v, pd.Timestamp) else v
                                         for k, v in b.items()} if b else None for m, b in blockers.items()},
                   valid_filled_orders=int((trades.status.eq("filled") & trades.valid_before_unresolved).sum()),
                   conditional_filled_orders=int((trades.status.eq("filled") & ~trades.valid_before_unresolved).sum()),
                   held_events_by_status=events.status.value_counts().to_dict(),
                   days_accounting_complete=days.groupby("method").accounting_complete.sum().astype(int).to_dict(),
                   assumptions=["Fractional raw shares and 0.1425% commission, 0.1% slippage per side, 0.3% stock sell tax.",
                                "AMAX-KY 2025-07-16 dividend uses a 30% maximum foreign withholding stress case on gross cash; the net receivable settles on 2025-10-13, without fractional cash rounding or a claim about actual investor tax.",
                                "6919 par change exchanges each pre-change share for ten new shares on 2025-07-21 in the fractional research account.",
                                "3665 USD cash claim uses prior FX business-day CBC interbank close until issuer's after-hours 2025-08-12 conversion notice, effective 2025-08-13; 2025-08-22 payout is locked to the actual TWD per share without fractional cash rounding.",
                                "Free bonus shares are marked as claims at quoted underlying raw prices from ex-date, not tradeable physical shares until published delivery/trading dates: 2025-08-22 (3665), 2025-08-29 (2836 and 1519), 2025-09-26 (2250), 2025-11-21 (2364).",
                                "2250 issuer specifies cash in lieu and per-account truncation for fractional share allotments; the normalized fractional research ledger does not reproduce actual brokerage rounding and settlement.",
                                "6288 predecessor converts 1:1 to tradeable 3717 on 2025-08-15; no cash consideration is imputed and predecessor quotes remain stale during suspension.",
                                "OHLC price-limit heuristic only; no exchange auction or order queue.",
                                "After first unresolved held action, subsequent orders are hypothetical no-op-action diagnostics only, never a valid NAV or physical share claim.",
                                "Known dividend evidence includes MOPS republishes that still require original announcement audit.",
                                "Issuer aggregate-only paid rights are explicitly waived without imputing an individual subscription ratio or any right sale proceeds."],
                   input_sha256={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("input_sha256", "assumptions")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
