# Jev research decision layer

## Purpose

Jev is integrated as a bounded research-orchestration sidecar. It does not own strategy logic, position sizing, execution, risk limits, promotion, leverage, or frozen protocol definitions.

The architecture is:

```text
DETERMINISTIC RESEARCH STATE
        |
        v
JEV BOUNDED JUDGMENTS
  research_action
  dominant_uncertainty
  protocol_intact
  evidence_maturity
        |
        v
DETERMINISTIC POLICY
  allowed-action filter
  confidence threshold
  hard protocol veto
        |
        v
RESEARCH ACTION ONLY
```

The frozen universal session/alignment shadow remains unchanged.

## Jev questions

The v1 battery asks four atomic questions against the same compact research state:

- `research_action`: one of `collect_more_evidence`, `inspect_data_quality`, `inspect_state_coverage`, `prepare_formal_review`, or `stop_protocol_breach`;
- `dominant_uncertainty`: sample size, state coverage, data quality, mixed strategy results, or none;
- `protocol_intact`: bounded yes/no probability;
- `evidence_maturity`: ordered score from pre-start through review-ready or invalid.

## Hard ownership boundary

Code, not Jev, owns these rules:

- with zero completed prospective trades, state-coverage inspection is not an allowed action; the system continues evidence collection unless there is a concrete data-quality issue;

- any frozen-protocol breach forces `stop_protocol_breach`;
- Jev may only choose from actions allowed by deterministic state;
- a low-confidence Jev choice falls back to a deterministic action;
- Jev cannot authorize strategy promotion;
- Jev cannot authorize live trading;
- Jev cannot authorize leverage;
- Jev cannot change frozen strategy or hypothesis definitions.

This keeps the decision model useful without making it the source of trading truth.

## Providers

`provider=jev` uses TypeSafe System One through `typesafe-sdk` and requires `TYPESAFE_API_KEY`.

`provider=offline` uses a deterministic local fallback for tests and environments without Jev credentials. Its accepted choices are labeled `offline_bounded_choice`, never `jev_bounded_choice`.

`provider=auto` tries Jev when a TypeSafe key is available and otherwise uses the offline fallback.

Install Jev support with:

```bash
python -m pip install -e ".[research,jev]"
```

Run a decision over a shadow report:

```bash
orderflow-jev-research-decision \
  --shadow-report artifacts/universal_session_alignment_shadow/report.json \
  --output artifacts/jev_research_decision.json \
  --provider auto
```

## Chat usage

The same contract should be used when making research decisions in ChatGPT:

1. state the deterministic facts;
2. frame only bounded Jev-style judgments;
3. apply hard protocol and risk vetoes outside the judgment model;
4. choose the research action;
5. never represent a local ChatGPT judgment as an actual Jev API result.

Until a native TypeSafe/Jev ChatGPT integration is available, chat-side decisions are Jev-style rather than direct Jev inference. Actual Jev output must identify the provider and model in the decision artifact. In this chat, research decisions should follow the same sequence: deterministic state, bounded judgment, deterministic veto, selected research action.
