# Zero-fee scalping v1: development research

The separate `zero-fee-scalping-v1` lane explores order-flow continuation with
maximum holds of 5, 15, 30, 60 and 120 seconds. It is development-only, with no
live execution or strategy promotion. Existing frozen research is unchanged.

The [pilot result](../research/zero_fee_scalping/RESULT.md) records a five-minute
public ZEC_USDT capture. All execution lanes ended with unresolved positions;
completed original-direction trades lost money even under hypothetical zero
fees. These observations establish neither strategy profitability nor a final
rejection of the wider hypothesis.

## Fee eligibility before strategy selection

A public zero-rate advertisement is a candidate inventory, not proof of an
account's effective commission. MEXC's zero-fee promotion excludes API users;
its published API taker fee table provides the pilot's 8-bps-per-leg baseline.
See the result's official source links. Manual MEXC and API-eligible promotions
on another venue are separate research paths; no account has been checked.

The fee record binds venue, linear USDT perpetual market, exact symbol,
execution channel, official terms URL/snapshot hash, observation/validity times,
account/region/channel eligibility, maker and taker rates, normal taker rate,
and remaining volume quota or explicitly unlimited quota. Missing, mismatched,
future, expired or inapplicable evidence falls back to the declared normal rate.
Quota counts both legs. A quota-crossing leg conservatively pays normal fees
and exhausts the remaining allowance. Entry and exit rates are checked separately.

The runner reports three scenarios on identical completed fills: hypothetical
zero fees, normal fees, and fees applicable under the supplied declaration.
Declarations are not independently audited. Maker-only promotions are not
simulated as free taker execution; maker fills would require a separate queue
and adverse-selection model.

## Data and execution model

- Trade and depth feature JSONL schema v2, locally observed receive-time ordering.
- Fresh applied depth establishes BBO; cached trade BBO never refreshes a quote.
  Initial/recovery snapshots invalidate entry until a fresh depth update arrives.
- Exchange timestamps additionally bound transport staleness/clock skew. Old
  trade packets do not generate fresh signals. Identical timestamps preserve
  source-line order; timers use quotes observed strictly before arrival.
- File-backed replay requires a terminal session summary with zero reconnects.
  Feature captures lack disconnect timestamps, so reconnects are unsupported.
- Delayed taker entry/exit, bid/ask spread once, adverse slippage per leg,
  contract-size conversion, minimum volume and step rounding.
- Maximum requested notional is 100 USDT; fills use at most 5% of displayed
  top-level contract volume. This is a capacity proxy, not a full L2/partial-fill
  model. Unfillable entries are rejected; unfillable exits retain exposure and
  halt the affected lane. No simulation of inventory silently disappearing.
- Price stops/targets and aligned-flow reversal can close before the horizon.
  Time-stop orders are sent early enough to include exit latency within the
  maximum hold. No guarantee of a real stop fill is implied.
- Funding settlement windows are excluded using a contemporaneous funding
  endpoint's next settlement and interval. The schedule must precede capture
  and be less than 24 hours old. No funding PnL is guessed.

No aggregate portfolio return is computed. Closed-trade drawdown omits unrealized
exposure; incomplete execution invalidates total-PnL interpretation. A capture
is one dependence cluster, and overlapping horizon/control trials are not
independent evidence. Manual execution also needs human latency calibration.

## Commands

Install the package, save public endpoint responses, and screen the advertised
inventory without looking at strategy PnL:

```bash
python -m pip install -e .
mkdir -p artifacts/zero_fee_scalping
curl --fail https://api.mexc.com/api/v1/contract/detail \
  -o artifacts/zero_fee_scalping/contracts.json
curl --fail https://api.mexc.com/api/v1/contract/ticker \
  -o artifacts/zero_fee_scalping/tickers.json
orderflow zero-fee-scalping screen \
  --contracts artifacts/zero_fee_scalping/contracts.json \
  --tickers artifacts/zero_fee_scalping/tickers.json \
  --output artifacts/zero_fee_scalping/screen.json
```

For a selected native symbol, fetch its funding schedule before capture:

```bash
curl --fail https://api.mexc.com/api/v1/contract/funding_rate/ZEC_USDT \
  -o artifacts/zero_fee_scalping/funding_ZEC_USDT.json
orderflow-mexc-record --symbol ZEC_USDT --duration-seconds 300 \
  --max-reconnects 0 --output-dir artifacts/zero_fee_scalping/capture
```

Prepare the contemporaneous fee declaration without storing account identifiers
or credentials. The saved pilot record deliberately declares API ineligibility
and can be used for hypothetical-versus-normal engineering comparisons only.
Use the recorder's returned feature path for replay:

```bash
orderflow zero-fee-scalping replay <FEATURES_JSONL> --symbol ZEC_USDT \
  --contracts artifacts/zero_fee_scalping/contracts.json \
  --funding artifacts/zero_fee_scalping/funding_ZEC_USDT.json \
  --fees research/zero_fee_scalping/fee_record_mexc_api.json \
  --protocol config/zero_fee_scalping_v1.json \
  --output artifacts/zero_fee_scalping/report.json
```

Reports are exclusive-create. Use a new output filename for each replay.
The flat `orderflow-zero-fee-scalping` command exposes the same implementation.

## Validation boundary

Do not rank settings by pilot PnL or retune existing protocols. Establish an
eligible promotion, execution feasibility and sufficient independent capture
coverage first. Then freeze one candidate, risk/exit rules, minimum independent
session/day clusters and trade counts, cost stresses, trial accounting and a
predetermined untouched evaluation window. Compare normal fees and reversed
controls, retain failed captures, and require paper fill reliability and the
existing repository promotion gates before any deployment claim.
