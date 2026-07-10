# Third-Party Notices

This project bundles or depends on third-party components. Their respective
licenses and attributions are listed below. UMAT-OTI as a whole is distributed
under the GNU General Public License v3.0 (GPL-3.0-only), a choice driven by the
GPL-licensed OTIlib/pyoti components that the project bundles (see section 1).
Bundled files remain the copyright of their original authors.

---

## 1. OTIlib / pyoti (Order Truncated Imaginary numbers library)

**Location in this repository:** `vendor/_otilib_upstream/`

Files:

- `vendor/_otilib_upstream/src/python/pyoti/python/base_derivs_fortran.f90`
- `vendor/_otilib_upstream/src/python/pyoti/python/core_functions.f90`

These are Fortran template files taken from the OTIlib / pyoti library, an
open-source algebra of Order Truncated Imaginary (OTI) numbers for efficient
arbitrary-order, multivariate automatic differentiation. This project uses them
to generate the complete OTI Fortran support modules that back the transformed
UMATs.

Upstream reference:

- Project: OTIlib / pyoti
- Author: Mauricio Aristizabal (UTSA; HYPAD group, https://ceid.utsa.edu/HYPAD/)
- URL: https://github.com/mauriaristi/otilib
- Upstream license: **GPL-3.0** (see `vendor/_otilib_upstream/LICENSE`)
- Version vendored: from the upstream `master` branch; a specific commit SHA
  was not recorded at the time of vendoring.

> **LICENSE COMPATIBILITY — RESOLVED.**
> OTIlib is licensed under **GPL-3.0**, a copyleft license. Because this project
> bundles OTIlib template code and compiles it into the generated OTI Fortran
> modules, the distributed/combined work is a derivative governed by the GPL.
> This project has therefore been **relicensed as GPL-3.0-only** (option 1
> below), which is the simplest path to compatibility: the UMAT-OTI authors'
> own files are GPL-compatible and are distributed as part of the GPL-licensed
> whole. A verbatim copy of the upstream license is included at
> `vendor/_otilib_upstream/LICENSE`.
>
> Alternatives that were considered but not adopted:
>
> 1. **Relicense this project as GPL-3.0.** *(Adopted.)*
> 2. **Obtain written permission / a compatible re-license** for the vendored
>    OTIlib files from Mauricio Aristizabal. Several authors of this project are
>    in the same UTSA/HYPAD group, so a permissive grant or dual-license for the
>    vendored templates could be arranged in writing if a future permissive
>    release is desired.
> 3. **Remove the vendored OTIlib files** and instead require users to install
>    OTIlib themselves, so it is a runtime dependency rather than bundled code.


---

## 2. Bundled UMAT source files (`UMATs/`)

**Location in this repository:** `UMATs/UMATs/ICP/`

The `UMAT_*.for` constitutive models and the files under `elasticity/`,
`plasticity_exp/`, `plasticity_imp/`, `spin/`, and `visco/` are the authors' own
UMAT implementations, distributed as part of this project under GPL-3.0-only.

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
