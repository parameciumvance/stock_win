import copy,unittest
from tpex_source_pilot import validate_quotes
class NumericSourceTests(unittest.TestCase):
 def doc(self):return {'tables':[{'date':'112/01/03','fields':['代號','收盤','開盤','最高','最低','成交股數','成交金額(元)'],'data':[['1258','20','20','21','19','100','2000']]}]}
 def test_nan_open_rejected(self):
  j=self.doc();j['tables'][0]['data'][0][2]='NaN'
  with self.assertRaises(ValueError):validate_quotes(j,'2023-01-03')
 def test_negative_volume_rejected_even_missing_price(self):
  j=self.doc();j['tables'][0]['data'][0][1]='--';j['tables'][0]['data'][0][5]='-1'
  with self.assertRaises(ValueError):validate_quotes(j,'2023-01-03')
 def test_infinite_amount_rejected(self):
  j=self.doc();j['tables'][0]['data'][0][6]='inf'
  with self.assertRaises(ValueError):validate_quotes(j,'2023-01-03')
 def test_missing_price_remains_unpriced(self):
  j=self.doc();j['tables'][0]['data'][0][1]='--'
  self.assertEqual(validate_quotes(j,'2023-01-03')['priced_rows'],0)
if __name__=='__main__':unittest.main()
