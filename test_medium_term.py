import unittest
import numpy as np
import pandas as pd
from medium_term_research import endpoint_labels
from medium_term_portfolio import simulate,plan_shares,fee_for
from audit_revenue_proxy import evaluate_day


class MediumTests(unittest.TestCase):
    def test_fixed_top15_retains_unknown_highest_score(self):
        n=103;day=pd.Timestamp('2024-04-01')
        g=pd.DataFrame(dict(date=day,symbol=[str(i).zfill(4) for i in range(n)],score=np.arange(n),endpoint_target=np.arange(n)/n,revenue_month='2024-01',proxy_available_date=day,month_end=pd.Timestamp('2024-01-31'),label_window_end=pd.Timestamp('2024-07-01')))
        g.loc[n-1,'endpoint_target']=np.nan
        row,top=evaluate_day(g,.1,['score'],top_count=15)
        self.assertEqual(len(top),15);self.assertEqual(row['score_unknown'],1);self.assertTrue(np.isnan(row['score_top_net_relative']));self.assertIn(str(n-1).zfill(4),top.symbol.to_list())
    def prices(self,n=100):
        days=pd.bdate_range('2023-12-01',periods=n)
        p=pd.concat([pd.DataFrame(dict(date=days,symbol=s,universe_role=role,open=100.,close=100.,adj_open=100.,adj_close=np.arange(n)+100.)) for s,role in [('0050','benchmark'),('2330','common_stock')]],ignore_index=True)
        return days,p

    def config(self):
        return dict(commission=.001425,sell_tax=.003,slippage_each_side=.005,monthly=dict(top_n=15,capital=300000,reserve_twd=15000,per_new_name_budget=19000,price_buffer=.01,min_fee_per_ticket=20))

    def test_60_day_endpoint_and_unknown_tail(self):
        days,p=self.prices();f=endpoint_labels(p,days,60,0,0,0).set_index('date')
        self.assertEqual(f.loc[days[0],'entry_date'],days[1]);self.assertEqual(f.loc[days[0],'label_window_end'],days[60]);self.assertAlmostEqual(f.loc[days[0],'endpoint_target'],0)
        self.assertTrue(pd.isna(f.loc[days[40],'endpoint_target']))

    def test_interior_benchmark_suspension_keeps_known_endpoints(self):
        days,p=self.prices();p=p[~(p.symbol.eq('0050')&p.date.eq(days[15]))]
        f=endpoint_labels(p,days,60,0,0,0);self.assertTrue(np.isfinite(f.endpoint_target.iloc[0]))
        p=p[~(p.symbol.eq('0050')&p.date.eq(days[60]))];f=endpoint_labels(p,days,60,0,0,0);self.assertTrue(pd.isna(f.endpoint_target.iloc[0]))

    def test_min_fee_split_and_budget(self):
        c=self.config();self.assertEqual(fee_for(1001,1,.001425,20),40)
        n=plan_shares(100,19000,c);self.assertLessEqual(n*101+fee_for(n,101,c['commission'],20),19000)
        self.assertGreater((n+1)*101+fee_for(n+1,101,c['commission'],20),19000)
        self.assertEqual(plan_shares(20000,19000,c),0)

    def test_retained_name_not_sold_and_rebought(self):
        days,p=self.prices(10);p['adj_close']=100.;p['adj_open']=100.
        signals=pd.DataFrame(dict(date=[days[0],days[4]],entry_date=[days[1],days[5]],symbol='2330',signal_close=100.,score=1.))
        d,e=simulate(p,signals,'score',self.config());self.assertEqual(e.action.eq('buy').sum(),1);self.assertFalse(e.action.eq('sell').any());self.assertGreaterEqual(d.cash.min(),15000)

    def test_missing_hold_quote_is_unknown_not_forward_filled(self):
        days,p=self.prices(8);p=p[~(p.symbol.eq('2330')&p.date.eq(days[3]))]
        signals=pd.DataFrame(dict(date=[days[0]],entry_date=[days[1]],symbol='2330',signal_close=100.,score=1.))
        d,e=simulate(p,signals,'score',self.config());self.assertTrue(d.loc[d.date.eq(str(days[3].date())),'quote_proxy_nav'].isna().all());self.assertTrue(np.isfinite(d.quote_proxy_nav.iloc[-1]))

    def test_gap_over_limit_cancel_not_replace(self):
        days,p=self.prices(8);p.loc[p.symbol.eq('2330')&p.date.eq(days[1]),'open']=110.
        signals=pd.DataFrame(dict(date=[days[0]],entry_date=[days[1]],symbol='2330',signal_close=100.,score=1.))
        d,e=simulate(p,signals,'score',self.config());self.assertEqual(e.status.iloc[0],'buy_limit_not_met');self.assertTrue(d.cash.eq(300000).all());self.assertTrue(d.holdings.eq(0).all())

    def test_sale_cash_not_reused_before_tplus2_close(self):
        days,p=self.prices(10);p['adj_close']=100.;p['adj_open']=100.
        q=p[p.symbol.eq('2330')].copy();q['symbol']='9999';p=pd.concat([p,q],ignore_index=True)
        c=self.config();c['slippage_each_side']=.01;c['monthly'].update(capital=20000,reserve_twd=1000,per_new_name_budget=19000,top_n=1)
        signals=pd.DataFrame(dict(date=[days[0],days[3],days[5],days[6]],entry_date=[days[1],days[4],days[6],days[7]],symbol=['2330','9999','9999','9999'],signal_close=100.,score=1.))
        d,e=simulate(p,signals,'score',c)
        buys=e[e.status.eq('hypothetical_quote_buy')]
        self.assertEqual(list(buys.date),[str(days[1].date()),str(days[7].date())])
        self.assertTrue(e[(e.symbol.eq('9999'))&e.date.isin([str(days[4].date()),str(days[6].date())])].status.eq('cash_or_one_share_gate').all())

if __name__=='__main__':unittest.main()
