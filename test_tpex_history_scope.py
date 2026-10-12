import json,tempfile,unittest
from pathlib import Path
from tpex_history_scope import validate_source_year

class HistoricalScopeTests(unittest.TestCase):
    def test_supported_history_and_cutoff(self):
        for year in (2015,2018,2019,2020,2022): validate_source_year(year)
        for year,month in ((2014,1),(2027,1),(2026,11),(2020,13)):
            with self.assertRaises(ValueError):validate_source_year(year,month)
    def test_future_rule_cannot_authorize_past_year(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'scope.json';d=json.loads(Path('configs/tpex_history_scope.json').read_text())
            d['rule_evidence'][0]['document_date']='2020-05-01';p.write_text(json.dumps(d))
            with self.assertRaises(ValueError):validate_source_year(2015,scope_path=p)

if __name__=='__main__':unittest.main()
