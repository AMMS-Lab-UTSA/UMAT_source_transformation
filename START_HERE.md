# Start here

This page is for anyone meeting UMAT-OTI for the first time, including
reviewers: in about five minutes it shows whether the software does what it
says, and then where to read next.

## Five-minute check

```bash
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
cd UMAT_source_transformation
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
python -m umat_oti.reproduce --profile smoke
```

You need Python 3.10 or newer and `gfortran`. You do not need Abaqus, a
network connection or a licence.

The smoke profile takes a few seconds. It transforms one UMAT (the J2 model
`m3_j2`) and compiles it. It also compiles the *original* subroutine
separately and runs both over a strain path. It then checks that the
derivatives from the transformed build agree with centred differences of the
original, and exits non-zero if they do not.

It writes five files into `reproduce/smoke/`:

| File | What it is |
|---|---|
| `reproduction_summary.md` | the summary to read first |
| `run_manifest.json` | every step, its status, and the reason for it |
| `environment.json` | interpreter, compiler, platform, commit |
| `claim_matrix.json` | which published claim each step supports |
| `artifact_checksums.sha256` | SHA-256 of everything the run produced |

## What this software does

An Abaqus UMAT must return `DDSDDE`, the consistent material tangent. Deriving
it by hand is slow and easy to get wrong. Approximating it by finite differences
costs accuracy and robustness. UMAT-OTI rewrites the UMAT's Fortran so the
derivative is computed with order-truncated imaginary (OTI) numbers. The result
is exact to machine precision and needs no step size.

The same machinery produces:

- higher-order stress derivatives;
- the internal Jacobian of a model's own local Newton solve;
- sensitivities of stress and state to material parameters, packaged as a
  compiled provider (`OTI_UMAT.obj` and `Mapping.json`, optionally with
  `REAL_UMAT.obj`) for the companion Residual Assembler.

Every derivative reported as verified was compared with centred differences of
the independently compiled original subroutine. The comparison has three
outcomes: agreement, disagreement, and *the reference could not resolve a value
of this size*. The third outcome is never counted as a pass.

## Where to go next

| You want to | Read |
|---|---|
| See every command and interface | [`README.md`](README.md), then [`docs/USAGE_REPORT.md`](docs/USAGE_REPORT.md) |
| Transform your own UMAT | [`new_user_umat_starter/README.md`](new_user_umat_starter/README.md) and the contracts in `examples/` |
| Build a compiled provider for the Residual Assembler | [`docs/PROVIDER.md`](docs/PROVIDER.md) |
| Use the graphical interface | [`docs/GUI.md`](docs/GUI.md) |
| Reproduce a specific table or figure | [`docs/SOFTWAREX_REPRODUCTION.md`](docs/SOFTWAREX_REPRODUCTION.md) |
| Know what has been verified, and how | [`docs/VERIFICATION_RECORD.md`](docs/VERIFICATION_RECORD.md) and [`paper_results/generality/generality_matrix.csv`](paper_results/generality/generality_matrix.csv) |
| See how third-party UMATs are verified | [`docs/CORPUS_VERIFICATION.md`](docs/CORPUS_VERIFICATION.md) |
| Contribute | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

## Longer reproductions

```bash
python -m umat_oti.reproduce --profile offline   # every redistributable test
python -m umat_oti.reproduce --profile paper     # regenerate the paper artefacts
```

`offline` needs no network and no Abaqus. `paper` regenerates the
parameter-sensitivity round, the internal-Jacobian round and the generality
matrix. It reports the Abaqus-paired table as blocked, because that table needs
a licensed Abaqus installation.

The same runs are available as `make` targets: `make reproduce-smoke`,
`make reproduce-offline`, `make reproduce-paper`, `make test` and `make audit`.

## If something fails

The summary names the failing step and the reason. Common causes:

- **`gfortran` is not on `PATH`.** Every Fortran step reports
  `blocked_by_external_dependency` rather than failing. Install `gfortran`.
- **`abaqus` is not installed.** This is expected. Paired Abaqus validation is
  Tier C (see [`docs/SOFTWAREX_REPRODUCTION.md`](docs/SOFTWAREX_REPRODUCTION.md)),
  and the archived evidence in `paper_results/arc_791506/` can be read without
  it.
- **A derivative disagrees.** That is a real finding. Please open an issue with
  the contract and the source, and attach `reproduce/*/run_manifest.json`.
