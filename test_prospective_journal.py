import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from prospective_journal import seal, verify

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 14, 16, tzinfo=ZoneInfo('Asia/Taipei'))
    def payload(self):
        return dict(signal_date='2026-10-14', status='missing_inputs', protocol_sha256='a'*64)
    def test_immutable_and_replay(self):
        p = seal(self.root, 'signal', '2026-10-14', self.payload(), now=self.now)
        self.assertEqual(verify(p)['payload'], self.payload())
        with self.assertRaises(FileExistsError): seal(self.root, 'signal', '2026-10-14', self.payload(), now=self.now)
    def test_tamper(self):
        p = seal(self.root, 'snapshot', 'raw', {'value': 1}, now=self.now)
        obj = json.loads(p.read_text()); obj['record']['payload']['value'] = 2; p.write_text(json.dumps(obj))
        with self.assertRaises(ValueError): verify(p)
    def test_backdate(self):
        p = self.payload(); p['signal_date'] = '2026-10-13'
        with self.assertRaises(ValueError): seal(self.root, 'signal', 'old', p, now=self.now)
    def test_naive_clock(self):
        with self.assertRaises(ValueError): seal(self.root, 'snapshot', 'raw', {}, now=datetime(2026, 10, 14))
    def test_complete_needs_snapshot(self):
        p = self.payload(); p['status'] = 'complete'
        with self.assertRaisesRegex(ValueError, 'requires prior snapshots'): seal(self.root, 'signal', '2026-10-14', p, now=self.now)
    def test_future_snapshot(self):
        seal(self.root, 'snapshot', 'late', {}, now=self.now.replace(hour=17))
        p = self.payload(); p.update(status='complete', snapshot_records=['late'])
        with self.assertRaisesRegex(ValueError, 'after signal'): seal(self.root, 'signal', '2026-10-14', p, now=self.now)
    def test_cutoff_and_unsafe_key(self):
        with self.assertRaises(ValueError): seal(self.root, 'signal', 'early', self.payload(), now=self.now.replace(hour=14))
        with self.assertRaises(ValueError): seal(self.root, 'snapshot', '../bad', {}, now=self.now)

if __name__ == '__main__': unittest.main()
