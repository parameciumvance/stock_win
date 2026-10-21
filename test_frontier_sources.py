"""Synthetic checkpoint and pre-network failure tests; no live acquisition."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import frontier_sources as source
from research_runtime import exclusive_lock


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def digest(body):
    return hashlib.sha256(body).hexdigest()


class FrontierSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.root, self.out = Path('inputs/frontier_test'), Path('deliverables/frontier_test')
        self.raw = self.root / 'raw_discovery'
        self.cfg_path, self.policy_path = Path('configs/requests.json'), Path('configs/protocol.json')
        self.raw.mkdir(parents=True)
        self.out.mkdir(parents=True)
        self.request = {'filename': 'official.html', 'url': 'https://www.twse.com.tw/fixture'}
        self.cfg = dict(output_directory=str(self.raw), allowed_hosts=['www.twse.com.tw'], requests=[self.request])
        write(self.cfg_path, self.cfg)
        Path('frozen_input.txt').write_bytes(b'old frozen input')
        write('checkpoint.json', {'files': {'frozen_input.txt': source.sha256('frozen_input.txt')}})
        self.policy = dict(prior_checkpoints={'checkpoint.json': source.sha256('checkpoint.json')},
                           batches={'discovery': dict(path=str(self.cfg_path), sha256=source.sha256(self.cfg_path), requests=1)},
                           max_saved_requests=3)
        self.freeze()
        self.patchers = [patch.object(source, 'ROOT', self.root), patch.object(source, 'OUT', self.out),
                         patch.object(source, 'POLICY', self.policy_path)]
        for value in self.patchers:
            value.start()
        self.network = patch.object(source, 'native_acquire')
        self.native = self.network.start()

    def tearDown(self):
        self.network.stop()
        for value in reversed(self.patchers):
            value.stop()
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def freeze(self):
        write(self.policy_path, self.policy)
        write(self.out / 'protocol_freeze.json', {'protocol_sha256': digest(self.policy_path.read_bytes())})

    def saved(self, status=200):
        records = []
        for item in self.cfg['requests']:
            body, headers = b'official saved response', f'HTTP/2 {status}\n'.encode()
            (self.raw / item['filename']).write_bytes(body)
            (self.raw / (item['filename'] + '.headers')).write_bytes(headers)
            record = dict(request=item, transport='WSL native curl; verified HTTPS; two workers',
                          http_status=status, exit_code=0, sha256=digest(body), headers_sha256=digest(headers),
                          request_started_at='2026-10-20T00:00:00+00:00', observed_at='2026-10-20T00:00:01+00:00')
            write(self.raw / (item['filename'] + '.meta.json'), record)
            records.append(record)
        write(self.raw / 'results.json', dict(config_sha256=source.sha256(self.cfg_path), workers=2, requests=records))

    def backed_package(self, status=200):
        self.saved(status)
        source.package()
        package = source.read(self.out / 'discovery_package.json')
        shutil.copyfile(package['archive'], package['retrieved'])
        write(package['transfer_receipt'], {'sha256': package['sha256'], 'roundtrip_verified': True})
        return package

    def test_fresh_acquisition_delegates_without_holding_nested_lock(self):
        def native(path):
            self.assertEqual(path, self.cfg_path)
            with exclusive_lock(self.root / 'acquisition.lock'):
                pass
        self.native.side_effect = native
        source.acquire()
        self.native.assert_called_once_with(self.cfg_path)

    def test_complete_valid_cache_skips_native_and_preserves_bytes(self):
        self.saved()
        before = {p.name: p.read_bytes() for p in self.raw.iterdir()}
        source.acquire()
        self.assertEqual({p.name: p.read_bytes() for p in self.raw.iterdir()}, before)
        self.native.assert_not_called()

    def test_archive_restores_missing_local_sources_without_live_replacement(self):
        package = self.backed_package()
        expected = {p.name: p.read_bytes() for p in self.raw.iterdir()}
        shutil.rmtree(self.raw)
        source.acquire()
        self.assertEqual({p.name: p.read_bytes() for p in self.raw.iterdir()}, expected)
        self.assertEqual(source.sha256(package['retrieved']), package['sha256'])
        self.native.assert_not_called()

    def test_local_tamper_is_not_overwritten_from_archive_or_network(self):
        self.backed_package()
        (self.raw / 'official.html').write_bytes(b'user changed bytes')
        with self.assertRaisesRegex(ValueError, 'not overwritten'):
            source.acquire()
        self.assertEqual((self.raw / 'official.html').read_bytes(), b'user changed bytes')
        self.native.assert_not_called()

    def test_corrupt_archive_and_unverified_transfer_fail_before_native(self):
        for failure in ('archive', 'transfer'):
            package = self.backed_package()
            if failure == 'archive':
                with Path(package['retrieved']).open('ab') as stream:
                    stream.write(b'corruption')
            else:
                write(package['transfer_receipt'], {'sha256': package['sha256'], 'roundtrip_verified': False})
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                source.acquire()
            if failure == 'archive':
                shutil.copyfile(package['archive'], package['retrieved'])
            else:
                write(package['transfer_receipt'], {'sha256': package['sha256'], 'roundtrip_verified': True})
        self.native.assert_not_called()

    def test_protocol_config_checkpoint_and_checkpoint_member_drift_precede_live_io(self):
        targets = [self.policy_path, self.cfg_path, Path('checkpoint.json'), Path('frozen_input.txt')]
        for path in targets:
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.subTest(path=path), self.assertRaises(ValueError):
                source.acquire()
            path.write_bytes(original)
        self.native.assert_not_called()

    def test_second_cached_leg_checked_before_any_worker_can_fetch_first_leg(self):
        second = dict(filename='second.html', url='https://www.twse.com.tw/second')
        self.cfg['requests'].append(second)
        write(self.cfg_path, self.cfg)
        self.policy['batches']['discovery'].update(sha256=source.sha256(self.cfg_path), requests=2)
        self.freeze()
        # No first-leg data exists.  A partial second-leg file must be rejected
        # before handing the batch to workers, not after the first worker starts.
        (self.raw / 'second.html').write_bytes(b'unrecorded partial source')
        with self.assertRaisesRegex(ValueError, 'Unrecorded partial'):
            source.acquire()
        self.native.assert_not_called()

    def test_failed_http_is_preserved_but_never_promoted_to_source_validity(self):
        self.backed_package(status=502)
        source.verify()
        receipt = source.read(self.out / 'source_receipt_discovery.json')
        self.assertEqual(receipt['observations'][0]['http_status'], 502)
        self.assertTrue(receipt['crc_manifest_verified'])
        self.assertTrue(receipt['roundtrip_verified'])
        for flag in ('semantic_source_validated', 'historical_pit_verified',
                     'complete_population_verified', 'source_gate_passed'):
            self.assertFalse(receipt[flag], flag)
        self.native.assert_not_called()

    def test_existing_package_cannot_be_replaced_with_extra_raw(self):
        package = self.backed_package()
        original = Path(package['archive']).read_bytes()
        (self.raw / 'extra.txt').write_bytes(b'new bytes')
        with self.assertRaisesRegex(ValueError, 'not replaced'):
            source.package()
        self.assertEqual(Path(package['archive']).read_bytes(), original)
        self.native.assert_not_called()

    def test_output_path_must_use_same_frontier_lock(self):
        self.cfg['output_directory'] = 'inputs/other/raw'
        write(self.cfg_path, self.cfg)
        self.policy['batches']['discovery']['sha256'] = source.sha256(self.cfg_path)
        self.freeze()
        with self.assertRaisesRegex(ValueError, 'share frontier acquisition lock'):
            source.acquire()
        self.native.assert_not_called()

    def test_separately_frozen_adaptive_batch_still_obeys_global_request_ceiling(self):
        path = Path('configs/adaptive.json')
        cfg = dict(self.cfg, output_directory=str(self.root / 'raw_adaptive'))
        write(path, cfg)
        freeze = dict(protocol_sha256=source.sha256(self.policy_path), path=str(path),
                      sha256=source.sha256(path), requests=1)
        write(self.out / 'adaptive_freeze.json', freeze)
        self.assertEqual(source.plan('adaptive')[0], path)
        self.policy['max_saved_requests'] = 1
        self.freeze()
        freeze['protocol_sha256'] = source.sha256(self.policy_path)
        write(self.out / 'adaptive_freeze.json', freeze)
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            source.acquire('adaptive')
        self.native.assert_not_called()

    def test_adaptive_batch_count_limit_applies_even_below_request_ceiling(self):
        self.policy['max_source_batches'] = 1
        self.freeze()
        path = Path('configs/adaptive.json')
        write(path, dict(self.cfg, output_directory=str(self.root / 'raw_adaptive')))
        write(self.out / 'adaptive_freeze.json', dict(protocol_sha256=source.sha256(self.policy_path),
              path=str(path), sha256=source.sha256(path), requests=1))
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            source.acquire('adaptive')
        self.native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
