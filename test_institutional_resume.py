import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from resume_institutional import restore_archive


class ArchiveRestoreTests(unittest.TestCase):
    def bundle(self, root, name, value=b'input'):
        p = root / 'bundle.zip'
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr(name, value)
            z.writestr('SHA256MANIFEST.json', json.dumps({name: hashlib.sha256(value).hexdigest()}))
        return p, hashlib.sha256(p.read_bytes()).hexdigest()

    def test_unsafe_archive_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            p, sha = self.bundle(Path(folder), '../escape.csv')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                restore_archive(p, sha)

    def test_different_existing_input_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'existing.csv'; target.write_bytes(b'old')
            p, sha = self.bundle(root, 'existing.csv')
            previous = Path.cwd()
            try:
                os.chdir(root)
                with self.assertRaisesRegex(ValueError, 'Existing input differs'):
                    restore_archive(p, sha)
            finally:
                os.chdir(previous)
            self.assertEqual(target.read_bytes(), b'old')

    def test_wrong_bundle_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p, _ = self.bundle(Path(folder), 'inputs/test.csv')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                restore_archive(p, '0' * 64)


if __name__ == '__main__':
    unittest.main()
