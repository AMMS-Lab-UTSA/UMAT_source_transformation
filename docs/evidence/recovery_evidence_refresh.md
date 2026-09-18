# Recovery Evidence Refresh

Date: 2026-09-18. Scope: the two reported UMAT offline failures and necessary
RA shared-contract synchronization. No commits, pushes, branch changes,
subagents, Abaqus solves or whole-corpus jobs. Pre-existing work was preserved.
This is working-tree evidence, NOT a committed clean-clone gate or a completed
ledger. Earlier wheel hashes in recovery_install.md identify earlier builds.

## Before And After

The exact two tests reproduced as **2 failed in 0.28s** before edits:
`test_the_recorded_generation_is_this_worktrees_actual_transform` recorded
`94a92c01814f107a` versus actual `6aa20d22e37f14c9`;
`test_every_terminal_state_in_the_report_is_marked_external_or_internal`
found `arguments_diverged_before_the_routine` labelled EXTERNAL.

Read shared brief, branch audit, both installation records and history:
`d3bffa2` genuinely reran pass12 before changing its generation; `bcc8605`
made divergence INTERNAL because solver arguments depend on each build's own
earlier outputs. Its retained report had not been regenerated.

The generation now records measured code `6aa20d22e37f14c9`, with explicit
historical retirement, not a claim that old results ran under new code.
`umat_oti.store.transform_fingerprint()` hashes names and bytes of .py/.f90/.f/
.for/.inc files, excluding abaqus/app/assist/contract/publication/store as
specified by NOT_TRANSFORM_CODE. No fingerprint exclusions were changed.
Contract version remains 3.0.0. `write_lock()` generated combined digest
`e326b594c40f95ebd1aa3ac7455d2060035b4d5faac45fafa97591bcc239a10e`.
Only generation and lock were copied byte-for-byte to RA's schemas directory,
following the generation document's existing how_to_update procedure.

The canonical registry builder now accepts `--refresh-retained`: Record,
kind_of, summarise and markdown regenerate all three published formats from
retained records. Exactly three record kinds change; all other record fields,
numeric observations, source/evidence references, original generated date and
historical store fingerprint remain. A separate evidence_currency block retires
current capability. Row verification_is_current still refers to the old store,
not the new code; the report explicitly says so.

| Historical registry quantity | Before | After |
| --- | ---: | ---: |
| D1 acquired sources | 391 | 391 |
| D2 adequately specified genuine UMATs | 260 | 260 |
| Fully verified / all gates true | 44 / 44 | 44 / 44 |
| External | 122 | 119 |
| Internal | 225 | 228 |
| Divergence records (2 in D2) | 3 external | 3 internal |

## Exhaustive Retirement Inventory

[Machine-readable file inventory](recovery_evidence_inventory.json) lists
every path, byte length, SHA-256, embedded generation and parse error under
the stated trees: 757 UMAT files and 10 RA files. It includes supporting files
without embedded fingerprints, not merely search hits. Nothing in this
inventory is promoted to current verification by its presence or hash.

| Repository / scope | Files | Disposition |
| --- | ---: | --- |
| UMAT umat tree | 313 | All 44 material contracts, baseline, registry, withdrawn entries, sources, decks, histories, results and descriptions retained as history |
| UMAT tests/fixtures tree | 23 | Four verified fixtures, both corpus/corpus_current bundles and their decks/logs/histories retained; directory names do not establish currency |
| UMAT paper_results tree | 421 | Corpus JSON/CSV/report, refusal audit, publication tables, figures, presentations and parameter-sensitivity results are historical claims, not current-code verification |
| RA tests/fixtures/verified tree | 10 | All ten pass12 fixtures kept at their original generation with original/converted numerical histories |

Recorded generations include `94a92c01814f107a`, `ff94800b1884bcc0`,
`b0d27ee53c630500`, `b5c7a8d71b01c6e3` and `e4257779bd847cc4`.
The refreshed registry also mentions current code in its retirement metadata;
that is NOT the generation of its measurements. Two archived ARC stdout files
are not parseable JSON; their errors and hashes remain in the inventory.
The old 57 promoted/pass12-terminal, 44 gate-verified, 18/18 benchmark and
20-model sensitivity claims, and archived presentation claims, do not prove
current corpus capability. External corpus_run/transform_store caches are not
rewritten: older-generation entries remain historical and require real reruns.

Exact consumers: UMAT contract fixtures.require_current and check_fingerprint;
TransformStore.current_entries/stale_entries; RA contract_reader.require_current;
RA materials.verified_fixture.load/load_all; core.fixture_residual_check.
RA STORE_PROVENANCE retains the pass12 counts 244/57/44 with ORIGINAL
fingerprint 94a92c01814f107a, not a dynamically substituted new fingerprint.
Regression tests check actual collection/local fixtures and all ten RA fixtures
are refused, with both fingerprints and names, while their numbers remain.
Historical comparisons (including RegressionService and explicit producer-
generation reads) are not current capability evidence. RA framework helpers
that require current fixtures will refuse them; no bypass or new skip was added.

## Current Executable J2 Evidence

The existing provider J2 test was rerun: **1 passed in 7.23s**. A separate
bounded verification CLI rerun retained its raw report under
`.pytest_cache/recovery_evidence_j2_run/verification.json`. It compiles current
transformed code and a separate ORIGINAL UMAT, then checks centred FD sweeps.
No Abaqus job is needed for this material-point check.

Seven increments: elastic, elastic, plastic, plastic, elastic, plastic, elastic.
Comparison counts: eval primal 49; final march primal 6; parameter FD 588 eval
and 504 march; tangent FD 756 each. Worst parameter error 2.493046730365579e-7;
worst tangent error 2.838732044089759e-8; unchanged tolerance 2e-6.
Primal stress/state absolute errors 5.684341886080802e-14 / 2.168404344971009e-19.
FD plateau stress/state/tangent: 1.994408000705079e-8 /
7.515721719070879e-10 / 2.7870660023874207e-10. Resetting carried sensitivities
changes derivatives by 2720.125996569597, so the check detects lost carryover.
Original source hash 9b779f0c6cadf9c4; fresh object SHA-256
8cb54ae11c1ecf511c4caaad7e05e7dc38a0e709ef9b86246d73bfcbb983d28d.
This does not re-freeze the older four-step Abaqus J2 fixture. The report says
clean_install_verified=false. Generic UMAT/FCC, full-sized models, corpus and
publication reproduction remain unestablished by this bounded run.

## Measured Checks

| Check | Result |
| --- | --- |
| Original two tests before edits | 2 failed, 0.28s |
| New RA retirement test before generation repair | 1 failed (old fixture accepted) |
| UMAT generation/lock tests after repair | 33 passed |
| Retained registry preservation/CLI regression | 1 passed |
| Report module plus original generation guard | 19 passed |
| Final focused UMAT fixture module | 18 passed |
| RA fixture module with production refusal | 17 passed |
| RA contract/integration, OTILib path initially omitted | 148 passed, 2 failed, 11 skipped |
| RA contract/integration, documented OTILib environment | 150 passed, 11 skipped, 30.75s |
| Final RA contract/integration after all production edits | 150 passed, 11 skipped, 31.23s |
| Full final UMAT offline suite | 3324 passed, 0 failed, 125 skipped, 5 deselected, 6 warnings, 477.24s |

Final JUnit: UMAT .pytest_cache/recovery_evidence_offline.xml (3449 executed,
zero failures/errors); RA .pytest_cache/recovery_evidence_contract_integration_final.xml.
The six UMAT warnings are four existing deprecated transform-entrypoint calls
and two constrained-layout warnings from a figure-rejection test. The 125
existing skips remain missing historical evidence/previously documented gates.
Final generation still equals actual code. Both shared asset copies match.
Comparison against Git HEAD proves only the three registry kind fields changed;
no fixture or material numerical evidence file changed (only umat/README.md).

The 11 RA skips are unchanged unavailable pass11 cross-reader records, not
passes. The failed environment attempt is preserved in its separate JUnit.
No test was deleted, no tolerance changed, and no skip/xfail added.
No full RA legacy-framework PASS is claimed: its current-generation fixture
helpers correctly refuse the retired corpus. Those workflows need a real new
Abaqus fixture run before they can claim current fixture validation. The requested
contract/integration suite passes without weakening that refusal.

## Reproduction Commands

```sh
WORKSPACE="$HOME/softwarex_work"
UMAT="$WORKSPACE/imq-umat-recovery"
RA="$WORKSPACE/imq-ra-recovery"
PY="$WORKSPACE/.venv/bin/python"
cd "$UMAT"
export PYTHONPATH="$UMAT/src"
"$PY" -c 'import ctypes, umat_oti; print(umat_oti.__file__)'
"$PY" -c 'from umat_oti.store import transform_fingerprint; print(transform_fingerprint())'
"$PY" -c 'from umat_oti.contract import write_lock, verify_lock; print(write_lock()); verify_lock()'
cp src/umat_oti/contract/schemas/transform_generation.json "$RA/schemas/transform_generation.json"
cp src/umat_oti/contract/contract_lock.json "$RA/schemas/contract_lock.json"
"$PY" tools/build_corpus_registry.py --refresh-retained paper_results/corpus/corpus_registry.json
"$PY" tools/inventory_retired_evidence.py --umat "$UMAT" --ra "$RA" --out docs/evidence/recovery_evidence_inventory.json
"$PY" -m pytest -q tests/test_contract_fixtures.py tests/test_contract_schema_lock.py tests/test_the_two_denominators_stay_apart.py
"$PY" -m pytest -q tests/test_provider_recovery.py::test_provider_j2_original_fd_and_carryover --junitxml=.pytest_cache/recovery_evidence_j2.xml
"$PY" -m umat_oti.validation.parameter_sensitivity_provider parameter_sensitivity/models/m3_j2/contract_v2.json --out .pytest_cache/recovery_evidence_j2_run
"$PY" -m pytest -q -ra -m 'not abaqus and not arc and not network and not corpus_pass' --junitxml=.pytest_cache/recovery_evidence_offline.xml
cd "$RA"
env PYTHONPATH="$RA:$UMAT/src:$HOME/otilib/build_py311" UMAT_OTI_REPO="$UMAT" PYOTI_PATH="$HOME/otilib/build_py311" OTILIB_ROOT="$HOME/otilib/build_py311" RUN_OTILIB_TESTS=1 "$PY" -m pytest -q -ra tests/contract tests/integration -m 'not abaqus and not arc and not network' --junitxml=.pytest_cache/recovery_evidence_contract_integration_otilib.xml
```

Both shared locks and generation bytes must agree. Tests run sequentially with
explicit cwd and imports; no detached one-shot jobs. Future fingerprint changes
require the same honest re-freeze-or-retire decision, not relabelling results.