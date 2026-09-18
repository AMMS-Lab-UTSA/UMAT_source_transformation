# W4 Recovery: Suite Health

**Historical suite snapshot:** the two blockers recorded here are addressed in
[the subsequent evidence refresh](recovery_evidence_refresh.md). The original
test counts and observations below remain a record of this earlier slice.

Date: 2026-09-18. Checkout: `$HOME/softwarex_work/imq-umat-recovery`.
Branch: `integration/recovery-2026-09-18`, base `d34c7ff`.
This is shared-environment offline evidence, **not clean-install PASS**.

## Scope and Changes

Read the shared brief and branch implementation audit. No commits, pushes,
branch changes, subagents, fetches, Abaqus jobs, or whole-corpus passes.
Original the integration line checkout untouched. No edits to the other worker's provider,
parameter transform, Fortran emitters, parameter validation, provider tests,
or pyproject. Lead-owned contracts and published corpus artifacts are unchanged.

- `tests/test_the_crystal_plasticity_trio_lost_one_state_slot.py`: recovered
  the content of inspected commit `4c65cee` using apply_patch, not cherry-pick.
  External pass9/cache resolution now happens in fixtures, not during import.
  Added regressions for missing/present paths, missing/present records, and
  malformed JSON. Existing evidence skips, assertions and tolerances remain.
- `tests/test_the_services_are_the_one_place_a_verdict_is_decided.py`: the two
  denominator tests now use synthetic JSONL with the same exact 237/55/42/13
  expectations and the real services. Synthetic records do not establish real
  corpus verification. Added two missing-file refusal regressions; no new skips.
  Inspected portability history `b7a4677` before editing.
- `tools/audit_documentation_commands.py`: historical cross-repository inline
  inventory paths in the branch audit are not current-local file references.
  Its commands and Markdown links are still checked. Inspected `b0d7d01` first.
- `tests/test_repository_standards.py`: a negative regression proves that the
  historical inventory's broken link/command and a current document's missing
  inline path are all still rejected.

## Commands and Results

All Python checks use the explicit shared interpreter and recovery source:

```bash
WORKSPACE="$HOME/softwarex_work"
RECOVERY="$WORKSPACE/imq-umat-recovery"
PYTHON="$WORKSPACE/.venv/bin/python"
export PYTHONPATH="$RECOVERY/src"
OFFLINE='not abaqus and not arc and not network and not corpus_pass'
cd "$RECOVERY"
"$PYTHON" -c 'import sys, umat_oti; print(sys.executable); print(umat_oti.__file__)'
```

Observed interpreter: `$WORKSPACE/.venv/bin/python`; package:
`$RECOVERY/src/umat_oti/__init__.py` (also checked with a runtime assertion).
Editor-selected interpreter was not established; runtime verification is explicit.

The finished the integration line baseline log was read from scratchpad `w4/suite_run1.log`
in session `91433a98-ad23-4631-8751-56d6f4ba5787`. Its five actual failures were
reproduced together: **5 failed in 0.82s**. The historical baseline total was
3291 passed, 125 skipped, 5 failed, 1 deselected, 6 warnings in 423.86s.

| Check | Result |
| --- | --- |
| Immediate collection test after recovery | 1 passed, 12 skipped (0.09s) |
| Denominator and missing-file regressions | 4 passed, 18 deselected (0.23s) |
| Documentation failure and negative regression | 2 passed, 6 deselected (0.16s) |
| Collection module with new evidence regressions | 4 passed, 12 skipped (0.07s) |
| Collection module after final indentation correction | 4 passed, 12 skipped (0.08s) |
| Relevant subsystem, including both unresolved guards | 84 passed, 19 skipped, 2 failed, 1 warning (4.84s) |
| First complete-suite attempt, interrupted | Partial only: 390 passed, 29 skipped (17.216s JUnit time); not a suite result |
| Complete offline suite, isolated retry | **3296 passed, 125 skipped, 2 failed, 5 deselected, 6 warnings in 444.17s (7m24s)** |

```bash
"$PYTHON" -m pytest -q -rs tests/test_the_crystal_plasticity_trio_lost_one_state_slot.py -m "$OFFLINE"
"$PYTHON" -m pytest -q tests/test_the_services_are_the_one_place_a_verdict_is_decided.py -k 'denominator or summary_reports or missing_results' -m "$OFFLINE"
"$PYTHON" -m pytest -q tests/test_repository_standards.py -k 'documented_commands or historical_inventory' -m "$OFFLINE"
"$PYTHON" -m pytest -q tests/test_the_services_are_the_one_place_a_verdict_is_decided.py tests/test_the_crystal_plasticity_trio_lost_one_state_slot.py tests/test_repository_standards.py tests/test_contract_fixtures.py tests/test_contract_terminal_states.py tests/test_a_stage_the_registry_cannot_translate_raises.py tests/test_the_two_denominators_stay_apart.py -m "$OFFLINE" --junitxml=/tmp/recovery_W4_subsystem.xml
"$PYTHON" -m pytest -q -m "$OFFLINE" --junitxml=/tmp/recovery_W4_offline.xml
setsid --wait env --chdir="$RECOVERY" PYTHONPATH="$RECOVERY/src" "$PYTHON" -m pytest -q -m "$OFFLINE" --junitxml=/tmp/recovery_W4_offline_complete.xml > /tmp/recovery_W4_offline_complete.log 2>&1
```

Logs: `/tmp/recovery_W4_collection.log`, `/tmp/recovery_W4_denominators.log`,
`/tmp/recovery_W4_documentation.log`, `/tmp/recovery_W4_subsystem.log`,
`/tmp/recovery_W4_collection_final.log`, `/tmp/recovery_W4_offline.log`, and
`/tmp/recovery_W4_offline_complete.log`. Early output was captured with tee;
use pytest's summary/JUnit, not tee's exit status, to determine success.
Shared terminal output occasionally belonged to another worker; such output
was not accepted as W4 validation. Absolute test paths and `env --chdir` were
used subsequently. The first full-suite attempt was interrupted, not passed.
The retry used a separate process session and direct log capture: its launcher
was interrupted with exit 130, but the isolated pytest process was confirmed
running independently (PID 919873). Exit 130 is not a pytest test result.
The isolated process then completed: JUnit reports 3423 executed tests,
2 failures, 125 skips, and zero errors. Exactly one complete offline run
finished; the preceding interrupted attempt is recorded above, not counted
as a completed run. No additional full-suite rerun was made.

The six warnings are four existing deprecated transform-entrypoint calls and
two constrained-layout warnings from the figure-size rejection test. The five
deselections are the tests excluded by the offline marker expression.
The full run included the shared checkout's sources as they stood during
execution, not an immutable clean-install snapshot. The other worker continued
to change fingerprinted provider/transform sources during this slice.

## Remaining Blockers

1. `test_contract_fixtures.py::test_the_recorded_generation_is_this_worktrees_actual_transform`:
   recorded generation `94a92c01814f107a` does not match current transform.
   Observed `4932351c15488137` at initial reproduction and `1a11b5b85fed956c`
   at subsystem validation as the other worker changed fingerprinted sources.
  The completed offline run observed `2a0f3e7719b0385a`.
   Inspected `d3bffa2`: prior recovery refroze evidence before updating the
   contract/lock, rather than asserting currency by changing a number.
   Requires lead-owned contract and evidence work after source stabilization.
2. `test_the_two_denominators_stay_apart.py::test_every_terminal_state_in_the_report_is_marked_external_or_internal`:
   the published report still calls `arguments_diverged_before_the_routine`
   EXTERNAL. Inspected `bcc8605`: code intentionally makes it INTERNAL because
   the paired solver arguments depend on each build's earlier outputs.
   The correct classifier was not reverted to match stale published evidence.
   Refreshing `paper_results/corpus/**` belongs to the lead.

Lead request: `../imq_queue/W4_recovery_suite_health_blockers.json`.

The subsystem's 19 skips are external evidence, not passes: 12 missing pass9
records, 4 pass11 service evidence checks, and 3 frozen-store contract checks.
The complete suite's 125 skips comprise 81 missing pass11 evidence checks,
26 missing pass9 checks, 16 missing pass10 checks, one check with no older
contract minor version to read at version 3.0.0, and one published manifest
that cached nothing. Missing evidence was not downloaded or reconstructed.
The collection regressions exercise the missing conditions as passing tests
using pytest.raises, not by adding skip decorators. Available synthetic data
and corrupt data take their normal execution/error paths. No tests were deleted,
no tolerance was weakened, and no skip/xfail was added to hide a failure.

No completion-ledger capability or clean-install claim is made by this slice.
All edited Python files had no editor-reported diagnostics, and git diff
--check reported no whitespace errors. Both remaining failure guards were
preserved, with the lead request naming the required authorized follow-up.