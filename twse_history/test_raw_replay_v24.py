"""Point-in-time FX, distribution claims, successor shares, and NAV gate."""
import json
import unittest
from pathlib import Path

import pandas as pd

from twse_history.corporate_claims_v24 import BonusClaim, ClaimBook, FxCashClaim
from twse_history.physical_ledger_v9 import PhysicalBook


ROOT = Path('twse_history')
OUT = ROOT / 'output_research_v24'


class ReplayV24Tests(unittest.TestCase):
    def test_fx_revalues_only_from_available_close_then_issuer_notice(self):
        proof = pd.read_csv(ROOT / 'combined_distribution_evidence_v24.csv', dtype={'symbol': str})
        c = proof[proof.symbol.eq('3665')].iloc[0]
        rates = pd.read_csv(ROOT / 'fx_usdtwd_cbc_v24.csv', parse_dates=['date', 'available_from_date'])
        available = dict(zip(rates.available_from_date, rates.ntd_per_usd))
        claim = FxCashClaim('3665', 2., c.usd_total / c.shares_entitled,
                            pd.Timestamp(c.cash_payment_date), c.final_twd_per_share,
                            pd.Timestamp(c.final_fx_effective_date))
        book = PhysicalBook()
        claims = ClaimBook()
        claims.add_fx(claim)
        starting_cash = book.cash
        self.assertAlmostEqual(claims.fx_value(pd.Timestamp('2025-07-17'), available),
                               2 * claim.usd_per_share * 29.416)
        self.assertAlmostEqual(claims.fx_value(pd.Timestamp('2025-08-12'), available),
                               2 * claim.usd_per_share * available[pd.Timestamp('2025-08-12')])
        self.assertAlmostEqual(claims.fx_value(pd.Timestamp('2025-08-13'), available),
                               2 * c.final_twd_per_share)
        self.assertEqual(claims.settle_fx(book, pd.Timestamp('2025-08-21')), 0)
        self.assertEqual(book.cash, starting_cash)
        self.assertAlmostEqual(claims.settle_fx(book, pd.Timestamp('2025-08-22')),
                               2 * c.final_twd_per_share)
        self.assertEqual(claims.fx_cash, [])

    def test_bonus_shares_claim_until_delivery(self):
        claims, book = ClaimBook(), PhysicalBook()
        book.shares['2836'] = 1.25
        claims.add_bonus(BonusClaim('2836', .0375, pd.Timestamp('2025-08-29')))
        self.assertAlmostEqual(claims.bonus_value({'2836': 10.}), .375)
        self.assertEqual(claims.deliver_bonus(book, pd.Timestamp('2025-08-28')), [])
        self.assertAlmostEqual(book.shares['2836'], 1.25)
        self.assertEqual(len(claims.deliver_bonus(book, pd.Timestamp('2025-08-29'))), 1)
        self.assertAlmostEqual(book.shares['2836'], 1.2875)
        self.assertEqual(claims.bonus, [])

    def test_conversion_precedes_successor_quote_and_delisting(self):
        proof = pd.read_csv(ROOT / 'share_conversion_evidence_v24.csv', dtype=str).iloc[0]
        self.assertEqual((proof.predecessor, proof.successor, proof.conversion_date),
                         ('6288', '3717', '2025-08-15'))
        audit = pd.read_csv(OUT / 'held_action_audit.csv', dtype={'symbol': str})
        rows = audit[audit.status.eq('verified_successor_delivered_tradeable')]
        self.assertEqual(set(rows.method), {'equal', 'logistic', 'hist_gradient_boosting'})
        self.assertTrue(rows.date.eq('2025-08-15').all())

    def test_free_stock_is_receivable_until_published_delivery(self):
        events = pd.read_csv(OUT / 'held_action_audit.csv', dtype={'symbol': str})
        cases = [('1519', '2025-07-25', '2025-08-29', 'cash_receivable_bonus_pending'),
                 ('2250', '2025-08-25', '2025-09-26', 'cash_receivable_bonus_pending'),
                 ('2364', '2025-08-28', '2025-11-21', 'bonus_only_receivable_pending')]
        for symbol, ex, delivery, pending in cases:
            on_ex = events[events.symbol.eq(symbol) & events.date.eq(ex)]
            self.assertGreater(len(on_ex), 0)
            self.assertTrue(on_ex.status.eq(pending).all())
            self.assertTrue(on_ex.bonus_receivable_shares.gt(0).all())
            self.assertTrue(on_ex.bonus_delivery_date.eq(delivery).all())
            on_delivery = events[events.symbol.eq(symbol) & events.date.eq(delivery)]
            self.assertEqual(len(on_delivery), len(on_ex))
            self.assertTrue(on_delivery.status.eq('bonus_shares_delivered_tradeable').all())

    def test_revised_dividends_use_pre_ex_rate(self):
        evidence = pd.read_csv(ROOT / 'dividend_evidence_v24.csv', dtype={'symbol': str})
        for symbol, rate, ex in [('6873', 5.25940226, '2025-04-01'),
                                 ('3004', 3.01040065, '2025-04-01'),
                                 ('5225', 10.39433232, '2025-03-27')]:
            row = evidence[evidence.symbol.eq(symbol) & evidence.ex_date.eq(ex)].iloc[0]
            self.assertAlmostEqual(row.cash_per_share, rate)
            self.assertLess(row.announced_date, row.ex_date)

    def test_partial_replay_does_not_publish_year_performance(self):
        old = json.loads((ROOT / 'output_research_v23/summary.json').read_text())
        now = json.loads((OUT / 'summary.json').read_text())
        self.assertGreater(sum(now['days_accounting_complete'].values()),
                           sum(old['days_accounting_complete'].values()))
        self.assertFalse(now['stock_strategy_nav_produced'])
        days = pd.read_csv(OUT / 'daily_accounting_status.csv')
        self.assertTrue(days.loc[~days.accounting_complete, 'nav_if_complete'].isna().all())
        self.assertEqual(days.nav_if_complete.count(), 485)


if __name__ == '__main__':
    unittest.main()
