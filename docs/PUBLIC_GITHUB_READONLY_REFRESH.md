# Public GitHub read-only refresh fallback

When the GitHub connector is unavailable, the repository is public and a research pass may use public GitHub pages or the `gh` CLI to refresh read-only engineering state.

Useful checks include:

```bash
gh pr view 113 --repo PKostur/orderflow_edge_lab \
  --json isDraft,headRefName,headRefOid,commits,files,updatedAt

gh api "repos/PKostur/orderflow_edge_lab/commits?sha=fix/universal-existing-validation&per_page=20"

gh api "repos/PKostur/orderflow_edge_lab/actions/runs?branch=fix/universal-existing-validation&per_page=50"

gh run view <RUN_ID> --repo PKostur/orderflow_edge_lab --log
```

This fallback is for read-only state reconciliation only.

## Evidence limitation

Public PR/commit/run metadata can establish that code or a workflow exists and whether a visible run succeeded.

It does **not** establish the contents of an artifact unless that artifact is actually retrieved and inspected.

If artifact download requires authentication or is otherwise unavailable:

- state that the artifact could not be inspected;
- retain the latest previously verified artifact result as the last confirmed evidence;
- do not infer new trade counts, PnL, verdicts or control-plane state from a green workflow alone.

Connector-native GitHub access remains preferred when available because it can retrieve repository files, workflow logs and artifacts directly.
