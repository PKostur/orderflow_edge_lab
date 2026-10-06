# Paper Bot v3: finite offline replay only

`orderflow_edge_lab.paper_bot_v3` is a **deterministic, finite, simulated-only** replay engine. It is an L2 simulation artifact, not a trading service. It has no network, collector, broker, exchange, wallet, credential, account, import-payload, scheduler, endpoint, or live-mode capability.

> **Safety boundary:** `mode="offline"` is the only accepted mode. Any other mode, including `live`, is rejected. Nothing produced by this module is an executable instruction, record of a transaction, or connection to a financial platform.

## Scope and limitations

The engine supports exactly **one caller-declared `synthetic_linear` instrument** per replay. Quantities are fractional model units, and cash/equity is a self-contained hypothetical ledger. It models a full bid/ask cross, positive declared fees, and positive declared slippage.

It does **not** model funding, borrow charges, interest, liquidation, margin rules, taxes, partial fills, queue position, market impact, venue outages, or actual instrument lot/tick rules. The caller must explicitly set:

```json
"instrument": {
  "symbol": "EXAMPLE-USD",
  "contract_multiplier": 1.0,
  "instrument_type": "synthetic_linear",
  "funding_treatment": "not_modeled"
}
```

`funding_treatment: "not_modeled"` is mandatory, rather than silently treating funding as zero. Results are therefore **not funding-inclusive** and must not be used as an execution or profitability claim.

## Python API

```python
from orderflow_edge_lab.paper_bot_v3 import run_paper_bot_v3

artifact = run_paper_bot_v3(
    frames,
    signal_fn,
    policy,
    run_id="research-replay-001",
    mode="offline",
)
```

`frames` is a finite iterable. The result is a JSON-shaped artifact with `mode: "SIMULATED_OFFLINE_ONLY"`. It can be exclusively published with `write_paper_bot_artifact_v3(path, artifact)` and locally checked with `verify_paper_bot_artifact_file_v3(path)`.

### Standardized frame contract

Every frame must be a mapping with these required fields; arbitrary additional JSON fields are allowed and remain visible to the signal function.

| Field | Type | Requirement |
|---|---:|---|
| `ts_ns` | integer | Positive event timestamp in nanoseconds |
| `received_ns` | integer | Positive receipt timestamp in nanoseconds; must be at least `ts_ns` |
| `symbol` | string | Must equal the one policy instrument symbol |
| `bid` | number | Finite and positive |
| `ask` | number | Finite and positive; must be at least `bid` |
| `close` | number | Finite and positive causal input feature; not used as an execution price |
| `source_id` | string | Nonempty provenance label |
| `batch_id` | string | Nonempty caller batch label |

Input is processed in supplied order. Per replay, timestamps must strictly increase and receipt timestamps may not go backward. The engine latches a halt on a malformed, duplicate, future, stale, out-of-order, or wrong-instrument quote. A bad quote **does not** cause an invented flatten: the existing simulated position and any pending target are preserved in the terminal checkpoint.

### Signal function and causality

`signal_fn(history)` receives an immutable tuple of accepted standardized frames. The final item is the current quote and no future quote is present. It returns one finite signed target fraction in `[-1, 1]`:

```python
def signal_fn(history):
    if len(history) < 2:
        return 0.0
    return 0.25 if history[-1]["close"] > history[-2]["close"] else -0.25
```

The policy’s `signal_id` is a caller-declared stable identity for the deterministic signal implementation. It binds checkpoints to the intended signal definition. Signals must be deterministic to obtain restart equivalence.

A signal is recorded as a pending model target **after** its own quote is accepted. It can only be simulated on the next valid quote. The modeled fill crosses the next quote’s `ask × (1 + slippage_bps / 10,000)` for positive quantity changes and `bid × (1 - slippage_bps / 10,000)` for negative changes. Therefore, a signal can never fill on the same event that produced it.

### Required policy

The policy has this exact schema; it rejects missing and extra fields to make risk assumptions visible and hash-bound.

```json
{
  "schema": "orderflow_edge_lab.paper_bot_policy.v3",
  "signal_id": "my-frozen-signal-v1",
  "instrument": {
    "symbol": "EXAMPLE-USD",
    "contract_multiplier": 1.0,
    "instrument_type": "synthetic_linear",
    "funding_treatment": "not_modeled"
  },
  "initial_cash": 10000.0,
  "fee_rate": 0.0005,
  "slippage_bps": 2.0,
  "max_quote_age_ns": 2000000000,
  "max_position_fraction": 0.50,
  "max_gross_exposure_fraction": 0.50,
  "max_loss_fraction": 0.10,
  "max_drawdown_fraction": 0.10
}
```

`fee_rate` and `slippage_bps` are required to be **strictly positive**. Position and gross exposure fractions are capped at 1.0. The cash ledger does not borrow cash: if a requested long target would make cash negative or breach gross exposure, the modeled quantity is reduced deterministically. The engine latches—not flattens—when an equity, maximum-loss, maximum-drawdown, or gross-exposure budget is reached.

## Checkpoints, hashes, and restart

Each accepted or rejected input gets a hash-chained event identity. The result contains a checkpoint with:

- an ordered `event_chain` ending at `event_chain_head`;
- a hash of each state after that event;
- policy hash, signal identity, and exact raw-frame identity prefix;
- a checkpoint hash over all of the above.

A checkpoint passed to `run_paper_bot_v3(..., checkpoint=...)` must match the same `run_id`, policy, signal identity, and full recording prefix. Corrupted state/event hashes, changed policy, or changed/reordered prefix frames fail closed. Restart with the same full recording and deterministic signal function is equivalent to uninterrupted processing:

```python
first = run_paper_bot_v3(frames, signal_fn, policy, run_id="r", max_events=100)
resumed = run_paper_bot_v3(frames, signal_fn, policy, run_id="r", checkpoint=first["checkpoint"])
```

The hashes provide local mutation/replay detection and deterministic identity; they are not a signature, custody record, or external attestation.

## Offline CLI

The module is invoked directly and reads only local finite JSONL/JSON files:

```bash
PYTHONPATH=src /home/ubuntu/orderflow-implementation/venv/bin/python \
  -m orderflow_edge_lab.cli.paper_bot_v3 \
  --recording /path/quotes.jsonl \
  --policy /path/policy.json \
  --signal close-momentum \
  --output /path/new-simulated-artifact.json
```

Each nonblank recording line is one standardized frame JSON object. Built-in signals are deliberately small and local: `flat` and `close-momentum`. The CLI has no provider collection path.

For a visibly non-market fixture only:

```bash
PYTHONPATH=src /home/ubuntu/orderflow-implementation/venv/bin/python \
  -m orderflow_edge_lab.cli.paper_bot_v3 \
  --synthetic-demo --output /path/new-synthetic-demo.json
```

Synthetic-demo output includes `synthetic_demo: true`; it is not observational evidence. Output is validated, written to a temporary local file, `fsync`ed, and atomically linked into a previously absent path. Existing output paths are never overwritten. `--verify` performs a read-only local identity check of `--output`.
