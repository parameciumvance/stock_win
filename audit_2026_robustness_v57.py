"""Frozen-score 2026 next-open, temporal-block and quarter diagnostics."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from audit_temporal_uncertainty_v54 import bootstrap_gap


METHODS = ("logistic", "hist_gradient_boosting", "mom60_skip5", "mom20")
PAIRS = (("logistic", "mom60_skip5"), ("logistic", "mom20"),
         ("hist_gradient_boosting", "mom60_skip5"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path,
                   default=Path("twse_history/output_multiyear_2023_2026_asof_20261002"))
    p.add_argument("--output", type=Path, default=Path("deliverables"))
    args = p.parse_args()
    out = args.output
    scores = pd.read_csv(out / "holdout_scores_2026_v57.csv.gz",
                         dtype={"symbol": str}, parse_dates=["date", "label_window_end"])
    labels = pd.read_csv(args.source / "surge_labels_adjusted_2023_2026.csv.gz",
                         usecols=["date", "symbol", "surge_adjusted", "surge_next_open",
                                  "entry_open_next_adj", "label_available"],
                         dtype={"symbol": str}, parse_dates=["date"])
    data = scores.merge(labels, on=["date", "symbol"], validate="one_to_one",
                        suffixes=("_scored", ""))
    if (len(data) != len(scores) or scores.duplicated(["date", "symbol"]).any() or
            not data.surge_adjusted_scored.eq(data.surge_adjusted).all() or
            not data.label_available.eq(True).all()):
        raise ValueError("Scored population and adjusted labels differ")
    main = pd.read_csv(out / "holdout_daily_2026_v57.csv", parse_dates=["date"])
    if len(main) != 161 or main.date.duplicated().any():
        raise ValueError("Unexpected main holdout dates")

    # The secondary target must have an actual next-day opening quote.
    valid_next = data.surge_next_open.notna() & data.entry_open_next_adj.gt(0)
    next_data = data[valid_next].copy()
    days = []
    for date, group in next_data.groupby("date", sort=True):
        k = math.ceil(.1 * len(group))
        row = dict(date=date, eligible=len(group), top_n=k,
                   base_rate=float(group.surge_next_open.mean()))
        for method in METHODS:
            row[method] = float(group.nlargest(k, method).surge_next_open.mean())
        days.append(row)
    next_daily = pd.DataFrame(days)
    if not next_daily.date.eq(main.date).all():
        raise ValueError("Secondary label dates differ from primary")
    entry_summary = dict(total_primary_rows=len(data), valid_next_open_rows=len(next_data),
                         label_flips=int(data.loc[valid_next, "surge_adjusted"].ne(
                             data.loc[valid_next, "surge_next_open"]).sum()),
                         next_open_base_rate=float(next_data.surge_next_open.mean()),
                         **{m:float(next_daily[m].mean()) for m in METHODS})
    next_daily.to_csv(out / "holdout_next_open_daily_2026_v57.csv", index=False)
    pd.DataFrame([entry_summary]).to_csv(out / "holdout_next_open_summary_2026_v57.csv", index=False)

    quarters = main.assign(quarter=main.date.dt.to_period("Q").astype(str)).groupby(
        "quarter", as_index=False).agg(days=("date", "size"),
        mean_daily_prevalence=("base_rate", "mean"),
        **{m:(m, "mean") for m in METHODS})
    quarters["logistic_minus_mom60"] = quarters.logistic - quarters.mom60_skip5
    quarters.to_csv(out / "holdout_quarters_2026_v57.csv", index=False)

    uncertainty = []
    for i, (model, rule) in enumerate(PAIRS):
        gap = (main[model] - main[rule]).to_numpy()
        for block in (10, 20, 40):
            q, p_nonpositive = bootstrap_gap(gap, block=block,
                                              repetitions=10000,
                                              seed=20261003 + 100*i + block)
            uncertainty.append(dict(comparison=f"{model} - {rule}",
                                    days=len(main), block_days=block,
                                    observed_gap=float(gap.mean()),
                                    q025=float(q[0]), q975=float(q[2]),
                                    fraction_nonpositive=p_nonpositive))
    pd.DataFrame(uncertainty).to_csv(out / "holdout_block_sensitivity_2026_v57.csv", index=False)
    print("next_open",entry_summary)
    print(quarters.to_string(index=False))
    print(pd.DataFrame(uncertainty).to_string(index=False))


if __name__ == "__main__":
    main()
