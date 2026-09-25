# Third-Party Notices

This project bundles or depends on third-party components. Their respective
licenses and attributions are listed below. UMAT-OTI as a whole is distributed
under the GNU General Public License v3.0 (GPL-3.0-only), a choice driven by the
GPL-licensed OTIlib/pyoti components that the project bundles (see section 1).
Bundled files remain the copyright of their original authors.

---

## 1. OTIlib / pyoti (Order Truncated Imaginary numbers library)

**Location in this repository:** `src/umat_oti/oti/support/pyoti_templates/`

Files:

- `src/umat_oti/oti/support/pyoti_templates/base_derivs_fortran.f90`
- `src/umat_oti/oti/support/pyoti_templates/core_functions.f90`

These are Fortran template files taken from the OTIlib / pyoti library, an
open-source algebra of Order Truncated Imaginary (OTI) numbers for efficient
arbitrary-order, multivariate automatic differentiation. This project uses them
to generate the complete OTI Fortran support modules that back the transformed
UMATs.

Upstream reference:

- Project: OTIlib / pyoti
- Author: Mauricio Aristizabal (UTSA; HYPAD group, https://ceid.utsa.edu/HYPAD/)
- URL: https://github.com/mauriaristi/otilib
- Upstream license: **GPL-3.0** (see `src/umat_oti/oti/support/pyoti_templates/LICENSE`)
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
> `src/umat_oti/oti/support/pyoti_templates/LICENSE`.
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

### 2a. `UMATs/UMATs/ICP/UMAT_*.for` — ABAQUS-US (MIT)

The twelve files `UMAT_ECL_TEMP.for`, `UMAT_ECO.for`, `UMAT_HIN.for`,
`UMAT_NKH_1.02.for`, `UMAT_PCL.for`, `UMAT_PCLI.for`, `UMAT_PCLI_R.for`,
`UMAT_PCLK.for`, `UMAT_PCO.for`, `UMAT_VPDCL.for`, `UMAT_VPDCL_R.for` and
`UMAT_VPDCO.for` are **not** the UMAT-OTI authors' work. After line-ending
normalisation (CRLF to LF) each one is byte-identical to the file of the same
name under `UMATS/` in

- Project: ABAQUS-US (user elements and user materials for Abaqus)
- Author: Juan Gomez, Universidad EAFIT
- URL: https://github.com/jgomezc1/ABAQUS-US (branch `master`, checked 2026-09-18
  by SHA-256 of every file)
- Upstream license: **MIT** (`LICENSE.md` upstream), reproduced below.

The following files in this repository are adaptations of those UMATs and are
therefore also covered by the MIT notice below:
`parameter_sensitivity/models/sweep_real_ECL_TEMP/umat.for`,
`parameter_sensitivity/models/sweep_real_PCO/umat.for` and
`parameter_sensitivity/models/sweep_eco/umat.for`.

MIT is GPL-compatible; the files are distributed as part of the GPL-3.0-only
whole with their MIT notice kept:

```text
MIT License

Copyright (c) [2015] [Juan Gomez]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 2b. `UMATs/UMATs/ICP/{elasticity,plasticity_exp,plasticity_imp,spin,visco}/` and `ICP/index.html` — book companion code (licence not stated)

These files are the companion code of F. Dunne and N. Petrinic,
*Introduction to Computational Plasticity*, Oxford University Press, 2005
(ISBN 0 19 856826 6), Appendix B, "Fortran coding available via the OUP
website"; `index.html` is that appendix page. They are **not** the UMAT-OTI
authors' work, and neither the files nor the page state a licence. They are
not covered by this project's GPL-3.0 grant. **Before any publication or
release, the maintainers must confirm redistribution rights with the authors
or Oxford University Press, or remove these directories and have users
download the code from the publisher.**

### 2c. The authors' own UMATs

`UMATs/UMATs/generic_ps/` and the other `parameter_sensitivity/models/*/umat.for`
files (everything not listed in 2a) are the UMAT-OTI authors' own
implementations, distributed under GPL-3.0-only.

### 2d. Removed files and the public corpus

The proprietary Abaqus verification-manual UMATs (`umatmst3.f`, `umathrt2.f`
and their `.inp` files) have been **removed** from this repository because
they are copyrighted by Dassault Systèmes and cannot be redistributed under an
open-source license. Users who wish to reproduce those cases must obtain the
files from their own licensed Abaqus installation.

The public-UMAT corpus under `umat/` commits only each material's identity,
contract, results and the SHA-256 of the verified source bytes; the sources
themselves are fetched by `tools/materialize_umat_sources.py` into the
git-ignored `umat/*/materialized/` and are never redistributed (see
`umat/.gitignore`).

---

## 3. Python dependencies

Runtime dependencies (installed via pip, not bundled) and their licenses:

- `numpy` — BSD-3-Clause
- `pandas` — BSD-3-Clause
- `streamlit` — Apache-2.0

Development/test dependencies:

- `pytest` — MIT

---

## 4. Reference LAPACK / BLAS (optional public porting input)

The experimental OTI library audit uses Reference LAPACK `v3.12.1`, commit
`6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca`, from
https://github.com/Reference-LAPACK/lapack. Its upstream license is BSD-3-Clause.
The public source checkout is obtained separately, not bundled as package data.

Each audit output retains the upstream license as `LAPACK_LICENSE.txt` and
selected original source files, including their notices, under
`reference_sources/`. Keep these notices with derived source and binary
redistributions and satisfy the upstream license's attribution requirements.
The generated OTI support also depends on the GPL-licensed components in section 1.

See [the port status](docs/LAPACK_OTI_PORT.md) for scope and verification limits.
