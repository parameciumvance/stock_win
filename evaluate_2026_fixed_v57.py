"""First fixed-protocol 2026 ranking evaluation after source audits pass.

Fits v5 fixed Logistic/HGB on 2023-2025 with purged 20-day label windows;
scores the 2026 prefix once. This is an event-label ranking audit, not NAV.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from crossyear_research_2023_2025_v55 import METHODS, daily_and_summary, yearly_fold
from twse_history.research_v5 import FEATURES, feature_panel, training_frame

REFERENCE_RIGHTS_UNRESOLVED = ("3149", "4989", "6225")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path,
                   default=Path("twse_history/output_multiyear_2023_2026_asof_20261002"))
    p.add_argument("--output", type=Path, default=Path("deliverables"))
    args = p.parse_args()
    source, out = args.source, args.output
    suffix = "_2023_2026.csv.gz"
    meta = json.loads((source / "summary_2023_2026.json").read_text())
    if (meta["as_of"] != "2026-10-02" or not meta["calendar_exact_match"] or
            meta["event_audit_states"] != {"matched": sum(meta["event_audit_states"].values())}):
        raise ValueError("Official calendar or event audit did not pass")
    prices = pd.read_csv(source / ("prices_adjusted" + suffix),
                         dtype={"symbol": str}, parse_dates=["date"])
    labels = pd.read_csv(source / ("surge_labels_adjusted" + suffix),
                         dtype={"symbol": str}, parse_dates=["date", "label_window_end"])
    roles = pd.read_csv(source / ("temporal_split" + suffix),
                        dtype={"symbol": str}, parse_dates=["date"])
    calendar = pd.DatetimeIndex(sorted(prices.date.unique()))
    if len(calendar) != 905 or calendar.min() != pd.Timestamp("2023-01-03"):
        raise ValueError("Unexpected 2023-2026 market calendar")
    features = feature_panel(prices, calendar, min_turnover=10_000_000)
    panel = training_frame(features, labels, roles, [("2429", pd.Timestamp("2024-07-02"))])
    test_all, detail = yearly_fold(panel, 2026, 2023)
    if not test_all.role.eq("test_eligible").all() or not np.isfinite(test_all[FEATURES]).all().all():
        raise ValueError("Unexpected evaluation role or nonfinite features")
    # Decided from official quote/reference discontinuities before inspecting
    # 2026 model scores or stock-specific labels. The build summary already
    # exposed aggregate 2026 prevalence. Preserve the unfiltered diagnostic.
    excluded = test_all[test_all.symbol.isin(REFERENCE_RIGHTS_UNRESOLVED)].copy()
    test = test_all[~test_all.symbol.isin(REFERENCE_RIGHTS_UNRESOLVED)].copy()
    if test.empty or test.date.nunique() != test_all.date.nunique():
        raise ValueError("Exception mask unexpectedly removes evaluation dates")
    sensitivity_daily, sensitivity_summary = daily_and_summary(test_all, detail)
    detail.update(eval_rows=len(test), eval_dates=test.date.nunique(),
                  positives=int(test.surge_adjusted.sum()),
                  excluded_symbols=list(REFERENCE_RIGHTS_UNRESOLVED),
                  excluded_stock_days=len(excluded),
                  excluded_basis="Official 2026 reference-price discontinuity; rights valuation unresolved")
    daily, summary = daily_and_summary(test, detail)
    out.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out / "holdout_daily_2026_v57.csv", index=False)
    summary.to_csv(out / "holdout_summary_2026_v57.csv", index=False)
    sensitivity_summary.to_csv(out / "holdout_unfiltered_sensitivity_2026_v57.csv", index=False)
    sensitivity_daily.to_csv(out / "holdout_unfiltered_daily_2026_v57.csv", index=False)
    excluded[["fold", "date", "symbol", "surge_adjusted", *METHODS]].to_csv(
        out / "holdout_excluded_2026_v57.csv", index=False)
    test[["fold", "date", "symbol", "surge_adjusted", "label_window_end",
          *METHODS]].to_csv(out / "holdout_scores_2026_v57.csv.gz",
                             index=False, compression="gzip")
    (out / "holdout_fold_2026_v57.json").write_text(json.dumps(detail, indent=2))
    print(json.dumps(detail, indent=2))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
