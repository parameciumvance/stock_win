import unittest
from frontier_cb_major_inventory import classify_html
class ShellTests(unittest.TestCase):
    def test_http200_empty_shell_never_means_zero_events(self):
        _,r=classify_html(b'<html><div id="div01">\n </div><script>loadLater()</script></html>')
        self.assertTrue(r['empty_div01_shell']);self.assertFalse(r['explicit_no_data_message']);self.assertFalse(r['absence_of_events_proven']);self.assertFalse(r['usable_event_listing'])
    def test_explicit_no_data_still_not_universal_absence(self):
        _,r=classify_html('<html><div id="div01">查無資料</div></html>'.encode())
        self.assertFalse(r['empty_div01_shell']);self.assertTrue(r['explicit_no_data_message']);self.assertFalse(r['absence_of_events_proven'])
    def test_whole_tables_are_retained(self):
        full,r=classify_html(b'<div id="div01"><table><tr><td>a</td></tr><tr><td>b</td></tr></table></div>')
        self.assertEqual(r['returned_row_count'],2);self.assertEqual(len(full['rows']),2);self.assertFalse(r['empty_div01_shell'])
    def test_pending_auto_form_is_preserved_and_not_absence(self):
        full,r=classify_html(b'<div id="div01"><form name="autoForm" action="/actual" method="post"><input type="hidden" name="step" value="12"></form></div>')
        self.assertTrue(r['empty_div01_shell']);self.assertTrue(r['pending_declared_auto_form'])
        self.assertEqual(r['declared_auto_forms'][0]['controls'][0]['value'],'12')
        self.assertFalse(r['absence_of_events_proven'])
if __name__=='__main__':unittest.main()
