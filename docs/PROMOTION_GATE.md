# Strategy promotion gate

`orderflow-promotion-check` is a fail-closed barrier between research artifacts and any future strategy promotion decision.

It does not infer profitability from descriptive statistics. It requires an upstream validation artifact to explicitly state both `deployment_eligible=true` and `verified_out_of_sample_evidence=true`. Current `orderflow-validate` reports intentionally set both fields to false, so current evidence remains research-only.

Promotion also requires three immutable provenance and research-governance artifacts:

1. a candidate freeze that binds the exact candidate registry bytes and candidate specification to the frozen research protocol;
2. a holdout audit that proves the exact observation bytes used by validation contain the candidate only inside the predeclared holdout interval and, when source files are supplied, rehashes the referenced market-data bytes locally;
3. a trial ledger that proves this exact candidate specification, holdout audit, and observation set were counted as a holdout inspection within the declared experiment family.

The holdout audit and trial ledger deliberately do not claim an edge. Their research claims remain false. They prove provenance, partition compliance, and holdout-access accounting only.

Create the holdout audit after observations have matured, before promotion checking:

```bash
orderflow-holdout-audit \
  --observations artifacts/holdout_observations.jsonl \
  --candidate-freeze research/candidate_freeze.json \
  --candidate-id CANDIDATE_ID \
  --source-file data/deepcharts_export.csv \
  --output research/holdout_audit.json
```

Count the inspection in the experiment-family ledger before promotion:

```bash
orderflow-trial-ledger append \
  --ledger research/trial_ledger_00.json \
  --holdout-audit research/holdout_audit.json \
  --output research/trial_ledger_01.json
```

The promotion boundary then verifies that:

* the candidate freeze still re-verifies against the current research freeze and registry bytes;
* the holdout audit references the exact candidate-freeze manifest;
* the holdout candidate specification hash matches the frozen candidate;
* the validation report registry SHA-256 matches the frozen registry bytes;
* the validation report observations SHA-256 matches the exact holdout observations bytes;
* holdout event and outcome timestamps remained inside the frozen interval;
* holdout source bytes were locally rehashed successfully;
* the trial ledger manifest is valid;
* exactly one trial-ledger entry matches the candidate ID, candidate specification SHA-256, holdout-audit manifest SHA-256, and observation SHA-256;
* the recorded Bonferroni threshold remains arithmetically consistent with the family alpha and trial number;
* the existing causal-window, evidence-count, source-byte, and economics checks also pass.

The trial ledger does not establish statistical significance. The current validation schema is descriptive and does not provide a calibrated inferential p-value suitable for comparison with the ledger threshold. The ledger therefore prevents silent repeated holdout access from being treated as a single test, while leaving any future significance procedure to a separately specified and validated research method.

For a structurally promotable candidate, the file-backed promotion path performs a second source-byte verification immediately at the promotion boundary. Every source file recorded in `source_verification.files` must still exist as a regular file and its current SHA-256 must match the digest embedded in the validation report. Missing, unreadable, duplicate-resolved, or changed source files fail closed. A successful file-backed assessment records `source_files_reverified=true`.

Project operating costs are part of the gate. If `config/economics.json` contains any non-zero recurring cost, promotion remains blocked until the validation evidence contains a defensible currency-denominated return model that can be compared with those costs. This avoids treating data, platform, compute, or model subscriptions as economically free.

Example:

```bash
orderflow-promotion-check \
  --validation-report artifacts/validation.json \
  --candidate-id CANDIDATE_ID \
  --economics config/economics.json \
  --candidate-freeze research/candidate_freeze.json \
  --holdout-audit research/holdout_audit.json \
  --trial-ledger research/trial_ledger_01.json \
  --output artifacts/promotion_assessment.json
```

Exit codes:

* `0`: all implemented promotion gates passed, including holdout binding, trial accounting, and promotion-time source re-verification.
* `2`: malformed or unreadable evidence.
* `3`: valid evidence was assessed but promotion is blocked.

Passing this command is not permission to transmit live orders. The repository still contains no live broker or exchange transmission path, and `ready_for_live` remains false.
