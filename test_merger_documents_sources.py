"""Known official form/query guards with mocked prior readbacks and transport."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import frontier_sources
import merger_documents_sources as sources


FIELDS = [('step', '1'), ('firstin', 'ture'), ('off', '1'), ('TYPEK', 'all'),
          ('keyword4', ''), ('code1', ''), ('TYPEK2', ''), ('checkbtn', ''),
          ('queryName', 'co_id'), ('inpuType', 'co_id'), ('co_id', ''), ('year', '')]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class DocumentQuerySourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='document_query_')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.out, self.form_out = self.base / 'out', self.base / 'form_out'
        self.out.mkdir()
        self.form_out.mkdir()
        self.raw_root = Path('inputs') / self.base.name
        self.policy_path, self.config_path = self.base / 'policy.json', self.base / 'requests.json'
        self.selection_path = self.out / 'selection.json'
        self.prior, self.member = self.form_out / 'checkpoint.json', self.base / 'member.json'
        self.member.write_text('{"saved":"old"}\n')
        dump(self.prior, dict(files={str(self.member): digest(self.member)}))
        self.form_body = ('<html><form name="form1" method="post" action="/mops/web/ajax_t57sb01_q5">'
             + ''.join(f'<input name="{name}" value="{value}">' for name, value in FIELDS)
             + '</form><script>document.form1.firstin.value=\'1\';</script></html>').encode()
        self.form_sha = hashlib.sha256(self.form_body).hexdigest()
        for module, values in [(sources, dict(ROOT=self.raw_root, OUT=self.out, POLICY=self.policy_path,
                QUERY_CONFIG=self.config_path, SELECTION=self.selection_path, FORM_OUT=self.form_out,
                FORM_BODY_SHA256=self.form_sha, REQUIRED_CHECKPOINT=self.prior)),
                (frontier_sources, dict(ROOT=frontier_sources.ROOT, OUT=frontier_sources.OUT,
                                       POLICY=frontier_sources.POLICY))]:
            for name, value in values.items():
                guard = patch.object(module, name, value)
                guard.start()
                self.addCleanup(guard.stop)
        request_fields = dict(FIELDS, firstin='1', co_id='6674', year='115')
        self.config = dict(output_directory=str(self.raw_root / 'raw_query'),
            allowed_hosts=['mopsov.twse.com.tw'], requests=[dict(filename='meeting_books_6674_115.html',
                url=sources.QUERY_URL, method='POST', data=urlencode(request_fields))])
        self.selection = dict(source_form_sha256=self.form_sha, issuer='6674', roc_year='115',
                              book_type_filter=None, query_filename='meeting_books_6674_115.html')
        dump(self.config_path, self.config)
        self.policy = dict(max_saved_requests=4, max_source_batches=4,
            prior_checkpoints={str(self.prior): digest(self.prior)},
            source_ledger=dict(completed_saved_requests=8, new_saved_request_ceiling=4,
                               combined_request_ceiling=12, old_discovery_phases_retired=True),
            source_form=dict(out=str(self.form_out), batch='ebook_form',
                archive_sha256=sources.FORM_ARCHIVE_SHA256, member=sources.FORM_MEMBER, body_sha256=self.form_sha),
            batches=dict(query=dict(path=str(self.config_path), sha256=digest(self.config_path), requests=1)))
        self.save_selection()
        self.save_policy()
        self.saved_count = 8
        guard = patch.object(sources, '_prior_saved_count', side_effect=lambda policy: (self.saved_count, self.form_body))
        guard.start()
        self.addCleanup(guard.stop)

    def save_selection(self):
        dump(self.selection_path, self.selection)
        self.policy['selection_manifest'] = dict(path=str(self.selection_path), sha256=digest(self.selection_path))

    def save_config(self):
        dump(self.config_path, self.config)
        self.policy['batches']['query']['sha256'] = digest(self.config_path)

    def save_policy(self, freeze=True):
        dump(self.policy_path, self.policy)
        if freeze:
            dump(self.out / 'protocol_freeze.json', dict(protocol_sha256=digest(self.policy_path)))

    def blocked(self, exception=ValueError):
        with patch.object(frontier_sources, 'native_acquire') as native:
            with self.assertRaises(exception):
                sources.acquire('query')
            native.assert_not_called()

    def test_known_form_fields_and_button_update_allow_one_mocked_query(self):
        self.assertEqual(sources.validate_query_plan(), self.config)
        with patch.object(frontier_sources, 'native_acquire') as native:
            sources.acquire('query')
            native.assert_called_once_with(self.config_path)
        self.assertFalse(self.raw_root.exists())

    def test_request_issuer_year_firstin_or_book_type_cannot_drift(self):
        original = copy.deepcopy(self.config)
        for before, after in [('co_id=6674', 'co_id=2324'), ('year=115', 'year=114'),
                              ('firstin=1', 'firstin=ture'), ('TYPEK=all', 'TYPEK=sii')]:
            self.config = copy.deepcopy(original)
            self.config['requests'][0]['data'] = self.config['requests'][0]['data'].replace(before, after)
            self.save_config()
            self.save_policy()
            with self.subTest(field=before):
                self.blocked()
        for suffix in ['&book_type=meeting', '&co_id=6674', '&year=115']:
            self.config = copy.deepcopy(original)
            self.config['requests'][0]['data'] += suffix
            self.save_config()
            self.save_policy()
            with self.subTest(suffix=suffix):
                self.blocked()

    def test_bound_form_action_fields_or_button_evidence_must_match_even_after_hash_repin(self):
        original_body = self.form_body
        for before, after in [(b'/ajax_t57sb01_q5', b'/ajax_other'), (b'method="post"', b'method="get"'),
                              (b'name="year"', b'name="book_type"'), (b'value="ture"', b'value="true"'),
                              (b"firstin.value='1';", b"firstin.value='2';")]:
            self.form_body = original_body.replace(before, after)
            changed_sha = hashlib.sha256(self.form_body).hexdigest()
            self.policy['source_form']['body_sha256'] = changed_sha
            self.selection['source_form_sha256'] = changed_sha
            self.save_selection()
            self.save_policy()
            with self.subTest(field=before), patch.object(sources, 'FORM_BODY_SHA256', changed_sha):
                self.blocked()

    def test_changed_form_body_without_sha_change_is_rejected(self):
        self.form_body += b'<!-- later source revision -->'
        self.blocked()

    def test_selection_cannot_introduce_specific_book_filter_or_different_issuer_year(self):
        original = copy.deepcopy(self.selection)
        for key, value in [('issuer', '2324'), ('roc_year', '114'), ('book_type_filter', '議事手冊'),
                           ('query_filename', 'guessed_contract.pdf')]:
            self.selection = copy.deepcopy(original)
            self.selection[key] = value
            self.save_selection()
            self.save_policy()
            with self.subTest(key=key):
                self.blocked()

    def test_query_route_method_or_host_cannot_be_substituted(self):
        original = copy.deepcopy(self.config)
        for field, value in [('url', sources.QUERY_URL.replace('mopsov.twse.com.tw', 'other.example')),
                              ('url', sources.QUERY_URL.replace('q5', 'q6')), ('method', 'GET')]:
            self.config = copy.deepcopy(original)
            self.config['requests'][0][field] = value
            self.save_config()
            self.save_policy()
            with self.subTest(field=field, value=value):
                self.blocked()

    def test_prior_completed_count_and_new_ledger_cannot_hide_more_requests(self):
        self.saved_count = 7
        self.blocked()
        self.saved_count = 8
        original = copy.deepcopy(self.policy)
        for key, value in [('completed_saved_requests', 7), ('new_saved_request_ceiling', 5),
                           ('combined_request_ceiling', 13), ('old_discovery_phases_retired', False)]:
            self.policy = copy.deepcopy(original)
            self.policy['source_ledger'][key] = value
            self.save_policy()
            with self.subTest(key=key):
                self.blocked()

    def test_unpinned_parent_changed_frozen_member_and_missing_freeze_block_native_io(self):
        self.policy['prior_checkpoints'][str(self.prior)] = None
        self.save_policy()
        self.blocked()
        self.policy['prior_checkpoints'][str(self.prior)] = digest(self.prior)
        self.save_policy()
        self.member.write_text('{"saved":"changed"}')
        self.blocked()
        dump(self.prior, dict(files={str(self.member): digest(self.member)}))
        self.policy['prior_checkpoints'][str(self.prior)] = digest(self.prior)
        self.save_policy()
        (self.out / 'protocol_freeze.json').unlink()
        self.blocked(FileNotFoundError)

    def test_configuration_path_or_byte_drift_blocks_validate_a_acquire_b(self):
        self.config_path.write_text(json.dumps(self.config))
        self.blocked()
        self.save_config()
        alternate = self.base / 'alternate.json'
        dump(alternate, self.config)
        self.policy['batches']['query'] = dict(path=str(alternate), sha256=digest(alternate), requests=1)
        self.save_policy()
        self.blocked()

    def test_new_phase_limit_and_adaptive_total_remain_four(self):
        self.policy['max_saved_requests'] = 5
        self.save_policy()
        self.blocked()
        self.policy['max_saved_requests'] = 4
        self.save_policy()
        adaptive = self.base / 'adaptive.json'
        dump(adaptive, self.config)
        dump(self.out / 'attachments_freeze.json', dict(path=str(adaptive), sha256=digest(adaptive), requests=4,
                                                      protocol_sha256=digest(self.policy_path)))
        self.blocked()


if __name__ == '__main__':
    unittest.main()
