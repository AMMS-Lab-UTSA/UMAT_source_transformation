# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Rewritten user manual (`UMAT_Source_transformation_user_manual.docx`) covering
  the current implementation, utilities, and tutorials.

### Changed
- Package renamed from `umat-oti-standalone` to `umat-oti`; expanded
  `pyproject.toml` metadata (authors, license, keywords, classifiers, URLs).
- Relicensed the combined UMAT-OTI distribution from BSD-3-Clause to
  **GPL-3.0-only** to preserve compatibility with the GPL-licensed OTIlib/pyoti
  template components that the project bundles and builds upon.
- Corrected the OTI expansion to "order-truncated imaginary" across all
  metadata, matching the upstream library and the accompanying paper.

### Removed
- Proprietary Abaqus verification-manual UMATs (`umatmst3.f`, `umathrt2.f`,
  `umathrt2.inp`) and their JSON contracts, which cannot be redistributed under
  an open-source license.

## [0.1.0]

- Initial standalone bundle: compact-JSON UMAT transformation runtime, Streamlit
  GUI, CLI entry points, and the 19-case completed benchmark set.
