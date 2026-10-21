"""Metadata shape and unresolved terms do not establish an exercisable cash claim."""
import copy
import hashlib
import json
import unittest

from frontier_cb_metadata import EXPECTED_FIELDS, parse_metadata


def row(**changes):
    result = {field: '' for field in EXPECTED_FIELDS}
    result.update(Date='20261020', IssuerCode='2756', IssuerName='原發行人', BondCode='27561',
                  BondType='5', SeriesNumber='112-1', IssueDate='20240530', MaturityDate='20290530',
                  IssueAmount='500000000', OutstandingAmount='400000000', CouponRate='0.000000',
                  PutOptionPrice='100.0000', PutOptionDate='20270530', TenorYear='5', TenorMonth='0',
                  ListingDate='20240530', ListingStatus='2', Currency='1', PrincipalRepayment='1',
                  OfferingMethod='7', Guaranteed='2',
                  **{'Conversion/ExchangePriceAtIssuance': '50.0000',
                     'Conversion/ExchangePeriodStartDate': '20240831',
                     'Conversion/ExchangePeriodEndDate': '20290530'})
    result.update(changes)
    return result


def response(rows):
    return json.dumps(rows, ensure_ascii=False).encode()


class FrontierCBMetadataTests(unittest.TestCase):
    def assert_closed(self, result):
        for flag in ('business_day_shifts_applied', 'snapshot_date_is_publication_timestamp',
                     'enum_meanings_verified', 'notice_window_verified', 'payment_date_verified',
                     'current_tradability_verified', 'holder_put_eligibility_verified',
                     'complete_population_verified', 'historical_pit_verified',
                     'source_gate_passed', 'profit_edge_proven', 'valid_signal'):
            self.assertFalse(result[flag], flag)

    def test_original_records_all42_fields_and_hyphenated_series_preserved(self):
        original = row(PrincipalRepaymentDescription='原文&#63754;\n條款')
        body = response([original])
        result = parse_metadata(body)
        self.assertEqual(result['records'], [original])
        self.assertEqual(result['source_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(result['summary']['field_count'], 42)
        self.assertEqual(result['summary']['record_count'], 1)
        self.assertEqual(result['canonical_identity_rows'][0]['canonical_identity'],
                         ['2756', '112-1', '', '20240530'])
        self.assert_closed(result)

    def test_missing_extra_and_nonstring_fields_fail(self):
        for change in ('missing', 'extra', 'number', 'null'):
            item = row()
            if change == 'missing':
                item.pop('Trustee')
            elif change == 'extra':
                item['UnexpectedField'] = 'new schema'
            else:
                item['PutOptionPrice'] = 100 if change == 'number' else None
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, '42-string-field'):
                parse_metadata(response([item]))

    def test_duplicate_json_keys_constants_bad_utf8_and_wrong_top_level_fail(self):
        duplicate = response([row()]).replace(b'"Date": "20261020"',
                                              b'"Date": "20261020", "Date": "20261020"')
        for body in (duplicate, b'[NaN]', b'[Infinity]', b'\xff', b'{}', response([row()])[:-1]):
            with self.subTest(body=body[:60]), self.assertRaises(ValueError):
                parse_metadata(body)

    def test_duplicate_canonical_identity_fails_despite_different_bond_codes(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate canonical CB identity'):
            parse_metadata(response([row(), row(BondCode='27562')]))

    def test_empty_and_nonstandard_bond_codes_remain_in_inventory(self):
        records = [row(BondCode='', IssuerCode='75306405'),
                   row(BondCode='YB66AC', IssuerCode='6165'),
                   row(BondCode='無', IssuerCode='90121589'),
                   row(BondCode='140201', IssuerCode='1402')]
        result = parse_metadata(response(records))
        self.assertEqual(result['records'], records)
        self.assertEqual(result['summary']['record_count'], 4)
        self.assertEqual(result['summary']['empty_bond_code_count'], 1)
        self.assertEqual(result['summary']['nonstandard_bond_code_count'], 2)
        self.assertEqual(result['nonstandard_bond_code_rows'][0]['bond_code'], 'YB66AC')
        self.assert_closed(result)

    def test_zero_put_price_is_an_unresolved_term_not_zero_cash_or_discarded_row(self):
        records = [row(PutOptionPrice='0.0000'),
                   row(IssuerCode='8070', PutOptionDate='', PutOptionPrice='101.0025')]
        result = parse_metadata(response(records))
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(result['summary']['anomaly_counts']['put_date_with_zero_price_unresolved'], 1)
        self.assertEqual(result['summary']['anomaly_counts']['put_price_without_put_date_unresolved'], 1)
        self.assert_closed(result)

    def test_future_issue_listing_and_weekend_put_flagged_without_date_shifts(self):
        original = row(IssueDate='20261021', ListingDate='20261021', PutOptionDate='20270530')
        result = parse_metadata(response([original]))
        kinds = {item['kind'] for item in result['anomalies']}
        self.assertTrue({'issue_date_after_snapshot', 'listing_date_after_snapshot',
                         'nominal_put_date_on_weekend_no_shift'} <= kinds)
        self.assertEqual(result['records'][0]['PutOptionDate'], '20270530')
        self.assert_closed(result)

    def test_dates_must_be_canonical_real_days_but_optional_empty_dates_are_valid(self):
        for field, value in [('Date', ''), ('IssueDate', '1130530'), ('MaturityDate', '20290230'),
                             ('PutOptionDate', '2027-05-30'), ('ListingDate', '20261301'),
                             ('OutstandingChangeDate', '2026102')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                parse_metadata(response([row(**{field: value})]))
        result = parse_metadata(response([row(ListingDate='', PutOptionDate='',
                                              OutstandingChangeDate='', PutOptionPrice='0.0000')]))
        self.assertEqual(result['summary']['record_count'], 1)

    def test_numeric_fields_reject_invalid_nonfinite_and_nonobserved_strings(self):
        for field in ('IssueAmount', 'OutstandingAmount', 'CouponRate', 'PutOptionPrice',
                      'Conversion/ExchangePriceAtIssuance'):
            for value in ('NaN', 'Infinity', '1_000', '1,000', '', 'not a number'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    parse_metadata(response([row(**{field: value})]))

    def test_unknown_enum_codes_and_noncash_principal_text_are_not_interpreted(self):
        original = row(Currency='unknown-new-code', ListingStatus='999', Guaranteed='custom',
                       PrincipalRepayment='2', PrincipalRepaymentDescription='依辦法第九條轉換為本公司普通股')
        result = parse_metadata(response([original]))
        self.assertEqual(result['records'][0], original)
        self.assertEqual(result['summary']['literal_enum_code_counts']['Currency'], {'unknown-new-code': 1})
        self.assert_closed(result)

    def test_no_unstated_lifecycle_business_rule_is_used_to_drop_rows(self):
        # Source lifecycle semantics require separate investigation; schema
        # checks must not silently reinterpret or remove a canonical record.
        original = row(ListingDate='20030804', PutOptionDate='20241025')
        before = copy.deepcopy(original)
        result = parse_metadata(response([original]))
        self.assertEqual(result['records'], [before])
        self.assertEqual(original, before)

    def test_empty_array_does_not_certify_an_empty_universe(self):
        result = parse_metadata(b'[]')
        self.assertEqual(result['records'], [])
        self.assertEqual(result['summary']['record_count'], 0)
        self.assert_closed(result)


if __name__ == '__main__':
    unittest.main()
