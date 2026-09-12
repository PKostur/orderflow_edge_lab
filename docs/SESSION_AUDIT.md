# Paper session closeout audit

`orderflow-session-audit` closes the operational provenance loop around an approval-bound paper session.

Before a session, create the normal runtime snapshot:

```powershell
orderflow-runtime-snapshot create `
  --state runtime\paper-state.json `
  --journal runtime\paper-journal.jsonl `
  --output runtime\snapshots\session_start.json
```

New snapshots include the exact journal byte boundary at session start. This allows the closeout to prove that all journal history that existed before the session is still byte-for-byte unchanged.

After the paper session ends:

```powershell
orderflow-session-audit `
  --snapshot runtime\snapshots\session_start.json `
  --state runtime\paper-state.json `
  --journal runtime\paper-journal.jsonl `
  --output runtime\snapshots\session_closeout.json
```

By default the closeout requires a flat runtime with no pending proposals or open paper positions. It verifies the pre-session journal prefix, rejects truncation or history rewrites, reports records appended during the session, checks state revision monotonicity, checks that engine configuration and trading day did not change, and re-runs paper runtime readiness checks.

The closeout output is itself SHA-256 bound. It is operational evidence only. It does not establish an out-of-sample edge, profitability, or permission for live broker transmission.

Older runtime snapshots created before the journal byte boundary was added cannot be used for append-only session closeout. Create a fresh pre-session snapshot instead.
