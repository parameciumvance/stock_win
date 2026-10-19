from decimal import Decimal as D,localcontext
import unittest

from settled_etf_account import Account,replay,settlement_day


class SettlementAccountTests(unittest.TestCase):
    def setUp(self):
        self.context=localcontext();self.context.__enter__().prec=40

    def tearDown(self):self.context.__exit__(None,None,None)

    def test_unpaid_dividend_is_nav_but_not_buying_cash(self):
        b=Account('0','100');b.ex_dividend('2024-01-02','2024-01-05','1')
        self.assertEqual(b.nav('10'),1100);self.assertEqual(b.spendable,0)
        trade=b.rebalance('2024-01-03','2024-01-05','10','1','0')
        self.assertEqual(trade['status'],'rejected_insufficient_spendable_cash');self.assertEqual(b.units,100)

    def test_sale_cannot_be_spent_before_settlement(self):
        b=Account('0','100');b.rebalance('2024-01-02','2024-01-04','10','0','0')
        self.assertEqual(b.cash,0);self.assertEqual(b.sale_receivable,1000);self.assertEqual(b.nav('10'),1000)
        self.assertEqual(b.rebalance('2024-01-03','2024-01-05','10','1','0')['status'],'rejected_insufficient_spendable_cash')
        b.settle('2024-01-04');self.assertEqual(b.cash,1000);self.assertEqual(b.sale_receivable,0)

    def test_purchase_is_reserved_without_double_debit(self):
        b=Account('1000');b.rebalance('2024-01-02','2024-01-04','10','1','0')
        self.assertEqual((b.cash,b.payable,b.spendable,b.nav('10')),(1000,1000,0,1000))
        b.settle('2024-01-04');self.assertEqual((b.cash,b.payable,b.nav('10')),(0,0,1000))

    def test_cost_and_post_cost_target_conserve_wealth(self):
        b=Account('300000');r=b.rebalance('2024-01-02','2024-01-04','100','0.7','0.002')
        self.assertLess(abs(b.units*100/b.nav(100)-D('.7')),D('1e-35'))
        self.assertLess(abs(b.nav(100)-(300000-D(r['cost']))),D('1e-30'))

    def test_split_changes_units_and_dividend_entitlement_once(self):
        b=Account('0','100');b.split(4)
        self.assertEqual(b.units,400);self.assertEqual(b.nav('25'),10000)
        self.assertEqual(b.ex_dividend('2025-07-21','2025-08-08','.36'),D('144'))
        b.pay_dividends('2025-08-08');self.assertEqual((b.cash,b.dividend_receivable),(144,0))

    def test_ex_date_entitlement_survives_same_day_sale(self):
        b=Account('0','100');b.ex_dividend('2024-01-02','2024-01-05','1')
        b.rebalance('2024-01-02','2024-01-04','9','0','0')
        self.assertEqual(b.units,0);self.assertEqual(b.dividend_receivable,100)

    def test_tplus2_keeps_halt_sessions_and_skips_weekends(self):
        calendar=['2025-06-10','2025-06-11','2025-06-12','2025-06-13','2025-06-16','2025-06-17','2025-06-18']
        self.assertEqual(settlement_day(calendar,'2025-06-10'),'2025-06-12')
        with self.assertRaises(ValueError):settlement_day(calendar,'2025-06-18')

    def test_missing_settlement_date_or_negative_state_fails(self):
        with self.assertRaises(ValueError):Account('-1')
        b=Account('100');b.rebalance('2024-01-02','2024-01-04','10','1','0')
        with self.assertRaisesRegex(ValueError,'Missed'):b.settle('2024-01-05')

    def test_payment_at_endofday_cannot_fund_open_and_no_queue(self):
        market=[dict(date=d,open='10',close='10') for d in ['2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08','2024-01-09']]
        decisions=[dict(date=r['date'],target='1' if i in [0,3] else '',reason='rebalance' if i in [0,3] else 'hold') for i,r in enumerate(market)]
        result=replay(market,decisions,[dict(ex_date='2024-01-03',payment_date='2024-01-05',cash_per_unit='1')],dict(date='2099-01-01',ratio=4),'2024-01-02','2024-01-09','100','0')
        self.assertEqual(result['trades'][1]['status'],'rejected_insufficient_spendable_cash')
        self.assertEqual(D(result['daily'][-1]['units']),10);self.assertEqual(D(result['daily'][-1]['bank_cash']),10)

    def test_nonmarket_payment_is_not_lost(self):
        days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08']
        market=[dict(date=d,open='10',close='10') for d in days]
        decisions=[dict(date=d,target='1' if i==0 else '',reason='rebalance' if i==0 else 'hold') for i,d in enumerate(days)]
        result=replay(market,decisions,[dict(ex_date='2024-01-05',payment_date='2024-01-06',cash_per_unit='1')],dict(date='2099-01-01',ratio=4),days[0],days[-1],'100','0')
        saturday=next(r for r in result['daily'] if r['date']=='2024-01-06')
        self.assertFalse(saturday['market_session']);self.assertEqual(D(saturday['bank_cash']),10);self.assertEqual(D(saturday['dividend_receivable']),0)

    def test_finite_target_on_unquoted_day_cannot_shift_to_later(self):
        days=['2024-01-02','2024-01-03','2024-01-04']
        market=[dict(date=d,open='' if i==0 else '10',close='' if i==0 else '10') for i,d in enumerate(days)]
        decisions=[dict(date=d,target='1' if i==0 else '',reason='rebalance' if i==0 else 'hold') for i,d in enumerate(days)]
        with self.assertRaisesRegex(ValueError,'unquoted'):replay(market,decisions,[],dict(date='2099-01-01',ratio=4),days[0],days[-1],'100','0')

    def test_entry_on_exdate_does_not_inherit_prior_holder_rights(self):
        days=['2024-01-02','2024-01-03','2024-01-04']
        market=[dict(date=d,open='10',close='10') for d in days]
        decisions=[dict(date=d,target='1' if i==0 else '',reason='rebalance' if i==0 else 'hold') for i,d in enumerate(days)]
        result=replay(market,decisions,[dict(ex_date=days[0],payment_date=days[1],cash_per_unit='1')],dict(date=days[0],ratio=4),days[0],days[-1],'100','0')
        self.assertEqual(D(result['claims'][0]['amount']),0);self.assertEqual(D(result['daily'][-1]['units']),10)


if __name__=='__main__':unittest.main()
