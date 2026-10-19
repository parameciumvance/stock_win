import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import buyback_preflight as b
from source_checkpoint import package_sources


class SavedSourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.root, self.out = Path('inputs/unit'), Path('deliverables/unit')
        self.raw, self.requests = self.root / 'raw', Path('requests.json')
        self.raw.mkdir(parents=True)
        request = {'filename': 'source.txt', 'url': 'https://www.twse.com.tw/example'}
        cfg = {'output_directory': str(self.raw), 'allowed_hosts': ['www.twse.com.tw'], 'requests': [request]}
        self.requests.write_text(json.dumps(cfg))
        self.protocol = Path('protocol.json')
        self.protocol.write_text('{"unit_fixture":true}')
        self.body, self.header = b'original frozen source', b'HTTP/2 200\n'
        (self.raw / 'source.txt').write_bytes(self.body)
        (self.raw / 'source.txt.headers').write_bytes(self.header)
        sha = lambda data: hashlib.sha256(data).hexdigest()
        row = {'request': request, 'transport': 'WSL native curl; verified HTTPS; two workers', 'http_status': 200,
               'exit_code': 0, 'sha256': sha(self.body), 'headers_sha256': sha(self.header)}
        (self.raw / 'source.txt.meta.json').write_text(json.dumps(row))
        (self.raw / 'results.json').write_text(json.dumps({'config_sha256': sha(self.requests.read_bytes()), 'workers': 2, 'requests': [row]}))
        entries = {'requests.json': self.requests, 'protocol.json': self.protocol}
        entries.update({'raw/' + p.name: p for p in self.raw.iterdir()})
        package_sources(self.root, self.out, 'sources', entries)
        self.pkg = json.loads((self.out / 'sources_package.json').read_text())
        shutil.copyfile(self.pkg['archive'], self.pkg['retrieved'])
        Path(self.pkg['transfer_receipt']).write_text(json.dumps({'sha256': self.pkg['sha256'], 'roundtrip_verified': True}))
        self.patchers = [patch.object(b, 'ROOT', self.root), patch.object(b, 'OUT', self.out),
                         patch.object(b, 'REQUESTS', self.requests), patch.object(b, 'TAG', 'sources'),
                         patch.object(b, 'POLICY', self.protocol),
                         patch.object(b, 'policy', return_value={'resource_bound': {'initial_requests': 5}})]
        for p in self.patchers:
            p.start()
        self.network = patch('native_public_sources.subprocess.run', side_effect=AssertionError('No live source request allowed'))
        self.live = self.network.start()

    def tearDown(self):
        self.network.stop()
        for p in reversed(self.patchers):
            p.stop()
        os.chdir(self.cwd)
        self.temp.cleanup()

    def test_missing_raw_restores_exact_checkpoint_without_live_request(self):
        shutil.rmtree(self.raw)
        b.acquire()
        self.assertEqual((self.raw / 'source.txt').read_bytes(), self.body)
        self.assertEqual((self.raw / 'source.txt.headers').read_bytes(), self.header)
        self.live.assert_not_called()

    def test_modified_raw_is_rejected_without_overwrite_or_live_replacement(self):
        (self.raw / 'source.txt').write_bytes(b'different source')
        with self.assertRaisesRegex(ValueError, 'not overwritten'):
            b.acquire()
        self.assertEqual((self.raw / 'source.txt').read_bytes(), b'different source')
        self.live.assert_not_called()

    def test_corrupt_readback_is_rejected_before_live_request(self):
        with Path(self.pkg['retrieved']).open('ab') as f:
            f.write(b'changed archive')
        with self.assertRaises(ValueError):
            b.acquire()
        self.live.assert_not_called()

    def test_protocol_drift_prevents_any_source_access(self):
        with patch.object(b, 'policy', side_effect=ValueError('Frozen protocol drift')):
            with self.assertRaisesRegex(ValueError, 'Frozen protocol drift'):
                b.acquire()
        self.live.assert_not_called()

    def test_extra_file_cannot_replace_an_existing_frozen_package(self):
        original_archive = Path(self.pkg['archive']).read_bytes()
        (self.raw / 'extra.txt').write_bytes(b'unrecorded new source')
        with self.assertRaisesRegex(ValueError, 'not replaced'):
            b.package()
        self.assertEqual(Path(self.pkg['archive']).read_bytes(), original_archive)
        self.assertEqual(json.loads((self.out / 'sources_package.json').read_text())['sha256'], self.pkg['sha256'])
        self.live.assert_not_called()


if __name__ == '__main__':
    unittest.main()
