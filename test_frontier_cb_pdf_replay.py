"""Synthetic byte/page/transport checks; no archived market or contract input."""
from copy import deepcopy
import unittest

from cash_merger_pdf_replay import digest
from frontier_cb_pdf_replay import ARCHIVE_SHA256, replay_terms, verify_annotation
from test_cash_merger_pdf_replay import pdf_bytes


def fixture():
    controls, bodies, records = [], {}, []
    for code in ('99587', '68351', '68741'):
        name, url = code + '_terms.pdf', 'https://mopsov.twse.com.tw/actual/' + code + '.pdf'
        controls.append(dict(bond_code=code, filename=name, url=url,
                             identity_terms=dict(issuer=['Issuer' + code], series=['Series1'])))
        raw = pdf_bytes(['Issuer' + code + ' Series1 conditional terms', None], mixed_image=True)
        bodies[name] = raw
        records.append(dict(request=dict(filename=name, url=url, method='GET'),
                            sha256=digest(raw), http_status=200, exit_code=0,
                            curl=dict(url_effective=url)))
    return controls, bodies, records, {name: digest(body) for name, body in bodies.items()}


class CbPdfReplayTests(unittest.TestCase):
    def test_all_three_full_pages_hashes_images_and_false_gates(self):
        controls, bodies, records, shas = fixture()
        fulls, summaries = replay_terms(controls, bodies, records, shas,
                                       {name: 2 for name in bodies})
        self.assertEqual([row['bond_code'] for row in summaries], ['99587', '68351', '68741'])
        for full, small in zip(fulls, summaries, strict=True):
            self.assertEqual(len(full['pages']), 2)
            self.assertTrue(small['text_identity_candidates_complete'])
            self.assertTrue(small['pages'][1]['empty_extracted_text'])
            self.assertTrue(small['visual_review_needed'])
            self.assertEqual(small['image_refs'][0]['physical_page'], 1)
            self.assertEqual(small['image_refs'][0]['image_number'], 1)
            self.assertEqual(len(small['image_refs'][0]['data_sha256']), 64)
            for page, page_summary in zip(full['pages'], small['pages'], strict=True):
                self.assertEqual(digest(page['text'].encode()), page_summary['text_sha256'])
            for key in ('source_gate_passed', 'cash_claim_source_gate_passed',
                        'historical_pit_verified', 'current_contract_version_verified',
                        'holder_put_contract_verified', 'actual_notice_or_payment_verified'):
                self.assertIs(small[key], False)

    def test_missing_identity_is_retained_uncertain_not_empty_contract(self):
        controls, bodies, records, shas = fixture()
        controls[0]['identity_terms']['issuer'] = ['DifferentIssuer']
        fulls, summaries = replay_terms(controls, bodies, records, shas)
        self.assertEqual(len(fulls), 3)
        self.assertFalse(summaries[0]['text_identity_candidates_complete'])
        self.assertIn('issuer', summaries[0]['missing_identity_candidate_fields'])
        self.assertFalse(summaries[0]['holder_put_contract_verified'])

    def test_exact_population_rejects_dropped_extra_and_duplicate_controls_or_records(self):
        controls, bodies, records, shas = fixture()
        variants = [
            (controls[:-1], bodies, records, shas),
            ([controls[0], controls[0], controls[2]], bodies, records, shas),
            (controls, {k: v for k, v in bodies.items() if k != controls[0]['filename']}, records, shas),
            (controls, dict(bodies, extra=b'extra'), records, shas),
            (controls, bodies, records[:-1], shas),
            (controls, bodies, [records[0], records[0], records[2]], shas),
        ]
        for args in variants:
            with self.subTest(populations=[len(x) for x in args]), self.assertRaises(ValueError):
                replay_terms(*args)

    def test_transport_hash_url_and_method_are_not_semantic_absence(self):
        controls, bodies, records, shas = fixture()
        mutations = [lambda r: r.update(http_status=404), lambda r: r.update(exit_code=28),
                     lambda r: r.update(http_status=True), lambda r: r.update(exit_code=False),
                     lambda r: r.update(sha256='0' * 64),
                     lambda r: r['request'].update(method='POST'),
                     lambda r: r['request'].update(url='https://example.invalid/wrong.pdf'),
                     lambda r: r['curl'].update(url_effective='https://example.invalid/error')]
        for mutation in mutations:
            changed = deepcopy(records)
            mutation(changed[0])
            with self.subTest(record=changed[0]), self.assertRaises(ValueError):
                replay_terms(controls, bodies, changed, shas)
        altered = dict(bodies)
        altered[controls[0]['filename']] += b'changed'
        with self.assertRaisesRegex(ValueError, 'SHA'):
            replay_terms(controls, altered, records, shas)

    def test_http200_html_and_wrong_page_expectation_fail(self):
        controls, bodies, records, shas = fixture()
        name = controls[0]['filename']
        bodies[name] = b'<html>contract download</html>'
        shas[name] = records[0]['sha256'] = digest(bodies[name])
        with self.assertRaisesRegex(ValueError, 'PDF magic'):
            replay_terms(controls, bodies, records, shas)
        controls, bodies, records, shas = fixture()
        with self.assertRaisesRegex(ValueError, 'expected page count'):
            replay_terms(controls, bodies, records, shas, {name: 3 for name in bodies})

    def test_timestamp_requires_both_aware_ordered_values(self):
        controls, bodies, records, shas = fixture()
        for started, observed in [('2026-10-23T01:00:00+00:00', None),
                                  ('2026-10-23T01:00:00', '2026-10-23T01:00:01'),
                                  ('2026-10-23T01:00:02+00:00', '2026-10-23T01:00:01+00:00')]:
            changed = deepcopy(records)
            changed[0]['request_started_at'] = started
            if observed is not None:
                changed[0]['observed_at'] = observed
            with self.subTest(started=started, observed=observed), self.assertRaises(ValueError):
                replay_terms(controls, bodies, changed, shas)

    def test_annotation_wrong_page_anchor_image_or_promoted_gate_fails(self):
        controls, bodies, records, shas = fixture()
        fulls, summaries = replay_terms(controls, bodies, records, shas)
        annotation = dict(source_archive_sha256=ARCHIVE_SHA256, documents=[],
                          source_gate_passed=False, cash_claim_source_gate_passed=False,
                          historical_pit_verified=False, profit_edge_proven=False, orders_authorized=False)
        for small in summaries:
            annotation['documents'].append(dict(filename=small['filename'], bond_code=small['bond_code'],
                body_sha256=small['body_sha256'], source_observed_at=small['actual_source_timestamps'],
                physical_page_count=2, all_physical_pages_read=[1, 2],
                findings=[dict(references=[dict(physical_page=1,
                    page_text_sha256=small['pages'][0]['text_sha256'], exact_anchors=['conditional terms'])])],
                visual_review=[dict(small['image_refs'][0], actually_viewed=True, observation='Synthetic red pixel.')],
                source_gate_passed=False, current_contract_version_verified=False))
        verified = verify_annotation(annotation, fulls, summaries)
        self.assertEqual(verified['text_anchors_verified'], 3)
        self.assertEqual(verified['image_references_verified'], 3)
        self.assertFalse(verified['semantic_interpretation_automatically_approved'])
        mutations = [lambda a: a['documents'][0]['findings'][0]['references'][0].update(physical_page=2),
                     lambda a: a['documents'][0]['findings'][0]['references'][0].update(exact_anchors=['not present']),
                     lambda a: a['documents'][0]['visual_review'][0].update(data_sha256='0'*64),
                     lambda a: a['documents'][0].update(source_gate_passed=True),
                     lambda a: a.update(historical_pit_verified=True)]
        for mutation in mutations:
            changed = deepcopy(annotation)
            mutation(changed)
            with self.assertRaises(ValueError):
                verify_annotation(changed, fulls, summaries)


if __name__ == '__main__':
    unittest.main()
