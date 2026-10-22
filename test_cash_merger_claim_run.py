"""Frozen pending-case replay guards with temporary evidence, never sources."""
import contextlib
import copy
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cash_merger_claim_clock import REQUIRED_FACTS
import cash_merger_claim_run as runner


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ClaimReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='claim_run_')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.protocol_path, self.freeze = self.base / 'protocol.json', self.base / 'freeze.json'
        self.case_path, self.terms = self.base / 'case.json', self.base / 'terms.json'
        self.annotation, self.member = self.base / 'annotation.json', self.base / 'source_receipt.json'
        self.checkpoint = self.base / 'checkpoint.json'
        dump(self.annotation, dict(terms=[dict(topic='synthetic_rule', evidence=[dict(
            pdf_sha256='c' * 64, pdf_page_number=20, page_text_sha256='b' * 64)]),
            dict(topic='other_rule', evidence=[dict(pdf_sha256='d' * 64, pdf_page_number=21,
                                                    page_text_sha256='e' * 64)])]))
        dump(self.member, dict(source_archive_sha256='a' * 64))
        dump(self.checkpoint, dict(files={str(self.member): sha(self.member)}))
        dump(self.terms, dict(all_evidence_bindings_verified=True, source_gate_passed=False))
        evidence = dict(annotation_path=str(self.annotation), annotation_sha256=sha(self.annotation),
                        topic='synthetic_rule', physical_pages=[20], page_text_sha256=['b' * 64],
                        pdf_sha256=['c' * 64])
        self.case = dict(case_id='SYNTHETIC_PENDING', actual_inputs_state='pending',
            facts={key: dict(value=None, verified=None, evidence=[copy.deepcopy(evidence)]) for key in REQUIRED_FACTS},
            source_observation_taipei='2026-10-22T06:43:57+08:00',
            observation_scope='Morning saved observation; no evening status claim',
            evening_current_status_verified=False, contract_copy_date='2026-09-18',
            source_hashes=dict(archive_sha256='a' * 64),
            annotation_references=[dict(path=str(self.annotation), sha256=sha(self.annotation))],
            business_calendar=None, written_extension=None,
            provisional_terms=dict(consideration='18.50', conversion_date='2026-12-31',
                                   evidence=[copy.deepcopy(evidence)]),
            voting_bookclosure=['2026-10-11', '2026-11-09'])
        dump(self.case_path, self.case)
        self.protocol = dict(freeze_path=str(self.freeze),
            prior_checkpoints={str(self.checkpoint): sha(self.checkpoint)},
            case_config=dict(path=str(self.case_path), sha256=sha(self.case_path)),
            terms_audit=dict(path=str(self.terms), sha256=sha(self.terms)))
        self.save_protocol()

    def save_protocol(self, freeze=True):
        dump(self.protocol_path, self.protocol)
        if freeze:
            dump(self.freeze, dict(protocol_sha256=sha(self.protocol_path)))

    def save_case(self):
        dump(self.case_path, self.case)
        self.protocol['case_config']['sha256'] = sha(self.case_path)
        self.save_protocol()

    def test_pending_case_replays_hashes_gaps_and_null_cash_without_semantic_promotion(self):
        result = runner.replay(self.protocol_path)
        self.assertEqual(result['source_observation_taipei'], '2026-10-22T06:43:57+08:00')
        self.assertEqual(result['protocol_sha256'], sha(self.protocol_path))
        self.assertEqual(result['case_config_sha256'], sha(self.case_path))
        self.assertEqual(result['terms_audit_sha256'], sha(self.terms))
        self.assertEqual(result['frozen_prior_member_checks'], 1)
        self.assertIsNone(result['claim']['cash'])
        self.assertIsNone(result['claim']['payment_date'])
        self.assertIn('final_conversion_date_unknown', result['gaps'])
        for key in ('hash_validation_is_semantic_approval', 'source_acquisition_performed',
                    'evening_current_status_verified', 'user_holdings_requested', 'source_gate_passed',
                    'cash_claim_source_gate_passed', 'historical_pit_verified', 'profit_edge_proven',
                    'market_prices_or_returns_read', 'orders_authorized'):
            self.assertFalse(result[key], key)

    def test_case_terms_or_annotation_hash_drift_stops_before_evaluation(self):
        for key in ('case', 'terms', 'annotation'):
            path = {'case': self.case_path, 'terms': self.terms, 'annotation': self.annotation}[key]
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.subTest(key=key), patch.object(runner, 'evaluate_claim') as evaluate:
                with self.assertRaisesRegex(ValueError, 'Frozen reference drift'):
                    runner.replay(self.protocol_path)
                evaluate.assert_not_called()
            path.write_bytes(original)

    def test_protocol_drift_or_missing_freeze_blocks_replay(self):
        self.protocol['later_revision'] = True
        self.save_protocol(freeze=False)
        with self.assertRaisesRegex(ValueError, 'Frozen claim protocol drift'):
            runner.replay(self.protocol_path)
        self.save_protocol()
        self.freeze.unlink()
        with self.assertRaises(FileNotFoundError):
            runner.replay(self.protocol_path)

    def test_missing_prior_or_changed_checkpoint_member_cannot_be_skipped(self):
        original = self.checkpoint.read_bytes()
        self.checkpoint.unlink()
        with self.assertRaises(FileNotFoundError):
            runner.replay(self.protocol_path)
        self.checkpoint.write_bytes(original)
        self.member.write_text('{"source":"changed"}')
        with self.assertRaisesRegex(ValueError, 'Frozen reference drift'):
            runner.replay(self.protocol_path)
        self.protocol['prior_checkpoints'] = {}
        self.save_protocol()
        with self.assertRaisesRegex(ValueError, 'prior checkpoint'):
            runner.replay(self.protocol_path)

    def test_fake_pending_case_cannot_promote_any_actual_fact_or_fill_a_calendar(self):
        original = copy.deepcopy(self.case)
        for failure in ('verified', 'known', 'calendar', 'extension', 'state'):
            self.case = copy.deepcopy(original)
            if failure == 'verified':
                self.case['facts']['final_consideration_per_share']['verified'] = True
            elif failure == 'known':
                self.case['facts']['final_conversion_date']['value'] = '2026-12-31'
            elif failure == 'calendar':
                self.case['business_calendar'] = dict(verified=False)
            elif failure == 'extension':
                self.case['written_extension'] = dict(verified=False)
            else:
                self.case['actual_inputs_state'] = 'ready'
            self.save_case()
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                runner.replay(self.protocol_path)

    def test_source_asof_needs_taipei_timezone_and_cannot_be_called_evening_status(self):
        original = copy.deepcopy(self.case)
        for failure in ('naive', 'wrong_offset', 'evening'):
            self.case = copy.deepcopy(original)
            if failure == 'naive':
                self.case['source_observation_taipei'] = '2026-10-22T06:43:57'
            elif failure == 'wrong_offset':
                self.case['source_observation_taipei'] = '2026-10-21T22:43:57+00:00'
            else:
                self.case['evening_current_status_verified'] = True
            self.save_case()
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                runner.replay(self.protocol_path)

    def test_missing_gap_page_hash_or_unbound_annotation_is_not_a_valid_case_citation(self):
        original = copy.deepcopy(self.case)
        for failure in ('missing_fact', 'bad_hash', 'unbound_annotation', 'bool_page'):
            self.case = copy.deepcopy(original)
            row = self.case['facts']['lawful_withholding_twd']['evidence'][0]
            if failure == 'missing_fact':
                self.case['facts'].pop('all_closing_conditions')
            elif failure == 'bad_hash':
                row['page_text_sha256'] = ['unknown']
            elif failure == 'unbound_annotation':
                row['annotation_path'] = 'not-pinned.json'
            else:
                row['physical_pages'] = [True]
            self.save_case()
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                runner.replay(self.protocol_path)

    def test_cli_writes_only_the_requested_local_result_after_validation(self):
        output = self.base / 'result.json'
        with patch('sys.argv', ['cash_merger_claim_run.py', '--protocol', str(self.protocol_path), '--output', str(output)]), \
             contextlib.redirect_stdout(StringIO()):
            runner.main()
        result = json.loads(output.read_text())
        self.assertEqual(result['status'], 'frozen_pending_actual_case_replayed')
        self.assertIsNone(result['claim']['cash'])
        self.assertIsNone(result['claim']['payment_date'])

    def test_repinned_case_cannot_cite_wrong_topic_page_hash_or_pdf_in_facts_or_proposals(self):
        original = copy.deepcopy(self.case)
        for location in ('fact', 'provisional'):
            for failure in ('topic', 'unknown_topic', 'page', 'hash', 'pdf'):
                self.case = copy.deepcopy(original)
                citation = (self.case['facts']['final_conversion_date']['evidence'][0] if location == 'fact'
                            else self.case['provisional_terms']['evidence'][0])
                if failure == 'topic':
                    citation['topic'] = 'other_rule'
                elif failure == 'unknown_topic':
                    citation['topic'] = 'not_in_annotation'
                elif failure == 'page':
                    citation['physical_pages'] = [21]
                elif failure == 'hash':
                    citation['page_text_sha256'] = ['e' * 64]
                else:
                    citation['pdf_sha256'] = ['d' * 64]
                self.save_case()  # The changed case/protocol hashes are valid.
                with self.subTest(location=location, failure=failure), self.assertRaisesRegex(ValueError, 'topic|annotation'):
                    runner.replay(self.protocol_path)

    def test_duplicate_keys_or_nonfinite_json_are_rejected(self):
        for body in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                runner.decode(body)


if __name__ == '__main__':
    unittest.main()
