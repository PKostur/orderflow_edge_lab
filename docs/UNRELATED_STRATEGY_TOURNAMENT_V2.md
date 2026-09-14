# Unrelated Strategy Tournament v2

This protocol expands strategy research beyond the seven price families already tested in `price-strategy-tournament-v1.1` and beyond the slower-horizon evidence-backed trend/basis work.

## Wave A: independent price families

The first wave freezes eight families before results are inspected:

1. SMA crossover
2. Keltner channel breakout
3. Williams %R reversal
4. MACD histogram impulse
5. Volume-shock continuation
6. Opening-range breakout
7. Chande Momentum Oscillator reversal
8. ATR-expansion breakout

They use the same ten PnL-independent MEXC futures markets and 5m/15m/1h timeframes as the earlier price tournament, but they are separate trials with separate accounting.

Signals execute at the next bar open. Development folds are 21-day calendar dependence clusters. Cost cases remain 12/16/20 bps round trip. Every loser is retained. Screening requires positive median net expectancy, PF above 1, at least 60% positive folds, at least 80 trades, broad symbol participation, and parameter-neighborhood review.

## Wave B: institutional-style lane

Institutional-style hypotheses are not approximated with candles when the required source fields are absent. They are tested only against legitimate MEXC order-flow captures, public derivatives context, or already-owned DeepCharts/dxFeed fields.

Frozen candidate families for data-eligibility review:

* microprice plus book-imbalance continuation
* displayed-depth pull plus absorption reversal
* CVD versus price divergence
* large-trade share plus flow acceleration
* funding plus OI crowding reversal
* spot-perpetual basis convergence
* BTC lead-lag residual momentum

For each family, state prediction precedes PnL testing. Examples include future continuation versus reversion, future volatility expansion, and liquidity deterioration. Only after a state relationship is observed may the frozen strategy translation be evaluated after realistic friction.

## Validity boundaries

`discovery-v1` and `regime-research-v1` remain unchanged. Cross-pair transfer is not untouched OOS. Simultaneously captured symbols are one dependence cluster. No strategy can be called profitable without later untouched evidence after exact candidate freeze. Live transmission remains disabled.

## Promotion sequence

Development screening -> adversarial validity review -> redundancy and parameter-neighborhood review -> exact candidate freeze -> later-data paper/shadow evidence -> reconciliation/reliability checks -> separate promotion decision.
