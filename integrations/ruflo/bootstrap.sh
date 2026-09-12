#!/usr/bin/env bash
set -euo pipefail

START_DAEMON=0
if [[ "${1:-}" == "--start-daemon" ]]; then
  START_DAEMON=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

command -v node >/dev/null 2>&1 || { echo "Node.js 20+ is required" >&2; exit 1; }
command -v npx >/dev/null 2>&1 || { echo "npx is required" >&2; exit 1; }
NODE_MAJOR="$(node --version | sed 's/^v//' | cut -d. -f1)"
if [[ "$NODE_MAJOR" -lt 20 ]]; then
  echo "Ruflo requires Node >=20; found $(node --version)" >&2
  exit 1
fi

ruflo() {
  npx -y ruflo@latest "$@"
}

BACKUP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t orderflow-ruflo)"
trap 'rm -rf "$BACKUP_DIR"' EXIT
cp AGENTS.md "$BACKUP_DIR/AGENTS.md"
cp .agents/skills/orderflow-research/SKILL.md "$BACKUP_DIR/SKILL.md"

set +e
ruflo init --codex --force --no-signup
INIT_STATUS=$?
set -e
cp "$BACKUP_DIR/AGENTS.md" AGENTS.md
mkdir -p .agents/skills/orderflow-research
cp "$BACKUP_DIR/SKILL.md" .agents/skills/orderflow-research/SKILL.md
if [[ "$INIT_STATUS" -ne 0 ]]; then
  echo "Ruflo initialization failed" >&2
  exit "$INIT_STATUS"
fi

ruflo doctor
ruflo swarm init --topology hierarchical --max-agents 15 --strategy specialized
ruflo agent spawn --type coordinator --name orderflow-lead
ruflo agent spawn --type researcher --name data-integrity
ruflo agent spawn --type researcher --name trend-structure
ruflo agent spawn --type researcher --name volatility-regime
ruflo agent spawn --type researcher --name liquidity-microstructure
ruflo agent spawn --type researcher --name aggressive-flow
ruflo agent spawn --type researcher --name mean-reversion
ruflo agent spawn --type researcher --name cross-asset-context
ruflo agent spawn --type researcher --name derivatives-session
ruflo agent spawn --type performance-engineer --name execution-economics
ruflo agent spawn --type reviewer --name risk-path
ruflo agent spawn --type reviewer --name indicator-orthogonality
ruflo agent spawn --type researcher --name research-validity
ruflo agent spawn --type researcher --name transfer-generalization
ruflo agent spawn --type tester --name reliability-observability

ruflo memory store --namespace "orderflow/decisions" --key "safety-boundary-v1" --value "Automatic live broker/exchange transmission is disabled. Ruflo and DeerFlow coordinate research but cannot bypass candidate freeze, holdout audit, trial ledger, realistic economics, approval-bound paper execution, reconciliation, or explicit future user approval."
ruflo memory store --namespace "orderflow/decisions" --key "orchestration-layers-v1" --value "Ruflo is the meta-harness for memory/swarm coordination; DeerFlow provides trading-domain context; orderflow_edge_lab is the executable source of truth and deterministic evidence gate."
ruflo memory store --namespace "orderflow/experiments" --key "current-research-v2" --value "Preserve discovery-v1 and regime-research-v1 definitions. First predict future market state, then test conditional strategy economics. Use specialized trend, volatility, liquidity, flow, mean-reversion, cross-asset, derivatives/session, execution, risk, orthogonality, validity and transfer roles. Exploratory findings are not OOS proof."
ruflo memory store --namespace "orderflow/decisions" --key "indicator-combination-policy-v1" --value "Do not combine indicators solely because they each show high PF. Prefer non-redundant features that add incremental market-state information or have a pre-specified interaction rationale."

if [[ "$START_DAEMON" -eq 1 ]]; then
  ruflo daemon start
fi

echo "Ruflo integration is initialized for $REPO_ROOT"
echo "Run: npx ruflo@latest swarm status"
echo "Run: npx ruflo@latest agent list"
echo "Run: npx ruflo@latest memory search --query orderflow"
if [[ "$START_DAEMON" -eq 0 ]]; then
  echo "Optional background workers: bash integrations/ruflo/bootstrap.sh --start-daemon"
fi
