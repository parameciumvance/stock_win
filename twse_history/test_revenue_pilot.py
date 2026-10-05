import unittest
from datetime import date
from .revenue_pilot import (parse_issuer_date, parse_sec_revenue,
                            reconcile_acceptance, next_market_day)


class RevenuePilotTests(unittest.TestCase):
    def test_date_only_ignores_false_epoch_metadata(self):
        html = '<script>{"datePublished":"1970-01-01"}</script><h1>TSMC January 2024 Revenue Report</h1>Issued on: 2024/02/07'
        self.assertEqual(parse_issuer_date(html, "2024-01"), date(2024, 2, 7))

    def test_missing_visible_date_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_issuer_date('<h1>TSMC January 2024 Revenue Report</h1><time datetime="2024-02-07T12:00:00Z"></time>', '2024-01')

    def test_exact_table_used_instead_of_rounded_news_number(self):
        html = ('TSMC January 2024 Revenue Report TWSE: 2330 '
                'Net Revenue 215,785 an increase of 7.9 percent from January 2023 '
                '1. Revenue (in NT$ thousands) Period Items 2024 2023 Jan. '
                'Net Revenue 215,785,127 200,050,544')
        self.assertEqual(parse_sec_revenue(html, '2024-01'), (215785127, 200050544, 7.9))
        with self.assertRaises(ValueError):
            parse_sec_revenue(html.replace('in NT$ thousands', 'in NT$ million'), '2024-01')

    def test_yoy_mismatch_rejected(self):
        html = ('TSMC January 2024 Revenue Report TWSE: 2330 '
                'an increase of 99.9 percent from January 2023 '
                '1. Revenue (in NT$ thousands) Period Items 2024 2023 Jan. '
                'Net Revenue 215,785,127 200,050,544')
        with self.assertRaises(ValueError):
            parse_sec_revenue(html, '2024-01')

    def test_sec_timezone_agreement_across_dst(self):
        for eastern, utc, taipei in [('2024-03-08 06:05:24', '2024-03-08T11:05:24Z', '2024-03-08T19:05:24+08:00'),
                                     ('2024-04-10 06:04:06', '2024-04-10T10:04:06Z', '2024-04-10T18:04:06+08:00')]:
            index = f'Form 6-K accession doc.htm Accepted {eastern}'
            submissions = {'filings': {'recent': {'accessionNumber': ['accession'],
                'primaryDocument': ['doc.htm'], 'form': ['6-K'], 'acceptanceDateTime': [utc]}}}
            self.assertEqual(reconcile_acceptance(index, submissions, 'accession', 'doc.htm').isoformat(), taipei)
            submissions['filings']['recent']['acceptanceDateTime'] = ['2024-04-10T06:04:06Z']
            with self.assertRaises(ValueError):
                reconcile_acceptance(index, submissions, 'accession', 'doc.htm')

    def test_real_holiday_calendar_and_no_same_day_release(self):
        days = {date(2024, 2, 5), date(2024, 2, 15), date(2024, 2, 16)}
        self.assertEqual(next_market_day(date(2024, 2, 7), days), date(2024, 2, 15))
        self.assertEqual(next_market_day(date(2024, 2, 15), days), date(2024, 2, 16))
        with self.assertRaises(ValueError):
            next_market_day(date(2024, 2, 16), days)


if __name__ == '__main__':
    unittest.main()
