# Reproduction summary: `smoke` profile

Generated 2026-10-27T17:33:08.855078+00:00.

- Python 3.11.16 on Windows-10-10.0.26200-SP0
- gfortran: GNU Fortran (MinGW-W64 x86_64-ucrt-posix-seh, built by Brecht Sanders, r4) 16.1.0
- Abaqus: not available (abaqus is not on PATH)
- Repository: https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
- Commit: c24ff0d3c43cfc1f5aa4522c0fe17b03b8bf5bca (clean)

## Steps

| Step | Status | Detail |
|---|---|---|
| `import_package` | succeeded | umat_oti imports and its transform modules load |
| `material_point_smoke` | failed | sweep produced no readable verdict for m3_j2: 'derivatives_verified' |

## Outcome

1 succeeded, 1 failed, 0 unavailable for a stated external reason.

> **Nothing was verified in this run.** Every step that checks a published claim was unavailable, so this report establishes only that the package imports. See the reasons below before treating the absence of failures as success.

### Failures

- `material_point_smoke`: sweep produced no readable verdict for m3_j2: 'derivatives_verified'
