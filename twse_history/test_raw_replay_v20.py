import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path('twse_history')
OUT = ROOT / 'output_research_v20'

class ReplayV20Tests(unittest.TestCase):
    def test_evidence_replays_without_claiming_same_day_nav(self):
        prior = json.loads((ROOT / 'output_research_v19/summary.json').read_text())
        current = json.loads((OUT / 'summary.json').read_text())
        self.assertEqual(current['days_accounting_complete'], {
            'equal': 31, 'momentum_60_skip5': 105,
            'logistic': 113, 'hist_gradient_boosting': 117})
        self.assertEqual(sum(current['days_accounting_complete'].values())-
                         sum(prior['days_accounting_complete'].values()), 9)
        self.assertEqual({m: x['symbol'] for m,x in current['first_unresolved'].items()},
                         {'equal':'6177','momentum_60_skip5':'2421',
                          'logistic':'6890','hist_gradient_boosting':'3338'})
        self.assertFalse(current['stock_strategy_nav_produced'])
        audit=pd.read_csv(OUT/'held_action_audit.csv',dtype={'symbol':str})
        for d,m,s,expected in (
            ('2025-02-19','equal','6625','paid_subscription_waived'),
            ('2025-06-16','momentum_60_skip5','3563','cash_receivable_recorded'),
            ('2025-06-24','logistic','4571','cash_receivable_recorded'),
            ('2025-06-27','hist_gradient_boosting','4755','cash_receivable_recorded')):
            rows=audit[(audit.date==d)&(audit.method==m)&(audit.symbol==s)]
            self.assertEqual(len(rows),1)
            self.assertEqual(rows.iloc[0].status,expected)
            self.assertTrue(rows.iloc[0].valid_before_unresolved)
        same_day=audit[(audit.date=='2025-06-16')&
                       (audit.method=='momentum_60_skip5')&(audit.symbol=='2421')]
        self.assertEqual(same_day.iloc[0].status,'unresolved')
        days=pd.read_csv(OUT/'daily_accounting_status.csv')
        self.assertTrue(days.loc[~days.accounting_complete,'nav_if_complete'].isna().all())

    def test_announcement_predates_action_and_preserves_components(self):
        cash=pd.read_csv(ROOT/'dividend_evidence_v20.csv',dtype={'symbol':str})
        rights=pd.read_csv(ROOT/'paid_rights_evidence_v20.csv',dtype={'symbol':str})
        self.assertFalse(cash[['symbol','ex_date']].duplicated().any())
        self.assertFalse(rights[['symbol','ex_date']].duplicated().any())
        for symbol,rate,pay in (('3563',5,'2025-07-15'),
                                ('4571',5.17960452,'2025-07-23'),
                                ('4755',3.5,'2025-07-18')):
            row=cash[cash.symbol==symbol].iloc[-1]
            self.assertAlmostEqual(row.cash_per_share,rate)
            self.assertEqual(row.payment_date,pay)
            self.assertLess(row.announced_date,row.ex_date)
        r=rights[rights.symbol=='6625'].iloc[0]
        self.assertAlmostEqual(r.paid_subscription_shares_per_1000,147.021323)
        self.assertEqual(r.issue_price_at_ex,68)
        self.assertEqual(r.payment_start,'2025-03-04')
        self.assertEqual(r.payment_end,'2025-03-10')
        self.assertLess(r.price_announcement_date,r.ex_date)
        self.assertEqual(r.policy,'waive_paid_subscription')

if __name__=='__main__':unittest.main()
