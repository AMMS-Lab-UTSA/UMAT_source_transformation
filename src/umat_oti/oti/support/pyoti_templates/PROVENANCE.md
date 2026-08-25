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
