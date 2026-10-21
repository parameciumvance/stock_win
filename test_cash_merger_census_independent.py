"""Synthetic census evidence controls; no archived source or prices are read."""

import copy
import hashlib
from html import escape
from io import BytesIO
import json
import unittest
import zipfile

from cash_merger_census_independent import (
    _transport, check_allocation, check_annotations, read_identity,
    read_title_rows, verify_archive_bytes,
)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def row(issuer='6674', clock='20:25:55', subject='董事會決議現金股份轉換', sequence='5'):
    return dict(
        CDATE='115/09/18', COMPANY_NAME='甲公司', AN_NAME='發行有價證券、減資、併購或股份轉交換',
        CODE_NAME='其他業', AN_CODE='M11', CTIME=clock, TYPEK='上市', SUBJECT=subject,
        COMPANY_ID=issuer,
        HYPERLINK='https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1?firstin=true&stp=1&step=1'
                  '&SEQ_NO='+sequence+'&SPOKE_TIME='+clock.replace(':', '')
                  +'&SPOKE_DATE=20260918&COMPANY_ID='+issuer,
    )


def event_id(source):
    seq = source['HYPERLINK'].split('SEQ_NO=')[1].split('&')[0]
    return f'M11:{source["COMPANY_ID"]}:2026-09-18:{source["CTIME"].replace(":", "")}:{seq}'


def encode_payload(rows):
    return json.dumps(dict(data=rows, message=['回傳成功'], status='success'),
                      ensure_ascii=False).encode()


def fixtures():
    rows = [
        row(subject='董事會決議現金股份轉換\r\n普通股退出'),
        row('3008', '17:52:38', '增資發行新股進行股份轉換', '4'),
        row('5203', '15:26:12', '撤銷子公司簡易合併', '1'),
        row('6472', '16:58:56', '員工認股權增資基準日', '1'),
    ]
    quarter = encode_payload(rows)
    selected = []
    requests = []
    for number, source in enumerate(rows[:3]):
        item = dict(event_id=event_id(source), index_original_fields=copy.deepcopy(source))
        if number == 2:
            item['original_source'] = dict(archive_sha256='a'*64, member='raw/cancel.html')
        else:
            item['new_filename'] = f'doc{number+1}.html'
            requests.append(dict(filename=item['new_filename'], url=source['HYPERLINK']))
        selected.append(item)
    return quarter, rows, dict(source_quarter_sha256=digest(quarter), rows=selected), requests


def check(quarter, selection, requests, counts=(3, 2, 1)):
    return check_allocation(quarter, selection, json.dumps(dict(requests=requests)).encode(),
                            expected_counts=counts, expected_quarter_count=4)


def document(source, description='1.董事會決議日期:115/09/18\n2.每股現金18.50元。\n3.條件未成就可終止。'):
    sequence = source['HYPERLINK'].split('SEQ_NO=')[1].split('&')[0]
    return (
        '<html><table><tr><td>本資料由 (上市公司) '+source['COMPANY_ID']+' '
        +escape(source['COMPANY_NAME'])+' 公司提供</td></tr></table>'
        '<table><tr><th>序號</th><td>'+sequence+'</td><th>發言日期</th><td>'+source['CDATE']
        +'</td><th>發言時間</th><td>'+source['CTIME']+'</td></tr>'
        '<tr><th>主旨</th><td>'+escape(source['SUBJECT'])+'</td></tr>'
        '<tr><th>說明</th><td><pre>'+escape(description)+'</pre></td></tr></table></html>'
    ).encode()


def annotation_context():
    _, sources, _, _ = fixtures()
    docs, descriptions, annotations, deals = [], {}, [], []
    texts = [
        '1.董事會決議日期:115/09/18\n2.每股現金18.50元。\n3.付款仍附條件。',
        '1.董事會決議日期:115/09/18\n2.增資發行新股進行股份轉換，非全現金。',
        '1.董事會決議撤銷日期:115/09/18\n2.撤銷100%子公司簡易合併。',
    ]
    dispositions = ['cash_conversion_candidate', 'stock_consideration', 'canceled_intragroup']
    for number, (source, text, disposition) in enumerate(zip(sources[:3], texts, dispositions)):
        identity, description = read_identity(document(source, text), source)
        docs.append(identity)
        descriptions[identity['event_id']] = description
        deal = f'deal_{number}'
        annotations.append(dict(event_id=identity['event_id'], body_sha256=identity['body_sha256'],
                                description_sha256=identity['description_sha256'],
                                deal_id=deal, disposition=disposition, anchors=[text.split('\n')[1]]))
        deals.append(dict(deal_id=deal, event_ids=[identity['event_id']]))
    return dict(rows=annotations, deals=deals), docs, descriptions


class CensusSelectionTests(unittest.TestCase):
    def test_title_census_preserves_stock_and_cancel_rows_with_original_crlf(self):
        quarter, rows, selection, requests = fixtures()
        actual = read_title_rows(quarter, expected_count=4)
        self.assertEqual(actual, rows[:3])
        self.assertIn('\r\n', actual[0]['SUBJECT'])
        self.assertEqual(check(quarter, selection, requests), selection['rows'])

    def test_dropping_noncash_or_cancel_fails_even_with_adjusted_expected_counts(self):
        for dropped in (1, 2):
            quarter, _, selection, requests = fixtures()
            removed = selection['rows'].pop(dropped)
            requests = [r for r in requests if r['filename'] != removed.get('new_filename')]
            counts = (2, len(requests), 2-len(requests))
            with self.subTest(dropped=dropped), self.assertRaises(ValueError):
                check(quarter, selection, requests, counts)

    def test_complete_original_fields_cannot_be_replaced_by_subset_or_normalized_text(self):
        for mutation in ('subset', 'crlf'):
            quarter, _, selection, requests = fixtures()
            original = selection['rows'][0]['index_original_fields']
            if mutation == 'subset':
                del original['CODE_NAME']
            else:
                original['SUBJECT'] = original['SUBJECT'].replace('\r\n', '\n')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check(quarter, selection, requests)

    def test_quarter_wrong_time_or_external_url_cannot_hide_in_unselected_row(self):
        _, rows, _, _ = fixtures()
        for key, value in [('CTIME', '26:58:56'), ('HYPERLINK', rows[-1]['HYPERLINK'].replace('mopsov.twse.com.tw', 'other.example'))]:
            altered = copy.deepcopy(rows)
            altered[-1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                read_title_rows(encode_payload(altered), expected_count=4)

    def test_truncation_bad_status_and_duplicate_exact_pointer_fail(self):
        quarter, rows, _, _ = fixtures()
        with self.assertRaises(ValueError):
            read_title_rows(quarter[:-8], expected_count=4)
        payload = json.loads(quarter)
        payload['status'] = 'fail'
        with self.assertRaises(ValueError):
            read_title_rows(json.dumps(payload).encode(), expected_count=4)
        rows[-1] = copy.deepcopy(rows[0])
        with self.assertRaises(ValueError):
            read_title_rows(encode_payload(rows), expected_count=4)

    def test_clock_namespace_preserves_distinct_same_legacy_sequence_messages(self):
        first = row()
        second = row(clock='16:58:56', subject='另一不同股份轉換原文')
        selected = read_title_rows(encode_payload([first, second]), expected_count=2)
        self.assertEqual(len(selected), 2)
        a, _ = read_identity(document(first), first)
        b, _ = read_identity(document(second), second)
        self.assertNotEqual(a['event_id'], b['event_id'])

    def test_reuse_new_double_locator_and_wrong_request_url_fail(self):
        for mutation in ('double', 'url', 'path'):
            quarter, _, selection, requests = fixtures()
            if mutation == 'double':
                selection['rows'][0]['original_source'] = dict(archive_sha256='a'*64, member='raw/other.html')
            elif mutation == 'url':
                requests[0]['url'] = requests[1]['url']
            else:
                selection['rows'][2]['original_source']['member'] = 'raw/../escape.html'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check(quarter, selection, requests)

    def test_request_duplicate_or_source_hash_change_fails(self):
        for mutation in ('request', 'hash'):
            quarter, _, selection, requests = fixtures()
            if mutation == 'request':
                requests[1]['filename'] = requests[0]['filename']
            else:
                selection['source_quarter_sha256'] = '0'*64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check(quarter, selection, requests)


class CensusDocumentAndAnnotationTests(unittest.TestCase):
    def test_unknown_numbered_form_retains_all_description_and_validates_identity(self):
        source = row()
        text = '1.董事會決議日期:115/09/18\n2.特殊新表單:−１，１２３。\n(1)每股18.50元，附全部原條件。'
        raw = document(source, text)
        identity, description = read_identity(raw, source)
        self.assertEqual(description, text)
        self.assertEqual(identity['event_id'], event_id(source))
        self.assertEqual(identity['body_sha256'], digest(raw))
        self.assertEqual(identity['description_sha256'], digest(text.encode()))

    def test_document_wrong_metadata_url_time_and_duplicate_record_fail(self):
        source = row()
        raw = document(source)
        alternatives = [
            raw.replace(b'20:25:55', b'20:25:56'),
            raw.replace('115/09/18'.encode(), '115/09/19'.encode()),
            raw+raw,
        ]
        for altered in alternatives:
            with self.subTest(body=altered[:35]), self.assertRaises(ValueError):
                read_identity(altered, source)
        wrong = {**source, 'HYPERLINK': source['HYPERLINK'].replace('202555', '202556')}
        with self.assertRaises(ValueError):
            read_identity(raw, wrong)

    def test_complete_annotations_allow_display_whitespace_only(self):
        annotation, docs, descriptions = annotation_context()
        annotation['rows'][0]['anchors'] = ['每 股 現 金18.50\n元。']
        self.assertIsNone(check_annotations(annotation, docs, descriptions))

    def test_body_or_complete_description_sha_change_fails(self):
        for key in ('body_sha256', 'description_sha256'):
            annotation, docs, descriptions = annotation_context()
            annotation['rows'][0][key] = '0'*64
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_annotations(annotation, docs, descriptions)
        annotation, docs, descriptions = annotation_context()
        descriptions[docs[0]['event_id']] += '\n新增未雜湊修訂'
        with self.assertRaises(ValueError):
            check_annotations(annotation, docs, descriptions)

    def test_changed_cash_anchor_wrong_document_or_missing_anchors_fail(self):
        for anchors in (['每股現金18.60元。'], ['撤銷100%子公司簡易合併。'], []):
            annotation, docs, descriptions = annotation_context()
            annotation['rows'][0]['anchors'] = anchors
            with self.subTest(anchors=anchors), self.assertRaises(ValueError):
                check_annotations(annotation, docs, descriptions)

    def test_missing_row_or_invalid_disposition_cannot_drop_cancel_evidence(self):
        annotation, docs, descriptions = annotation_context()
        annotation['rows'].pop()
        with self.assertRaises(ValueError):
            check_annotations(annotation, docs, descriptions)
        annotation, docs, descriptions = annotation_context()
        annotation['rows'][-1]['disposition'] = 'profitable_merger'
        with self.assertRaises(ValueError):
            check_annotations(annotation, docs, descriptions)

    def test_document_must_have_exactly_one_consistent_deal_assignment(self):
        for mutation in ('duplicate', 'missing', 'wrong'):
            annotation, docs, descriptions = annotation_context()
            if mutation == 'duplicate':
                annotation['deals'][1]['event_ids'].append(docs[0]['event_id'])
            elif mutation == 'missing':
                annotation['deals'].pop()
            else:
                annotation['rows'][0]['deal_id'] = 'another_deal'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check_annotations(annotation, docs, descriptions)


class CensusArchiveAndTransportTests(unittest.TestCase):
    @staticmethod
    def archive(members, manifest=None):
        buffer = BytesIO()
        if manifest is None:
            manifest = {name: digest(body) for name, body in members.items()}
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, body in members.items():
                archive.writestr(name, body)
            archive.writestr('manifest.json', json.dumps(manifest))
        return buffer.getvalue()

    @staticmethod
    def transport_fixture(include_failed=False):
        request = dict(filename='original.html', url=row()['HYPERLINK'])
        body, headers = document(row()), b'HTTP/1.1 200 OK\r\n\r\n'
        record = dict(request=request, http_status=200, exit_code=0,
                      sha256=digest(body), headers_sha256=digest(headers))
        requests, records = [request], [record]
        members = {'raw/original.html': body, 'raw/original.html.headers': headers}
        if include_failed:
            failed = dict(filename='failed.html', url='https://official.example/law')
            requests.append(failed)
            records.append(dict(request=failed, http_status=0, exit_code=7))
        request_body = json.dumps(dict(requests=requests)).encode()
        members['requests.json'] = request_body
        for item in records:
            members['raw/' + item['request']['filename'] + '.meta.json'] = json.dumps(item).encode()
        members['raw/results.json'] = json.dumps(dict(
            workers=2, config_sha256=digest(request_body), requests=records)).encode()
        return members

    def test_archive_rejects_rehashed_changed_body_with_stale_member_manifest(self):
        members = {'raw/original.html': document(row())}
        valid = self.archive(members)
        self.assertEqual(verify_archive_bytes(valid, digest(valid))['raw/original.html'],
                         members['raw/original.html'])
        manifest = {name: digest(body) for name, body in members.items()}
        changed = self.archive({'raw/original.html': b'changed official terms'}, manifest)
        # The outer digest is current: the inner preserved-source manifest must
        # still reject replacement rather than merely checking ZIP readability.
        with self.assertRaisesRegex(ValueError, 'member SHA/path'):
            verify_archive_bytes(changed, digest(changed))
        with self.assertRaisesRegex(ValueError, 'Archive SHA'):
            verify_archive_bytes(valid, '0' * 64)

    def test_archive_rejects_unmanifested_extra_or_unsafe_source_member(self):
        for members, manifest in [
            ({'raw/a.html': b'a', 'raw/unrequested.html': b'b'}, {'raw/a.html': digest(b'a')}),
            ({'raw/../outside.html': b'a'}, {'raw/../outside.html': digest(b'a')}),
        ]:
            body = self.archive(members, manifest)
            with self.subTest(members=list(members)), self.assertRaises(ValueError):
                verify_archive_bytes(body, digest(body))

    def test_valid_identity_body_cannot_override_failed_http_or_exit_status(self):
        for status, exit_code in ((502, 0), (200, 7), (200, False)):
            members = self.transport_fixture()
            results = json.loads(members['raw/results.json'])
            record = results['requests'][0]
            record.update(http_status=status, exit_code=exit_code)
            # Metadata and body hashes agree: failure must come from the
            # selected transport status, even though the body has valid terms.
            members['raw/original.html.meta.json'] = json.dumps(record).encode()
            members['raw/results.json'] = json.dumps(results).encode()
            with self.subTest(status=status, exit_code=exit_code), self.assertRaisesRegex(
                    ValueError, 'HTTP200/exit0'):
                _transport(members, {'original.html'})

    def test_transport_detects_metadata_body_and_headers_drift(self):
        for mutation in ('metadata', 'body', 'headers', 'configuration'):
            members = self.transport_fixture()
            if mutation == 'metadata':
                meta = json.loads(members['raw/original.html.meta.json'])
                meta['http_status'] = 502
                members['raw/original.html.meta.json'] = json.dumps(meta).encode()
            elif mutation == 'body':
                members['raw/original.html'] += b'changed terms'
            elif mutation == 'headers':
                members['raw/original.html.headers'] += b'changed headers'
            else:
                results = json.loads(members['raw/results.json'])
                results['config_sha256'] = '0' * 64
                members['raw/results.json'] = json.dumps(results).encode()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                _transport(members, {'original.html'})

    def test_unselected_failed_observation_is_retained_but_cannot_be_selected(self):
        members = self.transport_fixture(include_failed=True)
        self.assertIsNone(_transport(members, {'original.html'}))
        self.assertEqual(json.loads(members['raw/failed.html.meta.json'])['exit_code'], 7)
        with self.assertRaisesRegex(ValueError, 'HTTP200/exit0'):
            _transport(members, {'original.html', 'failed.html'})
        with self.assertRaisesRegex(ValueError, 'Missing selected transport'):
            _transport(members, {'unrecorded.html'})


if __name__ == '__main__':
    unittest.main()
