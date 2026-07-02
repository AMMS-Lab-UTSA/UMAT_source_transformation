# Advanced mode: a deposit for extra Jacobian / higher-order instructions

Status: **loader implemented; codegen next.**

Decision: **keep the original contract form unchanged.** Anything non-standard a
Jacobian, a second-order term, or a special material needs goes into one optional
top-level block called **`advanced`**, where the user *deposits the extras* and
the tool computes them automatically. A contract without an `advanced` block
behaves byte-for-byte as it does today.

## 1. The original form keeps working (unchanged)

```json
"jacobian": { "seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE" }
```
`DDSDDE[i][j] = d STRESS[i] / d DSTRAN[j]`, order 1, written directly. `order`,
`ntens`, `promote`, `replace`, `constant`, `extra_jacobian_contracts` keep their
current meaning. None of this is touched.

## 2. The `advanced` block — where you deposit the extras

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

Named vocabularies (the only accepted values — an unknown value raises, so a typo
never silently produces a wrong UMAT; extend by adding a value + its emitter):

- `seed_build`: `identity` · `green_lagrange_from_dfgrd1` · `invariants_from_dfgrd1`
- `extract[].layout`: `jacobian` (a standard `DDSDDE`-style Jacobian) ·
  `gradient` (1st derivs of a scalar, e.g. `UI1`) ·
  `hessian_voigt_sym` (2nd derivs, packing `11,22,33,12,13,23`, e.g. `UI2` / `ℂ`) ·
  `third_voigt` (`UI3`) · `pk2` · `material_tangent`
- `transform`: `{ "push_forward": "dfgrd1", "objective_rate": "jaumann",
  "voigt": "engineering_shear" }`

### Non-interference rule (enforced in the loader)

`_expand_advanced` returns nothing unless an `advanced` block exists, and the
required-field validator only relaxes the standard `jacobian.{target,output,seed}`
requirements **when** `advanced` is present. Verified: all 19 completed configs +
`elastic.json` expand with no `advanced` block and identical output.

## 3. Why this shape

- **Original form intact**: standard contracts never mention `advanced`.
- **One obvious place for extras**: the user deposits whatever the Jacobian / 2nd
  order / special case needs in `advanced`; the tool computes it.
- **Understandable & future-proof**: every capability is a short named value with
  a fixed meaning; new strain measures, rates, or targets are new values, not
  schema changes.

## 4. Two examples in `advanced` mode

### 4a. `UHYPER` hyperelastic — no transform, verifiable without Abaqus
`umathrt2.f` hand-codes `UI1/UI2` (lines 18–26), so AD output is checked against
those exact values in a standalone driver.

```json
{
  "name": "umathrt2_uhyper",
  "source": "../UMATs/UMATs/ICP/umathrt2.f",
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

### 4b. energy-based `UMAT` — push-forward + Jaumann transform
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

1. **Loader (done).** Parse the optional `advanced` block into the full config;
   relax the validator only when `advanced` is present. Regression-clean.
2. **`UHYPER` emitter (next).** Multi-scalar seed, `gradient` + `hessian_voigt_sym`
   layouts, no transform. Verify AD `UI1/UI2` vs. `umathrt2.f`'s hand-coded values
   in a standalone driver — no Abaqus.
3. **Transform emitter.** `green_lagrange_from_dfgrd1` + push-forward + Jaumann +
   Voigt for the energy UMAT, validated against Ravi's FD reference and Abaqus.
