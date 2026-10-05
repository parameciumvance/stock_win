"""Compare frozen surge scores with simple volatility-only rankings.

All methods use exactly the same eligible stock-days in each calendar-year
fold. This is retrospective label discrimination, not executable performance.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from twse_history.research_v5 import feature_panel


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "twse_history/output_multiyear_2023_2026_asof_20261002"
OUT = ROOT / "deliverables"
METHODS = ("logistic", "hist_gradient_boosting", "mom60_skip5",
           "volatility20", "atr14")


def assemble() -> pd.DataFrame:
    prices = pd.read_csv(SOURCE / "prices_adjusted_2023_2026.csv.gz",
                         dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    features = feature_panel(prices, calendar)[
        ["date", "symbol", "signal_eligible", "volatility20", "atr14",
         "relative_return20"]]
    old = pd.read_csv(OUT / "crossyear_scores_v55.csv.gz",
                      dtype={"symbol": str}, parse_dates=["date"])
    old = old[old.fold.isin(["2023-2023_to_2024", "2023-2024_to_2025"])]
    new = pd.read_csv(OUT / "holdout_scores_2026_v57.csv.gz",
                      dtype={"symbol": str}, parse_dates=["date"])
    scored = pd.concat([old, new], ignore_index=True)
    assert scored.date.dt.year.isin([2024, 2025, 2026]).all()
    assert not scored.duplicated(["date", "symbol"]).any()
    scored = scored.merge(features, on=["date", "symbol"], validate="one_to_one")
    # v55's 2025 scores end at 12-02 because its original source ended 12-31;
    # do not silently extrapolate the frozen Logistic beyond those scored days.
    assert len(scored) == 169005 + 139487 + 110932
    assert scored.signal_eligible.eq(True).all()
    assert np.isfinite(scored[["volatility20", "atr14", "relative_return20"]]).all().all()
    assert scored.surge_adjusted.notna().all()
    scored["fold_year"] = scored.date.dt.year
    return scored


def evaluate(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = []
    for date, frame in scored.groupby("date", sort=True):
        k = math.ceil(.1 * len(frame))
        base = float(frame.surge_adjusted.mean())
        row = dict(date=str(date.date()), year=date.year, eligible=len(frame), top_n=k,
                   base_rate=base, universe_relative20=float(frame.relative_return20.mean()))
        for method in METHODS:
            order = frame.sort_values([method, "symbol"], ascending=[False, True])
            for tag, subset in (("top10", order.head(k)), ("top15", order.head(15))):
                row[f"{method}_{tag}_hit"] = float(subset.surge_adjusted.mean())
                row[f"{method}_{tag}_relative20"] = float(subset.relative_return20.mean())
            row[f"{method}_relative_rank_ic"] = float(
                frame[method].corr(frame.relative_return20, method="spearman"))
        daily.append(row)
    daily = pd.DataFrame(daily)
    summary = []
    for year, group in daily.groupby("year"):
        base = float(group.base_rate.mean())
        for method in METHODS:
            hit = float(group[f"{method}_top10_hit"].mean())
            summary.append(dict(year=year, method=method, dates=len(group),
                                stock_days=int(group.eligible.sum()),
                                base_rate=base, top10_hit=hit, top10_lift=hit/base,
                                top15_hit=float(group[f"{method}_top15_hit"].mean()),
                                top15_relative20=float(group[f"{method}_top15_relative20"].mean()),
                                universe_relative20=float(group.universe_relative20.mean()),
                                mean_relative_rank_ic=float(
                                    group[f"{method}_relative_rank_ic"].mean())))
    assert daily.groupby("year").size().to_dict()=={2024:242,2025:223,2026:161}
    return daily,pd.DataFrame(summary)


def main():
    OUT.mkdir(exist_ok=True)
    scored = assemble()
    daily, summary = evaluate(scored)
    daily.to_csv(OUT / "volatility_baseline_daily_v79.csv",index=False)
    summary.to_csv(OUT / "volatility_baseline_summary_v79.csv",index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
