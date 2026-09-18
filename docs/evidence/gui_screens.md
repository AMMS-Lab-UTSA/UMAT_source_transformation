# The GUI work stream: the slide-16/40 and slide-17/41 screens

Branch `dev/gui`, from the snapshot `f6fcc42` of the recovery line's
`imq-umat-recovery` working tree. This file lists **every edit to a file that
the recovery line or another front end also owns**, for the merge. New files follow.

## Edits to existing files

### `src/umat_oti/provider/build.py` (the recovery line's provider)

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

### Follow-up (same day): the lead's three items

**`src/umat_oti/validation/parameter_sensitivity_provider.py` (the recovery line's verifier).**

- `check_path()`: the path is read from the contract's
  `validation.check_path`, either explicit `increments` or
  `dstran_per_increment` with `n_increments`. A contract without it uses
  `J2_PATH`, as before.
- The fixed step ladder (`PARAMETER_STEPS`, `STRAIN_STEPS`) and the
  column-scaled `_relative_error` with its 1e-12 floor no longer decide
  anything. Every entry of DSIGMA_DP, DSTATEV_DP and DDSDDE, from EVAL and
  from MARCH, is judged by `_adjudicate` against centred differences of the
  ORIGINAL over `reference_resolution.DEFAULT_LADDER`. It uses
  `converged_value`, with an uncertainty of max(window spread, Richardson
  residual, next finer step's distance, eps·|response|/(2h)). The verdicts
  are agrees / consistent_with_zero / reference_unresolved / disagrees.
- Columns: `_column_verdict`. Verification fails on any disagreement. The
  report keeps `passed`, `props`, `path`, `branches`, the primal parity keys,
  `carry_reset_stress_derivative_difference` and `comparisons` (with new
  counts). It adds `verdict`, `criterion`, `arrays`, `columns`,
  `unresolved_columns`, `path_source`, `state_growth`, and
  `verification_entries.csv`.
- `FD_TOLERANCE` and `_relative_error` stay, because `legacy_check.py` uses
  them.

**`tests/test_provider_recovery.py` (the recovery line's test).**
`test_provider_j2_original_fd_and_carryover` asserted the old per-step counts.
It now asserts the new ones (628 verified, 240 zero, 0 unresolved, 0
disagreeing), that the verdict is `verified`, that every column agrees, and
that the path is the provider default. m3_j2 is otherwise unchanged: same
path, same branches, primal parity 5.7e-14 as before, still passes.

**`src/umat_oti/provider/build.py` (the recovery line's provider, second edit).**

- Every compile runs in the build directory on relative names, and the
  original source is compiled from a copy at `original/<name>`. The flags gain
  `-ffile-prefix-map=<build>=.`, which gfortran 9 does not apply to
  bounds-check messages; the relative names are what removes the paths.
- `ld -r` gets relative names too.
- The recorded `compile_command` no longer contains a path.
- New option `--abaqus-toolchain` (with `--abaqus`): `_abaqus_make` runs
  `abaqus make library=<name> directory=.` in `abaqus_make/` and publishes
  `<stem>-std.o` as the regular object. The contract's `regular_object`
  gains `toolchain` and `compiler`.

**`parameter_sensitivity/models/m6_fcc/contract_v2.json` is not edited.** Its
SHA-256 is pinned in `parameter_sensitivity/IMPORT_PROVENANCE.json`, so the
check path for m6_fcc is written into the contract the GUI or packager stages.
The named paths are in `collaborator.CHECK_PATHS`.

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
- `tests/gui/test_developer_screens.py` (AppTest, offline suite, 17
  tests), `tests/test_provider_regular_object.py` (9 tests),
  `tests/test_provider_check_path_and_verdicts.py` (17 tests),
  `tests/gui/test_developer_screens_browser.py` (`-m gui`, 5 tests),
  `tests/gui/tangent_reference.py`, `tests/gui/gui_helpers.py`,
  `tests/gui/conftest.py`.
- `docs/GUI.md`, and the screenshots `docs/screenshots/umat_constitutive_jacobian.png`,
  `umat_constitutive_jacobian_fcc.png`, `umat_parameter_sensitivities_j2.png`
  and `umat_parameter_sensitivities_fcc.png`.

## REAL_UMAT.obj in Abaqus

One Abaqus 2021.HF5 job, `gui_real`, in `../imq_abaqus/gui/abaqus_real/`:
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

## Follow-up measurements (2026-09-18)

- m3_j2 (shipped contract, J2 path): verified, 628 agree, 240 zero, 0
  unresolved, 0 disagree. Worst relative error 1.7e-10 (DSIGMA_DP), 9.5e-11
  (DSTATEV_DP), 4.8e-10 (DDSDDE). Primal 5.7e-14 (unchanged).
- m6_fcc at the slide-17 values, tension with shear: verified, all 10
  parameter columns agree in every array. 4,556 agree, 1,572 zero, 112
  unresolved, 0 disagree. Worst 5.7e-8 / 1.0e-9 / 3.5e-8. The slip
  resistances reach 2.52.
- m6_fcc, uniaxial strain (loading_paths.json default): C44 is unresolved in
  3 arrays (zero on that path) and 9 parameters agree.
- The criterion fails a provider whose DSIGMA_DP is off by 1e-5 relative, or
  whose single entry is off by 1e-3 (`test_a_wrong_derivative_is_caught`).
- Objects: no directory of the developer's appears in OTI_UMAT.obj,
  REAL_UMAT.obj or Mapping.json. Two builds in different directories are
  byte-identical, for both the gfortran objects and the `abaqus make` object.
- REAL_UMAT in Abaqus: see docs/GUI.md, "REAL_UMAT in Abaqus". The "buffer
  overflow detected" abort does not come from gfortran. It also happens with
  the `abaqus make` object and without LD_LIBRARY_PATH. Its stack ends in the
  Intel runtime bundled with Abaqus (`fname_from_piped_fd`), which formats the
  PID into 7 bytes, and this machine's PIDs are above 1,000,000. In a PID
  namespace, jobs `gui_clean` (`--abaqus-toolchain` object) and
  `gui_gfns` (gfortran object) ran clean (exit 0, "COMPLETED"), with
  results identical to the reference job.
  Abaqus jobs run by this agent: gui_real, gui_ifort, gui_noLD,
  gui_clean, gui_gfns, one at a time, all under
  `../imq_abaqus/gui/`.

## Consequence for the transform fingerprint

`transform_fingerprint()` hashes every `.py` file of the package outside
`abaqus`, `app`, `assist`, `contract`, `publication` and `store`. The edits to
`cli.py` and `provider/build.py`, and the new `services/jacobian_request.py`
and `provider/collaborator.py`, move it from `6aa20d22e37f14c9` (recorded in
`schemas/transform_generation.json`) to `debe10540f9eff1b`, and the
follow-up edits to the provider build and verifier move it again, to
`e39880419502a43d`. None of them
changes a generated transform: the four-field contract reaches the same
`run_transformation`, and the elastic output is byte-identical to the
hand-written contract's. But the hash is deliberately broad, so
`tests/test_contract_fixtures.py::test_the_recorded_generation_is_this_worktrees_actual_transform`
fails on this branch. Updating the generation file is a re-freeze, which is the
lead's lane (COORDINATION.md); this branch does not touch it. If the lead
wants the front ends out of the hash, `provider` and the CLI modules meet the
file's own exemption rule: nothing the transform runs imports them.

## Suites after the follow-up (2026-09-18)

- UMAT offline suite: 3 failed, 3368 passed, 125 skipped, 6 deselected. The 3
  failures are the two pre-existing documentation audits (absolute paths and
  stale links in the recovery line's recovery evidence) and the fingerprint record
  above.
- RA offline suite (`-m "not abaqus and not arc and not network"`): 56 failed,
  299 passed, 19 skipped, 1 deselected, 5 errors. These are the pre-existing
  fixture-fingerprint failures, the same as the baseline.
- UMAT `-m gui`: 5 passed. RA `-m gui`: 1 passed, against the real ODB with a
  provider built by this branch.

## Commands and results (2026-09-18)

Environment: `PYTHONPATH=<ra-gui>:<this worktree>/src:<otilib build_py311>`,
Python 3.11 venv, gfortran 9.4. Scratch output went to `../imq_abaqus/gui/`
or to pytest's temporary directories, never into the worktree.

```text
python -m pytest -q -p no:cacheprovider tests/gui/test_developer_screens.py \
  tests/test_provider_regular_object.py          -> 21 passed
python -m pytest -q -p no:cacheprovider -m gui tests/gui
                                                 -> 5 passed, 15 deselected (146 s)
```

The measured numbers (J2 transform and tangent against FD of the original;
the J2 provider at slide 41's values; the FCC build at slide 17's values and
its failed verification) are in [../GUI.md](../GUI.md).
