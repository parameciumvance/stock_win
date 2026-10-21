"""Synthetic evidence controls for the independent cash-merger source audit.

These tests use no saved prices, source downloads or production audit outputs.
"""
import copy
import hashlib
from html import escape
import unittest

from cash_merger_independent import (
    full_field_multisets_equal, verify_annotation_evidence, verify_document, verify_row,
)


START, END = '2026-07-01', '2026-09-30'
FIRST_DESCRIPTION = ('1.董事會決議日期:115/08/13\n2.原訂現金對價每股100元。\n'
                     '3.另依核准條件辦理。\n(1)子條款與原字：−１，１２３。')
SECOND_DESCRIPTION = ('1.董事會決議撤銷日期:115/08/13\n'
                      '2.撤銷股份轉換，原現金對價不再適用。\n3.不據此主張已付款。')


def row(**changes):
    value = dict(COMPANY_ID='6472', COMPANY_NAME='甲公司', TYPEK='上市', AN_CODE='M11',
                 AN_NAME='發行有價證券、減資、併購或股份轉交換', CODE_NAME='其他業',
                 CDATE='115/08/13', CTIME='20:06:54', SUBJECT='本公司董事會決議原契約',
                 HYPERLINK='https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1?firstin=true&step=1&stp=1'
                 '&COMPANY_ID=6472&SPOKE_DATE=20260813&SPOKE_TIME=200654&SEQ_NO=1')
    value.update(changes)
    return value


def document(source=None, description=FIRST_DESCRIPTION, sequence='1'):
    source = row() if source is None else source
    return (f'<html><table><tr><td>本資料由　(上市公司) {source["COMPANY_ID"]} '
            f'{escape(source["COMPANY_NAME"])} 公司提供</td></tr></table>'
            f'<table><tr><th>序號</th><td>{sequence}</td><th>發言日期</th><td>{source["CDATE"]}</td>'
            f'<th>發言時間</th><td>{source["CTIME"]}</td></tr>'
            f'<tr><th>主旨</th><td>{escape(source["SUBJECT"])}</td></tr>'
            f'<tr><th>說明</th><td><pre>{escape(description)}</pre></td></tr></table></html>').encode()


def annotation_context():
    first = row()
    second = row(CTIME='16:58:56', SUBJECT='本公司董事會撤銷原契約',
                 HYPERLINK=first['HYPERLINK'].replace('200654', '165856'))
    documents, descriptions, notes = [], {}, []
    for number, source, description, excerpt in [
        (1, first, FIRST_DESCRIPTION, '原訂現金對價每股100元。'),
        (2, second, SECOND_DESCRIPTION, '撤銷股份轉換，原現金對價不再適用。'),
    ]:
        name = f'control{number:02}.html'
        raw = document(source, description)
        source_sha = hashlib.sha256(raw).hexdigest()
        text_sha = hashlib.sha256(description.encode()).hexdigest()
        documents.append(dict(filename=name, sha256=source_sha, description_sha256=text_sha,
                              issuer=source['COMPANY_ID'], reported_datetime='2026-08-13T' + source['CTIME'] + '+08:00',
                              sequence='1', url=source['HYPERLINK'], subject=source['SUBJECT'], identity_verified=True))
        descriptions[name] = description
        notes.append(dict(document_numbers=[number], interpretation='有限原文核對，不作收益推論',
                          evidence=[dict(filename=name, sha256=source_sha, description_sha256=text_sha,
                                         exact_excerpts=[excerpt])]))
    return dict(semantic_reading=notes), documents, descriptions


class IndependentMergerEvidenceTests(unittest.TestCase):
    def test_same_issuer_date_sequence_with_different_clocks_remain_distinct_identities(self):
        first = row()
        second = row(CTIME='16:58:56', SUBJECT='不同原始公告主旨',
                     HYPERLINK=first['HYPERLINK'].replace('200654', '165856'))
        a, b = verify_row(first, START, END), verify_row(second, START, END)
        self.assertEqual(a['issuer'], b['issuer'])
        self.assertEqual(a['sequence'], b['sequence'])
        self.assertNotEqual(a['reported_datetime'], b['reported_datetime'])
        self.assertNotEqual(a['url'], b['url'])
        self.assertNotEqual(a, b)

    def test_row_rejects_missing_identity_and_mismatched_url_time_date_or_issuer(self):
        first = row()
        for missing in ('COMPANY_ID', 'CDATE', 'CTIME', 'SUBJECT', 'HYPERLINK'):
            bad = {key: value for key, value in first.items() if key != missing}
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                verify_row(bad, START, END)
        for before, after in (('200654', '120654'), ('20260813', '20260814'),
                              ('COMPANY_ID=6472', 'COMPANY_ID=1103')):
            with self.subTest(before=before), self.assertRaises(ValueError):
                verify_row({**first, 'HYPERLINK': first['HYPERLINK'].replace(before, after)}, START, END)

    def test_row_rejects_external_pointer_and_duplicate_query_identity(self):
        first = row()
        for url in (first['HYPERLINK'].replace('mopsov.twse.com.tw', 'foreign.example'),
                    first['HYPERLINK'] + '&SEQ_NO=1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                verify_row({**first, 'HYPERLINK': url}, START, END)

    def test_document_accepts_unknown_m11_numbered_form_and_preserves_complete_description(self):
        source = row()
        raw = document(source)
        identity, description = verify_document(raw, source)
        self.assertEqual(description, FIRST_DESCRIPTION)
        self.assertEqual(identity['issuer'], '6472')
        self.assertEqual(identity['reported_datetime'], '2026-08-13T20:06:54+08:00')
        self.assertEqual(identity['sequence'], '1')
        self.assertEqual(identity['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(identity['description_sha256'], hashlib.sha256(description.encode()).hexdigest())
        self.assertTrue(identity['identity_verified'])

    def test_early_morning_five_digit_pointer_matches_clock_without_accepting_invalid_hour(self):
        source = row(CTIME='06:31:17', HYPERLINK=row()['HYPERLINK'].replace('200654', '63117'))
        identity = verify_row(source, START, END)
        self.assertEqual(identity['reported_datetime'], '2026-08-13T06:31:17+08:00')
        actual, description = verify_document(document(source), source)
        self.assertEqual(actual['reported_datetime'], identity['reported_datetime'])
        self.assertEqual(description, FIRST_DESCRIPTION)
        invalid = {**source, 'HYPERLINK': source['HYPERLINK'].replace('63117', '700000')}
        with self.assertRaises(ValueError):
            verify_row(invalid, START, END)
        with self.assertRaises(ValueError):
            verify_document(document(source), invalid)

    def test_document_rejects_wrong_record_metadata_and_duplicate_announcement(self):
        source = row()
        raw = document(source)
        for candidate in (raw.replace(b'20:06:54', b'20:06:55'),
                          raw.replace('<td>1</td>'.encode(), '<td>2</td>'.encode()),
                          raw.replace(source['SUBJECT'].encode(), '不同主旨'.encode()), raw + raw):
            with self.subTest(size=len(candidate)), self.assertRaises(ValueError):
                verify_document(candidate, source)

    def test_annotation_with_exact_bound_hashes_and_excerpts_passes(self):
        annotation, documents, descriptions = annotation_context()
        self.assertIsNone(verify_annotation_evidence(annotation, documents, descriptions))

    def test_annotation_rejects_changed_source_or_description_evidence_sha(self):
        annotation, documents, descriptions = annotation_context()
        for field in ('sha256', 'description_sha256'):
            bad = copy.deepcopy(annotation)
            bad['semantic_reading'][0]['evidence'][0][field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_annotation_evidence(bad, documents, descriptions)

    def test_description_hash_uses_full_original_text_not_only_matching_excerpt(self):
        annotation, documents, descriptions = annotation_context()
        changed = dict(descriptions)
        changed['control01.html'] += '\n新增未被引句涵蓋之原文。'
        with self.assertRaises(ValueError):
            verify_annotation_evidence(annotation, documents, changed)

    def test_annotation_rejects_changed_numeric_excerpt_but_tolerates_display_whitespace(self):
        annotation, documents, descriptions = annotation_context()
        bad = copy.deepcopy(annotation)
        bad['semantic_reading'][0]['evidence'][0]['exact_excerpts'] = ['原訂現金對價每股101元。']
        with self.assertRaises(ValueError):
            verify_annotation_evidence(bad, documents, descriptions)
        spaced = copy.deepcopy(annotation)
        spaced['semantic_reading'][0]['evidence'][0]['exact_excerpts'] = ['原訂現金對價\n 每股100元。']
        self.assertIsNone(verify_annotation_evidence(spaced, documents, descriptions))

    def test_annotation_evidence_must_bind_to_declared_document_numbers(self):
        annotation, documents, descriptions = annotation_context()
        bad = copy.deepcopy(annotation)
        bad['semantic_reading'][0]['evidence'] = copy.deepcopy(bad['semantic_reading'][1]['evidence'])
        with self.assertRaises(ValueError):
            verify_annotation_evidence(bad, documents, descriptions)
        for numbers in ([0], [3], [-1]):
            bad = copy.deepcopy(annotation)
            bad['semantic_reading'][0]['document_numbers'] = numbers
            with self.subTest(numbers=numbers), self.assertRaises(ValueError):
                verify_annotation_evidence(bad, documents, descriptions)

    def test_new_semantic_note_without_evidence_fails_even_when_old_notes_cover_documents(self):
        annotation, documents, descriptions = annotation_context()
        for evidence in ({}, {'evidence': []}):
            bad = copy.deepcopy(annotation)
            bad['semantic_reading'].append(dict(document_numbers=[1], interpretation='沒有來源的新推論', **evidence))
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                verify_annotation_evidence(bad, documents, descriptions)

    def test_every_control_document_requires_semantic_note_coverage(self):
        annotation, documents, descriptions = annotation_context()
        annotation['semantic_reading'] = annotation['semantic_reading'][:1]
        with self.assertRaises(ValueError):
            verify_annotation_evidence(annotation, documents, descriptions)

    def test_full_field_multisets_preserve_duplicate_multiplicity(self):
        first, second = row(), row(SUBJECT='另一個公告欄位')
        self.assertTrue(full_field_multisets_equal([first, first, second], [[second], [first], [first]]))
        self.assertFalse(full_field_multisets_equal([first, first, second], [[second], [first], []]))
        self.assertFalse(full_field_multisets_equal([first, second], [[first], [first], [second]]))

    def test_full_fields_include_source_newlines_and_nonidentity_metadata(self):
        first = row(SUBJECT='公告主旨\r\n第二行')
        self.assertFalse(full_field_multisets_equal([first], [[row(SUBJECT='公告主旨\n第二行')], [], []]))
        self.assertFalse(full_field_multisets_equal([row()], [[row(COMPANY_NAME='不同來源名稱')], [], []]))
        self.assertTrue(full_field_multisets_equal([first], [[], [copy.deepcopy(first)], []]))


if __name__ == '__main__':
    unittest.main()
