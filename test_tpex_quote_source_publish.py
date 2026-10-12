"""A semantically bad quote reply must not replace an existing verified snapshot."""
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from acquire_tpex_month import fetch

class QuoteSourcePublishTests(unittest.TestCase):
    def test_invalid_reply_preserves_raw_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'quotes.json';meta=path.with_suffix('.json.meta.json')
            path.write_bytes(b'previous verified raw');meta.write_bytes(b'previous metadata')
            def download(args,**kwargs):
                Path(args[-1]).write_text(json.dumps({'stat':'unavailable'}))
                return SimpleNamespace(returncode=0,stderr='')
            def validate(doc):
                if doc['stat']!='ok':raise ValueError('Quote source unavailable')
            with patch('acquire_tpex_month.subprocess.run',side_effect=download):
                with self.assertRaises(ValueError):fetch('https://example.invalid',path,validator=validate)
            self.assertEqual(path.read_bytes(),b'previous verified raw')
            self.assertEqual(meta.read_bytes(),b'previous metadata')

if __name__=='__main__':unittest.main()
