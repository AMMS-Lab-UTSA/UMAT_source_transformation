# Troubleshooting a new contract

This page lists the common failures when transforming your own UMAT, what each
one means, and what to do. It follows the steps of [README.md](README.md); the
contract fields are described in [JSON_REFERENCE.md](JSON_REFERENCE.md).

## The source could not be resolved

**Symptom.** The loader says it could not resolve the UMAT source path.

**Fix.**

- A relative `source` is looked up relative to the JSON file, then the current
  working directory, then the repository root. Make it relative to the JSON
  file, not to the directory your shell happens to be in.
- Run `scripts/check_config.py --config path/to/file.json` again after fixing
  the path.
- For a contract uploaded through the browser, see
  [A relative path works in one place but not another](#a-relative-path-works-in-one-place-but-not-another).

## Required fields are missing

**Symptom.** The loader says the compact configuration must define the
explicit user contract fields, and names them.

**Fix.** Start from `templates/new_umat_minimal_template.json` and fill in every
required field: `name`, `source`, `jacobian.seed`, `jacobian.output`,
`jacobian.target`, `promote`, `replace`, `ntens` and `order`. `constant` and
`real` are optional.

## A variable has multiple roles

**Symptom.** The loader reports that a variable has multiple roles.

**Fix.** A variable may appear in only one of `promote`, `constant` and `real`.
Remove the duplicate and run `scripts/check_config.py` again.

## The anchor status is `needs_json_completion`

**Symptom.** `scripts/check_config.py` reports an anchor status of
`needs_json_completion`, or `scripts/run_from_json.py` exits with code 2.

**Meaning.** The contract loaded, but it does not yet identify enough of the
transform surface for the pipeline to proceed.

**Fix.**

- Re-check the `replace` line ranges: they must cover the whole old DDSDDE block
  and nothing else.
- If the file contains several routines, set `umat` explicitly.
- Compare with `examples/elastic_minimal.json` and the contracts in
  `benchmarks/`.

## I do not know what to put in `replace`

- Run `scripts/show_source_lines.py` on the source file.
- Find the old DDSDDE assignment block.
- Add inclusive 1-based line ranges such as `"83-87"`.
- Or let the tool find the block: `umat-oti jacobian path/to/YOUR_UMAT.for
  --ntens 6 --out DIR` writes the contract it inferred to
  `DIR/jacobian_contract.json`.

## No UMAT routine was detected

- Make sure the source file contains the entry routine you want.
- If the entry routine is not named `UMAT`, set the optional top-level `umat`
  field.

## The transform reports warnings, blockers or failed semantic checks

**Symptom.** The transform finishes with warnings or blockers, or with
`transform_success: false`.

**Meaning.** This does not automatically mean the contract is wrong. The
transformer checks its own output (for example, that no OTI value is passed to
a routine that was not transformed) and refuses rather than write a UMAT that
would compute the wrong derivative.

**Fix.**

- Read the transform report whose path is printed (`report_path`). Each
  blocker and failed semantic check names the variable, routine or line
  involved.
- If a warning says a helper routine was "neither lifted, inlined, nor
  transformed", the UMAT calls a routine defined in another file. Declare the
  folder that holds it in `dependency_roots` and run `umat-oti-config`, which
  resolves it (`run_from_json.py` does not).
- Compare with a working contract in `examples/` or `benchmarks/`.
- If the contract loads cleanly but the transform still refuses, the
  limitation may be in the transformer rather than in the contract. Please
  report it, with the contract and the source (see
  [CONTRIBUTING.md](../CONTRIBUTING.md)).

## A relative path works in one place but not another

**Symptom.** A relative `source` works from the helper scripts but not when the
same JSON is uploaded through the browser.

**Meaning.** An uploaded file has no location on disk, so its relative `source`
is looked up only against the working directory of the app and the repository
root.

**Fix.** Put the contract in `json_files/` or `user_jsons/` and pick it from
the list on tab **1. Load Config**, or use an absolute `source` path on the
machine running the app.

## I need more than the minimal contract

If the main `DDSDDE = dSTRESS/dDSTRAN` contract is not enough:

- start from `templates/new_umat_constitutive_template.json`;
- keep the main tangent contract working first;
- add `constitutive_jacobians` only where needed;
- add `helper_surfaces` only when helper-call data must be declared explicitly.
