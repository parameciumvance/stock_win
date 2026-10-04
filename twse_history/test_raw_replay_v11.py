import unittest

import numpy as np
import pandas as pd

from .raw_replay_v11 import load_selections, tradable


class RawReplayTests(unittest.TestCase):
    def test_prior_signal_date_and_stable_tie_order(self):
        scores = pd.DataFrame(dict(date=pd.to_datetime(["2024-12-31"] * 3),
                                   symbol=["A", "B", "C"], mom60_skip5=[1., 1., 0.],
                                   logistic=[.8, .8, .1], hist_gradient_boosting=[.8, .8, .1]))
        counts = pd.DataFrame(dict(signal_date=pd.to_datetime(["2024-12-31"] * 12),
                                   fill_date=pd.to_datetime([f"2025-{m:02d}-02" for m in range(1, 13)]),
                                   candidates=[3] * 12, top_k=[1] * 12))
        selections, rows = load_selections(scores, counts)
        self.assertEqual(selections[pd.Timestamp("2025-01-02")]["logistic"], ["A"])
        self.assertEqual(selections[pd.Timestamp("2025-01-02")]["equal"], ["A", "B", "C"])
        self.assertTrue((rows.signal_date < rows.fill_date).all())
        with self.assertRaisesRegex(ValueError, "counts or dates"):
            load_selections(scores, counts.assign(candidates=4))

    def test_lock_proxy_blocks_but_keeps_missing_quote_explicit(self):
        self.assertEqual(tradable(None, 10, "buy"), (False, "missing_quote"))
        self.assertEqual(tradable(dict(open=11, high=11, low=11, volume=100), 10, "buy"),
                         (False, "possible_limit_up"))

    def test_completed_cash_ledger_and_blocker_quarantine(self):
        root = "twse_history/output_research_v11/"
        trades = pd.read_csv(root + "raw_order_diagnostics.csv")
        days = pd.read_csv(root + "daily_accounting_status.csv")
        events = pd.read_csv(root + "held_action_audit.csv")
        selected = pd.read_csv(root + "selected_symbols.csv")
        self.assertEqual(len(days), 243 * 4)
        self.assertEqual(selected.fill_date.nunique(), 12)
        self.assertEqual(days[days.accounting_complete].shape[0], 107)
        self.assertTrue(days.loc[~days.accounting_complete, "nav_if_complete"].isna().all())
        self.assertTrue((days.cash_if_complete.dropna() >= -1e-9).all())
        first = trades[trades.valid_before_unresolved & trades.status.eq("filled")]
        buys = first[first.side.eq("buy")]
        sells = first[first.side.eq("sell")]
        self.assertTrue(np.allclose(buys.cash_delta,
                                    -buys.shares * buys.raw_open * 1.001 * 1.001425,
                                    atol=1e-10))
        self.assertTrue(np.allclose(sells.cash_delta,
                                    sells.shares * sells.raw_open * .999 * (1 - .001425 - .003),
                                    atol=1e-10))
        opening = events[(events.date == "2025-01-06") & events.symbol.eq(6658)]
        self.assertEqual(set(opening.method), {"equal", "logistic"})
        self.assertTrue(opening.status.eq("paid_subscription_waived").all())
        self.assertTrue(opening.valid_before_unresolved.all())
        self.assertTrue(opening.cash_receivable.isna().all())
        self.assertTrue(opening.issue_price_at_ex.eq(65).all())
        self.assertTrue((opening.waived_subscription_shares > 0).all())
        self.assertEqual(days[(days.method == "equal") & days.accounting_complete].date.max(), "2025-01-08")

    def test_revised_price_never_leaks_into_ex_date(self):
        proof = pd.read_csv("twse_history/paid_rights_evidence_v11.csv", dtype={"symbol": str})
        self.assertEqual(set(proof.symbol), {"6658", "6438", "8033"})
        stock = proof.set_index("symbol").loc["6658"]
        self.assertEqual(stock.issue_price_at_ex, 65)
        self.assertEqual(stock.revised_price, 60)
        self.assertGreater(stock.revised_announcement_date, stock.ex_date)


if __name__ == "__main__":
    unittest.main()
