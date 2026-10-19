"""UI/transport evidence must never silently become a historical source gate."""
import hashlib
import unittest

from buyback_source_inspection import inspect_response


class SourceInspectionTests(unittest.TestCase):
    def inspect(self, body, status=200, code=0, url='https://mops.example/web/query', kind='buyback_html'):
        return inspect_response(body.encode() if isinstance(body, str) else body, url, status, code, kind)

    def assert_closed(self, value):
        for key in ('historical_pit_verified', 'source_gate_passed', 'complete_cohort_verified',
                    'empty_universe_verified', 'followup_authorized', 'site_blocking_proven'):
            self.assertFalse(value[key], key)

    def test_http200_error_is_not_empty_cohort(self):
        for body in ('<html><h1>安全性問題</h1></html>', '<h1>查詢過量，請稍後查詢</h1>',
                     '<title>Access Denied</title><table><tr><th>X</th></tr><tr><td>0</td></tr></table>'):
            result = self.inspect(body)
            self.assertEqual(result['classification'], 'explicit_error_page')
            self.assert_closed(result)

    def test_redirected_error_url_is_explicit_even_if_blank(self):
        result = self.inspect('', url='https://mops.example/mops/error/error.html')
        self.assertEqual(result['classification'], 'explicit_error_page')
        self.assertTrue(result['error_url_observed'])

    def test_ui_form_and_layout_table_are_not_data(self):
        result = self.inspect('''<form action="/query" method="POST"><input type="hidden" name="step" value="1">
          <table><tr><th>查詢</th></tr><tr><td>年度<select name="year"><option value="113" selected>113 年</option></select></td></tr></table>
          <label for="year">民國年度</label></form>''')
        self.assertEqual(result['classification'], 'query_form_only')
        form = result['forms'][0]
        self.assertEqual(form['method'], 'post')
        self.assertEqual(form['hidden_inputs'][0]['value'], '1')
        self.assertEqual(form['selects'][0]['name'], 'year')
        self.assertEqual(form['selects'][0]['options'][0]['text'], '113 年')
        self.assertTrue(form['selects'][0]['options'][0]['selected'])
        self.assertEqual(form['labels'][0]['text'], '民國年度')
        self.assert_closed(result)

    def test_actual_table_is_only_unverified_structure(self):
        result = self.inspect('<table><tr><th>代號</th><th>股數</th></tr><tr><td>1234</td><td>1000</td></tr></table>')
        self.assertEqual(result['classification'], 'data_response_unverified')
        self.assertEqual(result['data_shape_observed'], 'html_table_structure_only')
        self.assert_closed(result)

    def test_result_table_inside_form_with_per_row_query_button_is_unverified_data(self):
        result = self.inspect('''<form name='fm_t35sc09' action='/mops/web/ajax_t35sb01'
          method='post' onsubmit='return false;'>
          <table class='hasBorder'><tr class='tblHead'><th rowspan='2'>序號</th>
          <th rowspan='2'>公司代號</th><th colspan='2'>買回價格區間</th><th>達一定標準資料</th></tr>
          <tr><th>最低</th><th>最高</th></tr>
          <tr><td>1</td><td>1587</td><td>15.93</td><td>34.12</td>
          <td><input type='button' value='查詢' onclick='document.fm.submit();'></td></tr>
          </table></form>''')
        self.assertEqual(result['classification'], 'data_response_unverified')
        self.assertEqual(result['tables'][0]['plain_data_rows'], 0)
        self.assertEqual(result['tables'][0]['mixed_control_data_rows'], 1)
        self.assert_closed(result)

    def test_standalone_javascript_error_strings_are_not_error_page_evidence(self):
        body = 'search_value_msg.innerText = "系統忙碌，請再重新查詢";\nconst template = "<form>Access Denied</form>";'.encode()
        result = self.inspect(body, kind='javascript')
        self.assertEqual(result['classification'], 'unrecognized')
        self.assertEqual(result['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(result['size_bytes'], len(body))
        self.assertEqual(result['forms'], [])
        self.assertEqual(result['content_interpretation'], 'standalone_javascript_not_interpreted')
        self.assert_closed(result)
        failed = self.inspect(body, status=0, code=60, kind='javascript')
        self.assertEqual(failed['classification'], 'transport_failure')
        self.assert_closed(failed)

    def test_empty_claim_or_empty_json_never_proves_zero_events(self):
        for body in ('<div>查無資料</div>', '[]', '{"data":[]}'):
            result = self.inspect(body)
            self.assertEqual(result['classification'], 'data_response_unverified')
            self.assert_closed(result)

    def test_tls_failure_is_transport_only_not_site_blocking(self):
        result = self.inspect(b'', status=0, code=60)
        self.assertEqual(result['classification'], 'transport_failure')
        self.assert_closed(result)
        self.assertEqual(self.inspect('<form></form>', code=28)['classification'], 'transport_failure')

    def test_http503_has_no_transport_root_cause_inference(self):
        result = self.inspect('temporarily unavailable', status=503)
        self.assertEqual(result['classification'], 'explicit_error_page')
        self.assert_closed(result)

    def test_foreign_action_and_changed_base_never_authorize_followup(self):
        result = self.inspect('<base href="https://foreign.example/"><form action="/query"></form>')
        action = result['forms'][0]['action']
        self.assertEqual(action['resolved_url'], 'https://foreign.example/query')
        self.assertFalse(action['same_origin'])
        self.assertFalse(action['followup_authorized'])
        result = self.inspect('<form action="https://foreign.example/query"></form>')
        self.assertFalse(result['forms'][0]['action']['same_origin'])
        result = self.inspect('<form action="/query"></form>')
        self.assertTrue(result['forms'][0]['action']['same_origin'])
        self.assertFalse(result['forms'][0]['action']['followup_authorized'])

    def test_only_observed_literal_ajax_routes_and_no_js_execution(self):
        result = self.inspect('''<script src="/assets/query.js"></script><script>
          $.ajax({type:'POST', url:'/ajax/t35sc09', data:params});
          fetch('/api/result'); $.post('https://foreign.example/collect', payload);
          $.get('/computed/' + suffix); fetch(prefix + '/guess');
          request.open('GET', '/xhr/literal');
        </script>''')
        self.assertEqual(result['script_sources'][0]['src'], '/assets/query.js')
        self.assertEqual({r['raw'] for r in result['ajax_routes']}, {'/ajax/t35sc09', '/api/result', '/xhr/literal'})
        self.assertEqual(result['rejected_ajax_routes'][0]['raw'], 'https://foreign.example/collect')
        self.assertTrue(all(not r['followup_authorized'] for r in result['ajax_routes']))
        self.assert_closed(result)

    def test_raw_text_whitespace_entities_and_fullwidth_characters_preserved(self):
        body = '<form action="/q?a=1&amp;b=2"><input type="hidden" name="raw" value="−１,２３４"><label>  Ａ&amp;Ｂ −１,２３４\n</label><select name="v"><option value="１"> １　年 </option></select></form>'.encode()
        result = self.inspect(body)
        form = result['forms'][0]
        self.assertEqual(result['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(form['hidden_inputs'][0]['value'], '−１,２３４')
        self.assertEqual(form['labels'][0]['text'], '  Ａ&amp;Ｂ −１,２３４\n')
        self.assertEqual(form['selects'][0]['options'][0]['text'], ' １　年 ')
        self.assertIn('a=1&amp;b=2', form['raw_start_tag'])

    def test_invalid_utf8_fails_closed_without_replacement(self):
        body = b'<form><label>\xff</label></form>'
        result = self.inspect(body)
        self.assertEqual(result['classification'], 'unrecognized')
        self.assertIsNotNone(result['decoding']['error'])
        self.assertEqual(result['forms'], [])
        self.assertEqual(result['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assert_closed(result)

    def test_explicit_legacy_charset_strictly_decoded(self):
        body = '<meta charset="big5"><form><label>公司代號</label></form>'.encode('big5')
        result = self.inspect(body)
        self.assertEqual(result['decoding']['encoding'], 'big5')
        self.assertEqual(result['forms'][0]['labels'][0]['text'], '公司代號')
        unknown = self.inspect(b'<meta charset="not-a-real-charset"><form></form>')
        self.assertEqual(unknown['classification'], 'unrecognized')

    def test_csv_shape_does_not_certify_schema_or_pit(self):
        result = self.inspect('symbol,amount\n1234,1000\n', kind='buyback_csv')
        self.assertEqual(result['classification'], 'data_response_unverified')
        self.assert_closed(result)

    def test_binary_and_plain_text_are_not_accepted_by_expected_kind(self):
        for body in (b'%PDF-1.4 binary\x00', b'not a source table'):
            result = self.inspect(body)
            self.assertEqual(result['classification'], 'unrecognized')
            self.assert_closed(result)

    def test_original_bytes_required_instead_of_implicit_reencoding(self):
        with self.assertRaises(TypeError):
            inspect_response('原字串', 'https://mops.example/query', 200, 0, 'html')


if __name__ == '__main__':
    unittest.main()
