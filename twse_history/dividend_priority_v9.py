"""Prioritize cash-dividend evidence and audit documented amendments.

Reference price gaps identify event importance but are never booked as cash.
Verified terms are imported from an editable, source-linked evidence CSV.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def validate_revisions(evidence, revisions):
    required = {"symbol", "ex_date", "prior_cash_per_share", "revised_cash_per_share",
                "revised_announced_date", "prior_source_url", "revised_source_url", "reason"}
    if not required.issubset(revisions) or revisions.duplicated(["symbol", "ex_date"]).any():
        raise ValueError("Missing revision columns or duplicate keys")
    if revisions[list(required)].isna().any().any():
        raise ValueError("Incomplete revision history")
    joined = revisions.merge(evidence, on=["symbol", "ex_date"], how="left", validate="one_to_one")
    if joined.cash_per_share.isna().any():
        raise ValueError("Revision without dividend evidence")
    if not (joined.prior_cash_per_share.gt(0) &
            joined.prior_cash_per_share.ne(joined.revised_cash_per_share) &
            joined.revised_cash_per_share.eq(joined.cash_per_share) &
            joined.revised_announced_date.eq(joined.announced_date) &
            joined.revised_announced_date.le(joined.ex_date) &
            joined.revised_source_url.eq(joined.amount_source_url) &
            joined.evidence_status.str.contains("amended")).all():
        raise ValueError("Revision disagrees with imported terms or timing")
    return joined


def validate_evidence(evidence, actions):
    required = {"symbol", "ex_date", "payment_date", "cash_per_share",
                "announced_date", "amount_source_url", "payment_source_url",
                "evidence_status"}
    if not required.issubset(evidence) or evidence.duplicated(["symbol", "ex_date"]).any():
        raise ValueError("Missing columns or duplicate evidence")
    if evidence[list(required - {"symbol", "ex_date", "payment_date", "cash_per_share",
                                "announced_date"})].isna().any().any():
        raise ValueError("Missing evidence provenance")
    dates = (evidence.announced_date.le(evidence.ex_date) &
             evidence.ex_date.le(evidence.payment_date) &
             evidence.ex_date.dt.year.eq(2025))
    if not dates.all() or not evidence.cash_per_share.gt(0).all():
        raise ValueError("Invalid cash amount or dividend dates")
    event = actions[(actions.event_type.eq("exrights")) &
                    (actions.event_subtype.eq("息"))].copy()
    matched = evidence.merge(event[["symbol", "effective_date", "event_id",
                                    "official_previous_close", "official_reference"]],
                             left_on=["symbol", "ex_date"],
                             right_on=["symbol", "effective_date"],
                             how="left", validate="one_to_one")
    if matched.event_id.isna().any():
        raise ValueError("Cash evidence must match a pure official ex-dividend event")
    matched["reference_price_gap_not_cash"] = (matched.official_previous_close -
                                                matched.official_reference)
    matched["cash_minus_reference_gap"] = (matched.cash_per_share -
                                            matched.reference_price_gap_not_cash)
    if (matched.cash_minus_reference_gap.abs() > .1).any():
        raise ValueError("Cash amount differs from reference gap by over NT$0.10")
    return matched


def prioritize(inventory, actions, verified):
    cash = inventory[(inventory.event_type.eq("exrights")) &
                     (inventory.event_subtype.eq("息"))].copy()
    action = actions[["event_id", "official_previous_close", "official_reference"]]
    cash = cash.merge(action, on="event_id", validate="many_to_one")
    cash["reference_price_gap_not_cash"] = (cash.official_previous_close -
                                              cash.official_reference)
    if cash.reference_price_gap_not_cash.le(0).any():
        raise ValueError("Non-positive pure dividend reference gap")
    cash["priority_weight_not_payout"] = (cash.adjusted_unit_equivalent_shares *
                                           cash.reference_price_gap_not_cash)
    verified = verified[["symbol", "ex_date", "cash_per_share", "payment_date",
                         "evidence_status", "cash_minus_reference_gap"]]
    cash = cash.merge(verified, left_on=["symbol", "date"],
                      right_on=["symbol", "ex_date"], how="left", validate="many_to_one")
    cash["claim_in_portfolio_nav"] = False
    cash["cash_per_share_status"] = np.where(cash.cash_per_share.notna(),
                                                cash.evidence_status, "unverified")
    # One official event can affect several strategies. Aggregate only to
    # decide where manual evidence collection saves the most work.
    ranked = cash.groupby(["event_id", "date", "symbol"], as_index=False).agg(
        affected_methods=("method", "nunique"),
        aggregate_priority_weight=("priority_weight_not_payout", "sum"),
        reference_price_gap_not_cash=("reference_price_gap_not_cash", "first"),
        cash_per_share=("cash_per_share", "first"),
        cash_per_share_status=("cash_per_share_status", "first"))
    ranked = ranked.sort_values("aggregate_priority_weight", ascending=False)
    return cash, ranked


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--actions", default="twse_history/output_multiyear/corporate_actions_2024_2025.csv")
    p.add_argument("--inventory", default="twse_history/output_research_v6/held_corporate_actions_2025.csv")
    p.add_argument("--evidence", default="twse_history/dividend_evidence_v9.csv")
    p.add_argument("--revisions", default="twse_history/dividend_revisions_v9.csv")
    p.add_argument("--output", default="twse_history/output_research_v9")
    args = p.parse_args()
    a, i, e, out = [Path(x) for x in (args.actions, args.inventory, args.evidence, args.output)]
    rev = Path(args.revisions)
    out.mkdir(parents=True, exist_ok=True)
    actions = pd.read_csv(a, dtype={"symbol": str}, parse_dates=["effective_date"])
    inventory = pd.read_csv(i, dtype={"symbol": str}, parse_dates=["date"])
    evidence = pd.read_csv(e, dtype={"symbol": str},
                           parse_dates=["ex_date", "payment_date", "announced_date"])
    revisions = pd.read_csv(rev, dtype={"symbol": str},
                            parse_dates=["ex_date", "revised_announced_date"])
    verified = validate_evidence(evidence, actions)
    audited = validate_revisions(evidence, revisions)
    exposure, ranked = prioritize(inventory, actions, verified)
    if len(exposure) != 663 or exposure.event_id.nunique() != 521:
        raise ValueError("Expected held pure-cash-event coverage")
    verified.to_csv(out / "source_linked_dividend_terms.csv", index=False)
    audited.to_csv(out / "audited_dividend_revisions.csv", index=False)
    exposure.to_csv(out / "held_cash_event_priority.csv", index=False)
    ranked.to_csv(out / "cash_event_research_queue.csv", index=False)
    summary = dict(held_pure_exdiv_rows=len(exposure),
                   distinct_pure_exdiv_events=ranked.shape[0],
                   source_linked_event_count=len(verified),
                   source_linked_held_rows=int(exposure.cash_per_share.notna().sum()),
                   remaining_held_rows=int(exposure.cash_per_share.isna().sum()),
                   audited_revision_count=len(audited),
                   研究警語="優先順序使用還原價參考缺口，不是股利或策略報酬；本輪不改 NAV",
                   inputs_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (a, i, e, rev)})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
