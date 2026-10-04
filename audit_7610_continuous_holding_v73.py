"""Reconcile uninterrupted 7610 selections; no month-end fictional round trips."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deliverables"


def main() -> None:
    event = json.loads((OUT / "hypothetical_rights_assumptions_2026_v72.json").read_text())["events"]["7610"]
    selections = pd.read_csv(OUT / "monthly_selections_2026_v62.csv", dtype={"symbol": str})
    orders = pd.read_csv(OUT / "monthly_proposed_orders_2026_v63.csv", dtype={"symbol": str})
    proxy = pd.read_csv(OUT / "pure_rights_waiver_proxy_2026_v69.csv", dtype={"symbol": str})
    observed_dates = ["2026-04-01", "2026-05-04", "2026-06-01", "2026-07-01",
                      "2026-08-03", "2026-09-01", "2026-10-01"]
    expected_selection_dates = observed_dates[:-1]
    results = []
    for method in ("logistic", "mom60_skip5"):
        sel = selections[(selections.method.eq(method)) & selections.symbol.eq("7610")]
        assert sel.fill_date.tolist() == expected_selection_dates
        assert sel.new_since_previous_month.tolist() == [True] + [False] * 5
        ords = orders[(orders.method.eq(method)) & orders.symbol.eq("7610")]
        assert len(ords) == 1 and ords.iloc[0].side == "buy" and ords.iloc[0].fill_date == "2026-04-01"
        sub = proxy[(proxy.method.eq(method)) & proxy.symbol.eq("7610")]
        opens = {x.entry_date: float(x.entry_raw_open) for x in sub.itertuples()}
        assert set(observed_dates[:-1]) == set(opens)
        opens["2026-10-01"] = float(sub[sub.entry_date.eq("2026-09-01")].iloc[0].exit_raw_open)
        assert opens["2026-04-01"] == 356.5
        cash_claim = float(event["cash_per_original"])
        free_claim = float(event["free_shares_per_original"])
        for timing in ("early", "late"):
            due = event["hypothetical_dates"][timing]
            payment, delivery = due["cash_payment"], due["free_share_delivery"]
            cash, receivable, saleable, pending = 0.0, 0.0, 1.0, 0.0
            dates = sorted(set(observed_dates + [event["ex_date"], payment, delivery]))
            for day in dates:
                phases = []
                if day == "2026-04-01":
                    phases.append("assumed_one_original_share_bought_at_open")
                if day == event["ex_date"]:
                    receivable += cash_claim
                    pending += free_claim
                    phases.append("ex_entitle;waive_paid_subscription")
                if day == payment:
                    cash += receivable
                    receivable = 0.0
                    phases.append("hypothetical_payment")
                if day == delivery:
                    saleable += pending
                    pending = 0.0
                    phases.append("hypothetical_delivery")
                if day in observed_dates[1:-1]:
                    phases.append("continued_selection_no_order")
                if day == "2026-10-01":
                    phases.append("quote_only_no_october_selection_or_sale_assumed")
                assert abs(saleable + pending - (1 + free_claim if day >= event["ex_date"] else 1)) < 1e-10
                assert abs(cash + receivable - (cash_claim if day >= event["ex_date"] else 0)) < 1e-10
                quote = opens.get(day)
                mark = (cash + receivable + (saleable + pending) * quote) if quote is not None else None
                results.append({"method": method, "timing": timing, "date": day,
                                "phase": ";".join(phases), "open_quote": quote,
                                "spendable_cash": cash, "cash_receivable": receivable,
                                "saleable_shares": saleable, "pending_free_shares": pending,
                                "assumed_gross_economic_mark": mark,
                                "sold_shares": 0.0, "is_portfolio_nav": False})
    frame = pd.DataFrame(results)
    frame.to_csv(OUT / "continuous_7610_account_2026_v73.csv", index=False, na_rep="")
    monthly = frame[frame.date.isin(observed_dates)].copy()
    assert len(monthly) == 28
    pivot = monthly.pivot(index=["method", "date"], columns="timing", values="assumed_gross_economic_mark")
    assert (pivot.early - pivot.late).abs().max() < 1e-9
    aug = monthly[monthly.date.eq("2026-08-03")]
    assert (aug[aug.timing.eq("late")].saleable_shares == 1).all()
    assert (aug[aug.timing.eq("early")].saleable_shares > 1).all()
    assert (monthly[monthly.date.eq("2026-10-01")].sold_shares == 0).all()
    monthly.to_csv(OUT / "continuous_7610_monthly_snapshots_2026_v73.csv", index=False)
    print(monthly[(monthly.method.eq("logistic")) &
                  (monthly.date.isin(["2026-08-03", "2026-09-01", "2026-10-01"]))][
                      ["timing", "date", "spendable_cash", "cash_receivable",
                       "saleable_shares", "pending_free_shares", "assumed_gross_economic_mark"]].to_string(index=False))


if __name__ == "__main__":
    main()
