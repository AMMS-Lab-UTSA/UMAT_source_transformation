# pyoti Fortran templates

`core_functions.f90` and `base_derivs_fortran.f90` are vendored from upstream
**OTILib** (pyoti), whose `LICENSE` travels with them in this directory.

They are read at run time by OTI module generation. They live inside the package
rather than under a top-level `vendor/` directory because a wheel ships only what
is under `src/`: with them outside, a pip-installed `umat_oti` fell back to empty
placeholder templates and emitted a module whose generic interfaces referenced
procedures that were never written, so the generated Fortran would not compile.

They are inputs to generation, not generated artefacts, and must not be edited
here. To update them, take the new upstream revision and record it in this file.

## Upstream revision (recorded 2026-10-27)

Both template files are byte-identical to upstream OTIlib
(https://github.com/mauriaristi/otilib) at commit
`de3f7fa2b1ba667dff054ad5ba1f6f41f4ba8b54` (2025-08-25), path
`src/python/pyoti/python/`:

| File | Git blob id, here and upstream at `de3f7fa` |
|---|---|
| `core_functions.f90` | `52a6a6e93e44608475672cf32be2872762d7377e` |
| `base_derivs_fortran.f90` | `5ac0ab9b200eec554f1e672587b2df65fefdaa45` |

This identifies matching **content**, not the commit the files were originally
vendored from. The same two blobs are present on upstream `master` at every
commit from `9f81983` (2025-07-09), the last upstream change to either file, to
`214c71d` (2026-09-27), the newest commit checked; `de3f7fa` is in that range.
`de3f7fa` is recorded because it is the revision pinned by the sibling
Enterprise/warp_hypad project.

`LICENSE` in this directory is the upstream `LICENSE` (the verbatim GNU GPL v3
text) preceded by a UTF-8 byte-order mark; apart from those 3 bytes the two are
identical.

Reproduce, with an upstream clone in `OTILIB`:

```bash
git hash-object core_functions.f90 base_derivs_fortran.f90
git -C OTILIB rev-parse de3f7fa:src/python/pyoti/python/core_functions.f90
git -C OTILIB rev-parse de3f7fa:src/python/pyoti/python/base_derivs_fortran.f90
git -C OTILIB log --format='%h %ad' --date=short -- src/python/pyoti/python/core_functions.f90 src/python/pyoti/python/base_derivs_fortran.f90
```
