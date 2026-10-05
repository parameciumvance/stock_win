import unittest
from .institutional import normalize_t86


def fixture(modern=True):
    foreign = '外陸資' if modern else '外資'
    suffix = '(不含外資自營商)' if modern else ''
    values = {'證券代號': '2330', '證券名稱': '台積電  ',
              foreign + '買進股數' + suffix: '1,010', foreign + '賣出股數' + suffix: '1,000',
              foreign + '買賣超股數' + suffix: '10',
              '投信買進股數': '100', '投信賣出股數': '200', '投信買賣超股數': '-100',
              '自營商買賣超股數': '32',
              '自營商買進股數(自行買賣)': '20', '自營商賣出股數(自行買賣)': '8',
              '自營商買賣超股數(自行買賣)': '12',
              '自營商買進股數(避險)': '60', '自營商賣出股數(避險)': '40',
              '自營商買賣超股數(避險)': '20', '三大法人買賣超股數': '-58'}
    if modern:
        values.update({'外資自營商買進股數': '12', '外資自營商賣出股數': '5', '外資自營商買賣超股數': '7'})
    return {'stat': 'OK', 'date': '20240105', 'fields': list(values), 'data': [list(values.values())]}


class InstitutionalTests(unittest.TestCase):
    def test_modern_foreign_dealer_not_counted_twice(self):
        row = normalize_t86(fixture(), '20240105')[0]
        self.assertEqual(row['total_net_shares'], -58)
        self.assertEqual(row['foreign_dealer_net_shares'], 7)
        self.assertEqual(row['foreign_schema'], 'excluding_foreign_dealer')

    def test_legacy_missing_dealer_is_not_zero(self):
        row = normalize_t86(fixture(False), '20240105')[0]
        self.assertIsNone(row['foreign_dealer_net_shares'])
        self.assertEqual(row['foreign_schema'], 'legacy_foreign')

    def test_report_date_mismatch_rejected(self):
        with self.assertRaises(ValueError):normalize_t86(fixture(), '20240108')

    def test_duplicate_symbol_rejected(self):
        j = fixture();j['data'].append(j['data'][0].copy())
        with self.assertRaises(ValueError):normalize_t86(j, '20240105')

    def test_missing_value_rejected_instead_of_zero_fill(self):
        j = fixture();j['data'][0][j['fields'].index('投信買賣超股數')] = '--'
        with self.assertRaises(ValueError):normalize_t86(j, '20240105')

    def test_inconsistent_total_rejected(self):
        j = fixture();j['data'][0][j['fields'].index('三大法人買賣超股數')] = '-51'
        with self.assertRaises(ValueError):normalize_t86(j, '20240105')


if __name__ == '__main__':unittest.main()
