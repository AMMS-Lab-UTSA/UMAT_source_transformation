# Reproduction summary: `smoke` profile

Generated 2026-10-27T17:32:14.946251+00:00.

- Python 3.11.16 on Windows-10-10.0.26200-SP0
- gfortran: GNU Fortran (MinGW-W64 x86_64-ucrt-posix-seh, built by Brecht Sanders, r4) 16.1.0
- Abaqus: not available (abaqus is not on PATH)
- Repository: https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
- Commit: ce4255affe50945565591ace06a6d7ca5af5f2ea (clean)

## Steps

| Step | Status | Detail |
|---|---|---|
| `import_package` | succeeded | umat_oti imports and its transform modules load |
| `material_point_smoke` | succeeded | m3_j2 transformed, compiled, executed and verified against centred differences of the original build |

## Outcome

2 succeeded, 0 failed, 0 unavailable for a stated external reason.
