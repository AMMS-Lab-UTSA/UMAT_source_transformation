# Verifying a corpus of other people's UMATs

This is the loop that turns a directory of downloaded Fortran into a set of
materials with evidence behind them, and a set of named reasons for the rest.

Nothing in it is verified because it downloaded, because it contains the word
UMAT, because it parses, because it transforms, because the generated Fortran
compiles, because Abaqus started, or because a report was produced. A material
is verified when six things have happened, in this order, and every one of them
left an artefact:

1. the ORIGINAL routine ran in Abaqus;
2. the OTI-converted routine ran in Abaqus, on the same deck;
3. their stress and state histories agreed over the whole path;
4. the loading activated whatever the material actually does;
5. the OTI tangent agreed with a converged finite difference of the original
   at several smooth states;
6. the whole experiment was frozen so a later commit can be measured against it.

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

Everything else is unfinished and OURS, named as precisely as the evidence
allows -- `transform_refused`, `unsupported_formulation`,
`support_build_failed`, `original_job_failed`, `transformed_job_failed`,
`primal_disagreed`, `derivative_truncated`, `tangent_not_verified` -- because
the cluster a failure belongs to is what decides which fix is worth making,
and because calling any of them terminal would be relabelling our own
limitation as somebody else's.

The registry counts them separately for that reason. A completion figure that
pooled them would be a claim about the corpus made out of facts about the
pipeline.

```bash
python tools/build_corpus_registry.py \
    --transform <run>/transform_batch.json \
    --abaqus <run>/results/store_verification.jsonl
```

## Things that stop a job that are properties of the source

Two are worth knowing about because they look like solver failures and are not.

A Fortran `PAUSE` waits on terminal input, so Abaqus sits on it until the job's
timeout and the licence is spent on nothing. It is a rung of its own.

A user subroutine that writes to standard output aborts Abaqus/Standard
2021.HF5 on this installation, in the element loop, with no diagnostic.
Measured on two decks identical but for one `print*` line: the one without it
completes and the one with it aborts, three runs out of three. 179 of the
corpus's 391 sources contain such a statement. The copy that is compiled has
them commented out -- which cannot change what the routine computes, because a
Fortran output statement assigns nothing unless it carries `IOSTAT=`, `ERR=`,
`END=`, `IOMSG=` or `SIZE=`, and one that does is left alone.

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
