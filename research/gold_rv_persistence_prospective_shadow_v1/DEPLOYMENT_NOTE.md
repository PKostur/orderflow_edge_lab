# Default-branch deployment note

This branch is an engineering-only deployment of the already-frozen `gold-rv-persistence-prospective-shadow-v1` state monitor onto the repository default branch so GitHub's scheduled workflow can execute automatically.

Research provenance is unchanged:

- original protocol frozen before the prospective start;
- prospective inference boundary remains `2026-09-16T04:00:00Z`;
- candidate remains `rv_persistence` with frozen positive sign;
- source remains Dukascopy XAUUSD bid M1 via `dukascopy-node@1.50.0`;
- scorer/config/protocol/helper are copied byte-for-byte from the existing prospective-shadow branch;
- no parameter, threshold, gate, anchor, baseline, source, candidate, or claim boundary is changed;
- economics and direction remain disabled;
- no live or leverage authorization is introduced.

Reason for deployment: the original shadow PR remained off the default branch, so GitHub's scheduled trigger did not accumulate daily post-start observations. Run 35524153707 was generated on 2026-09-20 via an engineering-only push retrigger to recover the first post-start evidence snapshot without changing research logic.

This deployment must be reviewed as infrastructure plumbing, not as a new research version.
