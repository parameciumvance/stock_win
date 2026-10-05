"""Attach verified monthly revenue releases to post-close daily signals.

Input is a normalized *release ledger*, not an aggregate table with an assumed
month-end or statutory filing date. Every record needs its actual publication
timestamp and an archived source reference. The feature becomes available on
the first market day strictly after the release date, even if released early.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = {"symbol", "revenue_month", "revenue_twd_thousands",
            "reported_yoy_pct", "published_at", "source_url", "snapshot_sha256"}


def attach_revenue(signals: pd.DataFrame, reports: pd.DataFrame,
                   market_days: pd.DatetimeIndex) -> pd.DataFrame:
    """Return signals plus latest announced month, using no same-day release.

    Revisions of the latest month are accepted. A late correction of an older
    month cannot replace a newer revenue month already available to investors.
    Missing historical releases leave features missing, never forward inventing
    the statutory deadline as a release timestamp.
    """
    missing = REQUIRED.difference(reports.columns)
    if missing:
        raise ValueError(f"Missing release ledger columns: {sorted(missing)}")
    if not {"date", "symbol"}.issubset(signals.columns):
        raise ValueError("Signals need date and symbol")
    days = pd.DatetimeIndex(pd.to_datetime(market_days)).normalize().sort_values()
    if days.has_duplicates or days.tz is not None or len(days) == 0:
        raise ValueError("Market dates must be distinct, nonempty and timezone naive")
    s = signals.copy()
    s["date"] = pd.to_datetime(s.date, errors="raise")
    if s.date.dt.tz is not None or not s.date.dt.normalize().eq(s.date).all():
        raise ValueError("Signal dates must be local market dates")
    s["symbol"] = s.symbol.astype(str)
    if s.duplicated(["date", "symbol"]).any() or not s.date.isin(days).all():
        raise ValueError("Duplicate or off-calendar signal date/symbol")
    r = reports.copy()
    if r.empty:
        for col in ("revenue_month", "revenue_twd_thousands", "revenue_yoy",
                    "published_at", "available_date", "source_url", "snapshot_sha256"):
            s[col] = np.nan if col in ("revenue_twd_thousands", "revenue_yoy") else pd.NaT if col in ("available_date", "published_at") else None
        return s
    if r[list(REQUIRED)].isna().any().any() or (r[list(REQUIRED)].astype(str).eq("")).any().any():
        raise ValueError("Release ledger has missing required values")
    if not r.published_at.astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)").all():
        raise ValueError("published_at requires explicit timezone offset")
    r["published_at"] = pd.to_datetime(r.published_at, utc=True).dt.tz_convert("Asia/Taipei")
    r["symbol"] = r.symbol.astype(str)
    r["revenue_month"] = pd.PeriodIndex(r.revenue_month, freq="M")
    r["revenue_twd_thousands"] = pd.to_numeric(r.revenue_twd_thousands, errors="raise")
    r["reported_yoy_pct"] = pd.to_numeric(r.reported_yoy_pct, errors="raise")
    if not np.isfinite(r[["revenue_twd_thousands", "reported_yoy_pct"]]).all().all():
        raise ValueError("Nonfinite revenue or reported growth")
    if (r.revenue_twd_thousands < 0).any():
        raise ValueError("Negative monthly revenue")
    local_release_date = r.published_at.dt.tz_localize(None).dt.normalize()
    if (local_release_date <= r.revenue_month.dt.to_timestamp(how="end").dt.normalize()).any():
        raise ValueError("Release must follow the revenue month")
    if not r.source_url.astype(str).str.startswith("https://").all():
        raise ValueError("Release must have HTTPS source URL")
    if not r.snapshot_sha256.astype(str).str.fullmatch("[a-fA-F0-9]{64}").all():
        raise ValueError("Release needs archived source SHA-256")
    if r.duplicated(["symbol", "revenue_month", "published_at"]).any():
        raise ValueError("Duplicate release/revision")
    positions = days.searchsorted(local_release_date.to_numpy(), side="right")
    r["available_date"] = pd.NaT
    in_range = positions < len(days)
    r.loc[in_range, "available_date"] = days[positions[in_range]].to_numpy()
    r = r.dropna(subset=["available_date"]).sort_values(
        ["symbol", "available_date", "revenue_month", "published_at"])
    # A newer month's release wins over a subsequently published old-month edit.
    r = r[r.revenue_month.eq(r.groupby("symbol").revenue_month.cummax())]
    r = r.drop_duplicates(["symbol", "available_date"], keep="last")
    r["revenue_month"] = r.revenue_month.astype(str)
    r["revenue_yoy"] = r.reported_yoy_pct / 100
    keep = ["symbol", "available_date", "revenue_month", "revenue_twd_thousands",
            "revenue_yoy", "published_at", "source_url", "snapshot_sha256"]
    original_order = s.index
    s = s.reset_index(drop=True).assign(_row=np.arange(len(s)))
    result = pd.merge_asof(s.sort_values("date"), r[keep].sort_values("available_date"),
                           left_on="date", right_on="available_date", by="symbol",
                           direction="backward")
    result = result.sort_values("_row").drop(columns="_row")
    result.index = original_order
    assert result.loc[result.available_date.notna(), "available_date"].le(
        result.loc[result.available_date.notna(), "date"]).all()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", required=True, help="CSV with date,symbol")
    parser.add_argument("--reports", required=True, help="Verified release ledger CSV")
    parser.add_argument("--market-calendar", required=True, help="CSV with date column")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    signals = pd.read_csv(args.signals, dtype={"symbol": str})
    reports = pd.read_csv(args.reports, dtype={"symbol": str})
    days = pd.to_datetime(pd.read_csv(args.market_calendar).date)
    result = attach_revenue(signals, reports, pd.DatetimeIndex(days))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"signals={len(result)} with_revenue={int(result.revenue_month.notna().sum())}")


if __name__ == "__main__":
    main()
