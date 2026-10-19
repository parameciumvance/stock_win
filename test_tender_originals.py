import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research_runtime import sha256
from tender_originals import notice, pdf_request, request_for_pointer
from tender_paced_sources import acquire, quota_body


def announcement(content, symbol='6938'):
    return ('<table><tr><td>被收購公司代號：'+symbol+'</td></tr>'
            '<tr><td>事實發生日：113/08/05</td></tr>'
            '<tr><td><pre>公開收購期間屆滿</pre></td></tr>'
            '<tr><td><pre>'+content+'</pre></td></tr></table>').encode()


class OriginalContentTests(unittest.TestCase):
    def test_expiry_quantity_and_time_are_not_actual_settlement_or_pit(self):
        r=notice(announcement('實際成交數量：1,949,647股'), '6938')
        self.assertEqual(r['declared_actual_shares'],1949647)
        self.assertFalse(r['actual_broker_settlement_verified'])
        self.assertFalse(r['first_public_availability_verified'])

    def test_wei_form_zero_not_missing_and_repeated_zero_not_conflict(self):
        r=notice(announcement('實際成交數量為0股，未成就。\n實際成交數量為0股。'),'6938')
        self.assertEqual(r['declared_actual_shares'],0)

    def test_unknown_quantity_not_zero(self):
        self.assertIsNone(notice(announcement('實際成交數量：尚未公告'),'6938')['declared_actual_shares'])

    def test_malformed_share_comma_not_silently_repaired(self):
        self.assertIsNone(notice(announcement('實際成交數量：1,94股'),'6938')['declared_actual_shares'])

    def test_ambiguous_quantity_and_wrong_target_rejected(self):
        with self.assertRaises(ValueError):
            notice(announcement('實際成交數量：10股。實際成交數量：20股。'),'6938')
        with self.assertRaises(ValueError):
            notice(announcement('實際成交數量：10股',symbol='9999'),'6938')

    def test_navigation_or_quota_not_announcement(self):
        for body in [b'<a>Home</a>','查詢過量，請稍後再查詢!'.encode()]:
            with self.assertRaises(ValueError):
                notice(body,'6938')

    def test_generated_pdf_link_must_match_frozen_document_and_host(self):
        expected='202400_6214_6938_B2d_1.pdf'
        body=('<a href="/pdf/'+expected[:-4]+'_20261019_082717.pdf">檔案</a>').encode('big5')
        self.assertEqual(pdf_request(body,expected),'https://doc.twse.com.tw/pdf/'+expected[:-4]+'_20261019_082717.pdf')
        for bad in [b'<a href="https://example.org/fake.pdf">x</a>',b'<a href="/pdf/other.pdf">x</a>',b'<script>location="/pdf/other.pdf"</script>']:
            with self.assertRaises(ValueError):
                pdf_request(bad,expected)

    def test_http200_quota_never_generates_pdf(self):
        for encoding in ['big5','utf-8']:
            body='查詢過量，請稍後再查詢!'.encode(encoding)
            self.assertTrue(quota_body(body))
            with self.assertRaises(ValueError):
                pdf_request(body,'expected.pdf')

    def test_opaque_form_date_is_preserved_separately(self):
        action='; '.join('document.form2.'+k+'.value="'+v+'"' for k,v in [('step','2'),('COMPANY_ID2','6938'),('SEQ_NO','1'),('DATE','20240730'),('TYPE','9')])
        req=request_for_pointer(dict(links=[],actions=[action]),dict(filename=None),'6938',7)
        self.assertIn('DATE=20240730',req['data'])
        self.assertNotIn('20240806',req['data'])
        with self.assertRaises(ValueError):
            request_for_pointer(dict(links=[],actions=[action]),dict(filename=None),'9999',7)


class PacedRecoveryTests(unittest.TestCase):
    def test_pace_budget_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'cfg.json'
            p.write_text(json.dumps(dict(output_directory='inputs/test_unused',allowed_hosts=['doc.twse.com.tw'],requests=[dict(filename='a.html',url='https://doc.twse.com.tw/a')],request_interval_seconds=0)))
            with patch('tender_paced_sources.subprocess.run') as transport, self.assertRaises(ValueError):
                acquire(p)
            transport.assert_not_called()

    def test_cached_transport_failure_stops_pending_requests_without_retries(self):
        with tempfile.TemporaryDirectory(dir='inputs') as temp:
            root=Path(temp).relative_to(Path.cwd()) if Path(temp).is_absolute() else Path(temp)
            raw=root/'raw';raw.mkdir()
            req=dict(filename='a.html',url='https://doc.twse.com.tw/a')
            first=dict(request=req,http_status=0,exit_code=6)
            (raw/'a.html.meta.json').write_text(json.dumps(first))
            cfg=root/'cfg.json';cfg.write_text(json.dumps(dict(output_directory=str(raw),allowed_hosts=['doc.twse.com.tw'],request_interval_seconds=4,requests=[req,dict(filename='b.html',url='https://doc.twse.com.tw/b')])))
            with patch('tender_paced_sources.subprocess.run') as transport, contextlib.redirect_stdout(io.StringIO()):
                acquire(cfg)
            transport.assert_not_called()
            r=json.loads((raw/'results.json').read_text())['requests'][1]
            self.assertIsNone(r['request_started_at'])
            self.assertIn('not_requested_reason',r)

    def test_cached_response_tampering_fails_instead_of_redownload(self):
        with tempfile.TemporaryDirectory(dir='inputs') as temp:
            root=Path(temp).relative_to(Path.cwd()) if Path(temp).is_absolute() else Path(temp)
            raw=root/'raw';raw.mkdir();body=raw/'a.html';body.write_bytes(b'original')
            req=dict(filename='a.html',url='https://doc.twse.com.tw/a')
            (raw/'a.html.meta.json').write_text(json.dumps(dict(request=req,http_status=200,exit_code=0,sha256=sha256(body))))
            body.write_bytes(b'replacement')
            cfg=root/'cfg.json';cfg.write_text(json.dumps(dict(output_directory=str(raw),allowed_hosts=['doc.twse.com.tw'],request_interval_seconds=4,requests=[req])))
            with patch('tender_paced_sources.subprocess.run') as transport, self.assertRaisesRegex(ValueError,'Cached recovery bytes differ'):
                acquire(cfg)
            transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
