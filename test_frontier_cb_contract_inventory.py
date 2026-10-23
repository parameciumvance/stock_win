"""Synthetic declared-link inventory controls; no saved sources or network IO."""
import hashlib
import json
import unittest
from urllib.parse import urlencode

from frontier_cb_contract_inventory import inspect_html, inspect_options, inspect_report, REPORT_FIELDS


URL = 'https://www.tpex.org.tw/zh-tw/bond/issue/cbond/listed.html'


class ContractEntryInventoryTests(unittest.TestCase):
    def test_every_returned_anchor_is_retained_without_filtering_old_or_selected_codes(self):
        raw = '''<html><meta charset="utf-8"><a href="./old.html?code=21043">舊資料</a>
<a href="./terms.html?code=99587">99587</a><a href="./terms.html?code=68351">68351</a>
<a href="./terms.html?code=68741">68741</a><a href="./unclassified.html">未知類別</a></html>'''.encode()
        result = inspect_html(raw, URL)
        self.assertEqual(result['body_sha256'], hashlib.sha256(raw).hexdigest())
        anchors = [p for p in result['pointers'] if p['tag'] == 'a']
        self.assertEqual(len(anchors), 5)
        self.assertEqual(anchors[0]['value'], './old.html?code=21043')
        self.assertEqual(anchors[-1]['value'], './unclassified.html')
        self.assertTrue(all(p['followup_authorized'] is False for p in result['pointers']))

    def test_html_source_literal_and_decoded_query_value_remain_separately_auditable(self):
        result = inspect_html(b'<html>\n<a HREF="./terms.html?a=1&amp;b=2">terms</a></html>', URL)
        pointer = result['pointers'][0]
        self.assertEqual(pointer['source_literal'], './terms.html?a=1&amp;b=2')
        self.assertEqual(pointer['value'], './terms.html?a=1&b=2')
        self.assertEqual(pointer['resolved_url'], 'https://www.tpex.org.tw/zh-tw/bond/issue/cbond/terms.html?a=1&b=2')
        self.assertTrue(pointer['same_origin'])
        self.assertGreaterEqual(pointer['line'], 1)
        self.assertGreaterEqual(pointer['column'], 0)

    def test_duplicate_attributes_and_repeated_pointer_occurrences_are_not_deduplicated(self):
        raw = b'<html><a href="./one.html" href="./two.html">two declarations</a><a href="./one.html">again</a><img src="/same.png"><img src="/same.png"></html>'
        pointers = inspect_html(raw, URL)['pointers']
        self.assertEqual([p['value'] for p in pointers], ['./one.html', './two.html', './one.html', '/same.png', '/same.png'])
        self.assertTrue(all(p['followup_authorized'] is False for p in pointers))

    def test_relative_root_protocol_relative_and_external_origins_remain_distinct(self):
        raw = b'<html><a href="../terms.html">up</a><script src="/js/tables.js"></script><a href="//www.tpex.org.tw/help">same</a><a href="https://doc.twse.com.tw/form">external</a></html>'
        pointers = inspect_html(raw, URL)['pointers']
        self.assertEqual(pointers[0]['resolved_url'], 'https://www.tpex.org.tw/zh-tw/bond/issue/terms.html')
        self.assertEqual(pointers[1]['resolved_url'], 'https://www.tpex.org.tw/js/tables.js')
        self.assertEqual([p['same_origin'] for p in pointers], [True, True, True, False])
        self.assertFalse(pointers[-1]['followup_authorized'])

    def test_non_http_empty_and_missing_values_are_preserved_without_authorizing_fetches(self):
        raw = b'<html><a href="javascript:void(0)">JS</a><a href="mailto:a@example.org">mail</a><a href="">empty</a><a href>missing</a><img src="data:image/png;base64,AA=="></html>'
        pointers = inspect_html(raw, URL)['pointers']
        self.assertEqual([p['value'] for p in pointers], ['javascript:void(0)', 'mailto:a@example.org', '', None, 'data:image/png;base64,AA=='])
        self.assertTrue(all(p['followup_authorized'] is False for p in pointers))

    def test_comment_or_inline_script_text_does_not_fabricate_html_link_attributes(self):
        raw = b'''<html><!-- <a href="/comment-only">comment</a> -->
<script>var text = '<a href="/not-an-html-anchor">'; window.neverRun = function(){ throw Error('no execution'); };</script>
<a href="/actual">actual</a></html>'''
        pointers = inspect_html(raw, URL)['pointers']
        self.assertEqual([(p['tag'], p['value']) for p in pointers], [('a', '/actual')])

    def test_invalid_utf8_or_empty_saved_bytes_fail_without_replacement_characters(self):
        for raw in [b'', b'<html>\xff</html>']:
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                inspect_html(raw, URL)

    def test_form_duplicate_controls_and_options_preserved_without_default_method_or_submission(self):
        raw = '''<html><form action="/actual-query">
<input name="bond" value="99587"><input name="bond" value="68351">
<select name="kind"><option value="all">全部</option><option value="unknown">未知</option></select>
<textarea name="note">原始條款待查</textarea></form></html>'''.encode()
        result = inspect_html(raw, URL)
        form = result['forms'][0]
        self.assertEqual(form['action'], '/actual-query')
        self.assertIsNone(form['method'])
        self.assertEqual([c['value'] for c in form['controls'] if c['name'] == 'bond'], ['99587', '68351'])
        select = next(c for c in form['controls'] if c['tag'] == 'select')
        self.assertEqual([(o['value'], o['text']) for o in select['options']], [('all', '全部'), ('unknown', '未知')])
        action = next(p for p in result['pointers'] if p['attribute'] == 'action')
        self.assertFalse(action['followup_authorized'])
        self.assertFalse(result['JavaScript_executed'])

    def test_inline_script_text_and_hash_preserved_without_execution(self):
        script = "var table={action:'bond',option:'putProvision',pattern:unknownRoute};\nthrow Error('never execute');"
        raw = ('<html><script src="/actual.js"></script><script>' + script + '</script></html>').encode()
        result = inspect_html(raw, URL)
        self.assertEqual(result['scripts'][0]['src'], '/actual.js')
        self.assertEqual(result['scripts'][1]['raw_text'], script)
        self.assertEqual(result['scripts'][1]['text_sha256'], hashlib.sha256(script.encode()).hexdigest())
        self.assertFalse(result['JavaScript_executed'])
        self.assertFalse(result['source_gate_passed'])

    def test_script_property_evidence_keeps_quoted_values_distinct_from_unknown_identifiers(self):
        raw = b'''<html><select data-option="bondIssuer"></select>
<script>var cfg={action:'bond',option:"putProvision",pattern:unknownRoute};</script></html>'''
        result = inspect_html(raw, URL)
        literals = result['literal_declarations']
        self.assertEqual([(r['key'], r['value'], r['identifier']) for r in literals],
                         [('action', 'bond', None), ('option', 'putProvision', None), ('pattern', None, 'unknownRoute')])
        self.assertEqual([r['source_literal'] for r in literals], ["'bond'", '"putProvision"', 'unknownRoute'])
        self.assertTrue(all(r['kind'] == 'script_property_literal_evidence_only'
                            and r['followup_authorized'] is False for r in literals))
        self.assertEqual([(r['attribute'], r['value']) for r in result['data_declarations']],
                         [('data-option', 'bondIssuer')])
        self.assertTrue(result['script_properties_are_syntactically_unverified_evidence'])

    def test_foreign_html_base_controls_relative_resolution_without_changing_observed_origin(self):
        raw = b'<html><base href="https://doc.twse.com.tw/declared/"><a href="actual.html">actual</a><a href="https://www.tpex.org.tw/help">official</a></html>'
        result = inspect_html(raw, URL)
        self.assertEqual(result['resolution_base'], 'https://doc.twse.com.tw/declared/')
        anchors = [p for p in result['pointers'] if p['tag'] == 'a']
        self.assertEqual(anchors[0]['resolved_url'], 'https://doc.twse.com.tw/declared/actual.html')
        self.assertFalse(anchors[0]['same_origin'])
        self.assertTrue(anchors[1]['same_origin'])
        self.assertFalse(anchors[0]['followup_authorized'])

    def test_invalid_base_scheme_does_not_silently_resolve_against_response_url(self):
        raw = b'<html><base href="javascript:invalid()"><a href="actual.html">relative</a></html>'
        result = inspect_html(raw, URL)
        relative = next(p for p in result['pointers'] if p['tag'] == 'a')
        self.assertIsNone(relative['resolved_url'])
        self.assertFalse(relative['followup_authorized'])

    def test_declared_big5_is_strict_and_unsupported_or_invalid_charset_is_rejected(self):
        raw = '<html><meta charset="big5"><a href="./actual.html">公司債</a></html>'.encode('big5')
        result = inspect_html(raw, URL)
        self.assertEqual(result['body_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['encoding'], 'big5')
        self.assertEqual(result['pointers'][0]['value'], './actual.html')
        for bad in [b'<html><meta charset="shift_jis">text</html>', b'<html><meta charset="big5">\x81</html>']:
            with self.subTest(raw=bad), self.assertRaises((ValueError, UnicodeError)):
                inspect_html(bad, URL)


class ContractOptionInventoryTests(unittest.TestCase):
    def test_all_options_in_original_order_including_empty_and_old_issuer_are_preserved(self):
        options = [dict(value='', text='請選擇'), dict(value='9958', text='  世紀鋼  '),
                   dict(value='2104', text='舊發行人，不依新近掛牌篩除')]
        raw = json.dumps(dict(stat='ok', options=dict(bondIssuer=options)), ensure_ascii=False).encode()
        result = inspect_options(raw)
        self.assertEqual(result['body_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['options'], options)
        self.assertEqual(result['returned_option_count'], 3)
        self.assertEqual(result['first_returned_option'], options[0])
        self.assertFalse(result['source_gate_passed'])

    def test_duplicate_values_wrong_schema_nonfinite_or_duplicate_json_are_rejected(self):
        good = dict(stat='ok', options=dict(bondIssuer=[dict(value='9958', text='世紀鋼')]))
        invalid = [dict(stat='ok', options=dict(bondIssuer=[dict(value='', text='甲'), dict(value='', text='乙')])),
                   dict(stat='ok', options=dict(bondIssuer=[dict(value='9958', text='甲'), dict(value='9958', text='乙')])),
                   dict(stat='ok', options=dict(bondIssuer=[dict(value=9958, text='甲')])),
                   dict(stat='ok', options=dict(bondIssuer=[dict(value='9958', text='甲', extra='new')])),
                   dict(stat='ok', options=dict(bondIssuer=[], unknown=[])),
                   dict(stat='failed', options=dict(bondIssuer=[])), dict(good, extra='new')]
        raw_invalid = [json.dumps(value, ensure_ascii=False).encode() for value in invalid]
        raw_invalid.extend([b'{"stat":"ok","stat":"ok","options":{"bondIssuer":[]}}',
                            b'{"stat":"ok","options":{"bondIssuer":[{"value":"1","text":NaN}]}}',
                            b'{"stat":"ok","options":{"bondIssuer":[{"value":"1","text":1e999}]}}'])
        for raw in raw_invalid:
            with self.subTest(raw=raw[:100]), self.assertRaises(ValueError):
                inspect_options(raw)

    def test_310_dropdown_options_are_not_a_complete_bond_population_or_empty_universe_proof(self):
        options = [dict(value=str(number), text='原發行人' + str(number)) for number in range(310)]
        result = inspect_options(json.dumps(dict(stat='ok', options=dict(bondIssuer=options))).encode())
        self.assertEqual(result['returned_option_count'], 310)
        self.assertEqual(result['options'], options)
        self.assertFalse(result['complete_bond_population_verified'])
        self.assertFalse(result['source_gate_passed'])
        empty = inspect_options(b'{"stat":"ok","options":{"bondIssuer":[]}}')
        self.assertEqual(empty['returned_option_count'], 0)
        self.assertIsNone(empty['first_returned_option'])
        self.assertFalse(empty['complete_bond_population_verified'])


def report_row(issuer='9958', bond='99587', **changes):
    pairs = [('TYPEK', ''), ('bond_id', bond), ('bond_kind', '5'), ('bond_subn', '$M00000001'),
             ('bond_yrn', '7'), ('come', '2'), ('encodeURIComponent', '1'), ('firstin', 'ture'),
             ('issuer_stock_code', issuer), ('monyr_reg', '202609'), ('pg', ''), ('step', '0'), ('tg', '')]
    row = [issuer, '  原發行機構  ', '原公司債，不依名稱選取', '113/10/28',
           'https://mopsov.twse.com.tw/mops/web/t120sg01?' + urlencode(pairs)]
    if 'url' in changes:
        row[4] = changes['url']
    return row


def report_body(rows=None, **changes):
    table = dict(title='最近上櫃轉(交)換公司債', subtitle='<a href="/actual-subtitle">原附註</a>',
                 date='2026/10/23', fields=REPORT_FIELDS, data=[report_row()] if rows is None else rows,
                 totalCount=1 if rows is None else len(rows), notes=['原備註'], summary=[])
    table.update(changes)
    return json.dumps(dict(stat='ok', tables=[table]), ensure_ascii=False).encode()


class ContractReportInventoryTests(unittest.TestCase):
    def test_all_rows_original_columns_order_and_exact_url_strings_remain(self):
        original = [report_row(), report_row('2104', '21043'), report_row('6835', '68351')]
        raw = report_body(original)
        result = inspect_report(raw)
        self.assertEqual(result['body_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['returned_row_count'], 3)
        self.assertEqual([r['original_fields'] for r in result['rows']], original)
        self.assertEqual([r['bond_code'] for r in result['rows']], ['99587', '21043', '68351'])
        self.assertEqual(result['rows'][0]['issuance_data_pointer']['url'], original[0][4])
        self.assertIn('monyr_reg=202609', result['rows'][0]['issuance_data_pointer']['url'])
        self.assertIn('bond_subn=%24M00000001', result['rows'][0]['issuance_data_pointer']['url'])
        for row in result['rows']:
            pointer = row['issuance_data_pointer']
            self.assertFalse(pointer['followup_authorized'])
            self.assertFalse(pointer['PDF_verified'])
            self.assertFalse(pointer['holder_put_contract_verified'])

    def test_bond_prefix_and_issuer_must_match_the_report_column(self):
        original_url = report_row()[4]
        for before, after in [('bond_id=99587', 'bond_id=12347'),
                              ('issuer_stock_code=9958', 'issuer_stock_code=1234'),
                              ('bond_id=99587', 'bond_id=9958'), ('bond_id=99587', 'bond_id=9958X')]:
            with self.subTest(field=before, value=after), self.assertRaises(ValueError):
                inspect_report(report_body([report_row(url=original_url.replace(before, after))]))

    def test_foreign_host_duplicate_url_key_and_malformed_escape_are_rejected(self):
        original_url = report_row()[4]
        invalid = [original_url.replace('mopsov.twse.com.tw', 'other.example'),
                   original_url.replace('/mops/web/t120sg01', '/mops/web/other'),
                   original_url + '&bond_id=99587', original_url + '&%62ond_id=99587',
                   original_url.replace('%24', '%ZZ'), original_url.replace('https:', 'http:')]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                inspect_report(report_body([report_row(url=url)]))

    def test_duplicate_bonds_counts_schema_dates_and_duplicate_json_fail(self):
        invalid = [report_body([report_row(), report_row()]), report_body(totalCount=2),
                   report_body(totalCount=True), report_body(fields=REPORT_FIELDS[:-1]),
                   report_body(data=[report_row()[:-1]]), report_body(extra='new')]
        bad_date = report_row()
        bad_date[3] = '113/02/30'
        invalid += [report_body([bad_date]), b'{"stat":"ok","stat":"ok","tables":[]}',
                    report_body().replace(b'"notes": [', b'"notes": [NaN,')]
        for raw in invalid:
            with self.subTest(raw=raw[:100]), self.assertRaises(ValueError):
                inspect_report(raw)

    def test_subtitle_pointers_and_matching_count_never_establish_contract_or_population(self):
        result = inspect_report(report_body())
        self.assertEqual(result['subtitle_pointers'][0]['value'], '/actual-subtitle')
        self.assertFalse(result['subtitle_pointers'][0]['followup_authorized'])
        self.assertTrue(result['count_reconciliation_passed'])
        for key in ('complete_bond_population_verified', 'holder_put_contracts_verified',
                    'cash_claim_source_gate_passed', 'source_gate_passed', 'historical_pit_verified'):
            self.assertFalse(result[key], key)


if __name__ == '__main__':
    unittest.main()
