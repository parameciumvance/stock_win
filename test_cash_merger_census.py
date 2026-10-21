"""The finite title census retains every generic form and rejects scope drift."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import cash_merger_census as census
import frontier_sources
import merger_census_sources
from merger_announcement_index import parse_index
from test_merger_document import fixture


def inputs():
    original_rows, raw = [], []
    for number, (issuer, subject, text) in enumerate([
        ('1103', '現金股份轉換案', '現金條款仍待股東會，長篇原文只留輸入'),
        ('2887', '金融機構股票合併案', '股票對價，長篇原文只留輸入'),
        ('5203', '停止與子公司簡易合併案', '取消合併，長篇原文只留輸入'),
        ('2324', '子公司股份轉換案', '子公司交易，長篇原文只留輸入'),
    ], 1):
        body, original = fixture(text, issuer=issuer, sequence=str(number), subject=subject)
        original.update(COMPANY_NAME='原名稱', AN_NAME='發行有價證券、減資、併購或股份轉交換',
                        CODE_NAME='原產業', AN_CODE='M11', TYPEK='上市')
        original_rows.append(original)
        raw.append(body)
    quarter = parse_index(json.dumps(dict(data=original_rows, status='success', message=['回傳成功']),
                                    ensure_ascii=False).encode())
    rows = []
    for number, record in enumerate(quarter['rows']):
        locator = (dict(original_source=dict(archive_sha256='a' * 64, member='raw/reused.html'))
                   if number == 0 else dict(new_filename=f'original_{number}.html'))
        rows.append(dict(event_id=record['event_id'], index_original_fields=record['original_fields'], **locator))
    selection = dict(source_quarter_sha256=quarter['body_sha256'], rows=rows)
    title = dict(quarter_source_sha256=quarter['body_sha256'], explicit_merger_title_cohort_count=4,
                 explicit_merger_title_cohort=[dict(event_id=row['event_id']) for row in quarter['rows']])
    bodies = {row['event_id']: body for row, body in zip(quarter['rows'], raw, strict=True)}
    return quarter, selection, title, bodies


def fixed_inputs():
    originals, bodies = [], []
    for number in range(19):
        body, original = fixture('尚待條款資格審查', issuer=str(1100 + number),
                                 sequence=str(number + 1), subject='合併公告')
        original.update(COMPANY_NAME='原名稱', AN_NAME='發行有價證券、減資、併購或股份轉交換',
                        CODE_NAME='原產業', AN_CODE='M11', TYPEK='上市')
        originals.append(original)
        bodies.append(body)
    quarter_body = json.dumps(dict(data=originals, status='success', message=['回傳成功']),
                              ensure_ascii=False).encode()
    quarter = parse_index(quarter_body)
    rows, requests = [], []
    for number, row in enumerate(quarter['rows']):
        name = f'doc{number}.html'
        source = (dict(original_source=dict(archive_sha256='a' * 64, member='raw/' + name))
                  if number < 4 else dict(new_filename=name))
        rows.append(dict(event_id=row['event_id'], index_original_fields=row['original_fields'], **source))
        if number >= 4:
            requests.append(dict(filename=name, url=row['original_fields']['HYPERLINK']))
    selection = dict(source_quarter_sha256=quarter['body_sha256'], rows=rows)
    title = dict(quarter_source_sha256=quarter['body_sha256'], explicit_merger_title_cohort_count=19,
                 explicit_merger_title_cohort=[dict(event_id=row['event_id']) for row in rows])
    cfg = dict(expected_documents=19, expected_new_requests=15, expected_reused_documents=4,
               reused_archives=[dict(out='old-out', batch='controls', archive_sha256='a' * 64)])
    return cfg, dict(requests=requests), quarter, selection, title, quarter_body, bodies


def preflight_fixture(directory):
    cfg, requests, quarter, selection, title, quarter_body, bodies = fixed_inputs()
    root = Path(directory)
    for key, value in [('selection_manifest', selection), ('title_census', title)]:
        path = root / (key + '.json')
        path.write_text(json.dumps(value))
        cfg[key] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    cfg['source_quarter'] = dict(out='quarter-out', batch='discovery', member='raw/quarter.json',
                                archive_sha256='b' * 64, body_sha256=quarter['body_sha256'],
                                start='2026-07-01', end='2026-09-30')
    quarter_zip = root / 'quarter.zip'
    with zipfile.ZipFile(quarter_zip, 'w') as archive:
        archive.writestr('raw/quarter.json', quarter_body)
    old_cfg = dict(requests=[dict(filename=f'doc{n}.html', url=row['index_original_fields']['HYPERLINK'])
                             for n, row in enumerate(selection['rows'][:4])])
    old_bytes = json.dumps(old_cfg).encode()
    records = [dict(request=item, http_status=200, exit_code=0,
                    sha256=hashlib.sha256(bodies[n]).hexdigest()) for n, item in enumerate(old_cfg['requests'])]
    old_zip = root / 'old.zip'
    with zipfile.ZipFile(old_zip, 'w') as archive:
        archive.writestr('requests.json', old_bytes)
        archive.writestr('raw/results.json', json.dumps(dict(workers=2, requests=records,
                          config_sha256=hashlib.sha256(old_bytes).hexdigest())))
        for n, record in enumerate(records):
            archive.writestr('raw/' + record['request']['filename'], bodies[n])
            archive.writestr('raw/' + record['request']['filename'] + '.meta.json', json.dumps(record))
    policy = root / 'policy.json'
    policy.write_text(json.dumps(cfg))
    packages = {'quarter-out': dict(sha256='b' * 64, retrieved=str(quarter_zip)),
                'old-out': dict(sha256='a' * 64, retrieved=str(old_zip))}
    return cfg, requests, SimpleNamespace(POLICY=policy), packages


class CashMergerCensusTests(unittest.TestCase):
    def test_all_forms_identity_and_full_text_retained_without_semantic_qualification(self):
        arguments = inputs()
        full, summary = census.replay_documents(*arguments)
        self.assertEqual(len(full), 4)
        self.assertEqual(summary['new_document_count'], 3)
        self.assertEqual(summary['reused_document_count'], 1)
        self.assertTrue(summary['all_selected_original_identities_verified'])
        self.assertEqual({row['issuer'] for row in full}, {'1103', '2887', '5203', '2324'})
        self.assertTrue(all('長篇原文只留輸入' in row['description'] for row in full))
        self.assertNotIn('長篇原文只留輸入', json.dumps(summary, ensure_ascii=False))
        for row in full:
            self.assertEqual(row['body_sha256'], hashlib.sha256(arguments[3][row['event_id']]).hexdigest())
            self.assertIsNone(row['eligible_cash_merger'])
            self.assertIsNone(row['transaction_form'])
        for flag in ('title_census_is_all_eligible_cash_mergers', 'transaction_semantics_classified',
                     'cash_claim_source_gate_passed', 'all_eligible_cash_mergers_known',
                     'historical_pit_verified', 'source_gate_passed', 'profit_edge_proven',
                     'market_prices_or_returns_read', 'orders_authorized'):
            self.assertFalse(summary[flag], flag)

    def test_dropping_non_cash_or_canceled_titles_does_not_pass_the_full_census(self):
        quarter, selection, title, bodies = inputs()
        selection['rows'] = selection['rows'][:1]
        with self.assertRaisesRegex(ValueError, 'entire frozen explicit-title census'):
            census.replay_documents(quarter, selection, title, bodies)

    def test_quarter_snapshot_and_selected_original_fields_cannot_change(self):
        for failure in ('source_sha', 'original_fields'):
            quarter, selection, title, bodies = inputs()
            if failure == 'source_sha':
                selection['source_quarter_sha256'] = 'wrong snapshot'
            else:
                selection['rows'][0]['index_original_fields'] = dict(
                    selection['rows'][0]['index_original_fields'], SUBJECT='後來替換的主旨')
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                census.replay_documents(quarter, selection, title, bodies)

    def test_duplicate_selection_and_extra_or_missing_bodies_are_rejected(self):
        for failure in ('duplicate', 'extra_body', 'missing_body'):
            quarter, selection, title, bodies = inputs()
            if failure == 'duplicate':
                selection['rows'][1] = copy.deepcopy(selection['rows'][0])
            elif failure == 'extra_body':
                bodies['unrequested-event'] = b'<html>not selected</html>'
            else:
                bodies.pop(next(iter(bodies)))
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                census.replay_documents(quarter, selection, title, bodies)

    def test_wrong_original_identity_or_error_page_is_not_a_valid_document(self):
        for body in (b'<html>HTTP502 upstream error</html>', inputs()[3][next(iter(inputs()[3]))].replace(b'1103', b'9999')):
            quarter, selection, title, bodies = inputs()
            bodies[selection['rows'][0]['event_id']] = body
            with self.subTest(body=body[:50]), self.assertRaises(ValueError):
                census.replay_documents(quarter, selection, title, bodies)

    def test_reused_source_cannot_be_requeried_or_have_two_competing_locators(self):
        for failure in ('both', 'neither', 'unsafe_member', 'unsafe_filename'):
            quarter, selection, title, bodies = inputs()
            row = selection['rows'][0]
            if failure == 'both':
                row['new_filename'] = 'requery.html'
            elif failure == 'neither':
                row.pop('original_source')
            elif failure == 'unsafe_member':
                row['original_source']['member'] = 'raw/../outside.html'
            else:
                row.pop('original_source')
                row['new_filename'] = '../outside.html'
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                census.replay_documents(quarter, selection, title, bodies)

    def test_small_summary_preserves_exact_subject_and_source_hashes(self):
        arguments = inputs()
        _, summary = census.replay_documents(*arguments)
        for actual, original in zip(summary['documents'], arguments[1]['rows'], strict=True):
            self.assertEqual(actual['subject'], original['index_original_fields']['SUBJECT'])
            self.assertEqual(len(actual['body_sha256']), 64)
            self.assertEqual(len(actual['description_sha256']), 64)
            self.assertNotIn('raw_metadata', actual)
            self.assertNotIn('description', actual)
        self.assertIsNone(summary['valid_prospective_signal_date'])
        self.assertEqual(summary['frozen_title_event_ids'], sorted(arguments[3]))
        self.assertNotIn('frozen_title_case_ids', summary)

    def test_exact19_request_plan_rejects_changed_population_urls_and_reused_routes(self):
        for failure in ('counts', 'missing_event', 'fields', 'url', 'filename', 'reused_archive', 'reused_duplicate'):
            cfg, requests, quarter, selection, title, _, _ = fixed_inputs()
            if failure == 'counts':
                cfg['expected_new_requests'] = 16
            elif failure == 'missing_event':
                selection['rows'].pop()
            elif failure == 'fields':
                selection['rows'][0]['index_original_fields'] = dict(selection['rows'][0]['index_original_fields'],
                                                                    SUBJECT='事後替換')
            elif failure == 'url':
                requests['requests'][0]['url'] += '&different=1'
            elif failure == 'filename':
                requests['requests'][0]['filename'] = 'substitute.html'
            elif failure == 'reused_archive':
                selection['rows'][0]['original_source']['archive_sha256'] = 'c' * 64
            else:
                selection['rows'][1]['original_source'] = copy.deepcopy(selection['rows'][0]['original_source'])
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                census.validate_selection(cfg, requests, quarter, selection, title)

    def test_saved_prior_archives_bind_reused_documents_before_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg, requests, module, packages = preflight_fixture(directory)
            with patch.object(census, 'readback', side_effect=lambda out, batch: (packages[out], {})):
                result = census.preflight(module, 'originals', requests)
            self.assertEqual(len(result['selection']['rows']), 19)
            # A valid archived body is not enough when its request belongs to another pointer.
            selection_path = Path(cfg['selection_manifest']['path'])
            selection = json.loads(selection_path.read_text())
            selection['rows'][0]['original_source']['member'] = 'raw/doc1.html'
            selection['rows'][1]['original_source']['member'] = 'raw/doc0.html'
            selection_path.write_text(json.dumps(selection))
            cfg['selection_manifest']['sha256'] = hashlib.sha256(selection_path.read_bytes()).hexdigest()
            module.POLICY.write_text(json.dumps(cfg))
            with patch.object(census, 'readback', side_effect=lambda out, batch: (packages[out], {})), \
                 self.assertRaisesRegex(ValueError, 'Reused original route'):
                census.preflight(module, 'originals', requests)

    def test_selection_or_title_hash_drift_aborts_before_live_source_call(self):
        for key in ('selection_manifest', 'title_census'):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                cfg, requests, module, packages = preflight_fixture(directory)
                Path(cfg[key]['path']).write_text('{}')
                with patch.object(frontier_sources, 'ROOT'), patch.object(frontier_sources, 'OUT'), \
                     patch.object(frontier_sources, 'POLICY'), \
                     patch.object(merger_census_sources, 'POLICY', module.POLICY), \
                     patch.object(frontier_sources, 'plan', return_value=(Path('requests.json'), requests, Path('raw'), None)), \
                     patch.object(frontier_sources, 'acquire') as live, \
                     patch.object(census, 'readback', side_effect=lambda out, batch: (packages[out], {})), \
                     self.assertRaisesRegex(ValueError, 'Frozen selection or title census differs'):
                    merger_census_sources.acquire()
                live.assert_not_called()

    def test_transport_failure_cannot_become_valid_original_even_with_saved_body(self):
        census.require_successful_originals([dict(http_status=200, exit_code=0)])
        for status, code in [(502, 0), (200, 28), (None, 0), (200, None), (True, 0), (200, False)]:
            with self.subTest(status=status, code=code), self.assertRaisesRegex(ValueError, 'HTTP200 and exit0'):
                census.require_successful_originals([dict(http_status=status, exit_code=code)])

    def test_source_wrapper_is_process_local_and_does_not_touch_prior_policy(self):
        with patch.object(frontier_sources, 'ROOT', Path('sentinel-root')), \
             patch.object(frontier_sources, 'OUT', Path('sentinel-out')), \
             patch.object(frontier_sources, 'POLICY', Path('sentinel-policy')), \
             patch.object(frontier_sources, 'plan', return_value=('requests', {}, 'raw', None)) as plan, \
             patch.object(census, 'preflight') as preflight:
            self.assertEqual(merger_census_sources.plan(), ('requests', {}, 'raw', None))
            plan.assert_called_once_with('originals')
            preflight.assert_called_once_with(frontier_sources, 'originals', {})
            self.assertEqual(frontier_sources.ROOT, merger_census_sources.ROOT)
            self.assertEqual(frontier_sources.OUT, merger_census_sources.OUT)
            self.assertEqual(frontier_sources.POLICY, merger_census_sources.POLICY)


if __name__ == '__main__':
    unittest.main()
