"""Waive the six pure '權' rights events in v66; keep pure cash accruals.

This is a scenario for original shares, not a claim about actual elections,
liquidity, rights transferability, subscription proceeds, or account NAV.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deliverables"
RAW = ROOT / "twse_history/raw/exrights_2026.json"


def main() -> None:
    base = pd.read_csv(OUT / "cash_only_monthly_proxy_2026_v66.csv", dtype={"symbol": str})
    old = base.copy(deep=True)
    inventory = pd.read_csv(OUT / "unresolved_monthly_rights_inventory_2026_v67.csv", dtype={"symbol": str})
    pure = inventory[inventory.event_type.eq("權")]
    assert len(pure) == 8 and pure.event_id.nunique() == 6
    raw = json.loads(RAW.read_text())
    fields = raw["fields"]
    raw_events = {(r[fields.index("股票代號")],
                   str(int(r[fields.index("資料日期")].split("年")[0]) + 1911)
                   + "-" + r[fields.index("資料日期")].split("年")[1].replace("月", "-").replace("日", "")):
                  r for r in raw["data"]}
    for x in pure.itertuples():
        r = raw_events[(x.symbol, x.event_date)]
        assert r[fields.index("權/息")] == "權"
        before = float(r[fields.index("除權息前收盤價")].replace(",", ""))
        cash_and_free_only = float(r[fields.index("減除股利參考價")].replace(",", ""))
        rights_ref = float(r[fields.index("除權息參考價")].replace(",", ""))
        assert before == cash_and_free_only and rights_ref < before
    base["v69_scenario"] = "v66_cash_only"
    target_indices = set()
    for x in pure.itertuples():
        m = (base.method.eq(x.method) & base.symbol.eq(x.symbol)
             & base.entry_date.eq(x.entry_date)
             & base.exit_observation_date.eq(x.exit_observation_date))
        assert m.sum() == 1
        i = base.index[m][0]
        target_indices.add(i)
        assert old.at[i, "in_holding_unresolved_event_count"] == 1
        assert old.at[i, "missing_or_nontrade_days"] == 0
        assert not old.at[i, "gross_cash_entitlement_proxy_available"]
        base.at[i, "gross_price_plus_cash_return"] = (
            (base.at[i, "exit_raw_open"] + base.at[i, "gross_cash_per_original_share"])
            / base.at[i, "entry_raw_open"] - 1
        )
        base.at[i, "gross_cash_entitlement_proxy_available"] = True
        base.at[i, "v69_scenario"] = "waive_pure_paid_rights"
    assert len(target_indices) == 8
    assert base.loc[~base.index.isin(target_indices), old.columns].equals(
        old.loc[~base.index.isin(target_indices), old.columns]
    )
    base.to_csv(OUT / "pure_rights_waiver_proxy_2026_v69.csv", index=False)

    by = base.groupby(["method", "entry_date", "exit_observation_date"], sort=True).agg(
        selected=("symbol", "size"),
        available=("gross_cash_entitlement_proxy_available", "sum"),
        waiver_scenario_stock_months=("v69_scenario", lambda x:(x == "waive_pure_paid_rights").sum()),
        mean_gross_price_plus_cash_return=("gross_price_plus_cash_return", "mean"),
    ).reset_index()
    by["coverage"] = by.available / by.selected
    by.to_csv(OUT / "pure_rights_waiver_by_month_2026_v69.csv", index=False)
    total = by.groupby("method", sort=True).agg(
        months=("entry_date", "size"), selected=("selected", "sum"),
        available=("available", "sum"),
        waiver_scenario_stock_months=("waiver_scenario_stock_months", "sum"),
        mean_of_nine_monthly_means=("mean_gross_price_plus_cash_return", "mean"),
    ).reset_index()
    assert total.set_index("method").available.to_dict() == {"logistic": 614, "mom60_skip5": 615}
    assert total.set_index("method").waiver_scenario_stock_months.to_dict() == {
        "logistic": 6, "mom60_skip5": 2
    }
    total.to_csv(OUT / "pure_rights_waiver_summary_2026_v69.csv", index=False)
    print(total.to_string(index=False))


if __name__ == "__main__":
    main()
