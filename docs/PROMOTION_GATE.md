# Strategy promotion gate

`orderflow-promotion-check` is a fail-closed barrier between research artifacts and any future strategy promotion decision.

It does not infer profitability from descriptive statistics. It requires an upstream validation artifact to explicitly state both `deployment_eligible=true` and `verified_out_of_sample_evidence=true`. Current `orderflow-validate` reports intentionally set both fields to false, so current evidence remains research-only.

The gate also requires source bytes to have been locally hash-verified and the selected candidate to contain at least one complete causal validation window with matured outcomes.

For a structurally promotable candidate, the file-backed promotion path performs a second source-byte verification immediately at the promotion boundary. Every source file recorded in `source_verification.files` must still exist as a regular file and its current SHA-256 must match the digest embedded in the validation report. Missing, unreadable, duplicate-resolved, or changed source files fail closed. A successful file-backed assessment records `source_files_reverified=true`.

This second verification prevents a previously valid report from silently authorizing paper execution after the underlying research data has been replaced or modified. It does not prove that the original export was authentic or complete.

Project operating costs are part of the gate. If `config/economics.json` contains any non-zero recurring cost, promotion remains blocked until the validation evidence contains a defensible currency-denominated return model that can be compared with those costs. This avoids treating data, platform, compute, or model subscriptions as economically free.

Example:

```bash
orderflow-promotion-check \
  --validation-report artifacts/validation.json \
  --candidate-id CANDIDATE_ID \
  --economics config/economics.json \
  --output artifacts/promotion_assessment.json
```

Exit codes:

* `0`: all implemented promotion gates passed, including promotion-time source re-verification.
* `2`: malformed or unreadable evidence.
* `3`: valid evidence was assessed but promotion is blocked.

Passing this command is not permission to transmit live orders. The repository still contains no live broker or exchange transmission path, and `ready_for_live` remains false.
