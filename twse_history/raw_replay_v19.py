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


def replay(prices, actions, evidence, delistings, selections, paid_rights=None):
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.date.dt.year.eq(2025), "date"].unique()))
    if len(calendar) != 243:
        raise ValueError("Expected 243 holdout trading days")
    quote = {(r.date, r.symbol): r._asdict() for r in prices[prices.date.dt.year.eq(2025)].itertuples(index=False)}
    action = {(r.effective_date, r.symbol): r._asdict() for r in actions[actions.effective_date.dt.year.eq(2025)].itertuples(index=False)}
    dividends = {(r.ex_date, r.symbol): r._asdict() for r in evidence.itertuples(index=False)}
    paid_rights = {} if paid_rights is None else {(r.ex_date, r.symbol): r._asdict() for r in paid_rights.itertuples(index=False)}
    delisted = {(r.delisted_date, r.symbol) for r in delistings.itertuples(index=False)
                if pd.notna(r.delisted_date) and r.delisted_date.year == 2025}
    previous = {}
    for sym, g in prices.sort_values("date").groupby("symbol"):
        previous[sym] = g.set_index("date").close.ffill().shift().to_dict()
    books = {method: PhysicalBook() for method in METHODS}
    marks = {method: {} for method in METHODS}
    first_blocker = {method: None for method in METHODS}
    trades, events, days = [], [], []
    for date in calendar:
        for method in METHODS:
            book, mark = books[method], marks[method]
            held = [(sym, qty) for sym, qty in book.shares.items() if qty > 1e-12]
            for sym, qty in held:
                event = action.get((date, sym))
                if event is None:
                    continue
                event_type, subtype = event["event_type"], event["event_subtype"]
                status, amount = "unresolved", np.nan
                waived_shares, price_at_ex, ratio_status = np.nan, np.nan, ""
                if event_type == "exrights" and subtype == "息" and (date, sym) in dividends:
                    proof = dividends[(date, sym)]
                    if pd.Timestamp(proof["announced_date"]) <= date and pd.Timestamp(proof["payment_date"]) >= date and float(proof["cash_per_share"]) > 0:
                        amount = book.ex_cash(sym, date, pd.Timestamp(proof["payment_date"]), float(proof["cash_per_share"]))
                        status = "cash_receivable_recorded"
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
                if status == "unresolved" and first_blocker[method] is None:
                    first_blocker[method] = dict(date=date, event_id=event["event_id"], symbol=sym)
                events.append(dict(date=date, method=method, symbol=sym,
                                   event_id=event["event_id"], event_type=event_type,
                                   event_subtype=subtype, opening_shares=qty,
                                   status=status, cash_receivable=amount,
                                   waived_subscription_shares=waived_shares,
                                   issue_price_at_ex=price_at_ex,
                                   ratio_status=ratio_status,
                                   source_url=event["source_url"],
                                   valid_before_unresolved=first_blocker[method] is None))
            # All known payments are on market days; payable cash enters before the open.
            paid = book.pay(date)
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
                equity_open = book.cash + book.receivable + sum(qty * mark[s] for s, qty in book.shares.items() if qty > 1e-12)
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
                                   waived_subscription_shares=np.nan, issue_price_at_ex=np.nan,
                                   ratio_status="",
                                   valid_before_unresolved=False))
            stale = 0
            for sym, qty in [(s, q) for s, q in book.shares.items() if q > 1e-12]:
                q = quote.get((date, sym))
                if q and np.isfinite(q["close"]) and q["close"] > 0:
                    mark[sym] = float(q["close"])
                else:
                    stale += 1
            complete = first_blocker[method] is None
            # No post-blocker amount, share, or NAV is published as a physical ledger.
            days.append(dict(date=date, method=method, accounting_complete=complete,
                             active_positions=sum(q > 1e-12 for q in book.shares.values()),
                             stale_positions=stale, cash_received_today=paid if complete else np.nan,
                             cash_if_complete=book.cash if complete else np.nan,
                             receivable_if_complete=book.receivable if complete else np.nan,
                             nav_if_complete=(book.cash + book.receivable + sum(q * mark[s] for s, q in book.shares.items() if q > 1e-12)) if complete and not stale else np.nan))
            if book.cash < -1e-9 or book.receivable < -1e-9 or any(q < -1e-9 for q in book.shares.values()):
                raise ValueError("Share/cash conservation violation")
    return pd.DataFrame(trades), pd.DataFrame(events), pd.DataFrame(days), first_blocker


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="twse_history")
    ap.add_argument("--output", default="twse_history/output_research_v19")
    args = ap.parse_args()
    root, out = Path(args.root), Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"prices": root / "output_multiyear/prices_adjusted_2024_2025.csv.gz",
             "actions": root / "output_multiyear/corporate_actions_2024_2025.csv",
             "evidence": root / "dividend_evidence_v19.csv",
             "delistings": root / "output_multiyear/delistings_2024_2025.csv",
             "scores": root / "output_research_v5/monthly_signal_scores.csv.gz",
             "counts": root / "output_research_v5/monthly_candidate_counts.csv",
             "paid_rights": root / "paid_rights_evidence_v19.csv"}
    read = lambda key, **kw: pd.read_csv(paths[key], dtype={"symbol": str}, **kw)
    prices = read("prices", parse_dates=["date"])
    actions = read("actions", parse_dates=["effective_date"])
    evidence = read("evidence", parse_dates=["ex_date", "payment_date", "announced_date"])
    delistings = read("delistings", parse_dates=["delisted_date"])
    scores = read("scores", parse_dates=["date"])
    counts = pd.read_csv(paths["counts"], parse_dates=["signal_date", "fill_date"])
    paid_rights = read("paid_rights", parse_dates=["ex_date", "price_announcement_date", "revised_announcement_date", "payment_start", "payment_end"])
    if paid_rights.event_id.duplicated().any() or paid_rights[["ex_date", "symbol"]].duplicated().any():
        raise ValueError("Duplicate paid rights evidence")
    if evidence[["ex_date", "symbol"]].duplicated().any():
        raise ValueError("Duplicate cash dividend evidence")
    selections, selected = load_selections(scores, counts)
    trades, events, days, blockers = replay(prices, actions, evidence, delistings, selections, paid_rights)
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
                                "OHLC price-limit heuristic only; no exchange auction or order queue.",
                                "After first unresolved held action, subsequent orders are hypothetical no-op-action diagnostics only, never a valid NAV or physical share claim.",
                                "Known dividend evidence includes MOPS republishes that still require original announcement audit.",
                                "Issuer aggregate-only paid rights are explicitly waived without imputing an individual subscription ratio or any right sale proceeds."],
                   input_sha256={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("input_sha256", "assumptions")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
