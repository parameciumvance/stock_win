"""Regression checks for the v22 cash stress case and par conversion."""
import json
import unittest
from pathlib import Path

import pandas as pd

from twse_history.physical_ledger_v9 import PhysicalBook


ROOT = Path('twse_history')
OUT = ROOT / 'output_research_v22'


class ReplayV22Tests(unittest.TestCase):
    def test_foreign_gross_to_net_and_payment_day(self):
        evidence = pd.read_csv(ROOT / 'dividend_evidence_v22.csv', dtype={'symbol': str})
        policy = pd.read_csv(ROOT / 'dividend_withholding_policy_v22.csv', dtype={'symbol': str})
        am = evidence[(evidence.symbol == '6933') & (evidence.ex_date == '2025-07-16')].iloc[0]
        tax = policy.iloc[0]
        self.assertEqual((am.payment_date, am.announced_date), ('2025-10-13', '2025-07-02'))
        self.assertEqual(tax.event_id, 'exrights:6933:20250716')
        self.assertAlmostEqual(tax.withholding_rate_assumed, .30)
        audit = pd.read_csv(OUT / 'held_action_audit.csv', dtype={'symbol': str})
        rows = audit[(audit.symbol == '6933') & (audit.date == '2025-07-16') & audit.valid_before_unresolved]
        self.assertEqual(set(rows.method), {'logistic', 'hist_gradient_boosting'})
        for r in rows.itertuples():
            self.assertAlmostEqual(r.cash_receivable_gross, r.opening_shares * am.cash_per_share, places=12)
            self.assertAlmostEqual(r.withholding_assumed, r.cash_receivable_gross * .30, places=12)
            self.assertAlmostEqual(r.cash_receivable, r.cash_receivable_gross * .70, places=12)
        book = PhysicalBook()
        book.shares['6933'] = 2
        book.ex_cash('6933', pd.Timestamp('2025-07-16'), pd.Timestamp(am.payment_date),
                     am.cash_per_share * .70)
        before = book.cash
        self.assertEqual(book.pay(pd.Timestamp('2025-07-16')), 0)
        self.assertAlmostEqual(book.pay(pd.Timestamp(am.payment_date)), 2 * am.cash_per_share * .70)
        self.assertAlmostEqual(book.cash - before, 2 * am.cash_per_share * .70)
        self.assertAlmostEqual(book.receivable, 0)

    def test_par_change_and_fractional_share_conservation(self):
        proof = pd.read_csv(ROOT / 'par_change_evidence_v22.csv', dtype={'symbol': str}).iloc[0]
        self.assertEqual((proof.symbol, proof.effective_date, proof.delivery_date),
                         ('6919', '2025-07-21', '2025-07-21'))
        self.assertEqual(proof.old_par_value / proof.new_par_value, proof.new_shares_per_old)
        book = PhysicalBook()
        book.shares['6919'] = .125
        book.split('6919', proof.new_shares_per_old)
        self.assertAlmostEqual(book.shares['6919'], 1.25)
        audit = pd.read_csv(OUT / 'held_action_audit.csv', dtype={'symbol': str})
        rows = audit[(audit.symbol == '6919') & (audit.date == '2025-07-21')]
        self.assertEqual(set(rows.method), {'equal', 'momentum_60_skip5', 'logistic', 'hist_gradient_boosting'})
        self.assertTrue(rows.status.eq('verified_par_change_fractional_research_shares').all())

    def test_extension_stops_at_documented_complex_actions(self):
        before = json.loads((ROOT / 'output_research_v21/summary.json').read_text())
        now = json.loads((OUT / 'summary.json').read_text())
        self.assertEqual(now['days_accounting_complete'], {'equal': 49, 'momentum_60_skip5': 128,
                                                            'logistic': 133, 'hist_gradient_boosting': 149})
        self.assertGreater(sum(now['days_accounting_complete'].values()),
                           sum(before['days_accounting_complete'].values()))
        self.assertEqual({m: row['symbol'] for m, row in now['first_unresolved'].items()},
                         {'equal': '5222', 'momentum_60_skip5': '3665',
                          'logistic': '2836', 'hist_gradient_boosting': '6288'})
        days = pd.read_csv(OUT / 'daily_accounting_status.csv')
        self.assertEqual(days.nav_if_complete.notna().sum(), 434)
        self.assertTrue(days.loc[~days.accounting_complete, 'nav_if_complete'].isna().all())
        self.assertFalse(now['stock_strategy_nav_produced'])


if __name__ == '__main__':
    unittest.main()
