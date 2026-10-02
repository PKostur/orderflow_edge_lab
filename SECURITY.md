# Security policy

## Supported code

The current `main` branch is the only supported code line. Historical research
branches and closed experiment branches are preserved for provenance and are not
supported runtime releases.

## Reporting a vulnerability

Use GitHub's private vulnerability-reporting / Security Advisory interface when
it is available for this repository. If private reporting is unavailable,
contact the repository owner through GitHub before publishing exploit details.

Do not include exchange credentials, API keys, private market-data entitlements,
account identifiers, or other secrets in an issue, pull request, test fixture, or
research artifact.

## Scope

Security reports are appropriate for vulnerabilities in:

- repository automation and GitHub Actions;
- dependency or supply-chain handling;
- data-integrity and provenance enforcement;
- paper-execution state, approval, journal, or risk controls;
- code paths that could bypass a documented fail-closed boundary.

This repository does not authorize automatic live broker or exchange order
transmission. A security report must not be interpreted as permission to test
against a live account or transmit live orders.

## Research integrity

A change that alters a frozen research definition, decision threshold, evidence
boundary, or immutable review artifact is also a research-integrity event. Such
changes must use a new version or research ID unless the existing protocol
explicitly permits the modification.
