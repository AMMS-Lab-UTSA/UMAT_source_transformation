# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- BSD-3-Clause `LICENSE`.
- `CITATION.cff` and `codemeta.json` software metadata.
- `THIRD_PARTY_NOTICES.md` documenting bundled OTIlib/pyoti templates and UMATs.
- `CONTRIBUTING.md` and this changelog.
- `tests/` suite (package import, CLI, and end-to-end transform smoke test).
- GitHub Actions CI workflow across Python 3.10–3.12 on Linux and Windows.
- SoftwareX submission materials under `paper/`.

### Changed
- Package renamed from `umat-oti-standalone` to `umat-oti`; expanded
  `pyproject.toml` metadata (authors, license, keywords, classifiers, URLs).

### Removed
- Proprietary Abaqus verification-manual UMATs (`umatmst3.f`, `umathrt2.f`,
  `umathrt2.inp`) and their JSON contracts, which cannot be redistributed under
  an open-source license.

## [0.1.0]

- Initial standalone bundle: compact-JSON UMAT transformation runtime, Streamlit
  GUI, CLI entry points, and the 19-case completed benchmark set.
