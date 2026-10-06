# Process Integrity v2 — Genuine offline independent calibration (05-F5)

## Disposition: native evidence implemented; finding remains partially calibrated

This successor closes the previous **engine-not-installed/adapter-not-implemented** gap. It runs the genuine Rust-native **NautilusTrader BacktestEngine 2.0.0rc5** against eight completely synthetic fixtures. Native matching, notional taker commissions, netting, weighted-average-cost resize, reversal, funding and explicit terminal liquidation are exercised and reconciled. **This is engineering evidence, not market realism, profitability, promotion, or external attestation.** No market data, provider, credential, collector, account, holdout, service or live order path is used.

Two models are deliberately kept distinct:

1. **`canonical_quote_fixed_contract_v2`**: new opt-in transparent fixed-contract quote ledger. It handles BBO prices, native-style notional fees and explicit settlement/resize/reversal events. It is independently compared with the native engine, not with another copy of itself.
2. **Frozen `canonical_v3`**: unchanged equity-weighted, compounded turnover-cost/bar-open model. It is executed diagnostically on **every** fixture, but is **NOT independently calibrated** by claiming it equals the quote model. In particular, it has no bid/ask inputs, and its fee, resize sizing and funding conventions differ. No frozen result or research byte is changed.

The old `docs/PROCESS_V2_05_BACKTESTING.md` correctly described the then-missing shared-venv engine; this addendum records the new **dedicated optional environment**, not a change to that historical claim or shared environment.

## Authentic engine identity and byte checks

| Identity | Pin / evidence |
|---|---|
| Distribution | `nautilus_trader==2.0.0rc5` (same version as original repository execution calibration) |
| Python | CPython **3.12.3**, native v2 wheel requires CPython 3.12 |
| Platform tested | Linux x86_64, glibc 2.39, Ubuntu 24.04 |
| Artifact | `nautilus_trader-2.0.0rc5-cp312-cp312-manylinux_2_34_x86_64.whl` |
| SHA-256 | `eab45fafd2312deda1236554c49a9798bfc76bc8465af864878e2f70189ebebe` |
| Published source | [PyPI rc5 release manifest](https://pypi.org/pypi/nautilus_trader/2.0.0rc5/json) |
| Wheel URL | [Official PyPI distribution](https://files.pythonhosted.org/packages/9c/f7/c3ff46171588fb1cf52ccfde078e5738ab1929aa72ad8da5831c086a1c8a/nautilus_trader-2.0.0rc5-cp312-cp312-manylinux_2_34_x86_64.whl) |

`verify_engine_wheel` hashes the supplied wheel, enforces this exact version/platform, and compares **all 97 installed package files** byte-for-byte with wheel members, including the native extension. It does not accept an arbitrary supplied engine-name/version/hash as proof. Wheel downloading and installation are explicit reversible setup steps; the adapter never downloads anything. There is no signature/SLSA/attestation claim. Other Python/platform wheels are not silently substituted; they currently return unavailable until separately pinned and tested.

The original adapter at `research/discovery_v2/adapters/run_nautilus_execution_calibration.py` and its calibration status remain untouched. No original data was fetched or replayed.

## Reproducible protocol and audit

Frozen fixture: [`tests/fixtures/v2_13_independent_calibration.json`](../tests/fixtures/v2_13_independent_calibration.json). Input source identities bind each synthetic quote-case's canonical bytes. Fixture expected ledgers were calculated from the separate reference model and stored as ordinary numeric test data, **not** generated from the native ledger at runtime. Tests require both reference and native output to match those frozen ledgers.

- Starting cash: 10,000 USDT. Integer fixed contracts, multiplier 1; two-decimal synthetic tick 0.01.
- Quote times: `1700000000000000000 + step*10000000000 + 1 ns`.
- Funding settlement: at the boundary **one ns before** the quote/resize/reversal/terminal fill; latest rate update arrives one second before the boundary. Old held quantity and previous quote midpoint determine native settlement. Positive rates debit longs and credit shorts; negative and observed-zero rates are included.
- A `null` funding rate means **no scheduled settlement in this synthetic case**, not an unknown rate converted to zero. This does not establish completeness of real funding data.
- Native `MakerTakerFeeModel` computes commissions from the instrument's notional percentage rate, with USDT eight-decimal money precision. Fees are included on terminal and reversal quantities.
- Native `OneTickSlippageFillModel(prob_slippage=1, seed=42)` in rc5 **empirically moves these L1 fills by two ticks**, not one. The fixture records that observed engine behavior explicitly; it is not relabelled as a one-tick result or a proportional-bps calibration.
- Predetermined tolerance: **absolute `1e-7`, relative `0`**. Integer nanosecond timestamps are compared without casting to float, so a one-ns timing perturbation fails. Quantity/order/event count and names are exact in the bounded integer fixtures.
- Every fixture must include a nonzero held position immediately before the explicit final liquidation; no-op fixtures cannot gain terminal calibration evidence.

Native output is extracted from **OrderFilled callbacks, cached Position/Position snapshot realized PnL, PositionAdjusted FUNDING records, and AccountState cash balances**. The adapter never calls the reference calculator and never reads `expected_ledger`; an adversarial test replaces expected data and makes the reference function raise to prove this separation. Reversal engine snapshots preserve the closed episode, including its commissions and funding adjustments.

Each report contains the actual normalized fill/event/fee/funding/trade/cash series, raw native audit events, runtime and adapter-source identity, and native account-change-minus-position-PnL residual. Native cash and native position PnL reconcile within `1e-7`; open positions are zero. Nondeterministic native event UUIDs remain in the audit, not in the deterministic comparison ledger.

| Synthetic case | Final native cash (USDT) | Native/reference result |
|---|---:|---|
| long BBO + notional fees | 9999.596 | matched |
| short BBO + notional fees | 9991.596 | matched |
| resize up/down + reversal | 9992.978 | matched |
| native adverse tick-slippage + resize/reversal | 9992.778 | matched |
| long funding + final-boundary terminal settlement | 9998.992 | matched |
| short positive/negative funding | 9991.392 | matched |
| observed-zero funding + resize/reversal | 9993.085 | matched |
| close, reopen opposite, terminal close | 9995.594 | matched |

In the zero/resize/reversal case, native funding adjustments are `[0.0, -0.303, +0.204, +0.206]` USDT. Terminal funding precedes the actual terminal fill by exactly one ns. Changing fee, funding sign, BBO, slippage model, resize or reversal inputs while preserving the frozen expectation produces **ENGINE_LEDGER_MISMATCH**. A supplied ledger, even when matching, never receives the genuine-local-runtime evidence status.

## Runtime and CLI

`orderflow_edge_lab.independent_calibration_v2` is additive. `orderflow_edge_lab.economics_v2` exposes the new operation through the existing dispatcher/delegator without registry/packaging changes:

```bash
# Preparation, not calibration runtime: no market/provider access.
python3.12 -m venv .venv-native
.venv-native/bin/python -m pip download --no-deps --only-binary=:all: \
  nautilus_trader==2.0.0rc5 -d /tmp/orderflow-native-wheels
# On Linux x86_64 / CPython3.12, verify the published hash before installation.
echo 'eab45fafd2312deda1236554c49a9798bfc76bc8465af864878e2f70189ebebe  /tmp/orderflow-native-wheels/nautilus_trader-2.0.0rc5-cp312-cp312-manylinux_2_34_x86_64.whl' | sha256sum --check
.venv-native/bin/python -m pip install \
  /tmp/orderflow-native-wheels/nautilus_trader-2.0.0rc5-cp312-cp312-manylinux_2_34_x86_64.whl
# Existing numerical/lint extras; pytest is an explicit test-only install.
.venv-native/bin/python -m pip install -e '.[research,dev]' pytest==9.1.1

# REQUIRED dedicated calibration CI job: a missing engine/wheel must fail, not skip.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
ORDERFLOW_REQUIRE_INDEPENDENT_ENGINE=1 \
ORDERFLOW_NAUTILUS_WHEEL=/tmp/orderflow-native-wheels/nautilus_trader-2.0.0rc5-cp312-cp312-manylinux_2_34_x86_64.whl \
.venv-native/bin/python -m pytest -q \
  tests/test_v2_13_independent_calibration.py tests/test_v2_05_backtesting.py
```

For a single fixture, generate a complete request from the frozen suite:

```bash
.venv-native/bin/python - <<'PY'
import json
from pathlib import Path
suite = json.loads(Path('tests/fixtures/v2_13_independent_calibration.json').read_text())
fixture = suite['fixtures'][4]
wheel = '/tmp/orderflow-native-wheels/nautilus_trader-2.0.0rc5-cp312-cp312-manylinux_2_34_x86_64.whl'
Path('request.json').write_text(json.dumps({'fixture': fixture, 'wheel_path': wheel}) + '\n')
Path('fixture.json').write_text(json.dumps(fixture) + '\n')
PY
```

```bash
PYTHONPATH=src .venv-native/bin/python -m orderflow_edge_lab.economics_v2 \
  calibrate-nautilus request.json --output local-calibration.json
# Equivalent installed dispatcher: orderflow economics-v2 calibrate-nautilus request.json
```

The genuine standalone external-runner protocol is also implemented:

```bash
PYTHONPATH=src .venv-native/bin/python -m orderflow_edge_lab.independent_calibration_v2 \
  --wheel /absolute/path/to/the/pinned.whl --fixture fixture.json --output native-ledger.json
```

It is compatible with `run_pinned_external_engine_calibration_v2`'s appended `--fixture`/`--output`. That harness strips the environment intentionally; an installed package or a bootstrap setting the explicit local `src` path is needed when invoking through it. The focused tests execute the real subprocess runner as well as the CLI.

**Unavailable handling**: missing engine, missing/tampered wheel, incompatible Python/platform or native runtime failure produces `NOT_CALIBRATED_ENGINE_UNAVAILABLE`; invalid inputs produce `INVALID`/validation errors. Ordinary dependency-light jobs skip optional native tests, but still test unavailable/invalid behavior and the reference ledger. The integrated `.github/workflows/independent-calibration-v2.yml` job installs the optional exact hash-locked engine and requires all native tests; missing runtime evidence fails rather than skips. The engine is not a base dependency, and the shared dependency-light test environment remains separate.

## Exact claims and remaining blockers

Passing actual execution has status **`LOCAL_INDEPENDENT_CALIBRATION_PASSED_PARTIAL_MECHANISMS`**, with `local_independent_calibration_evidence: true`. Every shared `non_authority_claims` flag remains **false**, including `independent_engine_calibration_verified`; external provenance/attestation flags remain false. Coverage is per-case and distinguishes an unexercised mechanism from an exercised native event.

Still **NOT independently calibrated**:

1. The original v2 envelope's **proportional-bps adverse slippage** and **displayed-depth-linear market impact**. A custom copy of our formula injected into the engine would not constitute independent verification; that fallback was not used.
2. **Frozen canonical_v3 fee, funding, resize and compounding semantics**: diagnostics execute the model but demonstrate different numerical economics, not parity. A separately frozen successor integration or independent native equivalent of those semantics is required before any broader calibration claim.
3. Realistic latency, depth consumption, probabilistic partial fills, insolvency and real-venue funding/source completeness are outside these bounded synthetic fixtures; no real-execution claim is made.
4. Dedicated Linux x86_64 / CPython3.12 native CI wiring and the optional exact hash pin are implemented and verified. Other Python/platform native-engine distributions require their own authentic hash pins and execution evidence; native Windows package-install proof does not imply Windows engine calibration.

Installing the engine is **no longer a blocker**. Broader scientific/external authority remains deliberately unverified.
