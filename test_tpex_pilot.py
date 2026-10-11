import unittest
from tpex_classification_pilot import parse_isin
from tpex_event_pilot import detail
from tpex_source_pilot import validate_quotes

class PilotTests(unittest.TestCase):
    def test_retains_group_and_cfi(self):
        html='<tr><td colspan="7"><B>股票<B></td></tr><tr>'+''.join('<td>'+x+'</td>' for x in ['4736　泰博','TW0004736004','2023/12/22','上市','生技','ESVUFR',''])+'</tr>'
        row=parse_isin(html.encode('cp950'))['4736']
        self.assertEqual(row['group'],'股票');self.assertEqual(row['cfi'],'ESVUFR')
    def test_duplicate_isin_rejected(self):
        row='<tr>'+''.join('<td>'+x+'</td>' for x in ['4736　泰博','id','2023/12/22','上市','生技','ESVUFR',''])+'</tr>'
        with self.assertRaises(ValueError):parse_isin((row+row).encode('cp950'))
    def test_detail_required(self):
        with self.assertRaises(ValueError):detail('<table></table>','換股率')
    def test_wrong_date_rejected(self):
        with self.assertRaises(ValueError):validate_quotes({'tables':[{'date':'112/01/04','data':[['x']]}]},'2023-01-03')
    def test_empty_response_not_holiday(self):
        with self.assertRaises(ValueError):validate_quotes({'stat':'ok','tables':[]},'2023-01-03')

if __name__=='__main__':unittest.main()
