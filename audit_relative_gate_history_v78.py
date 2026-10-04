"""Replicate a fixed >0 relative-return gate on 2024/25 monthly score dates.

Uses yearly purged model scores already computed independently of each year's
future labels. January-style first-trading-day signals are rank diagnostics,
not fills; 2024/25 periods were previously studied and are not fresh tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from audit_relative_return_model_v76 import OUT


def main():
    surge = pd.read_csv(OUT / "crossyear_scores_v55.csv.gz", dtype={"symbol": str},
                        parse_dates=["date"])
    surge = surge[surge.fold.isin(["2023-2023_to_2024", "2023-2024_to_2025"])]
    regression = pd.read_csv(OUT / "relative_return_tree_scores_v77.csv.gz",
                             dtype={"symbol": str}, parse_dates=["date"])
    regression = regression[regression.fold.isin([2024, 2025])]
    scored = surge.merge(regression[["date", "symbol", "predicted_relative20",
                                     "relative_return20"]],
                         on=["date", "symbol"], validate="one_to_one")
    assert scored.date.dt.year.isin([2024, 2025]).all()
    assert not scored.duplicated(["date", "symbol"]).any()
    assert len(scored) > 300_000 and np.isfinite(scored.predicted_relative20).all()
    month_key = scored.date.dt.to_period("M")
    first = scored.groupby(month_key).date.min()
    first_dates = set(first)
    monthly = scored[scored.date.isin(first_dates)].copy()
    assert monthly.date.nunique() == 24
    details, summary = [], []
    for date, frame in monthly.groupby("date", sort=True):
        for method in ("logistic", "mom60_skip5"):
            selected = frame.sort_values([method, "symbol"],ascending=[False,True]).head(15)
            assert len(selected) == 15
            positive = selected[selected.predicted_relative20.gt(0)]
            summary.append(dict(year=date.year, date=str(date.date()), method=method,
                                selected=15, passing=len(positive),
                                all_mean_relative20=float(selected.relative_return20.mean()),
                                passing_mean_relative20=float(positive.relative_return20.mean())
                                if len(positive) else np.nan))
            for row in selected.itertuples():
                details.append(dict(date=str(date.date()), method=method,
                                    symbol=row.symbol, surge_score=getattr(row,method),
                                    predicted_relative20=row.predicted_relative20,
                                    relative_return20=row.relative_return20,
                                    pass_positive_relative_pred=row.predicted_relative20>0,
                                    gate_status="diagnostic_only_no_orders_changed"))
    detail, monthly_summary = pd.DataFrame(details),pd.DataFrame(summary)
    assert len(detail)==720 and len(monthly_summary)==48
    detail.to_csv(OUT / "relative_gate_history_detail_v78.csv",index=False)
    monthly_summary.to_csv(OUT / "relative_gate_history_monthly_v78.csv",index=False)
    by_year = detail.assign(year=detail.date.str[:4]).groupby(
        ["year", "method", "pass_positive_relative_pred"],as_index=False).agg(
            n=("symbol","size"), mean_relative20=("relative_return20","mean"))
    by_year.to_csv(OUT / "relative_gate_history_summary_v78.csv",index=False)
    print(by_year.to_string(index=False))


if __name__ == "__main__":
    main()
