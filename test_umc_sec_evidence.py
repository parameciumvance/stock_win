import unittest
from sec_submission import acceptance_clock
from umc_sec_evidence import extract_umc_sec_text,guidance_umc,reconcile_clocks

TEXT=('UMC Reports Fourth Quarter 2024 Results TWSE: 2303 January 21, 2025 '
      'consolidated operating results for the fourth quarter of 2024 '
      'Revenue: NT$60.39 billion Gross margin: 30.4% Earnings per share: NT$0.68')
GUIDANCE='First Quarter 2025 Outlook & Guidance Gross Profit Margin: Will be higher than 25% with 0121 earthquake impact'


class UmcEvidenceTests(unittest.TestCase):
    def test_numeric_units_and_absent_standard_are_preserved(self):
        r=extract_umc_sec_text(TEXT)
        self.assertEqual((r['gross_margin_pct'],r['eps_twd'],r['revenue_twd_billions']),(30.4,0.68,60.39))
        self.assertTrue(r['consolidated_basis_explicit']);self.assertIsNone(r['accounting_standard_explicit'])

    def test_wrong_period_units_and_conflicting_values_rejected(self):
        for text in [TEXT.replace('Fourth Quarter 2024','First Quarter 2025'),TEXT.replace('NT$60.39','US$60.39'),TEXT+' Gross margin: 35.0%']:
            with self.assertRaises(ValueError):extract_umc_sec_text(text)

    def test_guidance_is_conditional_strict_lower_bound_not_point(self):
        r=guidance_umc(GUIDANCE)
        self.assertEqual((r['target_quarter'],r['operator'],r['threshold_pct']),('2025Q1','>',25))
        self.assertIsNone(r['point_forecast']);self.assertFalse(r['ready_for_evaluation'])
        for text in [GUIDANCE.replace('First Quarter','Second Quarter'),GUIDANCE+' '+GUIDANCE,GUIDANCE.replace('25%','125%'),GUIDANCE.replace('with 0121 earthquake impact','')]:
            with self.assertRaises(ValueError):guidance_umc(text)

    def test_actual_five_hour_conflict_never_selects_a_clock(self):
        raw=acceptance_clock('20250121060358');reported='2025-01-21T16:03:58.000Z'
        r=reconcile_clocks(raw,reported)
        self.assertEqual(r['status'],'conflict');self.assertFalse(r['matches'])
        self.assertEqual(r['delta_seconds_json_minus_sgml'],18000)
        self.assertEqual(r['sgml_raw'],'20250121060358');self.assertEqual(r['json_as_reported'],reported)
        self.assertIsNone(r['canonical_sec_accepted_at']);self.assertIsNone(r['public_dissemination_at'])

    def test_matching_clocks_still_do_not_prove_publication(self):
        r=reconcile_clocks(acceptance_clock('20250121060358'),'2025-01-21T11:03:58Z')
        self.assertTrue(r['matches']);self.assertEqual(r['delta_seconds_json_minus_sgml'],0)
        self.assertIsNone(r['canonical_sec_accepted_at']);self.assertIsNone(r['public_dissemination_at'])
        with self.assertRaises(ValueError):reconcile_clocks(acceptance_clock('20250121060358'),'2025-01-21T11:03:58')


if __name__=='__main__':unittest.main()
