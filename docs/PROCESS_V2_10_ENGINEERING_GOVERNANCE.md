# Engineering Governance v2

## Scope and preserved boundaries

This is an **additive, opt-in successor** to the legacy multi-agent and research-control-plane surfaces. It preserves `config/multi_agents.json`, `config/research_control_plane_v1.json`, `multi_agent.py`, `research_control_plane.py`, historical reports, frozen research/config/evidence identity, and legacy command aliases. It contains no collector, scheduler, service, credentials, purchase, broker/exchange-order route, sealed-holdout access, or live-trading capability.

## Executable surfaces

| Surface | Command / API | Semantics |
| --- | --- | --- |
| Multi-agent policy | `config/multi_agents_v2.json`; `validate_policy_config` | Strict pre-dispatch schema validation: unique IDs/checks/paths, safe relative paths, known severities, full required-agent policy, normalized SHA-256. v1 accepts only explicit read-only compatibility mode. |
| Governance profile | `orderflow-governance-v2 release-profile` ; `build_release_profile_v2` | Local deterministic checks with evidence digests. `advisory` is deliberately `not_release_eligible`; `release` can be `reviewable` only with every required check once, no required skip/failure, and no declared-policy blocker. |
| Control plane | `orderflow-governance-v2 control-plane-status`; `build_control_plane_status_v2` | Contract-bound successor status that validates exact input analysis IDs, false authority fields, and operational non-evidence claim, then records four canonical input digests, contract digest, and self-hash. It retains the v1 stage calculation without changing v1. |
| Governance map | `orderflow-governance-v2 governance-map` | Generates `docs/governance_map_v2.json` and `docs/GOVERNANCE_MAP_V2.md` from the validated policy. DeerFlow/Ruflo are logical coordination only, never deterministic evidence. |
| Command registry | `src/orderflow_edge_lab/command_registry_v2.json` | Single package-owned command declaration for targets, flat/dispatcher/gui/internal exposure, safe probe, and alias deprecation state. The dispatcher no longer implicitly discovers unclassified CLI modules. |

## Required release evidence

A prospective release workflow executes:

```bash
orderflow-governance-v2 release-profile \
  --profile release \
  --output artifacts/governance_release_profile_v2.json \
  --strict
```

The read-only workflow runs on pull request, push, and manual dispatch. It asserts hash validity, `execution_profile == release`, zero skipped required checks, and `release_manager.status == reviewable`. No new research cron is introduced or activated.

The package smoke path reads installed distribution entry-point metadata, compares it exactly to the registry, and runs declared flat `--help` probes. `orderflow-dxfeed-login` remains an explicit GUI metadata-only exception. It does not call collectors or order paths.

## Policy and activation blockers

A successful profile is not an activation decision and cannot establish external durable storage, provider completeness, independent-engine calibration, a profitable edge, promotion authority, or live-order support. These remain false through the shared v2 non-authority claims.

New research, scientific, risk, freshness, retention, or eligibility parameters must be caller-declared and separately frozen before later evidence is viewed. This module intentionally provides no working defaults. A durable-storage activation claim needs operator-approved configuration, immutable-copy/retrieval evidence, and recovery rehearsal through the review horizon; local file hashes are insufficient.

## Hash-locked dependency artifacts

`requirements/locks/py312-manylinux-x86_64-research.txt` has authentic hashes for locally available CPython 3.12 Linux x86_64 wheel bytes. It is prospective artifact-install input, not a claim that fresh wheel/sdist installs have occurred. CPython 3.10, CPython 3.11, and Windows locks/install proof are presently **blocked**: target artifacts were not locally available and this stage was not authorized to download or install fresh dependencies. See [requirements/locks/README.md](../requirements/locks/README.md) for exact provenance and the required integrator/release-owner procedure.

## Integration obligations

1. Run the full suite, compile/lint, build wheel and sdist, and run clean target-matching artifact installs with `pip check`.
2. Add reviewed target-specific authentic hash locks for all declared CI platforms before treating artifact reproducibility as release evidence.
3. Keep all v1 commands and reports readable; do not use a v2 profile to recertify frozen evidence.
4. When other stages expose v2 CLIs, the integrator must add explicit command-registry entries and flat metadata exposure decisions, then update registry parity tests and safe probes.
