# UMAT-OTI evidence freeze: recommendation (builder: Ada, 2026-10-27)

**Status: builder recommendation, revised after Vera's independent review (`reviews/vera-freeze.md`: choice of commit supported; one blocking and three important findings, all addressed below). Santiago decides.** No tag was created, no
push was made, and ARC and Abaqus were not used. Every run described here was made on Windows 11 with
MinGW-w64 GNU Fortran 16.1.0 through a harness shim (see `MANIFEST.md` §3). That platform is **not** the one
UMAT-OTI declares (Linux). The results are therefore *local regeneration evidence*. They are not the
submission freeze itself.

## 1. Recommendation

**Base the freeze on `2ae2ee07547ae86c5c4c9bb9fe123b1245c13dbc` (`origin/pipeline/library-routines`,
2026-10-15). `2ae2ee0` is not tag-ready as it stands (§1a).** The authors should make one minimal pre-tag
commit on top of it. Santiago then tags that commit `v1.1.0` after the fast-forward merge into `main`,
archives it to Zenodo as a new version of concept DOI 10.5281/zenodo.21297172, and runs the Linux/ARC
re-freeze (T1) at the tag.

### 1a. Minimal pre-tag commit (for the authors; described here only, nothing done or pushed)
1. **Generation fingerprint (blocking, Vera B1).** `src/umat_oti/contract/schemas/transform_generation.json`
   records `c61511ea0ffe58e2`. The transform code at `2ae2ee0` digests, as Linux computes it, to
   **`eaa152dde6047af2`**. I reproduced this independently with
   `refreeze/scripts/checks/fingerprint_posix.py`, which reads raw git blobs with POSIX paths; at `8090ff4`,
   the commit that wrote the record, it returns the recorded `c61511ea0ffe58e2`. The fix follows the
   record's own `how_to_update`: run `umat_oti.store.transform_fingerprint()`, write the result, regenerate
   `contract_lock.json`, and copy both to `Residual_Assembler/schemas/`. The authors must also state that
   the pass25 corpus evidence (115/242 and others) belongs to an older generation: it is history, and must
   be re-frozen before it is cited. Otherwise
   `test_contract_fixtures.py::test_the_recorded_generation_is_this_worktrees_actual_transform` fails on
   every platform.
2. **Tests that reach outside the repository (Vera I3).** `tests/test_corpus_cases_council.py` (10 cases:
   9 setup errors and 1 failure) copies `../corpus_campaign/material_data/...` through
   `WORKSPACE_REAL = REPO.parent` (`:32, :91-97`). `tools/corpus_cases.py` (`REDERIVE`, `COUNCIL_ROWS`)
   uses the same path. Either skip these with a named reason when that directory is absent, or vendor
   the needed inputs after checking their licences.
3. **`CITATION.cff`.** It says `version: 1.1.0` with `date-released: "2026-08-21"`, which is older than the
   code. Set the date to the tag date, and align `codemeta.json` and `.zenodo.json` with it.
4. Optional: widen the FD step in `tests/test_library_routines.py` (Vera O1; see reason 4 below).

After that commit, run the full offline suite on Linux. Every remaining failure must be explained
before the tag.

**Do not freeze at `origin/main` HEAD (`57eaeff`).** It carries both known regressions, and I reproduced them
here (§3). **Do not keep `8e12548` (V11) as the cited commit either.** It predates the regressions but
contains two correctness defects that were fixed later (§4.1). It is not tagged, and its committed evidence
predates it (L47).

Reasons, in order of weight:
1. **Correctness.** `2ae2ee0` contains the fixes to the finite-strain tangent definition (`5cd9ad2`, `4d7036c`,
   2026-09-12), the B1-6 parameter-carrier fix and the B1-1 consumer-layout fix (`faeec2b`, 2026-10-02). The
   parameter-sensitivity sweep, which is 0/20 at `57eaeff`, returns to 19/20 at `2ae2ee0` (83/84 directions, 14539/14540 rows, identical to V11) (§3).
2. **Regression status.** Smoke passes at `2ae2ee0`. The sweep and tangent rounds reproduce V11's committed
   values where V11's code was correct (§3).
3. **Reproducibility.** The bundled OTIlib/pyoti templates are byte-identical from `8e12548` to `2ae2ee0`
   (git tree `d20b35e466ba`). The public GitHub repository holds every commit. The OneDrive copy holds
   nothing that GitHub lacks: its branch heads `60efc97`, `0d0395f`, `75ffc43`, `2cd2699` and `664a5cb` all
   exist on GitHub and all predate `8e12548`.
4. **Cost.** `2ae2ee0` is 379 commits ahead of `main`, and `main` is an ancestor of it, so the merge is a
   fast-forward. It is not on `main`, however, and its branch name ("library-routines") marks feature work.
   Its two BLAS library-routine test failures are a **test defect, not an OTI defect** (Vera O1). The
   central-FD reference in that test is dominated by rounding: its error falls as h grows (4.6e-6 at
   h=1e-4, 2.2e-9 at 1e-2) and rises as h shrinks, and the OTI value is the stable limit. The authors still
   decide whether the library-routines feature ships.

**What I could not establish:** whether ARC (`/home/ammslab3/softwarex_work/final-umat`) holds unpushed commits
newer than `2ae2ee0`. If it does, compare them before tagging. This is an open question. I did not check ARC.

## 2. Repository facts
| Item | Value |
|---|---|
| Authoritative remote | `https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation` (cloned read-only to `refreeze/src/ust`; push URL disabled) |
| Remote heads (2026-10-27) | main/HEAD `57eaeff`; corpus/robustness-2026-10-01 `b802d3a`; pipeline/library-routines `2ae2ee0`; feature/softwarex-unified-umat-oti `f8080b5`; develop `3b835d2`; integration/imqcam-recovery-2026-09-18 `3f340b7`; tag v1.0.0 `fe40e9f` |
| Ancestry | fe40e9f (v1.0.0, 07-10) < c24ff0d (08-26) < 8e12548 (V11, 09-09) < f8080b5 < ce4255a (09-21) < 57eaeff (09-25, main) < faeec2b (10-02) < b802d3a (10-09) < 2ae2ee0 (10-15). Linear (`git merge-base --is-ancestor`) |
| OneDrive copy | `…/Desktop/Ordeal/UMAT_source_transformation`: object store broken. Its refs all resolve in the GitHub clone, except remote-tracking `9c63def`, which is unknown |
| Zenodo 10.5281/zenodo.21297173 (v1.0.0, 2026-07-10) | `santiagarcia/UMAT_source_transformation-v1.0.0.zip`, md5 `53aebb8b…74f8`, sha256 `4f864595…5d41`. Content equals `git archive fe40e9f`, except for CRLF line endings (210 files, `diff -rq --strip-trailing-cr` clean). The record points to the fork `santiagarcia/…` and not to the AMMS-Lab repo. Software Heritage field empty |
| OTIlib | Vendored templates `src/umat_oti/oti/support/pyoti_templates/`, unchanged 8e12548→2ae2ee0. Upstream `mauriaristi/otilib` "master", **no upstream commit SHA recorded** (T12) |
| Dependencies | No lock file in the repository (AA-17 iv). Every venv here resolved to numpy 2.4.6, pandas 3.1.0, sympy 1.14.0, streamlit 1.66.1, matplotlib 3.11.2, pytest 9.1.1 on Python 3.11.16. V11 used Python 3.11.15 and gfortran 13.3.0 (L40), so these runs do not reproduce V11's environment |

## 3. Candidate results (local, Windows plus shim; logs under `evidence/<sha7>/`)
"=V11" means the regenerated file is byte-identical to the file committed at `8e12548`, after CRLF
normalisation. Sweep = models verified / directions verified / comparison rows agreeing. IJ = repository and
bundled internal-Jacobian rows that ran locally.

| Commit | Smoke (m3_j2) | Offline test suite, Windows | Sweep (Table 6, L38) | Tangent + higher order (Tables 2/4, L21/L22) | IJ (L27) |
|---|---|---|---|---|---|
| `2ae2ee0` (recommended base) | pass | 5485 passed, 152 failed, 9 errors, 265 skipped, 1 xfail (24.9 min, 8 workers). All 161 reproduce serially. **Corrected classification (Vera I3; I first called 159 platform-specific):** about 148 are platform or harness failures (backslash paths, `/`-split roots, `os.WNOHANG`/`killpg`, scripts on PATH that Windows cannot execute, case-insensitive `aba_param.inc`, encoding). **11 will fail on Linux too, in a clean clone**: 1 stale generation record (§1a.1) and 10 that need `../corpus_campaign` (§1a.2). **2** (BLAS) come from a noisy FD reference in the test. The tests that need `abaqus` or `gh` on PATH depend on the environment and must be re-checked on Linux | 19/20, 83/84, 14539/14540. Summary table =V11. Rows: 81 cells differ at round-off (OTI ≤ 5.4e-16 rel.; FD references of near-zero entries), 0 verdict changes | L21 (`tools/run_tangent_round.py`): 540/354/186, 0 disagree, worst 2.188e-15; all 5 tangent-round tables =V11. **L22 comes from a different script, `python -m umat_oti.validation.higher_order_convergence_study --model j2`.** Vera ran it first (I1), and my rerun is archived in `evidence/2ae2ee0/rounds/higher_order_convergence/j2/`: `convergence_rows.csv` (540 rows, resolved 20/20/26, max 2.956e-11, verified) and `convergence_sweep.csv` =V11. `convergence_evidence.json` differs from V11's file | m5_cpflow 3.876e-12, PCL, PCLK, VPDCL verified, values =V11 |
| `faeec2b` (fix) | pass | not run | 19/20, 83/84, 14539/14540 | =V11 | =V11 (4 rows) |
| `57eaeff` (main) | **fail**: transform_failed, `old_ddsdde_assignments_disabled` | not run | **0/20, 11/84, 5692/10600; 5 transform_failed** (B1-6 reproduced) | =V11, on the second attempt. The first failed on the shim (`.exe` read), see MANIFEST §3 | 4 rows verified |
| `ce4255a` | pass | not run | 19/20, 83/84, 14539/14540 | =V11 | 4 rows |
| `8e12548` (V11) | fails with GNU make default `FC=f77`, passes with `FC=gfortran` | 1936 passed, 41 failed, 25 skipped (2.0 min). All 41 reproduce serially and are platform-specific by message (V11 on Linux: 1984 passed, 0 failed) | 19/20, 83/84, 14539/14540 | =V11 | 4 rows |
| `c24ff0d` | as 8e12548 (f77, then pass) | not run | 18/20, 76/84, 14507/14540 (unresolved: m6_fcc, sweep_drucker_prager) | older path: 108 entries, 66 zeros, 42 resolved, worst 2.52e-15 (not V11's table) | 4 rows |
| `fe40e9f` (v1.0.0 = Zenodo) | no reproduce module | 6 passed (3 modules) | tool absent | tool absent | tool absent |

V11's committed Table 3 has 8 rows. The 4 rows not regenerated (jgomezc1 PCO/VPDCO/PCL/PCLK, which include
the L28 hand-coded-error rows) need the pinned upstream snapshot, which was not fetched (network off).

## 4. Why not the other candidates
### 4.1 `8e12548` (V11 pin)
- Finite-strain DDSDDE: the seed was `dF = ε` with no Kirchhoff term. `5cd9ad2` ("The converted tangent
  answered a question Abaqus did not ask") changed it to `dF = ε·F` + `σ_ij δ_kl`. `4d7036c` fixed an FD
  reference that shared the same wrong definition. Compare `git show 8e12548:src/umat_oti/transform/source_transform.py`
  lines 2915–2924 with `2ae2ee0` `source_transform.py:4945–4991, 5461–5520`.
- **The blast radius is larger than 2 generality rows** (Vera I2; my first version understated it).
  According to `4d7036c`, all **67 gradient-driven corpus rows** were scored against a reference that
  shared the wrong definition. None of the 67 converted tangents meets the 1e-6 tolerance against the
  corrected reference, yet **61 had been recorded verified**. The cause is one missing σ⊗δ term, and no
  primal history moves. The impact on V11, checked against
  `8e12548:paper_results/corpus/corpus_report.json`, is as follows.
  - **L36** ("67 at the furthest stage"): the corpus report (09-09) predates the fix (09-12). Of its 67
    `fully_verified` entries, **56 are Jeff97 growth-framework sources**, which are driven by the deformation
    gradient. The rest are RitioL 3, irfancn 2, mholla 2, and 1 each from four other repositories. I could not
    match the entries one by one to the 61 in `4d7036c`, because that list is not in the repository. Even so,
    most of L36's verified count very probably rests on the defective reference. **Do not carry it forward.**
  - **L39** (9 of 11 external sources reach `derivatives_verified`): mostly small-strain jgomezc1 sources,
    which this defect does not affect. Its finite-strain members, such as `lucarini_neohookean` (worst
    error "not measured"), need re-checking.
  - **L09/L37**: the verified parts for gradient-driven sources, including the 2 finite-strain generality
    rows, are affected.
  - Quill and Curie should treat every V11 corpus or verified count as unestablished until it is
    regenerated at the tag.
- Its Makefiles fall back to GNU make's default `FC=f77`. Smoke fails on a machine without `f77` and passes
  with `FC=gfortran` exported (`evidence/8e12548/smoke-FC_default_f77.log` against `smoke.log`).
- It is untagged, and its archived evidence snapshots predate it (L47).
### 4.2 `57eaeff` (`main` HEAD)
Reproduced here: smoke `transform_failed` (`old_ddsdde_assignments_disabled`) on m3_j2. Sweep 0/20 verified,
11/84 directions, 5692/10600 rows, 5 transform failures (m3_j2, sweep_j2_bilinear, sweep_j2_combined,
sweep_j2_kinematic, sweep_perzyna_linear). This matches Council finding B1-6 exactly.
### 4.3 `faeec2b`, `ce4255a`, `c24ff0d`, `fe40e9f`
`faeec2b` is the minimal fix commit. It would be a defensible freeze, but it lacks two weeks of later fixes.
`ce4255a` is the last commit before the regression, but it still has the f77 Makefile. `c24ff0d` (Curie's
local results copy) and `fe40e9f` (v1.0.0, Zenodo) predate the article's tooling: v1.0.0 has 3 test modules
(6 tests pass) and no `reproduce` module, so none of the V11 numbers can be generated from it.

## 5. Manuscript numbers (ledger ids) at `2ae2ee0`
"Regenerated" means regenerated here, locally, on Windows plus the shim. The final freeze must repeat the
run on Linux at the tag. "Publishable?" refers only to provenance and licence (Scout's report). Santiago
decides.

| Ledger id | Regenerable at `2ae2ee0`? | Status here | Publishable? |
|---|---|---|---|
| L01 version/tag | yes, after Santiago tags | `pyproject` says 1.1.0. No tag at 2ae2ee0 | — |
| L02 dependency floors | yes (code fact) | read: numpy ≥1.26, pandas ≥2.0, streamlit ≥1.30, sympy ≥1.12, Python ≥3.10 | — |
| L03–L06, L29–L31 code facts | yes (read code at the tag) | not re-read in this round | — |
| L08 order-4 export counts | yes | tangent round regenerated (=V11) | j2_props.f: Scout calls it clean in content; authorship to confirm |
| L14, L15 J2 path, yield at step 7 | yes | path unchanged (`actual_umat_higher_order.py:41-49`). Tables =V11 | as L08 |
| L21 tangent 540/354/186, 2.188e-15 | yes | **regenerated, identical** | as L08 |
| L22 higher order | yes | **regenerated with the correct script**, `umat_oti.validation.higher_order_convergence_study --model j2`. The j2 rows and sweep are =V11 (Vera's run, I1, and mine). Not regenerated: the code_imp, visco_imp and UMAT_PCL(K) convergence rows, and `tools/build_table4_from_convergence.py` | as L08; code_imp/visco_imp/PCL: ICP licence unresolved |
| L24, L25 m3_j2 DSIGMA/DSTATEV | yes | regenerated inside the sweep | **no**: m3_j2 has umatmst3.f lineage (unresolved) |
| L27 m5_cpflow internal Jacobian | yes | **regenerated, identical values** | **no**: m5_cpflow unresolved |
| L28 six IJ sources, jgomezc1 PCO/VPDCO | needs the pinned upstream snapshot (network) | not regenerated | MIT notice pending (EAFIT) |
| L09, L37 generality/Table 3 counts | partly: the Abaqus columns come from ARC runs | not regenerated | 15 of the 20 "local paired" sources are sweep models |
| L10 ≤35 directions | cause is a code fact (`oti_directions.py`). `bench3.py` is outside the repo (AA-16) | not regenerated | — |
| L32–L34 test-suite counts | yes, on Linux | **changed**: 490 test files at 2ae2ee0 against 130 at V11 (by Vera's glob, 492 against 131). Windows: 5485 passed / 161 failed or error (§3). At least 11 will fail on Linux until the pre-tag commit (§1a), so V11's "0 failed" cannot be restated | — |
| L35 paired Abaqus 19 cases | no (Abaqus/ARC) | not regenerated. 36 vs 19 reconciled from files (`evidence/2ae2ee0/CODE_FACTS_T9.md`) | ICP/EAFIT rows: licence unresolved |
| L36, L39 corpus counts | no (corpus store on ARC, network) | not regenerated. **L36 is very probably invalid as stated**: 56 of its 67 entries are gradient-driven Jeff97 rows, scored before `4d7036c` (§4.1). The finite-strain rows of L39 need re-checking. The pass25 registry in the repo is also out of generation (§1a.1) | — |
| L38 sweep 20/84/83 | yes | **regenerated, identical counts** | **no**: all 20 models unresolved |
| L40–L44 performance | no: scripts outside the repo (AA-16), and this machine is shared | not regenerated | — |
| L45, L47 archived manifest facts | superseded by the new freeze manifest | — | — |

## 6. Unresolved
- The exact overlap between V11's 67 `fully_verified` entries and the 61 recorded-verified rows of `4d7036c`.
- ARC holds unchecked commits. No Linux run was made. No Abaqus run was made: the local licence was in
  use by other users' jobs, and ARC was excluded.
- Every number regenerated from the 20 imported sweep models, from m5_cpflow or from the ICP/EAFIT files is
  **technically regenerable but not publishable** until provenance and licensing are resolved
  (`reviews/scout-model-provenance.md`; T2, T3, T11). The smoke profile and the Table 6 sweep depend on m3_j2,
  which descends from umatmst3.f.
