---
title: "UMAT-OTI: Automated operational-Taylor tangent generation for Abaqus user-material subroutines"
authors:
  - name: "Santiago García Botero"
    affiliation: "The University of Texas at San Antonio"
    corresponding: true
    email: "TODO@utsa.edu"
  - name: "Harry Millwater"
    affiliation: "The University of Texas at San Antonio, Department of Mechanical Engineering"
  - name: "Arturo Montoya"
    affiliation: "The University of Texas at San Antonio, Department of Civil Engineering"
  - name: "David Restrepo"
    affiliation: "The University of Texas at San Antonio, Department of Mechanical Engineering"
keywords:
  - Abaqus
  - UMAT
  - automatic differentiation
  - operational Taylor integration
  - consistent tangent
---

<!--
This is a draft following the SoftwareX article structure. Before submission,
transfer the content into the official SoftwareX template (LaTeX or Word) from
the journal Guide for Authors, keep the length within ~6 pages, and complete
every TODO. Text in angle-bracket comments is guidance and must be removed.
-->

## Abstract

Finite-element analyses of nonlinear materials in Abaqus/Standard rely on
user-material subroutines (UMATs) that must return both the stress update and
its consistent Jacobian, `DDSDDE`. Deriving and hand-coding this tangent is
error-prone and a common source of poor convergence. UMAT-OTI is an open-source
tool that automatically rewrites an existing UMAT so that the consistent tangent
is computed by operational-Taylor (OTI) automatic differentiation, using a
compact, human-readable JSON contract to specify the differentiation. The tool
produces an Abaqus-submittable transformed source together with machine-readable
transform and validation reports, and can optionally validate the transformed
UMAT against the original at a material point. <!-- TODO: one-sentence headline result -->

## 1. Motivation and significance

<!--
Explain the scientific/engineering problem and why existing solutions are
insufficient. Suggested points to develop:
-->
- The consistent tangent `DDSDDE = d(STRESS)/d(DSTRAN)` governs the quadratic
  convergence of the Newton solver in Abaqus/Standard. Analytical tangents are
  tedious and error-prone; finite-difference tangents are inaccurate and slow.
- Operational-Taylor integration (OTI) provides exact, high-order derivatives
  without the truncation error of finite differences and without a full
  source-to-source AD rewrite of the constitutive logic.
- UMAT-OTI lowers the barrier to using OTI-based tangents by transforming an
  *existing* UMAT automatically from a small JSON contract, so users keep their
  validated constitutive code and gain an exact tangent. <!-- TODO: expand -->

## 2. Software description

### 2.1 Software architecture

UMAT-OTI is a Python package (`umat_oti`, under `src/`) organized into modules
that parse the Fortran UMAT, build a call graph, plan and apply the OTI
transformation, generate the OTI Fortran support modules, and optionally build
and run a material-point validation. The transformation is driven by a compact
JSON contract that names the variables to promote to OTI numbers, the code
regions to replace, the tensor size (`ntens`), and the differentiation order.

Entry points:

- `umat-oti-config` / `transform_from_json.py` — transform a single UMAT from a
  JSON contract.
- `umat-oti-batch` — transform (and optionally validate) a directory of
  contracts.
- `app.py` — a Streamlit GUI front end.

### 2.2 Software functionalities

- Source-to-source transformation of fixed- and free-form Fortran UMATs to emit
  an OTI-instrumented tangent.
- A compact JSON contract format with automatic role inference for variables
  (constant/real) and explicit override.
- Deterministic, machine-readable `transform_report.json` including the call
  graph, decisions, differentiation contract, and semantic checks.
- Optional original-vs-transformed validation at a material point (requires a
  Fortran compiler / Abaqus).
- A single Abaqus-submittable combined source file for direct `user=` submission.

### 2.3 Illustrative example

The bundled minimal isotropic-elasticity example transforms with a single
command and no Abaqus dependency:

```bash
python transform_from_json.py examples/elastic_minimal.json --out out/elastic
```

The run writes the transformed source (`elastic_oti.f`), a combined
Abaqus-submittable source, and `transform_report.json`, in which all semantic
checks report `true` and `transform_success` is `true`.

<!-- TODO: add a second, more representative constitutive example (e.g. one of
the bundled UMAT_* plasticity/viscoelastic models) and, if available, a figure
comparing the OTI tangent against the analytical/FD tangent. -->

## 3. Impact

<!--
Describe how the software improves research: new questions enabled, adoption,
performance/accuracy gains vs. prior practice. Suggested points:
-->
- Enables researchers to add exact consistent tangents to existing UMATs without
  manual differentiation, improving Newton convergence and reducing debugging
  time.
- The completed 19-case benchmark set demonstrates the approach across
  elasticity, plasticity, and viscoelasticity models. <!-- TODO: quantify -->

## 4. Conclusions

UMAT-OTI automates a routinely difficult and error-prone step in nonlinear
finite-element modeling. It is open source (BSD-3-Clause), tested in continuous
integration, and packaged for reuse. <!-- TODO: future work -->

## Acknowledgements

<!-- TODO: funding sources, grant numbers, and computing resources. -->

## References

<!-- TODO: cite the OTI method, Abaqus UMAT interface documentation, and related
automatic-differentiation work. -->
