# UMAT-OTI

**Current user entry point:** [verified usage report](docs/USAGE_REPORT.md)
contains installation, captured help, five reproduced example invocations,
GUI limits and the exact artifact-only presentation connection.
[Requirement audit](docs/COMPLETION_LEDGER.md): 104 bounded implemented,
159 partial, 11 unestablished; **0 final clean-install complete, 274 outstanding**.

**Recovery evidence status (2026-09-18):** retained corpus, collection and
fixture results are historical, not current capability claims. The current
generation and bounded executable J2 evidence are separated in
[the evidence refresh record](docs/evidence/recovery_evidence_refresh.md).
No whole-corpus rerun or committed clean-clone gate is claimed.

[![CI](https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/actions/workflows/ci.yml/badge.svg)](https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/actions/workflows/ci.yml)
[![License: GPL-3.0-only](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE.txt)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

**UMAT-OTI** transforms Abaqus user-material subroutine (UMAT) Fortran source so
that the consistent material tangent (`DDSDDE`) is computed by order-truncated
imaginary (OTI) automatic differentiation instead of hand-coded or
finite-difference derivatives. The transformation is driven by a compact JSON
contract.

This directory is a standalone source bundle that contains the full UMAT-OTI
transformation runtime plus the files a new user needs to try the workflow on
their own UMAT.

It is meant to be copied, zipped, or shared as its own folder.

Earlier compact-JSON smoke and 19-case benchmark results are historical.
Current bounded provider/local-Jacobian results are recorded in the usage report;
they do not establish a current whole-benchmark or corpus pass.

## What Is Included

- `src/umat_oti/`: the full transformation runtime code.
- `scripts/`: convenience entry scripts (`app.py` GUI launcher, `transform_from_json.py`, `run_json_pipeline.py`).
- `templates/`: JSON contract templates to copy and edit.
- `examples/`: example JSON contracts that already work.
- `user_jsons/`: suggested place to keep your own JSON contracts.
- `UMATs/`: bundled sample UMAT source files used by the example configs.
- `benchmarks/`: completed compact JSON contracts (the 19-case benchmark set).
- `json_files/`: general JSON-contract directory for user-authored configs.
- `new_user_umat_starter/`: starter docs, templates, examples, and helper scripts.
- `tools/run_completed_json_batch.py`: batch transform runner.
- `docs/`: user manual and design notes.
- `src/umat_oti/oti/support/pyoti_templates/`: bundled pyoti template files used to generate complete OTI Fortran modules inside the standalone package.

## Intended Usage Model

Use this bundle from source.

That means:

1. copy or clone this folder to a machine,
2. change into this folder,
3. optionally install it in editable mode,
4. run the GUI, starter scripts, or CLI from this folder.

The runtime currently relies on this source-tree layout for paths such as
`benchmarks/`, `UMATs/`, and `umat_oti_workspace/`.

## Install

From this directory:

```bash
python3 -m pip install -e .
```

On ARC, use `/usr/bin/python3.12` instead of the default `python3`.

You do not need to install the package just to run the bundled starter scripts.
They work directly from this folder.

## Fastest Way For A New User

Use the root-level files first:

1. Copy a JSON template from `templates/` into `user_jsons/` and edit it.
2. Edit the settings at the top of `scripts/run_json_pipeline.py`.
3. Run `/usr/bin/python3.12 scripts/run_json_pipeline.py`.

The runner defaults to `examples/`, so if you run it without edits it executes
the bundled known-good example JSONs first.

`scripts/run_json_pipeline.py` now defaults to `RUN_VALIDATION = False`, so a new user
can test the transformation path without Abaqus.

Set `RUN_VALIDATION = True` only on a machine where Abaqus is installed and the
module/load environment is already configured.

If you want one single JSON from the command line instead, use:

```bash
/usr/bin/python3.12 scripts/transform_from_json.py user_jsons/my_new_umat.json --out umat_oti_workspace/my_new_umat
```

If you want the deeper helper scripts and reference material, see `new_user_umat_starter/README.md`.

## GUI

Run the GUI from this directory with:

```bash
streamlit run scripts/app.py
```

The GUI can load bundled contracts from `benchmarks/` or an uploaded
JSON file.

## CLI

The package exposes:

```bash
umat-oti transform path/to/umat.for --out generated/case_name
umat-oti-config --config json_files/my_new_umat.json --out umat_oti_workspace/my_new_umat
umat-oti-batch --config-dir benchmarks --batch-dir umat_oti_workspace/completed_json_batch
```

Without installation, the same JSON-contract path is:

```bash
PYTHONPATH=src /usr/bin/python3.12 -m umat_oti.cli_json --config json_files/my_new_umat.json --out umat_oti_workspace/my_new_umat
```

The top-level wrapper script above is just a simpler front door for the same transformation path.

You can also run the bundled script directly:

```bash
/usr/bin/python3.12 tools/run_completed_json_batch.py --config-dir benchmarks --batch-dir umat_oti_workspace/completed_json_batch
```

## Recommended First Files To Read

- `new_user_umat_starter/README.md`
- `new_user_umat_starter/JSON_REFERENCE.md`
- `new_user_umat_starter/TROUBLESHOOTING.md`
- `examples/elastic_minimal.json`

## Known Limits

- The compact JSON layer is working and the completed config set is in the simple top-level format.
- The standalone bundle transforms the current 19 completed benchmark configs successfully.
- The standalone no-argument runner now also supports original-vs-transformed validation using the bundled pyoti templates and Abaqus validation pipeline.
- The bundle now includes the pyoti template files needed for complete OTI module generation, so the minimal-template fallback warning should not appear in normal runs.

## Verifying a corpus

The transformation is one half. The other is establishing, with evidence,
which of a directory of downloaded UMATs actually work -- and naming, for the
rest, whose move it is. That loop is described in
[`docs/CORPUS_VERIFICATION.md`](docs/CORPUS_VERIFICATION.md):

```bash
make batch-transform                    # convert every discovered source
make batch-abaqus                       # run both builds, compare, difference
make corpus-registry TRANSFORM_REPORT=... ABAQUS_RESULTS=...
make umat-regress                       # replay the frozen experiments
```

A material is verified when the original ran in Abaqus, the converted build ran
on the same deck, their stress and state histories agreed over the whole path,
the loading activated what the material actually does, and the OTI tangent
agreed with a converged finite difference of the original at several smooth
states. Compiling is not working and running is not verified.

The interface reads the same records: `streamlit run scripts/app.py`, tab 6.

## Testing

The test suite does not require Abaqus or a Fortran compiler:

```bash
python -m pip install -e ".[test]"
python -m pytest
```

## Citing

If you use UMAT-OTI in academic work, please cite it using the metadata in
[CITATION.cff](CITATION.cff). Publication details for the accompanying software
paper will be added here once available.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

UMAT-OTI is released under the [GNU General Public License v3.0 (GPL-3.0-only)](LICENSE.txt).

This project bundles and builds upon template code from the GPL-licensed
OTIlib / pyoti library by Mauricio Aristizabal
(https://github.com/mauriaristi/otilib). Because the combined work incorporates
GPL-licensed components, UMAT-OTI as a whole is distributed under the GPL-3.0.
See [COPYRIGHT](COPYRIGHT) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for authorship and attribution details.

Bundled and third-party components are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Note that proprietary Abaqus
verification-manual UMATs are **not** included in this repository and must be
obtained from a licensed Abaqus installation.