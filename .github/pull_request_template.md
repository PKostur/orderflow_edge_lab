## Scope

<!-- What changes, and why? Keep engineering changes separate from research claims. -->

## Change class

- [ ] Engineering / CI / documentation only
- [ ] Development research
- [ ] Frozen candidate / validation tooling
- [ ] Prospective / forward-watch infrastructure
- [ ] Formal review / terminal research record

## Research-integrity checklist

- [ ] This PR does not silently change an existing frozen strategy, threshold, universe, cost model, session definition, prospective boundary, or review gate. Any intentional versioned change is named and justified below.
- [ ] No inspected validation/forward outcome was used to retune the same frozen research ID.
- [ ] New research definitions were registered/frozen before the evidence they score was inspected, or the work is explicitly labelled post-hoc/descriptive.
- [ ] Data provenance, timestamps, dependence units, costs/funding/slippage, and source limitations are recorded where applicable.
- [ ] Failed or terminal research IDs are not being rescued by sign flips, leverage, relaxed thresholds, or reopened holdouts.
- [ ] `profitable_edge_established`, `live_execution_supported`, and `leverage_supported` remain false unless a separately documented promotion gate has actually been satisfied.

## Validation

- [ ] Relevant deterministic/unit tests pass.
- [ ] CI/lint/release checks are green or any unrelated/cancelled check is explained.
- [ ] Prospective watches preserve their original start boundary and do not score pre-start observations.
- [ ] Generated artifacts/reports are reproducible from the declared inputs where applicable.

## Evidence / boundary notes

<!-- State prospective start timestamps, frozen config IDs/hashes, formal-review IDs, or "N/A — engineering only". -->

## Claim boundary

<!-- State exactly what this PR does NOT establish. Default: no strategy promotion, no live trading, no leverage recommendation. -->
