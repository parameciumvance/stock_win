"""Second, fixed-parameter nonlinear relative-return baseline; research only."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_squared_error

from audit_relative_return_model_v76 import FEATURES, OUT, day_metrics, prep


def model():
    # Structural settings fixed to the earlier surge-classifier baseline;
    # no grid search and no choice based on 2026 returns.
    return HistGradientBoostingRegressor(learning_rate=.06, max_iter=100,
                                        max_leaf_nodes=15, min_samples_leaf=100,
                                        l2_regularization=1., early_stopping=False,
                                        random_state=2025)


def main():
    data = prep()
    rows, pred2026, all_scores = [], None, []
    for year in (2024, 2025, 2026):
        start, end = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
        train = data[data.date.lt(start) & data.label_window_end.lt(start)]
        test = data[data.date.ge(start) & data.date.lt(end)].copy()
        assert len(train) > 10_000 and train.label_window_end.max() < start
        tree = model().fit(train[FEATURES], train.relative_return20)
        test["predicted_relative20"] = tree.predict(test[FEATURES])
        all_scores.append(test[["date", "symbol", "predicted_relative20",
                                "relative_return20"]].assign(fold=year))
        d = day_metrics(test, str(year))
        rows.append(dict(fold=year, train_rows=len(train), eval_rows=len(test),
                         eval_days=len(d), rmse=math.sqrt(mean_squared_error(
                             test.relative_return20, test.predicted_relative20)),
                         train_mean_baseline_rmse=math.sqrt(mean_squared_error(
                             test.relative_return20,
                             np.full(len(test), train.relative_return20.mean()))),
                         mean_daily_rank_ic=float(d.rank_ic.mean()),
                         tree_top15_relative20=float(d.predicted_relative20_top15_mean.mean()),
                         mom_top15_relative20=float(d.mom60_skip5_top15_mean.mean()),
                         universe_relative20=float(d.population_mean.mean())))
        if year == 2026:
            pred2026 = test[["date", "symbol", "predicted_relative20",
                             "relative_return20"]].copy()
    assert pred2026 is not None
    pd.DataFrame(rows).to_csv(OUT / "relative_return_tree_folds_v77.csv",index=False)
    pd.concat(all_scores, ignore_index=True).to_csv(
        OUT / "relative_return_tree_scores_v77.csv.gz", index=False, compression="gzip")
    comparison = pd.read_csv(OUT / "top15_300k_selections_2026_v74.csv",
                             dtype={"symbol": str}, parse_dates=["signal_date"])
    # January signal occurred on 2025-12-31, with the same pre-2026 purged fit.
    train = data[data.date.lt(pd.Timestamp("2026-01-01")) &
                 data.label_window_end.lt(pd.Timestamp("2026-01-01"))]
    jan = data[data.date.eq(pd.Timestamp("2025-12-31"))].copy()
    jan["predicted_relative20"] = model().fit(train[FEATURES],
                                               train.relative_return20).predict(jan[FEATURES])
    regression = pd.concat([jan[["date", "symbol", "predicted_relative20",
                                 "relative_return20"]], pred2026], ignore_index=True)
    regression = regression.rename(columns={"date": "signal_date"})
    joined = comparison.merge(regression, on=["signal_date", "symbol"],
                              how="left", validate="many_to_one")
    assert len(joined) == len(comparison) and joined.predicted_relative20.notna().all()
    joined["pass_positive_relative_pred"] = joined.predicted_relative20.gt(0)
    joined["gate_status"] = "diagnostic_only_no_orders_changed"
    joined.to_csv(OUT / "top15_tree_gate_diagnostic_2026_v77.csv", index=False)
    summary = joined.groupby(["method", "pass_positive_relative_pred"],as_index=False).agg(
        n=("symbol", "size"), mean_relative20=("relative_return20", "mean"))
    summary.to_csv(OUT / "top15_tree_gate_summary_2026_v77.csv", index=False)
    monthly = pd.DataFrame([dict(method=m, signal_date=str(d.date()),
                                 selected=len(g), passing=int(g.pass_positive_relative_pred.sum()),
                                 all_mean_relative20=float(g.relative_return20.mean()),
                                 passing_mean_relative20=float(
                                     g.loc[g.pass_positive_relative_pred, "relative_return20"].mean()))
                            for (m,d),g in joined.groupby(["method","signal_date"],sort=True)])
    monthly.to_csv(OUT / "top15_tree_gate_monthly_2026_v77.csv", index=False)
    meta=dict(model="HistGradientBoostingRegressor, prior classifier structural settings",
              target="20 market-day adjusted close relative 0050",
              activation="none", independently_untouched=False, tradeable_nav=False)
    (OUT / "relative_return_tree_meta_v77.json").write_text(json.dumps(meta,indent=2))
    print(pd.DataFrame(rows).to_string(index=False))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
