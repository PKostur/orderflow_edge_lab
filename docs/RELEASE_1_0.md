# Version 1.0 — research and manual paper release

## Release scope

This is the completed engineering release for local export research and explicit
manual paper operations. It is not an autonomous signal generator, unattended
deployment certification, live trading system, or a claim of profitable edge.

Included:

- Exact timestamp normalization and causal trade/BBO enrichment with diagnostics.
- Local export checks and a masked dxFeed login/test window supporting existing
  Basic or bearer credentials; no credential persistence or redirect forwarding.
- Frozen-candidate observation audits with byte hashes, cost-adjusted descriptive
  summaries, empty-window retention, and no deployment eligibility certification.
- Submit, inspect, approve, reject, close, expire, kill, and release paper commands.
- Durable journal-first state checkpoints, bounded recovery, OS ownership locks,
  persisted execution settings, chronological execution, and portfolio loss checks.
- An installable, dependency-free runtime package with console and GUI commands.

## Install and use

Use Python 3.10–3.12; the login window additionally requires Tk. From the checkout:

```text
python -m pip install .
orderflow-paper init --equity 10000
orderflow-paper status
orderflow-dxfeed-login
```

Or install the built `orderflow_edge_lab-1.0.0-py3-none-any.whl` with pip. Existing
scripts remain thin wrappers for the installed commands. For observation audits,
pass `orderflow-validate --registry PATH` pointing to your preserved frozen registry;
the wheel does not silently create or replace research rules.

See [operator and migration instructions](DEPLOYMENT.md), [data access](DXFEED.md),
and [research protocol](RESEARCH_PROTOCOL.md).

## Verification

CI runs the regression suite, compilation, paper/restart diagnostics, wheel build,
and isolated installed-command smoke tests on Ubuntu Python 3.10, 3.11, 3.12 and
Windows Python 3.12. The network-authentication tests use mocks and do not require
or store credentials. Synthetic fixtures verify engineering behavior only.

The actual user-initiated dxFeed test returned an HTTP 302 redirect; this does not
confirm or deny the account's external API entitlement. Fresh real-market evidence
and subscription-specific access remain external inputs, not release-test claims.

## Remaining operational boundaries

- Confirm the provider endpoint, entitlement, and required NQ/MNQ history before
  attempting real-market validation. No paid subscription was added by this release.
- Supervise manual paper use. Clock synchronization, off-process backups, process
  monitoring, and representative paper soak testing remain deployment responsibilities.
- Partial journal tails fail closed. Coordinated rollback of both state and journal
  requires external checkpoint comparison to detect; local hashes are not signatures.
- Storage power-loss behavior and network filesystems are outside the tested guarantee.
- Research observations and coverage are supplied assertions until independently audited.
- No module can transmit broker orders; live readiness remains false.
