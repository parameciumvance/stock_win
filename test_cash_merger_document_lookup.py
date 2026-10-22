"""Full saved lookup inventories without selecting a favorable document type."""
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cash_merger_document_lookup as lookup


HTML = '''<html><body><h1>6674／115文件查詢</h1>
<table id="books"><tr><th>類別</th><th>原檔名</th></tr>
<tr><td>年報</td><td><a href="../bookA.pdf?a=1&amp;b=2">A.pdf</a></td></tr>
<tr><td>股東會議事手冊</td><td><input type="button" value="詳細資料"
 onclick="openWindow('ACTUAL_book_B.pdf','115','6674')"></td></tr>
<tr><td>未知類別及其他年度</td><td>不因名稱篩掉C.pdf</td></tr></table>
<form name="download" action="/server-java/ActualForm" method="post">
 <input name="filename" value="ACTUAL_book_B.pdf"><input name="filename" value="revision_C.pdf">
 <input name="co_id" value="6674"><select name="book_type"><option value="all" selected>全部</option>
 <option value="unknown">未知原類別</option></select><textarea name="note">完整原文，不重新推論條款。</textarea>
</form><script>function openWindow(filename){return filename;}</script><img src="../actual.png">
</body></html>'''.encode()


class LookupInventoryTests(unittest.TestCase):
    def test_all_returned_rows_and_book_types_retained_without_document_selection(self):
        full, summary = lookup.inventory_html(HTML)
        self.assertEqual(full['body_sha256'], hashlib.sha256(HTML).hexdigest())
        self.assertEqual(summary['html_row_count'], 4)
        self.assertEqual(summary['returned_rows'][1]['cells'], ['年報', 'A.pdf'])
        self.assertIn('未知類別及其他年度', summary['returned_rows'][3]['cells'])
        self.assertIn('完整原文，不重新推論條款。', full['page_text'])
        for flag in ('book_type_filter_applied', 'returned_company_year_identity_verified',
                     'specific_document_selected', 'linked_documents_acquired', 'document_population_complete',
                     'no_documents_proven', 'javascript_executed', 'pointers_followed',
                     'contractual_cash_claim_verified', 'source_gate_passed', 'cash_claim_source_gate_passed',
                     'historical_pit_verified', 'profit_edge_proven', 'market_prices_or_returns_read',
                     'orders_authorized'):
            self.assertFalse(summary[flag], flag)

    def test_actual_filenames_and_duplicate_controls_retained_without_collapsing_fields(self):
        full, summary = lookup.inventory_html(HTML)
        form = full['forms'][0]
        self.assertEqual(form['action'], '/server-java/ActualForm')
        filenames = [control['attributes']['value'] for control in form['controls']
                     if control['attributes'].get('name') == 'filename']
        self.assertEqual(filenames, ['ACTUAL_book_B.pdf', 'revision_C.pdf'])
        select = next(c for c in form['controls'] if c['tag'] == 'select')
        self.assertEqual([o['attributes']['value'] for o in select['options']], ['all', 'unknown'])
        self.assertEqual(summary['forms'], full['forms'])

    def test_exact_scripted_and_href_src_pointers_are_preserved_never_executed_or_resolved(self):
        full, summary = lookup.inventory_html(HTML)
        self.assertEqual(summary['pointer_count'], 2)
        pointer = summary['pointers'][0]
        self.assertEqual(pointer['value'], '../bookA.pdf?a=1&b=2')
        self.assertEqual(pointer['source_literal'], '../bookA.pdf?a=1&amp;b=2')
        self.assertIsNone(pointer['resolved_url'])
        self.assertFalse(pointer['fetch_authorized'])
        self.assertEqual(summary['scripted_attributes'][0]['value'],
                         "openWindow('ACTUAL_book_B.pdf','115','6674')")
        self.assertIn('function openWindow', full['scripts'][0]['text'])
        self.assertNotIn('function openWindow', json.dumps(summary))
        self.assertEqual(summary['scripts'][0]['text_sha256'],
                         hashlib.sha256(full['scripts'][0]['text'].encode()).hexdigest())

    def test_nested_and_layout_rows_stay_in_inventory_with_table_context(self):
        raw = b'<html><table id="layout"><tr><td>outer<table id="result"><tr><td>inner</td></tr></table></td></tr></table></html>'
        full, summary = lookup.inventory_html(raw)
        self.assertEqual(summary['html_table_count'], 2)
        self.assertEqual(summary['html_row_count'], 2)
        self.assertEqual([row['table'] for row in full['rows']], [1, 2])
        self.assertIn('inner', full['rows'][0]['text'])
        self.assertEqual(full['rows'][1]['cells'][0]['text'], 'inner')

    def test_empty_or_error_page_is_preserved_without_claiming_no_documents(self):
        for raw in [b'<html><body><div></div></body></html>', '<html>查詢異常，稍後再試</html>'.encode()]:
            full, summary = lookup.inventory_html(raw)
            self.assertEqual(summary['html_row_count'], 0)
            self.assertFalse(summary['no_documents_proven'])
            self.assertFalse(summary['document_population_complete'])
            self.assertFalse(summary['source_gate_passed'])

    def test_non_utf8_empty_or_non_html_response_fails_without_fabricated_rows(self):
        for raw in [b'', b'upstream error', b'<html>\xff</html>']:
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                lookup.inventory_html(raw)

    def test_explicit_declared_big5_preserves_raw_hash_and_exact_decoded_pointers(self):
        raw = '<html><meta http-equiv="Content-Type" content="text/html;charset=big5"><a href="實際檔案.pdf">股東會</a></html>'.encode('big5')
        full, summary = lookup.inventory_html(raw, 'big5', b'Content-Type: text/html;charset=big5\r\n')
        self.assertEqual(full['body_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(summary['source_encoding'], 'big5')
        self.assertEqual(summary['pointers'][0]['value'], '實際檔案.pdf')
        self.assertIn('股東會', full['page_text'])

    def test_conflicting_undeclared_unsupported_or_invalid_charset_is_never_replaced(self):
        raw = b'<html><meta charset="big5">text</html>'
        for body, encoding, headers in [
            (raw, 'utf-8', None), (raw, 'big5', b'Content-Type: text/html;charset=utf-8\r\n'),
            (b'<html>ascii only</html>', 'big5', None), (raw, 'cp950', None),
            (b'<html><meta charset="big5">\x81</html>', 'big5', None),
            (b'\xef\xbb\xbf' + raw, 'big5', None),
        ]:
            with self.subTest(encoding=encoding, headers=headers), self.assertRaises((ValueError, UnicodeError)):
                lookup.inventory_html(body, encoding, headers)

    def test_transport_failure_or_wrong_request_count_is_not_a_valid_query(self):
        lookup.require_successful_query([dict(http_status=200, exit_code=0)])
        for rows in [[], [dict(http_status=200, exit_code=0)] * 2,
                     [dict(http_status=503, exit_code=0)], [dict(http_status=200, exit_code=28)],
                     [dict(http_status=200, exit_code=False)]]:
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, 'HTTP200/exit0'):
                lookup.require_successful_query(rows)

    def test_frozen_pre_io_guard_blocks_before_saved_query_or_output_is_opened(self):
        module = SimpleNamespace(archived=Mock())
        with patch.object(lookup.merger_documents_sources, '_source_module', return_value=module), \
             patch.object(lookup.merger_documents_sources, 'plan', side_effect=ValueError('Form SHA drift')), \
             patch.object(lookup, 'atomic_json') as write, self.assertRaisesRegex(ValueError, 'Form SHA drift'):
            lookup.run()
        module.archived.assert_not_called()
        write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
