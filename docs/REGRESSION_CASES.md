# Regression cases

A **regression case** freezes one UMAT that the routine-level harness
(`umat_oti.corpus_features`, as run by `tools/run_corpus_features.py`) verified,
so that every later change to the transform, the harness, or the toolchain is
checked against it by numbers. Cases live in `umat/cases/<case_id>/`; the
historical `umat/<id>/` directories are untouched (decision D-7). Design:
`corpus_campaign/design/REGRESSION_ARCHITECTURE.md` (outside this repository).

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
`corpus_assets/` beside the checkout's workspace (`$UMAT_CASE_ASSETS`, default
`~/softwarex_work/corpus_assets`; `objects/sha256/aa/bb/<sha>`,
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

(discovery cache by sha256, then `corpus_assets`, then, with `--allow-network`,
the raw file **at the pinned commit**; any digest mismatch is refused). The CI
tier accepts only `permitted` cases; `freeze --tier ci` refuses the others.

## Freezing a case

    PYTHONHASHSEED=0 python tools/corpus_cases.py freeze --key <registry/store key> --tier offline
    PYTHONHASHSEED=0 python tools/corpus_cases.py freeze --model parameter_sensitivity/models/m3_j2 \
        --family plasticity --activation 1.2e-3 --tier ci

`freeze` takes the transform store's entry for the current transform
fingerprint (read only), or regenerates the transform privately when there is
none (or when it was built for a different NTENS than the experiment drives).
It runs the harness (features `primal_stress_state`, `ddsdde`), and refuses
unless both cells are verified, STRESS and DDSDDE are fully defined in the
ORIGINAL (D-12.3; undefined STATEV slots are recorded and never compared), and
the new case passes its own check (R and P, all canaries rejected). A case is
current only at the fingerprints it records (D-6): after a transform or harness
change, re-run `check`, and re-freeze only through a recorded decision.

## Checking

    make case-ci          # CI tier: permitted cases, R + P, gfortran
    make case-offline     # every case on this machine (needs discovery_cache / corpus_assets)
    PYTHONHASHSEED=0 python tools/corpus_cases.py check --tier offline --replay --only <case_id>

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
| `tolerance` | a DDSDDE entry outside its frozen `tau_e`, or STRESS/STATEV outside the primal rule (row-scaled, rtol 1e-10) |
| `coverage_shrank` | a frozen judged state is no longer judged: output missing/non-finite, primal disagreement at or before it, a hidden-state difference at or before it, or the ORIGINAL no longer reproducing its history |
| `drift` | error/tolerance above 10 x max(frozen error/tolerance, 1e-3), even inside tolerance; needs a recorded re-baseline decision |
| `hidden_state` | the unperturbed call replayed with restored state is not bit-identical |
| `rule_changed` | the global tolerance rule (`case-rule/1-<hash>`, from `RULE` in the tool and the harness rule) differs from the one the case was frozen under |
| `canary_passed` | a mutant was not rejected: per case, a DDSDDE column x (1+1e-4), the smallest resolved entry dropped, STRESS x (1+1e-6); per tier, the SAVE-counter toy `umat/cases/_canaries/hidden_state_toy.f` (its control must pass) |
| `transform`, `build`, `run`, `source_unavailable`, `assets`, `case_corrupted` | the check could not produce numbers, or a case file changed |

A missing gfortran is a failure, never a skip. `--report <file>` writes the
full JSON result; `tools/corpus_cases.py verify-assets` re-hashes every asset
a case lists.

## Tests

`tests/test_corpus_cases_comparators.py` (every failure kind on synthetic data)
and `tests/test_corpus_cases_tier.py` (case files, licence rule, index; with
gfortran: one CI case passes, the same case with a moved reference fails, the
hidden-state toy is rejected).
