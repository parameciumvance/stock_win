"""Build adopted Top-15 monthly research orders from the frozen surge score.

This produces an as-of order-sizing plan, not odd-lot fills, NAV, calibrated
probabilities, target prices, or a newly independent holdout evaluation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from twse_history.research_v5 import FEATURES, feature_panel, training_frame


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deliverables"
SOURCE = ROOT / "twse_history/output_multiyear_2023_2026_asof_20261002"
METHODS = ("logistic", "mom60_skip5")
TOP_N = 15
CAPITAL = 300_000
RESERVE = 0.05
PER_NAME = CAPITAL * (1 - RESERVE) / TOP_N
FEE = 0.001425
MIN_FEE = 20.0  # an explicit broker scenario, not a universal tariff
PRICE_BUFFER = 0.01


def commission(value: float) -> float:
    return max(value * FEE, MIN_FEE)


def parts(shares: int) -> tuple[int, int]:
    return shares // 1000 * 1000, shares % 1000


def planned_cost(shares: int, reference: float) -> float:
    whole, odd = parts(shares)
    px = reference * (1 + PRICE_BUFFER)
    return sum(n * px + commission(n * px) for n in (whole, odd) if n)


def planned_shares(reference: float) -> int:
    if reference <= 0 or not np.isfinite(reference):
        return 0
    # Find the greatest integer amount that fits each position's fixed budget
    # after separate regular/odd-order minimum commissions.
    upper = int(PER_NAME // reference) + 1
    lo, hi = 0, upper
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if planned_cost(mid, reference) <= PER_NAME:
            lo = mid
        else:
            hi = mid - 1
    return lo


def january_scores(prices: pd.DataFrame) -> pd.DataFrame:
    labels = pd.read_csv(SOURCE / "surge_labels_adjusted_2023_2026.csv.gz",
                         dtype={"symbol": str}, parse_dates=["date", "label_window_end"])
    roles = pd.read_csv(SOURCE / "temporal_split_2023_2026.csv.gz",
                        dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    panel = training_frame(feature_panel(prices, calendar), labels, roles,
                           [("2429", pd.Timestamp("2024-07-02"))])
    start = pd.Timestamp("2026-01-01")
    train = panel[panel.signal_eligible & panel.label_available.eq(True) &
                  ~panel.quarantined_label & panel.date.lt(start) &
                  panel.label_window_end.lt(start)]
    assert len(train) == 381756 and train.label_window_end.max() == pd.Timestamp("2025-12-31")
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500))
    model.fit(train[FEATURES], train.surge_adjusted.astype(int))
    old = pd.read_csv(OUT / "holdout_scores_2026_v57.csv.gz", dtype={"symbol": str},
                      parse_dates=["date"])
    check = panel[panel.date.eq(start + pd.Timedelta(days=1))].merge(
        old[old.date.eq(start + pd.Timedelta(days=1))][["symbol", "logistic"]],
        on="symbol", validate="one_to_one")
    assert len(check) > 500
    assert np.max(abs(model.predict_proba(check[FEATURES])[:, 1] - check.logistic)) < 1e-12
    jan = panel[panel.date.eq(pd.Timestamp("2025-12-31")) & panel.signal_eligible].copy()
    jan["logistic"] = model.predict_proba(jan[FEATURES])[:, 1]
    jan["mom60_skip5"] = jan.mom60_skip5.astype(float)
    return jan[["date", "symbol", *METHODS]].copy()


def main() -> None:
    prices = pd.read_csv(SOURCE / "prices_adjusted_2023_2026.csv.gz",
                         dtype={"symbol": str}, parse_dates=["date"])
    jan = january_scores(prices)
    score = pd.read_csv(OUT / "holdout_scores_2026_v57.csv.gz", dtype={"symbol": str},
                        parse_dates=["date"])
    months = pd.read_csv(OUT / "monthly_signal_audit_2026_v62.csv")
    old_selections = pd.read_csv(OUT / "monthly_selections_2026_v62.csv", dtype={"symbol": str})
    signal_pairs = [(pd.Timestamp("2025-12-31"), pd.Timestamp("2026-01-02"))]
    signal_pairs += [(pd.Timestamp(x.signal_date), pd.Timestamp(x.fill_date))
                     for x in months[months.method.eq("logistic")].itertuples()
                     if x.fill_date != "2026-01-02"]
    assert len(signal_pairs) == 9 and len(set(signal_pairs)) == 9
    raw_quote = prices[["date", "symbol", "close", "open", "volume"]]
    records, actions, monthly = [], [], []
    for method in METHODS:
        previous: set[str] = set()
        for signal, fill in signal_pairs:
            frame = jan if signal == pd.Timestamp("2025-12-31") else score[score.date.eq(signal)]
            assert len(frame) > TOP_N
            ranked = frame.sort_values([method, "symbol"], ascending=[False, True]).head(TOP_N).copy()
            assert ranked.symbol.is_unique
            prior = raw_quote[raw_quote.date.eq(signal)][["symbol", "close"]]
            ranked = ranked.merge(prior, on="symbol", validate="one_to_one")
            assert len(ranked) == TOP_N and ranked.close.gt(0).all()
            previous_old = set(old_selections[(old_selections.method.eq(method)) &
                                               (old_selections.fill_date.eq(str(fill.date())))].symbol)
            assert set(ranked.symbol).issubset(previous_old)
            names = set(ranked.symbol)
            for n, x in enumerate(ranked.itertuples(), 1):
                quantity = planned_shares(x.close)
                whole, odd = parts(quantity)
                assert planned_cost(quantity, x.close) <= PER_NAME + 1e-9
                if quantity:
                    assert planned_cost(quantity + 1, x.close) > PER_NAME
                records.append({"method": method, "signal_date": str(signal.date()),
                                "planned_trade_date": str(fill.date()), "symbol": x.symbol,
                                "rank": n, "ranking_score": getattr(x, method),
                                "score_kind": "uncalibrated_surge_logistic" if method == "logistic" else "momentum_rule",
                                "signal_raw_close": x.close, "position_target_twd": PER_NAME,
                                "is_continuing": x.symbol in previous,
                                "sizing_shares_if_new": quantity,
                                "regular_shares_if_new": whole, "odd_lot_shares_if_new": odd,
                                "sizing_cost_with_buffer_if_new": planned_cost(quantity, x.close),
                                "planned_action": "hold_no_rebalance" if x.symbol in previous else
                                                  ("buy_candidate" if quantity else "skip_unaffordable"),
                                "fill_status": "unverified" if x.symbol not in previous and quantity else "not_applicable"})
                if x.symbol not in previous:
                    for venue, size in (("regular", whole), ("intraday_odd_lot", odd)):
                        if size:
                            actions.append({"method": method, "signal_date": str(signal.date()),
                                            "planned_trade_date": str(fill.date()), "symbol": x.symbol,
                                            "side": "buy", "venue": venue, "quantity_if_filled": size,
                                            "sizing_reference_close": x.close, "per_name_budget_twd": PER_NAME,
                                            "fill_price": None, "fill_quantity": None,
                                            "execution_status": "unverified"})
            for symbol in sorted(previous - names):
                actions.append({"method": method, "signal_date": str(signal.date()),
                                "planned_trade_date": str(fill.date()), "symbol": symbol,
                                "side": "sell", "venue": "dependent_on_delivered_holdings",
                                "quantity_if_filled": None, "sizing_reference_close": None,
                                "per_name_budget_twd": None, "fill_price": None,
                                "fill_quantity": None, "execution_status": "unverified"})
            monthly.append({"method": method, "signal_date": str(signal.date()),
                            "planned_trade_date": str(fill.date()), "selected": TOP_N,
                            "retained": len(names & previous), "new": len(names - previous),
                            "retired": len(previous - names),
                            "initial_capital_twd": CAPITAL, "reserve_twd": CAPITAL * RESERVE,
                            "nominal_target_per_name_twd": PER_NAME,
                            "executed_trades": 0, "portfolio_nav_produced": False})
            previous = names
    selection = pd.DataFrame(records)
    orders = pd.DataFrame(actions)
    monthly = pd.DataFrame(monthly)
    assert len(selection) == TOP_N * 9 * len(METHODS)
    assert monthly.groupby("method").size().eq(9).all()
    selection.to_csv(OUT / "top15_300k_selections_2026_v74.csv", index=False)
    orders.to_csv(OUT / "top15_300k_order_intents_2026_v74.csv", index=False, na_rep="")
    monthly.to_csv(OUT / "top15_300k_monthly_intents_2026_v74.csv", index=False)
    print(monthly.to_string(index=False))
    print("venue / side", orders.groupby(["venue", "side"]).size().to_dict())


if __name__ == "__main__":
    main()
