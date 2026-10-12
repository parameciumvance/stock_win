import unittest
import numpy as np
import pandas as pd
from tpex_proxy_features import features,event_clock

class ProxyTest(unittest.TestCase):
    def frame(self,prices):
        days=pd.date_range('2023-01-01',periods=len(prices),freq='B')
        f=pd.DataFrame({'date':days,'code':'1234','primary_pool':True,'confirmed_subset':True,'type_evidence':'confirmed_ordinary','open':prices,'high':prices,'low':prices,'close':prices,'volume_shares':100})
        return days,f
    def event(self,day,status='last_close_matches',last=100,ref=90):
        return {'event_date':day.strftime('%Y-%m-%d'),'status':status,'official_last_close':last,'official_reference':ref}
    def test_dividend_quote_bridge_no_spurious_momentum(self):
        days,f=self.frame([100]*65+[90]*65);out=features(f,days,[self.event(days[65])])
        self.assertAlmostEqual(out.loc[65,'mom1'],0)
        self.assertAlmostEqual(out.loc[60,'gross_quote_return20'],0)
    def test_unknown_crossing_mask_and_later_window_recovers(self):
        days,f=self.frame([100]*65+[80]*65);out=features(f,days,[self.event(days[65],status='last_close_mismatch')])
        self.assertTrue(np.isnan(out.loc[65,'mom1']))
        self.assertTrue(out.loc[60,'label_unknown20'])
        self.assertAlmostEqual(out.loc[90,'mom20'],0)
        self.assertEqual(len(out),130)
    def test_future_event_does_not_change_past_features(self):
        days,f=self.frame([100]*65+[90]*65);event=self.event(days[65]);full=features(f,days,[event]);prefix=features(f.iloc[:64],days[:64],[event])
        np.testing.assert_allclose(full.loc[:63,'mom20'],prefix['mom20'],equal_nan=True)
    def test_duplicate_events_never_double_adjust(self):
        days,f=self.frame([100]*65+[90]*65);e=self.event(days[65]);factor,unknown=event_clock(days,[e,e]);self.assertEqual(factor[65],1);self.assertEqual(unknown[65],1)
    def test_missing_entry_is_unknown_without_dropping_pool_row(self):
        days,f=self.frame([100]*100);f['open']=f['open'].astype(object);f.loc[41,'open']='--';out=features(f,days,[])
        self.assertTrue(out.loc[40,'label_unknown20']);self.assertEqual(len(out),100)
    def test_year_boundary_warmup_and_unfinished_labels_remain_unknown(self):
        days,f=self.frame([100]*100);out=features(f,days,[])
        self.assertTrue(out.loc[:59,'breakout60_volume15'].isna().all())
        self.assertTrue(out.tail(60)['label_unknown60'].all())
        self.assertTrue(out.tail(20)['label_unknown20'].all())
    def test_missing_prior_quote_at_first_day_is_not_adjusted(self):
        days,f=self.frame([100]*100)
        factors,unknown=event_clock(days,[self.event(days[0],status='missing_prior_quote')])
        self.assertEqual(factors[0],1);self.assertEqual(unknown[0],1)
        out=features(f,days,[self.event(days[0],status='missing_prior_quote')])
        self.assertTrue(out.loc[0,'unverified_event_transition'])
        self.assertAlmostEqual(out.loc[61,'mom60'],0)

    def test_closed_market_date_is_unknown_on_next_market_day(self):
        for event_date,calendar in [('2019-08-09',['2019-08-08','2019-08-12','2019-08-13']),('2019-09-30',['2019-09-27','2019-10-01','2019-10-02'])]:
            days=pd.DatetimeIndex(calendar)
            for status in ['event_date_outside_market_calendar','last_close_matches']:
                with self.subTest(event_date=event_date,status=status):
                    e=self.event(pd.Timestamp(event_date),status=status)
                    factor,unknown=event_clock(days,[e])
                    np.testing.assert_array_equal(factor,[1,1,1])
                    np.testing.assert_array_equal(unknown,[0,1,1])

    def test_nonmarket_unknown_event_masks_crossing_labels(self):
        days,f=self.frame([100]*65+[80]*65)
        # The previous calendar date is Sunday; the event is never treated as verified.
        event_date=days[65]-pd.Timedelta(days=1)
        out=features(f,days,[self.event(event_date,status='event_date_outside_market_calendar')])
        self.assertTrue(out.loc[65,'unverified_event_transition'])
        self.assertTrue(np.isnan(out.loc[65,'mom1']))
        self.assertTrue(out.loc[60,'label_unknown20'])
        self.assertAlmostEqual(out.loc[90,'mom20'],0)

if __name__=='__main__':unittest.main()
