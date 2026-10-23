import unittest
from frontier_cb_material_sources import continuation
from frontier_cb_corporate_forms import corporate_query,current_month_query

def autoform():
    fields=[('run',''),('step','12'),('id',''),('T1','20260101'),('T2','20261023'),('co_id','9958'),('firstin','true'),('KK','2')]
    s='<form name="autoForm" action="/mops/web/ajax_t113sb04" method="post">'+''.join(f'<input type="hidden" name="{k}" value="{v}">' for k,v in fields)
    return (s+"</form><script>ajax1(document.autoForm,'div01');</script>").encode()

def corpform():
    fields=[('step','1'),('firstin','ture'),('off','1'),('keyword4',''),('code1',''),('TYPEK2',''),('checkbtn',''),('queryName','co_id'),('inpuType','co_id'),('TYPEK','all'),('co_id',''),('year','')]
    s='<form name="fh"><input name="funcName" value="t05st01"></form><form name="form1" action="/mops/web/ajax_t05st01" method="post">'
    s+=''.join(f'<input type="hidden" name="{k}" value="{v}">' for k,v in fields)
    for k in ('month','b_date','e_date'):
        s+=f'<select name="{k}"><option value="">'+('全年度' if k=='month' else '')+'</option></select>'
    s+='''<input type="button" onclick="doAction();ajax1(document.form1,'table01');"></form><script>document.form1.step.value='1';document.form1.firstin.value='1';document.form1.action='/mops/web/ajax_'+name;</script>'''
    return s.encode()

def script():return b"/* function ajax1(form1,targets) { backup } */ function ajax1(form1,targets) { var str='encodeURIComponent=1'; var es = form1.elements; str=str+'&'+es[i].name+'='+value1; var url=form1.action; xmlDoc[index].send(str); } function getVersion() {}"

class MaterialTests(unittest.TestCase):
    def test_preserves_actual_continuation_fields(self):
        r=continuation(autoform(),'9958');self.assertEqual(r['data'],'encodeURIComponent=1&run=&step=12&id=&T1=20260101&T2=20261023&co_id=9958&firstin=true&KK=2');self.assertFalse(r['source_gate_passed'])
    def test_changed_continuation_action_date_issuer_step_fails(self):
        for a,b in [(b'ajax_t113sb04',b'ajax_invented'),(b'20261023',b'20261024'),(b'9958',b'6835'),(b'value="12"',b'value="1"')]:
            with self.subTest(a=a),self.assertRaises(ValueError):continuation(autoform().replace(a,b),'9958')
    def test_duplicate_or_uninvoked_continuation_fails(self):
        with self.assertRaises(ValueError):continuation(autoform()+b'<form name="autoForm"></form>','9958')
        with self.assertRaises(ValueError):continuation(autoform().replace(b"ajax1(document.autoForm,'div01');",b''),'9958')
    def test_corporate_all15fields_and_active_prefix_for_all3issuers(self):
        for i in ('9958','6835','6874'):
            r=corporate_query(corpform(),script(),i)
            self.assertEqual(r['data'],'encodeURIComponent=1&step=1&firstin=1&off=1&keyword4=&code1=&TYPEK2=&checkbtn=&queryName=co_id&inpuType=co_id&TYPEK=all&co_id='+i+'&year=115&month=&b_date=&e_date=')
            self.assertFalse(r['source_gate_passed'])
    def test_corporate_wrong_action_scope_or_controls_fails(self):
        for a,b in [(b'ajax_t05st01',b'ajax_t113sb04'),(b'name="year"',b'name="invented"'),('全年度'.encode(),'九月'.encode())]:
            with self.subTest(a=a),self.assertRaises(ValueError):corporate_query(corpform().replace(a,b),script(),'9958')
    def test_corporate_missing_active_encoder_or_wrong_issuer_fails(self):
        with self.assertRaises(ValueError):corporate_query(corpform(),script().replace(b"encodeURIComponent=1",b"wrong"),'9958')
        with self.assertRaises(ValueError):corporate_query(corpform(),script(),'9999')
    def test_current_month_overlap_uses_actual_options_all3issuers(self):
        body=corpform().replace('全年度</option>'.encode(),'全年度</option><option value="10">10</option>'.encode())
        body=body.replace(b'<select name="b_date"><option value=""></option>',b'<select name="b_date"><option value=""></option><option value="01">1</option>')
        body=body.replace(b'<select name="e_date"><option value=""></option>',b'<select name="e_date"><option value=""></option><option value="23">23</option>')
        for issuer in ('9958','6835','6874'):
            r=current_month_query(body,script(),issuer)
            self.assertTrue(r['data'].endswith('year=115&month=10&b_date=01&e_date=23'))
        with self.assertRaises(ValueError):current_month_query(corpform(),script(),'9958')
if __name__=='__main__':unittest.main()
