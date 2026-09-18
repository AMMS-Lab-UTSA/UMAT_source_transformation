# Claude agent G: the slide-16/40 and slide-17/41 screens

Branch `claude/G-2026-09-18`, from the snapshot `f6fcc42` of Copilot's
`imq-umat-recovery` working tree. This file lists **every edit to a file that
Copilot or another front end also owns**, for the merge. New files follow.

## Edits to existing files

### `src/umat_oti/provider/build.py` (Copilot's provider)

Added `regular_object: str | None = None` to `build_provider` and the CLI
flag `--regular-object NAME.obj`, as the lead asked. Slide 11's developer
hands over REAL_UMAT.obj next to OTI_UMAT.obj. With the option, the object the
build already compiles from the ORIGINAL source for bundling
(`original_umat.o`, same compiler, same flags) is also published under that
name. The completed contract gains a `regular_object` block: file,
`sha256_full`, `source_sha256_full`, the compile command without machine
paths, and its role. Without the option the build and the contract are
unchanged (tested). The name is validated before anything is built.

### `src/umat_oti/cli.py`

New subcommand `umat-oti jacobian SOURCE --ntens N [--seed --response --target --order] --out DIR [--compile]`.
It calls the same function as the GUI screen
(`umat_oti.services.jacobian_request.run_jacobian_transform`), which calls
`run_transformation`.

### `src/umat_oti/app/streamlit_app.py`

Two tabs after "Start here": "Constitutive Jacobian" and "Parameter
Sensitivities". The later tab indices shifted by two, and the module
docstring lists the new tabs. Nothing else changed.

### `pyproject.toml`

One marker line: `gui`.

### `tests/test_frontend_equivalence.py`

Two entries in `DELEGATED_FRONT_ENDS`: the new screen must reach
`run_jacobian_transform`, and `services/jacobian_request.py` must reach
`run_transformation`.

### `docs/PROVIDER.md`

The limit bullet "No ... provider-build GUI entry is added" now says that the
screen and `--regular-object` were added later, and links docs/GUI.md.

## New files

- `src/umat_oti/services/jacobian_request.py`: the four-field contract
  (`replace: []`, so the transformer's anchor inference finds the tangent
  block), the run, and the preview.
- `src/umat_oti/provider/collaborator.py`: writes the provider contract from
  the table, runs `umat-oti-provider build --regular-object` and the verifier
  as subprocesses, ties the shipped object to the verified one, and writes
  REAL_UMAT.obj, OTI_UMAT.obj, Mapping.json and transform_report.txt. Run it
  with `python -m umat_oti.provider.collaborator`.
- `src/umat_oti/app/presentation_screens.py`: the two screens.
- `tests/gui/test_imqcam_developer_screens.py` (AppTest, offline suite, 16
  tests), `tests/test_provider_regular_object.py` (5 tests),
  `tests/gui/test_imqcam_developer_screens_browser.py` (`-m gui`, 5 tests),
  `tests/gui/tangent_reference.py`, `tests/gui/gui_helpers.py`,
  `tests/gui/conftest.py`.
- `docs/GUI.md`, and the screenshots `docs/screenshots/umat_constitutive_jacobian.png`,
  `umat_constitutive_jacobian_fcc.png`, `umat_parameter_sensitivities_j2.png`
  and `umat_parameter_sensitivities_fcc.png`.

## REAL_UMAT.obj in Abaqus

One Abaqus 2021.HF5 job, `claudeG_real`, in `../imq_abaqus/claude_G/abaqus_real/`:
the presentation example `Analysis.inp` with `user=REAL_UMAT.o`. That is the
package's REAL_UMAT.obj, SHA-256 53bac302..., copied to `.o` because Abaqus on
Linux rejects any other extension for a precompiled object. The job linked,
converged all four increments, and ended its .sta with "THE ANALYSIS HAS
COMPLETED SUCCESSFULLY". The strict export (`residual_core/io/abaqus_odb_export.py`
in the RA repository) of its ODB equals the reference `imqrp_j2` export (ifort,
same source; the Residual_Assembler fixture presentation_j2/fields.json) with max
|difference| 0 for U, RF, CF, S and SDV1 in all five frames. The process then
aborted with "buffer overflow detected", signal 6, exit code 1, which the
reference run did not do. This is recorded here and in docs/GUI.md, and is not
fixed.

## Consequence for the transform fingerprint

`transform_fingerprint()` hashes every `.py` file of the package outside
`abaqus`, `app`, `assist`, `contract`, `publication` and `store`. The edits to
`cli.py` and `provider/build.py`, and the new `services/jacobian_request.py`
and `provider/collaborator.py`, move it from `6aa20d22e37f14c9` (recorded in
`schemas/transform_generation.json`) to `debe10540f9eff1b`. None of them
changes a generated transform: the four-field contract reaches the same
`run_transformation`, and the elastic output is byte-identical to the
hand-written contract's. But the hash is deliberately broad, so
`tests/test_contract_fixtures.py::test_the_recorded_generation_is_this_worktrees_actual_transform`
fails on this branch. Updating the generation file is a re-freeze, which is the
lead's lane (COORDINATION.md); this branch does not touch it. If the lead
wants the front ends out of the hash, `provider` and the CLI modules meet the
file's own exemption rule: nothing the transform runs imports them.

## Commands and results (2026-09-18)

Environment: `PYTHONPATH=<claude-ra-G>:<this worktree>/src:<otilib build_py311>`,
Python 3.11 venv, gfortran 9.4. Scratch output went to `../imq_abaqus/claude_G/`
or to pytest's temporary directories, never into the worktree.

```text
python -m pytest -q -p no:cacheprovider tests/gui/test_imqcam_developer_screens.py \
  tests/test_provider_regular_object.py          -> 21 passed
python -m pytest -q -p no:cacheprovider -m gui tests/gui
                                                 -> 5 passed, 15 deselected (146 s)
```

The measured numbers (J2 transform and tangent against FD of the original;
the J2 provider at slide 41's values; the FCC build at slide 17's values and
its failed verification) are in [../GUI.md](../GUI.md).
