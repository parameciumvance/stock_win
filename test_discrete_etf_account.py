from decimal import Decimal as D,localcontext
from fractions import Fraction as F
import unittest

from discrete_etf_account import DiscreteAccount,replay_grid
from settled_etf_account import replay


class DiscreteAccountTests(unittest.TestCase):
    def setUp(self):self.context=localcontext();self.context.__enter__().prec=40
    def tearDown(self):self.context.__exit__(None,None,None)

    def test_board_unit_buy_keeps_cash_and_includes_cost(self):
        b=DiscreteAccount('300000',1000);t=b.rebalance('2024-01-02','2024-01-04','135.6','1','.001')
        self.assertEqual(b.units,2000);self.assertEqual(b.payable,D('271471.2'));self.assertEqual(b.spendable,D('28528.8'))
        self.assertEqual(t['status'],'filled_quote_scenario')

    def test_sell_rounds_final_holdings_down_not_sale_toward_zero(self):
        b=DiscreteAccount('0',1000);b.units=D(2000)
        t=b.rebalance('2024-01-02','2024-01-04','100','.75','0')
        self.assertEqual(b.units,1000);self.assertEqual(D(t['shares_delta']),-1000)
        self.assertLess(b.units*100/b.nav(100),D('.75'))

    def test_cost_can_move_an_exact_lot_boundary_to_no_purchase(self):
        a=DiscreteAccount('100000',1000);a.rebalance('2024-01-02','2024-01-04','100','1','0');self.assertEqual(a.units,1000)
        b=DiscreteAccount('100000',1000);t=b.rebalance('2024-01-02','2024-01-04','100','1','.001')
        self.assertEqual((b.units,b.payable,b.spendable),(0,0,100000));self.assertEqual(t['status'],'rounded_no_change')

    def test_floor_is_largest_grid_position_below_post_cost_target(self):
        b=DiscreteAccount('300000',1);t=b.rebalance('2024-01-02','2024-01-04','100','.7','.002')
        self.assertEqual(b.units,2097)
        self.assertLessEqual(F(b.units)*100,F('.7')*F(b.nav(100)))
        nextq=F(b.units)+1;self.assertGreater(nextq*100,F('.7')*(300000-nextq*100*F('.002')))
        self.assertLessEqual(F(t['rounded_final_shares']),F(t['ideal_final_shares_exact']))

    def test_unpaid_dividend_cannot_fund_even_rounded_full_purchase(self):
        b=DiscreteAccount('0',1000);b.units=D(1000);b.ex_dividend('2024-01-02','2024-01-05','100')
        t=b.rebalance('2024-01-03','2024-01-05','10','1','0')
        self.assertEqual(t['status'],'rejected_insufficient_spendable_cash');self.assertEqual(b.units,1000);self.assertFalse(b.buys)

    def test_rounded_sale_proceeds_wait_for_settlement_before_rebuy(self):
        b=DiscreteAccount('0',1000);b.units=D(1000)
        b.rebalance('2024-01-02','2024-01-04','100','0','0')
        self.assertEqual((b.units,b.cash,b.sale_receivable),(0,0,100000))
        t=b.rebalance('2024-01-03','2024-01-05','100','1','0');self.assertTrue(t['status'].startswith('rejected'))
        b.settle('2024-01-04');t=b.rebalance('2024-01-04','2024-01-08','100','1','0')
        self.assertEqual(t['status'],'filled_quote_scenario');self.assertEqual((b.units,b.spendable),(1000,0))

    def test_split_preserves_grid_and_grants_postsplit_rights(self):
        b=DiscreteAccount('300000',1000);b.rebalance('2024-01-02','2024-01-04','100','.5','0');b.split(4)
        self.assertEqual(b.units,4000);self.assertEqual(b.ex_dividend('2025-07-21','2025-08-08','.36'),1440)
        with self.assertRaisesRegex(ValueError,'off-grid'):b.split('1.1')

    def test_invalid_quantity_grid_rejected(self):
        for unit in [0,-1,1.5,True]:
            with self.assertRaises(ValueError):DiscreteAccount('300000',unit)

    def test_fractional_control_matches_old_replay_through_split_and_weekend_payment(self):
        days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08','2024-01-09','2024-01-10']
        market=[dict(date=d,open='10' if i<4 else '2.5',close='10' if i<4 else '2.5') for i,d in enumerate(days)]
        decisions=[dict(date=d,target='.5' if i==0 else '.4' if i==3 else '',reason='rebalance' if i in [0,3] else 'hold') for i,d in enumerate(days)]
        events=[dict(ex_date='2024-01-04',payment_date='2024-01-06',cash_per_unit='1')];split=dict(date='2024-01-08',ratio=4)
        old=replay(market,decisions,events,split,days[0],days[-1],'1000','.001')
        self.assertEqual(replay_grid(market,decisions,events,split,days[0],days[-1],'1000','.001',None),old)


if __name__=='__main__':unittest.main()
