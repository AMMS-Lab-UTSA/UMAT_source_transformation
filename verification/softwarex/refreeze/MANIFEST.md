# Re-freeze manifest: manuscript ↔ source commit ↔ environment ↔ scripts ↔ archived outputs

Builder: Ada, 2026-10-27. **Newly generated local evidence. Re-executed independently on the same platform by Vera
(`reviews/vera-freeze.md`); her corrections are applied here and in `RECOMMENDATION.md`. This is not the
submission freeze** (see `RECOMMENDATION.md`). Every archive directory has a `SHA256SUMS` file covering all
of its files, including those not committed. **The sums files were regenerated with LF line endings on
2026-10-27 after Vera's review (O2). The first versions had CRLF, so `sha256sum -c` failed on every line.**
To check an archive, run `cd evidence/<sha7> && sha256sum -c SHA256SUMS`. That check passes for every
archive. The hashes are of the files as the runs wrote them. A fresh checkout with `core.autocrlf=true` can
change the line endings of committed text files, so check with `core.autocrlf=false`, or compare after stripping CR.
**Run logs (`*.log`) were missing from the first commit (`93b4415`)**, because the workspace `.gitignore` ignores
`*.log` for LaTeX. `evidence/.gitignore` and `refreeze/.gitignore` now override that, and the 66 logs are committed. Build products and copies of model sources stay local
(`evidence/.gitignore`): some of those sources have unresolved provenance or licence.

## 1. Manuscript
- Workspace `umat-oti-softwarex-manuscript` at `b7ff395` (HEAD when this task started; `05e09ca` was added by
  Quill during the task).
- The values marked `\REFREEZE` in `tex/` are V11 values at `8e12548`. None of them is changed by this work
  (Quill owns `tex/` and `ledger/`).

## 2. Source
| Role | Commit | Where |
|---|---|---|
| Recommended freeze candidate | `2ae2ee07547ae86c5c4c9bb9fe123b1245c13dbc` | GitHub AMMS-Lab-UTSA/UMAT_source_transformation, branch pipeline/library-routines |
| V11 pin | `8e12548076ae657c66b7b99a457eebd1eedf38c1` | same, on main |
| main HEAD (regressed) | `57eaeff56a940b26de9bd83a8b258e5359fd404e` | same |
| Regression fix | `faeec2b` (2026-10-02) | same |
| Last good before regression | `ce4255affe50945565591ace06a6d7ca5af5f2ea` | same |
| Curie's local results copy | `c24ff0d3c43cfc1f5aa4522c0fe17b03b8bf5bca` | same |
| v1.0.0 = Zenodo 10.5281/zenodo.21297173 | `fe40e9f6265d56237d8eb3f4eee237a0c5951e49` | tag; Zenodo zip sha256 `4f8645956f5ddc7152b2afac5227c2990c0f17d1613e6720a6f8badf5c5e6d41` |

## 3. Environment (identical for every candidate)
- Windows 11 Enterprise 10.0.26200, 24 logical CPUs. The machine was shared with other users' Abaqus
  jobs during these runs, so the timings are not benchmarks.
- Python 3.11.16 (uv-managed). One venv per commit (`refreeze/venv/<sha7>`), each with an editable
  install of `.[test,paper]` (`.[test]` for fe40e9f). Frozen package lists are in
  `evidence/<sha7>/pip-freeze.txt`. Main packages: numpy 2.4.6, pandas 3.1.0, sympy 1.14.0, streamlit 1.66.1,
  matplotlib 3.11.2, mpmath 1.3.0, pytest 9.1.1. The repository has no lock file, so these are the
  versions that resolved on 2026-10-27.
- Harness-only test plugins: pytest-xdist 3.8.0 (sha256 `202ca578…0b88`), pytest-timeout 2.4.0 (`c42667e5…b5c2`),
  execnet 2.1.1 (`26dee51f…9fdc`). Fetched with curl into `refreeze/src/wheels` because uv could not
  reach PyPI from this session.
- Compiler: GNU Fortran 16.1.0 (MinGW-w64 x86_64-ucrt-posix-seh, Brecht Sanders r4). GNU make from
  w64devkit. Git-for-Windows bash.
- **POSIX shim** `refreeze/scripts/posix_shim/refreeze_posix_shim.py`, loaded by a `.pth` file in each venv.
  It (a) runs generated `*.sh` scripts through bash, (b) returns forward-slash paths from `shutil.which`,
  (c) treats `prog` as present when `prog.exe` exists, (d) adds gfortran's directory to the DLL search
  path, and (e) reads `prog.exe` for `Path.read_bytes("prog")`. It changes no UMAT-OTI source and no
  numerical code. It grew during the session: (a)–(d) were in place before every test-suite and round run
  except the first 57eaeff tangent round, and (e) (final sha256 `c6bd631f…67c7`) was added after that
  round failed on (e) and before it was re-run.
- `FC=gfortran` was exported for the rounds and for the second smoke runs of 8e12548 and c24ff0d. Their
  Makefiles fall back to GNU make's default `f77`.

## 4. Scripts (this workspace)
| Script | Purpose |
|---|---|
| `refreeze/scripts/run_candidate.sh <commit> <steps>` | worktree, venv, install, smoke profile, test suite (8 xdist workers plus a serial re-run of failures), per-step `step_status.tsv` |
| `refreeze/scripts/run_rounds.sh <commit>` | the three evidence rounds of the `paper` profile without its embedded test suite: `tools/run_parameter_sensitivity_sweep.py`, `tools/run_internal_jacobian_round.py`, `tools/run_tangent_round.py` |
| `refreeze/scripts/compare_rounds.py <sha7>…` | extracts counts and worst errors and compares them with the files committed at 8e12548 → `refreeze/rounds_comparison.json` |
| `refreeze/scripts/hash_evidence.py <sha7>…` | writes `evidence/<sha7>/SHA256SUMS` (LF) |
| `refreeze/scripts/checks/fingerprint_posix.py <clone> <commit>` | transform generation fingerprint as Linux computes it, from raw git blobs. Returns the recorded `c61511ea0ffe58e2` at `8090ff4` and `eaa152dde6047af2` at `2ae2ee0`, where the record is stale (Vera B1) |
| `python -m umat_oti.validation.higher_order_convergence_study --model j2 --out evidence/2ae2ee0/rounds/higher_order_convergence/j2` (run in the 2ae2ee0 worktree) | **source of L22.** I wrongly attributed L22 to the tangent round at first (Vera I1) |
| `refreeze/scripts/r1/r1_driver.f90`, `r1_verify.py`, `provenance_idcmp.py` | R1 verification (T4) and its provenance identifier check |

## 5. Archived outputs
| Archive | SHA256SUMS sha256 (first 16) | Steps (exit) — see `step_status.tsv` | Key files |
|---|---|---|---|
| `evidence/2ae2ee0/` | `135c150d6beb5944` | install(0), smoke(0), pytest(1), pytest_rerun_failed_serial(1), round_psweep(0), round_internal_jacobian(0), round_tangent(0), round_higher_order_convergence(0) | `pytest-junit.xml`, `pytest-failures.tsv`, `rounds/*/results/`, `rounds/higher_order_convergence/j2/`, `r1/` (R1, NOTES.md), `CODE_FACTS_T9.md` |
| `evidence/57eaeff/` | `8e1fb7478f3863a8` | install(0), smoke(1), round_psweep(0), round_internal_jacobian(0), round_tangent(1), round_tangent(0) | `reproduce-smoke/`, `rounds/psweep/results/parameter_sensitivity_round.json` (regression), `rounds/tangent-first-attempt*.log` |
| `evidence/faeec2b/` | `be85338d0714f6fa` | install(0), smoke(0), round_psweep(0), round_internal_jacobian(0), round_tangent(0) | `rounds/*/results/` |
| `evidence/8e12548/` | `adec6488dc50d94b` | install(0), smoke(1), smoke(0), note(-), round_psweep(0), round_internal_jacobian(0), round_tangent(0), pytest(1), pytest_rerun_failed_serial(1) | `smoke-FC_default_f77.log`, `pytest-junit.xml`, `rounds/*/results/` |
| `evidence/ce4255a/` | `d7d939b493b96728` | install(0), smoke(0), round_psweep(0), round_internal_jacobian(0), round_tangent(0) | `rounds/*/results/` |
| `evidence/c24ff0d/` | `2e7b0414988e2696` | install(0), smoke(1), smoke(0), note(-), round_psweep(0), round_internal_jacobian(0), round_tangent(0) | `smoke-FC_default_f77.log`, `rounds/*/results/` |
| `evidence/fe40e9f/` | `fc9800b759fa266a` | install(0), pytest(0), pytest_rerun_failed_serial(5) | `pytest.log` |

Cross-candidate comparison: `refreeze/rounds_comparison.json`. Chain logs: `refreeze/chain*.log`.

## 5a. Release metadata at `2ae2ee0` (for the pre-tag commit)
- `CITATION.cff`: `version: 1.1.0` and `date-released: "2026-08-21"`, which is two months before the code.
  It must be corrected to the tag date (see `RECOMMENDATION.md` §1a).
- `src/umat_oti/contract/schemas/transform_generation.json` records fingerprint `c61511ea0ffe58e2`, but the
  code is `eaa152dde6047af2`, so the record is stale (§1a.1).
- Clone hygiene: `refreeze/src/ust` was cloned with `--no-checkout`, so its primary worktree shows about
  1.6k staged deletions. Every run used detached worktrees under `refreeze/wt/`. Nobody should commit from
  the clone.

## 6. Not run (and why)
- Not regenerated for L22: the code_imp, visco_imp and UMAT_PCL(K) convergence rows, and
  `tools/build_table4_from_convergence.py`. The j2 rows were regenerated.
- The `paper` profile as a whole was not run. It embeds the full offline test suite again and builds docx
  manuscripts and GUI screenshots. Its three evidence rounds were run directly instead (§4).
- No Abaqus paired runs were made: the local licence was busy with other users' jobs, and ARC was
  excluded. No ARC corpus rounds were run. No benchmarks were run (the `bench*.py` scripts are not in
  the repository, AA-16).
- The external pinned snapshots were not fetched (the network is off by default in the internal-Jacobian
  round), so the jgomezc1/lucarini rows remain `blocked`.
