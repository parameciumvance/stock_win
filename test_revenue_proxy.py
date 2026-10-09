import unittest
import gzip
import hashlib
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from twse_history.revenue_proxy import parse_snapshot, build_monthly_features, attach_features, REVENUE_FEATURES
from audit_revenue_proxy import evaluate_day, SCORES, verify_flow


class RevenueProxyTests(unittest.TestCase):
    def test_regenerated_gzip_must_match_exact_frozen_csv(self):
        raw=b'date,symbol,value\n2024-01-02,2330,1.5\n'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'flow.csv.gz';p.write_bytes(gzip.compress(raw,mtime=123))
            original=hashlib.sha256(gzip.compress(raw,mtime=0)).hexdigest()
            frozen=hashlib.sha256(raw).hexdigest()
            verify_flow(p,original,frozen)
            p.write_bytes(gzip.compress(raw.replace(b'1.5',b'2.5'),mtime=123))
            with self.assertRaises(ValueError):verify_flow(p,original,frozen)

    def monthly(self):
        months = pd.period_range('2022-01', '2022-12', freq='M')
        return pd.DataFrame(dict(symbol='2330', revenue_month=months.astype(str),
                                 revenue_twd_thousands=np.arange(12)+100.,
                                 previous_month_twd_thousands=100., previous_year_twd_thousands=80.,
                                 snapshot_sha256='a'*64))

    def test_parser_source_identity_and_no_publication_time(self):
        raw = ('上市公司113年1月份(累計與當月)營業收入統計表 單位：千元 '
               '出表日期：115/10/05 全部國內上市公司合計 '
               '<table><tr><td>2330</td><td>台積電</td>' + ''.join('<td>'+x+'</td>' for x in
                ['100','90','80','11.11','25','100','80','25','無'])+'</tr></table>').encode('cp950')
        f=parse_snapshot(raw,'2024-01',0)
        self.assertEqual(f.revenue_twd_thousands.iloc[0],100)
        self.assertNotIn('published_at',f)
        with self.assertRaises(ValueError):parse_snapshot(raw,'2024-02',0)
        with self.assertRaises(ValueError):parse_snapshot(raw,'2024-01',1)

    def test_missing_month_does_not_bridge_three_month_window(self):
        m=self.monthly();m=m[m.revenue_month.ne('2022-04')]
        f=build_monthly_features(m).set_index('revenue_month')
        self.assertTrue(pd.isna(f.loc['2022-06','rev_3m_yoy']))
        self.assertTrue(np.isfinite(f.loc['2022-07','rev_3m_yoy']))
        self.assertTrue(pd.isna(f.loc['2022-07','rev_yoy_accel']))

    def test_duplicate_month_rejected(self):
        m=self.monthly()
        with self.assertRaises(ValueError):build_monthly_features(pd.concat([m,m.iloc[:1]]))

    def test_strict_next_market_day_and_no_future_join(self):
        f=build_monthly_features(self.monthly())
        # Jan 31 + 45 = Mar 17. Same-day is excluded, weekend advances to Mar 20.
        days=pd.to_datetime(['2022-03-16','2022-03-17','2022-03-20'])
        c=pd.DataFrame(dict(date=days,symbol='2330'))
        a=attach_features(c,f,days,45)
        self.assertTrue(a.loc[a.date.le('2022-03-17'),'revenue_month'].isna().all())
        self.assertEqual(a.iloc[-1].revenue_month,'2022-01')
        self.assertEqual(a.iloc[-1].proxy_available_date,pd.Timestamp('2022-03-20'))

    def test_incomplete_latest_not_replaced_and_stale_invalid(self):
        f=build_monthly_features(self.monthly())
        f.loc[f.revenue_month.eq('2022-05'),REVENUE_FEATURES]=np.nan
        days=pd.bdate_range('2022-01-01','2022-08-01')
        c=pd.DataFrame(dict(date=pd.to_datetime(['2022-07-20']),symbol='2330'))
        a=attach_features(c,f,days,45)
        self.assertEqual(a.iloc[0].revenue_month,'2022-05')
        self.assertTrue(a[REVENUE_FEATURES].isna().all().all())
        b=attach_features(c,f,days,45,max_age=20)
        self.assertTrue(b[REVENUE_FEATURES].isna().all().all())

    def test_truncated_calendar_uses_latest_available_month(self):
        f=build_monthly_features(self.monthly())
        days=pd.bdate_range('2023-01-02','2023-03-01')
        c=pd.DataFrame(dict(date=[days[0]],symbol='2330'))
        a=attach_features(c,f,days,45)
        self.assertEqual(a.iloc[0].revenue_month,'2022-10')

    def test_unknown_top_is_retained_not_filled_or_replaced(self):
        g=pd.DataFrame(dict(date=pd.to_datetime(['2024-01-02']*3),symbol=['1111','2222','3333'],
                            endpoint_target=[np.nan,.2,.1],revenue_month='2023-10',
                            proxy_available_date=pd.Timestamp('2023-12-18'),month_end=pd.Timestamp('2023-10-31'),
                            label_window_end=pd.Timestamp('2024-01-30')))
        for name in SCORES:g[name]=[3,2,1]
        row,tops=evaluate_day(g,.1)
        self.assertTrue(pd.isna(row['price_top_net_relative']))
        self.assertEqual(row['price_unknown'],1)
        self.assertEqual(set(tops.symbol),{'1111'})


if __name__=='__main__':unittest.main()
