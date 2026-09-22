# H2 prospective ETF shadow

Candidate: `ETF_H2_VWAP_REVERSION_CONTEXT_V1`

Prospective start: **2026-09-22**

This directory is an execution layer for the already frozen candidate. It must not be used to change the candidate after seeing prospective results.

## Frozen signal

Universe:

* SPY
* QQQ
* GLD
* USO

Raw H2 signal:

* Search 09:50 through 11:00 America/New_York.
* Compute cumulative VWAP from exact 09:30 bars through the signal minute.
* Compute sample standard deviation from 20 exact one-minute log returns ending at the signal minute, requiring 21 exact closes.
* z = `log(close / cumulative_vwap) / (sigma_1m * sqrt(20))`.
* First z >= +1 is a short.
* First z <= -1 is a long.
* Entry is the next exact one-minute bar open.
* Exit is the open exactly 10 minutes after entry.
* Missing required minutes fail closed.

Frozen context filter:

For each ticker, compare the current raw H2 signal against the arithmetic mean of the **previous 10 eligible raw H2 signals** for that same ticker.

All three current factors must be strictly greater than their previous-10 mean:

1. absolute VWAP displacement in bps;
2. signal-candle range in bps;
3. signal-minute volume divided by the mean volume of the signal minute plus the preceding 19 exact minutes.

The current signal is added to raw history only **after** its context decision, preventing self-leakage.

## Prospective boundary

`H2_SHADOW_LEDGER.csv` may contain only filtered trades dated **2026-09-22 or later**.

Historical bars before the start date may be used only to construct the rolling previous-10 raw-signal benchmark. They must never be written into the prospective ledger.

## Returns and account model

The tracker reports two capital views.

**Constant-notional curve**

Every eligible trade receives the same notional. Net trade bps are summed through time.

**Four-sleeve portfolio curve**

The account is divided into four fixed 25% sleeves:

* SPY 25%
* QQQ 25%
* GLD 25%
* USO 25%

Unused sleeves stay in cash. Same-day sleeve returns are aggregated and the account compounds daily.

Primary friction is 2 bps round trip. A 4 bps stress view is recorded separately.

## MFE and MAE convention

The position exits at the **open** of the frozen exit minute.

Therefore MFE and MAE use bars from the entry bar through the minute immediately before the exit bar. The exit bar's high and low are excluded because they occur after the position has already been closed.

This convention affects excursion diagnostics only, not strategy PnL.

## Observation target

Do not evaluate the shadow as passed or failed before all three are reached:

* at least 20 filtered trades;
* at least 10 distinct sessions;
* at least 20 calendar days from the prospective start.

Until then the state is `ACCUMULATING`.

## Running locally

Set a Massive API key:

```powershell
$env:MASSIVE_API_KEY="your-key"
```

Run after the US session:

```powershell
python research/cross_market_etf_v1/h2_shadow_tracker.py --through 2026-09-22
```

Outputs are written to:

```text
research/cross_market_etf_v1/shadow/H2_SHADOW_LEDGER.csv
research/cross_market_etf_v1/shadow/H2_SHADOW_EQUITY.csv
research/cross_market_etf_v1/shadow/H2_SHADOW_SUMMARY.json
```

The default run refuses to treat an unfinished current US session as complete. `--allow-intraday` exists for diagnostics but should not be used for the official daily shadow record.

## Tests

```powershell
python -m unittest research/cross_market_etf_v1/test_h2_shadow_tracker.py
```

Tests cover:

* exclusion of post-exit price movement from MFE/MAE;
* strict previous-10 rolling context with no self-leakage;
* four-sleeve portfolio arithmetic;
* profit-factor arithmetic.

## Frozen references

* Filtered candidate freeze: `d7a43d440f97dbd8840e105498dfb40d7416d0ac`
* Corrected historical confirmation: `c878a89f5a8f5a81865ac6394f4b31012f9274ed`
* Prospective shadow freeze metadata: `7840d0b4e05eb026c5a94a94af9f206b0a79b417`
* Exact equity audit: `6b0ee47ecb10f2e84056c1950e58424810e92d62`

No live trading or leverage is authorized by this tracker.
