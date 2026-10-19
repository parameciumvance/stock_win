import unittest
from fractions import Fraction as F
import contextlib
import json
from pathlib import Path
import tempfile

from ipo_account import cash_events, integer_weights, next_market, path_cash, policy, quantile
from research_runtime import sha256


class AccountTests(unittest.TestCase):
    def test_exact_joint_mass_includes_impossible_states(self):
        weights, denominator = integer_weights([F(1,3), F(0), F(1)])
        self.assertEqual(weights, [0,0,0,0,2,1,0,0])
        self.assertEqual(denominator, 3)

    def test_dependent_lotteries_not_inferred_from_marginals(self):
        # Equal marginals can mean joint no-win0,1/4or1/2. The tool computes only independence.
        weights, denominator = integer_weights([F(1,2), F(1,2)])
        self.assertEqual(F(weights[0], denominator), F(1,4))
        self.assertNotEqual(F(weights[0], denominator), F(1,2))

    def test_market_lags_do_not_use_calendar_days_or_price_availability(self):
        days = ['2024-02-05','2024-02-06','2024-02-15','2024-02-16']
        self.assertEqual(next_market(days, '2024-02-05', 2), '2024-02-15')
        self.assertEqual(next_market(days, '2024-02-06', 1), '2024-02-15')

    def test_calendar_missing_duplicate_or_exhausted_fails(self):
        for days, day in [(['2024-01-02'], '2024-01-03'), (['2024-01-02']*2, '2024-01-02'), (['2024-01-02'], '2024-01-02')]:
            with self.assertRaises(ValueError): next_market(days, day, 1)

    def test_refund_cannot_fund_earlier_same_day_reservation(self):
        events = [('2024-01-02',0,0,'reserve',F(-170)),
                  ('2024-01-05',0,1,'reserve',F(-170)),
                  ('2024-01-05',1,0,'refund_if_loss',F(150)),
                  ('2024-01-08',1,1,'refund_if_loss',F(150))]
        cash, required, _ = path_cash(events, 0, 1)
        self.assertEqual((cash, required), (-40,340))
        self.assertGreater(required, 300)  # Cannot silently skip the second application.

    def test_same_deadline_cases_sum_not_max(self):
        events = [('2024-01-02',0,i,'reserve',F(-170)) for i in [0,1]]
        self.assertEqual(path_cash(events,0,1)[1],340)

    def test_loser_refund_winner_sale_and_negative_winner(self):
        events = [('2024-01-02',0,0,'reserve',F(-170)),
                  ('2024-01-05',1,0,'refund_if_loss',F(150)),
                  ('2024-01-08',1,0,'sale_if_win',F(90))]
        self.assertEqual(path_cash(events,0,1)[:2],(-20,170))
        self.assertEqual(path_cash(events,1,1)[:2],(-80,170))

    def test_discrete_quantiles_no_interpolation_or_zero_mass_tail(self):
        ordered=[(-320,84),(1000,10),(9000,6)]
        self.assertEqual(quantile(ordered,100,F(1,2)),-320)
        self.assertEqual(quantile(ordered,100,F(95,100)),9000)
        self.assertEqual(quantile([(-999,0),(-320,84),(1000,16)],100,F(0)),-320)

    def test_invalid_probability_rejected(self):
        for probabilities in [[], [F(-1,4)], [F(5,4)]]:
            with self.assertRaises(ValueError): integer_weights(probabilities)

    def test_recovery_rejects_substitute_input_and_changed_protocol(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.chdir(temp):
            Path('configs').mkdir();Path('input.txt').write_text('frozen')
            for name in ['ipo_account_20261020','ipo_screen_20261019','benchmark_cash_20261019']:
                folder=Path('deliverables',name);folder.mkdir(parents=True)
                (folder/'checkpoint.json').write_text(json.dumps(dict(files={})))
            protocol=Path('configs/ipo_account_protocol_20261020.json')
            original=json.dumps(dict(inputs={'input.txt':sha256(Path('input.txt'))}))
            protocol.write_text(original)
            Path('deliverables/ipo_account_20261020/protocol_freeze.json').write_text(json.dumps(dict(protocol_sha256=sha256(protocol))))
            policy()
            Path('input.txt').write_text('new dataset')
            with self.assertRaisesRegex(ValueError,'Pinned input drift'): policy()
            Path('input.txt').write_text('frozen');protocol.write_text(original+' ')
            with self.assertRaisesRegex(ValueError,'protocol drift'): policy()

    def test_cash_events_do_not_credit_sale_on_listing_day(self):
        rows=[dict(application_end='2024-01-02', draw_date='2024-01-04',listing_date='2024-01-08',
                   terms=dict(offer_price='100',lot_size='1'),raw_listing_quote=dict(open='120'))]
        days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08','2024-01-09','2024-01-10']
        events=cash_events(rows,days,F(0),F(20),F(50))
        self.assertEqual(events[-1][:4],('2024-01-10',1,0,'sale_if_win'))
        self.assertEqual(path_cash(events,1,1)[0],-50)


if __name__ == '__main__': unittest.main()
