"""Pure pre-acquisition guards using temporary policies and mocked transport."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import frontier_sources
import merger_current_sources as current


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CurrentSourcePlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='current_source_test_')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.out = self.base / 'out'
        self.out.mkdir()
        self.policy_path = self.base / 'policy.json'
        self.config_path = self.base / 'requests.json'
        self.prior_member = self.base / 'prior_member.json'
        self.prior_member.write_text('{"result":"saved"}\n')
        self.prior = self.base / 'census_checkpoint.json'
        self.write(self.prior, {'files': {str(self.prior_member): file_digest(self.prior_member)}})
        # Generic validation requires an ignored, relative inputs path. No file
        # is created there; all actual reads/writes in these tests are temporary.
        self.raw_root = Path('inputs') / self.base.name
        for module, values in [
            (current, dict(ROOT=self.raw_root, OUT=self.out, POLICY=self.policy_path,
                           INDEX_CONFIG=self.config_path)),
            (frontier_sources, dict(ROOT=frontier_sources.ROOT, OUT=frontier_sources.OUT,
                                    POLICY=frontier_sources.POLICY)),
        ]:
            for name, value in values.items():
                guard = patch.object(module, name, value)
                guard.start()
                self.addCleanup(guard.stop)
        queries = [
            dict(filename='target_6674_m00.json', issuer='6674', category='M00',
                 start='2026-09-18', end='2026-10-21'),
            dict(filename='buyer_2324_m00.json', issuer='2324', category='M00',
                 start='2026-09-18', end='2026-10-21'),
        ]
        self.config = dict(output_directory=str(self.raw_root / 'raw_index'),
                           allowed_hosts=['mopsov.twse.com.tw'], requests=[])
        for query in queries:
            self.config['requests'].append(dict(
                filename=query['filename'], url=current.INDEX_URL, method='POST',
                data='step=00&RADIO_CM=2&TYPEK=&CO_MARKET=&CO_ID='+query['issuer']
                     +'&PRO_ITEM=M00&SUBJECT=&SDATE=115%2F09%2F18'
                     '&EDATE=115%2F10%2F21&lang=TW&AN=',
            ))
        self.write(self.config_path, self.config)
        self.policy = dict(
            index_queries=queries, prior_checkpoints={str(self.prior): file_digest(self.prior)},
            max_saved_requests=8, max_source_batches=2,
            batches={'index': dict(path=str(self.config_path),
                                   sha256=file_digest(self.config_path), requests=2)},
        )
        self.save_policy()

    @staticmethod
    def write(path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

    def save_policy(self, frozen=True):
        self.write(self.policy_path, self.policy)
        if frozen:
            self.write(self.out / 'protocol_freeze.json',
                       dict(protocol_sha256=file_digest(self.policy_path)))

    def save_config_and_ref(self):
        self.write(self.config_path, self.config)
        self.policy['batches']['index']['sha256'] = file_digest(self.config_path)
        self.save_policy()

    def assert_blocked(self, exception=ValueError):
        with patch.object(frontier_sources, 'native_acquire') as native:
            with self.assertRaises(exception):
                current.acquire('index')
            native.assert_not_called()

    def test_exact_two_issuer_plan_passes_without_network_or_raw_creation(self):
        self.assertEqual(current.validate_index_plan(), self.config)
        path, config, raw, freeze = current.plan('index')
        self.assertEqual(path, self.config_path)
        self.assertEqual(config, self.config)
        self.assertEqual(raw, self.raw_root / 'raw_index')
        self.assertIsNone(freeze)
        self.assertFalse(self.raw_root.exists())

    def test_ready_acquire_delegates_once_to_mocked_native_transport(self):
        with patch.object(frontier_sources, 'native_acquire') as native:
            current.acquire('index')
            native.assert_called_once_with(self.config_path)
        self.assertFalse(self.raw_root.exists())

    def test_query_mapping_cannot_change_issuer_dates_or_category(self):
        for field, changed in [('issuer', '1103'), ('category', 'M11'),
                               ('start', '2026-07-01'), ('end', '2026-10-22')]:
            original = copy.deepcopy(self.policy)
            self.policy['index_queries'][0][field] = changed
            self.save_policy()
            with self.subTest(field=field):
                self.assert_blocked()
            self.policy = original

    def test_swapping_filenames_or_adding_an_issuer_cannot_change_query_population(self):
        for mutation in ('swap', 'extra'):
            self.policy = copy.deepcopy(self.policy)
            if mutation == 'swap':
                self.policy['index_queries'].reverse()
            else:
                self.policy['index_queries'].append(copy.deepcopy(self.policy['index_queries'][0]))
            self.save_policy()
            with self.subTest(mutation=mutation):
                self.assert_blocked()
            self.policy['index_queries'] = [
                dict(filename='target_6674_m00.json', issuer='6674', category='M00',
                     start='2026-09-18', end='2026-10-21'),
                dict(filename='buyer_2324_m00.json', issuer='2324', category='M00',
                     start='2026-09-18', end='2026-10-21'),
            ]

    def test_post_cannot_switch_to_market_mode_narrow_category_or_wrong_dates(self):
        original = copy.deepcopy(self.config)
        for before, after in [('RADIO_CM=2', 'RADIO_CM=1'), ('TYPEK=', 'TYPEK=sii'),
                              ('CO_ID=6674', 'CO_ID=2324'), ('PRO_ITEM=M00', 'PRO_ITEM=M11'),
                              ('115%2F10%2F21', '115%2F10%2F22')]:
            self.config = copy.deepcopy(original)
            self.config['requests'][0]['data'] = self.config['requests'][0]['data'].replace(before, after)
            self.save_config_and_ref()
            with self.subTest(field=before):
                self.assert_blocked()

    def test_duplicate_or_extra_post_parameters_fail_before_transport(self):
        original = copy.deepcopy(self.config)
        for suffix in ('&CO_ID=6674', '&PRO_ITEM=M00', '&unknown=value'):
            self.config = copy.deepcopy(original)
            self.config['requests'][0]['data'] += suffix
            self.save_config_and_ref()
            with self.subTest(suffix=suffix):
                self.assert_blocked()

    def test_foreign_route_get_method_or_allowlist_broadening_fail(self):
        original = copy.deepcopy(self.config)
        for mutation in ('host', 'method', 'allowlist'):
            self.config = copy.deepcopy(original)
            if mutation == 'host':
                self.config['requests'][0]['url'] = current.INDEX_URL.replace('mopsov.twse.com.tw', 'foreign.example')
            elif mutation == 'method':
                self.config['requests'][0]['method'] = 'GET'
            else:
                self.config['allowed_hosts'].append('foreign.example')
            self.save_config_and_ref()
            with self.subTest(mutation=mutation):
                self.assert_blocked()

    def test_missing_protocol_freeze_blocks_acquisition(self):
        (self.out / 'protocol_freeze.json').unlink()
        self.assert_blocked(FileNotFoundError)

    def test_protocol_bytes_changed_after_freeze_block_acquisition(self):
        self.policy['unexpected_revision'] = True
        self.save_policy(frozen=False)
        self.assert_blocked()

    def test_null_census_checkpoint_blocks_even_with_matching_protocol_freeze(self):
        self.policy['prior_checkpoints'][str(self.prior)] = None
        self.save_policy()
        self.assert_blocked()

    def test_matching_checkpoint_hash_cannot_hide_changed_frozen_member(self):
        self.prior_member.write_text('{"result":"different"}\n')
        self.assert_blocked()

    def test_semantically_equal_request_bytes_still_require_frozen_hash(self):
        self.config_path.write_text(json.dumps(self.config, ensure_ascii=False))
        self.assert_blocked()

    def test_policy_cannot_validate_one_configuration_but_acquire_another(self):
        alternate_path = self.base / 'alternate_requests.json'
        alternate = copy.deepcopy(self.config)
        alternate['requests'][0]['data'] = alternate['requests'][0]['data'].replace('CO_ID=6674', 'CO_ID=1103')
        self.write(alternate_path, alternate)
        self.policy['batches']['index'] = dict(path=str(alternate_path),
                                               sha256=file_digest(alternate_path), requests=2)
        self.save_policy()
        self.assert_blocked()

    def test_index_reference_count_cannot_differ_from_validated_two_requests(self):
        self.policy['batches']['index']['requests'] = 1
        self.save_policy()
        self.assert_blocked()

    def add_adaptive_freeze(self, name, requests, protocol_sha=None):
        self.write(self.out / (name+'_freeze.json'), dict(
            path=str(self.base / (name+'.json')), sha256='a'*64, requests=requests,
            protocol_sha256=protocol_sha or file_digest(self.policy_path),
        ))

    def test_adaptive_seven_requests_exceed_remaining_six_and_block_index_io(self):
        self.add_adaptive_freeze('documents', 7)
        self.assert_blocked()

    def test_a_third_source_batch_cannot_extend_two_batch_ceiling(self):
        self.add_adaptive_freeze('documents', 1)
        self.add_adaptive_freeze('extra', 1)
        self.assert_blocked()

    def test_adaptive_batch_bound_to_another_protocol_cannot_be_reused(self):
        self.add_adaptive_freeze('documents', 1, protocol_sha='0'*64)
        self.assert_blocked()


if __name__ == '__main__':
    unittest.main()
