from copy import deepcopy
import unittest
from frontier_cb_material_detail import listing

def fixture():
    fields=[('firstin','true'),('b_date',''),('e_date',''),('TYPEK',''),('year','115'),('month','all'),('type',''),('co_id',''),('spoke_date',''),('spoke_time',''),('seq_no',''),('MEETING_STEP',''),('MODEL',''),('ITEM',''),('e_month','all'),('step','2'),('off','1')]
    text='<form name="t05st01_fm" action="/mops/web/ajax_t05st01" method="post">'+''.join(f'<input type="hidden" name="{k}" value="{v}">' for k,v in fields)+'<table>'
    handler="document.t05st01_fm.action='ajax_t05st01';document.t05st01_fm.seq_no.value='2';document.t05st01_fm.spoke_time.value='170827';document.t05st01_fm.spoke_date.value='20260907';document.t05st01_fm.co_id.value='9958';document.t05st01_fm.TYPEK.value='sii';openWindow(this.form ,'');"
    for subject in ['99587賣回權相關事宜','99588賣回權相關事宜','99587停止轉換等事項']:
        text+='<tr><td>9958</td><td>世紀鋼</td><td>115/09/07</td><td>17:08:27</td><td>'+subject+'</td><td><input type="button" onclick="'+handler+'"></td></tr>'
    return (text+'</table></form>').encode()

class DetailTests(unittest.TestCase):
    def test_all_rows_retained_one_exact_code_and_topic_selected(self):
        r,full=listing(fixture(),'99587');self.assertEqual(r['returned_company_row_count'],3);self.assertEqual(r['selected_detail_count'],1)
        p=r['selected_details'][0];self.assertEqual(len(p['submitted_controls']),17)
        self.assertIn('spoke_date=20260907&spoke_time=170827&seq_no=2',p['request']['data'])
        self.assertFalse(r['coverage_complete_verified']);self.assertFalse(r['absence_of_put_notice_proven'])
    def test_identity_date_click_or_action_changes_fail(self):
        for a,b in [(b"co_id.value='9958'",b"co_id.value='9959'"),(b"spoke_date.value='20260907'",b"spoke_date.value='20260908'"),(b"action='ajax_t05st01'",b"action='external'"),(b"openWindow(this.form ,'')",b'eval(unsafe)')]:
            with self.subTest(a=a),self.assertRaises(ValueError):listing(fixture().replace(a,b),'99587')
    def test_unknown_handler_statement_and_missing_control_fail(self):
        with self.assertRaises(ValueError):listing(fixture().replace(b"openWindow(this.form ,'');",b"evil();openWindow(this.form ,'');"),'99587')
        with self.assertRaises(ValueError):listing(fixture().replace(b'name="off"',b'name="new"'),'99587')
    def test_no_relevant_row_is_a_gap_not_proof_of_no_put(self):
        r,_=listing(fixture().replace('99587賣回權'.encode(),'99588賣回權'.encode()),'99587')
        self.assertEqual(r['selected_detail_count'],0);self.assertEqual(r['returned_company_row_count'],3);self.assertFalse(r['absence_of_put_notice_proven'])
if __name__=='__main__':unittest.main()
