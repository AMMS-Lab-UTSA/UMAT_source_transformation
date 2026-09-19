# Advanced mode: one block for extra Jacobian and higher-order requests

This document specifies the optional `advanced` block of a compact JSON
contract. It is for contract authors who need more than the standard
`DDSDDE = dSTRESS/dDSTRAN` request, and for developers extending the code
generator. The standard contract fields are described in
[new_user_umat_starter/JSON_REFERENCE.md](../new_user_umat_starter/JSON_REFERENCE.md).

**Status: the loader is implemented; code generation is not.** An `advanced`
block is parsed, validated against the named vocabularies below, and normalised
into derivative requests (`umat_oti.core.derivative_request`). No emitter yet
generates Fortran from it: a transform of a contract that has one produces the
standard outputs only, and lists the advanced requests in its summary and in
`derivative_manifest.json` without computing them.

**Design decision: the original contract form stays unchanged.** Anything
non-standard that a Jacobian, a second-order term or a special material needs
goes into one optional top-level block called **`advanced`**. The user states
the extra computation there, and the tool generates it. A contract without an
`advanced` block behaves byte for byte as it did before the block existed.

## 1. The original form keeps working (unchanged)

```json
"jacobian": { "seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE" }
```

`DDSDDE[i][j] = d STRESS[i] / d DSTRAN[j]`, order 1, written directly. `order`,
`ntens`, `promote`, `replace`, `constant`, `extra_jacobian_contracts` keep their
current meaning. None of this is touched.

## 2. The `advanced` block

Optional, top-level. When present it fully describes **one extra computation**:
how to build/seed the independent variable(s), which derivative orders to read
into which target arrays, and an optional post-extraction transform. The tool
then generates that automatically.

```json
"advanced": {
  "routine":     "UHYPER",                 // optional: which routine to transform
  "seed":        ["BI1", "BI2", "AJ"],     // one variable or a list
  "seed_build":  "identity",               // how to construct the seed (default identity)
  "output":      "U",                      // quantity to differentiate
  "output_kind": "scalar",                 // scalar | tensor (default tensor)
  "extract": [                             // each derivative order -> a target array
    { "order": 1, "target": "UI1", "layout": "gradient" },
    { "order": 2, "target": "UI2", "layout": "hessian_voigt_sym" }
  ],
  "transform": null                        // optional spatial transform (see below)
}
```

The `//` comments are for explanation only; JSON itself has no comments.

**Named vocabularies.** These are the only accepted values: an unknown value
raises an error, so a typo never silently produces a wrong UMAT. To extend a
vocabulary, add a value together with its emitter.

- `seed_build`: `identity` · `green_lagrange_from_dfgrd1` · `invariants_from_dfgrd1`
- `extract[].layout`: `jacobian` (a standard `DDSDDE`-style Jacobian) ·
  `gradient` (1st derivs of a scalar, e.g. `UI1`) ·
  `hessian_voigt_sym` (2nd derivs, packing `11,22,33,12,13,23`, e.g. `UI2` / `ℂ`) ·
  `third_voigt` (`UI3`) · `pk2` · `material_tangent`
- `output_kind`: `tensor` (default) · `scalar`
- `transform`: `{ "push_forward": "dfgrd1", "objective_rate": "jaumann",
  "voigt": "engineering_shear" }`, where `objective_rate` is one of `jaumann` ·
  `green_naghdi` · `none` (default `none`), and `voigt` defaults to
  `engineering_shear`

### Non-interference rule (enforced in the loader)

`_expand_advanced` (in `umat_oti.core.config_loader`) returns nothing unless
an `advanced` block exists. The required-field validator relaxes the standard
`jacobian.{target,output,seed}` requirements **only when** `advanced` is
present, and then requires `advanced.output`, `advanced.seed` and at least one
`extract[].target` instead. When the loader was added, all 19 completed
benchmark contracts and `elastic.json` were confirmed to expand with no
`advanced` block and with unchanged output.

## 3. Why this shape

- **Original form intact**: standard contracts never mention `advanced`.
- **One obvious place for extras**: whatever a Jacobian, a second-order term
  or a special case needs goes in `advanced`, and the tool computes it.
- **Understandable & future-proof**: every capability is a short named value with
  a fixed meaning; new strain measures, rates, or targets are new values, not
  schema changes.

## 4. Two examples in `advanced` mode

### 4a. `UHYPER` hyperelastic: no transform, verifiable without Abaqus

A `UHYPER` routine that hand-codes `UI1/UI2` (for example on lines 18-26) lets
the OTI output be checked against those exact values in a standalone driver.

```json
{
  "name": "my_uhyper",
  "source": "path/to/your_uhyper.f",
  "promote": ["U"],
  "replace": ["18-26"],
  "ntens": 6,
  "order": 2,
  "advanced": {
    "routine": "UHYPER",
    "seed": ["BI1", "BI2", "AJ"],
    "output": "U",
    "output_kind": "scalar",
    "extract": [
      { "order": 1, "target": "UI1", "layout": "gradient" },
      { "order": 2, "target": "UI2", "layout": "hessian_voigt_sym" }
    ]
  }
}
```

### 4b. Energy-based `UMAT`: push-forward and Jaumann transform

```json
"advanced": {
  "seed": "EGREEN",
  "seed_build": "green_lagrange_from_dfgrd1",
  "output": "W",
  "output_kind": "scalar",
  "extract": [
    { "order": 1, "target": "STRESS", "layout": "pk2" },
    { "order": 2, "target": "DDSDDE", "layout": "material_tangent" }
  ],
  "transform": { "push_forward": "dfgrd1", "objective_rate": "jaumann",
                 "voigt": "engineering_shear" }
}
```

## 5. Implementation order

1. **Loader (done).** Parse the optional `advanced` block into the full
   config, and relax the validator only when `advanced` is present. Existing
   contracts are unaffected.
2. **`UHYPER` emitter (not yet implemented).** Multi-scalar seed, `gradient` and
   `hessian_voigt_sym` layouts, no transform. Verify the OTI values of `UI1` and
   `UI2` against the routine's hand-coded values in a standalone driver,
   without Abaqus.
3. **Transform emitter (not yet implemented).** `green_lagrange_from_dfgrd1`,
   push-forward, Jaumann rate and Voigt packing for the energy UMAT, validated
   against an independent finite-difference reference and against Abaqus.
