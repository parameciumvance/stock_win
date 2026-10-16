import unittest
from sec_submission import parse_submission,acceptance_clock


def fixture():
    return b'''<SEC-DOCUMENT>0001046179-25-000004.txt : 20250116
<SEC-HEADER>0001046179-25-000004.hdr.sgml : 20250116
<ACCEPTANCE-DATETIME>20250116061335
ACCESSION NUMBER: 0001046179-25-000004
CONFORMED SUBMISSION TYPE: 6-K
PUBLIC DOCUMENT COUNT: 2
CONFORMED PERIOD OF REPORT: 20241231
FILED AS OF DATE: 20250116
COMPANY CONFORMED NAME: TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD
CENTRAL INDEX KEY: 0001046179
</SEC-HEADER>
<DOCUMENT>
<TYPE>6-K
<SEQUENCE>1
<FILENAME>primary.htm
<TEXT>
<html>primary fixture</html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-99.1
<SEQUENCE>2
<FILENAME>release.htm
<TEXT>
<html>exhibit fixture</html>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
'''


class SubmissionTests(unittest.TestCase):
    def parse(self,body=None,**overrides):
        args=dict(cik='0001046179',accession='0001046179-25-000004',quarter='2024Q4');args.update(overrides)
        return parse_submission(fixture() if body is None else body,**args)

    def test_complete_snapshot_keeps_primary_and_exhibit_distinct(self):
        result=self.parse()
        self.assertEqual(result['primary_filename'],'primary.htm')
        self.assertEqual(result['document_count'],2)
        self.assertEqual(result['documents'][1]['type'],'EX-99.1')
        self.assertEqual(result['documents'][0]['payload'],b'<html>primary fixture</html>\n')

    def test_winter_summer_timezone_conversion(self):
        winter=acceptance_clock('20250116061335');summer=acceptance_clock('20250716061335')
        self.assertEqual(winter['utc'],'2025-01-16T11:13:35+00:00')
        self.assertEqual(winter['taipei'],'2025-01-16T19:13:35+08:00')
        self.assertEqual(summer['utc'],'2025-07-16T10:13:35+00:00')

    def test_ambiguous_nonexistent_and_invalid_clocks_rejected(self):
        for stamp in ['20251102013000','20250309023000','20251316061335','202501160613']:
            with self.subTest(stamp=stamp),self.assertRaises(ValueError):acceptance_clock(stamp)

    def test_wrong_issuer_accession_quarter_and_amendment_rejected(self):
        for args in [dict(cik='0001033767'),dict(accession='0001046179-25-000005'),dict(quarter='2025Q1')]:
            with self.subTest(args=args),self.assertRaises(ValueError):self.parse(**args)
        with self.assertRaises(ValueError):self.parse(fixture().replace(b'SUBMISSION TYPE: 6-K',b'SUBMISSION TYPE: 6-K/A'))

    def test_missing_duplicate_or_unsafe_documents_rejected(self):
        bads=[fixture().replace(b'COUNT: 2',b'COUNT: 3'),
              fixture().replace(b'<FILENAME>release.htm',b'<FILENAME>primary.htm'),
              fixture().replace(b'<SEQUENCE>2',b'<SEQUENCE>1'),
              fixture().replace(b'<FILENAME>release.htm',b'<FILENAME>../release.htm'),
              fixture().replace(b'<TYPE>6-K',b'<TYPE>EX-99.1')]
        for body in bads:
            with self.subTest(body=body[:100]),self.assertRaises(ValueError):self.parse(body)

    def test_truncated_or_http_error_cannot_be_submission(self):
        for body in [fixture()[:-30],b'<html>403 Forbidden</html>',fixture().replace(b'</TEXT>',b'',1),fixture().replace(b'</SEC-DOCUMENT>',b'<DOCUMENT>\n</SEC-DOCUMENT>')]:
            with self.subTest(body=body[:50]),self.assertRaises(ValueError):self.parse(body)

    def test_header_clock_uniqueness_and_report_time_consistency(self):
        bads=[fixture().replace(b'<ACCEPTANCE-DATETIME>',b'<ACCEPTANCE-DATETIME>20250116061335\n<ACCEPTANCE-DATETIME>',1),
              fixture().replace(b'20250116061335',b'20241216061335'),
              fixture().replace(b'FILED AS OF DATE: 20250116',b'FILED AS OF DATE: 20250115')]
        for body in bads:
            with self.assertRaises(ValueError):self.parse(body)


if __name__=='__main__':unittest.main()
