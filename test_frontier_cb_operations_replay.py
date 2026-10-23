import unittest
from unittest.mock import patch
from copy import deepcopy
from frontier_cb_operations_replay import calendar_request,verify_annotation
import frontier_cb_operations_sources as source

def calendar_fixture():
    body=b'<form id="form" data-api="/holidaySchedule/holidaySchedule"><input name="date" data-date="b:2021,e:1,f:Y"></form>'
    report=b'''$form.data("api"); `${cfg.apiHost.rwd}/${cfg.lan}${a}`; o.response="json"; $.getJSON(s,o,; String(i.val())+String(v.val()).padStart(2,"0")+String(m.val()).padStart(2,"0")'''
    main=b'let cfg={env:"prod",lan:"zh",apiHost:{rwd:"/rwd",rwdDev:"/rwd"}}'
    return body,report,main

def annotation_fixture():
    names=['kgi_service_closures.html','landbank_service_closures.html','tpex_bond_operations.html','tdcc_redemption_principles.pdf']
    a=dict(documents=[dict(filename=n,body_sha256='a'*64,observed_at='now',facts=[dict(anchors=['actual terms'])],semantic_interpretation_automatically_verified=False) for n in names],source_gate_passed=False,current_broker_acceptance_verified=False,calendar_annual_data_verified=False,actual_net_amount_verified=False,valid_prospective_signal_date=None,orders_authorized=False)
    fulls=[dict(filename=n,inventory=dict(page_text='actual terms')) for n in names]
    summaries=[dict(filename=n,body_sha256='a'*64,observed_at='now') for n in names]
    return a,fulls,summaries

class OperationTests(unittest.TestCase):
    def test_calendar_url_uses_all_three_actual_declarations(self):
        r=calendar_request(*calendar_fixture());self.assertEqual(r['request']['url'],'https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date=20260101&response=json');self.assertFalse(r['javascript_executed'])
    def test_wrong_api_field_prefix_or_year_format_fails(self):
        args=calendar_fixture()
        for idx,old,new in [(0,b'/holidaySchedule/holidaySchedule',b'/invented'),(0,b'f:Y',b'f:M'),(1,b'o.response="json"',b'o.response="html"'),(2,b'rwd:"/rwd"',b'rwd:"/test"')]:
            changed=list(args);changed[idx]=changed[idx].replace(old,new)
            with self.subTest(idx=idx,old=old),self.assertRaises(ValueError):calendar_request(*changed)
    def test_general_rules_do_not_prove_account_eligibility(self):
        a,f,s=annotation_fixture();r=verify_annotation(a,f,s)
        self.assertEqual(r['text_anchors_verified'],4);self.assertFalse(r['current_broker_acceptance_verified']);self.assertFalse(r['source_gate_passed'])
    def test_wrong_reference_time_hash_quote_and_promoted_gate_fail(self):
        a,f,s=annotation_fixture()
        for mutate in [lambda x:x['documents'][0].update(observed_at='past'),lambda x:x['documents'][0].update(body_sha256='b'*64),lambda x:x['documents'][0]['facts'][0].update(anchors=['invented']),lambda x:x.update(current_broker_acceptance_verified=True)]:
            b=deepcopy(a);mutate(b)
            with self.assertRaises(ValueError):verify_annotation(b,f,s)
    def test_missing_reference_cannot_be_silently_dropped(self):
        a,f,s=annotation_fixture();a['documents'].pop()
        with self.assertRaises(ValueError):verify_annotation(a,f,s)
    def test_unknown_adaptive_batch_fails_before_shared_io(self):
        with patch.object(source,'module') as shared:
            with self.assertRaises(ValueError):source.plan('unreviewed')
            shared.assert_not_called()
if __name__=='__main__':unittest.main()
