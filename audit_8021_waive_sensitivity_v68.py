"""Recompute the v66 descriptive quote proxy under one explicit rights waiver.

The 8021 2026-01-13 subscription terms are supported by issuer notices;
this does not infer that a real investor waived rights or filled opening orders.
"""
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deliverables"
SOURCE = OUT / "cash_only_monthly_proxy_2026_v66.csv"


def main() -> None:
    d = pd.read_csv(SOURCE, dtype={"symbol": str})
    original = d.copy(deep=True)
    target = (
        d.symbol.eq("8021")
        & d.entry_date.eq("2026-01-02")
        & d.exit_observation_date.eq("2026-02-02")
        & d.method.isin(["logistic", "mom60_skip5"])
    )
    assert target.sum() == 2
    assert set(d.loc[target, "method"]) == {"logistic", "mom60_skip5"}
    assert d.loc[target, "in_holding_unresolved_event_count"].eq(1).all()
    assert d.loc[target, "in_holding_cash_event_count"].eq(0).all()
    assert d.loc[target, "missing_or_nontrade_days"].eq(0).all()
    assert d.loc[target, "gross_cash_entitlement_proxy_available"].eq(False).all()
    assert d.loc[target, "entry_raw_open"].eq(193.5).all()
    assert d.loc[target, "exit_raw_open"].eq(196.5).all()
    # Prices are unadjusted; in the waiver scenario, original shares remain
    # and neither subscription cash nor pending shares enter the account.
    d["v68_scenario"] = "v66_cash_only"
    d.loc[target, "gross_price_plus_cash_return"] = (
        d.loc[target, "exit_raw_open"] / d.loc[target, "entry_raw_open"] - 1
    )
    d.loc[target, "gross_cash_entitlement_proxy_available"] = True
    d.loc[target, "v68_scenario"] = "8021_waive_paid_subscription"
    assert d.loc[~target, original.columns].equals(original.loc[~target, original.columns])
    d.to_csv(OUT / "waive_8021_monthly_proxy_2026_v68.csv", index=False)

    keys = ["method", "entry_date", "exit_observation_date"]
    m = d.groupby(keys, sort=True).agg(
        selected=("symbol", "size"),
        available=("gross_cash_entitlement_proxy_available", "sum"),
        scenario_rows=("v68_scenario", lambda x: (x == "8021_waive_paid_subscription").sum()),
        mean_gross_price_plus_cash_return=("gross_price_plus_cash_return", "mean"),
    ).reset_index()
    m["coverage"] = m.available / m.selected
    m.to_csv(OUT / "waive_8021_monthly_proxy_by_month_2026_v68.csv", index=False)
    s = m.groupby("method", sort=True).agg(
        months=("entry_date", "size"),
        selected=("selected", "sum"),
        available=("available", "sum"),
        scenario_rows=("scenario_rows", "sum"),
        mean_of_nine_monthly_means=("mean_gross_price_plus_cash_return", "mean"),
    ).reset_index()
    assert s.set_index("method").available.to_dict() == {"logistic": 609, "mom60_skip5": 614}
    assert s.scenario_rows.eq(1).all()
    s.to_csv(OUT / "waive_8021_monthly_proxy_summary_2026_v68.csv", index=False)
    print(s.to_string(index=False))


if __name__ == "__main__":
    main()
