"""Synthetic forms prove complete serialization and reject invented controls."""
import unittest
from frontier_cb_notice_forms import query_proof

def form():
    fields=dict(step='1',firstin='ture',off='1',keyword4='',code1='',TYPEK2='',checkbtn='',queryName='co_id',inpuType='co_id',TYPEK='all')
    s='<form name="fh"><input name="funcName" value="t108sb08"></form><form name="form1" method="post" action="/mops/web/ajax_t108sb08">'
    s+=''.join(f'<input name="{k}" type="hidden" value="{v}">' for k,v in fields.items())
    s+='<select name="isnew"><option value="true">最新資料</option><option value="false">歷史資料</option></select>'
    s+='<input name="co_id"><input name="year"><select name="month"><option value="">全年度</option></select>'
    s+='<select name="b_date"><option value=""></option></select><select name="e_date"><option value=""></option></select>'
    s+='''<input type="button" onclick="doAction();ajax1(document.form1,'table01');"></form><script>document.form1.step.value='1';document.form1.firstin.value='1';document.form1.action='/mops/web/ajax_'+name;</script>'''
    return s.encode()

class FormTests(unittest.TestCase):
    def test_preserves_every_field_and_full_year(self):
        p=query_proof(form(),'https://mopsov.twse.com.tw/mops/web/t108sb08','9958')
        self.assertEqual(p['data'],'step=1&firstin=1&off=1&keyword4=&code1=&TYPEK2=&checkbtn=&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id=9958&year=115&month=&b_date=&e_date=')
        self.assertFalse(p['javascript_executed']);self.assertFalse(p['notice_verified'])

    def test_changed_action_control_js_and_scope_refused(self):
        for a,b in [(b'ajax_t108sb08',b'ajax_other'),(b'name="off"',b'name="invented"'),
                    (b"firstin.value='1'",b"firstin.value='2'"),('全年度'.encode(),'九月'.encode())]:
            with self.subTest(a=a),self.assertRaises(ValueError):query_proof(form().replace(a,b),'https://mopsov.twse.com.tw/mops/web/t108sb08','9958')

    def test_wrong_issuer_and_html_base_refused(self):
        with self.assertRaises(ValueError):query_proof(form(),'https://mopsov.twse.com.tw/mops/web/t108sb08','9999')
        with self.assertRaises(ValueError):query_proof(b'<base href="https://foreign.invalid">'+form(),'https://mopsov.twse.com.tw/mops/web/t108sb08','9958')

if __name__=='__main__':unittest.main()
