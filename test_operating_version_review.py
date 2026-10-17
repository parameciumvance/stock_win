import json
import unittest
from operating_version_review import review_index, classify_time


def fixture():
    rows=[
        ['0000950170-25-006966','2025-01-21','2025-01-21','2025-01-21T16:03:58.000Z','6-K','release.htm'],
        ['0001292814-25-000981','2025-03-20','2024-12-31','2025-03-20T14:03:57.000Z','6-K','financials.htm'],
        ['0000950170-25-099999','2025-05-01','2024-12-31','2025-05-01T14:00:00Z','6-K/A','later.htm']]
    keys=['accessionNumber','filingDate','reportDate','acceptanceDateTime','form','primaryDocument']
    return dict(cik='1033767',name='UNITED MICROELECTRONICS CORP',filings=dict(recent={k:[r[i] for r in rows] for i,k in enumerate(keys)},files=[]))


class VersionReviewTests(unittest.TestCase):
    def review(self,obj):
        return review_index(json.dumps(obj).encode(),cik='0001033767',company_fragment='UNITED MICROELECTRONICS',start='2025-01-21',end='2025-04-30',period_end='2024-12-31',anchor_accession='0000950170-25-006966')

    def test_ordinary_later_financial_filing_is_not_lost_by_amendment_filter(self):
        r=self.review(fixture())
        self.assertEqual([c['relation'] for c in r['candidates']],['anchor','same_period_end_later_filing_candidate'])
        self.assertEqual(r['explicit_amendment_candidates'],0)
        self.assertFalse(r['full_revision_history_verified'])
        self.assertFalse(r['ready_for_model'])
        self.assertTrue(all(c['original_availability_not_inferred_from_index'] for c in r['candidates']))
        self.assertEqual(r['candidates'][0]['acceptance_as_reported'],'2025-01-21T16:03:58.000Z')

    def test_annual_report_with_same_period_end_is_only_a_candidate(self):
        obj=fixture();recent=obj['filings']['recent']
        row=['0001193125-25-092142','2025-04-24','2024-12-31','2025-04-24T14:10:32Z','20-F','annual.htm']
        for key,value in zip(['accessionNumber','filingDate','reportDate','acceptanceDateTime','form','primaryDocument'],row):
            recent[key].append(value)
        candidate=self.review(obj)['candidates'][-1]
        self.assertEqual(candidate['form'],'20-F')
        self.assertEqual(candidate['relation'],'same_period_end_later_filing_candidate')
        self.assertTrue(candidate['financial_quarter_not_inferred_from_index'])

    def test_explicit_amendment_is_kept_with_different_report_event_date(self):
        obj=fixture();obj['filings']['recent']['form'][1]='6-K/A';obj['filings']['recent']['reportDate'][1]='2025-03-20'
        r=self.review(obj);self.assertEqual(r['explicit_amendment_candidates'],1)
        self.assertEqual(r['candidates'][1]['relation'],'explicit_amendment_candidate')

    def test_unrelated_ordinary_6k_stays_in_content_review(self):
        obj=fixture();obj['filings']['recent']['reportDate'][1]='2025-03-20'
        self.assertEqual(self.review(obj)['candidates'][1]['relation'],'other_filing_requires_content_review')

    def test_anchor_outside_window_is_not_silently_ignored(self):
        obj=fixture();obj['filings']['recent']['filingDate'][0]='2025-01-20'
        with self.assertRaisesRegex(ValueError,'Anchor'):self.review(obj)

    def test_misaligned_optional_arrays_and_duplicates_fail(self):
        obj=fixture();obj['filings']['recent']['primaryDocDescription']=['only one']
        with self.assertRaisesRegex(ValueError,'Misaligned'):self.review(obj)
        obj=fixture();obj['filings']['recent']['accessionNumber'][1]=obj['filings']['recent']['accessionNumber'][0]
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.review(obj)

    def test_missing_historical_index_metadata_stays_unknown(self):
        obj=fixture();del obj['filings']['files']
        with self.assertRaisesRegex(ValueError,'coverage'):self.review(obj)

    def test_wrong_issuer_and_unsafe_candidate_are_rejected(self):
        for key,value in [('cik','1046179'),('name','OTHER CORP')]:
            obj=fixture();obj[key]=value
            with self.assertRaisesRegex(ValueError,'issuer'):self.review(obj)
        obj=fixture();obj['filings']['recent']['primaryDocument'][1]='../financials.htm'
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.review(obj)

    def test_naive_index_time_rejected(self):
        obj=fixture();obj['filings']['recent']['acceptanceDateTime'][1]='2025-03-20T14:03:57'
        with self.assertRaisesRegex(ValueError,'Naive'):self.review(obj)

    def test_duplicate_json_key_cannot_overwrite_issuer(self):
        raw=json.dumps(fixture()).replace('"name":','"cik":"1033767","name":',1).encode()
        with self.assertRaisesRegex(ValueError,'Duplicate JSON key'):
            review_index(raw,cik='0001033767',company_fragment='UNITED MICROELECTRONICS',start='2025-01-21',end='2025-04-30',period_end='2024-12-31',anchor_accession='0000950170-25-006966')

    def test_scheduled_or_observed_time_cannot_become_public_time(self):
        for kind in ['conference_schedule','transport_observation','sec_acceptance','issuer_date','usual_process_duration']:
            r=classify_time(kind,'2025-01-21T17:00:00+08:00',source_url='https://example.com/source',raw_obtained=True)
            self.assertIsNone(r['public_dissemination_at']);self.assertIsNone(r['taiwan_first_published_at'])
            self.assertFalse(r['ready_for_model'])
        with self.assertRaisesRegex(ValueError,'Unreviewed'):
            classify_time('inferred_from_search_snippet','2025-01-21',source_url='https://example.com',raw_obtained=False)


if __name__=='__main__':unittest.main()
