# Zero-fee scalping v1: development engineering pilot

Status: **INCOMPLETE_EXECUTION / DEVELOPMENT_ONLY**. No profitable edge,
untouched validation, account fee eligibility or promotion is established.

## Fee feasibility

MEXC's public metadata advertised maker and taker rates of zero for 25 screened
USDT crypto perpetuals. The screen requires spread <=3 bps and 24-hour quote
turnover >=10 million USDT, then ranks by turnover without strategy PnL. Its
top three were ZEC, QNT and NEAR; the first-ranked ZEC pair was captured.
This one snapshot does not prove sustained liquidity or effective account fees.

The [official MEXC API fee update](https://www.mexc.com/announcements/article/updates-to-api-futures-trading-fees-jun-1-2026-17827791535742)
sets the June-1-2026 API taker rate at 0.08% (8 bps per leg), independently of
web/app promotions. Its illustrative example retains older numbers; this
pilot uses the updated table's 8 bps. The [zero-fee event page](https://www.mexc.com/en-GB/zero-fee)
excludes API users and describes account-dependent validity and volume quotas.
No account was accessed. The fee record explicitly marks API eligibility false
and account/region/quota validity unknown, so all applicable-fee results use
the 8-bps declared baseline. This is not an audited account commission rate.

The [Binance FDUSD update](https://www.binance.com/en-NG/support/announcement/detail/4856a6d4e4014d4e8a5a29ec5fb44857)
ended zero taker fees on the selected crypto/FDUSD pairs on January 29, 2026;
zero maker fees remained. No alternative promotion has yet been verified for
both taker legs and the user's API/account/region.

## Pilot

Public ZEC_USDT capture: **2026-10-06 19:35:05–19:40:04 UTC**, approximately five
minutes and one dependence cluster. No keys or orders were used. The settings
were written before strategy outcomes were computed; this is an engineering
pilot, not a frozen validation candidate or statistical test.

Aligned aggressive-flow, book-imbalance and microprice entries use the
development configuration's thresholds. Each lane holds one position at a time,
with 5/15/30/60/120-second maximum holds, price stops and signal-reversal exits.
Thirty lanes cover original/reversed direction and three latency/slippage cases.
These are overlapping development trials, not thirty independent samples.

Every lane ended with an unresolved simulated exit because of quote freshness
or displayed-depth limits. A lane halts at unresolved exposure and retains it
in the report; no later trades are simulated as though the position vanished.
Completed original-direction trades lost money under hypothetical zero fees.
The slow-latency original lanes had no completed trades and no measured
expectancy. Identical outcomes across several horizons are duplicate paths
ended by earlier exits, not independent confirmation.

For illustration, the base 5-second original lane completed 10 trades before
halting with one unresolved position. Closed-trade PnL was approximately
**-0.226 USDT with hypothetical zero fees**, versus **-1.741 USDT at the normal
fee baseline**, for a 100-USDT requested notional per entry. These are closed
prefix figures; they omit the unresolved position and are **not total strategy
PnL**. The run supports no win-rate, profit-factor or return claim for trading.

## Artifacts and reproducibility

- `engineering_pilot_report.json`: all lanes, fills, exclusions, unresolved
  positions and input/source hashes. Its status is incomplete execution.
- `advertised_pair_screen.json`: PnL-independent advertised-fee screen.
- `fee_record_mexc_api.json`: explicit ineligibility and baseline assumption;
  never a template for claiming account verification.
- `pilot_manifest.json`: raw/feature capture hashes and storage limitations.

Raw capture, full contract/ticker/funding responses and downloaded official
terms are retained under `artifacts/zero_fee_scalping/` in this session's
workspace. They are not uploaded or durable repository inputs. The published
hashes and report preserve provenance but do not substitute for raw-data access
in independent reproduction. Use a new capture for further research and retain
its inputs in durable artifact storage before validation.

## Next research decision

For manual MEXC scalping, first confirm exact pair/account fees, remaining quota
and expiry in the app/web interface, then calibrate realistic human latency.
For automated research, first identify an API-eligible promotion on a supported
venue. Do not assume maker-only fees are zero-cost taker round trips.

The current pilot does not justify tuning thresholds, lowering freshness or
depth requirements, or scheduling a prospective validation watch. Next address
full-depth/partial-fill execution feasibility and collect independent sessions.
Freeze a separately versioned candidate, trial ledger, validation window and
decision rules before any untouched validation. Existing release/promotion and
paper execution gates remain applicable.

## Engineering validation

Local Python 3.12: 927 unit/integration tests passed, including 23 focused
scalping tests. Ruff, compile checks, deployment diagnostics, wheel build and
installed-package smoke checks passed. The deterministic hardening release
manager reported `reviewable` with zero errors/warnings. A focused independent
execution review verified the quota, stale-signal and terminal-summary fixes.
These are engineering checks, not trading validation.
