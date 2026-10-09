import copy
import json
import unittest
from twse_history.margin import parse,FIELDS
from twse_history.margin_features import build_features,MARGIN_FEATURES
import pandas as pd


class MarginTests(unittest.TestCase):
    def payload(self):
        return dict(stat='OK',date='20240105',tables=[dict(fields=FIELDS,notes=['次一營業日股票融資融券狀況'],
          data=[['2330','台積電','2','1','0','10','11','100','1','2','0','3','4','100','0','OX']])])

    def test_balance_identities_and_announced_flags(self):
        f=parse(json.dumps(self.payload()).encode(),'2024-01-05')
        self.assertEqual(f.finance_today.iloc[0],11)
        self.assertEqual(f.short_today.iloc[0],4)
        self.assertEqual(f.next_business_day_flags.iloc[0],'OX')

    def test_date_schema_and_balance_fail_closed(self):
        p=self.payload()
        with self.assertRaises(ValueError):parse(json.dumps(p).encode(),'2024-01-08')
        p['tables'][0]['data'][0][6]='12'
        with self.assertRaises(ValueError):parse(json.dumps(p).encode(),'2024-01-05')
        p=self.payload();p['tables'][0]['notes']=[]
        with self.assertRaises(ValueError):parse(json.dumps(p).encode(),'2024-01-05')

    def test_legal_alphanumeric_etf_not_confused_with_ordinary_stock(self):
        p=self.payload();p['tables'][0]['data'][0][0]='00753L'
        self.assertEqual(parse(json.dumps(p).encode(),'2024-01-05').symbol.iloc[0],'00753L')

    def test_policy_and_balances_used_only_next_market_day(self):
        day=pd.Timestamp('2024-01-05');days=pd.to_datetime(['2024-01-05','2024-01-08'])
        f=parse(json.dumps(self.payload()).encode(),str(day.date()))
        r=build_features(f,days)
        self.assertTrue(r.loc[r.date.eq(day),MARGIN_FEATURES].isna().all().all())
        observed=r[r.date.eq('2024-01-08')].iloc[0]
        self.assertEqual(observed.margin_source_date,day)
        self.assertEqual(observed.finance_stopped,1.)
        self.assertEqual(observed.short_stopped,1.)

    def test_missing_market_row_breaks_window_and_is_not_zero(self):
        days=pd.bdate_range('2024-01-02',periods=8)
        frames=[parse(json.dumps(dict(self.payload(),date=d.strftime('%Y%m%d'))).encode(),str(d.date()))
                for i,d in enumerate(days) if i!=3]
        r=build_features(pd.concat(frames),days).set_index('date')
        self.assertTrue(pd.isna(r.loc[days[4],'finance_stopped']))
        self.assertTrue(pd.isna(r.loc[days[6],'finance_balance_change_5d']))


if __name__=='__main__':unittest.main()
