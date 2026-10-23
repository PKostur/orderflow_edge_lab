import copy
import math
import statistics
import unittest
from datetime import datetime, timedelta, timezone

from orderflow_edge_lab.cash_trend_portfolio import SYMBOLS, rebalance, simulate, weights


class CashTrendTests(unittest.TestCase):
    def test_cash_limited_buys_and_cost_conservation(self):
        held = dict.fromkeys(SYMBOLS, 0.0)
        prices = dict(zip(SYMBOLS, (10.0, 20.0, 30.0, 40.0)))
        desired = dict.fromkeys(SYMBOLS, 100.0)
        cash, final, fills = rebalance(100, held, desired, prices, .002)
        self.assertGreaterEqual(cash, 0)
        self.assertLess(cash, 1e-9)
        self.assertAlmostEqual(cash + math.fsum(final[s] * prices[s] for s in SYMBOLS) + math.fsum(f['cost'] for f in fills), 100)
        self.assertLess(max(final.values()) - min(final.values()), 1e-12)

    def test_sell_before_buy_gap_and_immutable_inputs(self):
        held = dict(zip(SYMBOLS, (10., 0., 0., 0.)))
        prices = dict.fromkeys(SYMBOLS, 10.)
        desired = dict(zip(SYMBOLS, (0., 20., 0., 0.)))
        cash, final, fills = rebalance(0, held, desired, prices, .01)
        self.assertEqual([f['side'] for f in fills], ['sell', 'buy'])
        self.assertAlmostEqual(final['ETHUSDT'], 99 / 10.1)
        self.assertAlmostEqual(cash, 0)
        self.assertEqual(held['BTCUSDT'], 10)
        self.assertEqual(desired['ETHUSDT'], 20)

    def test_no_negative_wallet_or_bad_prices(self):
        zero = dict.fromkeys(SYMBOLS, 0.)
        for bad in (-1., float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                rebalance(1, zero, zero, dict.fromkeys(SYMBOLS, bad), .002)
        with self.assertRaises(ValueError):
            rebalance(-1, zero, zero, dict.fromkeys(SYMBOLS, 1.), .002)

    def test_risk_math_uses_180_returns_sample_vol(self):
        close = [100 * math.exp(.001 * i + .02 * math.sin(i)) for i in range(1100)]
        data = dict.fromkeys(SYMBOLS, close)
        logs = [math.log(close[i] / close[i - 1]) for i in range(920, 1100)]
        expected = .25 * min(1, .1 / (statistics.stdev(logs) * math.sqrt(1095)))
        self.assertAlmostEqual(weights(data, 1099)['BTCUSDT'], expected)
        self.assertTrue(all(x == 0 for x in weights(data, 1094).values()))

    def test_downtrend_cash_and_zero_vol_control(self):
        falling = dict.fromkeys(SYMBOLS, [2000 - i for i in range(1100)])
        flat = dict.fromkeys(SYMBOLS, [100.] * 1100)
        self.assertEqual(set(weights(falling, 1099).values()), {0.})
        self.assertEqual(set(weights(flat, 1099).values()), {0.})
        self.assertEqual(set(weights(flat, 1099, 'always_long').values()), {.25})

    @staticmethod
    def fixture():
        times = [datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(hours=8 * i) for i in range(1300)]
        panel = {s: {'open': [], 'high': [], 'low': [], 'close': []} for s in SYMBOLS}
        for s in SYMBOLS:
            for i in range(1300):
                p = 100 + .05 * i
                for k, value in (('open', p), ('high', p + 2), ('low', p - 2), ('close', p + 1)):
                    panel[s][k].append(value)
        return times, panel

    def test_clock_prefix_invariance_and_accounting(self):
        times, panel = self.fixture()
        result = simulate(times, panel, .002)
        for fill in result['fills']:
            t = datetime.fromisoformat(fill['fill_open_utc'])
            self.assertEqual((t.weekday(), t.hour), (0, 8))
            self.assertEqual(t - datetime.fromisoformat(fill['signal_close_utc']), timedelta(hours=8))
        cut = 1200
        shorter = simulate(times[:cut], {s: {k: v[:cut] for k, v in p.items()} for s, p in panel.items()}, .002)
        self.assertEqual(result['equity'][:len(shorter['equity'])], shorter['equity'])
        mutated = copy.deepcopy(panel)
        for s in SYMBOLS:
            for k in mutated[s]:
                mutated[s][k][cut:] = [v * 50 for v in mutated[s][k][cut:]]
        later = simulate(times, mutated, .002)
        self.assertEqual(shorter['equity'], later['equity'][:len(shorter['equity'])])
        self.assertTrue(all(m['cash_usdt'] >= 0 for m in result['equity']))
        # Independent reconstruct final wallet from the complete signed fill ledger.
        cash, qty = 10000., dict.fromkeys(SYMBOLS, 0.)
        for f in result['fills']:
            signed = f['quantity'] * (1 if f['side'] == 'buy' else -1)
            qty[f['symbol']] += signed
            cash -= signed * f['price'] + f['cost']
        value = cash + sum(qty[s] * panel[s]['close'][-1] * .998 for s in SYMBOLS)
        self.assertAlmostEqual(value, result['final_net_liquidation_usdt'], places=8)

    def test_btc_single_purchase_and_terminal_cost(self):
        times, panel = self.fixture()
        result = simulate(times, panel, .002, 'btc')
        self.assertEqual(result['fill_count'], 1)
        f = result['fills'][0]
        expected = 10000 / (f['price'] * 1.002) * panel['BTCUSDT']['close'][-1] * .998
        self.assertAlmostEqual(result['final_net_liquidation_usdt'], expected, places=8)


if __name__ == '__main__':
    unittest.main()
