from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch
from cb_entry_calendar import parse_calendar,is_open,next_day,lag_day,scenarios
import frontier_cb_calendar_completion_sources as source

def fixture():
    rows=[['2026-01-02','國曆新年開始交易日',''],['2026-02-12','市場無交易，僅辦理結算交割作業',''],['2026-02-13','市場無交易，僅辦理結算交割作業',''],['2026-10-25','臺灣光復暨金門古寧頭大捷紀念日',''],['2026-10-26','臺灣光復暨金門古寧頭大捷紀念日','']]
    return dict(stat='ok',queryYear=2026,date='20260101',title='115 年市場開休市日期',fields=['日期','名稱','說明'],data=rows,total=len(rows))

class EntryCalendarTests(unittest.TestCase):
    def test_settlement_only_is_not_an_all_purpose_holiday(self):
        c=parse_calendar(fixture());self.assertFalse(is_open(date(2026,2,12),c,'trade'));self.assertTrue(is_open(date(2026,2,12),c,'settlement'));self.assertTrue(is_open(date(2026,1,2),c,'trade'))
    def test_next_window_and_T2_skip_weekend_and_observed_holiday(self):
        c=parse_calendar(fixture());extra={date(2026,10,23)}
        self.assertEqual(next_day(date(2026,10,23),c,extra_closed=extra),date(2026,10,27))
        self.assertEqual(lag_day(date(2026,10,27),2,c,extra_closed=extra),date(2026,10,29))
        self.assertEqual(next_day(date(2026,11,1),c,inclusive=True),date(2026,11,2))
    def test_date_feasibility_never_promotes_account_or_signal(self):
        cases=[dict(bond_code='99587',broker_end='2026-10-27',expected_payment_date='2026-11-04'),dict(bond_code='68351',broker_end='2026-10-30',expected_payment_date='2026-11-06')]
        r=scenarios(parse_calendar(fixture()),date(2026,10,23),{date(2026,10,23)},cases)
        self.assertEqual([x['T2_date_comparison_only_reaches_broker_end'] for x in r['cases']],[False,True]);self.assertIsNone(r['valid_prospective_signal_date']);self.assertIsNone(r['earliest_verified_executable_entry']);self.assertFalse(r['source_gate_passed'])
    def test_bad_schema_count_unknown_label_and_duplicate_are_errors(self):
        for mutate in [lambda p:p.update(total=True),lambda p:p.update(queryYear=2027),lambda p:p['data'].append(p['data'][0]),lambda p:p['data'][0].__setitem__(1,'unknown market status')]:
            p=deepcopy(fixture());mutate(p)
            with self.assertRaises(ValueError):parse_calendar(p)
    def test_outside_year_is_not_silently_assumed_open(self):
        c=parse_calendar(fixture())
        with self.assertRaises(ValueError):is_open(date(2027,1,4),c)
        with self.assertRaises(ValueError):next_day(date(2026,12,31),c)
    def test_negative_boolean_lag_or_closed_entry_refused(self):
        c=parse_calendar(fixture())
        for lag in (-1,True):
            with self.assertRaises(ValueError):lag_day(date(2026,10,27),lag,c)
        with self.assertRaises(ValueError):lag_day(date(2026,10,26),2,c)
    def test_unknown_source_batch_rejected_before_io(self):
        with patch.object(source,'module') as shared:
            with self.assertRaises(ValueError):source.plan('extra')
            shared.assert_not_called()
if __name__=='__main__':unittest.main()
