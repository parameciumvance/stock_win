import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ipo_adjudication import annual_control
from native_public_sources import acquire
from research_runtime import sha256


class NativeTransportTests(unittest.TestCase):
    def fixture(self):
        cfg=dict(output_directory='inputs/native_test',allowed_hosts=['example.com'],requests=[dict(filename='raw.body',url='https://example.com/source')])
        Path('cfg.json').write_text(json.dumps(cfg));return Path(cfg['output_directory'])

    def test_preserves_nul_and_refuses_changed_cached_body(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.chdir(temp):
            root=self.fixture()
            def fetch(cmd,**kwargs):
                Path(cmd[cmd.index('--output')+1]).write_bytes(b'original\x00bytes')
                Path(cmd[cmd.index('--dump-header')+1]).write_text('HTTP/1.1 200 OK\n')
                return subprocess.CompletedProcess(cmd,0,b'{"http_code":200}',b'')
            with patch('native_public_sources.subprocess.run',side_effect=fetch) as transport,contextlib.redirect_stdout(io.StringIO()):
                acquire('cfg.json');result=json.loads((root/'results.json').read_text())
                self.assertEqual((root/'raw.body').read_bytes(),b'original\x00bytes')
                self.assertEqual(result['requests'][0]['sha256'],sha256(root/'raw.body'))
                (root/'raw.body').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'drift'):acquire('cfg.json')
                self.assertEqual(transport.call_count,1)

    def test_tls_failure_saved_without_retry_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.chdir(temp):
            root=self.fixture()
            with patch('native_public_sources.subprocess.run',return_value=subprocess.CompletedProcess([],60,b'{"http_code":0}',b'SSL certificate problem')) as transport,contextlib.redirect_stdout(io.StringIO()):
                acquire('cfg.json');acquire('cfg.json')
                r=json.loads((root/'results.json').read_text())['requests'][0]
                self.assertEqual(r['exit_code'],60);self.assertIn('SSL',r['stderr']);self.assertEqual(transport.call_count,1)
                self.assertFalse((root/'raw.body').exists())

    def test_unrecorded_partial_file_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.chdir(temp):
            root=self.fixture();root.mkdir(parents=True);(root/'raw.body').write_text('partial')
            with patch('native_public_sources.subprocess.run') as transport:
                with self.assertRaisesRegex(ValueError,'partial'):acquire('cfg.json')
                transport.assert_not_called()


class PrimaryControlTests(unittest.TestCase):
    def extract(self,text):
        reader=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:text)])
        with patch('pypdf.PdfReader',return_value=reader):return annual_control(b'%PDF-fake')

    def test_numeric_only_annual_row_never_verifies_issuer_identity(self):
        r=self.extract('101 亂碼 626 238 148,988,000 114/09/02 0.25')
        self.assertFalse(r['verified']);self.assertEqual(len(r['numeric_candidates']),1)

    def test_wrong_annual_price_or_odds_cannot_pass(self):
        for text in ['中華資安國際 初次上市 元大證券 626 238 148,988,000 114/09/02 3.55','中華資安國際 初次上市 元大證券 626 239 148,988,000 114/09/02 0.25']:
            self.assertFalse(self.extract(text)['verified'])

    def test_complete_primary_row_with_identity_passes(self):
        self.assertTrue(self.extract('101 中華資安國際 初次上市 元大證券 626 238 148,988,000 114/09/02 0.25')['verified'])

    def test_html_denial_is_not_a_pdf_control(self):
        self.assertFalse(annual_control(b'<html>Access denied</html>')['verified'])


if __name__=='__main__':unittest.main()
