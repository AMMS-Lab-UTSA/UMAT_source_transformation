# Start here

You have five minutes and want to know whether this software does what it says.

```bash
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
cd UMAT_source_transformation
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
python -m umat_oti.reproduce --profile smoke
```

You need Python 3.10 or newer and `gfortran`. No Abaqus, no network, no licence.

The smoke profile takes a few seconds. It transforms one UMAT, compiles it,
compiles the *original* subroutine separately, runs both over a strain path, and
checks that the derivatives the transformed build reports agree with centred
differences of the original. It exits non-zero if they do not.

It writes five files into `reproduce/smoke/`:

| File | What it is |
|---|---|
| `reproduction_summary.md` | read this one |
| `run_manifest.json` | every step, its status, and why |
| `environment.json` | interpreter, compiler, platform, commit |
| `claim_matrix.json` | which published claim each step supports |
| `artifact_checksums.sha256` | SHA-256 of everything the run produced |

## What this software does

An Abaqus UMAT must return `DDSDDE`, the consistent material tangent. Writing it
by hand is laborious and error-prone; approximating it by finite differences
costs accuracy and robustness. UMAT-OTI rewrites the UMAT's Fortran so the
derivative is computed by order-truncated imaginary (OTI) arithmetic, which is
exact to machine precision and needs no step size.

The same machinery produces higher-order stress derivatives, the internal
Jacobian of a model's own local Newton solve, and sensitivities of stress and
state to material parameters.

Nothing is asserted without a check. Every derivative reported as verified was
compared against centred differences of the independently compiled original
subroutine, and the comparison distinguishes three outcomes: agreement,
disagreement, and *the reference could not resolve a value of this magnitude*.
The third is not counted as a pass.

## Where to go next

| You want to | Read |
|---|---|
| Reproduce a specific table or figure | [`docs/SOFTWAREX_REPRODUCTION.md`](docs/SOFTWAREX_REPRODUCTION.md) |
| Understand the whole interface | [`README.md`](README.md) |
| Transform your own UMAT | [`README.md`](README.md), then `examples/` |
| Know what has been verified, on what | [`paper_results/generality/generality_matrix.csv`](paper_results/generality/generality_matrix.csv) |
| Contribute | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

## Deeper reproductions

```bash
python -m umat_oti.reproduce --profile offline   # every redistributable test
python -m umat_oti.reproduce --profile paper     # regenerate the paper artefacts
```

`offline` needs no network and no Abaqus. `paper` regenerates the
parameter-sensitivity round, the internal-Jacobian round and the generality
matrix, and reports the Abaqus-paired table as blocked because it needs a
licensed installation.

Equivalent `make` targets exist: `make reproduce-smoke`, `make reproduce-offline`,
`make reproduce-paper`, `make test`, `make audit`.

## If something fails

The summary names the failing step and why. Common causes:

- **`gfortran` not on PATH** — every Fortran step reports
  `blocked_by_external_dependency` rather than failing. Install `gfortran`.
- **`abaqus` not installed** — expected. Paired validation is Tier C; the
  archived evidence in `paper_results/arc_791506/` is readable without it.
- **A derivative disagrees** — that is a real finding. Please open an issue with
  the contract and the source, and include `reproduce/*/run_manifest.json`.
