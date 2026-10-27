# Dunne & Petrinic book code: removed from the current tree

The folders `elasticity/`, `plasticity_exp/`, `plasticity_imp/`, `spin/` and
`visco/` in this directory, and `index.html`, used to hold the companion Fortran
code of

> F. Dunne and N. Petrinic, *Introduction to Computational Plasticity*,
> Oxford University Press, 2005 (ISBN 0 19 856826 6), Appendix B,
> "Fortran coding available via the OUP website".

Neither the files nor the publisher's page state a licence, so the UMAT-OTI
authors cannot redistribute them under GPL-3.0 (see `THIRD_PARTY_NOTICES.md`,
section 2b). The `UMAT_*.for` files in this directory come from ABAQUS-US
(MIT) and are not affected.

Status of the copies (2026-10-27):

- The source folders and `index.html` were removed from the working tree on
  2026-10-27. **They had already been distributed**: they are in the public
  repository's history from the initial import (`938b821`), in tag `v1.0.0`
  (`fe40e9f`, 2026-07-10), in the 1.1.0 release recorded in `CITATION.cff`
  (2026-08-21), and in the trees of other branches. Removing them from the
  current tree does not withdraw those copies.
- Derived copies under `paper_results/` were also removed: the seven
  `paper_results/arc_791506/paired_batch/validation/<case>/original_umat_with_ddsdde_sdv.f`
  files (cases code_exp, code_imp, elastic, spin_elastic, spin_elas_def,
  visco_beam, visco_imp) and the transformed `code_imp_oti.f` and
  `code_imp_oti_combined.f90` in `paper_results/actual_umat_higher_order/code_imp/`.
- Source excerpts embedded in `paper_results/arc_791506/table2_abaqus_paired.json`
  (the seven book-code rows) and in
  `paper_results/actual_umat_higher_order/code_imp/transform_report.json` were
  replaced with a "source excerpt removed" marker. Their numerical results are
  unchanged. Hashes of these files recorded elsewhere (for example in
  `derivative_manifest.json` and `docs/evidence/recovery_evidence_inventory.json`)
  describe the earlier bytes.
- **Still present:** the five frozen publication snapshots
  `paper_results/frozen/*/evidence/arc_791506/table2_abaqus_paired.json` each
  contain the same short excerpts (14 distinct source lines, mainly the
  `DDSDDE` assignment lines of the book-code rows). They were left unchanged
  because each snapshot is fixed by its `SHA256SUMS`/`MANIFEST.json` and checked
  byte-for-byte by `tests/test_frozen_evidence_integrity.py`. Editing them means
  re-freezing a publication snapshot, which is the maintainers' decision.

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
