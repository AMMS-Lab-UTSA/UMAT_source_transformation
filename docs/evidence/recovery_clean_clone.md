# Committed Clean-Clone Verification

Date: 2026-09-18. **Full requested gate: FAIL / incomplete.** Bounded wheel
installation and the genuine J2 presentation workflow passed. Neither the
whole offline suites nor every installed example/GUI workflow passed.
The complete structured record is [recovery_clean_clone.json](recovery_clean_clone.json).
The detailed joint narrative is also retained in the RA recovery checkout at
`docs/evidence/recovery_clean_clone.md`; this report is self-contained.

## Exact Snapshot

Branch: `integration/imqcam-recovery-2026-09-18` in both LOCAL clones.
New parent: `/tmp/imqc_clean_clone_20260918_RwJ8VT`.

| Canonical clone | Full SHA |
| --- | --- |
| UMAT_source_transformation | dbd8ff229023b57e4231a2250a54e97dc111f547 |
| Residual_Assembler | 5ea3da4bdd250fe6eea79677cec44e59e86de197 |

Both were cloned with `git clone --no-hardlinks --branch` from the original
recovery paths. Original sources, clones and both full-suite pre-test statuses
were clean. No clone source/test edits. The final unmodified example auditor
modified only generated `docs/evidence/usage_examples.json` after the suites.
No commits, pushes, branches or subagents. Evidence is an uncommitted follow-up.

## Installed Gate

The unchanged UMAT clone forwarding script invoked the RA clone's documented
`scripts/clean_install_gate.py`, using healthy base Python
`/home/ammslab3/anaconda3/bin/python3.11`, the explicit existing ODB below,
and new `--work /tmp/imqc_clean_clone_20260918_RwJ8VT/gate`. All 20 child
commands passed. The raw report's conservative working-tree label is retained;
separate provenance proves these exact committed clean clones.

The gate created a new empty Python 3.11.7 venv and installed freshly built
wheels with RA `gui,test,yaml` and UMAT `test` extras. Scratch HOME, `env -i`,
isolated probes, no editable installs, no inherited PYTHONPATH/user-site or
developer HOME. Project imports resolved under new site-packages. `pip check`
passed; JSON retains exact dependencies, imports/resources, commands and exits.
Source suites separately used only clone sources plus fresh external OTILib;
UMAT's conftest inserts the clone's src. They are not wheel-only tests.

| Wheel | SHA-256 |
| --- | --- |
| residual_assembler-0.1.0-py3-none-any.whl | 8c38bb185fd162e336e20ca6711f54bafd3d004e13e477e9c452bcbcc39bf4e2 |
| umat_oti-1.1.0-py3-none-any.whl | f0cf7f51b59493c7d8cbd0cd7e8030b3ead56c4071e5ad192d077d87b8ef053d |

OTILib was freshly cloned and fully built, including new direction tables:
`https://github.com/mauriaristi/otilib.git` at
`a4b7a05ca275e8d441b0b717b7b272e96728ffcc`, GPLv3. No external old build.
The committed setup helper failed because it requires Conda. The successful
no-Conda follow-up used CMake 3.31.10, Cython 3.3.0, NumPy 2.4.6, SciPy 1.17.1
and GCC/gfortran 9.4.0; configure with `-DBUILD_TESTING=OFF`, then sequential
`cmake --build ... --target oticython --parallel 2` and `--target gendata`.
The installed RA adapter accepted the fresh build and first/second derivative
assertions passed. Upstream OTILib's own suite was not run. The exact procedure
is a separate [RA follow-up document](../../../Residual_Assembler/docs/OTILIB_VENV.md).

## Scientific Input And Repeat

Declared existing ODB:
`imq_abaqus/recovery_presentation/imqrp_reference/collaborator/Analysis.odb`,
SHA-256 `54745b97b515de159c3251e8a3ba0ed89ea1c65452e388ef34c8c81794e3b736`.
This was an explicit scientific input, not an undeclared development cache.

One fresh sequential `imqc_j2` job completed under
`imq_abaqus/recovery/imqc_clean_clone_RwJ8VT`, using copied public clone deck
and J2 source. Abaqus 2021.HF5, ifort 2021.10.0, five licensed Standard tokens.
The committed prepare script hardcodes `imqrp_` and a recovery sibling, so its
documented job recipe was run directly with canonical inputs and `imqc_`.
Fresh ODB SHA-256:
`92460c0ec883a14e0ea4a96021e52cb471dd509f93a4c5dbf0918ea9c9a3c54e`.
JSON records public-input and license hashes. Project source distributions
declare GPL-3.0-only; Abaqus is proprietary licensed software. No independent
ODB redistribution grant was established; no ODB/binary is added to Git.

Installed `resasm request` replayed four increments and four outputs for both
ODBs. Fresh and existing ODB results were numerically identical. Deleting only
the gate-created request output and regenerating gave byte-identical JSON,
CSV and text reports. Source-denied replay also matched. Output correctly
retains `verified=false`, separate from independent validation.

Independent reference `U1=300/E+(300-SIGY0)/H`: relative derivative errors E
`1.6568627353483993e-7`, SIGY0 `8.673617379884035e-16`, H
`8.839354487082118e-9`, all below `2e-5`; nu absolute error below `1e-8`.
Reaction/stress errors below `1e-3`, state error below `1e-6`.

## Examples And GUI

All ten cases attempted twice, deleting only inventoried gate-owned sample
outputs before regeneration. R-X3, R-X4, R-X5 and U-X1 through U-X5 passed
both rounds with identical scientific reports. R-X4 injects clone sources:
only seven successful cases prove installed-module execution. R-X1/R-X2
failed twice because the milestone RA wheel lacks template data. The original
auditor also failed before examples by forcing `$HOME/otilib/build_py311`
instead of the supplied fresh OTILib selectors. No old cache was substituted.

Playwright 1.63.0 refused Chromium on Ubuntu 20.04; 1.48.0 downloaded fresh
Chromium 130.0.6723.31 build 1140 into scratch HOME. Both GUIs were launched
from installed module paths. RA's actual browser request and all three
downloads passed and matched CLI numerical results. Desktop 1440x1100 and
mobile 390x844 had no exception/overflow. UMAT rendered but displayed
"The demo contract is missing" at an environment-relative path: its installed
transformation workflow is NOT established. All owned servers were stopped.

## Full Offline Results

| Run | Passed | Failed | Errors | Skipped | Deselected |
| --- | ---: | ---: | ---: | ---: | ---: |
| RA initial | 372 | 1 | 49 | 19 | 0 |
| RA after documented permissive dependency | 380 | 1 | 49 | 11 | 0 |
| UMAT initial | 3234 | 7 | 4 | 172 | 5 |
| UMAT after explicit ifort and compatible browser | 3243 | 3 | 0 | 171 | 5 |

Commands used documented offline markers: `not abaqus and not arc and not
network`, additionally `not corpus_pass` for UMAT. Final durations: RA
28.203 s; UMAT 582.051 s. Existing skips remain incomplete, not CI PASS.
RA's 49 errors and one failure hardcode absent sibling `imq-umat-recovery`.
UMAT's remaining failures are absolute-path standards, recovery-name
documentation links, and unavailable corpus source discovery. No symlinks,
developer caches, new skips, tolerance changes or fabricated fixture updates.

## Follow-Up Boundary

Only original RA source was fixed: wheel data for five public templates and
installed-path discovery. A separate wheel/environment created and ran both
previously failing templates; five analytic directions each matched within
`1e-8`. Focused regressions: 11 passed, no failures/skips. Follow-up wheel:
`7dbb43f95426529742f46fff09fffcf505e635c615946583804b4c61895c87f0`.
This is NOT the milestone gate; it needs a new commit and clean re-clone.
UMAT source was not edited. Original milestone wheels were not replaced.

Only U-A1, U-A4, R-A1, R-A6 are promoted: exact-SHA wheel installation and CLI
startup. Other ledger rows remain unchanged; historical usage indexes remain
historical. Entire suites, all installed examples/GUI workflows, no path leaks
and whole-ledger completion are NOT established.

All execution requested sync/sequential. The terminal tool auto-backgrounded
one idle-output OTILib command; it finished before the next build/test. No
intentional detach. Raw command/exit records, hashes, both suite attempts,
failure/skip identities, screenshots and embedded temporary harnesses are in
JSON and the retained temp parent. Evidence was written after validations.