# Unrelated Strategy Tournament v2.1.1

## Evidence identity

- Protocol: `unrelated-strategy-tournament-v2.1.1-state-first`
- Exact research head: `39fa21d14a545ca7a39dc3ff97e1792502df95dc`
- Workflow run: `34895093843`
- Artifact ID: `10369093279`
- Artifact SHA256: `72bbf0b16171127274b7428f5f4ebc6c78035dadaff1d0b019b647330b45c987`
- Intervals: 5m, 15m, 1h
- Dependence unit: 21-day calendar fold
- Cost cases: 12, 16, 20 bps round trip

## State layer

294 frozen state variants were evaluated before strategy economics. 84 passed the frozen state screen.

The passes were concentrated entirely in the two oscillator mean-reversion families:

- CMO reversal: all 12 variants passed on each of 5m, 15m, and 1h.
- Williams %R reversal: all 16 variants passed on each of 5m, 15m, and 1h.
- SMA crossover, Keltner breakout, MACD impulse, volume-shock continuation, opening-range breakout, and ATR-expansion breakout produced zero state passes.

This state evidence is not a trading-edge claim. The score families are also materially redundant. Seven high-redundancy relationships exceeded the frozen absolute median Spearman threshold of 0.80. In particular, CMO and Williams %R are highly associated at 1h, and both are strongly inversely associated with Keltner state scores across multiple intervals.

## Economic translation

Only state-pass variants entered the costed strategy layer, producing 252 economic rows. There were zero primary economic passes.

At the primary 16 bps cost case, the numerically strongest row was 1h CMO reversal with period 28, threshold 60, and max hold 12:

- trades: 82
- median fold net expectancy: +42.52 bps/trade
- median fold PF: 2.039
- positive-fold fraction: 0.80
- positive-symbol fraction: 0.444
- reversed-direction mean net expectancy: -20.51 bps/trade
- randomized-direction p-value: approximately 0.0195

This row is rejected. It fails the frozen symbol-breadth requirement and has no parameter-neighborhood support. The next strongest CMO cells show the same concentration problem, with positive-symbol fractions at or below 0.556. Selecting the isolated best cell would therefore violate the predeclared anti-overfitting rules.

No family cleared all frozen economic requirements at the primary cost case. Consequently:

- no candidate freeze is triggered;
- no MAE/MFE or stop/RR optimization is triggered;
- no holdout is opened;
- no paper or shadow promotion is permitted;
- no profitable-edge or untouched-OOS claim is made.

## Research conclusion

Wave A is rejected as an executable strategy-discovery lane under the frozen protocol. The useful surviving observation is limited to market-state information from oscillator-style mean reversion, not monetizable cross-symbol strategy economics.

The next independent step is Wave B data eligibility. Its purpose is only to establish which predeclared institutional-style families can be supported by legitimate public MEXC or already-authorized existing data. Missing order-book history, open-interest history, funding, liquidation, or basis fields must not be synthesized or inferred.
