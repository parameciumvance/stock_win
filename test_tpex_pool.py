import unittest
from tpex_pool import classify
class PolicyTests(unittest.TestCase):
 def test_candidate_keeps_cfi_blank(self):self.assertEqual(classify('1258',{},{}),('ordinary_stock_rule_candidate',''))
 def test_preferred_never_candidate(self):self.assertNotEqual(classify('4129A',{},{} )[0],'ordinary_stock_rule_candidate')
 def test_conflict_not_overridden_by_rule(self):self.assertEqual(classify('1258',{'1258':{'group':'股票','cfi':'XXX'}},{})[0],'unresolved_conflicting_evidence')
 def test_known_nonordinary_takes_precedence(self):self.assertEqual(classify('1258',{'1258':{'group':'特別股','cfi':'EP'}},{})[0],'confirmed_nonordinary')
if __name__=='__main__':unittest.main()
