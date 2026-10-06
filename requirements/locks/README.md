# Prospective dependency locks

These are **engineering/CI successor artifacts**. They do not rewrite frozen research environments, establish provider rights, activate prospective watches, or claim binary identity across platforms.

## Reviewed target closures

The runtime/research and build-tool closures are separately pinned for each supported target. `artifacts.json` records the authentic distribution URLs, byte hashes, sizes, Python requirements, dependency metadata and target identity used to generate the locks. Hashes were checked against downloaded distribution bytes, not guessed from installed files.

| Target | Build lock | Runtime/research lock | Native execution evidence |
|---|---|---|---|
| Linux x86_64 / CPython 3.10 | `py310-manylinux-x86_64-build.txt` | `py310-manylinux-x86_64-research.txt` | Clean wheel and sdist installations exercised locally |
| Linux x86_64 / CPython 3.11 | `py311-manylinux-x86_64-build.txt` | `py311-manylinux-x86_64-research.txt` | Clean wheel and sdist installations exercised locally |
| Linux x86_64 / CPython 3.12 | `py312-manylinux-x86_64-build.txt` | `py312-manylinux-x86_64-research.txt` | Clean wheel and sdist installations exercised locally |
| Windows amd64 / CPython 3.12 | `py312-win-amd64-build.txt` | `py312-win-amd64-research.txt` | Native clean wheel and sdist proof passed in [CI 37511970199](https://github.com/PKostur/orderflow_edge_lab/actions/runs/37511970199); downloaded project artifact hashes reverified |

`build-ci.txt` and `research-ci.txt` select the appropriate target with environment markers. Authentic package identity is not a signature, external attestation or durable-storage guarantee.

## Reproducible wheel AND sdist verification

Run this command with the **native supported interpreter** and a new work directory:

```bash
python scripts/verify_packaging.py --work-dir artifacts/packaging-proof
```

For a previously retrieved exact target artifact directory, add `--artifact-dir /path/to/target-artifacts`. The verifier creates a fresh builder and separate wheel/sdist environments without system site-packages. It installs hash-locked build inputs, builds both project formats, calculates each actual project artifact hash, and performs dependency-enabled `--require-hashes` installations using the full target closure. It then executes `pip check`, installed-command probes outside the checkout, and research dependency imports.

No `PYTHONPATH` fallback or project `--no-deps` installation is used as full artifact proof. The quicker governance wheel smoke remains explicitly **package isolation with a shared dependency runtime**, a separate and narrower check.

The CI matrix repeats native proof for all four targets and retains actual command logs, packaging identities and proof JSON. A lock alone cannot supply proof that a particular source snapshot installed successfully; use the retained evidence from that snapshot.

## Optional independent calibration environment

`independent-calibration-py312-linux.txt` pins the exact authentic NautilusTrader wheel used by the bounded synthetic calibration adapter. It is intentionally not part of the default package dependency closure. The dedicated `independent-calibration-v2.yml` job requires the engine and fails, rather than skipping, if it is unavailable. See [the calibration scope note](../../docs/PROCESS_V2_13_INDEPENDENT_CALIBRATION.md) for the genuine tested mechanisms and remaining unsupported semantics.

## Lock updates

Use `scripts/refresh_packaging_locks.py` to obtain and validate target artifacts, review the generated identities and dependency diffs, then repeat clean artifact verification and the complete regression suite. Preserve old environment records; future locks must not recertify historical research under a new dependency set.
