import json
from decimal import Decimal
import unittest

from ipo_screen import FIELDS,expected_amount,parse_year,number,terms,overlap_through_listing


def case():
    f=dict(zip(FIELDS,['1','113/01/10','測試','1234','初上市','113/01/04','113/01/08','1,000,000','1,000,000','100','100','113/01/17','券商','1,000','100,000,000','100,000','1','']))
    return dict(application_start='2024-01-04',application_end='2024-01-08',draw_date='2024-01-10',listing_date='2024-01-17',reported_fields=f)


class IPOScreenTests(unittest.TestCase):
    def setUp(self):
        self.policy=dict(application_fee_scenario='20',winner_fee_scenario='50',single_application_budget_twd='300000')

    def test_every_losing_application_still_pays_fee(self):
        self.assertEqual(expected_amount('100','1000','0.001','150','0','20','50'),Decimal('29.950'))
        self.assertEqual(expected_amount('100','1000','0','150','0','20','50'),Decimal('-20'))

    def test_winner_fee_is_not_charged_to_losers(self):
        self.assertEqual(expected_amount('100','1000','1','150','0','20','50'),Decimal('49930'))

    def test_flat_quote_has_negative_expectation(self):
        self.assertLess(expected_amount(100,1000,'0.01',100,0,20,50),0)

    def test_sale_drag_is_applied_to_proceeds_not_gain(self):
        self.assertEqual(expected_amount(100,1000,'0.01',150,'0.005',20,50),Decimal('472.00000'))

    def test_invalid_probability_and_nonfinite_prices_fail(self):
        for p,opening in [('1.01','150'),('-0.01','150'),('0.01','NaN')]:
            with self.assertRaises(ValueError):expected_amount(100,1000,p,opening,0,20,50)

    def test_wrong_year_count_and_schema_fail_closed(self):
        row=list(case()['reported_fields'].values())
        doc=dict(stat='OK',date='2024',fields=FIELDS,data=[row],total=1)
        self.assertEqual(len(parse_year(json.dumps(doc),2024)),1)
        for key,value in [('date','2026'),('total',2),('fields',FIELDS[:-1])]:
            bad={**doc,key:value}
            with self.assertRaises(ValueError):parse_year(json.dumps(bad),2024)

    def test_unknown_number_is_not_zero(self):
        self.assertIsNone(number('---'))
        self.assertEqual(number('0'),0)
        with self.assertRaises(ValueError):number('Infinity')
        with self.assertRaises(ValueError):number('1,00')

    def test_exact_probability_not_rounded_display(self):
        c=case();c['reported_fields']['總合格件']='186,000';c['reported_fields']['中籤率(%)']='0.53'
        t=terms(c,self.policy)
        self.assertFalse(t['issues'])
        self.assertEqual(Decimal(t['allocation_probability']),Decimal(1000)/Decimal(186000))

    def test_cancellation_or_changed_price_never_dropped_as_successful(self):
        for key,value,issue in [('取消公開抽籤','取消申購','cancelled_or_special_status'),('實際承銷價(元)','101','unknown_or_changed_final_price')]:
            c=case();c['reported_fields'][key]=value
            self.assertIn(issue,terms(c,self.policy)['issues'])

    def test_zero_qualified_applications_unknown_not_zero_probability(self):
        c=case();c['reported_fields']['總合格件']='0'
        self.assertIsNone(terms(c,self.policy)['allocation_probability'])

    def test_individual_budget_uses_offer_terms_only(self):
        c=case();c['reported_fields']['承銷價(元)']='301';c['reported_fields']['實際承銷價(元)']='301'
        self.assertFalse(terms(c,self.policy)['individually_affordable'])

    def test_coincident_deadlines_not_double_counted(self):
        a=dict(application_end='2024-01-08',listing_date='2024-01-17',terms=dict(reservation_scenario_twd='100'))
        b=dict(application_end='2024-01-08',listing_date='2024-01-18',terms=dict(reservation_scenario_twd='200'))
        self.assertEqual(overlap_through_listing([a,b]),300)


if __name__=='__main__':unittest.main()
