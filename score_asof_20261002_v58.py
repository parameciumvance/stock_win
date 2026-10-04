"""Research-only after-close ranking as of 2026-10-02 with fixed v5 models.

Training labels must end on or before the signal date. No future labels are
consulted to produce the current ranking. This is not an execution strategy.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from twse_history.research_v5 import FEATURES, feature_panel, training_frame


UNCERTAIN_RIGHTS = {"3149", "4989", "6225"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path,
                   default=Path("twse_history/output_multiyear_2023_2026_asof_20261002"))
    p.add_argument("--output", type=Path, default=Path("deliverables"))
    p.add_argument("--signal-date", default="2026-10-02")
    args = p.parse_args()
    as_of = pd.Timestamp(args.signal_date)
    if args.signal_date != "2026-10-02":
        raise ValueError("This frozen artifact is only validated for 2026-10-02")
    source, out = args.source, args.output
    meta = json.loads((source / "summary_2023_2026.json").read_text())
    if meta["as_of"] != args.signal_date or not meta["calendar_exact_match"]:
        raise ValueError("Source cutoff or calendar mismatch")
    suffix = "_2023_2026.csv.gz"
    prices = pd.read_csv(source / ("prices_adjusted" + suffix),
                         dtype={"symbol": str}, parse_dates=["date"])
    labels = pd.read_csv(source / ("surge_labels_adjusted" + suffix),
                         dtype={"symbol": str}, parse_dates=["date", "label_window_end"])
    roles = pd.read_csv(source / ("temporal_split" + suffix),
                        dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    if calendar.max() != as_of or len(calendar) != 905:
        raise ValueError("Unexpected calendar")
    features = feature_panel(prices, calendar, min_turnover=10_000_000)
    panel = training_frame(features, labels, roles, [("2429", pd.Timestamp("2024-07-02"))])
    uncertain = panel.symbol.isin(UNCERTAIN_RIGHTS) & panel.date.dt.year.eq(2026)
    train = panel[panel.signal_eligible & panel.label_available.eq(True) &
                  ~panel.quarantined_label & ~uncertain & panel.date.lt(as_of) &
                  panel.label_window_end.le(as_of)].copy()
    today = panel[panel.date.eq(as_of) & panel.signal_eligible & ~uncertain].copy()
    if (train.empty or today.empty or train.surge_adjusted.nunique() != 2 or
            train.label_window_end.max() > as_of or
            not np.isfinite(train[FEATURES]).all().all() or
            not np.isfinite(today[FEATURES]).all().all()):
        raise ValueError("Invalid train or signal frame")
    models = {
        "logistic_score": make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)),
        "hist_gradient_boosting_score": HistGradientBoostingClassifier(
            learning_rate=.06, max_iter=100, max_leaf_nodes=15,
            min_samples_leaf=100, l2_regularization=1., early_stopping=False,
            random_state=2025),
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, model in models.items():
        model.fit(train[FEATURES], train.surge_adjusted.astype(int))
        today[name] = model.predict_proba(today[FEATURES])[:, 1]
        joblib.dump(model, out / f"asof_20261002_{name}_v58.joblib", compress=3)
    quote = prices[prices.date.eq(as_of)][["symbol", "name", "close"]]
    today = today.merge(quote, on="symbol", how="left", validate="one_to_one")
    if today.name.isna().any() or today.close.isna().any():
        raise ValueError("Missing original close or display name for signal")
    today["logistic_rank"] = today.logistic_score.rank(ascending=False, method="first").astype(int)
    today["hgb_rank"] = today.hist_gradient_boosting_score.rank(ascending=False, method="first").astype(int)
    today["mom60_rank"] = today.mom60_skip5.rank(ascending=False, method="first").astype(int)
    k = math.ceil(.10 * len(today))
    today["selected_logistic_top10"] = today.logistic_rank.le(k)
    today["signal_available_after_close"] = args.signal_date
    cols = ["signal_available_after_close", "symbol", "name", "close", "turnover20",
            "logistic_score", "logistic_rank", "hist_gradient_boosting_score",
            "hgb_rank", "mom60_skip5", "mom60_rank", "selected_logistic_top10"]
    today.sort_values("logistic_rank")[cols].to_csv(out / "candidate_rank_20261002_v58.csv", index=False)
    today[today.selected_logistic_top10].sort_values("logistic_rank")[cols].to_csv(
        out / "candidate_top10_20261002_v58.csv", index=False)
    summary = dict(as_of=args.signal_date, training_rows=len(train),
                   training_dates=train.date.nunique(),
                   latest_training_signal=str(train.date.max().date()),
                   latest_training_label_end=str(train.label_window_end.max().date()),
                   scored_candidates=len(today), logistic_top10_count=k,
                   excluded_2026_symbols=sorted(UNCERTAIN_RIGHTS),
                   scores_are_not_calibrated_probabilities=True,
                   trade_executability_not_verified=True)
    (out / "candidate_rank_summary_20261002_v58.json").write_text(
        json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
