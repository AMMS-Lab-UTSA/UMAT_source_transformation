# Verification material for the SoftwareX article

This folder holds the verification evidence and the scripts behind the
SoftwareX article on UMAT-OTI. It contains code and results only; the
manuscript itself is not in the repository.

All commands below run from this folder (`verification/softwarex/`), which
plays the role of the workspace root the scripts were written for.

## Layout

| Path | What it is |
|---|---|
| `evidence/2ae2ee0/` | The verified freeze of the code released as 1.2.0: test-suite logs, the tangent, internal-Jacobian, parameter-sensitivity and higher-order rounds, the Abaqus parity runs, and the R1 results (`r1/`). |
| `evidence/<commit>/` (others) | The same checks run at the earlier commits that were compared before choosing the freeze (`refreeze/RECOMMENDATION.md`). |
| `evidence/replacement-models/j2_voce_newton/` | Model R1: the UMAT source and its specification (`README.md`). |
| `evidence/2ae2ee0/figures/` | The first figure scripts, from which the article's Figure 2 and 3 scripts were derived. |
| `refreeze/` | How the freeze was chosen and recorded (`MANIFEST.md`, `RECOMMENDATION.md`), and the scripts `MANIFEST.md` lists (`refreeze/scripts/`). `run_candidate.sh` and `run_rounds.sh` set `WS` to the original workspace path on the builder's machine; set it to this folder to rerun them. |
| `refreeze/scripts/r1/` | R1 verification: `r1_verify.py` (a separate Python implementation of R1 with complex-step references), `r1_driver.f90` (a separate Fortran material-point driver) and `provenance_idcmp.py` (identifier comparison used for R1's provenance check). |
| `refreeze/scripts/posix_shim/` | The small POSIX shim used to run the 1.2.0 code on Windows for these runs. |
| `figures/` | `fig2_tangent.py` and `fig3_higher_order.py`, which draw the article's Figures 2 and 3. `article-provenance/` holds the provenance records written when the article's figures were drawn. |
| `timing-v11/` | The timing scripts and run files the article's performance supplement cites (see `timing-v11/README.md`). |

Each evidence archive has a `SHA256SUMS` file listing every file the run
wrote, including files that are deliberately not published (build products
and copies of third-party model sources; see `evidence/.gitignore`). The
evidence is stored byte for byte (`evidence/.gitattributes`), so for every
published file:

```bash
cd evidence/2ae2ee0 && sha256sum -c SHA256SUMS 2>/dev/null | grep -v 'open or read'
```

## Article Figures 2 and 3

The data are the committed round outputs:
`evidence/2ae2ee0/rounds/tangent/results/table2_ddsdde_illustrative.csv`
(Figure 2) and
`evidence/2ae2ee0/rounds/higher_order_convergence/j2/convergence_rows.csv`
(Figure 3). With Python and matplotlib:

```bash
python -I figures/fig2_tangent.py .
python -I figures/fig3_higher_order.py .
```

Each script writes the PDF, a PNG and a provenance JSON into `figures/`
(ignored by git). Compared with the article copies, the only change is the
output folder (`OUT = "figures"` instead of the workspace's `tex/figures`).
Checked on 2026-10-28: the regenerated PNGs are byte-identical to the
article's, and the data hashes in the new provenance records equal those in
`figures/article-provenance/` (PDFs differ only in their embedded creation
time).

## Model R1

`refreeze/scripts/r1/r1_verify.py` expects, relative to this folder:
the R1 source at `evidence/replacement-models/j2_voce_newton/umat_j2_voce.f`,
a checkout of the UMAT-OTI code to test at `refreeze/wt/<commit>/` (from the
repository root: `git worktree add verification/softwarex/refreeze/wt/v1.2.0 v1.2.0`),
`gfortran` on the PATH, and a Python with NumPy in which that checkout's
dependencies are installed. It writes its results to `evidence/<commit>/r1/`,
replacing `evidence/<commit>/r1/verify/`:

```bash
python refreeze/scripts/r1/r1_verify.py --commit v1.2.0
```

Use a name other than `2ae2ee0` for `--commit` (as above), or the run
overwrites the archived results; `git restore` brings them back. The
archived results, their notes and the review status are in
`evidence/2ae2ee0/r1/` (`NOTES.md`, `r1_report.json`).
