# Process Integrity v2 release note

## What this release adds

This release adds **opt-in, offline v2 successor surfaces** for ingestion readiness,
data integrity, feature/target contracts, discovery governance, economic accounting,
validation bindings, portfolio-risk reporting, paper-only execution controls, forward
operations overlays, and engineering governance. The successors preserve legacy
research records, frozen configurations, active-watch starts, scoring, accounting, and
review semantics. They do not reinterpret previously inspected or sealed evidence.

The release also adds a package-owned command registry, installed console-script
metadata checks, and a strict local governance release profile. These are software
quality controls, not scientific or operating authorization.

## Safe opt-in examples

Install the package using the project’s normal local environment, then inspect the
registered successor surface without collecting data or creating a watch:

```bash
python -m pip install -e ".[research]"
orderflow-v2 --list
orderflow-contracts-v2 --help
orderflow-ingestion-v2 --help
orderflow-data-integrity-v2 --help
orderflow-features-v2 --help
orderflow-discovery-governance-v2 --help
orderflow-economics-v2 --help
orderflow-validation-binding-v2 --help
orderflow-portfolio-risk-v2 --help
orderflow-paper-replay-v2 --help
orderflow-paper-execution-v2 --help
orderflow-forward-operations-v2 --help
```

A release owner can generate a **read-only local** code-quality report:

```bash
orderflow-governance-v2 release-profile \
  --profile release \
  --output artifacts/governance_release_profile_v2.json \
  --strict
```

The release-profile command validates local repository checks and emits a
self-hashed report. A `reviewable` result means its required local checks ran without
required failures or skips. It is **not** an activation, promotion, profitability, or
live-execution decision.

## No activation in this release

This release does **not** enable or start any of the following:

- active/prospective watches, market-data collectors, schedules, services, or
  third-party-provider calls;
- broker/exchange order transmission, live trading, credentials, purchases, or
  sealed-holdout access;
- changes to frozen v1 research/configuration/evidence identity or active-watch
  scientific semantics.

All v2 authority claims remain false, including durable external storage, provider
completeness/authenticity, independent-engine calibration, profitable edge,
promotion authorization, and live-order support.

## Before any future activation

A future owner must separately approve and freeze each applicable policy before later
relevant evidence is viewed. That includes risk limits, economic/funding and
execution assumptions, eligibility/retention rules, cohort/family/cluster designs,
and provider capabilities. Activation additionally requires independently evidenced
provider/source completeness, durable immutable retention plus retrieval rehearsal,
qualified prospective inputs, and any required independent-engine/execution
calibration. Local SHA-256 checks and this release’s fixture tests do not substitute
for those external prerequisites.
