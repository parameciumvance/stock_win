"""Fixed Ridge 20-market-day relative-return research, no fill or portfolio NAV.

Annual time folds are descriptive: every calendar year here has already been
inspected for the surge research. The 2026 Top-15 filter diagnostic is a new
post hoc branch and must not be presented as an independent strategy test.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from twse_history.research_v5 import FEATURES, feature_panel, training_frame


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "twse_history/output_multiyear_2023_2026_asof_20261002"
OUT = ROOT / "deliverables"
EXCLUDE_2026 = {"3149", "4989", "6225"}  # v57 official reference-price discontinuities
ALPHA = 100.0  # fixed before observing the regression outputs; no tuning here


def prep() -> pd.DataFrame:
    prices = pd.read_csv(SOURCE / "prices_adjusted_2023_2026.csv.gz",
                         dtype={"symbol": str}, parse_dates=["date"])
    labels = pd.read_csv(SOURCE / "surge_labels_adjusted_2023_2026.csv.gz",
                         dtype={"symbol": str}, parse_dates=["date", "label_window_end"])
    roles = pd.read_csv(SOURCE / "temporal_split_2023_2026.csv.gz",
                        dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    assert calendar.min() == pd.Timestamp("2023-01-03")
    assert calendar.max() == pd.Timestamp("2026-10-02")
    panel = training_frame(feature_panel(prices, calendar), labels, roles,
                           [("2429", pd.Timestamp("2024-07-02"))])
    assert not panel.duplicated(["date", "symbol"]).any()
    # The existing secondary target requires all 20 subsequent market days.
    eligible = panel[panel.signal_eligible & panel.label_available.eq(True) &
                     ~panel.quarantined_label & panel.relative_return20.notna()].copy()
    eligible = eligible[~(eligible.date.dt.year.eq(2026) &
                          eligible.symbol.isin(EXCLUDE_2026))].copy()
    assert np.isfinite(eligible[FEATURES + ["relative_return20"]]).all().all()
    return eligible


def fit_at(data: pd.DataFrame, start: pd.Timestamp):
    train = data[data.date.lt(start) & data.label_window_end.lt(start)].copy()
    assert len(train) > 10_000 and train.label_window_end.max() < start
    model = make_pipeline(StandardScaler(), Ridge(alpha=ALPHA))
    model.fit(train[FEATURES], train.relative_return20)
    return train, model


def day_metrics(frame: pd.DataFrame, fold: str):
    records = []
    for date, group in frame.groupby("date", sort=True):
        target = group.relative_return20
        row = dict(fold=fold, date=str(date.date()), eligible=len(group),
                   n=min(15, len(group)), population_mean=float(target.mean()),
                   rank_ic=float(group.predicted_relative20.corr(target, method="spearman")))
        for method in ("predicted_relative20", "mom60_skip5"):
            chosen = group.sort_values([method, "symbol"], ascending=[False, True]).head(15)
            row[method + "_top15_mean"] = float(chosen.relative_return20.mean())
        records.append(row)
    return pd.DataFrame(records)


def main():
    OUT.mkdir(exist_ok=True)
    data = prep()
    daily, folds = [], []
    scores = None
    for year in (2024, 2025, 2026):
        start = pd.Timestamp(year, 1, 1)
        end = pd.Timestamp(year + 1, 1, 1)
        train, model = fit_at(data, start)
        test = data[data.date.ge(start) & data.date.lt(end)].copy()
        assert len(test) > 1_000 and test.date.min() >= start
        if year == 2026:
            assert test.date.max() <= pd.Timestamp("2026-09-02")
        test["predicted_relative20"] = model.predict(test[FEATURES])
        test["fold"] = str(year)
        test["train_mean"] = float(train.relative_return20.mean())
        ds = day_metrics(test, str(year))
        daily.append(ds)
        rmse = math.sqrt(mean_squared_error(test.relative_return20,
                                            test.predicted_relative20))
        baseline_rmse = math.sqrt(mean_squared_error(test.relative_return20,
                                                     test.train_mean))
        folds.append(dict(fold=year, train_rows=len(train),
                          train_max_label_end=str(train.label_window_end.max().date()),
                          eval_rows=len(test), eval_dates=test.date.nunique(),
                          eval_min=str(test.date.min().date()),
                          eval_max=str(test.date.max().date()),
                          rmse=rmse, train_mean_baseline_rmse=baseline_rmse,
                          mae=float(mean_absolute_error(test.relative_return20,
                                                        test.predicted_relative20)),
                          mean_daily_rank_ic=float(ds.rank_ic.mean()),
                          pred_top15_relative20=float(ds.predicted_relative20_top15_mean.mean()),
                          mom_top15_relative20=float(ds.mom60_skip5_top15_mean.mean()),
                          universe_relative20=float(ds.population_mean.mean())))
        if year == 2026:
            scores = test[["date", "symbol", "predicted_relative20",
                           "relative_return20", "mom60_skip5"]].copy()
    assert scores is not None
    daily = pd.concat(daily, ignore_index=True)
    pd.DataFrame(folds).to_csv(OUT / "relative_return_folds_v76.csv", index=False)
    daily.to_csv(OUT / "relative_return_daily_v76.csv", index=False)

    # The adopted January signal is 2025-12-31, prior to the January execution.
    # Its score uses the very same 2026-as-of-Jan-1 fit with purged labels.
    train, model = fit_at(data, pd.Timestamp("2026-01-01"))
    jan = data[data.date.eq(pd.Timestamp("2025-12-31"))].copy()
    jan["predicted_relative20"] = model.predict(jan[FEATURES])
    jan = jan[["date", "symbol", "predicted_relative20", "relative_return20"]]
    comparison = pd.read_csv(OUT / "top15_300k_selections_2026_v74.csv",
                             dtype={"symbol": str}, parse_dates=["signal_date"])
    regression = pd.concat([jan.rename(columns={"date": "signal_date"}),
                            scores.rename(columns={"date": "signal_date"})], ignore_index=True)
    joined = comparison.merge(regression[["signal_date", "symbol", "predicted_relative20",
                                          "relative_return20"]],
                              on=["signal_date", "symbol"], how="left", validate="many_to_one")
    assert len(joined) == len(comparison) and joined.predicted_relative20.notna().all()
    joined["pass_positive_relative_pred"] = joined.predicted_relative20.gt(0)
    joined["gate_status"] = "diagnostic_only_no_orders_changed"
    grouped = joined.groupby(["method", "signal_date"], as_index=False).agg(
        selected=("symbol", "size"), passing=("pass_positive_relative_pred", "sum"),
        mean_predicted_relative20=("predicted_relative20", "mean"),
        mean_realized_relative20=("relative_return20", "mean"))
    assert grouped.selected.eq(15).all()
    joined.to_csv(OUT / "top15_relative_gate_diagnostic_2026_v76.csv", index=False)
    grouped.to_csv(OUT / "top15_relative_gate_monthly_2026_v76.csv", index=False)
    metadata = dict(target="adjusted_close_20_market_day_return_minus_0050_adjusted_close_20_return",
                    features=FEATURES, model="StandardScaler + Ridge(alpha=100)",
                    time_rule="train label_window_end < evaluation-year Jan 1",
                    historical_folds=[2024, 2025, 2026],
                    evaluated_2026_end="2026-09-02", excluded_2026=sorted(EXCLUDE_2026),
                    gate="predicted relative return > 0; retrospective diagnostic only",
                    independently_untouched=False, tradeable_nav=False)
    (OUT / "relative_return_meta_v76.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    print(pd.DataFrame(folds).to_string(index=False))
    print(grouped.to_string(index=False))


if __name__ == "__main__":
    main()
