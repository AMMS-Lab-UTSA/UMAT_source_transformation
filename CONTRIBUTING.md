# Contributing to UMAT-OTI

This page is for anyone who wants to change UMAT-OTI or report a problem. It
covers the development setup, the tests and audits a change must pass, and how
to propose it.

## Development setup

```bash
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
cd UMAT_source_transformation
python -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[test]"
```

Python 3.10 or newer is required. Most of the suite also needs `gfortran` on
`PATH`, because it compiles the transformed and the original Fortran and
compares them.

## Running the tests

```bash
make test                         # the offline suite: no Abaqus, HPC or network
python -m pytest -q               # all but the whole-corpus Abaqus pass and browser tests
python -m pytest -q -m fortran    # only the tests that need a Fortran compiler
```

Tests are marked by what they need (`fortran`, `abaqus`, `arc`, `network`,
`gui`, and others; the full list is in `pyproject.toml`). A test whose
prerequisite is missing is skipped and names that prerequisite; a skip is
never counted as a pass. The browser tests run only with `-m gui` (see
[`docs/GUI.md`](docs/GUI.md)).

Before opening a pull request, also run the repository audits:

```bash
make audit                                    # repository standards
python tools/audit_documentation_commands.py  # documented commands and links resolve
```

## Coding conventions

- Keep changes focused: one logical change per pull request.
- Follow the existing module layout under `src/umat_oti/`.
- Every GUI screen and command-line entry point calls the same service
  function. Put new behaviour in the service, not in a front end.
- A derivative is verified only against an independent reference (centred
  differences of the separately compiled original). Do not use a model's own
  hand-written Jacobian, or the manuscript's numbers, as a reference.
- Do not commit generated run outputs (`umat_oti_workspace/`, `oti_results/`,
  `reproduce/`) or build products; `.gitignore` already excludes them.
- Do not name a machine-specific path (a home or scratch directory) in code,
  documentation or configuration; `make audit` rejects it.
- Do not add third-party or proprietary source files, for example UMATs shipped
  with a licensed Abaqus installation. See
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Submitting changes

1. Fork the repository and create a feature branch.
2. Make your change and add or update tests.
3. Make sure `make test` and `make audit` pass locally.
4. Open a pull request against `main` with a clear description.

## Reporting issues

Please open an issue at
<https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/issues> and include:

- what you ran (the JSON contract and the command),
- what you expected,
- what happened, including any report JSON written to the output directory.

A derivative that disagrees with the reference is a real finding. Please
include the contract and the source that produced it.

## License

By contributing, you agree that your contributions will be licensed under the
project's [GNU General Public License v3.0 (GPL-3.0-only)](LICENSE.txt).
