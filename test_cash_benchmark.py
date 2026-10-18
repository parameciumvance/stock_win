import copy
import unittest

import numpy as np
import pandas as pd

from cash_benchmark import audit_ledger, parse_distributions, parse_split, physical_ledger, csv12_product_matches


def fixture():
    dates = pd.bdate_range('2024-01-02','2024-01-12')
    factor = np.where(dates >= '2024-01-09',4.,1.)
    p = pd.DataFrame(dict(date=dates, open=100/factor, close=100/factor,
                          adj_open=100.,adj_close=100.,causal_factor=factor))
    dividends = [dict(ex_date='2024-01-03',payment_date='2024-01-06',cash_per_unit=2.),
                 dict(ex_date='2024-01-10',payment_date='2024-01-15',cash_per_unit=.5)]
    split=dict(date='2024-01-09',ratio=4,halt_dates=[])
    return p,dividends,split,'2024-01-02','2024-01-12',10


class LedgerTests(unittest.TestCase):
    def run_book(self):
        args=fixture();daily,claims,initial=physical_ledger(*args)
        return args,daily,claims,initial

    def test_calendar_payment_on_weekend_does_not_arrive_early(self):
        _,daily,_,_=self.run_book();d=daily.set_index('date')
        self.assertEqual(d.loc['2024-01-05','settled_cash'],0)
        self.assertEqual(d.loc['2024-01-05','dividend_receivable'],20)
        self.assertEqual(d.loc['2024-01-06','settled_cash'],20)
        self.assertEqual(d.loc['2024-01-06','paid_today'],20)
        self.assertFalse(d.loc['2024-01-06','market_session'])
        self.assertEqual(d.loc['2024-01-06','gross_wealth'],d.loc['2024-01-05','gross_wealth'])

    def test_split_changes_units_not_cash_or_receivable(self):
        _,daily,claims,_=self.run_book();d=daily.set_index('date')
        self.assertEqual(d.loc['2024-01-08','physical_units'],10)
        self.assertEqual(d.loc['2024-01-09','physical_units'],40)
        self.assertEqual(d.loc['2024-01-09','settled_cash'],20)
        self.assertEqual(d.loc['2024-01-09','gross_wealth'],d.loc['2024-01-08','gross_wealth'])
        self.assertEqual([x['gross_claim'] for x in claims],[20,20])
        self.assertEqual(d.iloc[-1].dividend_receivable,20)

    def test_exdate_initial_purchase_has_no_entitlement(self):
        p,divs,split,_,end,units=fixture()
        daily,claims,_=physical_ledger(p,divs,split,'2024-01-03',end,units)
        self.assertEqual(claims[0]['gross_claim'],0)
        self.assertEqual(daily.paid_today.sum(),0)
        self.assertEqual(claims[1]['entitled_units'],40)

    def test_future_actions_cannot_change_past_account(self):
        p,d,s,start,end,n=fixture()
        full,_,_=physical_ledger(p,d,s,start,end,n)
        short,_,_=physical_ledger(p,d,s,start,'2024-01-05',n)
        pd.testing.assert_frame_equal(full[full.date.le('2024-01-05')].reset_index(drop=True),short)

    def test_actual_missing_halt_quote_is_carried_and_flagged(self):
        p,d,s,start,end,n=fixture();s['halt_dates']=['2024-01-04']
        p.loc[p.date.eq('2024-01-04'),['open','close','adj_open','adj_close','causal_factor']]=np.nan
        daily,claims,_=physical_ledger(p,d,s,start,end,n)
        row=daily[daily.date.eq('2024-01-04')].iloc[0]
        self.assertTrue(row.stale_market_quote)
        self.assertEqual(row.last_quote_date,'2024-01-03')
        self.assertEqual(audit_ledger(p,d,s,start,end,n,daily,claims)['status'],'passed')

    def test_unknown_missing_quote_partial_quote_and_factor_tamper_rejected(self):
        args=list(fixture())
        for col,value in [('close',np.nan),('open',0),('adj_close',999),('causal_factor',np.inf)]:
            bad=args[0].copy();bad.loc[2,col]=value
            with self.assertRaises(ValueError):physical_ledger(bad,*args[1:])
        bad=args[0].copy();bad.loc[2,['open','close','adj_open','adj_close','causal_factor']]=np.nan
        with self.assertRaisesRegex(ValueError,'Unknown missing'):physical_ledger(bad,*args[1:])

    def test_missing_boundaries_and_invalid_units_rejected(self):
        p,d,s,start,end,n=fixture()
        for args in [(p.iloc[1:],d,s,start,end,n),(p,d,s,start,end,0),(p,d,s,start,end,np.nan)]:
            with self.assertRaises(ValueError):physical_ledger(*args)

    def test_duplicate_dividend_bad_terms_and_ambiguous_composite_rejected(self):
        p,d,s,start,end,n=fixture()
        for divs in [d+[d[0]],[{**d[0],'payment_date':'2024-01-01'}], [{**d[0],'cash_per_unit':-1}], [{**d[0],'ex_date':s['date']}]]:
            with self.assertRaises(ValueError):physical_ledger(p,divs,s,start,end,n)

    def test_independent_decimal_direct_formula(self):
        args,daily,claims,initial=self.run_book()
        audit=audit_ledger(*args,daily,claims)
        self.assertEqual(initial,1000)
        self.assertEqual(daily.iloc[-1].gross_wealth,1040)
        self.assertEqual(audit['calendar_days'],11)
        self.assertLess(audit['max_money_error_twd'],1e-8)

    def test_tampered_daily_account_calendar_or_entitlement_rejected(self):
        args,daily,claims,_=self.run_book()
        for column in ['settled_cash','dividend_receivable','physical_units','gross_nav','paid_today','raw_close']:
            bad=daily.copy();bad.loc[2,column]+=.1
            with self.assertRaisesRegex(ValueError,'account differs'):audit_ledger(*args,bad,claims)
        with self.assertRaisesRegex(ValueError,'calendar'):audit_ledger(*args,daily.iloc[1:],claims)
        bad=copy.deepcopy(claims);bad[0]['gross_claim']+=1
        with self.assertRaisesRegex(ValueError,'entitlement'):audit_ledger(*args,daily,bad)

    def test_no_reinvestment_or_interest(self):
        _,daily,_,_=self.run_book()
        self.assertTrue(daily[daily.date.lt('2024-01-09')].physical_units.eq(10).all())
        self.assertTrue(daily[daily.date.ge('2024-01-09')].physical_units.eq(40).all())
        self.assertTrue(daily[daily.date.ge('2024-01-06')].settled_cash.eq(20).all())


class SourceTests(unittest.TestCase):
    def test_frozen_csv_twelve_significant_digits_have_bounded_roundoff(self):
        self.assertTrue(csv12_product_matches(1.08180899048,4,4.32723596190))
        self.assertFalse(csv12_product_matches(1.08180899048,4,4.32723596290))

    def body(self):
        cells=['ETF Code','ETF Name','Ex-dividend Date','Dividend Payment Date','Cash Dividend (NT$/Per beneficiary unit)','Year Announced']
        rows=[cells,['0050','Yuanta/P-shares Taiwan Top 50 ETF','2024/01/17','2024/02/21','3.0','2024'],['0050','Yuanta/P-shares Taiwan Top 50 ETF','2024/07/16','2024/08/09','1','2024']]
        return ('<table>'+''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)+'</table>').encode()

    def test_dividend_table_keeps_physical_unit_amounts(self):
        r=parse_distributions(self.body(),2024)
        self.assertEqual([x['cash_per_unit'] for x in r],[3,1])

    def test_wrong_year_schema_issuer_missing_duplicate_or_bad_terms_fail(self):
        body=self.body()
        for bad,year in [(body,2023),(body.replace(b'ETF Code',b'code'),2024),(body.replace(b'Yuanta/P-shares',b'Other/P-shares'),2024),(body.replace(b'2024/07/16',b'2024/01/17'),2024),(body.replace(b'2024/02/21',b'2024/01/01'),2024),(body.replace(b'>3.0<',b'>-3<'),2024),(body.replace(b'>0050<',b'>006208<'),2024)]:
            with self.assertRaises(ValueError):parse_distributions(bad,year)

    def test_split_must_have_explicit_ratio_and_dates_not_price_jump(self):
        body='<table><tr><td>證券代碼0050 分割比率（分割後受益權單位數/分割前受益權單位數）：4 (6)新受益憑證上市(櫃)買賣日：114年6月18日 停止交易期間：114年6月11日至114年6月17日</td></tr></table>'.encode()
        self.assertEqual(parse_split(body)['ratio'],4)
        for bad in [body.replace(b'0050',b'006208'),body.replace('：4'.encode(),'：2'.encode()),body.replace('114年6月18日'.encode(),'114年6月19日'.encode())]:
            with self.assertRaises(ValueError):parse_split(bad)


if __name__=='__main__':unittest.main()
