"""Two timing assumptions for three unresolved stock-months, never a portfolio NAV.

The account is normalized to one original share. Fractional stock claims and
opening fills are analytical assumptions. Corporate actions attach on ex-date;
scheduled payments/deliveries occur before the open on their assumed day.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deliverables"
CONFIG = OUT / "hypothetical_rights_assumptions_2026_v72.json"


def run_one(method: str, symbol: str, row: pd.Series, event: dict,
            timing: str) -> tuple[list[dict], dict]:
    entry = row.entry_date
    exit_day = row.exit_observation_date
    ex = event["ex_date"]
    dates = event["hypothetical_dates"][timing]
    payment = dates["cash_payment"]
    delivery = dates["free_share_delivery"]
    assert entry < ex < exit_day and ex <= payment
    assert delivery is None or ex <= delivery
    cash_claim = float(event["cash_per_original"])
    free_claim = float(event["free_shares_per_original"])
    assert 0 <= cash_claim and 0 <= free_claim
    assert (delivery is None) == (free_claim == 0)

    # One share is purchased at the entry open with an external contribution;
    # no dividend or pending share may fund a subsequent purchase.
    spendable_cash = 0.0
    cash_receivable = 0.0
    saleable_shares = 1.0
    pending_free_shares = 0.0
    sold_shares = 0.0
    trace = []
    keys = sorted(set([entry, ex, exit_day, payment] + ([delivery] if delivery else [])))
    exit_state = None
    for date in keys:
        phase = []
        if date == entry:
            phase.append("buy_one_original_at_open")
        if date == ex:
            cash_receivable += cash_claim
            pending_free_shares += free_claim
            phase.append("ex_entitle;waive_paid_subscription")
        if date == payment:
            spendable_cash += cash_receivable
            cash_receivable = 0.0
            phase.append("hypothetical_cash_payment")
        if date == delivery:
            saleable_shares += pending_free_shares
            pending_free_shares = 0.0
            phase.append("hypothetical_free_share_delivery")
        if date == exit_day:
            sold_shares = saleable_shares
            spendable_cash += sold_shares * float(row.exit_raw_open)
            saleable_shares = 0.0
            phase.append("sell_only_saleable_at_exit_open")
        assert abs(cash_receivable + (cash_claim if date >= payment else 0)
                   - (cash_claim if date >= ex else 0)) < 1e-8
        if date >= ex:
            assert abs(sold_shares + saleable_shares + pending_free_shares
                       - 1.0 - free_claim) < 1e-8
        rec = {"timing": timing, "method": method, "symbol": symbol,
               "date": date, "phase": ";".join(phase),
               "spendable_cash_per_original": spendable_cash,
               "cash_receivable_per_original": cash_receivable,
               "saleable_shares_per_original": saleable_shares,
               "pending_free_shares_per_original": pending_free_shares,
               "cumulative_sold_shares_per_original": sold_shares}
        trace.append(rec)
        if date == exit_day:
            exit_state = dict(rec)
    assert exit_state is not None
    mark = (exit_state["spendable_cash_per_original"]
            + exit_state["cash_receivable_per_original"]
            + (exit_state["saleable_shares_per_original"]
               + exit_state["pending_free_shares_per_original"])
            * float(row.exit_raw_open))
    summary = {"timing": timing, "method": method, "symbol": symbol,
               "entry_date": entry, "ex_date": ex, "exit_date": exit_day,
               "assumed_cash_payment": payment, "assumed_free_share_delivery": delivery,
               "entry_open": float(row.entry_raw_open), "exit_open": float(row.exit_raw_open),
               "assumed_cash_entitlement": cash_claim,
               "assumed_free_shares_entitlement": free_claim,
               "assumed_paid_subscription_election": "waive_all_without_compensation",
               "exit_spendable_cash": exit_state["spendable_cash_per_original"],
               "exit_cash_receivable": exit_state["cash_receivable_per_original"],
               "exit_pending_free_shares": exit_state["pending_free_shares_per_original"],
               "exit_cumulative_sold_shares": exit_state["cumulative_sold_shares_per_original"],
               "exit_economic_mark_with_claims": mark,
               "hypothetical_gross_mark_return": mark / float(row.entry_raw_open) - 1,
               "post_exit_saleable_shares_not_sold": saleable_shares,
               "post_exit_spendable_cash_without_later_sale": spendable_cash,
               "portfolio_nav_or_realized_return": False}
    return trace, summary


def main() -> None:
    config = json.loads(CONFIG.read_text())
    events = config["events"]
    assert config["paid_subscription_election"] == "waive_all_paid_rights_without_compensation"
    assert set(events) == {"7610", "2464"}
    assert abs(events["7610"]["free_shares_per_original"] -
               events["7610"]["free_shares_total"] /
               (events["7610"]["cash_total"] / events["7610"]["cash_per_original"])) < 1e-12
    base = pd.read_csv(OUT / "pure_rights_waiver_proxy_2026_v69.csv", dtype={"symbol": str})
    inventory = pd.read_csv(OUT / "unresolved_monthly_rights_inventory_2026_v67.csv",
                            dtype={"symbol": str})
    pending = inventory[inventory.symbol.isin(events)].copy()
    assert len(pending) == 3
    traces, summaries = [], []
    for x in pending.itertuples():
        match = base[(base.method.eq(x.method)) & (base.symbol.eq(x.symbol)) &
                     (base.entry_date.eq(x.entry_date)) &
                     (base.exit_observation_date.eq(x.exit_observation_date))]
        assert len(match) == 1
        row = match.iloc[0]
        assert not row.gross_cash_entitlement_proxy_available and row.gross_cash_per_original_share == 0
        assert x.event_date == events[x.symbol]["ex_date"]
        for timing in ("early", "late"):
            trace, summary = run_one(x.method, x.symbol, row, events[x.symbol], timing)
            traces += trace
            summaries.append(summary)
    ledger = pd.DataFrame(traces)
    detail = pd.DataFrame(summaries)
    assert len(detail) == 6 and detail.groupby("timing").size().eq(3).all()
    # Timing only moves claims between account buckets; it never creates value.
    marks = detail.pivot(index=["method", "symbol", "entry_date"], columns="timing",
                         values="exit_economic_mark_with_claims")
    assert (marks.early - marks.late).abs().max() < 1e-9
    assert (detail[detail.symbol.eq("7610") & detail.timing.eq("late")]
            .exit_pending_free_shares > 0).all()
    assert (detail[detail.timing.eq("early")].exit_pending_free_shares == 0).all()
    ledger.to_csv(OUT / "hypothetical_rights_account_events_2026_v72.csv", index=False)
    detail.to_csv(OUT / "hypothetical_rights_exit_states_2026_v72.csv", index=False, na_rep="")

    # A separate illustrative full-universe mark. It is not the realized v69
    # subset, a funded strategy, or a walk-forward market NAV.
    scenarios = []
    for timing in ("early", "late"):
        frame = base.copy()
        frame["scenario"] = timing
        frame["valuation_kind"] = "v69_observable_gross_proxy"
        for x in detail[detail.timing.eq(timing)].itertuples():
            m = (frame.method.eq(x.method) & frame.symbol.eq(x.symbol) &
                 frame.entry_date.eq(x.entry_date) & frame.exit_observation_date.eq(x.exit_date))
            assert m.sum() == 1
            i = frame.index[m][0]
            frame.at[i, "gross_price_plus_cash_return"] = x.hypothetical_gross_mark_return
            frame.at[i, "gross_cash_entitlement_proxy_available"] = True
            frame.at[i, "valuation_kind"] = "hypothetical_claim_mark_not_realized"
        assert frame.groupby("method").gross_cash_entitlement_proxy_available.sum().eq(616).all()
        scenarios.append(frame)
    full = pd.concat(scenarios, ignore_index=True)
    full.to_csv(OUT / "hypothetical_full_universe_marks_2026_v72.csv", index=False)
    monthly = full.groupby(["scenario", "method", "entry_date"], sort=True).agg(
        selected=("symbol", "size"),
        hypothetical_claim_marks=("valuation_kind", lambda x: (x == "hypothetical_claim_mark_not_realized").sum()),
        mean_hypothetical_gross_mark=("gross_price_plus_cash_return", "mean"),
    ).reset_index()
    assert monthly.groupby(["scenario", "method"]).size().eq(9).all()
    monthly.to_csv(OUT / "hypothetical_full_universe_by_month_2026_v72.csv", index=False)
    summary = monthly.groupby(["scenario", "method"], sort=True).agg(
        months=("entry_date", "size"), selected=("selected", "sum"),
        hypothetical_claim_marks=("hypothetical_claim_marks", "sum"),
        mean_of_nine_monthly_marks=("mean_hypothetical_gross_mark", "mean"),
    ).reset_index()
    summary.to_csv(OUT / "hypothetical_full_universe_summary_2026_v72.csv", index=False)
    print(detail[["timing", "method", "symbol", "exit_spendable_cash",
                  "exit_cash_receivable", "exit_pending_free_shares",
                  "hypothetical_gross_mark_return", "post_exit_saleable_shares_not_sold"]].to_string(index=False))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
