import copy,gzip,json,unittest
from pathlib import Path
from tpex_flow_pilot import parse,source_table,OUTPUT_COLUMNS
class LegacyFlowTests(unittest.TestCase):
 def setUp(self):
  self.date='2015-01-05';self.doc=json.loads(gzip.decompress(Path('tests/fixtures/tpex_institutional_20150105.json.gz').read_bytes()))
 def row(self):return self.doc['tables'][1]['data'][0]
 def test_real_sources_counts_and_totals(self):
  for date,expected in [('2015-01-05',372),('2018-01-02',475)]:
   doc=json.loads(gzip.decompress(Path('tests/fixtures/tpex_institutional_'+date.replace('-','')+'.json.gz').read_bytes()));f=parse(doc,date)
   self.assertEqual(len(f),expected);self.assertEqual(list(f.columns),OUTPUT_COLUMNS)
   self.assertTrue((f.foreign_net+f.trust_net+f.dealer_net==f.total_net).all());self.assertEqual(f.iloc[0].code,'006201')
 def test_buy_sell_mismatch_rejected(self):
  self.row()[2]='1'
  with self.assertRaisesRegex(ValueError,'Buy-sell'):parse(self.doc,self.date)
 def test_dealer_subtotal_rejected(self):
  self.row()[8]='0'
  with self.assertRaisesRegex(ValueError,'Subtotal'):parse(self.doc,self.date)
 def test_total_rejected(self):
  self.row()[15]='0'
  with self.assertRaisesRegex(ValueError,'Total'):parse(self.doc,self.date)
 def test_duplicate_rejected(self):
  self.doc['tables'][1]['data'].append(copy.deepcopy(self.row()))
  with self.assertRaisesRegex(ValueError,'duplicate'):parse(self.doc,self.date)
 def test_schema_and_extra_tables_rejected(self):
  for change in ['field','table']:
   d=copy.deepcopy(self.doc)
   if change=='field':d['tables'][1]['fields'][2]='買進張數'
   else:d['tables'].append(copy.deepcopy(d['tables'][1]))
   with self.assertRaises(ValueError):parse(d,self.date)
 def test_count_and_wrong_date_rejected(self):
  self.doc['tables'][1]['totalCount']-=1
  with self.assertRaises(ValueError):parse(self.doc,self.date)
  with self.assertRaises(ValueError):parse(self.doc,'2015-01-06')
 def test_empty_placeholder_location_irrelevant(self):
  expected=parse(self.doc,self.date);self.doc['tables'].reverse()
  self.assertTrue(expected.equals(parse(self.doc,self.date)))
if __name__=='__main__':unittest.main()
