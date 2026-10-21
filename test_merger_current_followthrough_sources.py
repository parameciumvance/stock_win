"""Synthetic spent-ledger and pointer guards, before any native source IO."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import frontier_sources
import merger_current_followthrough_sources as sources
from test_cash_merger_current_notices import fixture


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class FollowthroughSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='followthrough_sources_')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.out, self.index_out = self.base / 'out', self.base / 'index_out'
        self.out.mkdir()
        self.index_out.mkdir()
        self.raw_root = Path('inputs') / self.base.name
        self.policy_path, self.config_path = self.base / 'policy.json', self.base / 'requests.json'
        self.selection_path, self.old_requests = self.base / 'selection.json', self.base / 'old_requests.json'
        self.prior, self.prior_member = self.index_out / 'checkpoint.json', self.base / 'member.json'
        self.prior_member.write_text('{"verified":"old"}\n')
        dump(self.prior, dict(files={str(self.prior_member): digest(self.prior_member)}))
        (self.index_out / 'index_package.json').write_text('{}')
        patches = [(sources, dict(ROOT=self.raw_root, OUT=self.out, POLICY=self.policy_path,
                    NOTICE_CONFIG=self.config_path, SELECTION=self.selection_path, INDEX_OUT=self.index_out,
                    INDEX_REQUESTS=self.old_requests, INDEX_CHECKPOINT=self.prior)),
                   (frontier_sources, dict(ROOT=frontier_sources.ROOT, OUT=frontier_sources.OUT,
                                           POLICY=frontier_sources.POLICY))]
        for module, values in patches:
            for key, value in values.items():
                guard = patch.object(module, key, value)
                guard.start()
                self.addCleanup(guard.stop)
        self.selection, _ = fixture()
        for selected, (event_id, filename) in zip(self.selection['rows'], sources.NOTICE_IDENTITIES, strict=True):
            self.assertEqual(selected['event_id'], event_id)
            selected['new_filename'] = filename
        self.index_rows = [copy.deepcopy(r['index_original_fields']) for r in self.selection['rows']]
        self.old_cfg = dict(requests=[dict(filename=filename, url='https://mopsov.twse.com.tw/mops/web/ezsearch_query',
                                         method='POST', data='saved-query') for filename in
                                     ['target_6674_m00.json', 'buyer_2324_m00.json']])
        dump(self.old_requests, self.old_cfg)
        self.archive = self.base / 'index.zip'
        self.records = [dict(request=request, http_status=200, exit_code=0) for request in self.old_cfg['requests']]
        self.config = dict(output_directory=str(self.raw_root / 'raw_notices'),
                           allowed_hosts=['mopsov.twse.com.tw'], requests=[
                               dict(filename=r['new_filename'], url=r['index_original_fields']['HYPERLINK'])
                               for r in self.selection['rows']])
        dump(self.config_path, self.config)
        self.policy = dict(max_saved_requests=6, max_source_batches=6,
            prior_checkpoints={str(self.prior): digest(self.prior)},
            source_ledger=dict(completed_saved_requests=2, remaining_saved_requests=6,
                combined_request_ceiling=8, old_unused_adaptive_branch_retired=True,
                prior_requests=dict(path=str(self.old_requests), sha256=digest(self.old_requests), requests=2)),
            source_index=dict(out=str(self.index_out), batch='index', member='raw/target_6674_m00.json',
                              archive_sha256='a' * 64, body_sha256='pending'),
            batches=dict(notices=dict(path=str(self.config_path), sha256=digest(self.config_path), requests=3)))
        self.save_archive()
        self.save_selection()
        self.save_policy()
        self.readback = patch.object(sources, 'readback', return_value=(dict(sha256='a' * 64,
                                     retrieved=str(self.archive)), dict(roundtrip_verified=True)))
        self.readback.start()
        self.addCleanup(self.readback.stop)

    def save_archive(self):
        raw = json.dumps(dict(data=self.index_rows, status='success', message=['回傳成功']), ensure_ascii=False).encode()
        self.policy['source_index']['body_sha256'] = hashlib.sha256(raw).hexdigest()
        self.selection['source_index_sha256'] = hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('requests.json', self.old_requests.read_bytes())
            archive.writestr('raw/target_6674_m00.json', raw)
            archive.writestr('raw/results.json', json.dumps(dict(workers=2,
                config_sha256=digest(self.old_requests), requests=self.records)))
            for record in self.records:
                archive.writestr('raw/' + record['request']['filename'] + '.meta.json', json.dumps(record))

    def save_selection(self):
        dump(self.selection_path, self.selection)
        self.policy['selection_manifest'] = dict(path=str(self.selection_path), sha256=digest(self.selection_path))

    def save_config(self):
        dump(self.config_path, self.config)
        self.policy['batches']['notices']['sha256'] = digest(self.config_path)

    def save_policy(self, freeze=True):
        dump(self.policy_path, self.policy)
        if freeze:
            dump(self.out / 'protocol_freeze.json', dict(protocol_sha256=digest(self.policy_path)))

    def blocked(self, exception=ValueError):
        with patch.object(frontier_sources, 'native_acquire') as native:
            with self.assertRaises(exception):
                sources.acquire('notices')
            native.assert_not_called()

    def test_exact_three_requests_reuse_verified_index_and_delegate_once(self):
        self.assertEqual(sources.validate_notice_plan(), self.config)
        with patch.object(frontier_sources, 'native_acquire') as native:
            sources.acquire('notices')
            native.assert_called_once_with(self.config_path)
        self.assertFalse(self.raw_root.exists())

    def test_spent_or_remaining_ledger_cannot_extend_eight_or_reactivate_old_branch(self):
        original = copy.deepcopy(self.policy)
        for key, value in [('completed_saved_requests', 1), ('remaining_saved_requests', 7),
                           ('combined_request_ceiling', 9), ('old_unused_adaptive_branch_retired', False)]:
            self.policy = copy.deepcopy(original)
            self.policy['source_ledger'][key] = value
            self.save_policy()
            with self.subTest(key=key):
                self.blocked()

    def test_fixed_limits_remain_six_requests_and_six_source_batches(self):
        for key, value in [('max_saved_requests', 7), ('max_source_batches', 7)]:
            original = copy.deepcopy(self.policy)
            self.policy[key] = value
            self.save_policy()
            with self.subTest(key=key):
                self.blocked()
            self.policy = original

    def test_unpinned_parent_or_changed_frozen_parent_member_blocks_native_io(self):
        self.policy['prior_checkpoints'][str(self.prior)] = None
        self.save_policy()
        self.blocked()
        self.policy['prior_checkpoints'][str(self.prior)] = digest(self.prior)
        self.save_policy()
        self.prior_member.write_text('{"verified":"changed"}')
        self.blocked()

    def test_no_protocol_freeze_or_changed_protocol_blocks_native_io(self):
        freeze = self.out / 'protocol_freeze.json'
        freeze.unlink()
        self.blocked(FileNotFoundError)
        self.save_policy()
        self.policy['unexpected'] = 'later'
        self.save_policy(freeze=False)
        self.blocked()

    def test_old_branch_saved_package_is_not_ignored_by_two_spent_ledger(self):
        (self.index_out / 'documents_package.json').write_text('{}')
        self.blocked()

    def test_old_requests_file_hash_or_number_cannot_change(self):
        self.old_requests.write_text(json.dumps(self.old_cfg))
        self.blocked()
        dump(self.old_requests, self.old_cfg)
        self.policy['source_ledger']['prior_requests']['requests'] = 1
        self.save_policy()
        self.blocked()

    def test_old_saved_records_must_match_frozen_two_request_ledger(self):
        self.records = self.records[:1]
        self.save_archive()
        self.save_selection()
        self.save_policy()
        self.blocked()

    def test_wrong_source_archive_or_body_digest_blocks_before_requests(self):
        for field in ('archive_sha256', 'body_sha256'):
            original = copy.deepcopy(self.policy)
            self.policy['source_index'][field] = 'b' * 64
            self.save_policy()
            with self.subTest(field=field):
                self.blocked()
            self.policy = original

    def test_selection_and_request_hashes_cannot_be_semantically_reformatted(self):
        original = self.selection_path.read_bytes()
        self.selection_path.write_text(json.dumps(self.selection))
        self.blocked()
        self.selection_path.write_bytes(original)
        self.config_path.write_text(json.dumps(self.config))
        self.blocked()

    def test_complete_original_fields_must_match_saved_index_not_only_url_identity(self):
        self.selection['rows'][0]['index_original_fields']['SUBJECT'] = '事後替換的主旨'
        self.save_selection()
        self.save_policy()
        self.blocked()

    def test_selected_identity_filename_url_and_full_sequence_cannot_drift(self):
        for failure in ('event_id', 'filename', 'url', 'sequence'):
            original_selection, original_config = copy.deepcopy(self.selection), copy.deepcopy(self.config)
            original_rows = copy.deepcopy(self.index_rows)
            if failure == 'event_id':
                self.selection['rows'][0]['event_id'] += 'changed'
            elif failure == 'filename':
                self.selection['rows'][0]['new_filename'] = 'substitute.html'
            elif failure == 'url':
                self.config['requests'][0]['url'] = self.config['requests'][1]['url']
            else:
                old = self.index_rows[0]['HYPERLINK']
                self.index_rows[0]['HYPERLINK'] = old.replace('SEQ_NO=1', 'SEQ_NO=99')
                self.selection['rows'][0]['index_original_fields']['HYPERLINK'] = self.index_rows[0]['HYPERLINK']
                self.config['requests'][0]['url'] = self.index_rows[0]['HYPERLINK']
                self.save_archive()
            self.save_selection()
            self.save_config()
            self.save_policy()
            with self.subTest(failure=failure):
                self.blocked()
            self.selection, self.config, self.index_rows = original_selection, original_config, original_rows
            self.save_archive()

    def test_validated_notice_config_cannot_be_different_from_acquired_config(self):
        alternate = self.base / 'other_requests.json'
        dump(alternate, self.config)
        self.policy['batches']['notices'] = dict(path=str(alternate), sha256=digest(alternate), requests=3)
        self.save_policy()
        self.blocked()

    def test_seven_adaptive_requests_cannot_escape_six_remaining_budget(self):
        adaptive = self.base / 'adaptive.json'
        dump(adaptive, self.config)
        dump(self.out / 'attachments_freeze.json', dict(path=str(adaptive), sha256=digest(adaptive), requests=4,
                                                      protocol_sha256=digest(self.policy_path)))
        self.blocked()


if __name__ == '__main__':
    unittest.main()
