import copy
import unittest

import numpy as np
import pandas as pd

from risk_control import audit_summary, features, independent_audit, metrics, rebalance, simulate, validate_market


def fixture():
    dates = pd.bdate_range('2023-01-02', '2024-04-30')
    close = 100 * np.cumprod(1 + .012 * np.sin(np.arange(len(dates)) / 3))
    f = pd.DataFrame(dict(date=dates, open=close * .999, close=close,
                          adj_open=close * .999, adj_close=close, causal_factor=1.))
    c = dict(calibration_start='2023-01-02', calibration_end='2023-12-29',
             evaluation_start='2024-01-01', evaluation_end='2024-04-30',
             volatility_lookback=20, annualization=252, target_annual_volatility=.1)
    return f, c


class BudgetTests(unittest.TestCase):
    def test_full_buy_cost_is_financed(self):
        a, cash, traded, cost = rebalance(0, 1, 1, .01)
        self.assertAlmostEqual(a, 1/1.01)
        self.assertAlmostEqual(cash, 0)
        self.assertAlmostEqual(a+cash, 1-cost)

    def test_full_sell(self):
        self.assertEqual(rebalance(1, 0, 0, .01), (0, .99, 1, .01))

    def test_target_after_cost(self):
        for a, cash in [(0, 1), (.9, .1), (.2, .8)]:
            result = rebalance(a, cash, .4, .002)
            self.assertAlmostEqual(result[0]/sum(result[:2]), .4)
            self.assertAlmostEqual(sum(result[:2]), a+cash-result[3])

    def test_invalid_states(self):
        for args in [(-1, 1, .5, 0), (1, 0, 1.1, 0), (1, 0, .5, -1), (1, 0, .5, 1), (1, 0, np.nan, 0)]:
            with self.assertRaises(ValueError):
                rebalance(*args)

    def test_no_trade_no_cost(self):
        self.assertEqual(rebalance(.5, .5, .5, .2), (.5, .5, 0, 0))


class CausalityTests(unittest.TestCase):
    def test_current_close_does_not_change_current_target(self):
        f, c = fixture()
        a, _ = simulate(f, c, .001)
        changed = f.copy()
        index = changed.index[changed.date.eq('2024-02-01')][0]
        changed.loc[index:, ['close', 'adj_close']] *= 1.5
        b, _ = simulate(changed, c, .001)
        cut = lambda x: x[x.date.le('2024-02-01')][['date', 'method', 'target', 'reason']].reset_index(drop=True)
        pd.testing.assert_frame_equal(cut(a), cut(b))

    def test_future_prefix_invariance(self):
        f, c = fixture()
        full, _ = simulate(f, c, .001)
        c2 = {**c, 'evaluation_end': '2024-03-15'}
        prefix, _ = simulate(f[f.date.le('2024-03-15')], c2, .001)
        pd.testing.assert_frame_equal(full[full.date.le('2024-03-15')].reset_index(drop=True), prefix)

    def test_static_calibration_ignores_evaluation(self):
        f, c = fixture()
        _, a = simulate(f, c, .001)
        f.loc[f.date.ge('2024-01-01'), ['open', 'close', 'adj_open', 'adj_close']] *= 3
        _, b = simulate(f, c, .001)
        self.assertEqual(a, b)

    def test_monthly_only(self):
        f, c = fixture()
        result, _ = simulate(f, c, .001)
        decisions = result[result.reason.eq('rebalance')]
        self.assertTrue(decisions.date.str.endswith('01').all())
        self.assertEqual(len(decisions[decisions.method.eq('buy_hold')]), 1)

    def test_missing_window_skips_without_queue(self):
        f, c = fixture()
        f.loc[f.date.eq('2024-01-25'), ['open', 'close', 'adj_open', 'adj_close', 'causal_factor']] = np.nan
        result, _ = simulate(f, c, .001)
        dynamic = result[result.method.eq('dynamic')].set_index('date')
        self.assertEqual(dynamic.loc['2024-02-01', 'reason'], 'missing_vol_window')
        self.assertTrue(dynamic.loc['2024-02-02':'2024-02-29', 'reason'].eq('hold').all())
        self.assertEqual(dynamic.loc['2024-03-01', 'reason'], 'rebalance')

    def test_missing_open_blocks_trade_and_carries_close(self):
        f, c = fixture()
        columns = ['open', 'close', 'adj_open', 'adj_close', 'causal_factor']
        f.loc[f.date.eq('2024-02-01'), columns] = np.nan
        result, _ = simulate(f, c, .001)
        rows = result[result.date.eq('2024-02-01')]
        self.assertTrue(rows.traded.eq(0).all())
        self.assertTrue(rows.carried_valuation.all())
        self.assertTrue(rows.daily_return.abs().lt(1e-14).all())

    def test_no_synthetic_zero_in_volatility(self):
        f, c = fixture()
        f.loc[270, ['open', 'close', 'adj_open', 'adj_close', 'causal_factor']] = np.nan
        feat, returns = features(f, c)
        self.assertTrue(returns.iloc[270:272].isna().all())
        self.assertTrue(feat.prior_vol.iloc[271:292].isna().all())

    def test_split_changes_raw_prices_not_proxy_nav(self):
        f, c = fixture()
        a, _ = simulate(f, c, .001)
        f.loc[f.date.ge('2024-02-01'), ['open', 'close']] /= 4
        f.loc[f.date.ge('2024-02-01'), 'causal_factor'] *= 4
        b, _ = simulate(f, c, .001)
        pd.testing.assert_frame_equal(a, b)

    def test_zero_volatility_is_capped(self):
        f, c = fixture()
        f[['open', 'close', 'adj_open', 'adj_close']] = 100.
        result, cal = simulate(f, c, .001)
        self.assertEqual(cal['static_weight'], 1)
        self.assertTrue(result.target.dropna().between(0, 1).all())
        self.assertTrue(result[result.method.eq('dynamic')].target.dropna().eq(1).all())

    def test_initial_quote_is_required(self):
        f, c = fixture()
        f.loc[f.date.eq(c['evaluation_start']), ['open', 'close', 'adj_open', 'adj_close', 'causal_factor']] = np.nan
        with self.assertRaises(ValueError):
            simulate(f, c, .001)


class AuditTests(unittest.TestCase):
    def test_independent_decimal_replay(self):
        f, c = fixture()
        result, _ = simulate(f, c, .002)
        audit = independent_audit(f, result, c)
        self.assertEqual(audit['rows'], len(result))
        self.assertLess(audit['max_absolute_error'], 1e-10)

    def test_summary_and_gate_tampering_rejected(self):
        f, c = fixture()
        c['one_way_turnover_costs'] = [.001]
        result, _ = simulate(f, c, .001)
        groups = [dict(method=method, cost_rate=.001, **metrics(part)) for method, part in result.groupby('method')]
        years = [dict(method=method, cost_rate=.001, year=2024, return_=float(part.nav.iloc[-1]-1), days=len(part)) for method, part in result.groupby('method')]
        d, s = [next(r for r in groups if r['method'] == method) for method in ['dynamic', 'calibration_static']]
        gate = dict(cost_rate=.001, higher_cagr=d['cagr']>s['cagr'], no_larger_drawdown=d['max_drawdown']>=s['max_drawdown'], higher_mean_over_vol=d['mean_over_vol']>s['mean_over_vol'], at_least_two_year_wins=False, year_wins=int(d['total_return']>s['total_return']))
        summary = dict(summary=groups, calendar_subperiods=years, gates=[gate], go_gate_passed=False, decision='close_fixed_rule_no_tuning')
        self.assertEqual(audit_summary(result, summary, c), 4)
        for key in ['cagr', 'annualized_vol', 'cost_initial_nav_units']:
            bad = copy.deepcopy(summary)
            bad['summary'][0][key] += .01
            with self.assertRaisesRegex(ValueError, 'summary differs'):
                audit_summary(result, bad, c)
        bad = copy.deepcopy(summary)
        bad['gates'][0]['higher_cagr'] = not gate['higher_cagr']
        with self.assertRaisesRegex(ValueError, 'decision gate'):
            audit_summary(result, bad, c)

    def test_tampered_ledger_rejected(self):
        f, c = fixture()
        result, _ = simulate(f, c, .001)
        result.loc[2, 'nav'] += .001
        with self.assertRaises(ValueError):
            independent_audit(f, result, c)

    def test_tampered_decision_rejected(self):
        f, c = fixture()
        result, _ = simulate(f, c, .001)
        result.loc[0, 'target'] = .99
        with self.assertRaises(ValueError):
            independent_audit(f, result, c)

    def test_bad_prices_calendar_and_factor_rejected(self):
        f, c = fixture()
        for frame in [pd.concat([f, f.iloc[:1]]), f.iloc[::-1], f.assign(causal_factor=2), f.assign(close=-1), f.assign(adj_open=np.nan)]:
            with self.assertRaises(ValueError):
                validate_market(frame)

    def test_cash_and_initial_cost_counted(self):
        f, c = fixture()
        result, _ = simulate(f, c, .002)
        cash = result[result.method.eq('cash')]
        self.assertTrue(cash.nav.eq(1).all())
        m = metrics(cash)
        self.assertEqual(m['cagr'], 0)
        self.assertIsNone(m['mean_over_vol'])
        initial = result[result.method.eq('buy_hold')].iloc[0]
        self.assertGreater(initial.charge, 0)
        self.assertAlmostEqual(initial.daily_return, initial.nav-1)

    def test_cost_increase_reduces_static_nav(self):
        f, c = fixture()
        a, _ = simulate(f, c, .001)
        b, _ = simulate(f, c, .002)
        for method in ['buy_hold', 'calibration_static']:
            self.assertLess(b[b.method.eq(method)].nav.iloc[-1], a[a.method.eq(method)].nav.iloc[-1])

    def test_drawdown_includes_initial_nav(self):
        f = pd.DataFrame(dict(nav=[.9, .95], daily_return=[-.1, .95/.9-1], traded=[0, 0], charge=[0, 0], exposure=[1, 1], carried_valuation=[False, False]))
        self.assertAlmostEqual(metrics(f)['max_drawdown'], -.1)


if __name__ == '__main__':
    unittest.main()
