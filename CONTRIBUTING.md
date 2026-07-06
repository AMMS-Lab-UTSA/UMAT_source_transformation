# Contributing to UMAT-OTI

Thanks for your interest in contributing. This document describes how to set up
a development environment, run the tests, and propose changes.

## Development setup

```bash
git clone https://github.com/santiagarcia/UMAT_source_transformation.git
cd UMAT_source_transformation
python -m pip install -e ".[test]"
```

Python 3.10 or newer is required.

## Running the tests

```bash
python -m pytest
```

The default test suite does **not** require Abaqus or a Fortran compiler. It
covers package imports, the CLI entry points, and an end-to-end transformation
of the bundled minimal elasticity example.

## Coding conventions

- Keep changes focused; one logical change per pull request.
- Follow the existing module layout under `src/umat_oti/`.
- Do not commit generated run outputs (`umat_oti_workspace/`, `oti_results/`);
  these are ignored via `.gitignore`.
- Do not add third-party or proprietary source files (for example, UMATs shipped
  with a licensed Abaqus installation) to the repository. See
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Submitting changes

1. Fork the repository and create a feature branch.
2. Make your change and add or update tests.
3. Ensure `python -m pytest` passes locally.
4. Open a pull request against `main` with a clear description.

## Reporting issues

Please open an issue at
https://github.com/santiagarcia/UMAT_source_transformation/issues and include:

- what you ran (the JSON contract and command),
- what you expected,
- what happened (including any report JSON produced under the output directory).

## License

By contributing, you agree that your contributions will be licensed under the
project's [BSD-3-Clause license](LICENSE).
