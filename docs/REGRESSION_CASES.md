# Regression cases

A **regression case** freezes one UMAT that the routine-level harness
(`umat_oti.corpus_features`, as run by `tools/run_corpus_features.py`) verified,
so that every later change to the transform, the harness, or the toolchain is
checked against it by numbers. Cases live in `umat/cases/<case_id>/`; the
historical `umat/<id>/` directories are untouched (decision D-7). Design:
`corpus_campaign/design/REGRESSION_ARCHITECTURE.md` (outside this repository).

## Listing the cases

`umat/cases/index.json` lists every case (118 at this commit: 4 curated CI
cases, and 114 corpus cases in the offline tier -- one for every source in the
routine-level D-8 count at pass23), all frozen at pass23: transform
`830e5ee95ce99cd2`, harness `ec609ab41bb45a02`. The superseded pass18 to pass22
cases are kept in `$UMAT_CASE_ASSETS/history/`, not here. `make case-offline`
checks all 118 in about 75 s with 12 jobs (measured 2026-10-06). One line per case:

```bash
python -c "import json; [print(c['case_id'], c['redistribution'], 'ci' if c['tiers']['ci'] else 'offline') for c in json.load(open('umat/cases/index.json'))['cases']]"
```

```text
bristolcompositesinstitute-abaci--umat--b8fa3835 unknown offline
...
irfancn-abaqus-umat-elastic--umat-elastic--7e9bb4c2 unknown offline
...
umat-oti-curated--m3-j2 permitted ci
```

A case id is `<repository>--<file>--<8 hex of the source key>`; `--only`
needs the whole id. `python tools/corpus_cases.py index` rebuilds the index
from the case directories (silent; no change when it is current).

Each index row also carries `digest`: the sha256 of the case's `case.json` and
of its `reference.json.gz`. This is the case's anchor **outside** its own
directory: `check` fails (`case_corrupted`) when either file no longer matches
it, so editing a reference and "fixing" the sha256 inside `case.json` is still
caught, and any accepted change to a case shows up as a diff of `index.json`.
`case.json` in turn pins the driver configs, the preserved transformed files and
the source by sha256. Rebuilding the index is therefore a re-baseline, to be
done only by `freeze` or through a recorded decision.

## What a case holds

| file | content |
|---|---|
| `case.json` | the manifest: source identity (repository, commit, path, URL, sha256), licence and redistribution status, transform and harness fingerprints, transform recipe, props/NTENS/NSTATV, every frozen loading path, tolerance rule id, frozen error summary, toolchain versions, asset tree, reproduce commands, limitations |
| `inputs/<path>.cfg` | the harness driver input of each frozen path: props, initial state, the full strain / deformation-gradient / time history |
| `reference.json.gz` | per path: the ORIGINAL routine's STRESS/STATEV history, and for every judged state the FD-of-the-ORIGINAL reference `D_e` and tolerance `tau_e` of every DDSDDE entry, plus the error the transformed build had when frozen |
| `source/` | the original source, **only** if its redistribution status is `permitted` |
| `transformed/` | the transformed units needed to rebuild (compile order, units, `dependencies/`), **only** if `permitted` (derivative work of the source) |

Everything else (harness records, histories, the whole transform output,
non-redistributable sources) goes to the content-addressed asset store
`$UMAT_CASE_ASSETS` (default `$UMAT_OTI_WORKSPACE/corpus_assets`, and
`$UMAT_OTI_WORKSPACE` defaults to `~/softwarex_work`, not to the checkout's
parent; see the
[workspace layout](CORPUS_VERIFICATION.md#workspace-layout-the-corpus-tools-assume); `objects/sha256/aa/bb/<sha>`,
`trees/<tree>.json`, `log.jsonl`); `case.json` names the tree. The store is on
one disk with no off-machine copy yet (D-3).

## Licences (D-2)

A source is `permitted` only when its repository has a licence **file** at the
pinned commit that is GPL-3.0-only compatible (MIT, BSD-2/3, Apache-2.0,
GPL-3.0(-or-later), LGPL-3.0). The status comes from the corpus manifest
(`paper_results/corpus/manifest/corpus_manifest.json`); repository metadata
without a file gives `unknown`. A case that is not `permitted` keeps only the
sha256 and the pinned URL; get the source with

    python tools/corpus_cases.py fetch <case_id>

It looks in `$UMAT_OTI_WORKSPACE/discovery_cache` (by sha256), then in
`$UMAT_CASE_ASSETS`, then, with `--allow-network`, downloads the raw file
**at the pinned commit**; any digest mismatch is refused. It prints where the
source is, for example

```text
irfancn-abaqus-umat-elastic--umat-elastic--7e9bb4c2: $UMAT_OTI_WORKSPACE/discovery_cache/irfancn__Abaqus-UMAT-elastic/umat_elastic.for (discovery_cache)
```

so outside the workspace it needs `--allow-network` (or the two variables set). The CI
tier accepts only `permitted` cases; `freeze --tier ci` refuses the others.

## Freezing a case

    PYTHONHASHSEED=0 python tools/corpus_cases.py freeze --key <registry/store key> --tier offline \
        --verification-records $UMAT_OTI_WORKSPACE/corpus_run/pass23/results/store_verification.jsonl \
        --registry $UMAT_OTI_WORKSPACE/corpus_campaign/pass23_registry/corpus_registry.json
    PYTHONHASHSEED=0 python tools/corpus_cases.py freeze --model parameter_sensitivity/models/m3_j2 \
        --family plasticity --activation 1.2e-3 --tier ci

`--verification-records` and `--registry` point the key resolution at a
verification pass (as `tools/run_corpus_features.py` takes them); without them
the harness defaults apply. `freeze` takes the transform store's entry for the current transform
fingerprint (read only), or regenerates the transform privately when there is
none (or when it was built for a different NTENS than the experiment drives).
It runs the harness (features `primal_stress_state`, `ddsdde`), and refuses
unless both cells are verified, STRESS and DDSDDE are fully defined in the
ORIGINAL (D-12.3; undefined STATEV slots are recorded and never compared), and
the new case passes its own check (R and P, all canaries rejected). A case is
current only at the fingerprints it records (D-6): after a transform or harness
change, re-run `check`, and re-freeze only through a recorded decision.

**Harness fingerprint.** The 118 cases at this commit record the fingerprints
the pass23 run recorded: transform `830e5ee95ce99cd2`, harness
`ec609ab41bb45a02`, the same values as the pass23 registry rows; every case was
frozen again from pass23, and the pass22 cases are archived under
`$UMAT_CASE_ASSETS/history/pass22_cases_830e5ee95ce99cd2/`. The case capture
records the verdict the harness used: `judge_binary32` judges a column three
times (normal, wide with eps = EPS_SINGLE, double variant) and returns a
fourth, per-entry verdict, and a case holds the returned verdict's codes
`pass`, `zero_pass`, `pass_b32` and `zero_pass_b32` (B32-1) and nothing
unresolved or failed (none of the cases holds a b32 code yet). A `freeze` that
stops, anywhere, leaves the existing case alone: the capture is read before
anything on disk changes, the new case is staged in a hidden `.freeze-*`
directory (never read as a case) and swapped in once it has passed its own
check.
Any later change to
`src/umat_oti/abaqus/` or `src/umat_oti/corpus_features/` changes the live
fingerprint, and the cases then no longer match it. Under D-6 that means: the
cases remain the frozen evidence of their own pass' count at the fingerprints they record;
`check` still runs them against the changed code (it compares numbers, not
fingerprints), and a pass shows the change did not move any frozen result. It
does not turn them into evidence at the new fingerprint -- that needs a re-freeze
through a recorded decision. Since G10 the Abaqus tangent gate imports
`corpus_features.fd`, so the harness fingerprint governs the Abaqus rows too
(D-17 superseded, 2026-10-03).

**Limit: the index is an anchor, not a lock.** Someone who edits a reference,
edits `case.json` to agree (counts, judged increments, sha256) and then re-runs
`python tools/corpus_cases.py index` gets a case that passes `check`. The edit is
visible only as a diff of `umat/cases/index.json` (its `digest`, `paths` and
`judged_states` change). Reviewing every `index.json` diff -- and accepting one
only with a `freeze` run or a recorded decision behind it -- is therefore part of
the integrity story; `check` alone does not prove a case was not re-baselined.

## Checking

    make case-ci          # CI tier: the 4 permitted cases, R + P, gfortran (~10 s)
    make case-offline     # every case on this machine (needs the workspace layout)
    PYTHONHASHSEED=0 python tools/corpus_cases.py check --tier offline --replay --only <case_id>

`make case-ci` needs only this repository and `gfortran`. It ends with

```text
4/4 cases pass; canaries all rejected; <seconds>s
```

after one `PASS <case_id> (...)` line per case, each followed by three
`canary rejected: ...` lines. The exit code is 0 only if every case passes and
every canary is rejected; a canary that is not rejected (per case or the tier's
hidden-state toy) is named in the closing line (`N canaries NOT REJECTED (tier
FAILS): ...`), never summarised as "all rejected".

A worked offline check (a corpus case whose source is not redistributable, so
it is rebuilt from `discovery_cache/`). Measured 2026-10-02, 3 s:

```bash
PYTHONHASHSEED=0 python tools/corpus_cases.py check --tier offline --replay \
    --only irfancn-abaqus-umat-elastic--umat-elastic--7e9bb4c2
```

```text
PASS irfancn-abaqus-umat-elastic--umat-elastic--7e9bb4c2 (2.4s; replay: 1.7s)
     canary rejected: tangent: DDSDDE column x (1+0.0001)
     canary rejected: tangent: smallest resolved nonzero entry dropped
     canary rejected: primal: STRESS x (1+1e-06)
tier canary rejected: hidden-state toy (SAVE counter) {...}
1/1 cases pass; canaries all rejected; 2.8s
```

Without `--replay` (or with `--regenerate`) the check also re-transforms the
original (R): about 7 s per corpus case (measured 2026-10-02).

* **R** (`--regenerate`): transform the ORIGINAL with the *current* code
  (`transform_one` in `tools/transform_all.py`, including its job-layout gfortran
  compile), build with the harness driver, rerun every frozen path.
* **P** (`--replay`): rebuild the *preserved* transformed units and rerun.
  R fails and P passes: a transform regression. R passes and P fails: toolchain
  or asset damage.
* The ORIGINAL is rebuilt too (unless `--no-original`) and must reproduce its
  frozen history.

Generated Fortran is never compared as text; only numbers decide.

## What fails a check

| failure | meaning |
|---|---|
| `tolerance` | a DDSDDE entry outside its frozen `tau_e`, or STRESS/STATEV outside the primal rule (row-scaled, rtol 1e-10). A structural-zero (`zero_pass`) entry needs both `|DDSDDE_e| <= tau_e` and its stored `|D_e| <= tau_e`, so a frozen zero moved off zero is a breach |
| `reference_incomplete` | a path declared in `case.json` is missing from the reference, or the reference holds a path `case.json` does not declare |
| `not_indexed` | the case has no row in the `index.json` beside it |
| `coverage_shrank` | a frozen judged state is no longer judged: output missing/non-finite, primal disagreement at or before it, a hidden-state difference at or before it, or the ORIGINAL no longer reproducing its history; or the reference holds fewer judged states (or other increments) than `case.json` declares, or fewer paths / judged states than `index.json` lists |
| `drift` | error/tolerance above 10 x max(frozen error/tolerance, 1e-3), even inside tolerance; needs a recorded re-baseline decision |
| `hidden_state` | the unperturbed call replayed with restored state is not bit-identical |
| `rule_changed` | the global tolerance rule (`case-rule/1-<hash>`, from `RULE` in the tool and the harness rule) differs from the one the case was frozen under |
| `canary_passed` | a mutant was not rejected: per case, a DDSDDE column x (1+1e-4), the smallest resolved entry dropped, STRESS x (1+1e-6); per tier, the SAVE-counter toy `umat/cases/_canaries/hidden_state_toy.f` (its control must pass) |
| `transform`, `build`, `run`, `source_unavailable`, `assets`, `case_corrupted` | the check could not produce numbers, or a case file changed (against `case.json`, or `case.json`/the reference against the `index.json` digest) |

A missing gfortran is a failure, never a skip. `--report <file>` writes the
full JSON result; `tools/corpus_cases.py verify-assets` re-hashes every asset
a case lists.

## Tests

`tests/test_corpus_cases_comparators.py` (every failure kind on synthetic data)
and `tests/test_corpus_cases_tier.py` (case files, licence rule, index; with
gfortran: one CI case passes, the same case with a moved reference fails, the
hidden-state toy is rejected), and `tests/test_corpus_cases_injections.py`
(tampering: a reference value moved by 2 tau, for a `pass` and a `zero_pass`
entry; judged states or a path dropped with the sha256 refreshed; a corrupted
transformed file with its sha256 refreshed; a reference moved past the drift
floor but inside tolerance -- each must fail). The licence guard in
`tests/test_verified_umat_collection.py` takes the redistribution decision from
the corpus manifest (corpus cases) or from the repository file and
`THIRD_PARTY_NOTICES.md` section 2a (curated cases), not from `case.json`.
