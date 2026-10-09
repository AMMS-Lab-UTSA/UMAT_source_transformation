# B20 package Hopper (harness): rules written BEFORE they were implemented or run (D-28)

Written 2026-10-08. Every rule applies to ALL sources; each changes how a measurement is taken or what
is staged/paired/placed, not what a counted gate means. Results are reported as separate lines beside
"106 of 242 as published (106 of 252 revised callee rule)": a freed source is freed from state X to state Y
only, never passed. Each rule has a planted-error canary and an offline A/B over the sources it could touch,
with the 112 fully_verified required to keep their status.

## H1. A wedge-meshed model is run on the author's wedge element

Observation (Bell D1, B19 diagnosis D2): decks meshed with C3D6/C3D6H/C3D15 were run on a unit hexahedron:
Alex (P1, 20470, 749), Car, Robot, Human-face, Bunny P1/P2, Model_car. The wedge has 2 (C3D6) or 9 (C3D15)
integration points, not 8, so a routine that assigns a thickness coordinate only for NPT 1,2 reads garbage at
NPT 3..8, and the author's mesh nodes are discarded because a wedge has 6 corners and a hexahedron 8, so the
element falls back to a unit cube where the growth tensor is singular.
Rule: when EVERY element type the author's deck attaches to the material is a wedge (C3D6, C3D6H, C3D15,
C3D15H), the verification runs that element type itself, on the corner coordinates of one element of the
author's mesh (a C3D15's midside nodes are the edge midpoints), and the expected number of material points
per increment is the element's own (2 or 9). A deck that mixes wedge and hexahedron elements for the same
material keeps the existing choice (the hexahedron family), so no row that does not mesh with wedges only changes.
Canary: a wedge deck is emitted with 6 (15) nodes and the wedge element name, not 8; a deck forced onto the
hexahedron for a wedge-only author must fail the node-count check; mixed decks are unchanged.
A/B: the manifest of every one of the 419 sources before and after: only the wedge-only decks differ.

## H2. The offline finite-difference replay stages the data files the Abaqus job staged

Observation: the replay work directory of each chosen tangent state holds no data file; a source that opens
`C:\Users\...\E0.CSV` (Human-face, Alex 20470, Alex 749, TendrilOfPumpkin) aborts "Cannot open file" in every
state. A name built through a PARAMETER (jpsferreira `DIR1='fibers.inp'` in an included file, joined to a job
directory by the source's own GETOUTDIR) was never seen by `opened_files`.
Rule: the replay of every chosen state (double and quad) stages, into its own directory and under the literal
name the source opens, the same files `data_files.stage` stages for the Abaqus job, searched beside the source
and through its repository (same roots, same base-name matching, same "required = status old" test). A file nobody
published is never supplied. A FILE= name that is a variable or PARAMETER is resolved through the PARAMETER
declarations of the source and its quoted includes and through earlier assignments of the same statement
block; pieces that cannot be resolved (a directory read at run time) are dropped, and the resolved base name is
staged beside the job and written into the job's run directory by the same path rewrite (relative traversal to the
staged copy) that `redirect` applies to literal names. Unresolvable names are reported, not guessed.
Canary: a source whose required file is unpublished is still reported missing; a replay without the staged file
must fail with the runtime's own message; a PARAMETER-named file is found by `opened_files`.
A/B: sources that open no file are unchanged byte for byte; the 112 verified list their data staging unchanged.

## H3. Abaqus-internal PTK/SMA symbols that the replay never enters are linked to aborting stubs

Observation: Worlthen `array_with_two_pixel_z.for` holds UEPACTIVATIONSETUP/UEPACTIVATIONVOL (PTK toolpath) and the
UMAT assigns `ptrb=SMAFloatArrayAccess(1)` whose pointee `b` is never read; the replay driver does not link.
G2c said: do not stub undocumented utilities. This rule does not give them semantics.
Rule: a symbol is linked to a stub only if it is on a closed list of Abaqus-internal PTK/SMA names, the source
references it, and the source does not define it. A SUBROUTINE stub, if entered, stops the run with status 8 and
the message "Abaqus-internal routine X was entered in a replay; it has no documented semantics here". A FUNCTION
stub returns the null address / zero and nothing else, so any use of its pointee crashes (status 139 or a runtime
error) instead of reading invented data. Therefore a replay that completes with these stubs proved that no stubbed
routine was entered, and that no pointee was read: the call count of the stubs is zero or their result is unused.
Canary: a source that calls a stubbed SUBROUTINE on the UMAT path stops with status 8, never completes; a source
that dereferences the null result fails.
A/B: only sources referencing those names change; every row that links today is byte-identical.

Closed list as implemented (all documented interfaces except the last two, which the same source calls only
from UEPACTIVATIONSETUP): PtkSetMeshAndEventSeries, PtkSetEventSeriesProperties, PtkCompute,
getEventSeriesSliceProperties, getEventSeriesSliceLG, PtkGetDataAccess, PtkGetNumIntersectedElements,
SMAFloatArrayCreateSP/DP, SMAIntArrayCreate, SMAFloatArrayAccess, SMAIntArrayAccess, SetTableCollection,
GetParameterTable.

H3b. The finite-difference replay is built with gfortran, which neither runs the C preprocessor on a `.for`
file nor accepts Cray pointers by default, and installs only `aba_param.inc`. Rule: the replay build installs the
other public Abaqus headers beside it (an existing file is never overwritten), and its flags gain `-cpp` when the
source has a preprocessor directive line (`#include`, `#define`, `#if`...) and `-fcray-pointer` when it declares a
Cray `POINTER(p, b)`, the two things the solver's own compile line (`-fpp`, ifort) does for the same text. A/B: the
13 sources with directives and the sources with Cray pointers are listed with their states; none of the 112
fully_verified has either.

## H4. Deck pairing and generation carry what the author's deck says

(a) Pairing by the routine's own dimensioning. A routine that dimensions arrays by `(NSTATV - a)/b` accepts only a
*DEPVAR for which `(DEPVAR - a)` is a positive multiple of `b`. A block whose DEPVAR leaves a remainder is not
this routine's material (the hybrid FGJD UMAT, `(NSTATV-4)/7`, was paired with cubeU.inp DEPVAR 10 instead of
cubeUH.inp DEPVAR 11). Applies to every source with such a declaration.
(b) A `*USER MATERIAL, TYPE=THERMAL` (or any TYPE other than MECHANICAL) block belongs to UMATHT or another user
subroutine and is never a UMAT's constants; the default and TYPE=MECHANICAL blocks are the UMAT's.
(c) Initial conditions. `*INITIAL CONDITIONS, TYPE=SOLUTION` values the author's deck lists for the material's
element set are carried into the generated deck and the manifest's initial state, in the Plan route as already in
the council route; `TYPE=STRESS, USER` is carried as `*INITIAL CONDITIONS, TYPE=STRESS, USER` exactly as
`TYPE=SOLUTION, USER` is. Nothing is defaulted: an absent card stays absent.
(d) `*ORIENTATION` keeps the author's SYSTEM keyword (RECTANGULAR, CYLINDRICAL, SPHERICAL) with the author's data
lines; the generator no longer hard-codes RECTANGULAR.
(e) `*USER MATERIAL` options. The paired deck's `HYBRID FORMULATION = TOTAL|INCREMENTAL` on the `*USER MATERIAL`
line of the material is carried into the generated `*USER MATERIAL` line (added after the single-source run of
the hybrid FGJD UMAT on cubeUH.inp failed at increment 1 without it: the generated line dropped the option the
author's deck states). Nothing is added when the author's line has none.
Canaries: DEPVAR 10 refused / 11 accepted for `/7`; a two-block material yields the six-constant block; a deck with
SOLUTION values and with STRESS,USER regenerates them; CYLINDRICAL survives.
A/B: pairing and generated decks of every source before/after: only sources with the construct differ.

## H5. The Jacobian-matched control is paired with the transformed run by the same increment

Observation (B19 diagnosis G9): `align_by_time` keys on (step, element, point, start time); Growth-CASE3 pairs a 5.0
increment of the control with a 1.25 increment of the transformed run that starts at the same time.
Rule: in the comparison of the Jacobian-matched control with the transformed run (`jacobian_matched_verdict` and the
first-parting-time helper) records are paired only if their increment sizes (DTIME, relative 1e-9) also agree;
records that carry none pair as before. The alignment note says "and increment size". The informational FE
comparison of the original with the converted run keeps the start-time key: the A/B shows one verified source
(SeaShell) would lose 8 informational pairs there, and the informativeness test reads those aligned lists, so that
comparison is outside this rule.
Expected: Growth-CASE3 then reads "did not walk the same increments" (not decided), not "disagree"; this alone is
not a pass: the control would have to follow the transformed run's incrementation, which is a gate-control redesign
and is not part of this batch.
Canary: two histories with equal start times and different DTIME pair nothing under the rule; equal DTIME pair
as before; the default call (no flag) is unchanged.
A/B: all stored histories of the 298 pass24 rows, control vs transformed, old key vs new key: only Growth-CASE3
loses pairs (184 -> 176); none of the 112 verified loses one.
