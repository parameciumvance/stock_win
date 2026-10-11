import unittest
from tpex_type_recovery import parse_single,candidate_from_formal_rule
class TypeTests(unittest.TestCase):
    def test_exact_code_preserved(self):
        cells=['1','TW0003202008','3202','樺晟','公開發行','普通股','電子','2002/07/30','ESVUFR','']
        html='<tr>'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>'
        self.assertEqual(parse_single(html.encode('cp950'))['3202']['cfi'],'ESVUFR')
    def test_rule_does_not_confirm_cfi(self):
        self.assertEqual(candidate_from_formal_rule('1258'),'ordinary_stock_rule_candidate')
    def test_etf_not_stock_candidate(self):
        self.assertNotEqual(candidate_from_formal_rule('00718B'),'ordinary_stock_rule_candidate')
    def test_preferred_suffix(self):
        self.assertEqual(candidate_from_formal_rule('4129A'),'preferred_stock_rule_candidate')
    def test_duplicate_rejected(self):
        h='<tr>'+''.join('<td>'+c+'</td>' for c in ['1','id','3202','name','market','普通股','industry','date','ESVUFR',''])+'</tr>'
        with self.assertRaises(ValueError):parse_single((h+h).encode('cp950'))
if __name__=='__main__':unittest.main()
