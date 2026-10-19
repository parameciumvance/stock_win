import unittest
from buyback_source_audit import annual_rows, independent_annual_rows


def fixture(issuer='1587', day='113/01/27', count=1):
    cells = ['1', issuer, '吉茂', day] + [''] * 16
    row = '<tr>' + ''.join('<td>' + c + '</td>' for c in cells) + '</tr>'
    return ('<html><table>' + row + '</table><p>家數合計：1家</p>'
            + '<p>件數合計：' + str(count) + '件</p><p>依最新財報計算</p></html>').encode('utf-8')


class AnnualSourceAuditTests(unittest.TestCase):
    def test_missing_rows_cannot_pass_reported_population_count(self):
        with self.assertRaisesRegex(ValueError, 'count mismatch'):
            annual_rows(fixture(count=2))

    def test_decision_date_outside_frozen_year_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside fixed scope'):
            annual_rows(fixture(day='112/12/31'))

    def test_independent_parser_must_preserve_unlabelled_utf8_chinese(self):
        # These MOPS replies omit a charset declaration. lxml defaults to a
        # different encoding unless the caller explicitly supplies UTF-8.
        expected = annual_rows(fixture())
        actual = independent_annual_rows(fixture())
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0][2], '吉茂')


if __name__ == '__main__':
    unittest.main()
