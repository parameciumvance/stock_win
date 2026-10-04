"""Round-trip per-name cost stress over v69's observable subset only."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deliverables"
FEE = 0.001425  # illustrative broker rate, not an account contract
SELL_TAX = 0.003  # ordinary stock sale, no intraday offset
SLIPPAGES = (0, 0.005, 0.01)


def main() -> None:
    base = pd.read_csv(OUT / "pure_rights_waiver_proxy_2026_v69.csv", dtype={"symbol": str})
    observed = base[base.gross_cash_entitlement_proxy_available].copy()
    assert observed.groupby("method").size().to_dict() == {"logistic": 614, "mom60_skip5": 615}
    assert observed.entry_raw_open.notna().all() and observed.exit_raw_open.notna().all()
    assert observed.gross_cash_per_original_share.notna().all()
    assert (observed.entry_raw_open > 0).all() and (observed.exit_raw_open > 0).all()
    calc = (observed.exit_raw_open + observed.gross_cash_per_original_share) / observed.entry_raw_open - 1
    assert (calc - observed.gross_price_plus_cash_return).abs().max() < 1e-12

    records = []
    for slip in SLIPPAGES:
        frame = observed.copy()
        frame["slippage_per_side"] = slip
        frame["buy_broker_fee_rate"] = FEE
        frame["sell_broker_fee_rate"] = FEE
        frame["sell_transaction_tax_rate"] = SELL_TAX
        frame["entry_cost_per_original_share"] = frame.entry_raw_open * (1 + slip) * (1 + FEE)
        frame["exit_proceeds_per_original_share"] = frame.exit_raw_open * (1 - slip) * (1 - FEE - SELL_TAX)
        frame["diagnostic_net_per_name_return"] = (
            (frame.exit_proceeds_per_original_share + frame.gross_cash_per_original_share)
            / frame.entry_cost_per_original_share - 1
        )
        assert (frame.diagnostic_net_per_name_return <= frame.gross_price_plus_cash_return + 1e-12).all()
        records.append(frame)
    detail = pd.concat(records, ignore_index=True)
    detail.to_csv(OUT / "monthly_cost_stress_detail_2026_v71.csv", index=False)
    by = detail.groupby(["method", "slippage_per_side", "entry_date"], sort=True).agg(
        observed=("symbol", "size"),
        mean_gross=("gross_price_plus_cash_return", "mean"),
        mean_diagnostic_net=("diagnostic_net_per_name_return", "mean"),
    ).reset_index()
    assert by.groupby(["method", "slippage_per_side"]).size().eq(9).all()
    by.to_csv(OUT / "monthly_cost_stress_by_month_2026_v71.csv", index=False)
    summary = by.groupby(["method", "slippage_per_side"], sort=True).agg(
        months=("entry_date", "size"), observed=("observed", "sum"),
        mean_of_monthly_gross=("mean_gross", "mean"),
        mean_of_monthly_diagnostic_net=("mean_diagnostic_net", "mean"),
    ).reset_index()
    summary["percentage_point_drag"] = 100 * (summary.mean_of_monthly_gross - summary.mean_of_monthly_diagnostic_net)
    assert (summary.months == 9).all()
    summary.to_csv(OUT / "monthly_cost_stress_summary_2026_v71.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
