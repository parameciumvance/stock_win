import contextlib,io,json,os,pathlib,tempfile,unittest
from unittest.mock import patch
from audit_tpex_calendar import run

class CalendarCutoffTest(unittest.TestCase):
    def test_future_index_dates_filtered_but_missing_index_price_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.getcwd()
            try:
                os.chdir(tmp);pathlib.Path('configs').mkdir();pathlib.Path('deliverables/tpex_2026/raw').mkdir(parents=True)
                pathlib.Path('configs/tpex_pool_policy.json').write_text(json.dumps({'research_asof':'2026-10-02'}))
                def response(url,path):
                    month=int(url.split('date=2026/')[1][:2])
                    dates=[f'2026/{month:02}/01'] if month!=10 else ['2026/10/01','2026/10/02','2026/10/05']
                    return {'stat':'ok','tables':[{'date':f'115/{month:02}','fields':['日期','指數'],'data':[[d,'--'] for d in dates]}]}
                with patch('audit_tpex_calendar.fetch',side_effect=response),contextlib.redirect_stdout(io.StringIO()):run(2026)
                result=json.loads(pathlib.Path('deliverables/tpex_2026/calendar_audit.json').read_text())
                self.assertEqual(len(result['months']),10)
                self.assertEqual(result['months'][-1]['dates'],['2026-10-01','2026-10-02'])
                self.assertEqual(result['tpex_trading_days'],11)
                with self.assertRaises(ValueError):run(2027)
            finally:os.chdir(previous)

if __name__=='__main__':unittest.main()
