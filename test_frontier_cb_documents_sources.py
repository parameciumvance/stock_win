"""Synthetic source identity and draft/pre-IO failure tests; no live sources."""
import copy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import frontier_cb_documents_sources as source


def digest(body):
    return hashlib.sha256(body).hexdigest()


def encoded(value):
    return json.dumps(value,ensure_ascii=False).encode()


def pointer(issuer,bond,series='1'):
    return ('https://mopsov.twse.com.tw/mops/web/t120sg01?TYPEK=&bond_id='+bond+
        '&bond_kind=5&bond_subn=%24M00000001&bond_yrn='+series+
        '&come=2&encodeURIComponent=1&firstin=ture&issuer_stock_code='+issuer+
        '&monyr_reg=202609&pg=&step=0&tg=')


def fixture():
    rows = [[str(1000+i),'Issuer'+str(i),'Bond'+str(i),'113/01/01',
             pointer(str(1000+i),str(1000+i)+'1')] for i in range(389)]
    controls = [('99587','9958','7',83,'113/10/28','2026-10-28'),
                ('68351','6835','1',85,'113/11/01','2026-11-01'),
                ('68741','6874','1',86,'113/11/04','2026-11-04')]
    for bond,issuer,series,number,listed,put in controls:
        rows[number-1] = [issuer,'Company'+issuer,'Company'+issuer+'Bond'+series,listed,pointer(issuer,bond,series)]
    raw = dict(stat='ok',tables=[dict(title='最近上櫃轉(交)換公司債',subtitle='Original instructions',date='',
        fields=source.FIELDS,totalCount=389,notes=[],summary=[],data=rows)])
    calendar_fields = ['code','name','date','amount','yield']
    calendar_rows = [[str(i),'fixture','115/11/01','100.0000','0.0000'] for i in range(29)]
    original = dict(controls_bond_codes=source.CONTROL_CODES,original_calendar_population_count=29,
        original_calendar_fields=calendar_fields,original_calendar_rows=calendar_rows,controls=[])
    selection = dict(source_report_sha256=digest(encoded(raw)),source_report_records=389,
        source_report_fields=source.FIELDS,controls_bond_codes=source.CONTROL_CODES,
        original_calendar_population_count=29,original_calendar_fields=calendar_fields,
        original_calendar_rows=calendar_rows,controls=[])
    requests = []
    for bond,issuer,series,number,listed,put in controls:
        row = rows[number-1]
        original['controls'].append(dict(bond_code=bond,nominal_put_date=put,
            metadata_20261020_original=dict(IssuerCode=issuer,SeriesNumber=series,
                ListingDate='2024'+listed[4:6]+listed[7:9])))
        selection['controls'].append(dict(bond_code=bond,issuer=issuer,issuer_name=row[1],bond_name=row[2],
            listed_date=listed,report_row_number=number,report_original_fields=row,issuance_url=row[4],
            nominal_put_date=put,request_filename=bond+'_issuance.html'))
        requests.append(dict(filename=bond+'_issuance.html',url=row[4],method='GET'))
    return raw,original,selection,requests


class ReportIdentityTests(unittest.TestCase):
    def setUp(self):
        self.raw,self.original,self.selection,self.requests = fixture()

    def select(self):
        return source.select_issuance(source.validate_report(encoded(self.raw)),self.selection,self.requests,
                                      original_selection=self.original)

    def test_three_whole_saved_urls_and29population_remain_unchanged(self):
        result = self.select()
        self.assertEqual([row['bond_code'] for row in result['identities']],source.CONTROL_CODES)
        self.assertTrue(result['whole_URLs_copied_without_reencoding'])
        self.assertEqual(result['returned_report_records'],389)
        self.assertFalse(result['complete_original29_contract_coverage_verified'])
        self.assertFalse(result['source_gate_passed'])

    def test_unselected_row_identity_is_validated(self):
        self.raw['tables'][0]['data'][0][4] = self.raw['tables'][0]['data'][0][4].replace('issuer_stock_code=1000','issuer_stock_code=9999')
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            source.validate_report(encoded(self.raw))

    def test_missing_or_duplicate_report_rows_fail(self):
        original = copy.deepcopy(self.raw)
        self.raw['tables'][0]['data'].pop()
        with self.assertRaisesRegex(ValueError,'count/schema'):
            source.validate_report(encoded(self.raw))
        self.raw = original
        self.raw['tables'][0]['data'][0] = self.raw['tables'][0]['data'][1]
        with self.assertRaisesRegex(ValueError,'Duplicate report'):
            source.validate_report(encoded(self.raw))

    def test_duplicate_query_unknown_field_and_official_typo_correction_fail(self):
        original = copy.deepcopy(self.raw)
        for old,new in (('&tg=','&tg=&bond_id=10001'),('firstin=ture','firstin=true'),
                        ('monyr_reg=202609','monyr_reg=202613'),('bond_subn=%24','bond_subn=%2524')):
            self.raw = copy.deepcopy(original)
            self.raw['tables'][0]['data'][0][4] = self.raw['tables'][0]['data'][0][4].replace(old,new)
            with self.subTest(new=new),self.assertRaises(ValueError):
                source.validate_report(encoded(self.raw))

    def test_foreign_host_or_fragment_is_not_an_issuance_pointer(self):
        for url in (self.requests[0]['url'].replace('mopsov.twse.com.tw','example.com'),self.requests[0]['url']+'#x'):
            self.raw['tables'][0]['data'][82][4] = url
            with self.subTest(url=url),self.assertRaisesRegex(ValueError,'host/path'):
                source.validate_report(encoded(self.raw))

    def test_duplicate_root_key_and_reordered_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate JSON key'):
            source.validate_report(b'{"stat":"ok","stat":"ok","tables":[]}')
        self.raw['tables'][0]['fields'] = list(reversed(source.FIELDS))
        with self.assertRaisesRegex(ValueError,'fields/count/schema'):
            source.validate_report(encoded(self.raw))

    def test_changed_month_or_reencoded_query_is_not_a_literal_saved_request(self):
        for url in (self.requests[0]['url'].replace('202609','202610'),
                    self.requests[0]['url'].replace('%24','$')):
            self.requests[0]['url'] = url
            with self.subTest(url=url),self.assertRaisesRegex(ValueError,'entire literal saved URL'):
                self.select()

    def test_company_name_whitespace_and_wrong_row_number_are_not_normalized(self):
        original = copy.deepcopy(self.selection)
        self.selection['controls'][0]['issuer_name'] += '\r\n'
        with self.assertRaisesRegex(ValueError,'original row/company'):
            self.select()
        self.selection = original
        self.selection['controls'][0]['report_row_number'] = 85
        with self.assertRaisesRegex(ValueError,'original row/company'):
            self.select()

    def test_original_series_or_population_change_fails(self):
        self.original['controls'][0]['metadata_20261020_original']['SeriesNumber'] = '8'
        with self.assertRaisesRegex(ValueError,'metadata issuer/series'):
            self.select()
        self.original['controls'][0]['metadata_20261020_original']['SeriesNumber'] = '7'
        self.selection['original_calendar_rows'] = self.selection['original_calendar_rows'][:-1]
        with self.assertRaisesRegex(ValueError,'Frozen29 population'):
            self.select()

    def test_requests_cannot_drop_control_reorder_or_add_post_data(self):
        original = copy.deepcopy(self.requests)
        for changed in (original[:-1],list(reversed(original)),[dict(original[0],data=''),*original[1:]]):
            self.requests = changed
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                self.select()


def phase_policy():
    return dict(max_saved_requests=9,max_source_batches=3,workers=2,automatic_retries=0,
        prior_checkpoints={source.ROUTE_CHECKPOINT:'a'*64},
        prior_CB_allocations=dict(first_discovery_cap=12,first_discovery_actual=12,contract_route_cap=4,
            contract_route_actual=3,contract_route_batches_actual=3,contract_route_batch_cap=3,
            cumulative_CB_requests_before_phase=15,cumulative_CB_request_cap_after_phase=24,
            one_unused_contract_route_request_is_not_reused=True),
        new_allocation=dict(maximum_requests=9,maximum_batches=3,initial_issuance_GETs=3,
            maximum_contract_pointer_requests=3,maximum_actual_file_transfers=3,all_failed_requests_count=True))


class PreIOPolicyTests(unittest.TestCase):
    def setUp(self):
        self.paths = source.frontier_sources.ROOT,source.frontier_sources.OUT,source.frontier_sources.POLICY

    def tearDown(self):
        source.frontier_sources.ROOT,source.frontier_sources.OUT,source.frontier_sources.POLICY = self.paths

    def test_valid_finite_ledger(self):
        source.validate_phase_policy(phase_policy())

    def test_rehashed_draft_or_missing_route_checkpoint_stays_pre_native(self):
        for mutation in ('pending','draft','missing','badsha'):
            policy = phase_policy()
            if mutation == 'pending':
                policy['pending_prior_checkpoint'] = dict(path=source.ROUTE_CHECKPOINT,sha256=None)
            elif mutation == 'draft':
                policy['status'] = 'draft_rehashed'
            elif mutation == 'missing':
                policy['prior_checkpoints'] = {}
            else:
                policy['prior_checkpoints'][source.ROUTE_CHECKPOINT] = None
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as temp:
                path = Path(temp)/'repinned_protocol.json'
                path.write_bytes(encoded(policy))
                with (patch.object(source,'POLICY',path),
                      patch.object(source.frontier_sources,'native_acquire') as native,
                      patch.object(source.frontier_sources,'plan') as generic):
                    with self.assertRaises(ValueError):
                        source.execute('acquire')
                    generic.assert_not_called()
                    native.assert_not_called()

    def test_old_unused_request_cannot_change15plus9_or_create_fourth_batch(self):
        for mutation in ('reuse','before16','after25','fourth','new10'):
            policy = phase_policy()
            if mutation == 'reuse':policy['prior_CB_allocations']['one_unused_contract_route_request_is_not_reused'] = False
            elif mutation == 'before16':policy['prior_CB_allocations']['cumulative_CB_requests_before_phase'] = 16
            elif mutation == 'after25':policy['prior_CB_allocations']['cumulative_CB_request_cap_after_phase'] = 25
            elif mutation == 'fourth':policy['max_source_batches'] = 4
            else:policy['new_allocation']['maximum_requests'] = 10
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                source.validate_phase_policy(policy)


if __name__ == '__main__':
    unittest.main()
