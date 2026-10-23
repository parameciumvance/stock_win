"""Synthetic labelled terms pointers; no actual sources, archives or requests."""
import copy
import hashlib
import json
import unittest

from frontier_cb_documents_sources import terms_pointer, select_terms, CONTROL_CODES
from test_frontier_cb_documents_replay import cohort


def fixture():
    controls, bodies, records = cohort()
    members, selected, requests = {}, [], []
    original = dict(controls=[])
    for control, record in zip(controls, records, strict=True):
        code = control['bond_code']
        filename = control['request_filename']
        literal = '/nas/t56/t56bondb/actual_' + code + '_terms.pdf'
        body = bodies[filename].replace(b'/actual/issuance.html?a=1&amp;b=2', literal.encode())
        body = body.replace('實際發行辦法'.encode(), ('original_' + code + '.pdf').encode())
        meta = dict(record, sha256=hashlib.sha256(body).hexdigest())
        member = 'raw/' + filename
        members[member] = body
        members[member + '.meta.json'] = json.dumps(meta).encode()
        series = '7' if code == '99587' else '1'
        original['controls'].append(dict(metadata_20261020_original=dict(SeriesNumber=series)))
        proof = terms_pointer(body, control, series)
        selected.append(dict(bond_code=code, source_body_sha256=meta['sha256'], source_member=member,
                             identity_and_pointer=proof))
        requests.append(dict(filename=code + '_terms.pdf', url=proof['url'], method='GET'))
    initial = dict(controls_bond_codes=CONTROL_CODES, controls=controls)
    selection = dict(controls_bond_codes=CONTROL_CODES, controls=selected)
    return members, initial, original, selection, requests


class LabelledTermsPointerTests(unittest.TestCase):
    def test_only_labelled_terms_anchor_is_selected_without_trustee_navigation_or_date_inference(self):
        members, initial, original, _, _ = fixture()
        control = initial['controls'][0]
        body = members['raw/' + control['request_filename']]
        body = b'<a href="/nas/t56/t56bondb/navigation.pdf">navigation</a>' + body
        proof = terms_pointer(body, control, original['controls'][0]['metadata_20261020_original']['SeriesNumber'])
        self.assertEqual(proof['literal_href'], '/nas/t56/t56bondb/actual_99587_terms.pdf')
        self.assertEqual(proof['url'], 'https://mopsov.twse.com.tw/nas/t56/t56bondb/actual_99587_terms.pdf')
        self.assertEqual(proof['anchor_text'], 'original_99587.pdf')
        self.assertEqual(proof['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertFalse(proof['response_is_PDF_verified'])
        self.assertFalse(proof['filename_date_meaning_inferred'])
        self.assertFalse(proof['source_gate_passed'])

    def test_wrong_bond_name_series_or_duplicate_identity_is_rejected(self):
        members, initial, _, _, _ = fixture()
        control = initial['controls'][0]
        body = members['raw/' + control['request_filename']]
        for altered, series in [(body.replace(b'99587', b'99588'), '7'),
                                (body.replace(control['bond_name'].encode(), '別家公司債券'.encode()), '7'),
                                (body, '8'),
                                (body.replace(b'</table>', '<tr><td>債券代碼：99587</td></tr></table>'.encode()), '7')]:
            with self.subTest(series=series, prefix=altered[:40]), self.assertRaises(ValueError):
                terms_pointer(altered, control, series)

    def test_error_page_missing_label_or_two_terms_anchors_cannot_be_empty_contract_evidence(self):
        members, initial, _, _, _ = fixture()
        control = initial['controls'][0]
        body = members['raw/' + control['request_filename']]
        alternatives = [b'<html>upstream error</html>',
                        body.replace('發行辦法之內容：'.encode(), '未知標籤：'.encode()),
                        body.replace(b'original_99587.pdf</a>',
                            b'original_99587.pdf</a><a href="/nas/t56/t56bondb/other.pdf">other</a>')]
        for altered in alternatives:
            with self.subTest(body=altered[:40]), self.assertRaises(ValueError):
                terms_pointer(altered, control, '7')

    def test_html_base_foreign_query_or_traversal_pointer_is_rejected_before_get(self):
        members, initial, _, _, _ = fixture()
        control = initial['controls'][0]
        body = members['raw/' + control['request_filename']]
        original = b'/nas/t56/t56bondb/actual_99587_terms.pdf'
        invalid = [b'https://foreign.example/terms.pdf', b'/nas/t56/t56bondb/../other.pdf',
                   original + b'?guessed=1', b'javascript:requestTerms()', b'/other/terms.pdf']
        for href in invalid:
            with self.subTest(href=href), self.assertRaises(ValueError):
                terms_pointer(body.replace(original, href), control, '7')
        with self.assertRaisesRegex(ValueError, 'base'):
            terms_pointer(b'<base href="https://foreign.example/">' + body, control, '7')

    def test_invalid_utf8_is_not_silently_replaced(self):
        members, initial, _, _, _ = fixture()
        control = initial['controls'][0]
        body = members['raw/' + control['request_filename']]
        with self.assertRaises(UnicodeError):
            terms_pointer(body + b'\xff', control, '7')

    def test_all_three_exact_gets_remain_bound_to_source_bodies_and_pointer_proofs(self):
        args = fixture()
        result = select_terms(*args)
        self.assertEqual(result['requests'], 3)
        self.assertEqual([p['bond_code'] for p in result['controls']], CONTROL_CODES)
        self.assertFalse(result['actual_terms_or_PDF_content_verified'])
        self.assertFalse(result['source_gate_passed'])
        for failure in ('method', 'different_url', 'body_sha', 'changed_proof', 'drop_case'):
            members, initial, original, selected, requests = fixture()
            if failure == 'method':
                requests[0]['method'] = 'POST'
            elif failure == 'different_url':
                requests[0]['url'] = requests[1]['url']
            elif failure == 'body_sha':
                selected['controls'][0]['source_body_sha256'] = 'a' * 64
            elif failure == 'changed_proof':
                selected['controls'][0]['identity_and_pointer']['literal_href'] = '/guessed.pdf'
            else:
                selected['controls'].pop()
                requests.pop()
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                select_terms(members, initial, original, selected, requests)


if __name__ == '__main__':
    unittest.main()
