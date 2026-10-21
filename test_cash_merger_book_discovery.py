"""Synthetic source-route/form tests; no network or archived sources are read."""
from html import escape
import unittest

from cash_merger_book_discovery import inspect_lineage


def pages():
    entry = b'''<form name="fm1" action="/mops/web/t146sb08" method="post">
<input name="step" value="1"><input name="run" value=""><input name="firstin" value="Y">
<input name="keyword" value="&#38651;&#23376;&#26360;"></form><script>document.fm1.submit();</script>'''
    routes = '<a href="t57sb01_q5">年報及股東會相關資料(含存託憑證資料)</a>'.encode()
    # These are literal UI defaults, including the source's typo "ture";
    # turning it into true would silently change evidence before JS dispatch.
    pairs = [('step', '1'), ('firstin', 'ture'), ('off', '1'), ('TYPEK', 'all'),
             ('keyword4', ''), ('code1', ''), ('TYPEK2', ''), ('checkbtn', ''),
             ('queryName', 'co_id'), ('inpuType', 'co_id'), ('co_id', ''), ('year', '')]
    controls = ''.join('<input type="' + ('hidden' if i < 10 else 'text')
                       + '" name="' + name + '" value="' + escape(value) + '">'
                       for i, (name, value) in enumerate(pairs))
    final = ('''<form name="fh"><input name="funcName" value="t57sb01_q5"></form>
<form name="form1" action="/mops/web/ajax_t57sb01_q5" method="post">''' + controls + '''</form>
<script>function doAction(){
if(document.form1.firstin!=null&&document.form1.firstin!=undefined&&document.form1.firstin.value!=''){
document.form1.firstin.value='1';}
var name=document.fh.funcName.value;document.form1.action='/mops/web/ajax_'+name;
}
function nextFunction(){}
</script>''').encode()
    return entry, routes, final


class BookDiscoveryTests(unittest.TestCase):
    def test_declared_route_and_defaults_do_not_execute_query_or_qualify_contract(self):
        result = inspect_lineage(*pages())
        self.assertEqual(result['relay_form']['fields'][2]['value'], 'Y')
        self.assertEqual(result['meeting_book_form']['declared_firstin_default'], 'ture')
        self.assertEqual(result['meeting_book_form']['declared_firstin_after_doAction'], '1')
        self.assertFalse(result['meeting_book_form']['javascript_executed'])
        self.assertFalse(result['company_year_query_performed'])
        self.assertFalse(result['contractual_cash_claim_verified'])

    def test_missing_extra_or_duplicate_form_fields_fail(self):
        entry, routes, final = pages()
        for bad in (final.replace(b'<input type="hidden" name="code1" value="">', b''),
                    final.replace(b'</form>\n<script>', b'<input name="extra" value=""></form>\n<script>'),
                    final.replace(b'<input type="hidden" name="code1" value="">',
                                  b'<input name="step" value="1">')):
            with self.subTest(body=bad[-80:]), self.assertRaises(ValueError):
                inspect_lineage(entry, routes, bad)

    def test_source_typo_cannot_be_corrected_or_empty_run_dropped(self):
        entry, routes, final = pages()
        with self.assertRaises(ValueError):
            inspect_lineage(entry, routes, final.replace(b'value="ture"', b'value="true"'))
        with self.assertRaises(ValueError):
            inspect_lineage(entry.replace(b'<input name="run" value="">', b''), routes, final)

    def test_wrong_route_or_ambiguous_anchor_cannot_be_resolved_as_meeting_form(self):
        entry, routes, final = pages()
        for bad in (routes.replace(b't57sb01_q5', b't57sb01_q3'), routes + routes):
            with self.subTest(body=bad), self.assertRaises(ValueError):
                inspect_lineage(entry, bad, final)
        with self.assertRaises(ValueError):
            inspect_lineage(entry.replace(b'/mops/web/t146sb08', b'/mops/web/other'), routes, final)

    def test_commented_or_different_firstin_assignment_is_not_declared_dispatch(self):
        entry, routes, final = pages()
        for bad in (final.replace(b"document.form1.firstin.value='1';", b"/*document.form1.firstin.value='1';*/"),
                    final.replace(b"document.form1.firstin.value='1';", b"document.form1.firstin.value='2';")):
            with self.subTest(body=bad[-120:]), self.assertRaises(ValueError):
                inspect_lineage(entry, routes, bad)


if __name__ == '__main__':
    unittest.main()
