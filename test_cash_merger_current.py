"""Current-status index replay preserves broad notices and fails closed."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cash_merger_current as current
from cash_merger_current import replay_indices, require_successful_indices
from test_corporate_announcement_index import body, row


def fixture():
    queries = [dict(filename=f'{issuer}.json', issuer=issuer, category='M00',
                    start='2026-09-18', end='2026-10-21') for issuer in ['6674', '2324']]
    bodies = {'6674.json': body([row(AN_CODE='M01', SUBJECT='無關財務公告'),
                                row(sequence='2', AN_CODE='M11', SUBJECT='終止或修正合併案')]),
              '2324.json': body([row(issuer='2324', AN_CODE='M99', SUBJECT='其他類別')])}
    return queries, bodies


class CurrentMergerReplayTests(unittest.TestCase):
    def test_unrelated_and_cancel_notices_preserved_without_status_claim(self):
        full, summary = replay_indices(*fixture())
        self.assertEqual([r['original_fields']['AN_CODE'] for r in full['6674']['rows']], ['M01', 'M11'])
        self.assertEqual(len(summary['returned_announcements']), 3)
        self.assertEqual(summary['returned_announcements'][0]['subject'], '無關財務公告')
        for key in ('title_filter_performed', 'current_transaction_status_verified', 'current_tradability_verified',
                    'no_later_notice_proven', 'notice_window_verified', 'payment_date_verified',
                    'contractual_cash_claim_verified', 'cash_claim_source_gate_passed', 'historical_pit_verified',
                    'source_gate_passed', 'profit_edge_proven', 'market_prices_or_returns_read', 'orders_authorized'):
            self.assertFalse(summary[key], key)

    def test_no_current_notice_is_not_proof_of_unmodified_or_valid_transaction(self):
        queries, _ = fixture()
        _, summary = replay_indices(queries, {q['filename']: body([]) for q in queries})
        self.assertEqual(summary['returned_announcements'], [])
        self.assertFalse(summary['no_later_notice_proven'])
        self.assertFalse(summary['complete_announcement_population_verified'])

    def test_scope_or_file_population_cannot_drift(self):
        for failure in ('issuer', 'range', 'category', 'missing', 'extra', 'duplicate_name'):
            queries, bodies = fixture()
            if failure == 'issuer':
                queries[1]['issuer'] = '9999'
            elif failure == 'range':
                queries[0]['end'] = '2026-10-22'
            elif failure == 'category':
                queries[0]['category'] = 'M11'
            elif failure == 'missing':
                bodies.pop('2324.json')
            elif failure == 'extra':
                bodies['unrequested.json'] = body([])
            else:
                queries[1]['filename'] = queries[0]['filename']
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                replay_indices(queries, bodies)

    def test_cross_issuer_response_rejected_even_if_each_body_is_valid_json(self):
        queries, bodies = fixture()
        bodies['6674.json'], bodies['2324.json'] = bodies['2324.json'], bodies['6674.json']
        with self.assertRaisesRegex(ValueError, 'issuer'):
            replay_indices(queries, bodies)

    def test_failed_or_partial_transport_cannot_qualify_saved_bytes(self):
        success = [dict(http_status=200, exit_code=0)] * 2
        require_successful_indices(success)
        for records in [success[:1], success + success[:1],
                        [success[0], dict(http_status=502, exit_code=0)],
                        [success[0], dict(http_status=200, exit_code=28)],
                        [success[0], dict(http_status=200, exit_code=None)]]:
            with self.subTest(records=records), self.assertRaisesRegex(ValueError, 'HTTP200 and exit0'):
                require_successful_indices(records)

    def test_frozen_plan_guard_fails_before_any_archive_or_output_access(self):
        module = SimpleNamespace(archived=Mock())
        with patch.object(current.merger_current_sources, '_source_module', return_value=module), \
             patch.object(current.merger_current_sources, 'plan', side_effect=ValueError('Prior checkpoint drift')), \
             patch.object(current, 'atomic_json') as write, \
             self.assertRaisesRegex(ValueError, 'Prior checkpoint drift'):
            current.run()
        module.archived.assert_not_called()
        write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
