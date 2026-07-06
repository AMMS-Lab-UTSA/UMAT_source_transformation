# SoftwareX submission materials

This folder holds the materials required to submit UMAT-OTI to *SoftwareX*
(Elsevier). Edit the placeholders (marked `TODO`) before submitting.

- [`code_metadata.md`](code_metadata.md) — the mandatory **Code metadata** table.
- [`manuscript.md`](manuscript.md) — a draft manuscript following the SoftwareX
  article structure. Transfer this into the official SoftwareX LaTeX/Word
  template before submission (download from the journal's *Guide for Authors*).

## SoftwareX submission checklist

- [ ] Software is in a **public** repository (GitHub) with an OSI-approved
      license — done: BSD-3-Clause (`../LICENSE`).
- [ ] A **permanent identifier** exists for the released version. Create a
      tagged release and archive it (e.g. mint a DOI via Zenodo by enabling the
      GitHub–Zenodo integration, then tag `v0.1.0`). Record the DOI in
      `code_metadata.md`. **TODO**
- [ ] Code metadata table completed (`code_metadata.md`).
- [ ] Manuscript ≤ 6 pages in the official template, with the required sections
      (Motivation and significance, Software description, Illustrative examples,
      Impact, Conclusions).
- [ ] All third-party licensing resolved (`../THIRD_PARTY_NOTICES.md`),
      especially confirming the OTIlib/pyoti upstream license. **TODO**
- [ ] Author list, affiliations, ORCIDs, and corresponding-author email
      confirmed in the manuscript and `../CITATION.cff`. **TODO**
