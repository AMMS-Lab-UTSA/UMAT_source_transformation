# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- A deck's own `*PARAMETER` values are substituted into its material
  constants. Abaqus resolves `<name>` at input-processing time, so a deck
  that writes `<k>, <mu>, <kappa>` read as publishing no constants at all,
  and the source paired to it was classified as needing material data its
  author had published in the same file. Reading them is not inventing them.
  Arithmetic is resolved too, because `bulk = mu*1e2` is the value the author
  wrote -- but by walking a parsed expression tree against a whitelist of
  arithmetic on numbers and known names, never by evaluating the text: a
  material constant is not a reason to run text out of a downloaded file. A
  call, an attribute, a subscript, an unbounded exponent or an unknown name
  is refused, and the constant it feeds stays unresolved, which leaves the
  vector short and reports the mismatch against the deck's own `CONSTANTS=`
  count rather than becoming a wrong number. Order in the file does not
  matter and a cycle stops rather than looping. Measured over the corpus:
  material vectors read from parameter-substituted decks that agree with
  their declared count went from 8 to 31.
- The documented body of an Abaqus utility the solver provides. A UMAT that
  calls `ROTSIG` publishes no definition for it, because Abaqus links it in;
  the helper lifter found nothing to lift and refused the source. That refusal
  was right -- an un-lifted external handed a hypercomplex array reads the
  first of seven doubles and returns a truncated derivative -- but the way
  past it is to supply the body, not to exempt the call. `ROTSIG` is one
  similarity transform on a symmetric tensor, so the ordinary lifter then
  transforms it like any other helper and the derivative flows through
  because the operation is bilinear in its input. Both storage conventions
  are honoured: `LSTR=2` stores engineering shear, twice the tensor entry,
  and rotating it as though it were the entry is a silent factor of two.
  Measured against a reference implementation over two hundred random
  rotations: worst relative error 9.7e-16 for stress, 6.1e-16 for strain.
  Six of the eleven corpus sources `ROTSIG` had stopped now transform; the
  other five stop on separate blockers (a LAPACK `DGESV` on the stress path,
  an unparsed helper header, a semantic check). `SPRIND` and `SPRINC` are
  deliberately not supplied: they solve an eigenproblem whose derivative is
  not the derivative of the algebra once eigenvalues coincide, so those
  sources keep their refusal until that case is handled deliberately.

### Fixed
- The Abaqus probe calls an argument what the routine calls it. The UMAT
  interface is positional, and position 23 is the state-variable count: the
  manual spells it `NSTATV` and **125 of the 251 sources in the store spell it
  `NSTATEV`**. The probe named `NSTATV` regardless, which in those routines is
  a name never declared -- an implicitly typed INTEGER with no value under
  `ABA_PARAM.INC` -- so `(STATEV(I),I=1,NSTATV)` walked off the end of the
  array and Abaqus died with a segmentation fault inside the formatted WRITE,
  in a stack whose top frame is `otis_probe_in`. Every such row was recorded
  as a failure of somebody's UMAT: eight of the first twenty-six rows of an
  Abaqus batch, all of them ours. Arguments are now resolved by position
  against the routine's own signature. 157 of 251 sources rename at least one
  (`NSTATEV` 125, `JSTEP` 24, `MATERL` 6, `KSLAY` 3, and singletons down to
  `NSTAT_VAR`). A signature too short to be the UMAT interface falls back to
  the canonical spellings rather than resolving positionally against a list
  that would map arguments to the wrong names. This also explains a symptom
  recorded earlier and left open: one source printed `NSTATV 0` in its first
  record and `********` in a later one, and which array overran was not
  established. It was this.
- The proposal writer no longer records the machine that ran the search.
  `DeckMaterial.as_dict` carries the absolute path it read -- right for an
  object in memory, wrong for a tracked file -- and it reached
  `proposed_corpus_entries.json` through the pairing record, where the
  repository-standards audit refused it. Scrubbing walks the whole structure
  rather than the fields known to carry a path today, so a field added later
  cannot reintroduce it.
- A fixed-form continuation is joined the way fixed form joins it. Blanks are
  insignificant inside a fixed-form statement, so a continuation break may fall
  in the middle of a name: the Jeff97 shell sources write `...G12*G23*G3` at
  the end of one line and `1+G13*G21*G32...` on the next, and the identifier is
  `G31`. The transform's three continuation joiners used `" ".join`, correct for
  free form and wrong for fixed, so the renamer saw `G3` -- not a name it knew
  -- left it alone, and emitted `*G3 1+`. The compiler read that back as `G31`:
  the original, un-renamed variable, which in those sources is never assigned.
  The answer was not wrong but nondeterministic, so no comparison could be
  relied on to catch it, and seven corpus sources carried it. The parser had
  the rule right all along, which is why the defect survived in sources that
  parse correctly. `no_identifier_split_by_insignificant_blanks` refuses an
  emitted file carrying the pattern, and the joiners now follow the form.
- Nothing reads a DDSDDE the transform has stopped filling.
  `old_ddsdde_assignments_disabled` asks whether the old writes to the array
  are gone; `no_ddsdde_read_after_disabled_assignment` asks the companion
  question, whether anything still reads what those writes used to put there.
  Four store entries passed the first and failed the second in silence,
  returning a stress of exactly zero -- a number that looks like an answer.
- A DATA-initialised constant is no longer promoted and silently zeroed. A
  DATA statement is not an assignment, so a name initialised by one and never
  written again read downstream as a variable with no value; it is the
  opposite, a compile-time constant. `data xi/1.d0,1.d0,1.d0,0.d0,0.d0,0.d0/`
  promoted, its shadow zeroed and the DATA values never delivered, multiplied
  a whole pressure term by zero in the returned stress and in every derivative
  taken from it -- while the file compiled, the transform reported success and
  all seventeen semantic checks passed. Such a name is kept real whatever the
  classifier guessed; the genuinely unhandled case, DATA-initialised *and*
  assigned, is a blocker naming the variable rather than an emitted shadow
  starting at zero.
- The seed follows the selected routine's own interface. `_build_contract`
  hard-coded `seeds = ["DSTRAN"]`, so a finite-strain model routine reached
  through a delegating UMAT -- one that receives DFGRD1 and no DSTRAN -- had
  `DSTRAN_OTI` written into a routine declaring `implicit none`. Where both
  are present neither is dropped.
- A UMAT that hands its whole body to another routine is followed
  (`fortran.callgraph.delegated_material_routine`): a single CALL passing
  STRESS and DDSDDE through to a routine defined in the same source.
- Whole-file scans are scoped to the routine being transformed. DO-loop ranges
  no longer pair an opener in one program unit with an `END DO` in another;
  region clamping drops a region with no overlap instead of inverting its
  bounds; "insert before RETURN" finds the selected routine's RETURN rather
  than the file's first; the finite-strain path no longer starts at SDVINI's
  `statev(1)=1.0d0`; and array shapes are read from the routine's own
  declarations, not file-wide first-wins.
- A live assignment is no longer commented out as old tangent. Where the
  anchor stage's classification is too wide it covered a statement the rest of
  the routine depends on, leaving `SSE` -- a UMAT output -- computed from an
  uninitialised variable. A claimed line is released when the name it assigns
  is still read by a line that will remain active; intermediates feeding only
  the tangent stay commented, which is the point of the classification.
- A comment is no longer read as a construct. The logical lines the
  unsupported-feature patterns match have already lost their comment marker,
  so `!I use Newton-Raphson to ...` arrived as text beginning `use ` and a
  source with no USE statement anywhere was reported as importing from a
  module. The column-1 rule is applied only in fixed form, where no statement
  may begin before column 7; in free form `c = 1.0` assigns to a variable.
- A promoted name is no longer substituted inside a character literal.
  `'STRESS is negative'` became `'STRESS_OTI is negative'` -- cosmetic in a
  message, not cosmetic in `IF (CMNAME(1:6) .EQ. 'ELAST1')`.
- The array, reduction, inquiry and conversion intrinsics are known (45 names
  to 130). `MATMUL(A,B)` and `A(I,J)` are the same shape to a reader that only
  knows names, so an unknown intrinsic was reported as a promoted variable
  indexed with no confirmed shape. Safe only because of the companion rule
  added with it: a name the source assigns is a variable whatever the list
  says, so an undeclared accumulator called `SUM` keeps its derivative.
- An assumed-size dummy is never given a shadow: `PROPS(*)` has its extent
  only in the caller, so `TYPE(...) :: PROPS_OTI(*)` is not a declaration and
  `DO OTI_HI = 1, *` is not a loop.
- A name in a COMMON block is kept real. Promoting one would change that
  block's storage layout in the transformed routine and in no other.
- The gh CLI is found where it is installed, not only where `PATH` mentions
  it. A per-user install under `~/.local/bin` left the client unauthenticated,
  and GitHub answers code search with 401 rather than degrading -- so the
  failure read as "code search is unavailable" instead of "you are not logged
  in", and discovery quietly stopped finding sources.
- The discovery triage compiles what it generates, and compiles each source as
  shipped first, so a source that never built is not charged to the
  transformer. Its baseline uses the same line-length flags as the generated
  compile; without that, twelve sources whose only fault was an 84-column line
  were recorded as "did not compile as shipped", which excused the transformer
  from every one of them.
- Fortran real literals are atomic again in every rewrite path. A promoted
  variable named `D` matched the `D` inside `1.d-12` and `xtol = 1.d-12` was
  emitted as `XTOL_OTI = 1.D_OTI-12` ("Missing exponent in real number"). The
  masking mechanism that had fixed this class lived inside
  `umat_oti.transform.helper_lifting` and the main source rewrite did not go
  through it; it now lives in `umat_oti.fortran.literals` and is applied at
  every identifier substitution, every identifier scan that drives a rename,
  and the integer-to-double promoter. The promoter's `(?<![eEdD][+-])`
  lookbehind is replaced by the mask: it read spelling rather than position and
  also blocked a genuine integer factor in `D-6*Y`.

### Added
- Discovery asks twelve differently-shaped code questions and, under
  `--repository-search`, six repository-index questions. One code query is one
  question and GitHub answers at most a thousand results to it however many
  hits it reports, so the corpus of 71 came from a single question read three
  pages deep and no number of extra pages would have reached further. Each
  source records which query found it. Candidates are deduplicated against the
  discovery cache as well as the pinned snapshot, and a VUMAT is excluded by
  signature -- a different interface, out of scope, and it matches several of
  these queries.
- Discovery refuses this project's own repository. The query set finds it
  because it genuinely contains UMAT sources, and a corpus assembled to show
  the transformer works on code nobody here wrote cannot contain the author.
- Two advisory proposers beside the deck pairing, both fenced the same way: a
  model may propose, deterministic code decides, and an unchecked proposal
  cannot be read.
  - `umat_oti.assist.blocker_triage` proposes a candidate cause for a failed
    source -- one construct from a closed vocabulary (the transformer's own
    `UNSUPPORTED_PATTERNS`, reused rather than restated) at one line number --
    and confirms it only by re-opening the source and finding that construct at
    that line, in code rather than in a comment. Exposed as
    `tools/run_discovery_triage.py --propose-causes`, off by default, writing a
    separate `blocker_proposals.json`. No stage, blocker kind, column or count
    in `discovery_triage.csv` is affected.
  - `umat_oti.assist.repair` proposes a minimal edit to generated Fortran that
    does not compile. The edit is made in a sandbox copy, so the transformer's
    output is never modified, and a repaired file is never counted as a
    transformed one. Three gates: the path resolves inside the sandbox and
    outside `src/` and the source cache; every edit must quote the line it
    changes exactly, so an invented edit cannot match; and the copy must compile
    under `gfortran` with no text-derived semantic check regressing and the
    sequence of semantically significant lines unchanged.
- `tests/test_assist_proposers_are_fenced.py` pins both against stub models that
  answer with confident nonsense, including a real-`gfortran` check that the
  compile gate is the compiler rather than the model's opinion.

## [1.1.0] - 2026-08-21

Adds the SoftwareX unified-derivative model on top of the 1.0.0 tangent pipeline.

### Added
- Unified `DerivativeRequest` canonical model (`umat_oti.core.derivative_request`)
  with a normalizer that maps the compact `jacobian` contract, legacy
  `extra_jacobian_contracts` / `constitutive_jacobians` lists, and the `advanced`
  higher-order block onto one internal representation.
- Parameter-sensitivity material-point driver
  (`umat_oti.validation.parameter_sensitivity`) for `DSIGMA_DP` and
  `DSTATEV_DP` on the focused J2 SoftwareX case, with centered finite-difference
  verification that replays the full loading path per perturbation.
- Derivative manifest emitter (`umat_oti.reports.manifest`) writing a
  machine-readable JSON that records schema version, source SHA-256, entry
  routine, `NTENS`/`NSTATV`/`NPROPS`, parameter/state maps, direction ordering,
  recovery-factor convention, and array shapes.
- Corpus discovery/regression tool (`umat_oti.corpus`) with a GitHub-API
  candidate discovery step, deterministic content hashing, license
  classification, and a per-round metrics report. Offline-safe: network is
  gated behind an explicit `--allow-network` flag.
- Unified Abaqus validator entry point
  `python -m umat_oti.validation.run_suite --abaqus-command abaqus` that
  detects the environment and produces an explicit "skipped: reason" report
  when Abaqus or a Fortran compiler is missing.
- Shared UMAT-OTI / Residual Assembler material-driver contract
  (`umat_oti.reports.driver_contract`, schema
  `umat-oti-driver-contract/1.1`).

### Changed
- Version bumped to 1.1.0 across `pyproject.toml`, `src/umat_oti/__init__.py`,
  `CITATION.cff`, `codemeta.json`, `.zenodo.json` (previously inconsistent:
  `__init__.py` said 0.1.0, everything else said 1.0.0).
- Repository URLs updated from the stale personal fork
  `santiagarcia/UMAT_source_transformation` to the canonical organization
  repository `AMMS-Lab-UTSA/UMAT_source_transformation` in
  `pyproject.toml`, `CITATION.cff`, `codemeta.json`, and the README badge.

## [1.0.0] - 2026-07-10

First public release accompanying the SoftwareX submission and archived on
Zenodo.

### Added
- GPL-3.0-only `LICENSE.txt` (verbatim GNU General Public License v3).
- `COPYRIGHT` file recording UMAT-OTI authorship and third-party attribution.
- `CITATION.cff`, `codemeta.json`, and `.zenodo.json` software metadata for
  citation and Zenodo DOI minting.
- `THIRD_PARTY_NOTICES.md` documenting bundled OTIlib/pyoti templates and UMATs.
- `CONTRIBUTING.md` and this changelog.
- `tests/` suite (package import, CLI, and end-to-end transform smoke test).
- GitHub Actions CI workflow across Python 3.10–3.12 on Linux and Windows.
- Rewritten user manual (`docs/UMAT_Source_transformation_user_manual.docx`)
  covering the current implementation, utilities, and tutorials.

### Changed
- Reorganized the repository into a conventional layout for publication: the
  convenience entry scripts (`app.py`, `transform_from_json.py`,
  `run_json_pipeline.py`) moved under `scripts/`, the completed benchmark
  contracts moved from `json_files_completed/` to `benchmarks/`, and the user
  manual moved under `docs/`.
- Package renamed from `umat-oti-standalone` to `umat-oti`; expanded
  `pyproject.toml` metadata (authors, license, keywords, classifiers, URLs).
- Relicensed the combined UMAT-OTI distribution from BSD-3-Clause to
  **GPL-3.0-only** to preserve compatibility with the GPL-licensed OTIlib/pyoti
  template components that the project bundles and builds upon.
- Corrected the OTI expansion to "order-truncated imaginary" across all
  metadata, matching the upstream library and the accompanying paper.

### Removed
- The internal WIP helper scripts `engine_app.py`, `validate_all_local.py`, and
  `verify_abaqus_local.py`, which were development aids not needed for the
  public release.
- Proprietary Abaqus verification-manual UMATs (`umatmst3.f`, `umathrt2.f`,
  `umathrt2.inp`) and their JSON contracts, which cannot be redistributed under
  an open-source license.

## [0.1.0]

- Initial standalone bundle: compact-JSON UMAT transformation runtime, Streamlit
  GUI, CLI entry points, and the 19-case completed benchmark set.
