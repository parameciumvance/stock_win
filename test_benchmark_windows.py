import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from benchmark_windows import CashWindowBenchmark, WindowUnavailable, direct_account, load_verified
from test_cash_benchmark import fixture
from benchmark_windows_run import audit_cases


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.p,self.divs,self.split,*_=fixture()
        self.b=CashWindowBenchmark(self.p,self.divs,self.split)

    def test_entry_on_exdate_gets_no_old_entitlement(self):
        r=self.b.window('2024-01-03','2024-01-05')
        self.assertEqual(r['entitlements'],[])
        self.assertEqual(r['dividend_receivable'],0)
        self.assertEqual(r['gross_change'],0)

    def test_entry_after_exdate_before_payment_does_not_inherit_receivable(self):
        r=self.b.window('2024-01-04','2024-01-08')
        self.assertEqual(r['settled_cash'],0)
        self.assertEqual(r['dividend_receivable'],0)
        self.assertEqual(r['gross_change'],0)

    def test_exit_on_exdate_retains_unpaid_right(self):
        r=self.b.window('2024-01-08','2024-01-10')
        self.assertEqual(r['ending_units'],4000)
        self.assertEqual(r['dividend_receivable'],2000)
        self.assertAlmostEqual(r['gross_change'],.02)

    def test_split_on_entry_is_not_applied_twice(self):
        r=self.b.window('2024-01-09','2024-01-10')
        self.assertEqual(r['ending_units'],1000)
        self.assertEqual(r['dividend_receivable'],500)
        self.assertEqual(r['initial_quote_cost'],25000)

    def test_cash_arrives_on_calendar_payment_date_without_reinvestment(self):
        before=self.b.window('2024-01-02','2024-01-05')
        after=self.b.window('2024-01-02','2024-01-08')
        self.assertEqual(before['settled_cash'],0)
        self.assertEqual(before['dividend_receivable'],2000)
        self.assertEqual(after['settled_cash'],2000)
        self.assertEqual(after['dividend_receivable'],0)
        self.assertEqual(before['ending_units'],after['ending_units'])
        self.assertEqual(before['gross_change'],after['gross_change'])

    def test_single_session_uses_open_to_close_no_exdate_rights(self):
        r=self.b.window('2024-01-03','2024-01-03')
        self.assertEqual(r['market_sessions'],1)
        self.assertEqual(r['gross_change'],0)
        self.assertFalse(r['actual_fill_verified'])
        self.assertFalse(r['historical_pit_verified'])
        self.assertFalse(r['source_verified'])
        self.assertIsNone(r['provenance'])

    def test_full_window_independent_decimal_formula(self):
        r=self.b.window('2024-01-02','2024-01-12')
        expected=direct_account(self.p,self.divs,self.split,r['entry'],r['exit'])
        for k,value in expected.items():
            if k=='entitlements':self.assertEqual(r[k],value)
            else:self.assertAlmostEqual(r[k],value,places=8)
        self.assertEqual(r['settled_cash'],2000)
        self.assertEqual(r['dividend_receivable'],2000)

    def test_repeated_queries_and_input_mutation_do_not_change_snapshot(self):
        before=self.b.window('2024-01-02','2024-01-12')
        self.b.window('2024-01-09','2024-01-12')
        self.divs[0]['cash_per_unit']=999
        self.p.loc[0,'close']=999
        self.assertEqual(self.b.window('2024-01-02','2024-01-12'),before)

    def test_horizon_counts_market_sessions_including_entry(self):
        self.assertEqual(self.b.dates('2024-01-05',2),'2024-01-08')
        self.assertEqual(self.b.dates('2024-01-05',1),'2024-01-05')
        with self.assertRaisesRegex(WindowUnavailable,'Insufficient'):
            self.b.dates('2024-01-12',2)

    def test_invalid_horizon_date_coverage_instrument_and_order_fail(self):
        for h in [0,-1,1.0,True,'20']:
            with self.assertRaises(WindowUnavailable):self.b.dates('2024-01-02',h)
        for date in ['2024-1-2','2024-02-30','2024-01-02T00:00:00Z','2024-01-06','2023-12-31']:
            with self.assertRaises(WindowUnavailable):self.b.window(date,'2024-01-12')
        with self.assertRaises(WindowUnavailable):self.b.window('2024-01-12','2024-01-02')
        with self.assertRaises(WindowUnavailable):self.b.window('2024-01-02','2024-01-12','006208')

    def test_halt_is_counted_but_not_a_tradable_endpoint(self):
        p=self.p.copy();split=dict(self.split,halt_dates=['2024-01-04'])
        p.loc[p.date.eq('2024-01-04'),['open','close','adj_open','adj_close','causal_factor']]=np.nan
        b=CashWindowBenchmark(p,self.divs,split)
        self.assertEqual(b.dates('2024-01-03',2),'2024-01-04')
        with self.assertRaisesRegex(WindowUnavailable,'Unquoted'):b.window('2024-01-03','2024-01-04')
        with self.assertRaisesRegex(WindowUnavailable,'Unquoted'):b.window('2024-01-04','2024-01-05')
        self.assertEqual(b.window('2024-01-03','2024-01-05')['stale_market_sessions'],1)

    def test_corrupt_pinned_checkpoint_and_missing_dependencies_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'checkpoint.json';p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'checkpoint differs'):load_verified(p,'0'*64)
            from research_runtime import sha256
            p.write_text(json.dumps(dict(files={str(Path(folder)/'absent'):'a'*64})))
            with self.assertRaises(FileNotFoundError):load_verified(p,sha256(p))


class CompleteCohortTests(unittest.TestCase):
    def cohort(self, missing=False):
        p,divs,split,*_=fixture()
        if missing:
            split=dict(split,halt_dates=['2024-01-04'])
            p.loc[p.date.eq('2024-01-04'),['open','close','adj_open','adj_close','causal_factor']]=np.nan
        b=CashWindowBenchmark(p,divs,split)
        b._provenance={'synthetic_fixture':True}
        rows=[]
        for h in [2,4]:
            for i,date in enumerate(b.clock):
                row=dict(entry=str(date.date()),horizon=h,exit=None,account=None)
                if i+h>len(b.clock):row['status']='insufficient_horizon'
                else:
                    row['exit']=b.dates(row['entry'],h)
                    try:row['account']=b.window(row['entry'],row['exit']);row['status']='accepted'
                    except WindowUnavailable:row['status']='unquoted_endpoint'
                rows.append(row)
        return rows,p,divs,split,[2,4]

    def test_independent_cohort_keeps_rejected_tails_and_halt_endpoints(self):
        args=self.cohort(missing=True)
        result=audit_cases(*args)
        self.assertEqual(result['attempts'],len(args[0]))
        self.assertGreater(result['rejected_windows_retained'],4)
        self.assertGreater(result['accepted_accounts_verified'],0)

    def test_missing_duplicate_or_extra_window_rejected(self):
        rows,*args=self.cohort()
        for changed in [rows[:-1],rows+[rows[0]],rows+[dict(rows[0],horizon=99)]]:
            with self.assertRaisesRegex(ValueError,'cohort'):audit_cases(changed,*args)

    def test_rejected_window_cannot_be_given_zero_return(self):
        rows,*args=self.cohort()
        rows[-1]['account']={'gross_change':0}
        with self.assertRaisesRegex(ValueError,'Rejected window'):audit_cases(rows,*args)

    def test_boundary_shift_and_account_identity_rejected(self):
        rows,*args=self.cohort()
        bad=copy.deepcopy(rows);bad[0]['exit']='2024-01-04'
        with self.assertRaisesRegex(ValueError,'boundary'):audit_cases(bad,*args)
        bad=copy.deepcopy(rows);bad[0]['account']['market_sessions']=999
        with self.assertRaisesRegex(ValueError,'endpoint identity'):audit_cases(bad,*args)

    def test_wrong_entitlement_cash_and_promotion_rejected(self):
        rows,*args=self.cohort()
        for key,value in [('settled_cash',999),('entitlements',[]),('profit_edge_proven',True),('source_verified',False),('initial_units',999),('hypothetical_quote_acquisition',False)]:
            bad=copy.deepcopy(rows);bad[0]['account'][key]=value
            with self.assertRaises(ValueError):audit_cases(bad,*args)

    def test_changed_pinned_dependency_rejected_before_any_archive_access(self):
        from research_runtime import sha256
        with tempfile.TemporaryDirectory() as directory:
            dep=Path(directory)/'dependency';dep.write_text('original')
            checkpoint=Path(directory)/'checkpoint.json';checkpoint.write_text(json.dumps(dict(files={str(dep):sha256(dep)})))
            pinned=sha256(checkpoint);dep.write_text('changed')
            with self.assertRaisesRegex(ValueError,'dependency differs'):load_verified(checkpoint,pinned)


if __name__=='__main__':unittest.main()
