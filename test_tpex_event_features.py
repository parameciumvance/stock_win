import unittest
import numpy as np
import pandas as pd
from tpex_event_features import institutional_five_days,revenue_acceleration,attach_revenue
class TestEventFeatures(unittest.TestCase):
 def test_five_days_excludes_current_report(self):
  days=pd.date_range('2024-01-01',periods=8);f=pd.DataFrame(dict(date=days,code='1234',total_net=[1]*5+[-1,1,1]))
  result=institutional_five_days(f,days);self.assertTrue(np.isnan(result.institutional_five_days.iloc[4]));self.assertEqual(result.institutional_five_days.iloc[5],1);self.assertEqual(result.institutional_five_days.iloc[6],0)
 def test_missing_daily_is_unknown(self):
  days=pd.date_range('2024-01-01',periods=7);f=pd.DataFrame(dict(date=days.delete(2),code='1234',total_net=1))
  self.assertTrue(np.isnan(institutional_five_days(f,days).institutional_five_days.iloc[5]))
 def test_month_gap_no_backfill(self):
  f=pd.DataFrame(dict(code='1234',month=['2023-01','2023-03'],revenue_thousands=[100,130],previous_year_thousands=[100,100]))
  self.assertTrue(revenue_acceleration(f).revenue_acceleration.isna().all())
 def test_strict_lag_boundary(self):
  days=pd.date_range('2023-03-17',periods=4);m=pd.DataFrame(dict(code=['1234'],month_end=[pd.Timestamp('2023-01-31')],revenue_acceleration=[1.],revenue_yoy=[.1]));c=pd.DataFrame(dict(date=days,code='1234'))
  r=attach_revenue(c,m,days,45);self.assertTrue(np.isnan(r.revenue_acceleration.iloc[0]));self.assertEqual(r.revenue_acceleration.iloc[1],1)
 def test_latest_incomplete_month_does_not_fallback(self):
  days=pd.date_range('2023-03-17',periods=35);m=pd.DataFrame(dict(code=['1234','1234'],month_end=pd.to_datetime(['2023-01-31','2023-02-28']),revenue_acceleration=[1.,np.nan],revenue_yoy=[.1,.2]));c=pd.DataFrame(dict(date=days,code='1234'))
  r=attach_revenue(c,m,days,45);self.assertTrue(np.isnan(r.revenue_acceleration.iloc[-1]))
if __name__=='__main__':unittest.main()
