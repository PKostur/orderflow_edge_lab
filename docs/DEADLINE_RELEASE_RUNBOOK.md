# Deadline standalone release runbook

This project must remain usable without ChatGPT or any premium ChatGPT feature.

## Install

Requirements: Python 3.10-3.12 and internet access to public MEXC endpoints.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .[research]
```

Linux/macOS shell:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[research]'
```

## Paper/shadow agents

The repository contains frozen candidate specifications under `config/`. Candidate hashes are checked at runtime. The agents use public MEXC market data and do not require exchange credentials.

ENA 1h frozen mean-reversion shadow:

```bash
orderflow-ena-forward-shadow --candidate config/ena_mean_reversion_candidate_v1.json --output artifacts/ena/report.json --source-output artifacts/ena/ENA_USDT_1h.csv
```

10-coin 8h frozen trend shadow:

```bash
orderflow-htf-trend-forward-shadow --candidate config/htf_trend_candidate_v1.json --output artifacts/trend/report.json --source-dir artifacts/trend/source
```

10-coin daily 30d/7d cross-sectional shadow:

```bash
orderflow-cross-sectional-forward-shadow --candidate config/cross_sectional_candidate_v1.json --output artifacts/xs/report.json --source-dir artifacts/xs/source
```

## Safety boundary

These commands are paper/shadow research. They do not automatically transmit live exchange orders. Do not reinterpret visible forward PnL as proof of a permanent edge. Candidate parameters must not be changed after their forward boundary when evaluating their recorded forward evidence.

## Verification

Run:

```bash
orderflow-multi-agent --output artifacts/multi_agent_report.json
python -m unittest discover -s tests -v
```

The deterministic release-manager status should be `reviewable`, and tests should pass before relying on a build.

## GitHub evidence

GitHub Actions preserves forward reports, source hashes and scoreboard artifacts. The deadline release workflow also produces a downloadable ZIP containing the installable wheel, source/configuration snapshot, runbook and SHA-256 manifest. These artifacts are independent of ChatGPT access.
