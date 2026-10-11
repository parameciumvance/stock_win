import unittest
import numpy as np
from tpex_ridge_baseline import intervals
class TestIntervals(unittest.TestCase):
 def test_missing_calendar_positions_remain(self):
  x=np.ones(100)*.02;x[::3]=np.nan
  r=intervals(x,20,500,20261010)
  self.assertEqual(r['calendar_positions'],100);self.assertEqual(r['known'],66)
  self.assertAlmostEqual(r['lower_95'],.02);self.assertAlmostEqual(r['upper_95'],.02)
 def test_insufficient_pairs(self):
  self.assertEqual(intervals([np.nan]*80+[1]*10,20,100,1)['status'],'insufficient_known_pairs')
if __name__=='__main__':unittest.main()
