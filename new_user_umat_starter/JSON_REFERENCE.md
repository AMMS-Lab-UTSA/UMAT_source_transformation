# JSON contract reference

This page describes, field by field, the compact JSON contract that the
command-line tools, the GUI loader and the helper scripts read. Use it while
writing or checking a contract for your own UMAT. For the order of the steps,
see [README.md](README.md).

## Minimal shape

```json
{
  "name": "my_new_umat",
  "source": "../UMATs/my_umat.for",
  "jacobian": {
    "seed": "DSTRAN",
    "output": "STRESS",
    "target": "DDSDDE"
  },
  "promote": ["STRESS"],
  "replace": ["120-132"],
  "ntens": 6,
  "order": 1
}
```

`constant` and `real` are not required. Any variable you do not list is
classified automatically; the optional fields below let you override a
specific classification.

## Required fields

`name`

- Case label used in reports and output directories.

`source`

- Path to the UMAT source file.
- A relative path is looked up, in order, relative to the JSON file (when the
  contract is loaded from disk), relative to the current working directory, and
  relative to the repository root.
- Prefer a path relative to the JSON file, with the source kept beside the
  contract or in a known folder of the same checkout. Such a contract works on
  any machine that has the same checkout. An absolute path works only on the
  machine where it was written.

`jacobian.seed`

- The independent variable seeded with OTI directions.
- For the standard UMAT tangent this is normally `DSTRAN`.

`jacobian.output`

- The output variable whose derivatives are extracted.
- For the standard UMAT tangent this is normally `STRESS`.

`jacobian.target`

- The real array that receives the extracted derivatives.
- For the standard UMAT tangent this is normally `DDSDDE`.

`promote`

- Variables that are promoted to OTI values.
- These are usually the evolving stress-update quantities.

`replace`

- Inclusive 1-based line ranges of the old DDSDDE block to replace.
- Example: `"83-87"` means lines 83 to 87 inclusive.
- Use `scripts/show_source_lines.py` to find these ranges.

`ntens`

- Tangent size used for `DSTRAN(1:NTENS)` seeding.
- Typical values are 4 for plane problems and 6 for three-dimensional stress
  and strain.

`order`

- OTI order. The standard tangent workflow is first order, so this is normally
  `1`.

## Optional fields

`constant`

- Variables that stay constant during differentiation (material properties,
  fixed inputs).
- An override: any variable you do not list is classified automatically. Use it
  only to correct a variable the tool classified incorrectly.

`real`

- Variables that must stay real rather than OTI (for example `DDSDDE`, integer
  indices, loop counters).
- An override, inferred automatically when omitted.
- In code generation `constant` and `real` are equivalent (both stay REAL and
  are not promoted); the distinction is documentation only.

`description`

- Free-text case description.

`umat`

- The entry routine name, when the main routine is not the default detected
  `UMAT`.

`dependency_roots`

- A list of directories, relative to the contract, holding the published
  sources of helper routines that the entry file calls but does not define.
- The routine closure is resolved and written as one file, entry file first, so
  every line number in the contract still points at the same statement. A
  routine that no root defines is an error, not a guess.
- Resolved when the contract file is passed to `umat-oti-config` (or
  `scripts/transform_from_json.py`); `run_from_json.py` does not resolve it.
  Example: `benchmarks/UMAT_PCO.json`.

`validation`

- Optional overrides for the paired validation settings, for example:

```json
{
  "validation": {
    "compare": ["STRESS", "STATEV", "CONVERGENCE"],
    "absolute_tolerance": 0.0001
  }
}
```

- Recognised tolerance keys are `absolute_tolerance`, `relative_tolerance`,
  `ddsdde_absolute_tolerance` and `ddsdde_relative_tolerance`.

## Variable-role rules

- If you supply `promote`, `constant` and `real`, they must be disjoint.
- If the same variable appears in more than one role list, loading the contract
  fails.
- Use upper-case names, to match the rest of the repository and the scanner
  output.

## Advanced fields

`constitutive_jacobians`

- Optional contracts that extract additional constitutive Jacobians beyond the
  main `DDSDDE` path.
- Use this only if you are deliberately lifting helper-level constitutive
  outputs.
- Compact example:

```json
{
  "constitutive_jacobians": [
    {
      "id": "fjac_from_oti",
      "description": "Example constitutive Jacobian contract.",
      "seed": "G1",
      "seed_shape": "scalar",
      "seed_directions": 1,
      "output": "G1JAC",
      "output_shape": "scalar",
      "loop": {
        "top": 250,
        "reseed_after": 260
      },
      "extract_after": 265,
      "replace_variable": "G1JAC"
    }
  ]
}
```

Supported compact fields:

- `id`
- `description`
- `selected_umat`
- `seed`
- `seed_shape`
- `seed_directions`
- `seed_operating_point`
- `output`
- `output_shape`
- `loop`
- `extract_after`
- `extract_kind`
- `replace_variable`
- `replace_lines`
- `additional_extractions`
- `post_loop_restore`
- `debug_dump`

`helper_surfaces`

- Optional mappings that tell the loader how helper-local outputs map back to
  caller variables.
- Compact example:

```json
{
  "helper_surfaces": [
    {
      "helper": "KCONSTITU",
      "target": "G1JAC",
      "source": "G1"
    }
  ]
}
```

You need this section only for advanced helper-surface extraction.

`advanced`

- One optional block for extra Jacobian and higher-order requests. The loader
  accepts and validates it, but no code is generated from it yet. See
  [docs/contract_generalization.md](../docs/contract_generalization.md).

## Practical advice

- Start from `examples/elastic_minimal.json` or
  `templates/new_umat_minimal_template.json`.
- Keep the first attempt small.
- Add `validation`, `constitutive_jacobians` or `helper_surfaces` only after
  the base contract works.
