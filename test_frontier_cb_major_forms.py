import unittest
from unittest.mock import patch
from frontier_cb_major_forms import query_proof,wire_query,mask_comments
import frontier_cb_major_sources as source

def fixture():
    fields=[('step','1'),('firstin','ture'),('off','1'),('keyword4',''),('code1',''),('TYPEK2',''),('checkbtn',''),('queryName','co_id'),('inpuType','co_id'),('TYPEK','all'),('co_id',''),('T1',''),('T2','')]
    s='<form name="fh"><input name="funcName" value="t113sb04_q2"></form><form name="form1" action="/mops/web/ajax_t113sb04_q2" method="post">'
    s+=''.join(f'<input type="hidden" name="{k}" value="{v}">' for k,v in fields)
    s+='''<input type="button" onclick="doAction();ajax1(document.form1,'table01');"></form><script>document.form1.step.value='1';document.form1.firstin.value='1';document.form1.action='/mops/web/ajax_'+name;</script>'''
    return s.encode()

class MajorFormTests(unittest.TestCase):
    def test_same_complete_range_and_every_field(self):
        for issuer in ('9958','6835','6874'):
            p=query_proof(fixture(),issuer)
            self.assertEqual(p['data'],'step=1&firstin=1&off=1&keyword4=&code1=&TYPEK2=&checkbtn=&queryName=co_id&inpuType=co_id&TYPEK=all&co_id='+issuer+'&T1=20260101&T2=20261023')
            self.assertFalse(p['historical_pit_verified']);self.assertFalse(p['source_gate_passed'])

    def test_changed_action_missing_field_default_or_script_fails(self):
        for a,b in [(b'ajax_t113sb04_q2',b'ajax_other'),(b'name="off"',b'name="new"'),(b'value="ture"',b'value="true"'),(b"firstin.value='1'",b"firstin.value='0'")]:
            with self.subTest(a=a),self.assertRaises(ValueError):query_proof(fixture().replace(a,b),'9958')

    def test_wrong_issuer_and_base_or_duplicate_form_fails(self):
        with self.assertRaises(ValueError):query_proof(fixture(),'9999')
        with self.assertRaises(ValueError):query_proof(b'<base href="https://foreign.invalid">'+fixture(),'9958')
        with self.assertRaises(ValueError):query_proof(fixture()+b'<form name="form1"></form>','9958')

    def test_unknown_batch_cannot_invoke_shared_io(self):
        with patch.object(source,'module') as shared:
            with self.assertRaises(ValueError):source.plan('unreviewed')
            shared.assert_not_called()


    def test_active_ajax_prefix_and_commented_backup(self):
        script=b"/* function ajax1(form1,targets) { fake(); } */\nfunction ajax1(form1,targets) { var str='encodeURIComponent=1'; var es = form1.elements; str=str+'&'+es[i].name+'='+value1; var url=form1.action; xmlDoc[index].send(str); }\nfunction getVersion(){}"
        r=wire_query(fixture(),script,'9958')
        self.assertTrue(r['data'].startswith('encodeURIComponent=1&step=1&firstin=1&'))
        self.assertTrue(r['commented_backup_ignored'])
        with self.assertRaises(ValueError):wire_query(fixture(),script.replace(b"var str='encodeURIComponent=1';",b"var str='';"),'9958')
        with self.assertRaises(ValueError):wire_query(fixture(),script+b'function ajax1(form1,targets) {}','9958')

    def test_comment_mask_retains_urls_and_offsets(self):
        text="var url='https://host/path'; /* comment */\n// line\nfunction ajax1(){}"
        masked=mask_comments(text)
        self.assertEqual(len(masked),len(text));self.assertIn("'https://host/path'",masked)
        self.assertNotIn('comment',masked);self.assertNotIn('// line',masked)
        self.assertEqual(masked.index('function'),text.index('function'))

if __name__=='__main__':unittest.main()
