# Verified materials

Every material in this collection passed **Abaqus verification**. That means,
for each one:

1. The **original** UMAT ran in Abaqus on a generated single-element deck and
   produced a converged stress and state history.
2. The **OTI-converted** UMAT ran in Abaqus on the *same* deck under the same
   physical conditions.
3. Their stress and state histories agreed across the loading path.
4. The **OTI tangent** agreed with a **finite difference of the original
   implementation**, replayed from beginning-of-increment states Abaqus
   actually reached, at several states along the path, over a sweep of step
   sizes spanning at least a decade.

Compiling is not verification and did not put anything here. Neither did a
standalone driver: step 3 and step 4 both require Abaqus to have executed
both builds.

## What a result here does not say

- The loading is a **verification probe chosen by this pipeline** —
  prescribed extension, then shear, then a reversal. It is **not** a
  reproduction of the author's own example, and a result here must not be
  read as one.
- The **meaning** of the material constants is not certified. The paired deck
  supplies values, not names, and nobody here has confirmed what they model.
- A passing tangent check covers `DDSDDE` at the states listed in that
  material's `README.md`. It does **not** cover parameter sensitivities,
  higher orders, or loading regimes outside the probe.
- **Physical correctness of the model is not in question here.** What is
  established is that the conversion computes what the original computes.

## Layout

```
umat/
  registry.json                  the authoritative list, one entry per material
  <material-id>/
    contract.json                what was run, and where every input came from
    results.json                 what happened, per execution and per state
    source.json                  upstream identity and the SHA-256 verified
    README.md                    what this material establishes, and what it does not
    verification/
      generated.inp              the deck both builds were run on
      original_history.json      the original build's probe output
      converted_history.json     the converted build's probe output
  materialized/                  git-ignored; see below
```

`<material-id>` is `<owner>-<repo>--<file-stem>--<digest>`. The digest is over
the full source path, because one repository can ship the same file name in
twenty example directories — Jeff97 ships `BodyForce-Growth-2Stages.for` in
nineteen — and a name collision would overwrite one material's evidence with
another's.

## The sources are not here

These are other people's UMATs, mirrored for study. **A public repository
without an explicit licence grant is not permission to redistribute it**, so
the files themselves are not committed. What is committed is each material's
identity: the upstream repository, the path within it, and the SHA-256 of the
exact bytes that were verified.

To put them on a machine that needs them:

```bash
python tools/materialize_umat_sources.py                  # from the local mirror
python tools/materialize_umat_sources.py --allow-network   # clone from upstream
```

They land in `umat/materialized/`, which is git-ignored. Anything whose digest
no longer matches what was verified is **refused**: a file that has changed
upstream is not the file this evidence is about, and attaching an old verdict
to new bytes would be wrong.

`--allow-network` is off by default, because a verification run should not
depend on the network being up or on upstream still existing.

The one exception is a material this project owns — the UMATs under `UMATs/`,
distributed under this repository's own licence. Those say
`"redistributed_here": true` in their `source.json`.

## Relationship to `UMATs/`

`UMATs/` is unchanged and still holds this project's **own** UMAT sources,
which are distributed under the repository licence. `umat/` is a different
thing: it is the **evidence** for materials that have been verified, whoever
wrote them. A material can appear in both — its source in `UMATs/`, its
verification record here — and its `source.json` says so.

## Promotion and regression

Promotion is deliberate. A material arrives here only when someone runs:

```bash
python tools/promote_verified_umats.py \
    --results <run>/store_verification.jsonl \
    --work-dir <run>/work
```

which reads a completed batch and copies across only the rows that reached
`verified`.

**A regression run never writes here.** It reads `registry.json`, re-runs
those materials, and fails if any of them stops verifying:

```bash
python tools/verify_store_in_abaqus.py --mode regression \
    --baseline umat/baseline.json
```

Missing Abaqus is not a pass. A required material that is blocked, or that
silently stops being attempted, fails the run — an entry that is no longer
attempted leaves no failing row to notice, which is exactly what a regression
exists to catch.
