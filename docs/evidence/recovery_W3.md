# W3 Provider Recovery Evidence

Date: 2026-09-18. Worktree: `imq-umat-recovery`, integration recovery branch.
No branches, commits, pushes, edits to original development worktrees, Abaqus jobs,
or corpus runs were made by this workstream. Existing recovery edits outside W3
ownership were left untouched. This is **not clean-install verification**.

## Provenance and Implementation

Read the shared brief and branch audit before editing. Inspected
`documents_umat/main:oti_provider/umat_transform.py` and the read-only
`~/Documents/UMAT_source_transformation/oti_provider` source, built-J2 metadata,
and ABI assets. The old `_auto_infer` regex logic was not copied.

The implementation uses `GenericPSContract` and
`transform_umat_for_parameter_sensitivity`, with a default-preserving optional
`extra_directions` argument. The new provider reserves six additional first-order
directions for the local strain tangent. Each EVAL seeds incoming stress/state
parameter derivatives and extracts them after the full lifted update. MARCH
carries those derivatives across increments and resets local strain directions.
The original UMAT is separately compiled and bundled, unchanged.

Added only provider sources, one provider test module, the provider validation
module, these docs, and the owned transformer edit. No package/service/core
registration was attempted. Required lead registration:
`umat-oti-provider = "umat_oti.provider.build:main"` in project scripts.

## Environment and Commands

The dedicated verification terminal printed:

```text
W3 interpreter: /home/ammslab3/softwarex_work/.venv/bin/python
W3 import: /home/ammslab3/softwarex_work/imq-umat-recovery/src/umat_oti/__init__.py
```

Commands run with that interpreter and
`PYTHONPATH=/home/ammslab3/softwarex_work/imq-umat-recovery/src`:

```sh
python -m umat_oti.provider build \
  parameter_sensitivity/models/m3_j2/contract_v2.json \
  --out /tmp/imq-recovery-W3-j2
python -m umat_oti.validation.parameter_sensitivity_provider \
  parameter_sensitivity/models/m3_j2/contract_v2.json \
  --out /tmp/imq-recovery-W3-j2-verified
python -m umat_oti.provider.legacy_check \
  /tmp/imq-recovery-W3-j2-verified/verification.json \
  --repo ../Residual_Assembler
python -m pytest -q tests/test_provider_recovery.py \
  --junitxml=/tmp/imq-W3-provider-tests-final.xml
python -m pytest -q tests/test_provider_recovery.py \
  tests/test_generic_parameter_sensitivity_transform.py \
  tests/test_j2_parameter_sensitivity.py \
  tests/test_parameter_sensitivity_validation.py \
  --junitxml=/tmp/imq-W3-subsystem-tests.xml
python -m pytest -q \
  tests/test_provider_recovery.py::test_provider_verification_failure_is_machine_readable \
  --junitxml=/tmp/imq-W3-failure-report-test.xml
```

The `python` spelling above abbreviates the exact interpreter printed above;
the console-script editable install was not trusted. Builds use `gfortran`.
Several shared-terminal attempts were interrupted by unrelated terminal
activity and are NOT counted as completed checks. A dedicated persistent Python
terminal then launched these subprocesses with the correct worktree and import.

## Measured J2 Results

Object: `/tmp/imq-recovery-W3-j2-verified/umat_m3_j2_oti.obj`.
Contract: `/tmp/imq-recovery-W3-j2-verified/umat_m3_j2_oti.json`.
Machine-readable report: `/tmp/imq-recovery-W3-j2-verified/verification.json`.

```text
object SHA-256: a4b9ff747d41f0f4bf8b2a4211445b1e95b58e24d00bbf0d09a810c18b16d8d0
original source hash prefix: 9b779f0c6cadf9c4
properties: [210000.0, 0.3, 250.0, 2000.0]
branches: elastic, elastic, plastic, plastic, elastic, plastic, elastic
primal stress max absolute error: 5.684341886080802e-14
primal state max absolute error: 2.168404344971009e-19
finest-step stress-parameter scaled error: 2.495089817332248e-09
finest-step state-parameter scaled error: 4.78632426878973e-10
finest-step tangent scaled error: 2.2909886607673335e-11
stress FD plateau discrepancy: 1.994408000705079e-08
state FD plateau discrepancy: 7.515721719070879e-10
tangent FD plateau discrepancy: 2.7870660023874207e-10
reset-carry stress-derivative difference: 2720.125996569597
```

All three parameter and strain step sizes passed the `2e-6` scaled-error limit.
Worst error across the complete sweep was `2.493046730365579e-7` for parameter
derivatives. The exact scaling, path, and tolerances are documented in
[../PROVIDER.md](../PROVIDER.md) and recorded in the report. No tolerances were
relaxed to obtain a pass, and branch-crossing comparisons are rejected.

Counts: 49 EVAL primal values, 6 MARCH final stress values, 588 EVAL parameter
derivative comparisons (stress and state), 504 MARCH stress-parameter comparisons,
756 EVAL tangent comparisons, and 756 MARCH tangent comparisons. Thus **2,604
derivative comparisons** against independently compiled ORIGINAL-source FD,
in addition to primal parity. This is not comparison against the lifted core.

## Original Replay Consumption

The optional compatibility check exported unchanged Python sources from RA
`origin/cross-platform-hardening` commit
`bfde4d027652b1b60d306a42bdc6746f64ddb24f` into a temporary output directory.
The actual `PathMaterial` loaded the new object, passed its legacy 16-character
object-hash check, and reported `has_march=true`. Both `march_oti` and
`march_fast` were compared against centered FD through `march_regular`, which
calls the bundled ORIGINAL UMAT, not the transformed core.

Result: **868 derivative comparisons passed**, with scaled errors:
stress parameter `2.495089817332248e-9`, state parameter
`4.78632426878973e-10`, tangent `2.833701120261542e-10`. Full report:
`/tmp/imq-recovery-W3-j2-verified/legacy_verification.json`.

J2 public EVAL has 18 arguments including incoming DSIGMA_DP and DSTATEV_DP;
MARCH has 11 arguments. Exported symbols are `umat_`, `umat_oti_internal_`,
`umat_oti_eval_`, and `umat_oti_march_`. Physical state is exactly one slot;
derivatives are returned separately. Complete signatures and a consumption
example are in [../PROVIDER.md](../PROVIDER.md).

## Test Status and Limits

The first complete provider run had **15 passed, 0 failed, 0 skipped** in
19.491 seconds (JUnit above), including compiled J2 FD, CLI elastic build and
independent FD, metadata/symbols, repeatability, and ten unsupported-contract
cases. An initial elastic-validator failure was fixed by using the actual legacy
stateless convention (zero incoming stress, total strain), not by changing the
provider mathematics or tolerances. Two subsequent regressions cover reordered,
noncontiguous PROPS slots and rejecting nonfinite verification data.

The subsystem run completed with **52 passed, 0 failed, 0 skipped**, and one
existing CLI deprecation warning, in 49.24 seconds: 17 provider tests plus 35
existing generic/J2/parameter-validation tests. The additional failure-report
regression then completed with **1 passed** in 0.97 seconds. Thus all 18 provider
tests and 35 existing subsystem tests were executed successfully (53 distinct
tests across these two runs); no single 53-test run is implied. The latter test
proves a rejected contract returns exit code 2, writes a failed JSON report with
the diagnostic, and does not publish an object. No whole-suite run is claimed by
W3. Other workers' suite output is not provider evidence.

The bounded slice does not establish arbitrary material/context support,
finite-strain or higher-order providers, other compilers/platforms, C-ABI/resmat
packaging, shared C assets, services, GUI, or a clean installation. Legacy ABI
dimension/cutback failures use Fortran ERROR STOP and require caller-side
preflight/process isolation. No ledger completion outside this evidence is
claimed.