"""Synthetic policy/pre-IO tampering checks for the separate notice budget."""
import copy
import unittest
from unittest.mock import patch
import frontier_cb_notices_sources as n


def policy():
    return dict(max_saved_requests=6,max_source_batches=3,workers=2,automatic_retries=0,
        prior_checkpoints={n.DOC_CHECKPOINT:'a'*64},batches=dict(forms={}),
        prior_CB_allocations=dict(first_discovery_actual=12,contract_route_actual=3,documents_actual=6,
            cumulative_CB_requests_before_phase=21,cumulative_CB_request_cap_after_phase=27,
            documents_unused_three_requests_reused=False,contract_route_unused_one_request_reused=False),
        new_allocation=dict(initial_generic_form_GETs=2,remaining_request_cap=4,remaining_batch_cap=2,all_failed_requests_count=True))

class NoticeGuardTests(unittest.TestCase):
    def test_separate_21_plus_6_budget(self):n.validate_phase_policy(policy())

    def test_drafts_or_missing_final_document_checkpoint_rejected(self):
        for change in [dict(draft=False),dict(status='draft_test'),dict(prior_checkpoints={}),
                       dict(prior_checkpoints={n.DOC_CHECKPOINT:'pending'})]:
            p=policy();p.update(change)
            with self.assertRaises(ValueError):n.validate_phase_policy(p)

    def test_limits_retry_workers_and_unreviewed_batch_refused(self):
        for change in [dict(max_saved_requests=7),dict(max_source_batches=4),dict(workers=True),
                       dict(automatic_retries=1),dict(batches=dict(forms={},queries={}))]:
            p=policy();p.update(change)
            with self.assertRaises(ValueError):n.validate_phase_policy(p)

    def test_unused_old_capacity_cannot_be_reused(self):
        p=policy();p['prior_CB_allocations']['documents_unused_three_requests_reused']=True
        with self.assertRaises(ValueError):n.validate_phase_policy(p)
        p=policy();p['new_allocation']['all_failed_requests_count']=False
        with self.assertRaises(ValueError):n.validate_phase_policy(p)

    def test_unknown_query_refused_before_any_module_or_network(self):
        with patch.object(n,'module') as shared:
            with self.assertRaises(ValueError):n.plan('unreviewed')
            shared.assert_not_called()

    def test_duplicate_json_keys_and_nonfinite_refused(self):
        for body in ['{"a":1,"a":2}','{"a":NaN}']:
            with self.assertRaises(ValueError):n.strict_json(body)

if __name__=='__main__':unittest.main()
