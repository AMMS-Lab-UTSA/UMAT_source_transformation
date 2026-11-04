# Redaction note (1.2.1, 2026-11-04)

`evidence/arc_791506/table2_abaqus_paired.json` in this snapshot held 37
strings quoted from the Dunne & Petrinic book companion code (*Introduction to
Computational Plasticity*, OUP 2005), which states no redistribution licence
(THIRD_PARTY_NOTICES.md section 2b). In release 1.2.1 each of those strings
was replaced by the marker

    [Dunne & Petrinic source excerpt removed: no redistribution licence]

the same marker used for the non-frozen copy in 1.2.0. Per case: code_exp 2,
code_imp 11, elastic 4, spin_elas_def 7, spin_elastic 5, visco_beam 4,
visco_imp 4. Only those string values changed: every other byte of the file,
including every numerical result, is as frozen. The file's `sha256` and
`bytes` in `MANIFEST.json`, and the lines for that file and for
`MANIFEST.json` in `SHA256SUMS`, were recomputed; no other recorded digest
changed. The bytes as originally frozen are in the git history before 1.2.1
(tag v1.2.0).

Digests of the redacted file: before 955ba2bebbe0612c8555f8ab21548cfcfb725e264487b5f4e3cca48f3ece001c, after bb4406b5ddc28e88f97d2637c5e9af5217636a37949a509c681b41925b225559.

This note itself is not listed in SHA256SUMS or MANIFEST.json: it was added in
1.2.1 beside the snapshot, and the sums were left covering the snapshot's own
files only.
