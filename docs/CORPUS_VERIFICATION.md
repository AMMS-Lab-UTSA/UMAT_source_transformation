# Verifying a corpus of other people's UMATs

This document describes the method used to verify third-party UMATs: the loop
that turns a directory of downloaded Fortran into a set of materials with
evidence behind them, and a named reason for every other source. Read it to
understand what "verified" means for the corpus, or before running the corpus
tools yourself.

## Current result

The whole corpus of 405 acquired sources was re-transformed and re-verified on
2026-10-03 (pass22: commit 417cfc4, transform fingerprint `830e5ee95ce99cd2`,
harness fingerprint `fb9b8017dc0fd59c`). pass22 is the author-deck acceptance
run of D-19a rev 2 (R7 step 2, with step 3's flow tables): no council
experiment counts yet. 245 sources at pass21 were adequately specified genuine
UMATs with an author's deck; 242 are at pass22 (the eligible denominator, D2).
Three left it, all by reviewed ruling or a newly read deck: hamza-djeloud
plate_with_notch and irfancn uel_elastic are the visualisation UMATs of a UEL
(`not_a_umat`), and vishalsubbiah umatcode3 needs an orientation file the author
did not publish (`missing_material_data`). Two counts are reported, never
pooled:

- **Abaqus, D-4 gate** (both builds run in Abaqus, primal gate by routine
  replay plus the Jacobian-matched control, DDSDDE judged entry by entry
  against a finite difference of the original with an FD-only plateau of at
  least 3 steps and a quad reference where double cannot resolve, mechanically
  informative): **105 of 242** (102 of 245 at pass21, the first D-4 pass; 67 of
  238 at pass20 came from the legacy tangent gate, which D-4 supersedes, and is
  not comparable). Of the 242, 4 are `tangent_not_verified`, all unresolved at their
  chosen states; none carries a measured disagreement.
- **Routine level (decision D-8)**: Abaqus primal gate passed, the
  mechanically informative gate read true, and the routine-level harness
  verifies primal and DDSDDE against FD of the original (FD-only plateau of at
  least 3 steps, entrywise tolerance, quad-precision reference where double
  cannot resolve, binary32 stores judged under rule B32), with STRESS and
  DDSDDE fully defined in the original: **113 of 242** (112 of 245 at pass21,
  109 of 238 at pass20).

Per material family (code-reviewed classification, decision D-11; "eligible" is the
family's share of D2):

| family | eligible | Abaqus D-4 gate | routine level |
|---|---|---|---|
| growth / morphoelastic | 134 | 97 | 100 |
| rate-independent plasticity | 21 | 1 | 2 |
| damage / phase field | 13 | 0 | 0 |
| crystal plasticity | 12 | 0 | 4 |
| linear elastic | 9 | 3 | 3 |
| viscoelastic | 10 | 1 | 1 |
| concrete / geomaterial | 13 | 0 | 0 |
| other (incl. hyperelastic) | 30 | 3 | 3 |
| **total** | **242** | **105** | **113** |

The growth figures include sources whose growth tensor is fixed to the identity
(neo-Hookean response), and 105 of the growth sources come from one author
(Jeff97). The largest remaining blockers are missing material data (no published
`*USER MATERIAL` deck), transform refusals in the non-growth families, and primal
disagreements in Abaqus; the per-source reasons are in
[paper_results/corpus/manifest/](../paper_results/corpus/manifest/) and the
registry. The pass20 -> pass21 change of every source, with its cause, is in
`corpus_campaign/batches/B10/atlas/` (outside this repository).

Reproduce the counts: `python3 $UMAT_OTI_WORKSPACE/corpus_campaign/count_target.py
paper_results/corpus/corpus_registry.json <harness manifest_cells.jsonl>`, or read
`summary.features` in the manifest (DDSDDE verified, D2 = 113).

The paragraph below is the 2026-09-18 census (Abaqus six-gate count only);
it predates the routine-level count and the reviewed classification.

The whole corpus of 391 acquired sources was re-run on 2026-09-18 at the
current transform generation. Of the 260 adequately specified genuine UMATs
among them, 43 clear all six evidence gates the census records
(`abaqus_job_completed`, `all_requested_outputs_present`,
`complete_history_finite`, `primal_agreed`, `derivatives_verified` and
`mechanically_informative`). The full census, with both denominators and the
reason for every source that did not verify, is
[paper_results/corpus/CORPUS_VERIFICATION.md](../paper_results/corpus/CORPUS_VERIFICATION.md).

## What "verified" means

Nothing is verified because it downloaded, parses, transforms, compiles, or
because Abaqus started. A source counts as verified (decision D-8) only when
**all** of these hold, each with an artefact behind it:

1. it was transformed and compiled in the Abaqus job layout;
2. **primal**: stress and state of the transformed build agree with the
   ORIGINAL over the family's loading paths (unload/cyclic where the model has
   them), on a mechanically informative run;
3. **DDSDDE** (dσ_{n+1}/dΔε at fixed incoming state) agrees with finite
   differences of the ORIGINAL, with an FD-only plateau over at least 3
   consecutive step sizes (D-4; a 2-size plateau is only `plausible`) and an
   entrywise tolerance, on enough smooth states;
4. the hidden-state gate passed, including the uninitialised-variable check;
5. the evidence is reproducible from a preserved regression case
   ([REGRESSION_CASES.md](REGRESSION_CASES.md)).

### Two counts, always side by side

| count | where measured | what it is |
|---|---|---|
| **Abaqus six-gate** | the original and the transformed build in Abaqus, same deck (`tools/verify_store_in_abaqus.py`) | gates `abaqus_job_completed`, `all_requested_outputs_present`, `complete_history_finite`, `primal_agreed`, `derivatives_verified`, `mechanically_informative`. The stronger claim. |
| **routine-level (D-8)** | the routine called directly by a gfortran driver, no Abaqus (`tools/run_corpus_features.py`) | points 1-5 above, cell by cell |

A figure quoted from the routine-level count says so. The corpus manifest's
DDSDDE column counts only D-4 evidence; the legacy `derivatives_verified`
plateau (taken from the OTI-vs-FD error) is shown there and never counted
([CORPUS_MANIFEST.md](CORPUS_MANIFEST.md)).

### Primal gate (D-15)

The routine-level primal check replays both builds over the same history. The
bound is set by the ORIGINAL itself: its per-row noise floor under 1-ulp input
perturbations, bound = clip(4 x floor, 2, 64) ulp, scaled by a stiffness capped
by the original's history maximum. A **Jacobian-matched control** repeats the
check with the original's stiffness and the same floor; a source that agrees at
routine level but fails the control is counted **not verified**.

### Undefined in the original (D-12)

The ORIGINAL is also built with signalling-NaN, zero and +inf/flipped-logical
initialisation. An output that differs between these builds reads an undefined
value: it is labelled `undefined_in_original`, reported as a defect of the
source, and never compared. The other outputs may verify only if they are
bit-identical across the init builds over the whole history. A source counts
towards D-8 only if STRESS and DDSDDE are fully defined on every judged state;
undefined STATEV or energy outputs are disclosed. Loading paths stay inside the
author's documented domain; a path outside it is `outside_model_domain` and
gives no verdict.

### Harness fingerprint (D-10)

Every verification row records the harness fingerprint
(`umat_oti.store.transform_store.harness_fingerprint()`, a digest of
`abaqus/` and `corpus_features/`) beside the transform fingerprint. A registry
built with `--harness-fingerprint H --store-fingerprint T` treats rows from any
other harness or store as not current. Routine-level cells carry their own
`run_id` and transformer fingerprint. A regression case is current only at the
fingerprints it records (D-6).

**Harness `d6f92d4704bee702` -> `3648d174377c2280` (2026-10-02, licence
clean-up before the push, Vera B7).** Two yield-function identifications in
`corpus_features/mechanics_checks.py` matched literal statements of a
republished Abaqus example. They now match the structure instead: the variable
stored in `STATEV(1+2*NTENS)` is the argument of the `Sy*(0.0001+p)**n` power
law (Lemaitre), or the returned stress is a direction times the `PROPS(3)`
variable plus a hydrostatic part, with a `PROPS(4)` modulus beside it (radial
return). The transform fingerprint is unchanged (`a4f0ea8c9d124f18`). Evidence
of equivalence: old and new `yield_function_for` give identical results
(description, evidence, plastic slot, tolerance, or none) on all 279 pass20
sources and on all 1937 Fortran files in the acquisition cache, under two
property sets each: 0 changed. The rules identify the same six cache files as
before (five of them pass20 sources).
Nothing else under `abaqus/` or `corpus_features/` changed, so every pass20 row
and every routine-level cell has the verdict it had. The Abaqus rows are
unaffected (D-17: nothing on the Abaqus verification path imports
`corpus_features`; rechecked by import). The 113 regression cases remain the
frozen evidence at `d6f92d4704bee702`, and `make case-ci` still passes them
against the new code. The script and its output are in
`corpus_campaign/batches/B7/gauss_prepush/` (`equivalence.py`, `equivalence.out`).

### Binary32 stores (rule B32)

A source that stores a derivative-carrying value in a `REAL` (binary32) variable
is judged against a finite difference of the original that carries binary32
noise. The scope is decided per derivative entry (output, input, state) from
the original's two builds only, before any value under test is read: the output
depends on a store of the transform's binary32 map and that store depends on the
input (static), and the FD of the original and of its double variant (binary32
declarations widened to `REAL*8`, no OTI) differ at one or more steps by more
than the entry's double noise envelope (dynamic). In scope, the FD noise is
`eps_single F / h` and a pass is counted as `pass_b32`. An entry that fails and is
not a B32 pass stays FAIL. It becomes `unresolved_binary32` only when the original
and the double variant both resolve, differ by more than 1e-3 relative, and the
value under test agrees with the double variant. The double variant is a
secondary reference and never verifies the author's function.

The 1e-3 bar was fixed in advance. One source sits close to it:
`Growth-CASE3.for` (Jeff97, `growth_held_stretch` path, `state_state_sens_local`)
has 210 `unresolved_binary32` entries in 10 records, all with the same
original-to-variant gap of 1.013e-3 (each of the 163 listed examples reads
1.01300e-3), so they clear the bar by 1.3 percent and not by a wide margin.
Read them as properly scoped but marginal: a bar of 1.02e-3 would have made them
FAIL. They are not counted as verified, and the bar was not tuned to them.

### Per-family figures (D-11)

Family figures use the code-reviewed classification
(`corpus_campaign/batches/B3/scout/families_reviewed_B3.json`, column S1), not
keyword matching. Eligible denominators: growth 134, plasticity 29, damage 15,
crystal plasticity 12, linear elastic 13, viscoelastic 11, concrete/geo 14,
other 32. Every growth figure carries this footnote:

> includes N growth-framework sources whose growth tensor is fixed to the
> identity (neo-Hookean response); 105 of the growth denominator come from one
> author (Jeff97).

N is the number of those 11 identity-growth files among the verified.

## The loop

```
inspect the source and what was published beside it
        |
build a manifest: tensor shape, kinematics, constants, and where each came from
        |
generate an experiment
        |
run the ORIGINAL  -->  did the material do anything?
        |                    |
        |                    no --> raise the amplitude / change the rate / hold
        |                            and generate again
        yes
        |
run the CONVERTED build on the same deck
        |
compare the whole history, not the last increment
        |
choose smooth states, away from any transition
        |
sweep step sizes and check the tangent converges
        |
freeze it as a regression case
```

## Where each number comes from

The rule is that no number a result depends on may be invented, and every one
carries where it came from.

| what | read from | recorded in |
|---|---|---|
| material constants | a `*MATERIAL` block in a deck the author published | `material_provenance` |
| finite or small strain | the paired deck's `*STEP ... NLGEOM` | `kinematics_provenance` |
| the formulation and NTENS | what the routine does with its own tensor, and what element the deck runs the material on | `formulation` |
| the state-variable count | the deck's `*DEPVAR`, or a bound inferred from the subscripts the source uses, said to be an inference | `material_provenance` |
| the loading | searched for, on the ORIGINAL only | `discovery` |
| the tangent tolerance and step ladder | this project's, stated | `manifest` |

Where a number cannot be found, the entry stops and says so. A plausible
elastic vector would have produced jobs that all ran and results about
materials nobody described.

## Two modes

**`discovery`** infers what is missing, generates an experiment, searches for
an amplitude and a rate that make the material do something, and chooses the
states to differentiate at.

**`regression`** replays what a material first verified under -- the same
amplitude, the same segments, the same hold, the same step ladder, the same
tolerances -- and fails if any of it stops verifying. It replays rather than
searches because a regression that searched again would be measuring a
different experiment, and a difference between two such runs says nothing
about the commit in between. A frozen experiment is used only while the
source's digest is still the one it was chosen for.

```bash
make batch-abaqus                       # discovery over the whole store
make umat-regress                       # regression against the frozen set
```

## What the loading search does, and what no amplitude can find

The amplitude is searched for, not chosen: a fixed probe is a guess about
somebody else's material, and at a strain the model answers elastically it
tests the part of a UMAT that every build gets right. Each candidate is a real
Abaqus job on the ORIGINAL; the converted build is never run while the loading
is being chosen, because a loading chosen with it in view would be a loading
chosen to agree.

Four things stop the search, and each is an answer rather than a failure:
the material activated; it stayed linear to the ceiling, which for a linear
elastic material is correct and final; it stopped converging, which bounds the
amplitude from above; or it left its domain.

**No amplitude asks about time.** A Kelvin-Voigt solid is linear in the strain
at every amplitude, so the search reports "nothing here to activate" about a
material whose whole subject is time. So the same path is walked again over a
different step time, and stopped for a while at the end of it. Where that finds
something, the verification loading gains a hold -- the only part of the path
that exercises a time-dependent branch at all.

**A state variable is not a plastic strain because it moved.** It can hold a
stretch, a deformation measure, a temperature or a copied input, and every one
of those moves at any amplitude however small. The question asked is whether
the movement is one the loading does not explain.

## Terminal states

Four are final and lie outside this repository. `missing_material_data`:
nobody published what the material is made of. `not_a_umat`: the file's Abaqus
entry point is something else. `incomplete_or_corrupt_source`: it does not
compile as published, measured by compiling the UNMODIFIED file with Abaqus's
own compile line. `external_dependency_unavailable`: a module or an include it
needs was never published beside it.

Everything else is unfinished work on this project's side, named as precisely
as the evidence allows -- `transform_refused`, `unsupported_formulation`,
`support_build_failed`, `original_job_failed`, `transformed_job_failed`,
`primal_disagreed`, `derivative_truncated`, `tangent_not_verified` -- because
the cluster a failure belongs to is what decides which fix is worth making,
and because calling any of them terminal would be relabelling this project's own
limitation as somebody else's.

The registry counts them separately for that reason. A completion figure that
pooled them would be a claim about the corpus made out of facts about the
pipeline.

```bash
python tools/build_corpus_registry.py \
    --transform <run>/transform_batch.json \
    --abaqus <run>/results/store_verification.jsonl \
    --store-fingerprint <T> --harness-fingerprint <H>   # the values the rows recorded (D-10, D-17)
```

Without `--json/--csv/--markdown` it overwrites the committed registry files.

## Things that stop a job that are properties of the source

Two are worth knowing about because they look like solver failures and are not.

A Fortran `PAUSE` waits on terminal input, so Abaqus sits on it until the job's
timeout and the licence is spent on nothing. It is a rung of its own.

A user subroutine that writes to standard output aborts Abaqus/Standard
2021.HF5 on the development workstation's installation, in the element loop,
with no diagnostic.
Measured on two decks identical but for one `print*` line: the one without it
completes and the one with it aborts, three runs out of three. 179 of the
corpus's 391 sources contain such a statement. The copy that is compiled has
them commented out -- which cannot change what the routine computes, because a
Fortran output statement assigns nothing unless it carries `IOSTAT=`, `ERR=`,
`END=`, `IOMSG=` or `SIZE=`, and one that does is left alone.

## Workspace layout the corpus tools assume

The corpus tools read data that is not in this repository. They expect the
checkout to sit beside it:

```text
<workspace>/                  this machine: $UMAT_OTI_WORKSPACE
  final-umat/                 this repository (any name)
  discovery_cache/            the downloaded sources (read only)
  transform_store/            transformed sources, one directory per key
  corpus_run/                 Abaqus passes (pass16/, pass18/, ...) and family files
  corpus_campaign/            batch evidence; the `campaign` evidence root
  corpus_assets/              content-addressed store of regression-case assets
  final-ra/                   Residual Assembler checkout (manifest `ra` root)
```

Nothing here is needed for the install checks, the examples or
`make case-ci`. Outside this layout, give every root explicitly:

| tool | roots it reads | how to point it elsewhere |
|---|---|---|
| `tools/build_corpus_manifest.py` | all of the above, relative to the **checkout's parent** | `--discovery-cache` / `UMAT_OTI_DISCOVERY_CACHE`, `--transform-store` / `UMAT_OTI_TRANSFORM_STORE`, `--corpus-run` / `UMAT_OTI_CORPUS_RUN`, `--campaign` / `UMAT_OTI_CAMPAIGN`, `--ra-repo` / `UMAT_OTI_RA_REPO`, `--families`, `--families-second-pass`; output `--out-dir` (default: the committed `paper_results/corpus/manifest/`) |
| `tools/corpus_cases.py` | `$UMAT_OTI_WORKSPACE` (default `~/softwarex_work`, **not** the checkout's parent): `discovery_cache/` under it; assets `$UMAT_CASE_ASSETS` (default `$UMAT_OTI_WORKSPACE/corpus_assets`); `freeze` also reads `~/softwarex_work/transform_store` | `UMAT_OTI_WORKSPACE`, `UMAT_CASE_ASSETS`; `check --work <dir>`. The store path has no override. |
| `tools/run_corpus_features.py` | fixed to `$UMAT_OTI_WORKSPACE` (`umat_oti.corpus_features.harness.WORKSPACE`): `discovery_cache/`, `transform_store/`, `corpus_run/pass16/`, families | `--verification-records`, `--registry`, `--out`, `--work` only. The cache and store have no override. |
| `tools/build_corpus_registry.py` | `--cache-dir` (default `UMAT_OTI_DISCOVERY_CACHE`, else `<checkout parent>/discovery_cache`); inventory and acquisition files in the repo | `--cache-dir`, `--inventory`, `--acquisition`, `--refusal-audit`; outputs `--json`, `--csv`, `--markdown` (defaults **overwrite** the committed `paper_results/corpus/` files) |
| `tools/verify_store_in_abaqus.py` | `--store` (default `~/softwarex_work/transform_store`), `--cache-dir` (default `UMAT_OTI_DISCOVERY_CACHE`, else `<checkout parent>/discovery_cache`) | `--store`, `--cache-dir`, `--triage`, `--proposals`, `--work-dir` (required), `--results-dir` (default `paper_results/store_verification/` in the repo). Needs Abaqus. |

A clone elsewhere on this machine, for example:

```bash
export UMAT_OTI_WORKSPACE=$UMAT_OTI_WORKSPACE
export UMAT_OTI_DISCOVERY_CACHE=$UMAT_OTI_WORKSPACE/discovery_cache
export UMAT_OTI_TRANSFORM_STORE=$UMAT_OTI_WORKSPACE/transform_store
export UMAT_OTI_CORPUS_RUN=$UMAT_OTI_WORKSPACE/corpus_run
export UMAT_OTI_CAMPAIGN=$UMAT_OTI_WORKSPACE/corpus_campaign
export UMAT_OTI_RA_REPO=$UMAT_OTI_WORKSPACE/final-ra
export UMAT_CASE_ASSETS=$UMAT_OTI_WORKSPACE/corpus_assets
```

Evidence locators (`campaign:...`, `corpus_run:...`) are resolved against
these roots, so they resolve only where the roots exist.

## Running the routine-level harness

No Abaqus. It reads the stored transform (read only) and the original source,
builds both with gfortran, and judges each feature:

```bash
PYTHONPATH=src python tools/run_corpus_features.py \
    --key 6c8ad0dfb0b64a98955acbae \
    --features primal_stress_state,ddsdde --out <dir>
```

`<key>` is a registry key (`paper_results/corpus/corpus_registry.json`,
field `key`; a case's `case.json` shows it under `reproduce.freeze`). A
relative `--out` is resolved against the current directory. Measured
2026-10-02 (10.9 s):

```text
6c8ad0dfb0b64a98955acbae irfancn__Abaqus-UMAT-elastic/umat_elastic.for (10.6s): primal_stress_state: verifiedx13; ddsdde: verifiedx13
26 records written to <dir>/corpus_features.jsonl (run 20261002T130023-43e33414, previous contents replaced)
2 manifest cells -> <dir>/manifest_cells.jsonl; merge-contract problems: [...]
```

One record per loading path and feature. `<dir>` also holds `roots.json`,
`run_id.json` and `work/`. The merge-contract problem above (`evidence root
'abs'`) means `<dir>` lies outside every evidence root, so the cells cannot be
merged into the manifest; write to a directory under `corpus_campaign/` when
they are meant to be merged.

By default the experiment for each key comes from pass16
(`corpus_run/pass16/results/store_verification.jsonl`) and keys from the
committed registry. For a store built for another pass, give that pass's rows
and registry: `--verification-records <pass>/results/store_verification.jsonl
--registry <registry.json>`.

## Reading a result

Everything is answerable from one record, and the interface reads the same
records:

```bash
streamlit run scripts/app.py        # tab 6, "Corpus"
```

or in Python:

```python
from umat_oti.app.corpus_view import load_run, histories, job_log

view = load_run("<run>/results", "<run>/work")
view.by_terminal_state
entry = view.entries[0]
entry.requirements            # what is missing, and why
entry.discovery               # what the amplitude search did
entry.tangent["states"]       # the sweep at each state
histories("<run>/work", entry.key)   # both builds, for plotting
job_log("<run>/work", entry.key, "original")   # the .sta and .msg
```

## A finite prefix is discovery evidence, not a verification

A run that produces good increments and then returns values that are not
numbers has located the edge of a material's numerical domain. That is what
an adaptive search is for, and the prefix is used for it.

It cannot carry a verdict. A UMAT marked `fully_verified` on a history that
later becomes non-finite has been verified on a truncated failed analysis:
the comparison drops everything after the break, and the frozen regression
fixture inherits a deck that does not run to completion, so every future
replay begins by reproducing a failure.

This was measured, not anticipated. `BodyForce-Growth-2Stages.for` reported
`verified` on 280 output records whose 23rd was a NaN, with primal agreement
of 1.16e-11 over what came before. That verdict is withdrawn.

Three things are now kept apart, because collapsing them is how a truncated
history became a verdict:

| field | what it means |
| --- | --- |
| `discovery_usable_prefix` | how far a run got, and where the domain edge is |
| `safe_loading_reconstructed` | the loading rebuilt to stop short of it |
| `complete_finite_verification_run` | a rerun that finished with nothing non-finite anywhere |

Only the third can be verified on. Alongside it the record separates what
the solver said from what the routine did, because Abaqus prints
`THE ANALYSIS HAS COMPLETED SUCCESSFULLY` about the solver:

`abaqus_job_completed`, `all_requested_outputs_present`,
`complete_history_finite`, `primal_agreed`, `derivatives_verified`.

### A record is not an increment

Abaqus calls a UMAT once per material point per increment. A single-element
C3D8 job of thirty-five increments writes 280 probe records; the same job on
a CPE4 writes 140. Neither number is thirty-five.

Counting the flattened records as increments made a verification report
"agreed over 280 increments" about a thirty-five increment analysis, and let
a prefix of two complete increments and six integration points of a third
clear a minimum of five. Histories are grouped by `(step, increment,
element, integration point)`; an increment is complete only when every
material point it should produce is present and finite. The counts are kept
under names that say what they are: `raw_output_records`,
`complete_increments`, `material_points_per_increment`,
`first_incomplete_increment`, `first_non_finite_material_point`.

### The repair is chosen from what the failure responds to

Shrinking the amplitude is right for one kind of failure and wrong for the
rest. Before anything is changed the failure is probed — the same loading at
half the amplitude, and at four times the increment resolution — and what
matters is whether the break MOVED, as a fraction of the path rather than as
a count of increments: refining fourfold turns "22 of 40" into "88 of 160",
and both are 55% of the same path.

`amplitude_limited`, `increment_resolution_limited`, `path_segment_limited`,
`step_transition_limited`, `time_limited`,
`initialization_or_state_limited`, `unknown_domain_failure`.

A failure whose location does not move when the amplitude is halved is not
controlled by the amplitude, and halving it again is the same experiment
driven less far, failing in the same place. Where the offending segment is
shortened or dropped, the record says which behaviour the experiment no
longer exercises — an experiment that stopped testing reversal must not be
reported as though it still did.

The safety margin is a first proposal, not a proof: what makes an endpoint
safe is a complete finite rerun at it, with the distance from the observed
failure recorded beside it.
