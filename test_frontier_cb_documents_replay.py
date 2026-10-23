"""Synthetic issuance-page identities and preserved evidence; never sources."""
import copy
import hashlib
from html import escape
import unittest
from urllib.parse import urlencode

from frontier_cb_documents_replay import inspect_issuance, replay_issuances


def control():
    query = [('TYPEK', ''), ('bond_id', '99587'), ('bond_kind', '5'), ('bond_subn', '$M00000001'),
             ('bond_yrn', '7'), ('come', '2'), ('encodeURIComponent', '1'), ('firstin', 'ture'),
             ('issuer_stock_code', '9958'), ('monyr_reg', '202609'), ('pg', ''), ('step', '0'), ('tg', '')]
    return dict(bond_code='99587', issuer='9958', issuer_name='世紀鋼',
                bond_name='世紀鋼鐵結構股份有限公司國內第七次無擔保轉換公司債',
                listed_date='113/10/28',
                issuance_url='https://mopsov.twse.com.tw/mops/web/t120sg01?' + urlencode(query),
                request_filename='99587_issuance.html')


def fixture(**changes):
    row = control()
    values = dict(code=row['bond_code'], name=row['bond_name'], series='7', listed=row['listed_date'])
    values.update(changes)
    raw = ('''<html><meta charset="utf-8"><table>
<tr><td>債券代碼：''' + escape(values['code']) + '''</td></tr>
<tr><td>債券中文名稱：''' + escape(values['name']) + '''</td></tr>
<tr><td>債券期別：第 ''' + escape(values['series']) + ''' 期　券</td></tr>
<tr><td>掛牌日期：''' + escape(values['listed']) + '''</td></tr>
<tr><td>發行辦法之內容：<a href="/actual/issuance.html?a=1&amp;b=2">實際發行辦法</a></td></tr>
<tr><td>受託契約內容：<a href="./actual-trustee.html">實際受託契約</a></td></tr>
<tr><td>其他原欄位：原資料不得因無關holder put而丟棄</td></tr></table>
<form action="/actual_form"><input name="bond_id" value="99587"><input name="bond_id" value="original"></form>
<script src="/actual.js">throw Error('never execute');</script><img src="/actual.png"></html>''').encode()
    return raw, row


HEADERS = b'Content-Type: text/html; charset=utf-8\r\n'


def cohort():
    controls, bodies, records = [], {}, []
    for code, issuer, series, name, listed in [
        ('99587', '9958', '7', '世紀鋼鐵結構股份有限公司國內第七次無擔保轉換公司債', '113/10/28'),
        ('68351', '6835', '1', '圓裕股份有限公司國內第一次無擔保轉換公司債', '113/11/01'),
        ('68741', '6874', '1', '倍力資訊股份有限公司國內第一次無擔保轉換公司債', '113/11/04'),
    ]:
        body, expected = fixture(code=code, name=name, series=series, listed=listed)
        url = expected['issuance_url'].replace('99587', code).replace('issuer_stock_code=9958', 'issuer_stock_code=' + issuer)
        url = url.replace('bond_yrn=7', 'bond_yrn=' + series)
        expected.update(bond_code=code, issuer=issuer, issuer_name={'9958': '世紀鋼', '6835': '圓裕', '6874': '倍力'}[issuer],
                        bond_name=name, listed_date=listed,
                        issuance_url=url, request_filename=code + '_issuance.html')
        controls.append(expected)
        bodies[expected['request_filename']] = body
        records.append(dict(request=dict(filename=expected['request_filename'], url=url, method='GET'),
                            http_status=200, exit_code=0, sha256=hashlib.sha256(body).hexdigest(),
                            curl=dict(url_effective=url)))
    return controls, bodies, records


class IssuanceReplayTests(unittest.TestCase):
    def test_identity_matches_exact_bond_series_name_listing_and_all_html_evidence_survives(self):
        body, expected = fixture()
        full, summary = inspect_issuance(body, expected, expected['issuance_url'], HEADERS)
        self.assertEqual(full['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(summary['identity']['bond_code'], '99587')
        self.assertEqual(summary['identity']['issuer'], '9958')
        self.assertEqual(summary['identity']['bond_name'], expected['bond_name'])
        self.assertEqual(str(summary['identity']['series']), '7')
        self.assertEqual(summary['identity']['listed_date'], '113/10/28')
        self.assertTrue(summary['identity']['identity_verified'])
        self.assertIn('其他原欄位', full['page_text'])
        self.assertEqual(len(full['rows']), 7)
        self.assertEqual([c['attributes']['value'] for c in full['forms'][0]['controls']], ['99587', 'original'])
        self.assertEqual(full['forms'][0]['action'], '/actual_form')
        self.assertEqual([p['value'] for p in full['pointers']],
                         ['/actual/issuance.html?a=1&b=2', './actual-trustee.html', '/actual.js', '/actual.png'])
        self.assertFalse(summary['source_gate_passed'])

    def test_wrong_bond_name_series_or_listed_date_cannot_be_identity_verified(self):
        for changes in [dict(code='99588'), dict(name='另一家公司另一債券'), dict(series='8'), dict(listed='113/10/29')]:
            body, expected = fixture(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                inspect_issuance(body, expected, expected['issuance_url'], HEADERS)

    def test_issuer_or_effective_url_query_cannot_drift_even_when_html_labels_match(self):
        for failure in ('issuer', 'bond', 'effective', 'duplicate', 'foreign'):
            body, expected = fixture()
            effective = expected['issuance_url']
            if failure == 'issuer':
                expected['issuer'] = '1234'
            elif failure == 'bond':
                expected['bond_code'] = '99588'
            elif failure == 'effective':
                effective = effective.replace('monyr_reg=202609', 'monyr_reg=202610')
            elif failure == 'duplicate':
                effective += '&bond_id=99587'
                expected['issuance_url'] = effective
            else:
                effective = effective.replace('mopsov.twse.com.tw', 'foreign.example')
                expected['issuance_url'] = effective
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                inspect_issuance(body, expected, effective, HEADERS)

    def test_error_page_missing_or_duplicate_identity_is_not_an_empty_contract_result(self):
        good, expected = fixture()
        wrong = [b'<html><body>upstream error</body></html>',
                 good.replace('債券代碼：99587'.encode(), '沒有債券代碼'.encode()),
                 good.replace(b'</table>', '<tr><td>債券代碼：99587</td></tr></table>'.encode())]
        for body in wrong:
            with self.subTest(body=body[:40]), self.assertRaises(ValueError):
                inspect_issuance(body, expected, expected['issuance_url'], HEADERS)

    def test_strict_declared_utf8_is_required_without_replacement_or_big5_fallback(self):
        good, expected = fixture()
        cases = [(good.replace('世紀鋼'.encode(), b'\xff'), HEADERS),
                 (good, b'Content-Type: text/html;charset=big5\r\n'),
                 (good.replace(b'charset="utf-8"', b'charset="big5"'), HEADERS)]
        for body, headers in cases:
            with self.subTest(headers=headers), self.assertRaises((ValueError, UnicodeError)):
                inspect_issuance(body, expected, expected['issuance_url'], headers)

    def test_valid_identity_without_terms_links_leaves_source_gate_false(self):
        body, expected = fixture()
        body = body.replace(b'<a href="/actual/issuance.html?a=1&amp;b=2">', b'<span>')
        body = body.replace(b'<a href="./actual-trustee.html">', b'<span>').replace(b'</a>', b'</span>')
        full, summary = inspect_issuance(body, expected, expected['issuance_url'], HEADERS)
        self.assertEqual(summary['document_pointers'], [])
        self.assertTrue(summary['identity']['identity_verified'])
        self.assertFalse(summary['source_gate_passed'])
        self.assertIn('發行辦法之內容', full['page_text'])

    def test_original_terms_and_trustee_pointers_are_evidence_not_pdf_or_put_contract_claims(self):
        body, expected = fixture()
        full, summary = inspect_issuance(body, expected, expected['issuance_url'], HEADERS)
        pointers = summary['document_pointers']
        self.assertEqual([p['label'] for p in pointers], ['發行辦法之內容', '受託契約內容'])
        self.assertEqual(pointers[0]['value'], '/actual/issuance.html?a=1&b=2')
        self.assertEqual(pointers[0]['source_literal'], '/actual/issuance.html?a=1&amp;b=2')
        self.assertEqual(pointers[0]['resolved_url'], 'https://mopsov.twse.com.tw/actual/issuance.html?a=1&b=2')
        for pointer in pointers:
            self.assertFalse(pointer['followup_authorized'])
            self.assertFalse(pointer['document_content_verified'])
            self.assertFalse(pointer['PDF_verified'])
        self.assertFalse(summary['javascript_executed'])
        self.assertTrue(summary['all_returned_html_rows_preserved'])

    def test_three_control_replay_preserves_every_case_after_transport_and_body_identity_checks(self):
        controls, bodies, records = cohort()
        full, summaries = replay_issuances(controls, bodies, records,
                                          headers={name: HEADERS for name in bodies})
        self.assertEqual(len(full), 3)
        self.assertEqual(len(summaries), 3)
        self.assertEqual([s['identity']['bond_code'] for s in summaries], ['99587', '68351', '68741'])
        self.assertTrue(all(s['source_gate_passed'] is False for s in summaries))

    def test_missing_extra_duplicate_failed_or_changed_control_cannot_shrink_the_three_case_replay(self):
        for failure in ('drop_case', 'missing_body', 'extra_body', 'duplicate_record', 'http', 'exit', 'sha', 'url'):
            controls, bodies, records = cohort()
            if failure == 'drop_case':
                controls.pop()
                records.pop()
                bodies.pop('68741_issuance.html')
            elif failure == 'missing_body':
                bodies.pop('68741_issuance.html')
            elif failure == 'extra_body':
                bodies['unrequested.html'] = b'<html>unrequested</html>'
            elif failure == 'duplicate_record':
                records[1] = copy.deepcopy(records[0])
            elif failure == 'http':
                records[0]['http_status'] = 503
            elif failure == 'exit':
                records[0]['exit_code'] = 28
            elif failure == 'sha':
                records[0]['sha256'] = 'a' * 64
            else:
                records[0]['request']['url'] = records[0]['request']['url'].replace('monyr_reg=202609', 'monyr_reg=202610')
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                replay_issuances(controls, bodies, records, headers={name: HEADERS for name in bodies})


if __name__ == '__main__':
    unittest.main()
