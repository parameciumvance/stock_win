import unittest
from unittest.mock import patch
import frontier_cb_notice_search_sources as n

def body():
    s='<form name="autoForm1" method="post" action="/mops/web/ajax_t198sb04">'
    s+=''.join(f'<input name="{k}" value="{v}">' for k,v in [('run',''),('firstin','true'),('TYPEK','all'),('step','9')])
    return (s+"</form><script>ajax1(document.autoForm1,'search');</script>").encode()

class DynamicGuardTests(unittest.TestCase):
    def test_literal_post_preserves_blank_and_declarations(self):
        r=n.dynamic_request(body(),'https://mopsov.twse.com.tw/mops/web/t198sb04_q1')
        self.assertEqual(r,dict(filename='pre_maturity_search_controls.html',url='https://mopsov.twse.com.tw/mops/web/ajax_t198sb04',method='POST',data='run=&firstin=true&TYPEK=all&step=9'))

    def test_action_method_controls_or_script_tampering_fails(self):
        for a,b in [(b'method="post"',b'method="get"'),(b'ajax_t198sb04',b'ajax_guessed'),(b'value="9"',b'value="1"'),(b"autoForm1,'search'",b"autoForm1,'other'")]:
            with self.subTest(a=a),self.assertRaises(ValueError):n.dynamic_request(body().replace(a,b),'https://mopsov.twse.com.tw/mops/web/t198sb04_q1')

    def test_no_unknown_adaptive_query_before_form_review(self):
        with patch.object(n,'module') as m:
            with self.assertRaises(ValueError):n.plan('unreviewed')
            m.assert_not_called()

    def test_budget_and_checkpoint_mandatory(self):
        p=dict(prior_checkpoints={n.CHECKPOINT:'a'*64},max_saved_requests=7,max_source_batches=3,workers=2,automatic_retries=0,request_ledger=dict(prior_CB_actual_requests=26,new_phase_cap=7,cumulative_CB_cap=33,prior_unused_one_reused=False),batches=dict(controls={}))
        n.validate_policy(p)
        for k,v in [('max_saved_requests',8),('prior_checkpoints',{}),('workers',True),('automatic_retries',1)]:
            with self.subTest(k=k),self.assertRaises(ValueError):n.validate_policy(dict(p,**{k:v}))

if __name__=='__main__':unittest.main()
