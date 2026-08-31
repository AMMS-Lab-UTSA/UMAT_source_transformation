# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Fortran real literals are atomic again in every rewrite path. A promoted
  variable named `D` matched the `D` inside `1.d-12` and `xtol = 1.d-12` was
  emitted as `XTOL_OTI = 1.D_OTI-12` ("Missing exponent in real number"). The
  masking mechanism that had fixed this class lived inside
  `umat_oti.transform.helper_lifting` and the main source rewrite did not go
  through it; it now lives in `umat_oti.fortran.literals` and is applied at
  every identifier substitution, every identifier scan that drives a rename,
  and the integer-to-double promoter. The promoter's `(?<![eEdD][+-])`
  lookbehind is replaced by the mask: it read spelling rather than position and
  also blocked a genuine integer factor in `D-6*Y`.

## [1.1.0] - 2026-08-21

Adds the SoftwareX unified-derivative model on top of the 1.0.0 tangent pipeline.

### Added
- Unified `DerivativeRequest` canonical model (`umat_oti.core.derivative_request`)
  with a normalizer that maps the compact `jacobian` contract, legacy
  `extra_jacobian_contracts` / `constitutive_jacobians` lists, and the `advanced`
  higher-order block onto one internal representation.
- Parameter-sensitivity material-point driver
  (`umat_oti.validation.parameter_sensitivity`) for `DSIGMA_DP` and
  `DSTATEV_DP` on the focused J2 SoftwareX case, with centered finite-difference
  verification that replays the full loading path per perturbation.
- Derivative manifest emitter (`umat_oti.reports.manifest`) writing a
  machine-readable JSON that records schema version, source SHA-256, entry
  routine, `NTENS`/`NSTATV`/`NPROPS`, parameter/state maps, direction ordering,
  recovery-factor convention, and array shapes.
- Corpus discovery/regression tool (`umat_oti.corpus`) with a GitHub-API
  candidate discovery step, deterministic content hashing, license
  classification, and a per-round metrics report. Offline-safe: network is
  gated behind an explicit `--allow-network` flag.
- Unified Abaqus validator entry point
  `python -m umat_oti.validation.run_suite --abaqus-command abaqus` that
  detects the environment and produces an explicit "skipped: reason" report
  when Abaqus or a Fortran compiler is missing.
- Shared UMAT-OTI / Residual Assembler material-driver contract
  (`umat_oti.reports.driver_contract`, schema
  `umat-oti-driver-contract/1.1`).

### Changed
- Version bumped to 1.1.0 across `pyproject.toml`, `src/umat_oti/__init__.py`,
  `CITATION.cff`, `codemeta.json`, `.zenodo.json` (previously inconsistent:
  `__init__.py` said 0.1.0, everything else said 1.0.0).
- Repository URLs updated from the stale personal fork
  `santiagarcia/UMAT_source_transformation` to the canonical organization
  repository `AMMS-Lab-UTSA/UMAT_source_transformation` in
  `pyproject.toml`, `CITATION.cff`, `codemeta.json`, and the README badge.

## [1.0.0] - 2026-07-10

First public release accompanying the SoftwareX submission and archived on
Zenodo.

### Added
- GPL-3.0-only `LICENSE.txt` (verbatim GNU General Public License v3).
- `COPYRIGHT` file recording UMAT-OTI authorship and third-party attribution.
- `CITATION.cff`, `codemeta.json`, and `.zenodo.json` software metadata for
  citation and Zenodo DOI minting.
- `THIRD_PARTY_NOTICES.md` documenting bundled OTIlib/pyoti templates and UMATs.
- `CONTRIBUTING.md` and this changelog.
- `tests/` suite (package import, CLI, and end-to-end transform smoke test).
- GitHub Actions CI workflow across Python 3.10–3.12 on Linux and Windows.
- Rewritten user manual (`docs/UMAT_Source_transformation_user_manual.docx`)
  covering the current implementation, utilities, and tutorials.

### Changed
- Reorganized the repository into a conventional layout for publication: the
  convenience entry scripts (`app.py`, `transform_from_json.py`,
  `run_json_pipeline.py`) moved under `scripts/`, the completed benchmark
  contracts moved from `json_files_completed/` to `benchmarks/`, and the user
  manual moved under `docs/`.
- Package renamed from `umat-oti-standalone` to `umat-oti`; expanded
  `pyproject.toml` metadata (authors, license, keywords, classifiers, URLs).
- Relicensed the combined UMAT-OTI distribution from BSD-3-Clause to
  **GPL-3.0-only** to preserve compatibility with the GPL-licensed OTIlib/pyoti
  template components that the project bundles and builds upon.
- Corrected the OTI expansion to "order-truncated imaginary" across all
  metadata, matching the upstream library and the accompanying paper.

### Removed
- The internal WIP helper scripts `engine_app.py`, `validate_all_local.py`, and
  `verify_abaqus_local.py`, which were development aids not needed for the
  public release.
- Proprietary Abaqus verification-manual UMATs (`umatmst3.f`, `umathrt2.f`,
  `umathrt2.inp`) and their JSON contracts, which cannot be redistributed under
  an open-source license.

## [0.1.0]

- Initial standalone bundle: compact-JSON UMAT transformation runtime, Streamlit
  GUI, CLI entry points, and the 19-case completed benchmark set.
