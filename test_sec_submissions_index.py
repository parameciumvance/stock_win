import contextlib
import hashlib
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import operating_umc_locator as locator
import json
import unittest
from sec_submissions_index import locate_candidates


def fixture():
    return dict(cik='1033767',name='UNITED MICROELECTRONICS CORP',filings=dict(recent=dict(
        accessionNumber=['0000950170-25-006966','0000950170-25-006967'],filingDate=['2025-01-21','2025-01-21'],
        reportDate=['2025-01-21','2025-01-21'],acceptanceDateTime=['2025-01-21T16:03:58.000Z','2025-01-21T17:00:00.000Z'],
        form=['6-K','6-K/A'],primaryDocument=['6k_on_01212025.htm','amended.htm']),files=[]))


class IndexLocatorTests(unittest.TestCase):
    def test_repackaging_survives_mtime_changes_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.chdir(tmp):
            root=Path('inputs');root.mkdir()
            protocol=Path('protocol.json');protocol.write_text('{}')
            source=Path('source');source.write_bytes(b'fixed original response')
            with patch.multiple(locator,ROOT=root,OUT=Path('out'),PROTOCOL=protocol,FROZEN=hashlib.sha256(protocol.read_bytes()).hexdigest()):
                with patch.object(locator,'utcnow',return_value='2026-01-01T00:00:00Z'):
                    locator.make_package('test',{'raw/source':source})
                before=(root/'test_checkpoint.zip').read_bytes();receipt=Path('out/test_package.json').read_bytes()
                os.utime(source,(1900000000,1900000000))
                with patch.object(locator,'utcnow',return_value='2030-01-01T00:00:00Z'):
                    locator.make_package('test',{'raw/source':source})
                self.assertEqual(before,(root/'test_checkpoint.zip').read_bytes())
                self.assertEqual(receipt,Path('out/test_package.json').read_bytes())

    def locate(self,obj):
        return locate_candidates(json.dumps(obj).encode(),cik='0001033767',filing_date='2025-01-21')

    def test_locator_retains_event_report_date_and_unverified_clock(self):
        result=self.locate(fixture());self.assertEqual(len(result['candidates']),1)
        candidate=result['candidates'][0]
        self.assertEqual(candidate['report_date_as_reported'],'2025-01-21')
        self.assertEqual(candidate['acceptanceDateTime_as_reported'],'2025-01-21T16:03:58.000Z')
        self.assertFalse(candidate['acceptance_clock_verified']);self.assertFalse(candidate['earnings_quarter_verified'])
        self.assertFalse(result['ready_for_model'])
        self.assertEqual(candidate['complete_submission_url'],'https://www.sec.gov/Archives/edgar/data/1033767/000095017025006966/0000950170-25-006966.txt')

    def test_wrong_issuer_company_and_non_object_rejected(self):
        for bad in [dict(fixture(),cik='1046179'),dict(fixture(),name='OTHER COMPANY'),[]]:
            with self.assertRaises(ValueError):self.locate(bad)

    def test_misaligned_arrays_and_duplicate_accessions_rejected(self):
        bad=fixture();bad['filings']['recent']['form'].pop()
        with self.assertRaisesRegex(ValueError,'Misaligned'):self.locate(bad)
        bad=fixture();bad['filings']['recent']['accessionNumber'][1]=bad['filings']['recent']['accessionNumber'][0]
        with self.assertRaisesRegex(ValueError,'Duplicate accession'):self.locate(bad)

    def test_naive_clock_and_path_injection_rejected(self):
        for key,value in [('acceptanceDateTime','2025-01-21T16:03:58'),('accessionNumber','../../other'),('primaryDocument','../other.htm')]:
            bad=fixture();bad['filings']['recent'][key][0]=value
            with self.assertRaises(ValueError):self.locate(bad)

    def test_missing_target_keeps_covering_archived_index(self):
        obj=fixture();obj['filings']['recent']['filingDate']=['2026-01-21','2026-01-21']
        archived=dict(name='CIK0001033767-submissions-001.json',filingFrom='2024-01-01',filingTo='2025-12-31')
        obj['filings']['files']=[archived]
        result=self.locate(obj);self.assertEqual(result['candidates'],[])
        self.assertEqual(result['archived_files_covering_target'],[archived]);self.assertFalse(result['ready_for_model'])

    def test_duplicate_json_keys_fail_instead_of_overwriting(self):
        body=json.dumps(fixture()).replace('"name":','"cik":"1033767","name":',1).encode()
        with self.assertRaisesRegex(ValueError,'Duplicate JSON key'):
            locate_candidates(body,cik='0001033767',filing_date='2025-01-21')


if __name__=='__main__':unittest.main()
