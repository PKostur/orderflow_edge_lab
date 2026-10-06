# Multi-Agent Hardening Control Plane

The repository has a local, zero-additional-cost deterministic governance plane. It performs repository-local checks only; it does **not** invoke an external LLM, collect market data, access credentials, start services/schedules, mutate research evidence, transmit orders, or promote a strategy.

## Versioned evidence semantics

- **v1:** `orderflow-multi-agent` and `config/multi_agents.json` are retained unchanged as historical engineering evidence.
- **v2:** `orderflow-governance-v2 release-profile` consumes the prospective `config/multi_agents_v2.json`. Its `advisory` profile is valid and hash-verifiable but is **not release eligible**. Its `release` profile is `reviewable` only when every required deterministic check executes exactly once, no required check is skipped, no required check fails, and the declared `block_on` severity policy has no matching finding.

The source-of-truth deterministic checker IDs, current count, logical compatibility roles, and lead responsibility are generated in [Governance Map v2](GOVERNANCE_MAP_V2.md). Do not copy counts or role lists into operational documents.

## Run locally

```bash
# Legacy compatibility surface; its semantics are unchanged.
orderflow-multi-agent --output artifacts/multi_agent_report.json

# Prospective, read-only v2 evidence profile.
orderflow-governance-v2 release-profile \
  --profile release \
  --output artifacts/governance_release_profile_v2.json \
  --strict

# Cheap local triage. This intentionally cannot return `reviewable`.
orderflow-governance-v2 release-profile \
  --profile advisory \
  --output artifacts/governance_advisory_profile_v2.json
```

`--strict` returns nonzero unless the v2 release profile is `reviewable`. Each v2 report contains named required/executed/skipped checks, deterministic evidence digests, a normalized policy hash, a report hash, and mandatory false non-authority claims.

## Release boundaries and blockers

A successful local governance profile is engineering evidence only. It does not prove durable external storage, provider completeness, independent engine calibration, profitability, promotion authorization, or live-order capability. Activation still requires separately approved durable-storage evidence and caller-declared/frozen research and risk policies; v2 does not invent defaults.

The workflow is read-only (`contents: read`). Optional DeerFlow/Ruflo coordination must never substitute for repository tests, command-contract checks, or this deterministic profile.
