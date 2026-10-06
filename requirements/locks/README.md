# Prospective dependency locks

These are **engineering/CI successor artifacts**. They do not rewrite frozen research-environment records or claim binary identity across platforms.

## Available reviewed artifact lock

`py312-manylinux-x86_64-research.txt` is hash-locked from local wheel artifact bytes available during this implementation. It covers the runtime dependency plus `.[research]` transitives for **CPython 3.12 / Linux x86_64**.

| Package class | Recorded artifact tags |
| --- | --- |
| numpy, scipy, scikit-learn | `cp312-cp312-manylinux_2_27_x86_64`, `manylinux_2_28_x86_64` |
| pandas | `cp312-cp312-manylinux_2_24_x86_64`, `manylinux_2_28_x86_64` |
| websockets | `cp312-cp312-manylinux_2_5_x86_64`, `manylinux1_x86_64`, `manylinux_2_17_x86_64`, `manylinux2014_x86_64` |
| pure Python transitives | `py2/py3-none-any` or `py3-none-any` as recorded in wheel metadata |

The requirement hashes are SHA-256 values computed over those exact local wheel bytes. They are not guessed from installed files and are not a claim of a provider signature, durable artifact store, or cross-platform equivalence.

## Intended reproducible artifact verification

Once reviewed artifact retrieval is available to the integration/release owner, use a fresh target-matching virtual environment:

```bash
python -m pip install --require-hashes -r requirements/locks/py312-manylinux-x86_64-research.txt dist/orderflow_edge_lab-*.whl
python -m pip check
python scripts/package_smoke.py dist/orderflow_edge_lab-*.whl
```

Repeat with the built sdist. `scripts/package_smoke.py` compares the installed wheel metadata to `command_registry_v2.json` and performs only `--help` safe probes (with an explicit metadata-only GUI exception); it does not request market data or create orders.

## Explicit coverage blocker

No authentic CPython 3.10, CPython 3.11, or Windows artifact set was locally available, and this stage was not authorized to download or install fresh dependencies. Therefore those supported CI targets are **not yet hash-locked or artifact-install-verified**. The integrator/release owner must resolve and review target-specific wheel/sdist artifacts, record their exact hashes and resolver/Python/platform provenance, then run clean wheel and sdist installs with `pip check` before activating a full artifact-release gate. Do not reuse the Linux CPython 3.12 wheel hashes for other targets.

Lock refresh is a reviewed dependency-maintenance change: regenerate a target-specific lock from resolved artifacts, inspect the diff, run the relevant clean artifact installation and full safe command registry smoke, then commit the lock and evidence together.
