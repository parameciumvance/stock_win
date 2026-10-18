import copy
import json
import unittest

import numpy as np
import pandas as pd

from index_review import audit_rows, event_endpoints, parse_notice, quote_return

TITLE = '臺灣證券交易所與富時國際有限公司合編之臺灣指數系列及臺灣高股息指數成分股定期審核結果'
BODY = TITLE + '''2024/03/01 16:59
富時羅素相關變動將自2024年3月15日（星期五）交易結束後生效（亦即自2024年3月18日（星期一）起生效）。
一、臺灣50指數<br>(一)成分股納入：世芯-KY(3661)。<br>(二)成分股刪除：豐泰(9910)。<br>(三)候補名單：奇鋐(3017)。
二、臺灣中型100指數<br>(一)成分股納入：豐泰(9910)、保瑞(6472)。<br>(二)成分股刪除：世芯-KY(3661)、聯邦銀(2838)。'''


def parse(body=BODY, quarter='2024Q1'):
    return parse_notice(('<html><body>'+body+'</body></html>').encode(), quarter)


class NoticeTests(unittest.TestCase):
    def test_scopes_index_excludes_reserves_and_other_indices(self):
        r = parse()
        self.assertEqual([(x['action'], x['symbol']) for x in r['changes']], [('add', '3661'), ('delete', '9910')])
        self.assertEqual(r['implementation_close'], '2024-03-15')
        self.assertEqual(r['effective_from'], '2024-03-18')
        self.assertEqual(r['displayed_publication'], '2024-03-01 16:59:00')

    def test_visible_old_date_does_not_prove_pit_or_timezone(self):
        r = parse()
        self.assertFalse(r['historical_pit_verified'])
        self.assertFalse(r['revision_history_verified'])
        self.assertIn('not explicitly established', r['publication_timezone'])

    def test_scripts_and_metadata_are_not_visible_evidence(self):
        raw = '<head><title>'+TITLE+'</title></head><script>'+BODY+'</script>'+BODY
        self.assertEqual(parse(raw)['changes'], parse()['changes'])

    def test_missing_and_ambiguous_titles_fail(self):
        for body in [BODY.replace(TITLE, '臺灣中型100審核'), BODY+TITLE]:
            with self.assertRaisesRegex(ValueError, 'title'):
                parse(body)

    def test_wrong_quarter_fails(self):
        with self.assertRaisesRegex(ValueError, 'quarter'):
            parse(quarter='2024Q2')

    def test_ambiguous_timestamp_fails(self):
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            parse(BODY+'2024/03/02 17:01')

    def test_ordering_fails(self):
        with self.assertRaisesRegex(ValueError, 'ordering'):
            parse(BODY.replace('2024/03/01', '2024/03/20'))

    def test_missing_effective_date_fails(self):
        with self.assertRaisesRegex(ValueError, 'dates'):
            parse(BODY.replace('2024年3月18日', '未知'))

    def test_duplicate_and_unbalanced_events_fail(self):
        for body in [BODY.replace('世芯-KY(3661)。', '世芯-KY(3661)、其他(1234)。'), BODY.replace('豐泰(9910)。', '世芯-KY(3661)。')]:
            with self.assertRaisesRegex(ValueError, 'Unbalanced/duplicate'):
                parse(body)

    def test_unparsed_symbol_fails_without_silently_dropping_it(self):
        with self.assertRaisesRegex(ValueError, 'residue'):
            parse(BODY.replace('世芯-KY(3661)。', '世芯-KY(3661)、未知(ABCD)。'))

    def test_zero_change_review_is_valid_and_retained(self):
        r = parse(BODY.replace('世芯-KY(3661)。', '無。').replace('豐泰(9910)。', '無。'))
        self.assertEqual(r['changes'], [])

    def test_whitespace_and_inline_markup(self):
        self.assertEqual(parse(BODY.replace('世芯-KY', '<span>世芯-KY</span>'))['changes'], parse()['changes'])


class CalendarCostTests(unittest.TestCase):
    def test_uses_second_session_not_calendar_day(self):
        clock = pd.to_datetime(['2024-06-21','2024-06-24','2024-06-25','2024-06-27','2024-06-28'])
        self.assertEqual(event_endpoints(clock,'2024-06-24',3), (pd.Timestamp('2024-06-25'),pd.Timestamp('2024-06-28')))

    def test_entire_market_clock_horizon_and_inclusive_entry(self):
        clock = pd.bdate_range('2024-03-18', periods=25)
        start, end = event_endpoints(clock,'2024-03-18',20)
        self.assertEqual(start, clock[1])
        self.assertEqual(end, clock[20])
        self.assertEqual(len(clock[(clock>=start)&(clock<=end)]),20)

    def test_missing_tail_duplicate_reversed_clock_fail(self):
        clock = pd.bdate_range('2024-03-18', periods=5)
        for dates, horizon in [(clock,20),(clock[::-1],2),(clock.append(clock[:1]),2),(clock,0)]:
            with self.assertRaises(ValueError):
                event_endpoints(dates,'2024-03-18',horizon)

    def test_cost_formula_and_fair_benchmark(self):
        self.assertAlmostEqual(quote_return(100,110,.005), 110*.995/(100*1.005)-1)
        for cost in [0,.0025,.005]:
            self.assertEqual(quote_return(100,100,cost)-quote_return(200,200,cost),0)
            self.assertAlmostEqual(quote_return(100,110,cost)-quote_return(100,105,cost), .05*(1-cost)/(1+cost))

    def test_invalid_cost_and_quotes_rejected(self):
        for args in [(0,100,0),(1,np.nan,0),(1,1,-.001),(1,1,1),(1,1,np.inf)]:
            with self.assertRaises(ValueError):
                quote_return(*args)

    def test_numpy_quote_scalars_produce_json_safe_decisions(self):
        value = quote_return(np.float64(100), np.float64(110), .005)
        self.assertIs(type(value), float)
        self.assertEqual(json.loads(json.dumps(dict(passed=value > 0))), dict(passed=True))


class IndependentAuditTests(unittest.TestCase):
    def fixture(self):
        clock = pd.bdate_range('2024-01-01', '2025-02-20')
        reviews, rows = [], []
        symbols = ['0050']+[str(1000+i) for i in range(8)]
        price = pd.DataFrame([(d, symbol, 100., 100.) for d in clock for symbol in symbols], columns=['date','symbol','adj_open','adj_close']).set_index(['date','symbol'])
        costs = [.0025,.005]
        for number, effective in enumerate(['2024-03-18','2024-06-24','2024-09-23','2024-12-23']):
            quarter = '2024Q'+str(number+1)
            start, end = event_endpoints(clock, effective, 20)
            changes = [dict(action=action, symbol=str(1000+number*2+i)) for i, action in enumerate(['add','delete'])]
            reviews.append(dict(quarter=quarter,effective_from=effective,source_sha256='a'*64,changes=changes))
            for change in changes:
                price.loc[(end, change['symbol']), 'adj_close'] = 110.
                rows.append(dict(quarter=quarter,**change,entry_date=str(start.date()),exit_date=str(end.date()),implementation_close=str((start-pd.Timedelta(days=7)).date()),source_sha256='a'*64,status='ok',entry_proxy=100.,exit_proxy=110.,benchmark_entry_proxy=100.,benchmark_exit_proxy=100.,historical_pit_verified=False,scenarios=[dict(one_way_cost=c,net_quote_change=quote_return(100,110,c),benchmark_net_quote_change=quote_return(100,100,c),relative_quote_change=quote_return(100,110,c)-quote_return(100,100,c)) for c in costs]))
        relative = rows[0]['scenarios'][1]['relative_quote_change']
        summary = dict(rows=rows,historical_pit_gate_passed=False,endpoints_complete=True,primary_deletion_quarter_means={r['quarter']:relative for r in reviews},primary_deletion_median=relative,continuation_gate_passed=True,decision='separate_independent_event_proposal_only')
        c = dict(reviews=reviews,horizon_market_sessions=20,primary_one_way_cost=.005,one_way_hypothetical_costs=costs)
        return summary,dict(records=reviews),c,price,clock

    def test_audit_full_cohort_provenance_calendar_and_arithmetic(self):
        s,ledger,c,prices,clock = self.fixture()
        r = audit_rows(s,ledger,c,prices,clock)
        self.assertEqual(r['scenarios'],16)
        self.assertTrue(r['quote_provenance_verified'])
        self.assertTrue(r['decision_gate_verified'])

    def test_wrong_date_and_source_identity_rejected(self):
        for key,value in [('entry_date','2024-03-18'),('source_sha256','b'*64)]:
            s,ledger,c,prices,clock = self.fixture()
            s['rows'][0][key] = value
            with self.assertRaisesRegex(ValueError,'endpoint/source'):
                audit_rows(s,ledger,c,prices,clock)

    def test_self_consistent_quote_tampering_rejected(self):
        s,ledger,c,prices,clock = self.fixture()
        s['rows'][0]['entry_proxy'] = 99.
        with self.assertRaisesRegex(ValueError,'provenance'):
            audit_rows(s,ledger,c,prices,clock)

    def test_missing_event_and_false_gap_rejected(self):
        s,ledger,c,prices,clock = self.fixture()
        missing = copy.deepcopy(s);missing['rows'].pop()
        with self.assertRaisesRegex(ValueError,'cohort'):
            audit_rows(missing,ledger,c,prices,clock)
        s['rows'][0]['status'] = 'endpoint_gap'
        s['rows'][0]['scenarios'] = []
        with self.assertRaisesRegex(ValueError,'False endpoint gap'):
            audit_rows(s,ledger,c,prices,clock)

    def test_actual_missing_endpoint_remains_and_fails_gate(self):
        s,ledger,c,prices,clock = self.fixture()
        row=s['rows'][0]
        prices.loc[(pd.Timestamp(row['entry_date']),row['symbol']),'adj_open']=np.nan
        row['status']='endpoint_gap';row['scenarios']=[]
        s['endpoints_complete']=False;s['continuation_gate_passed']=False;s['decision']='close_fixed_pilot_no_tuning'
        self.assertEqual(audit_rows(s,ledger,c,prices,clock)['scenarios'],14)

    def test_tampered_aggregates_gate_or_pit_rejected(self):
        for key,value in [('primary_deletion_median',.99),('continuation_gate_passed',False),('historical_pit_gate_passed',True)]:
            s,ledger,c,prices,clock=self.fixture();s[key]=value
            with self.assertRaises(ValueError):
                audit_rows(s,ledger,c,prices,clock)


if __name__ == '__main__':
    unittest.main()
