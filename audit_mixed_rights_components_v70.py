"""Audit two mixed rights events without promoting claims into spendable NAV.

The dividend decision fields were read from TWSE OpenAPI on 2026-10-04.
This is a post-event cross-check; it is not an archived as-of feed.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "deliverables"
URL = "https://openapi.twse.com.tw/v1/opendata/t187ap45_L"
DECISIONS = {
    "7610": {"cash_original": 0.5, "free_shares": 9720000,
             "total_cash": 24292728, "board_date_roc": "1150305",
             "shareholder_date_roc": "1150526", "status": "股東會確認"},
    "2464": {"cash_original": 0.5, "free_shares": 0,
             "total_cash": 103175614, "board_date_roc": "1150311",
             "shareholder_date_roc": "", "status": "董事會決議"},
}


def number(s: str) -> float:
    return float(s.replace(",", ""))


def main() -> None:
    twse = json.loads((ROOT / "twse_history/raw/exrights_2026.json").read_text())
    rows = {r[twse["fields"].index("股票代號")]: dict(zip(twse["fields"], r))
            for r in twse["data"] if r[twse["fields"].index("股票代號")] in DECISIONS}
    assert set(rows) == set(DECISIONS)
    base = pd.read_csv(OUT / "pure_rights_waiver_proxy_2026_v69.csv", dtype={"symbol": str})
    inventory = pd.read_csv(OUT / "unresolved_monthly_rights_inventory_2026_v67.csv",
                            dtype={"symbol": str})
    pending = inventory[inventory.symbol.isin(DECISIONS)].copy()
    assert len(pending) == 3 and set(pending.symbol) == set(DECISIONS)
    for x in pending.itertuples():
        match = base[(base.method.eq(x.method)) & (base.symbol.eq(x.symbol)) &
                     (base.entry_date.eq(x.entry_date))]
        assert len(match) == 1 and not match.iloc[0].gross_cash_entitlement_proxy_available
    events = []
    for symbol, decision in DECISIONS.items():
        raw = rows[symbol]
        assert raw["權/息"] == "權息"
        before, ref, dividend_ref = (number(raw[k]) for k in
                                     ("除權息前收盤價", "除權息參考價", "減除股利參考價"))
        assert ref < dividend_ref < before
        initial_share_count = decision["total_cash"] / decision["cash_original"]
        free_ratio = decision["free_shares"] / initial_share_count
        predicted_dividend_ref = (before - decision["cash_original"]) / (1 + free_ratio)
        matches = abs(predicted_dividend_ref - dividend_ref) < 0.02
        assert matches == (symbol == "7610")
        events.append({
            "symbol": symbol, "event_date": pending[pending.symbol.eq(symbol)].event_date.iloc[0],
            "reference_source": "twse_history/raw/exrights_2026.json",
            "decision_source_url": URL, "decision_snapshot_date": "2026-10-03",
            "retrieved_date": "2026-10-04", "decision_status": decision["status"],
            "board_date_roc": decision["board_date_roc"],
            "shareholder_date_roc": decision["shareholder_date_roc"],
            "initial_decision_cash_per_original_share": decision["cash_original"],
            "decision_cash_total": decision["total_cash"],
            "decision_free_share_total": decision["free_shares"],
            "derived_original_share_count": initial_share_count,
            "derived_free_shares_per_original": free_ratio,
            "preclose": before, "dividend_only_reference": dividend_ref,
            "full_exrights_reference": ref,
            "predicted_dividend_only_from_decision": predicted_dividend_ref,
            "absolute_reference_residual": abs(predicted_dividend_ref - dividend_ref),
            "decision_matches_reference_within_0_02": matches,
            "cash_payment_confirmed": False, "free_share_delivery_confirmed": False,
            "paid_subscription_terms_confirmed": False,
            "status_for_realized_return": "pending",
        })
    with (OUT / "mixed_rights_event_components_2026_v70.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=events[0]); w.writeheader(); w.writerows(events)

    claims = []
    for x in pending.itertuples():
        b = base[(base.method.eq(x.method)) & (base.symbol.eq(x.symbol)) &
                 (base.entry_date.eq(x.entry_date))]
        assert len(b) == 1
        row = b.iloc[0]
        free_ratio = next(e["derived_free_shares_per_original"] for e in events
                          if e["symbol"] == x.symbol)
        initial_cash = next(e["initial_decision_cash_per_original_share"] for e in events
                            if e["symbol"] == x.symbol)
        cash = initial_cash if x.symbol == "7610" else float("nan")
        # Display this mark for 7610 only: a claim is valued, never assumed sold.
        mark = ((row.exit_raw_open * (1 + free_ratio) + cash) / row.entry_raw_open - 1
                if x.symbol == "7610" else float("nan"))
        claims.append({"method": x.method, "symbol": x.symbol,
                       "entry_date": x.entry_date, "exit_date": x.exit_observation_date,
                       "entry_open": row.entry_raw_open, "exit_open": row.exit_raw_open,
                       "initial_decision_cash_amount": initial_cash,
                       "cash_entitlement_amount_confirmed_by_reference": cash,
                       "free_share_claim_per_original": free_ratio,
                       "free_share_claim_status": "delivery_unverified" if free_ratio else "none",
                       "cash_claim_status": "payment_unverified" if x.symbol == "7610" else "revised_amount_unknown",
                       "paid_rights_waiver_assumption": "yes_only_for_component_mark" if x.symbol == "7610" else "none",
                       "illustrative_claim_mark_return": mark,
                       "include_in_monthly_realized_proxy": False})
    pd.DataFrame(claims).to_csv(OUT / "mixed_rights_pending_claims_2026_v70.csv",
                                index=False, na_rep="")
    print(pd.DataFrame(events)[["symbol", "derived_free_shares_per_original",
                                 "predicted_dividend_only_from_decision",
                                 "dividend_only_reference", "absolute_reference_residual"]].to_string(index=False))
    print(pd.DataFrame(claims)[["method", "symbol", "illustrative_claim_mark_return"]].to_string(index=False))


if __name__ == "__main__":
    main()
