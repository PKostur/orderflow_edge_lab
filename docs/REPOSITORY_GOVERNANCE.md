# Repository governance

This document covers repository maintenance only. It does not alter any frozen
research definition, prospective boundary, trading rule, promotion gate, or
execution authority.

## Canonical source of truth

`main` is the canonical engineering and research-control branch. Long-lived
research branches may preserve provenance, but they are not allowed to become a
second operational source of truth.

A result that matters after a research lane closes should end in one of two
states:

1. its canonical immutable artifacts are merged into `main`; or
2. the pull request is closed with an explicit pointer to the canonical record
   that supersedes it.

Stacked research branches are permitted during active work, but completed stacks
must be collapsed or closed rather than left as permanent competing histories.

## Pull-request lifecycle

Active integration pull requests should target `main` and remain narrow enough
to review. Research pull requests may be larger when they preserve a frozen
sequence, but their terminal result must be recorded in the research index.

A pull request is considered stale for repository-maintenance purposes after
30 days without activity. Stale does not mean invalid. Before closing a stale
research PR, verify whether it contains any artifact, frozen definition, formal
review, or provenance record that is not already represented on `main`.

Do not close or rewrite a branch merely to reduce the open-PR count when doing so
would obscure research provenance.

## Required engineering checks

For changes that can affect executable code or automation, the expected checks
are:

- CI on Python 3.10, 3.11, 3.12 and Windows 3.12;
- Ruff lint;
- Multi-Agent Hardening;
- standalone release-bundle smoke checks where triggered;
- CodeQL for Python changes;
- any workflow-specific guardrail that the touched path activates.

A green engineering check establishes engineering health only. It does not
establish a profitable trading edge.

## Recommended protection for main

Repository administrators should configure a branch protection rule or GitHub
ruleset for `main` that:

- requires a pull request before merge;
- requires the core CI and lint checks to pass;
- requires conversations to be resolved;
- blocks force pushes and branch deletion;
- applies to administrators unless an explicit emergency process is documented.

CODEOWNERS is present so sensitive paths automatically request owner review once
branch protection or an equivalent ruleset is enabled.

## Dependency and security maintenance

Dependabot checks Python and GitHub Actions dependencies weekly. CodeQL analyzes
Python changes and runs weekly. Dependency updates must not silently change a
frozen research definition or invalidate a frozen evidence environment; when
runtime reproducibility matters, the applicable constraint or environment record
takes precedence.

## Research boundary

Repository cleanup must never be used to rewrite research history. Frozen
configuration hashes, formal-review snapshots, prospective boundaries, inspection
registries, and terminal failed research IDs remain authoritative even after the
corresponding working branch is archived or closed.
