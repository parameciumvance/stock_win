"""Synthetic notice and literal-link controls; no sources or prices fetched."""
import copy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cash_merger_current_notices as notices
from test_merger_document import fixture as document_fixture


def fixture(extra_html=b''):
    rows, bodies = [], {}
    for number, (date, clock, sequence, category) in enumerate([
        ('115/09/21', '15:50:00', '1', 'M17'),
        ('115/09/18', '20:25:33', '4', 'M17'),
        ('115/09/18', '19:40:28', '2', 'M99'),
    ]):
        text = '1.股東會條款仍待確認。\n2.完整長篇原文只留輸入：１２３−１。\n(1)不得自行推論付款。'
        body, original = document_fixture(text, issuer='6674', date=date, clock=clock,
                                           sequence=sequence, subject='尚待解讀的原公告' + str(number))
        original.update(AN_CODE=category, TYPEK='上市', COMPANY_NAME='甲', AN_NAME='原類別', CODE_NAME='原產業')
        event_id = category + ':6674:2026-' + date[4:].replace('/', '-') + ':' + clock.replace(':', '') + ':' + sequence
        name = f'notice{number}.html'
        rows.append(dict(event_id=event_id, index_original_fields=original, new_filename=name))
        bodies[name] = body + extra_html
    return dict(rows=rows), bodies


class CurrentNoticeTests(unittest.TestCase):
    def test_complete_text_and_hashes_retained_but_small_output_has_no_long_description(self):
        selection, bodies = fixture()
        full, summary = notices.replay_notices(selection, bodies)
        self.assertEqual(summary['document_count'], 3)
        self.assertTrue(summary['all_selected_original_identities_verified'])
        self.assertNotIn('完整長篇原文只留輸入', json.dumps(summary, ensure_ascii=False))
        for document in full:
            self.assertIn('完整長篇原文只留輸入：１２３−１', document['description'])
            self.assertEqual(document['body_sha256'], hashlib.sha256(bodies[document['filename']]).hexdigest())
            self.assertIsNone(document['disposition'])
        self.assertIsNone(summary['transaction_disposition'])
        for flag in ('current_transaction_status_verified', 'current_tradability_verified',
                     'contractual_cash_claim_verified', 'notice_window_verified', 'payment_date_verified',
                     'source_gate_passed', 'cash_claim_source_gate_passed', 'historical_pit_verified',
                     'first_publication_time_verified', 'profit_edge_proven',
                     'market_prices_or_returns_read', 'orders_authorized'):
            self.assertFalse(summary[flag], flag)

    def test_all_actual_href_src_occurrences_retained_with_source_literals_and_no_resolution(self):
        raw = b'''<base href="https://official.example/base/">
<a HREF='meeting.pdf?a=1&amp;b=2' href="same.pdf">one</a>
<a href="same.pdf">duplicate</a><iframe src=../meeting.html></iframe>
<script src="/script.js">var text='href="not-an-attribute"';</script>
<img src="/logo.png"/><link href="/style.css" rel="stylesheet">
<a href="javascript:void(0)">none</a><a href="mailto:office@example.org">mail</a>
<a href="">empty</a><a href>missing value</a>'''
        actual = notices.extract_pointers(raw)
        self.assertEqual(len(actual), 12)
        self.assertEqual([p['occurrence'] for p in actual], list(range(1, 13)))
        self.assertEqual(actual[1]['value'], 'meeting.pdf?a=1&b=2')
        self.assertEqual(actual[1]['source_literal'], 'meeting.pdf?a=1&amp;b=2')
        self.assertEqual([p['value'] for p in actual[2:4]], ['same.pdf', 'same.pdf'])
        self.assertEqual(actual[-2]['value'], '')
        self.assertIsNone(actual[-1]['value'])
        self.assertEqual({p['attribute'] for p in actual}, {'href', 'src'})
        self.assertTrue(all(p['resolved_url'] is None and p['fetch_authorized'] is False for p in actual))
        self.assertTrue(all('raw_start_tag' in p and p['html_line'] >= 1 for p in actual))

    def test_summary_preserves_exact_pointer_values_without_whole_html_tags(self):
        full, summary = notices.replay_notices(*fixture(b'<a href="../../terms.pdf?x=1&amp;y=2">terms</a>'))
        self.assertEqual(summary['pointer_count'], 3)
        pointer = summary['documents'][0]['pointers'][0]
        self.assertEqual(pointer['value'], '../../terms.pdf?x=1&y=2')
        self.assertEqual(pointer['source_literal'], '../../terms.pdf?x=1&amp;y=2')
        self.assertNotIn('raw_start_tag', pointer)
        self.assertFalse(summary['linked_documents_acquired'])
        self.assertFalse(summary['pointer_resolution_performed'])

    def test_no_link_does_not_claim_attachments_unavailable_or_terms_qualified(self):
        _, summary = notices.replay_notices(*fixture())
        self.assertEqual(summary['pointer_count'], 0)
        self.assertFalse(summary['contractual_cash_claim_verified'])
        self.assertNotIn('attachments_unobtainable', summary)

    def test_missing_extra_duplicate_or_changed_selection_cannot_replace_originals(self):
        for failure in ('missing', 'extra', 'duplicate', 'event_id', 'unsafe'):
            selection, bodies = fixture()
            if failure == 'missing':
                bodies.pop('notice0.html')
            elif failure == 'extra':
                bodies['replacement.html'] = bodies['notice0.html']
            elif failure == 'duplicate':
                selection['rows'][1] = copy.deepcopy(selection['rows'][0])
            elif failure == 'event_id':
                selection['rows'][0]['event_id'] += 'wrong'
            else:
                selection['rows'][0]['new_filename'] = '../notice0.html'
                bodies['../notice0.html'] = bodies.pop('notice0.html')
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                notices.replay_notices(selection, bodies)

    def test_wrong_issuer_clock_subject_or_category_is_not_identity_verified(self):
        for failure in ('issuer', 'clock', 'subject', 'category'):
            selection, bodies = fixture()
            original = selection['rows'][0]['index_original_fields']
            if failure == 'issuer':
                bodies['notice0.html'] = bodies['notice0.html'].replace(b'6674', b'2324')
            elif failure == 'clock':
                bodies['notice0.html'] = bodies['notice0.html'].replace(b'15:50:00', b'15:50:01')
            elif failure == 'subject':
                original['SUBJECT'] = '另一份公告'
            else:
                original['AN_CODE'] = 'M11'
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                notices.replay_notices(selection, bodies)

    def test_all_three_transports_must_succeed_even_if_the_saved_html_can_parse(self):
        success = [dict(http_status=200, exit_code=0)] * 3
        notices.require_successful_notices(success)
        for records in [success[:2], success + success[:1],
                        success[:2] + [dict(http_status=502, exit_code=0)],
                        success[:2] + [dict(http_status=200, exit_code=28)],
                        success[:2] + [dict(http_status=200, exit_code=False)]]:
            with self.subTest(records=records), self.assertRaisesRegex(ValueError, 'HTTP200 and exit0'):
                notices.require_successful_notices(records)

    def test_frozen_pre_io_guard_fails_before_archive_or_output_access(self):
        module = SimpleNamespace(archived=Mock())
        with patch.object(notices.merger_current_followthrough_sources, '_source_module', return_value=module), \
             patch.object(notices.merger_current_followthrough_sources, 'plan', side_effect=ValueError('Selection drift')), \
             patch.object(notices, 'atomic_json') as write, self.assertRaisesRegex(ValueError, 'Selection drift'):
            notices.run()
        module.archived.assert_not_called()
        write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
