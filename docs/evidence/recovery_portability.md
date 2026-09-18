# Recovery Portability Slice

Date: 2026-09-18. **Bounded working-tree portability slice: PASS.** This is
not committed clean-clone acceptance, full historical corpus coverage, or
whole-ledger completion. Exact commands, all original failure identities,
final skip identities, wheel hashes, import paths, browser harness and raw
artifact digests are in [recovery_portability.json](recovery_portability.json).
The joint commands and detailed handoff are in the companion
[portability report](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/evidence/recovery_portability.md).
The earlier [clean-clone report](recovery_clean_clone.md) remains historical.

| Check | Result |
| --- | --- |
| Full RA offline suite | 437 passed, 11 skipped, zero failures/errors |
| Full UMAT offline suite | 3249 passed, 171 skipped, 5 deselected, zero failures/errors |
| All ten installed examples | R-X1 through R-X5 and U-X1 through U-X5 passed sequentially |
| Fresh empty environment and new wheels | Installation gate passed, no editable installs |
| Installed UMAT browser demo and same-contract CLI | Genuine transform and compile passed; 21/21 structural checks, zero blockers |
| Desktop/mobile browser | 1440x1100 and 390x844, no page errors or overflow, server stopped |
| Existing genuine ODB source-denied consumption | Passed independent reference; no new Abaqus job |

## Changes And Provenance

The wheel packages only the original public elastic demo contract and Fortran
source, byte-for-byte, with their original relative reference. The app resolves
them using `importlib.resources` into a writable workspace; the unchanged
transformation service is used by GUI and CLI. No whole repository was bundled.
Tests cover wheel resource bytes, actual compilation and arbitrary checkout
paths. Test extras now declare wheel, mpmath and matplotlib.

The mathematical fingerprint measured before and after is exactly
`6aa20d22e37f14c9`. Only already-excluded app code and non-fingerprinted build,
test and documentation files changed. No fingerprint exclusions, generation,
lock or fixture bytes were changed; no retirement/regeneration is needed for
this slice.

Cross-project tests honor explicit `RESASM_REPO`; RA fixtures honor
`UMAT_OTI_REPO`. Canonical siblings remain the default. Invalid explicit paths
fail clearly. R-X4 now defaults to isolated installed imports and records
site-packages module paths. The auditor honors explicit OTILib selectors.
Documentation links use canonical companion paths and configured resolution,
with regressions that still reject missing targets. Missing historical browser
cache files are described as unavailable rather than linked as clone assets.
Only exact historical transcript files receive explained machine-path
exemptions; auditing was not disabled for source, tests, or whole docs trees.

The JSON classifies every one of the **114 failure/error entries** in the two
original attempts: 100 repeated RA locator entries, six browser prerequisite
entries, two compiler prerequisite entries, two standards entries, two docs
link entries and two missing-historical-source entries. The source discovery
test's existing prerequisite skip now checks its actual external originals,
not just the broad parent directory; identity assertions remain unchanged.

Temporary work: `/tmp/imq_portability_3W4QbqeM`, with snapshots named
`consumer-arbitrary` and `producer-arbitrary`. They include uncommitted
working-tree overlays, so this is not exact-commit clean-clone proof. The new
empty environment and wheels are under `installed-final`. Test-only follow-up
changes were copied to the producer snapshot before the final full-suite run.

| Wheel | SHA-256 |
| --- | --- |
| residual_assembler-0.1.0-py3-none-any.whl | `2dd7ece45b91d14249615cdbb184d627b914a10809d41179894161c5ba24d5ff` |
| umat_oti-1.1.0-py3-none-any.whl | `33a7f6ae8819b97cef88af96bcab9cebdb57883206158aca3df7cce25755f98b` |

## Commands And Limits

With explicit `RA`, `UMAT`, installed environment `PY`, genuine `OTILIB_BUILD`,
compatible browser and compiler environment configured as in the joint report:

```sh
export UMAT_OTI_REPO="$UMAT" RESASM_REPO="$RA"
export PYOTI_PATH="$OTILIB_BUILD" OTILIB_ROOT="$OTILIB_BUILD"
export RUN_OTILIB_TESTS=1
cd "$UMAT"
UMAT_OTI_SNAPSHOT_ROOT="$RA/sources" PYTHONPATH="$UMAT/src:$OTILIB_BUILD" \
  "$PY" -m pytest -q -ra -m 'not abaqus and not arc and not network and not corpus_pass' \
  --junitxml="$WORK/umat_offline_final.xml"
unset PYTHONPATH PYTHONHOME
"$PY" -I "$RA/scripts/audit_recovery_usage.py" --umat "$UMAT" \
  --phase examples --imports installed --work "$WORK/examples" \
  --evidence-dir "$WORK/example-evidence"
```

Actual runs used scratch HOME and `env -i`. Source suites deliberately import
snapshot sources, unlike wheel-only examples/browser. Genuine OTILib and
Chromium were explicitly reused from the earlier clean-clone investigation;
SciPy and Playwright 1.48.0 were installed into the new environment. No hidden
developer source import or large corpus copy was substituted.

All 171 UMAT skips and 11 RA skips are individually retained in JSON. They
include absent pass9/pass10/pass11 records, external originals/caches/decks,
and existing historical conditions. Five licensed corpus tests are deselected.
No missing-field assertions, scientific tolerances or gate requirements were
weakened. These missing historical inputs are not complete corpus evidence.

The first new RA run lacked SciPy; the final rerun passed unchanged gates.
One temporary snapshot had copied submodule Git metadata and one browser
harness CLI call lacked `--config`; both were corrected and disclosed in JSON.
The second UMAT suite was requested sync but auto-backgrounded after output
idle, and later browser/presentation checks overlapped it. All ten examples
ran sequentially. Final JUnit was collected only after completion.

No commits, pushes, recovery-branch changes, subagents or new Abaqus jobs.
**Next lead action:** review and commit both repos' bounded changes (including
the preserved earlier RA template fix), then perform a new exact-commit
clean-clone gate with explicitly supplied scientific inputs. No whole-ledger
or full historical-corpus completion is claimed.