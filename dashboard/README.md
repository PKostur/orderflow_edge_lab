# Research Dashboard

Read-only Streamlit dashboard for `orderflow_edge_lab` research evidence.

The design follows the useful separation found in public Streamlit trading-dashboard projects: a data-loader layer reads existing signals/results and the UI visualizes them. This implementation is purpose-built for this repository and does **not** import external strategy logic or synthetic fallback data.

## What it shows

- research artifact registry across `research/**` and `config/**`;
- D0/D2/D3/D4/frozen/shadow stage classification;
- explicit persistent-edge, candidate, live-execution and leverage flags when artifacts provide them;
- numeric strategy/research metrics, including bps/PnL/expectancy/PF-style fields;
- shadow/forward artifacts;
- raw evidence inspection and parse errors.

## Safety boundary

The dashboard is observational only. It cannot:

- change strategy parameters;
- rewrite frozen protocols;
- promote a candidate;
- transmit broker/exchange orders;
- enable leverage.

It also has **no synthetic-data fallback**. Missing evidence appears as missing evidence.

## Run locally

From the repository root:

```bash
python -m pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

Windows PowerShell:

```powershell
py -m pip install -r dashboard/requirements.txt
py -m streamlit run dashboard/app.py
```

The app discovers the repository root automatically. To point at another checkout:

```bash
ORDERFLOW_REPO_ROOT=/path/to/orderflow_edge_lab streamlit run dashboard/app.py
```

## Architecture

```text
research/** + config/**
        |
        v
research_dashboard/loader.py
  - fail-closed parsers
  - stage/status inference
  - explicit gate flags
  - metric extraction
        |
        v
dashboard/app.py
  - overview
  - evidence registry
  - metrics
  - shadow/forward view
  - raw artifact viewer
```

The executable trading/research engine remains `orderflow_edge_lab`; this dashboard is not a source of research truth.
