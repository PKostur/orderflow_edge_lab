param(
    [switch]$StartDaemon
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Invoke-Ruflo {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & npx.cmd -y ruflo@latest @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Ruflo command failed: $($Args -join ' ')"
    }
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required. Install Node 20 or newer."
}
if (-not (Get-Command npx.cmd -ErrorAction SilentlyContinue)) {
    throw "npx is required. Install npm with Node.js."
}

$NodeVersion = (& node --version).TrimStart('v')
$NodeMajor = [int]($NodeVersion.Split('.')[0])
if ($NodeMajor -lt 20) {
    throw "Ruflo requires Node >=20. Found $NodeVersion."
}

$BackupRoot = Join-Path ([System.IO.Path]::GetTempPath()) "orderflow-ruflo-$PID"
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
$AgentFile = Join-Path $RepoRoot "AGENTS.md"
$SkillFile = Join-Path $RepoRoot ".agents\skills\orderflow-research\SKILL.md"
$AgentBackup = Join-Path $BackupRoot "AGENTS.md"
$SkillBackup = Join-Path $BackupRoot "SKILL.md"
Copy-Item $AgentFile $AgentBackup -Force
Copy-Item $SkillFile $SkillBackup -Force

try {
    Invoke-Ruflo init --codex --force --no-signup
}
finally {
    Copy-Item $AgentBackup $AgentFile -Force
    New-Item -ItemType Directory -Force -Path (Split-Path $SkillFile) | Out-Null
    Copy-Item $SkillBackup $SkillFile -Force
    Remove-Item $BackupRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Invoke-Ruflo doctor
Invoke-Ruflo swarm init --topology hierarchical --max-agents 7 --strategy specialized

Invoke-Ruflo memory store --namespace "orderflow/decisions" --key "safety-boundary-v1" --value "Automatic live broker/exchange transmission is disabled. Ruflo and DeerFlow coordinate research but cannot bypass candidate freeze, holdout audit, trial ledger, realistic economics, approval-bound paper execution, reconciliation, or explicit future user approval."
Invoke-Ruflo memory store --namespace "orderflow/decisions" --key "orchestration-layers-v1" --value "Ruflo is the meta-harness for memory/swarm coordination; DeerFlow provides trading-domain context; orderflow_edge_lab is the executable source of truth and deterministic evidence gate."
Invoke-Ruflo memory store --namespace "orderflow/experiments" --key "current-research-v1" --value "Preserve frozen discovery-v1 thresholds. Current research stratifies executable PF by pre-registered market conditions and transfers the unchanged strategy to PnL-independent screened MEXC pairs. Exploratory findings are not OOS proof."

if ($StartDaemon) {
    Invoke-Ruflo daemon start
}

Write-Host "Ruflo integration is initialized for $RepoRoot"
Write-Host "Run: npx ruflo@latest swarm status"
Write-Host "Run: npx ruflo@latest memory search --query orderflow"
if (-not $StartDaemon) {
    Write-Host "Optional background workers: .\integrations\ruflo\bootstrap.ps1 -StartDaemon"
}
