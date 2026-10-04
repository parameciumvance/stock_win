"""Fixed-parameter retrospective yearly folds after adding official 2023 data.

2024/2025 were already explored in v54. These folds are descriptive and not
prospectively untouched validation. No portfolio NAV is computed.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from twse_history.research_v5 import FEATURES, feature_panel, training_frame


METHODS = ("logistic", "hist_gradient_boosting", "mom60_skip5", "mom20")


def yearly_fold(panel: pd.DataFrame, year: int, first_train_year: int):
    start = pd.Timestamp(year, 1, 1)
    finish = pd.Timestamp(year + 1, 1, 1)
    eligible = panel[panel.signal_eligible & panel.label_available.eq(True) &
                     ~panel.quarantined_label].copy()
    train = eligible[eligible.date.ge(pd.Timestamp(first_train_year, 1, 1)) &
                     eligible.date.lt(start) & eligible.label_window_end.lt(start)].copy()
    test = eligible[eligible.date.ge(start) & eligible.date.lt(finish)].copy()
    if train.empty or test.empty or train.surge_adjusted.nunique() != 2:
        raise ValueError(f"Empty or single-class fold for {year}")
    if train.label_window_end.max() >= test.date.min():
        raise ValueError("Overlapping training label window")
    if not np.isfinite(train[FEATURES]).all().all() or not np.isfinite(test[FEATURES]).all().all():
        raise ValueError("Nonfinite causal features")
    models = {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            learning_rate=.06, max_iter=100, max_leaf_nodes=15,
            min_samples_leaf=100, l2_regularization=1., early_stopping=False,
            random_state=2025),
    }
    for method, model in models.items():
        model.fit(train[FEATURES], train.surge_adjusted.astype(int))
        test[method] = model.predict_proba(test[FEATURES])[:, 1]
    test["fold"] = f"{first_train_year}-{year - 1}_to_{year}"
    detail = dict(fold=test.fold.iloc[0], train_rows=len(train),
                  train_dates=train.date.nunique(),
                  train_first=str(train.date.min().date()),
                  train_last=str(train.date.max().date()),
                  max_train_label_end=str(train.label_window_end.max().date()),
                  eval_rows=len(test), eval_dates=test.date.nunique(),
                  eval_first=str(test.date.min().date()),
                  eval_last=str(test.date.max().date()),
                  positives=int(test.surge_adjusted.sum()))
    return test, detail


def daily_and_summary(test, detail):
    day_rows = []
    for date, day in test.groupby("date", sort=True):
        k = math.ceil(.1 * len(day))
        row = dict(fold=detail["fold"], date=str(date.date()),
                   eligible=len(day), top_n=k,
                   base_rate=float(day.surge_adjusted.mean()))
        for method in METHODS:
            row[method] = float(day.nlargest(k, method).surge_adjusted.mean())
        day_rows.append(row)
    daily = pd.DataFrame(day_rows)
    summary = []
    for method in METHODS:
        summary.append(dict(fold=detail["fold"], method=method,
                            train_rows=detail["train_rows"],
                            train_dates=detail["train_dates"],
                            eval_rows=len(test), eval_dates=len(daily),
                            prevalence=float(test.surge_adjusted.mean()),
                            pr_auc=float(average_precision_score(
                                test.surge_adjusted.astype(int), test[method])),
                            daily_top10_precision=float(daily[method].mean())))
    return daily, pd.DataFrame(summary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("twse_history/output_multiyear_2023_2025"))
    p.add_argument("--output", type=Path, default=Path("deliverables"))
    args = p.parse_args()
    source, out = args.source, args.output
    out.mkdir(parents=True, exist_ok=True)
    suffix = "_2023_2025.csv.gz"
    prices = pd.read_csv(source / ("prices_adjusted" + suffix),
                         dtype={"symbol": str}, parse_dates=["date"])
    labels = pd.read_csv(source / ("surge_labels_adjusted" + suffix),
                         dtype={"symbol": str}, parse_dates=["date", "label_window_end"])
    roles = pd.read_csv(source / ("temporal_split" + suffix),
                        dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    if calendar.min() != pd.Timestamp("2023-01-03") or len(calendar) != 724:
        raise ValueError("Unexpected 2023-2025 market calendar")
    features = feature_panel(prices, calendar, min_turnover=10_000_000)
    panel = training_frame(features, labels, roles, [("2429", pd.Timestamp("2024-07-02"))])
    # One yearly historical fold and two choices of training history for 2025.
    folds = [(2024, 2023), (2025, 2023), (2025, 2024)]
    all_daily, all_summary, all_scores, fold_details = [], [], [], []
    for year, first_train in folds:
        test, detail = yearly_fold(panel, year, first_train)
        daily, summary = daily_and_summary(test, detail)
        all_daily.append(daily)
        all_summary.append(summary)
        all_scores.append(test[["fold", "date", "symbol", "surge_adjusted", *METHODS]])
        fold_details.append(detail)
        print(json.dumps(detail), flush=True)
    daily = pd.concat(all_daily, ignore_index=True)
    summary = pd.concat(all_summary, ignore_index=True)
    scores = pd.concat(all_scores, ignore_index=True)
    daily.to_csv(out / "crossyear_daily_v55.csv", index=False)
    summary.to_csv(out / "crossyear_summary_v55.csv", index=False)
    scores.to_csv(out / "crossyear_scores_v55.csv.gz", index=False, compression="gzip")
    (out / "crossyear_folds_v55.json").write_text(json.dumps(fold_details, indent=2))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
