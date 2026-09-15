# Gold Scheduled Macro Reaction v1: development state result

## Evidence identity

- branch: `research/gold-scheduled-macro-reaction-v1`
- canonical workflow run: `34985105443`
- head commit: `f5f8bd4060abbd2996b6973a93ae819d965edee9`
- artifact ID: `10402847710`
- artifact digest: `sha256:1f51f7123c36b632bde7515af04c1dcddea9bf46688ce9fcc74d1cb35c2caaf0`
- development source: pinned Dukascopy XAUUSD M1 bid/ask midpoint proxy
- development input rows: `1,139,040`
- input start: `2020-11-01T00:00:00+00:00`
- input end: `2022-12-31T23:59:00+00:00`
- locked 2023 validation opened: **no**
- economic scoring run: **no**

## Result

The frozen state gate produced **zero candidates**.

- calendar events: 64
- scorable events: 63
- primary hypotheses: 6
- state passes: 0
- state candidates: none

One event, the `2021-04-02` Employment Situation release, was unscorable because the exact required one-minute bars were unavailable. The protocol required dropping rather than interpolating missing event bars.

## Primary hypothesis table

| Hypothesis | Primary 60m effect | Raw p | BH q | Robustness notes | State pass |
|---|---:|---:|---:|---|---|
| CPI excess continuation | -0.0282 pre-event ranges | 0.9182 | 0.9182 | primary sign appears at only 1/3 horizons; directional consistency 50.0% | no |
| Employment excess continuation | +0.2983 pre-event ranges | 0.5010 | 0.9182 | directional consistency 60.9%, but primary sign appears at only 1/3 horizons | no |
| FOMC excess continuation | -0.2414 pre-event ranges | 0.7914 | 0.9182 | negative at all 3 horizons, but directional consistency only 50.0% and inference is weak | no |
| 4h trend-alignment effect | -0.1264 pre-event ranges | 0.8448 | 0.9182 | sign appears at only 1/3 horizons; only CPI subtype agrees while eligible | no |
| Pre-event compression effect | Spearman +0.1692 | 0.1848 | 0.9182 | positive at all 3 horizons and CPI/Employment agree, but primary rho is below frozen 0.25 minimum | no |
| Initial shock-size effect | Spearman +0.0766 | 0.5496 | 0.9182 | sign agrees in 2/3 horizons and CPI/Employment, but effect is far below frozen 0.25 minimum | no |

## Horizon detail

### CPI matched-placebo excess

- 30m: `+0.0347`
- 60m: `-0.0282`
- 120m: `+0.2650`

No stable continuation or reversal sign.

### Employment matched-placebo excess

- 30m: `-0.3965`
- 60m: `+0.2983`
- 120m: `-0.0425`

The attractive 60-minute median does not survive horizon-direction robustness or statistical correction and must not be promoted.

### FOMC matched-placebo excess

- 30m: `-0.1435`
- 60m: `-0.2414`
- 120m: `-0.2287`

The sign is consistently reversal-like, but only half of primary-horizon observations share that sign and the frozen permutation/FDR evidence is weak. This is not a candidate.

### Pre-event compression

Spearman continuation relationship:

- 30m: `+0.1566`
- 60m: `+0.1692`
- 120m: `+0.1303`

This is the most internally direction-consistent pooled feature, but the frozen primary effect threshold was `|rho| >= 0.25`, and the corrected evidence is not significant. It remains a rejected observation, not a tunable seed inside v1.

## Decision

Reject `gold-scheduled-macro-reaction-v1` at the development state gate.

Do not:

- define entries, stops, targets, partials, or costs around these observations;
- optimize the Employment 60-minute result;
- optimize the FOMC reversal-looking pattern;
- lower the compression threshold after seeing the result;
- open the locked 2023 historical validation;
- use leverage to rescue the lane;
- claim executable or profitable edge.

The correct promotion state is:

`development_state -> rejected`

Engineering success, the valid data source, and completion of the permutation study are separate from trading-edge evidence.
