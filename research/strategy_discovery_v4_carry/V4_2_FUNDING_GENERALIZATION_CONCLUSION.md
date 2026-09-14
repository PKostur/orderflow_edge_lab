# Strategy Discovery v4.2 — Funding Generalization Conclusion

## Evidence class

Retrospective cross-symbol generalization only. This is **not** untouched OOS and does not support live trading.

Canonical workflow run: `34887417821`

Canonical source head: `51a95d9edceda58170e61cf87326d5dadbc73640`

Artifact: `strategy-discovery-v4-2-funding-generalization` (`10365611913`)

Artifact digest: `sha256:8e68694d2886c6b425ff2b817ccf0ec129416bf44267e0f9e56069809f8febda`

## PnL-independent expansion panel

The primary panel excluded all original v4/v4.1 alpha symbols and admitted 17 new symbols using only current MEXC spot/perpetual intersection, historical coverage, funding-history availability and spot-liquidity rules:

`TRX, ZEC, LTC, HYPE, TAO, NEAR, BCH, ASTER, DOT, XMR, XLM, ETHFI, UNI, SHIB, DASH, ARB, INJ`

BTC remained hedge/context only and was not eligible for the alpha ranking sleeves.

## Frozen cells

No new parameter search was allowed. v4.2 evaluated only the two previously observed v4.1 mechanisms:

- top/bottom `k=3`, funding lookback `3` settlements, hold `72h`
- top/bottom `k=3`, funding lookback `5` settlements, hold `72h`

The same 192h causal BTC-beta hedge and 12/16/20 bps cost schedule were retained.

## State evidence

Funding dispersion generalized strongly as a PnL-independent state feature.

### 3-settlement lookback

- 6,006 state observations
- 14 scorable 21-day folds
- median fold Spearman: **+0.47338**
- positive state folds: **12/14 = 85.71%**
- state gate: **PASS**

### 5-settlement lookback

- 6,006 state observations
- 14 scorable 21-day folds
- median fold Spearman: **+0.43087**
- positive state folds: **12/14 = 85.71%**
- state gate: **PASS**

The combined old+new diagnostic panel also retained positive state structure, but that combined panel is diagnostic only and cannot rescue primary-panel economics.

## Executable economics

Both frozen carry-direction translations failed decisively on the new-symbol-only panel.

### 3-settlement lookback

- trades: 84
- primary 16 bps median fold net: **-16.6647 bps**
- primary median fold PF: **0.8416**
- positive economic folds: **4/14 = 28.57%**
- mean primary net: **-61.9985 bps/trade**
- 20 bps median fold net: **-20.6647 bps**
- reversed-direction mean at primary costs: **+29.9985 bps/trade**
- removing strongest fold leaves only **23.08%** positive folds
- economic/generalization gate: **FAIL**

### 5-settlement lookback

- trades: 84
- primary 16 bps median fold net: **-9.4929 bps**
- primary median fold PF: **0.9343**
- positive economic folds: **6/14 = 42.86%**
- mean primary net: **-38.8349 bps/trade**
- 20 bps median fold net: **-13.4929 bps**
- reversed-direction mean at primary costs: **+6.8349 bps/trade**
- removing strongest fold leaves **38.46%** positive folds
- economic/generalization gate: **FAIL**

## Conclusion

1. Funding dispersion is a robust cross-sectional market-state feature across a materially different symbol universe.
2. The original carry translation — long low-funding names and short high-funding names — does **not** generalize economically.
3. Costs alone are not the explanation; gross/primary results are weak enough that the portfolio direction itself is wrong for this price process.
4. The reversed-direction control is positive on mean return for both frozen cells, which creates a **post-observation crowding/continuation hypothesis**. It cannot be promoted by flipping direction on this already-observed sample.
5. Any reversed/crowding strategy must be frozen as a new protocol and tested prospectively or on genuinely unobserved data.
6. Parent holdout remains sealed. Leverage remains untested. No profitable-edge, verified-OOS or live claim is allowed.

## Research status

- funding state signal: **retained**
- original carry-direction strategy: **rejected**
- reversed/crowding mechanism: **new hypothesis only**
- untouched OOS: **false**
- profitable edge established: **false**
- live enabled: **false**
