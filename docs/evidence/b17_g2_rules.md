# B17 package G2 (Hopper): rules written BEFORE they were run (D-28)

Written 2026-10-07, before any all-row re-run of D-12 with the new probe and before
the NTENS change was applied to a store. Nothing in this file changes what a counted
gate means; each rule is a change to how a measurement is taken, and each is applied
to every source.

## G2a. The D-12 init probe is built the way the verified original is built

Observation that motivates it (measured before this rule, on the 9 registry rows in
state undefined_in_original, 8 of them in the 242): the probe was built with
gfortran (`-finit-real/-integer/-logical` zero / snan / inf) while Abaqus builds the
verified original with ifort and the Abaqus flag set (`ABAQUS_IFORT_FLAGS`, `-auto`,
`-extend_source`). ifort was used only if gfortran could not build the file.

Rule:
1. The primary probe is the ifort build set with the Abaqus flags and
   `-init=zero,arrays` / `-init=huge,arrays` / `-init=minus_huge,arrays` (ifort's
   `-init=snan` traps on the first read, so it is not used). The source form is the
   one the file is compiled in by the solver (fixed or free by extension, the same
   `-extend_source`).
2. An output is undefined_in_original iff the primary probe's zero build differs
   from the huge or the minus_huge build on it (bit comparison, as before). The
   zero build is still run twice (a difference there is hidden state, never
   "undefined").
3. If the primary probe cannot be built or run, the gfortran set decides (as it
   decided before), and the record says so. "Cannot be built or run" includes: a
   build failed, the zero build did not replay, a poisoned build stopped (a trapped
   value establishes nothing about which output it reaches), the zero build was
   not deterministic. In every such case the gfortran set decides.
4. The gfortran set is still run and recorded as the secondary probe. A disagreement
   between the two is REPORTED per source and does not decide.
5. Applies to every row that reaches D-12; the result is reported as a separate line
   beside the published figure (106 of 242 as published).

Canary: a source that really reads an uninitialised variable is still flagged
undefined_in_original (tests/test_init_probe_compiler.py).

## G2b. The transform is built at the NTENS of the deck's element

Observation: `tools/transform_all.py::_ntens_of` chose the element from the pairing
recorded in proposed_corpus_entries.json, while the verification chooses it from
`umat_oti.abaqus.experiment.plan` (deck_pairing + formulation.settle). The two pick
different decks for some sources, so the stored transform was built at NTENS 6 / 2 / 6
and the manifest called the material at 4 / 3 / 2 (PhaseFieldComp, Bilinear-CZM,
czmHealing), and the guard in verify_one refused them (correctly: the seed
directions would not correspond to the element's components).

Rule: ONE function decides the element, `umat_oti.abaqus.experiment.deck_element`,
which is the first two steps of `plan` (pairing, settle). `_ntens_of` and `plan` both
call it, so the NTENS a source is transformed at and the NTENS it is verified at are
the same value read once. Where the planner cannot name an element, the previous
fallback (proposal pairing, triage row, default 6) is kept and recorded as such. The
guard in verify_one is kept and is the canary: a transform at the wrong NTENS is
refused, never run.

Canary: a deliberately wrong NTENS mapping must fail (tests/test_transform_ntens_follows_the_deck.py).

## G2c. Abaqus-supplied utilities are linked in the offline drivers, from measured semantics

Written 2026-10-07 after the survey (corpus_campaign/batches/B17/hopper_g2/utilities.md)
and the measurements of the real solver, and BEFORE the all-row re-run with the stubs.

Rule:
1. A utility the solver provides is stubbed in the offline replay drivers only if its
   semantics are documented or have been measured against the real Abaqus on a
   one-element job, and the stub is checked against a hand-computed value. The stub
   must not hide or invent an uninitialised read: it writes every output it owns, and
   where the solver's behaviour cannot be reproduced (a repeated principal value with
   a shear, whose order is algorithm-dependent) it STOPS instead of returning a guess.
2. A utility with no documented semantics (ptk*, the SMA* wrappers) is not stubbed;
   the source keeps its "not established" verdict with that reason.
3. Applies to every source: D-12 is re-run offline over every row that reaches it,
   with and without the new stubs. Sources that newly reach the gate are NOT counted
   passed; they are reported as "106 of 242 plus j" beside "106 of 242 as published",
   and pass24 decides them.

Canary: a source that reads an uninitialised variable after calling SPRIND is still
flagged undefined_in_original (tests/test_abaqus_utility_stubs.py).
