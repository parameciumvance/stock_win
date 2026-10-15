import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from prospective_sources import calendar_days, verify_archive, fetch
from prospective_replay import independent_selection, next_entry, frozen
from prospective_journal import seal
import test_prospective_selection as fixtures


class ReplayTests(unittest.TestCase):
    def test_independent_rank_all_methods_and_unknown(self):
        fixture=fixtures.SelectionTests(); frame=fixture.matrix()
        from prospective_selection import select
        protocol=frozen()
        for f in (frame,frame.assign(vol20=float('nan')),frame.iloc[:99]):
            self.assertEqual(independent_selection(f,'2026-10-14'),select(f,'2026-10-14',protocol))

    def test_calendar_rejects_duplicates_wrong_month_and_failed_source(self):
        doc=dict(stat='ok',tables=[dict(date='115/10',fields=['日期'],data=[['2026/10/14'],['2026/10/15']])])
        self.assertEqual(calendar_days(json.dumps(doc),'2026-10','2026-10-14'),['2026-10-14'])
        for bad in ({'stat':'error'},dict(stat='ok',tables=[dict(date='115/09',fields=['日期'],data=[])])):
            with self.assertRaises(ValueError):calendar_days(json.dumps(bad),'2026-10','2026-10-15')
        doc['tables'][0]['data']*=2
        with self.assertRaises(ValueError):calendar_days(json.dumps(doc),'2026-10','2026-10-15')

    def test_archive_rejects_unlisted_and_changed_members(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'a.zip'
            for members,manifest in [({'a':b'ok'},{'a':hashlib.sha256(b'bad').hexdigest()}),({'a':b'ok','extra':b'x'},{'a':hashlib.sha256(b'ok').hexdigest()}),({'../escape':b'ok'},{'../escape':hashlib.sha256(b'ok').hexdigest()})]:
                with zipfile.ZipFile(path,'w') as z:
                    for n,b in members.items():z.writestr(n,b)
                    z.writestr('manifest.json',json.dumps(manifest))
                with self.assertRaises(ValueError):verify_archive(path,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_sealed_sources_and_unsupported_crossyear_fail_closed(self):
        from prospective_sources import acquire, archive
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaisesRegex(ValueError,'Cross-year'):acquire(root,'2027-01-15')
            (root/'journal/signal').mkdir(parents=True)
            (root/'journal/signal/2026-10-15.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Sealed run'):acquire(root,'2026-10-15')
            with self.assertRaisesRegex(ValueError,'Sealed run'):archive(root)

    def test_cache_hash_drift_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'raw').mkdir();(root/'raw/a').write_bytes(b'changed')
            (root/'raw/a.meta.json').write_text(json.dumps(dict(url='https://example.com',sha256='a'*64)))
            with self.assertRaisesRegex(ValueError,'cache drift'):fetch(root,'a','https://example.com')

    def test_forged_verified_status_not_enough(self):
        with tempfile.TemporaryDirectory() as d:
            now=datetime(2026,10,15,20,tzinfo=ZoneInfo('Asia/Taipei'))
            seal(d,'snapshot','raw',dict(raw_sha256='a'*64),now=now)
            payload=dict(signal_date='2026-10-15',status='complete',source_status='raw_replay_verified',protocol_sha256='b'*64,selection_manifest_sha256='c'*64,snapshot_records=['raw'])
            with self.assertRaises(FileNotFoundError):seal(d,'signal','2026-10-15',payload,now=now)
            self.assertFalse((Path(d)/'signal/2026-10-15.json').exists())

    def test_holiday_schedule_fails_closed(self):
        with self.assertRaises(ValueError):next_entry('{"stat":"ok","data":{"html":"115年"}}'.encode(),'2026-10-15')

if __name__=='__main__':unittest.main()

class LiveGateTests(unittest.TestCase):
    def test_manifest_tamper_rejected(self):
        from prospective_replay import validate_live_payload
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'manifests').mkdir();(root/'manifests'/('a'*64+'.json')).write_text('{}')
            with self.assertRaisesRegex(ValueError,'manifest hash'):
                validate_live_payload(root,dict(selection_manifest_sha256='a'*64),datetime.now(ZoneInfo('Asia/Taipei')))

    def test_entry_deadline_future_replay_and_date_drift(self):
        from unittest.mock import patch
        from prospective_replay import validate_live_payload
        import pandas as pd
        now=datetime(2026,10,15,22,tzinfo=ZoneInfo('Asia/Taipei'))
        for entry,verified,signal,error in [('2026-10-15T21:00:00+08:00','2026-10-15T21:00:00+08:00','2026-10-15','time boundary'),('2026-10-16T09:00:00+08:00','2026-10-15T23:00:00+08:00','2026-10-15','time boundary'),('2026-10-16T09:00:00+08:00','2026-10-15T21:00:00+08:00','2026-10-14','date/protocol')]:
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);(root/'manifests').mkdir()
                summary=dict(entry_at=entry,signal_date='2026-10-15',protocol_sha256='b'*64,source_last_observed_at='2026-10-15T20:00:00+08:00')
                manifest=dict(source_status='raw_replay_verified',summary=summary,verified_at=verified)
                body=json.dumps(manifest).encode();digest=hashlib.sha256(body).hexdigest();(root/'manifests'/f'{digest}.json').write_bytes(body)
                payload=dict(selection_manifest_sha256=digest,replay_root=d,signal_date=signal,protocol_sha256='b'*64)
                with patch('prospective_replay.rebuild',return_value=({},summary,pd.DataFrame())):
                    with self.assertRaisesRegex(ValueError,error):validate_live_payload(root,payload,now)
