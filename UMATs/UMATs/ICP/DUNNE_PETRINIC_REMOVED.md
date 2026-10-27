# Dunne & Petrinic book code: removed from this repository

The folders `elasticity/`, `plasticity_exp/`, `plasticity_imp/`, `spin/` and
`visco/` in this directory, and `index.html`, used to hold the companion Fortran
code of

> F. Dunne and N. Petrinic, *Introduction to Computational Plasticity*,
> Oxford University Press, 2005 (ISBN 0 19 856826 6), Appendix B,
> "Fortran coding available via the OUP website".

Neither the files nor the publisher's page state a licence, so the UMAT-OTI
authors cannot redistribute them under GPL-3.0 (see `THIRD_PARTY_NOTICES.md`,
section 2b). They were removed on 2026-10-27, before any publication or
release, as that section requires. The `UMAT_*.for` files in this directory
come from ABAQUS-US (MIT) and are not affected.

## Using the examples that need them

Several configurations, examples and validation studies still name these
files at their old paths, for example `elasticity/elastic.f`,
`plasticity_imp/code_imp.f` and `visco/visco_imp.f`. To run them, obtain the
code from the book's companion material (Oxford University Press) and place
each file at its old path:

| Folder | Files referenced by this repository |
|---|---|
| `elasticity/` | `elastic.f` |
| `plasticity_exp/` | `code_exp.f` |
| `plasticity_imp/` | `code_imp.f` |
| `spin/` | `spin_elastic.f`, `spin_elas_def.f` |
| `visco/` | `visco_beam.f`, `visco_imp.f` |

These folders are listed in `.gitignore`, so downloaded copies are not
committed again. Tests that need these files are skipped when the files are
absent. The files remain in this repository's git history.
