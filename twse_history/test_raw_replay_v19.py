import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path('twse_history')
OUT = ROOT / 'output_research_v19'

class ReplayV19Tests(unittest.TestCase):
    def test_four_events_and_same_day_blocker(self):
        previous = json.loads((ROOT / 'output_research_v18/summary.json').read_text())
        current = json.loads((OUT / 'summary.json').read_text())
        self.assertEqual(current['days_accounting_complete'], {
            'equal': 27, 'momentum_60_skip5': 105,
            'logistic': 111, 'hist_gradient_boosting': 114})
        self.assertEqual(sum(current['days_accounting_complete'].values()) -
                         sum(previous['days_accounting_complete'].values()), 5)
        self.assertEqual({method: row['symbol'] for method, row in current['first_unresolved'].items()},
                         {'equal': '6625', 'momentum_60_skip5': '3563',
                          'logistic': '4571', 'hist_gradient_boosting': '4755'})
        self.assertFalse(current['stock_strategy_nav_produced'])
        audit = pd.read_csv(OUT / 'held_action_audit.csv', dtype={'symbol': str})
        for date, method, symbol, status in (
            ('2025-02-14', 'equal', '4557', 'paid_subscription_waived'),
            ('2025-06-13', 'momentum_60_skip5', '2607', 'cash_receivable_recorded'),
            ('2025-06-23', 'logistic', '6768', 'cash_receivable_recorded'),
            ('2025-06-27', 'hist_gradient_boosting', '4555', 'cash_receivable_recorded')):
            rows = audit[(audit.date == date) & (audit.method == method) & (audit.symbol == symbol)]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows.iloc[0].status, status)
            self.assertTrue(rows.iloc[0].valid_before_unresolved)
        same_day = audit[(audit.date == '2025-06-27') &
                         (audit.method == 'hist_gradient_boosting') & (audit.symbol == '4755')]
        self.assertEqual(same_day.iloc[0].status, 'unresolved')
        self.assertFalse(same_day.iloc[0].valid_before_unresolved)
        days = pd.read_csv(OUT / 'daily_accounting_status.csv')
        self.assertTrue(days.loc[~days.accounting_complete, 'nav_if_complete'].isna().all())

    def test_rights_and_revised_dividend_are_known_before_ex_date(self):
        cash = pd.read_csv(ROOT / 'dividend_evidence_v19.csv', dtype={'symbol': str})
        rights = pd.read_csv(ROOT / 'paid_rights_evidence_v19.csv', dtype={'symbol': str})
        revisions = pd.read_csv(ROOT / 'dividend_revisions_v19.csv', dtype={'symbol': str})
        self.assertFalse(cash[['symbol', 'ex_date']].duplicated().any())
        self.assertFalse(rights[['symbol', 'ex_date']].duplicated().any())
        for symbol, rate, payment in (('2607', 1.3, '2025-07-18'),
                                      ('6768', 6.17546298, '2025-07-14'),
                                      ('4555', .5, '2025-07-25')):
            row = cash[(cash.symbol == symbol) & (cash.ex_date.str.startswith('2025'))].iloc[0]
            self.assertAlmostEqual(row.cash_per_share, rate)
            self.assertEqual(row.payment_date, payment)
            self.assertLess(row.announced_date, row.ex_date)
        revised = revisions[revisions.symbol == '6768'].iloc[0]
        self.assertAlmostEqual(revised.prior_cash_per_share, 6.18491925)
        self.assertAlmostEqual(revised.revised_cash_per_share, 6.17546298)
        self.assertEqual(revised.revised_announced_date, '2025-06-06')
        rights_4557 = rights[rights.symbol == '4557'].iloc[0]
        self.assertEqual(rights_4557.policy, 'waive_paid_subscription')
        self.assertAlmostEqual(rights_4557.paid_subscription_shares_per_1000, 107.21474207)
        self.assertEqual(rights_4557.issue_price_at_ex, 100)
        self.assertLess(rights_4557.price_announcement_date, rights_4557.ex_date)

if __name__ == '__main__':
    unittest.main()
