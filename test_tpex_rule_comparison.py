import unittest
import numpy as np
import pandas as pd
from tpex_rule_comparison import net_quote,strict_mean,benchmark_labels
class TestRules(unittest.TestCase):
 def test_cost_formula(self):
  self.assertAlmostEqual(net_quote(.1),110*.995*(1-.001425-.003)/(100*1.005*1.001425)-1)
 def test_unknown_not_dropped(self):
  self.assertTrue(np.isnan(strict_mean(pd.Series([.1,np.nan]))))
  self.assertTrue(np.isnan(strict_mean(pd.Series([],dtype=float))))
 def test_halt_does_not_shrink_calendar(self):
  days=pd.date_range('2024-01-01',periods=4)
  b=pd.DataFrame(dict(date=days[[0,2,3]],adj_open=[100,120,130],adj_close=[100,125,140]))
  labels=benchmark_labels(b,days,2)
  self.assertTrue(np.isnan(labels.iloc[0]));self.assertAlmostEqual(labels.iloc[1],140/120-1)
if __name__=='__main__':unittest.main()
