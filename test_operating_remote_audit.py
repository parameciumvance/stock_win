import hashlib
import contextlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
import operating_remote_audit as audit_module
from operating_remote_audit import guidance_tsmc, validate_observation


class RemoteAuditTests(unittest.TestCase):
    def test_repackaging_identical_sources_survives_wall_clock_change(self):
        real_localtime=time.localtime
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
            root=Path('inputs');root.mkdir()
            for name in ['one','two']:
                (root/name).mkdir();(root/name/'observation').write_bytes(b'fixed response')
            for name in ['operating_remote_sources.mjs','operating_remote_backup.mjs']:
                Path(name).write_text('// fixed source fixture')
            Path('configs').mkdir()
            for name in ['operating_remote_sources.json','operating_remote_followup_sources.json']:
                (Path('configs')/name).write_text('{}')
            protocol=Path('protocol.json');protocol.write_text('{}')
            with zipfile.ZipFile('prior.zip','w') as z:
                z.writestr('body',b'frozen')
                z.writestr('manifest.json',json.dumps({'body':hashlib.sha256(b'frozen').hexdigest()}))
            prior_sha=hashlib.sha256(Path('prior.zip').read_bytes()).hexdigest()
            for tag,key in [('operating_pilot_20261016','retrieved_path'),('operating_windows_recovery_20261016','retrieved')]:
                target=Path('deliverables')/tag;target.mkdir(parents=True)
                (target/'checkpoint.json').write_text(json.dumps({key:'prior.zip','sha256':prior_sha}))
            with patch.multiple(audit_module,ROOT=root,OUT=Path('out'),CONFIG=protocol,
                                FROZEN_SHA=hashlib.sha256(protocol.read_bytes()).hexdigest(),
                                BATCHES=['one','two'],ARCHIVE=root/'package.zip'):
                digests=[]
                for clock in [1700000000,1900000000]:
                    with patch('zipfile.time.localtime',side_effect=lambda seconds=None,c=clock:real_localtime(c if seconds is None else seconds)):
                        audit_module.package()
                    digests.append(hashlib.sha256((root/'package.zip').read_bytes()).hexdigest())
                self.assertEqual(digests[0],digests[1])

    def observation(self,body):
        return dict(url='https://www.sec.gov/test',http_status=403,sha256=hashlib.sha256(body).hexdigest(),size_bytes=len(body),
                    request_started_at='2026-10-16T14:00:00Z',observed_at='2026-10-16T14:00:01Z',transport='test')

    def test_http_403_body_is_observation_only(self):
        body=b'<html>Access denied</html>';record=self.observation(body)
        result=validate_observation(body,record)
        self.assertFalse(result['valid_source_response'])
        self.assertEqual(result['http_status'],403)

    def test_tampered_body_not_accepted_even_for_error(self):
        with self.assertRaisesRegex(ValueError,'bytes/hash'):
            validate_observation(b'changed',self.observation(b'original'))

    def test_request_clock_and_unknown_outcome_fail_closed(self):
        body=b'body';record=self.observation(body)
        record['observed_at']='2026-10-16T13:00:00Z'
        with self.assertRaisesRegex(ValueError,'clock'):validate_observation(body,record)
        record=self.observation(body);record['request_started_at']='2026-10-16T14:00:00'
        with self.assertRaisesRegex(ValueError,'clock'):validate_observation(body,record)
        record=self.observation(body);record['http_status']=None
        with self.assertRaisesRegex(ValueError,'HTTP outcome'):validate_observation(body,record)

    def test_guidance_keeps_target_and_timing_gate(self):
        text='for first quarter 2025 to be as follows: Gross profit margin is expected to be between 57% and 59%'
        result=guidance_tsmc(text)
        self.assertEqual(result['target_quarter'],'2025Q1')
        self.assertEqual((result['gross_margin_lower_pct'],result['gross_margin_upper_pct']),(57,59))
        self.assertFalse(result['timing_verified']);self.assertFalse(result['ready_for_evaluation'])
        for bad in [text.replace('first quarter 2025','second quarter 2025'),text+' '+text,text.replace('57% and 59%','60% and 59%')]:
            with self.assertRaises(ValueError):guidance_tsmc(bad)


if __name__=='__main__':unittest.main()
