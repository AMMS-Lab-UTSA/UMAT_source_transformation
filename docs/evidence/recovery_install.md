# Recovery Wheel Installation Evidence

**Historical installation snapshot:** the two failures recorded below have a
subsequent [evidence repair record](recovery_evidence_refresh.md). These wheel
hashes still identify the earlier builds; they were not refreshed or promoted
to a committed clean-clone gate by that repair.

Date: 2026-09-18. Both recovery repositories remained on
`integration/imqcam-recovery-2026-09-18`; all pre-existing changes were preserved.
No commit, push, reset, branch change, subagent, old-worktree or parent VS Code
configuration edit. No Abaqus analysis job or whole-corpus run was launched.

**PASS: working-tree wheel installation and the bounded public J2
provider/presentation workflow. NOT a final-branch committed clean-clone gate.**
The full completion ledger is not declared complete. UMAT's offline suite still
has two real stale-evidence failures, described below.

## Install And Use

Healthy Python >=3.10 with `venv`, `ssl`, `ctypes`, plus compatible gfortran and
its runtime are required. From outside the checkout, using NEW directories:

```sh
python3.11 -I -m venv /tmp/imqr_umat_env
/tmp/imqr_umat_env/bin/python -I -m pip wheel --no-deps --wheel-dir /tmp/imqr_umat_wheels /path/to/imq-umat-recovery
/tmp/imqr_umat_env/bin/python -I -m pip install '/tmp/imqr_umat_wheels/umat_oti-1.1.0-py3-none-any.whl[test]'
/tmp/imqr_umat_env/bin/python -I -m pip check
/tmp/imqr_umat_env/bin/umat-oti-provider build /path/to/public_model/contract_v2.json --out /tmp/new_provider
```

No editable install or PYTHONPATH is needed. Network access is needed for build
and runtime dependency downloads unless a wheelhouse is supplied. No new extras
were necessary: `test` is declared; Streamlit is a declared runtime dependency;
publication plotting remains optional in `paper`. The public m3_j2 source and
contract are developer build inputs, not collaborator requirements. Give the
collaborator the generated object and completed mapping; do not send private
source. The provider console registration already present in the worktree was
verified without rewriting it.

Launch the existing installed GUI directly, with no checkout wrapper:

```sh
PY=/tmp/imqr_umat_env/bin/python
APP=$("$PY" -I -c 'import importlib.util; print(importlib.util.find_spec("umat_oti.app.streamlit_app").origin)')
"$PY" -I -m streamlit run "$APP" --server.address=127.0.0.1 --server.port=8502
```

Use a free port. This is the existing UMAT GUI, not a new provider-build GUI.
Repository example/corpus discovery is not proven by launching the installed app.

## Exact Joint Gate Command

```sh
cd /home/ammslab3/softwarex_work/imq-umat-recovery
/home/ammslab3/softwarex_work/.venv/bin/python scripts/clean_install_gate.py \
  --ra-repo /home/ammslab3/softwarex_work/imq-ra-recovery \
  --python /home/ammslab3/anaconda3/bin/python3.11 \
  --odb /home/ammslab3/softwarex_work/imq_abaqus/recovery_presentation/imqrp_reference/collaborator/Analysis.odb \
  --work /tmp/imqr_install_20260918_03
```

For a repeat choose a NEW work path or omit `--work`. This script delegates to
the companion RA gate, avoiding a second implementation. Both worktree branches
are checked. The caller needs both source checkouts to build the wheels, but
application commands run outside them using only installed packages and copied
public inputs. Failures stay nonzero; there is no mock ODB/calculation fallback.

The shared venv bootstraps the script. The selected standalone base Python was
verified at `/home/ammslab3/anaconda3/bin/python3.11` (3.11.7). The old warning
was rechecked: `/usr/local/bin/python3.11` lacks `_ctypes`; `/usr/bin/python3`
is 3.8.10 and too old. Neither was silently used for the new environment.

Exact install after wheel builds and new-venv pip upgrade:

```sh
/tmp/imqr_install_20260918_03/env/bin/python -I -m pip install '/tmp/imqr_install_20260918_03/wheels/residual_assembler-0.1.0-py3-none-any.whl[gui,test,yaml]' '/tmp/imqr_install_20260918_03/wheels/umat_oti-1.1.0-py3-none-any.whl[test]'
/tmp/imqr_install_20260918_03/env/bin/python -I -m pip check
```

`pip check` exited 0 with no broken requirements. RA's historical `bridge`
extra is not selected: the companion is the locally built wheel. The gate strips
development import paths and pip overrides, disables user-site and pip config,
and uses scratch HOME `/tmp/imqr_install_20260918_03/home`. It rejects editable
distributions and asserts no recovery source directory appears on sys.path.

Installed versions: Python 3.11.7, pip 26.2.1, umat-oti 1.1.0,
residual-assembler 0.1.0, numpy 2.4.6, pandas 3.0.6, streamlit 1.64.0,
sympy 1.14.0, pytest 9.1.1, PyYAML 6.0.3; gfortran 9.4.0.
Full transitive versions, commands, cwd, return codes, resource paths and input
hashes: `/tmp/imqr_install_20260918_03/report.json`; command logs under `logs/`.
Dependencies are recorded, not locked to guarantee future byte-identical builds.

Wheel SHA-256:

| Wheel | SHA-256 |
| --- | --- |
| umat_oti-1.1.0-py3-none-any.whl | ca067f9e762359639d573efd93f533e0095c167eff4f53ab3ac8691d55ca6881 |
| residual_assembler-0.1.0-py3-none-any.whl | 4eca0c2c2201fb707b7423c124344f40b29c84e57c75c9b3bd0c0c3f6770a5fd |

All checked origins are under
`/tmp/imqr_install_20260918_03/env/lib/python3.11/site-packages/`, including
`umat_oti/__init__.py`, `umat_oti/provider/build.py`,
`umat_oti/app/streamlit_app.py`, `residual_core/__init__.py`,
`residual_core/replay/presentation.py`, `residual_core/app/streamlit_app.py`,
and `resasm_user/__init__.py`. Required OTI support sources/templates, contract
schemas/lock, RA replay ABI/version assets, manifest and Fortran driver/stubs
were asserted present. A namespace-resource probe bug in first run `_01` was
fixed and immediately checked against its existing wheel; `_02` and strengthened
`_03` passed. Failed evidence was retained rather than overwritten.

## Presentation And GUI Results

Installed `umat-oti-provider build` compiled copied public m3_j2 inputs with
gfortran. Installed `resasm request` consumed exactly `Analysis.inp`,
`Analysis.odb`, `OTI_UMAT.obj`, `sensitivity_request.json`, plus the automatically
discovered generated `Mapping.json`. It returned `sensitivity_results.json`,
`sensitivity_tables.csv`, `run_report.txt`; four increments replayed, four scalar
outputs, ordinary `verified=false`. No private source was given to that command.

A second installed-console execution under a Python material-source-read
denial hook produced byte-identical public outputs. Only its exact generated
link shim was exempt. This is an audit check, not an OS sandbox for native
compiler/Abaqus processes. Independent uniaxial J2 dU1 errors: E `1.6568627353483993e-7`,
SIGY0 `8.673617379884035e-16`, H `8.839354487082118e-9`, all below `2e-5`;
zero-reference nu derivative below `1e-8` absolute. Tolerances were unchanged.

Both installed GUIs rendered in Streamlit AppTest without exceptions. Real
servers reached HTTP readiness and were stopped/waited by owned PID: RA 1065394
(44163), UMAT 1065413 (33311). No server remains running. This checks installed
rendering/launch, not installed-browser downloads.

The ODB is the prior genuine Abaqus 2021 reference, not fabricated and not tracked
in either repository: SHA-256
`54745b97b515de159c3251e8a3ba0ed89ea1c65452e388ef34c8c81794e3b736`.
Licensed `abaqus python` with odbAccess extracts it; the gate launches no solve.
The exact three-file interface and physics limits remain in RA's
[presentation interface](../../../Residual_Assembler/docs/PRESENTATION_INTERFACE.md)
and [presentation evidence](../../../Residual_Assembler/docs/evidence/recovery_presentation.md).

## Tests And Unresolved Evidence

| Check | Passed | Failed | Skipped | Deselected |
| --- | ---: | ---: | ---: | ---: |
| New gate tests across both repositories | 8 | 0 | 0 | 0 |
| RA relevant offline suite | 390 | 0 | 11 | 0 |
| UMAT relevant offline suite | 3316 | 2 | 125 | 5 |

RA took 53.39 s; UMAT 495.26 s. Source-tree suites used the shared development
venv and do not count as wheel-isolation evidence. Existing unavailable-artifact
skips were not altered. JUnit: `.pytest_cache/recovery_install_offline.xml` in
each repository. UMAT command:

Post-guide checks: `tests/test_repository_standards.py` plus
`tests/test_clean_install_gate.py` passed 10/10;
`tools/audit_documentation_commands.py --json` returned `{"problems": []}`.
Editor diagnostics reported no errors in both gate scripts and their new tests.

```sh
cd /home/ammslab3/softwarex_work/imq-umat-recovery
env PYTHONPATH=/home/ammslab3/softwarex_work/imq-umat-recovery/src /home/ammslab3/softwarex_work/.venv/bin/python -m pytest -q -ra -m 'not abaqus and not arc and not network and not corpus_pass' --junitxml=.pytest_cache/recovery_install_offline.xml
```

Two unchanged failures:

1. `tests/test_contract_fixtures.py::test_the_recorded_generation_is_this_worktrees_actual_transform`:
   retained `94a92c01814f107a` versus actual `6aa20d22e37f14c9`. This is the next
   highest-priority real failure: coordinate shared generation/lock changes and
   genuine artifact re-freezing or retirement. Do not merely edit a fingerprint
   to obtain green tests.
2. `tests/test_the_two_denominators_stay_apart.py::test_every_terminal_state_in_the_report_is_marked_external_or_internal`:
   retained report says EXTERNAL for `arguments_diverged_before_the_routine`,
   registry expects INTERNAL. Reconcile/regenerate genuine evidence.

External dependencies remain real: matching ODB, licensed Abaqus odbAccess,
binary-compatible gfortran/runtime and healthy Python. Missing frozen corpus
data accounts for many existing skips. Final clean-clone verification awaits
authorized commits of both revisions. Generic UMAT/FCC/full-size models, OTILib
binary packaging, publication/corpus reproduction and whole-ledger completion
are not established by this gate.