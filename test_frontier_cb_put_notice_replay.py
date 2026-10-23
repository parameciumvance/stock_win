from copy import deepcopy
import unittest
from frontier_cb_put_notice_replay import verify_annotation

def fixture():
    a=dict(archive_sha256='a'*64,original_controls=['99587','68351','68741'],unresolved_controls=['68741'],cases=[],source_gate_passed=False,valid_prospective_signal_date=None,orders_authorized=False,profit_edge_proven=False)
    fulls=[];records=[]
    for code in ('99587','68351'):
        name=code+'.html';a['cases'].append(dict(filename=name,bond_code=code,issuer=code[:-1],body_sha256='b'*64,observed_at_utc='2026-10-23T06:00:00+00:00',facts=[dict(exact_anchors=['future payment'])],reported_payment_date_guaranteed=False,net_amount_verified=False,current_eligibility_verified=False,historical_first_availability_verified=False))
        fulls.append(dict(filename=name,inventory=dict(body_sha256='b'*64,page_text=code+' future payment')))
        records.append(dict(request=dict(filename=name),sha256='b'*64,observed_at='2026-10-23T06:00:00+00:00'))
    return a,fulls,records
class NoticeAuditTests(unittest.TestCase):
    def test_exact_bindings_leave_all_gates_false(self):
        a,f,r=fixture();x=verify_annotation(a,f,r,'a'*64)
        self.assertEqual(x['text_anchors_verified'],2);self.assertFalse(x['source_gate_passed']);self.assertFalse(x['semantic_interpretation_automatically_verified'])
    def test_hash_observation_and_anchor_tampering_fail(self):
        a,f,r=fixture()
        for field,value in [('body_sha256','c'*64),('observed_at_utc','2026-09-04'),('facts',[dict(exact_anchors=['guaranteed net cash'])])]:
            b=deepcopy(a);b['cases'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify_annotation(b,f,r,'a'*64)
    def test_missing_control_and_changed_gap_fail(self):
        a,f,r=fixture()
        b=deepcopy(a);b['cases'].pop()
        with self.assertRaises(ValueError):verify_annotation(b,f,r,'a'*64)
        b=deepcopy(a);b['unresolved_controls']=[]
        with self.assertRaises(ValueError):verify_annotation(b,f,r,'a'*64)
    def test_expected_dates_and_gross_amounts_cannot_be_promoted(self):
        a,f,r=fixture()
        for k in ('reported_payment_date_guaranteed','net_amount_verified','current_eligibility_verified','historical_first_availability_verified'):
            b=deepcopy(a);b['cases'][0][k]=True
            with self.subTest(k=k),self.assertRaises(ValueError):verify_annotation(b,f,r,'a'*64)
    def test_signal_or_orders_cannot_be_promoted(self):
        a,f,r=fixture()
        for change in [dict(source_gate_passed=True),dict(orders_authorized=True),dict(valid_prospective_signal_date='2026-09-04')]:
            b=deepcopy(a);b.update(change)
            with self.assertRaises(ValueError):verify_annotation(b,f,r,'a'*64)
if __name__=='__main__':unittest.main()
