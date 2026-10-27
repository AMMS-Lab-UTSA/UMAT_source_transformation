# Paired Abaqus primal parity, Model A and R1, UMAT-OTI 2ae2ee0

Ada, 2026-10-27. **Unreviewed builder output.** Saved by the main session from Ada's hand-back, because the subagent's report write was blocked. Commit 61d6d11 supersedes the earlier BLOCKED run, e2d7240, whose files are kept in `blocker/`.

## Environment
- Windows 11 (10.0.26200), Abaqus 2024 (RELr426).
- Compiler: ifx 2025.1.1. ifort is not installed.
- Linker: MSVC 14.44.
- Licence: 75 of 314 in use when checked; 5 tokens per job, one job at a time, `cpus=1`.

## Linking (non-standard)
This installation has no user-subroutine development files (SMAUsubs), so Abaqus's normal `user=` route fails (`blocker/`). The ABSS method was used instead, reimplemented in `scripts/build_usublib.py`:
- Read from ABSS `abaqus_usersub.cpp` at 5dcef95, read-only. No ABSS binary was used.
- Compile with ifx using Abaqus's flags plus `/libs:dll /threads`, minus `/Qpc64`.
- `aba_param.inc` is the documented two-line content.
- `standardU.dll` exports our `umat`; the other 98 exports are thunks into an unmodified private copy of Abaqus's own stub.
- Jobs load it through `usub_lib_dir` and run without `user=`. The installation is not modified.
- `builds_manifest.txt` records the build behind each run; binaries are not archived.

## Deck
- One C3D8 unit cube, NLGEOM=NO, `*STATIC, DIRECT`, 10 increments per step.
- Model A PROPS 200000/0.3/250/2000; R1 PROPS 200000/0.3/250/1000/150/20.
- **ext, shear, mixed:** every step prescribes all 24 DOFs as u = εX, one value per DOF.
  - ext: isochoric extension e·diag(1, −½, −½), e = 3e-3 → 0.5e-3 → 4e-3.
  - shear: γ12 = 5e-3 → 1e-3 → 7e-3.
  - mixed: e = 2e-3; then γ = 4e-3 at fixed e; then both to 0; then e = 3e-3 with γ = 6e-3.
- **uniax:**
  - Prescribed: u1 = 0 on face X0 (nodes 1, 4, 5, 8), u2 = 0 on Y0 (1, 2, 5, 6), u3 = 0 on Z0 (1, 2, 3, 4), u1 = d on X1 (2, 3, 6, 7), with d = 3e-3 → 0.5e-3 → 4e-3.
  - Free: Y1 and Z1 are traction-free.
- Every case loads, unloads and reloads. Equivalent plastic strain reaches 2.7e-3 to 5.8e-3.

## Results
"rel" is max|a−b| / max|b| over the quantity in the worst increment.

| Pair | Converged STRESS | STATEV | RF | U | Equilibrium iterations (orig / oti) |
|---|---|---|---|---|---|
| ext, shear, mixed (both models) | ≤8.5e-14 (≤7.1e-15 rel) | ≤1.3e-18 | ≤4.3e-14 | ≤1.4e-35 | 1 per increment, identical |
| R1 uniax | 1.1e-13 | 1.3e-18 | 4.3e-14 | 1.1e-18 | 33 / 33 |
| Model A uniax | 0.53 (2.1e-3 rel) | 1.05e-6 | 0.13 | 1.6e-6 (4.3e-4 rel) | 32 / 33 |

Notes on the results:
- **Model A uniax** differs because the original routine returns the elastic DDSDDE and the transformed one returns the consistent tangent. The two global solves therefore converge to different points within the equilibrium tolerance, which is the mechanism Curie raised in I-A.
- **DDSDDE:**
  - R1 agrees to ≤8.7e-11 absolute (≤3.6e-16 rel) at converged calls.
  - Model A differs by about 0.4 rel by design (elastic matrix vs consistent tangent). This is not part of primal parity.
- **Strain inputs are not bitwise identical even when fully prescribed.** Abaqus's second call in each increment carries round-off corrections, so inputs differ by ≤2.7e-20 absolute.
- **Yield-surface tie:** at a step-start call with DSTRAN = 0 on a state lying on the yield surface, R1's branch choice (elastic or plastic tangent) differs between builds, once each in ext, mixed and uniax. In uniax this changed the first iterate (stress up to 5 MPa) but not the converged result.

## Archive
- `decks/`
- `jobs/*`: `.inp`, `.msg`, `.sta`, `.dat`, `.fin`, `_calls.txt`, and console output
- `transform/` and `build/` (sources and transcripts)
- `scripts/`: `make_inputs.py`, `build_usublib.py`, `run_all.sh`, `compare.py`
- `comparison_increments.csv`, `comparison_summary.csv`
- `environment.txt`, `builds_manifest.txt`
- `SHA256SUMS` with LF line endings (240 files)

## Limitations
- ifx is used in place of ifort, with the stub `aba_param.inc`.
- The run-time loading of the Intel runtime DLLs is assumed, not traced.
- The fully prescribed cases have no unknowns, so Abaqus's global solve does not test DDSDDE there.

## Reproduce
```
python scripts/make_inputs.py
python scripts/build_usublib.py <build>
bash scripts/run_all.sh
python scripts/compare.py
```
