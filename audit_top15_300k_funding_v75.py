"""Funding commitments and next-day quote checks for unverified Top-15 orders.

This deliberately halts portfolio accounting at the missing-fill boundary.
No ordinary-market open is inserted as an intraday odd-lot execution price.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from audit_top15_300k_selections_v74 import (CAPITAL, FEE, MIN_FEE,
                                             OUT, PER_NAME, PRICE_BUFFER,
                                             SOURCE, commission)


def main() -> None:
    selection = pd.read_csv(OUT / "top15_300k_selections_2026_v74.csv", dtype={"symbol": str})
    orders = pd.read_csv(OUT / "top15_300k_order_intents_2026_v74.csv", dtype={"symbol": str})
    price = pd.read_csv(SOURCE / "prices_adjusted_2023_2026.csv.gz",
                        usecols=["date", "symbol", "open", "volume"],
                        dtype={"symbol": str})
    quote = price.rename(columns={"date": "planned_trade_date", "open": "regular_open_observed",
                                  "volume": "regular_day_volume"})
    buy = orders[orders.side.eq("buy")].merge(
        quote, on=["planned_trade_date", "symbol"], how="left", validate="many_to_one")
    assert buy.regular_open_observed.gt(0).all()
    assert buy.regular_day_volume.gt(0).all()
    buy["reference_price_with_buffer"] = buy.sizing_reference_close * (1 + PRICE_BUFFER)
    buy["reference_order_notional"] = buy.quantity_if_filled * buy.reference_price_with_buffer
    buy["reference_broker_fee"] = buy.reference_order_notional.map(commission)
    buy["reserved_if_filled"] = buy.reference_order_notional + buy.reference_broker_fee
    buy["regular_open_order_notional_diagnostic"] = buy.quantity_if_filled * buy.regular_open_observed
    buy["regular_open_order_fee_diagnostic"] = buy.regular_open_order_notional_diagnostic.map(commission)
    buy["regular_open_order_total_diagnostic"] = (buy.regular_open_order_notional_diagnostic
                                                    + buy.regular_open_order_fee_diagnostic)
    assert buy.venue.isin(["regular", "intraday_odd_lot"]).all()
    # For split regular/odd orders the candidate budget applies to their sum.
    budget = buy.groupby(["method", "planned_trade_date", "symbol"], sort=False).agg(
        reserved_if_filled=("reserved_if_filled", "sum"),
        regular_open_cost_diagnostic=("regular_open_order_total_diagnostic", "sum"),
        hypothetical_order_count=("venue", "size"),
    ).reset_index()
    assert budget.reserved_if_filled.le(PER_NAME + 1e-8).all()
    budget["regular_open_over_target_diagnostic"] = budget.regular_open_cost_diagnostic > PER_NAME
    buy.to_csv(OUT / "top15_300k_buy_ticket_checks_2026_v75.csv", index=False)
    budget.to_csv(OUT / "top15_300k_buy_budget_checks_2026_v75.csv", index=False)

    month = selection.groupby(["method", "planned_trade_date"], sort=True).agg(
        selected=("symbol", "size"), new=("planned_action", lambda x: (x == "buy_candidate").sum()),
        continuing=("planned_action", lambda x: (x == "hold_no_rebalance").sum()),
    ).reset_index()
    commitments = budget.groupby(["method", "planned_trade_date"], sort=True).agg(
        reference_buy_commitments=("reserved_if_filled", "sum"),
        order_tickets=("hypothetical_order_count", "sum"),
        post_observation_regular_open_over_target=("regular_open_over_target_diagnostic", "sum"),
    ).reset_index()
    month = month.merge(commitments, on=["method", "planned_trade_date"], validate="one_to_one")
    sell = orders[orders.side.eq("sell")].groupby(["method", "planned_trade_date"]).size()
    month["intended_sell_names"] = [int(sell.get((x.method, x.planned_trade_date), 0))
                                    for x in month.itertuples()]
    month["initial_uncommitted_cash_if_all_initial_orders_fill_at_buffered_reference"] = np.where(
        month.planned_trade_date.eq("2026-01-02"), CAPITAL - month.reference_buy_commitments, np.nan)
    assert month.loc[month.planned_trade_date.eq("2026-01-02"),
                     "initial_uncommitted_cash_if_all_initial_orders_fill_at_buffered_reference"].ge(15000).all()
    month["shortfall_vs_static_15000_initial_reserve"] = np.maximum(
        0, month.reference_buy_commitments - 15000)
    month["cash_and_holdings_after_unverified_fills"] = "unknown"
    month["actual_portfolio_nav"] = np.nan
    month["next_step_gate"] = np.where(month.planned_trade_date.eq("2026-01-02"),
                                       "initial_orders_unverified",
                                       "saleable_shares_and_sell_proceeds_unverified")
    month.to_csv(OUT / "top15_300k_funding_gates_2026_v75.csv", index=False, na_rep="")
    print(month.to_string(index=False))
    print("buy tickets", buy.groupby("venue").size().to_dict())
    print("regular-open per-ticket diagnostic over target", int(budget.regular_open_over_target_diagnostic.sum()),
          "out of", len(budget))


if __name__ == "__main__":
    main()
