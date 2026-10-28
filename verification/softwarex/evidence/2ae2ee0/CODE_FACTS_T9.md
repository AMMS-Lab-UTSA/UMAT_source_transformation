# Code facts for Quill (T9 and related markers), read from source at `2ae2ee0` unless stated

Builder: Ada, 2026-10-27. These were read from code and history. They were not executed, except where a
run is named. Paths are relative to the UMAT_source_transformation repository. "Unchanged since 8e12548" means
`git diff --stat 8e12548 2ae2ee0 -- <file>` printed nothing. Curie and Noether review these (T9).

## Q-60: where the internal-Jacobian probe sits (unchanged since 8e12548)
- `src/umat_oti/transform/local_jacobian_probe.py:284-319`: the probe **replaces the Newton update
  statement** on one increment with an IF block:
  `IF (KINC.EQ.<target>) THEN; [IF (counter.GE.2) RES=0]; <iterate>=PROPS(<seed slot>); ELSE <original update>; END IF`.
  It **sets** the iterate (assignment). It does not add a unit to it.
- The seed is a spare property slot `PROPS(NPROPS+1)` (`plan_probe_slots`, `:130-155`). The OTI build
  seeds only that one direction (`validation/internal_jacobian_validation.py`, the contract
  `parameters=((SEED_NAME, slots.seed_props),)`, around `:320-330`). DSTRAN is not seeded in this
  build, so no co-seeded strain directions exist to clear. All other inputs are real.
- Which iterate: a first, observing pass records the converged iterate. The seeded pass sets the iterate
  to that value at the update line, and the next trip round the loop evaluates the residual at it. The
  extracted coefficient is `GETIM(STATEV(residual slot),1)` = dF/dz at the converged z, with the incoming
  state unperturbed (`local_jacobian_probe.py:1-45`; `internal_jacobian_validation.py:230-312`). After
  the probe evaluation the residual is zeroed to force the loop to exit (`:301-307`).
- Guard: `probe_took_effect` requires ≥2 residual evaluations and a recorded iterate equal to the seed
  (`internal_jacobian_validation.py:296-312`). Without it, a zero would compare with a zero.
- Run evidence (R1, `evidence/2ae2ee0/r1/`): OTI −234601.99278664890 against −3G−H′ = −234601.99278664892.

## IR-12: the channel for internal-Jacobian output (unchanged since 8e12548)
- The output goes through spare STATEV slots **past the contract's declared NSTATV**: iterate, residual,
  hand-coded Jacobian, counter and sentinel, at NSTATV+offset+1…+5 (`local_jacobian_probe.py:130-155`).
  The standalone driver is built and run with the **extended** NSTATV (`internal_jacobian_validation.py`,
  `build_original_driver(..., nstatv=slots.nstatv, nprops=slots.nprops)`), so in that driver the slots are
  in bounds. A sentinel detects a source that writes past its declared NSTATV, and the probe block is then
  moved further out. This channel exists only in the standalone driver and is never used in an Abaqus job.

## Q-62: finite-strain seeding (CHANGED after V11)
- At `2ae2ee0`, the strain directions are seeded into the deformation gradient as a push-forward
  `dF = ε·F`: `DFGRD1_OTI(i,k) += c·E_d·DFGRD1(j,k)` (`src/umat_oti/transform/source_transform.py:4945-4991`).
  The Kirchhoff term `σ_ij δ_kl` is added to the extracted DDSDDE for gradient-driven sources
  (`:5461-5520`; enabled at `:3583-3589`).
- At `8e12548` (V11) the seed was additive, `dF = ε` (`source_transform.py:2915-2924` at that commit), and no
  Kirchhoff term existed (`grep -c -i kirchhoff` = 0). Fixed in `5cd9ad2` (2026-09-12). The FD reference
  that shared the wrong definition was fixed in `4d7036c` (2026-09-12). V11's finite-strain rows were
  therefore judged under the old definition. Curie's proposed falsification test has not been run.

## Curie-B2 / Curie-I5: paired-Abaqus decks and the 36 vs 19 count (read at 8e12548, the V11 evidence)
- Deck (`src/umat_oti/validation/job_builder.py:1109-1270` at 8e12548): a **single C3D8 unit cube**
  (CPE4 unit square for NTENS=4). Faces X0/Y0/Z0 are restrained in their normal directions. Loading is a
  **prescribed displacement** on X1 (tension, 1e-4, or 3e-3 for a "plastic probe"), or shear or mixed
  strain on Y1/Z1. One `*Static` step, initial increment 1.0 (0.25 for plastic probes), total 1.0.
  `nlgeom=NO` unless the mode names finite/large/nlgeom. Abaqus default solver tolerances. On ARC:
  `srun … --cpus-per-task=2` (`:16`). The deck is fully displacement-prescribed and homogeneous.
- Comparison tolerances: stress 1e-5 abs / 1e-7 rel, DDSDDE 5e-2 abs / 5e-3 rel
  (`validation/compare_results.py:18-21`).
- **DDSDDE reference in paired runs:** the original UMAT's own hand-coded DDSDDE. Both builds are
  instrumented to copy DDSDDE into extra SDV slots NSTATV+1…NSTATV+NTENS² (`job_builder.py:388-443`), which
  are read back from ODB field output (single precision). This compares two builds of the same routine.
  It is not an independent tangent check.
- **36 vs 19:** `paper_results/generality/generality_summary.json` `by_abaqus` counts 20 "passed (local
  paired round)" + 16 "passed (slurm 791506)" = 36 distinct canonical sources (+1 failed_execution, +6
  blocked). The **19** are the cases of `paper_results/tables/table2_abaqus_paired_validation.csv`
  (Slurm 791506: 18 passed, UMAT_VPDCL_R failed_execution). Those 18 collapse to 16 sources because
  visco_imp and visco_beam share one source and UMAT_ECO is attributed to the local round. The 20 "local
  paired round" sources come from `paper_results/abaqus_paired/abaqus_paired_round.csv` (30 rows, 23
  passed), and 15 of them are imported sweep models whose provenance is unresolved.

## Q-65: J2 tangent path (unchanged since 8e12548)
- `src/umat_oti/validation/actual_umat_higher_order.py:41-49`: 12 increments of
  `ΔE = (2.5e-4, 0, 0, 0, 0, 0)`. This is **uniaxial strain**: the other strain components are held at zero.
  Then state 13 `(3e-4, −1e-4, 0, 2e-4, 0, 0)` "multiaxial, plastic", state 14 `(−1e-3, 0,…)` "elastic
  unloading", and state 15 `(5e-4, 0, 0, −2e-4, 0, 0)` "multiaxial elastic reload". The model is `j2_props.f` via
  `examples/j2_actual_higher_order.json`. Branch and margin per state come from the tangent-round
  output (`evidence/<sha7>/rounds/tangent/results/`).

## Noether-D: direction ordering
- `src/umat_oti/oti/oti_directions.py`. **Both** statements hold at different levels: the flat GETIM index
  is graded by order (`flat_index` = sum of the sizes of the lower-order blocks + idx, `:77-83`). Within one
  order, directions are "grouped by largest basis index, lexicographic within" (`:1-17`, `:44-52`).

## Q-61
- (a) The generated OTI module overloads assignment only as OTI ← REAL (`ONUMMxNy_ASSIGN_R`, `INTENT(OUT)`
  OTI; e.g. the generated `otim6n1.f90:58-60, 264-282` in `evidence/2ae2ee0/r1/check/jacobian/`). No
  REAL ← OTI assignment exists, so an implicit OTI-to-REAL assignment fails to compile instead of
  truncating silently. Passing OTI values to REAL dummies through an implicit interface is refused in
  helper lifting (`src/umat_oti/transform/helper_lifting.py:325-343`, callback into the selected routine).
  I did not establish whether every such call path is refused.
- (b) SPRINC/SPRIND: the main transform supplies lifted definitions
  (`src/umat_oti/transform/abaqus_utility_definitions.py`, SPRINC/SPRIND/SINV added in B2, 2026-10-01). The
  **standalone parameter-sensitivity driver** still refuses them
  (`src/umat_oti/transform/parameter_sensitivity_transform.py:767, 791`). So the refusal is specific to
  the parameter-sensitivity path at `2ae2ee0`.

## Q-63 (partial)
- NTENS → (NDI, NSHR) comes from `voigt_layout` (`source_transform.py:5423-5430`). The CLI accepts NTENS
  3, 4 and 6.
- DDSDDT, DRPLDE and DRPLDT do not occur in `source_transform.py`. They are not differentiated and pass
  through as the source writes them.
- PNEWDT is not referenced by the transform. VUMAT does not occur in `src/umat_oti/transform/`.
- `UNSYMM` is written by the deck writer (`src/umat_oti/abaqus/deck.py:197`). I did not check its condition.
- SSE/SPD/SCD and the kinematic class of the 14 unclassified generality rows: not done.
