# Third-Party Notices

This project bundles or depends on third-party components. Their respective
licenses and attributions are listed below. The bundled files remain under the
license of their upstream projects, not the BSD-3-Clause license that covers
the rest of this repository.

---

## 1. OTIlib / pyoti (Operational Taylor Integration library)

**Location in this repository:** `vendor/_otilib_upstream/`

Files:

- `vendor/_otilib_upstream/src/python/pyoti/python/base_derivs_fortran.f90`
- `vendor/_otilib_upstream/src/python/pyoti/python/core_functions.f90`

These are Fortran template files taken from the OTIlib / pyoti hyper-dual /
operational-Taylor automatic differentiation library. This project uses them to
generate the complete OTI Fortran support modules that back the transformed
UMATs.

Upstream reference:

- Project: OTIlib / pyoti
- Author: Mauricio Aristizabal (UTSA; HYPAD group, https://ceid.utsa.edu/HYPAD/)
- URL: https://github.com/mauriaristi/otilib
- Upstream license: **GPL-3.0**
- Version / commit vendored: <TODO: record the exact commit SHA used>

> **LICENSE-COMPATIBILITY DECISION REQUIRED BEFORE PUBLICATION.**
> OTIlib is licensed under **GPL-3.0**, a copyleft license, while the rest of
> this repository is proposed under BSD-3-Clause. Because this project bundles
> OTIlib template code and compiles it into the generated OTI Fortran modules,
> the distributed/combined work is affected by the GPL. You must choose one of:
>
> 1. **Relicense this project as GPL-3.0** (simplest path to compatibility; BSD
>    code is GPL-compatible, so your own files can remain BSD-headed inside a
>    GPL-licensed whole).
> 2. **Obtain written permission / a compatible re-license** for the vendored
>    OTIlib files from Mauricio Aristizabal. Several authors of this project are
>    in the same UTSA/HYPAD group, so a permissive grant or dual-license for the
>    vendored templates should be straightforward to arrange in writing.
> 3. **Remove the vendored OTIlib files** and instead require users to install
>    OTIlib themselves, so it is a runtime dependency rather than bundled code.
>
> Also add a verbatim copy of the upstream license as
> `vendor/_otilib_upstream/LICENSE`. Do not publish until this is resolved.


---

## 2. Bundled UMAT source files (`UMATs/`)

**Location in this repository:** `UMATs/UMATs/ICP/`

The `UMAT_*.for` constitutive models and the files under `elasticity/`,
`plasticity_exp/`, `plasticity_imp/`, `spin/`, and `visco/` are the authors' own
UMAT implementations, distributed under this project's BSD-3-Clause license.

> **NOTE:** The proprietary Abaqus verification-manual UMATs (`umatmst3.f`,
> `umathrt2.f`, and their `.inp` files) have been **removed** from this
> repository because they are copyrighted by Dassault Systèmes and cannot be
> redistributed under an open-source license. Users who wish to reproduce those
> specific cases must obtain the files from their own licensed Abaqus
> installation.
>
> `elastic.f` (`UMATs/UMATs/ICP/elasticity/`) is a minimal isotropic-elasticity
> UMAT used as the smallest example. If any bundled UMAT is derived from Abaqus
> documentation examples, confirm redistribution rights before publication.

---

## 3. Python dependencies

Runtime dependencies (installed via pip, not bundled) and their licenses:

- `numpy` — BSD-3-Clause
- `pandas` — BSD-3-Clause
- `streamlit` — Apache-2.0

Development/test dependencies:

- `pytest` — MIT
