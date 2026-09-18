# Re-freeze at transform fingerprint da1f183708c19072 (2026-09-18)

The final integration branch changed transform code (provider entry point
`UMAT_OTI_EVAL_TOTAL`, the labelled-statement, predictor-input, DATA-constant
and helper-closure fixes, the per-entry provider verifier, and the
continued-assignment fix), so every stored transform and every frozen artefact
was evidence about code that no longer existed. This records how the evidence
was made current again, following the procedure in
`src/umat_oti/contract/schemas/transform_generation.json` (`how_to_update`).
The same file sits in both repositories.

## What was run

| step | command (from the UMAT repository root) | result |
| --- | --- | --- |
| 1. re-transform all 391 acquired sources | `python tools/transform_all.py --all --jobs 8 --json <run>/transform_all_pass14.json` | 244 transformed, 147 refused (same outcome for every source as pass13); 218 compile cleanly (pass13: 217) |
| 2. run every transformed entry in Abaqus 2021.HF5 | `python tools/verify_store_in_abaqus.py --work-dir <run>/pass14/work --results-dir <run>/pass14/results --jobs 6 --mode inventory --timeout 1800` | 244 of 244 entries attempted at fingerprint `da1f183708c19072` (16:48 to 17:36); 44 reach the verified stage |
| 3. rebuild the registry | `python tools/build_corpus_registry.py --transform <run>/transform_all_pass14.json --abaqus <run>/pass14/results/store_verification.jsonl --store-fingerprint da1f183708c19072 --audit-refusals` | `paper_results/corpus/` rewritten; the refused set changed, so the offline `ifort -syntax-only` audit of every refused source was redone |
| 4. report against pass13 | `python tools/pass_report.py --registry paper_results/corpus/corpus_registry.json --previous <pass13 registry> --families <run>/material_families.json --label pass14` | 43 of 260 accepted, as in pass13; none gained, none lost |
| 5. generation and lock | fingerprint written to `transform_generation.json`, `umat_oti.contract.schema.write_lock()`, both copied byte for byte to Residual_Assembler `schemas/` | combined lock digest `4ea5c3a5cc202e54cd1338f35240a65bc7880d71ed0ce4596329068f30598f88` |
| 6. Residual Assembler fixtures | Residual_Assembler `scripts/regenerate_recovery_fixture.py` for `isotropic-elasticity--f7eb90376a` and `j2_props--2feae9f158` (loading from the retained pass12 manifests, deck byte-identical) | four Abaqus jobs; both verified (tangent agreement 1.1e-14 and 8.3e-11 over a step-size plateau); both now carry `da1f183708c19072`; `residual_core.core.fixture_residual_check`: elasticity 1 held / 2 not established, J2 32 held / 3 not established, the same pattern as at the previous generation |

`<run>` is the corpus working directory outside the repositories
(`softwarex_work/corpus_run`; 12 GB for pass14, not committed). The
acquisition cache is `softwarex_work/discovery_cache`.

## The census at this fingerprint

| population | verified | external | internal |
| --- | ---: | ---: | ---: |
| all 391 acquired sources | 44 | 119 | 228 |

Within the 260 adequately specified genuine UMATs, 43 clear all six
acceptance gates (Abaqus job completed, all requested outputs present, finite
history, primal agreement, derivatives verified, mechanically informative).
The 217 not accepted are all internal, i.e. this project's to fix: transform
refused 98, primal disagreed 59, primal mismatch explained 16, tangent not
verified 13, original job failed 8, transformed job failed 7, unsupported
formulation 6, experiment not informative 4, support build failed 2,
arguments diverged before the routine 2, informativeness not established 1,
derivative truncated 1. By family: growth 35 of 132, hyperelasticity 3 of 19,
damage / phase field 2 of 20, elasticity 2 of 10, other 1 of 15, and none yet
for plasticity (15), crystal plasticity (15), viscoelasticity (22) or
geomaterials (12).

The continued-assignment fix restored the compile of `simplified_curing.for`
(it compiled at pass13 and stopped compiling after the predictor-input fix
kept its modulus assignments live) and made `enhanced_curing.for` compile for
the first time. Neither changes acceptance: both now stop at primal agreement
(`primal_disagreed`, internal). The same fix
leaves every other generated source it could touch unchanged: the transformed
sources of all 19 benchmark contracts (31 files) and the generated sources of
all 20 parameter-sensitivity providers (180 files) are byte-identical at the
commits before and after it.

## What stays history

The verified collection under `umat/` (44 material contracts, pass12,
`94a92c01814f107a`) and the ten Residual Assembler fixtures under
`tests/fixtures/historical/94a92c01814f107a/` are not regenerated here. They
keep their recorded generation and numbers, the tests keep refusing them as
regression baselines, and they are read only as history. Re-promoting the
collection from pass14 (`tools/promote_verified_umats.py --results
<run>/pass14/results/store_verification.jsonl --work-dir <run>/pass14/work`)
would make them current; it rewrites the collection and was not done in this
step.
