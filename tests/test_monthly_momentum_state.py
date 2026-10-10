import unittest
from dataclasses import replace
from datetime import timedelta

from orderflow_edge_lab.monthly_momentum_state import month_shift, observations, portfolio, state_effect
from orderflow_edge_lab.public_strategy_shadow import Bar, utc


class MonthlyMomentumStateTests(unittest.TestCase):
    def frames(self):
        start, end = utc('2019-01-01T00:00:00Z'), utc('2021-01-01T00:00:00Z')
        bars = []
        t = start
        while t <= end:
            p = 100 + len(bars) * .01
            bars.append(Bar(t, p, p + 1, p - 1, p + .005, 1))
            t += timedelta(hours=8)
        return {s: bars[:] for s in ('BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'LINK_USDT')}

    def test_calendar_endpoints_and_exit_candle_exclusion(self):
        frames = self.frames()
        rows = observations(frames)
        self.assertEqual(rows[0]['entry_time'], '2020-02-01T00:00:00Z')
        self.assertEqual(rows[0]['exit_time'], '2020-03-01T00:00:00Z')
        self.assertEqual(rows[-1]['exit_time'], '2021-01-01T00:00:00Z')
        self.assertEqual(len(rows), 33)
        row = rows[0]
        bars = frames[row['symbol']]
        self.assertAlmostEqual(row['gross_bps'], (bars[row['exit_index']].open / bars[row['entry_index']].open - 1) * 10000)
        index = row['exit_index']
        frames[row['symbol']][index] = replace(bars[index], high=1e9)
        self.assertEqual(observations(frames)[0]['mfe_bps'], row['mfe_bps'])

    def test_future_prices_cannot_change_current_signal(self):
        frames = self.frames()
        before = observations(frames)[0]
        for s in frames:
            for i in range(before['entry_index'], len(frames[s])):
                b = frames[s][i]
                frames[s][i] = replace(b, open=b.open * .1, close=b.close * .1, high=b.high * .1, low=b.low * .1)
        after = observations(frames)[0]
        self.assertEqual(after['positive_state'], before['positive_state'])
        self.assertEqual(after['prior12m_return'], before['prior12m_return'])
        self.assertEqual(month_shift(utc('2020-03-01T00:00:00Z'), -1), utc('2020-02-01T00:00:00Z'))

    def test_missing_grid_fails_closed(self):
        frames = self.frames()
        for s in frames:
            frames[s].pop(10)
        with self.assertRaises(ValueError):
            observations(frames)

    def test_sleeve_costs_and_cash_are_accounted(self):
        start = utc('2020-01-01T00:00:00Z')
        bars = [Bar(start, 100, 100, 100, 100, 1), Bar(start + timedelta(hours=8), 110, 110, 110, 110, 1)]
        frames = {s: bars for s in ('ETH_USDT', 'SOL_USDT', 'LINK_USDT')}
        rows = [{'symbol': 'ETH_USDT', 'entry_index': 0, 'exit_index': 1}]
        expected = (1.1 * .998 ** 2 + 2) / 3
        self.assertAlmostEqual(portfolio(rows, frames, 40)['return_pct'], (expected - 1) * 100)
        self.assertEqual(portfolio([], frames, 40)['return_pct'], 0)
        self.assertEqual(state_effect([{'positive_state': True, 'excess_bps': 3}, {'positive_state': False, 'excess_bps': 5}]), -2)
