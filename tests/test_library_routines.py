"""LAPACK/BLAS routines a UMAT calls: twins, private names, host LAPACK, refusals.

* The real twins follow reference LAPACK/BLAS: DGETRF/DGETRS/DGESV and the BLAS
  bodies give the same bits as the reference library on random, ill-conditioned,
  singular and pivoting cases; INFO follows reference LAPACK.
* The OTI copies run the twins' algorithm: their real parts agree with the
  real twins to a few ulps (the OTI algebra divides as x*y**(-1)), and their
  derivative parts agree with central differences and with the complex step.
* No generated object defines a standard LAPACK/BLAS name (inside Abaqus the
  user library sits before MKL in the global symbol scope, so such a definition
  would serve every caller in the solver).
* A stand-alone build links the host's LAPACK and records which.
* A routine with no supplied body is refused by name.
* A standard name the author defines (their own DGETRF) is renamed with every
  reference to it, in the transform and in the provider; a library routine the
  author calls (DGESV) keeps the library's whole chain, as MKL does in Abaqus.
* The provider builds and differentiates UMATs that hand literals and
  expressions to DGEMM, DGEMV, DSYEV, DSCAL, DAXPY and DCOPY.
"""
from __future__ import annotations

import ctypes as C
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from umat_oti.core.lapack_names import STANDARD_LAPACK_BLAS
from umat_oti.transform.abaqus_utility_definitions import LIBRARY_ROUTINES, library_twin_sources

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")

REFERENCE_LAPACK = Path("/lib/x86_64-linux-gnu/liblapack.so.3")
REFERENCE_BLAS = Path("/lib/x86_64-linux-gnu/libblas.so.3")
needs_reference = pytest.mark.skipif(not (REFERENCE_LAPACK.is_file() and REFERENCE_BLAS.is_file()),
                                     reason="needs the system reference LAPACK and BLAS")

HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
"""

#: Stress from a 3x3 solve whose matrix and right-hand side both depend on the
#: strain increment: the derivative runs through DGETRF and DGETRS.
LU_UMAT = HEADER + """      DIMENSION A(3,3), B(3), AI(3,3), WK(9)
      INTEGER IPIV(3), INFO
      DO I = 1, 3
        DO J = 1, 3
          A(I,J) = 0.3D0*I - 0.2D0*J + DSTRAN(I)*DSTRAN(J)*1.0D2
        END DO
        A(I,I) = A(I,I) + PROPS(1)*(1.0D0 + DSTRAN(I))
        B(I) = DSTRAN(I)*PROPS(1) + DSTRAN(I+3)
      END DO
      DO I = 1, 3
        DO J = 1, 3
          AI(I,J) = A(I,J)
        END DO
      END DO
      CALL DGESV(3, 1, A, 3, IPIV, B, 3, INFO)
      CALL DGETRF(3, 3, AI, 3, IPIV, INFO)
      CALL DGETRI(3, AI, 3, IPIV, WK, 9, INFO)
      DO I = 1, 3
        STRESS(I) = STRESS(I) + B(I) + AI(I,1)
        STRESS(I+3) = STRESS(I+3) + PROPS(1)*DSTRAN(I+3) + AI(2,I)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      RETURN
      END
"""

#: Stress through DGEMV, DCOPY, DSCAL, DAXPY, DGEMM and DSYEV.
BLAS_UMAT = HEADER + """      DIMENSION CC(6,6), T(6), Q(6), S3(3,3), W3(3), WK(20)
      DIMENSION AM(3,3), BM(3,3), CM(3,3)
      INTEGER INFO
      DO I = 1, 6
        DO J = 1, 6
          CC(I,J) = 0.01D0*PROPS(1)*(I+2*J)
        END DO
        CC(I,I) = PROPS(1)*(1.0D0 + 0.1D0*I)
      END DO
      CALL DGEMV('N', 6, 6, 1.0D0, CC, 6, DSTRAN, 1, 0.0D0, T, 1)
      CALL DCOPY(6, T, 1, Q, 1)
      CALL DSCAL(6, 0.5D0, Q, 1)
      CALL DAXPY(6, 0.25D0, T, 1, Q, 1)
      DO I = 1, 3
        DO J = 1, 3
          AM(I,J) = 0.1D0*(I+J) + T(I)*T(J)*1.0D-6
          BM(I,J) = 0.05D0*I*J
        END DO
        BM(I,I) = 1.0D0 + T(I)*1.0D-3
      END DO
      CALL DGEMM('N', 'T', 3, 3, 3, 1.0D0, AM, 3, BM, 3, 0.0D0, CM, 3)
      DO I = 1, 3
        DO J = 1, 3
          S3(I,J) = CM(I,J) + CM(J,I)
        END DO
        S3(I,I) = S3(I,I) + 1.0D0*I
      END DO
      CALL DSYEV('N', 'U', 3, S3, 3, W3, WK, 20, INFO)
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + Q(I)
      END DO
      STRESS(1) = STRESS(1) + 1.0D2*(W3(1) + 2.0D0*W3(2) + 3.0D0*W3(3))
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = CC(I,J)
        END DO
      END DO
      RETURN
      END
"""

#: BLAS_UMAT with every scalar handed to a library routine written as an
#: expression, and an array given its shape by DIMENSION before a type
#: statement names it (ID3, an I-N name declared DOUBLE PRECISION).
BLAS_EXPRESSION_UMAT = BLAS_UMAT.replace(
    "      INTEGER INFO\n",
    "      DIMENSION ID3(3,3)\n      DOUBLE PRECISION ID3\n      INTEGER INFO\n      HALF = 0.5D0\n"
).replace(
    "CALL DGEMV('N', 6, 6, 1.0D0, CC, 6, DSTRAN, 1, 0.0D0, T, 1)",
    "CALL DGEMV('N', 6, 6, 2.0D0*HALF, CC, 6, DSTRAN, 1, 0.0D0*HALF,\n     1 T, 1)"
).replace("CALL DSCAL(6, 0.5D0, Q, 1)", "CALL DSCAL(6, PROPS(1)/PROPS(1)*HALF, Q, 1)"
).replace("CALL DAXPY(6, 0.25D0, T, 1, Q, 1)", "CALL DAXPY(6, HALF*HALF, T, 1, Q, 1)"
).replace(
    "CALL DGEMM('N', 'T', 3, 3, 3, 1.0D0, AM, 3, BM, 3, 0.0D0, CM, 3)",
    "DO I = 1, 3\n        DO J = 1, 3\n          ID3(I,J) = 0.0D0\n        END DO\n"
    "        ID3(I,I) = 1.0D0\n      END DO\n"
    "      CALL DGEMM('N', 'N', 3, 3, 3, 1.0D0, BM, 3, ID3, 3, 0.0D0, CM, 3)\n"
    "      CALL DCOPY(9, CM, 1, BM, 1)\n"
    "      CALL DGEMM('N', 'T', 3, 3, 3, HALF+HALF, AM, 3, BM, 3,\n     1 -1.0D0+1.0D0, CM, 3)")

#: LU_UMAT whose author also defines DGETRF (no pivoting), counting its calls
#: into the stress: one call is the author's own; a second would mean the
#: library's DGESV had run the author's routine.
AUTHOR_UMAT = LU_UMAT.replace(
    "      INTEGER IPIV(3), INFO\n",
    "      INTEGER IPIV(3), INFO, NCALL\n      COMMON /AUTHLU/ NCALL\n      NCALL = 0\n"
).replace(
    "      DO I = 1, NTENS\n        DO J = 1, NTENS\n          DDSDDE(I,J) = 0.0D0",
    "      STRESS(1) = STRESS(1) + 1.0D3*NCALL\n"
    "      DO I = 1, NTENS\n        DO J = 1, NTENS\n          DDSDDE(I,J) = 0.0D0"
) + """      SUBROUTINE DGETRF(M, N, A, LDA, IPIV, INFO)
      INTEGER M, N, LDA, IPIV(*), INFO, NCALL
      DOUBLE PRECISION A(LDA,*)
      COMMON /AUTHLU/ NCALL
      NCALL = NCALL + 1
      INFO = 0
      DO K = 1, N
        IPIV(K) = K
        DO I = K+1, M
          A(I,K) = A(I,K)/A(K,K)
          DO J = K+1, N
            A(I,J) = A(I,J) - A(I,K)*A(K,J)
          END DO
        END DO
      END DO
      RETURN
      END
"""

#: An author's own DGEMM on the stress path, handed a constant matrix (S0) that
#: carries no derivative: the routine must be promoted and its arguments handled
#: as for any helper of the author's (the same body named MYGEMM always was).
AUTHOR_DGEMM_UMAT = HEADER + """      DIMENSION S0(6,6), CC(6,6), BB(6)
      DO I = 1, 6
        DO J = 1, 6
          S0(I,J) = 0.0D0
          CC(I,J) = 0.01D0*PROPS(1)*(I+2*J)
        END DO
        S0(I,I) = 1.0D0
        CC(I,I) = PROPS(1)*(1.0D0 + 0.1D0*I + DSTRAN(I))
      END DO
      CALL DGEMM('N', 'N', 6, 1, 6, 1.0D0, CC, 6, DSTRAN, 6, 0.0D0,
     1 BB, 6)
      CALL DGEMM('N', 'N', 6, 1, 6, 1.0D0, S0, 6, BB, 6, 0.0D0,
     1 STRESS, 6)
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = CC(I,J)
        END DO
      END DO
      RETURN
      END
      SUBROUTINE DGEMM(TA,TB,M,N,K,ALPHA,A,LDA,B,LDB,BETA,C,LDC)
      CHARACTER TA,TB
      INTEGER M,N,K,LDA,LDB,LDC,I,J,L
      DOUBLE PRECISION ALPHA,BETA,A(LDA,*),B(LDB,*),C(LDC,*)
      DO J=1,N
        DO I=1,M
          C(I,J)=0.0D0
          DO L=1,K
            C(I,J)=C(I,J)+2.0D0*A(I,L)*B(L,J)
          END DO
        END DO
      END DO
      RETURN
      END
"""

#: An author's own DDOT function (it adds one), on the stress path.
AUTHOR_DDOT_UMAT = HEADER + """      DOUBLE PRECISION DDOT, ENRG
      ENRG = DDOT(NTENS, DSTRAN, 1, DSTRAN, 1)
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + PROPS(1)*DSTRAN(I)*(1.0D0+1.0D2*ENRG)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      RETURN
      END
      DOUBLE PRECISION FUNCTION DDOT(N,X,INCX,Y,INCY)
      INTEGER N,INCX,INCY,I
      DOUBLE PRECISION X(*),Y(*)
      DDOT=1.0D0
      DO I=1,N
        DDOT=DDOT+X(I)*Y(I)
      END DO
      RETURN
      END
"""

#: The library functions DDOT and DNRM2 referenced, not defined: supplied.
FUNCTIONS_UMAT = HEADER + """      DOUBLE PRECISION DDOT, DNRM2, T(6)
      DO I = 1, NTENS
        T(I) = PROPS(1)*DSTRAN(I) + 0.1D0*I*DSTRAN(MOD(I,6)+1)
      END DO
      XN = DNRM2(NTENS, T, 1)
      XD = DDOT(3, T, 2, DSTRAN, 1)
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + T(I)*(1.0D0 + 1.0D1*XN) + PROPS(1)*XD
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      RETURN
      END
"""

#: DNRM2 and DSCAL with negative and zero increments, where reference BLAS
#: 3.9.0 returns zero / does nothing and Abaqus's MKL computes.
INCREMENT_UMAT = HEADER + """      DOUBLE PRECISION DNRM2, T(6)
      DO I = 1, NTENS
        T(I) = PROPS(1)*DSTRAN(I) + 0.1D0*I*DSTRAN(MOD(I,6)+1)
      END DO
      XN = DNRM2(NTENS, T, -1) + 2.0D0*DNRM2(3, T, 0)
      CALL DSCAL(3, 0.5D0, T, -2)
      CALL DSCAL(2, 1.5D0, T(2), 0)
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + T(I)*(1.0D0 + 1.0D1*XN)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      RETURN
      END
"""

#: A REAL function of the author's whose name begins with I-N (MYNRM2),
#: declared DOUBLE PRECISION, on the stress path of a large stress whose shear
#: components cancel to about zero.
MYNRM2_UMAT = HEADER + """      DIMENSION S(6,6), B(6), EPS(6)
      INTEGER IPIV(6), INFO
      DOUBLE PRECISION MYNRM2, XN
      E = PROPS(1)
      XNU = 0.3D0
      DO I = 1, NTENS
        EPS(I) = STRAN(I) + DSTRAN(I)
      END DO
      FACTOR = 1.0D0
      DO I = 1, NTENS
        FACTOR = FACTOR + 50.0D0*EPS(I)*EPS(I)
      END DO
      DO I = 1, 6
        DO J = 1, 6
          S(I,J) = 0.0D0
        END DO
      END DO
      DO I = 1, 3
        DO J = 1, 3
          S(I,J) = -XNU/E*FACTOR
        END DO
        S(I,I) = FACTOR/E
        S(I+3,I+3) = 2.0D0*(1.0D0+XNU)/E*FACTOR
      END DO
      DO I = 1, NTENS
        B(I) = EPS(I)
      END DO
      CALL DGESV(NTENS, 1, S, 6, IPIV, B, 6, INFO)
      XN = MYNRM2(NTENS, B, 1)
      DO I = 1, NTENS
        STRESS(I) = B(I)*(1.0D0+1.0D-3*XN)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = E
      END DO
      RETURN
      END
      DOUBLE PRECISION FUNCTION MYNRM2(N,X,INCX)
      INTEGER N,INCX,I
      DOUBLE PRECISION X(*)
      MYNRM2=0.0D0
      DO I=1,N
        MYNRM2=MYNRM2+3.0D0*X(I)*X(I)
      END DO
      RETURN
      END
"""

ABA_PARAM = "      IMPLICIT REAL*8 (A-H,O-Z)\n      PARAMETER (NPRECD=2)\n"


def _p(a):
    return a.ctypes.data_as(C.c_void_p)


def call_umat(lib, props, dstran, dtype=np.float64):
    """One UMAT call through ctypes; every REAL argument in ``dtype``."""
    nt = 6
    f = lambda *shape: np.zeros(shape if shape else (1,), dtype=dtype, order="F")
    stress, statev, ddsdde = f(nt), f(1), f(nt, nt)
    scal = [f() for _ in range(4)]
    ddsddt, drplde, drpldt = f(nt), f(nt), f()
    stran, ds = f(nt), np.asarray(dstran, dtype=dtype)
    time, dtime, temp, dtemp, predef, dpred = f(2), f() + 1, f(), f(), f(1), f(1)
    pr = np.asarray(props, dtype=dtype)
    coords, drot, pnewdt, celent = f(3), np.eye(3, dtype=dtype, order="F"), f() + 1, f() + 1
    f0, f1 = np.eye(3, dtype=dtype, order="F"), np.eye(3, dtype=dtype, order="F")
    i = lambda v: C.byref(C.c_int(v))
    cm = C.create_string_buffer(b"T".ljust(80), 80)
    lib.umat_(_p(stress), _p(statev), _p(ddsdde), *[_p(s) for s in scal], _p(ddsddt), _p(drplde),
              _p(drpldt), _p(stran), _p(ds), _p(time), _p(dtime), _p(temp), _p(dtemp), _p(predef),
              _p(dpred), cm, i(3), i(3), i(nt), i(1), _p(pr), i(len(pr)), _p(coords), _p(drot),
              _p(pnewdt), _p(celent), _p(f0), _p(f1), i(1), i(1), i(1), i(1), i(1), i(1), C.c_size_t(80))
    return stress, ddsdde


def _shared(directory: Path, sources, name: str, flags=()) -> Path:
    objects = []
    for source in sources:
        source = Path(source)
        form = ["-ffixed-form", "-ffixed-line-length-none"] if source.suffix.lower() in (".f", ".for") \
            else ["-ffree-form", "-ffree-line-length-none"]
        obj = directory / (source.stem + ".o")
        subprocess.run(["gfortran", "-O1", "-fPIC", "-std=legacy", *form, *flags, f"-I{directory}",
                        f"-J{directory}", "-c", str(source), "-o", str(obj)], check=True, cwd=directory)
        objects.append(str(obj))
    lib = directory / name
    subprocess.run(["gfortran", "-shared", *objects, "-o", str(lib)], check=True, cwd=directory)
    return lib


def _transformed(tmp_path: Path, umat: str, name: str) -> Path:
    src = tmp_path / "src" / f"{name}.f"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(umat)
    out = tmp_path / f"{name}_out"
    done = subprocess.run([sys.executable, "-m", "umat_oti.cli", "jacobian", str(src), "--ntens", "6",
                           "--out", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-3000:]
    return out


def _transformed_library(out: Path) -> Path:
    units = [out / u.strip() for u in (out / "compile_order.txt").read_text().splitlines() if u.strip()]
    (out / "ABA_PARAM.INC").write_text(ABA_PARAM)
    return _shared(out, units, "libtransformed.so")


def _original_library(tmp_path: Path, umat: str, name: str, *, complex_step=False) -> Path:
    work = tmp_path / f"{name}_original{'_cs' if complex_step else ''}"
    work.mkdir()
    bodies = library_twin_sources()
    twins = "".join(bodies.values())
    if complex_step:
        lu = ("DGESV", "DGETRF", "DGETRS", "DGETRI")
        lu += tuple(f"UMATOTI_{n}_R" for n in lu)          # the private chain the entries call
        umat, twins = _complexified(umat), _complexified("".join(bodies[n] for n in lu))
        (work / "ABA_PARAM.INC").write_text("      IMPLICIT COMPLEX*16 (A-H,O-Z)\n      PARAMETER (NPRECD=2)\n")
    else:
        (work / "ABA_PARAM.INC").write_text(ABA_PARAM)
    (work / "umat.f").write_text(umat)
    (work / "twins.f90").write_text(twins)
    return _shared(work, [work / "umat.f", work / "twins.f90"], "liboriginal.so")


def _complexified(text: str) -> str:
    """The same code in COMPLEX*16, for the complex step: pivots, thresholds and
    scale factors stay real (magnitudes of values whose imaginary parts are 1e-30)."""
    from umat_oti.fortran.parser import split_top_level

    keep_real = {"BIGGEST", "SFMIN", "BIG", "SMALL"}
    out = []
    for line in text.splitlines():
        match = re.match(r"(?i)^(\s*)DOUBLE PRECISION\s+(.*)$", line)
        if match:
            entities = [e.strip() for e in split_top_level(match.group(2))]
            real = [e for e in entities if re.match(r"\w+", e).group(0).upper() in keep_real]
            other = [e for e in entities if e not in real]
            parts = ([f"{match.group(1)}COMPLEX*16 {', '.join(other)}"] if other else []) + (
                [f"{match.group(1)}DOUBLE PRECISION {', '.join(real)}"] if real else [])
            line = "\n".join(parts)
        line = re.sub(r"(?i)\bABS\(([A-Z]\w*(\([^()]*\))?)\)", r"ABS(DBLE(\1))", line)
        out.append(line)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- twins vs reference

def _twin_library(tmp_path: Path) -> C.CDLL:
    source = tmp_path / "tw.f90"
    source.write_text("".join(library_twin_sources("TW_{name}").values()))
    lib = tmp_path / "libtw.so"
    subprocess.run(["gfortran", "-O1", "-fPIC", "-shared", str(source), "-o", str(lib)], check=True)
    return C.CDLL(str(lib))


def _cases():
    rng = np.random.default_rng(1)
    cases = {f"random{n}_{k}": rng.standard_normal((n, n)) for n in (2, 3, 6, 9) for k in range(10)}
    hilbert = lambda n: 1.0 / (np.arange(n)[:, None] + np.arange(n)[None, :] + 1)
    cases.update({f"hilbert{n}": hilbert(n) for n in (3, 6, 9)})
    cases.update({
        "pivot_needed": np.array([[0., 1, 2], [3, 4, 5], [6, 7, 9]]),
        "ties": np.array([[1., 2, 3], [-1, 5, 6], [1, 8, 10]]),
        "singular_zero_column": np.array([[1., 0, 2], [3, 0, 4], [5, 0, 6]]),
        "singular_rank_one": np.outer([1., 2, 3], [4., 5, 6]),
        "zero": np.zeros((3, 3)),
        "tiny_pivot": np.array([[1e-310, 1.0], [1.0, 1.0]]),
        "scaled_1e200": rng.standard_normal((4, 4)) * 1e200,
        "scaled_1e-200": rng.standard_normal((4, 4)) * 1e-200,
        "mixed_scales": np.diag([1e180, 1.0, 1e-180]) + 1e-3,
    })
    return cases


@needs_reference
def test_lu_twins_give_the_reference_lapack_bits_and_info(tmp_path):
    tw, ref = _twin_library(tmp_path), C.CDLL(str(REFERENCE_LAPACK))
    i = lambda v: C.byref(C.c_int(v))
    rng = np.random.default_rng(2)
    for name, matrix in _cases().items():
        results = []
        for lib, routine in ((tw, "tw_dgetrf_"), (ref, "dgetrf_")):
            a = np.asfortranarray(matrix.copy())
            n = a.shape[0]
            ipiv, info = np.zeros(n, np.int32), C.c_int(0)
            getattr(lib, routine)(i(n), i(n), _p(a), i(n), _p(ipiv), C.byref(info))
            results.append((a, ipiv, info.value))
        (a1, p1, i1), (a2, p2, i2) = results
        assert i1 == i2, name                      # INFO = first zero pivot, factorization completed
        assert np.array_equal(p1, p2), name
        assert np.array_equal(a1, a2, equal_nan=True), name
        rhs = rng.standard_normal((a1.shape[0], 2))
        for trans in (b"N", b"T"):
            solved = []
            for lib, routine, a, ipiv in ((tw, "tw_dgetrs_", a1, p1), (ref, "dgetrs_", a2, p2)):
                b = np.asfortranarray(rhs.copy())
                info = C.c_int(0)
                getattr(lib, routine)(C.c_char_p(trans), i(a.shape[0]), i(2), _p(a), i(a.shape[0]),
                                      _p(ipiv), _p(b), i(a.shape[0]), C.byref(info), C.c_size_t(1))
                solved.append((b, info.value))
            assert solved[0][1] == solved[1][1] == 0, name   # no INFO for a zero diagonal
            if i1 == 0:
                assert np.array_equal(solved[0][0], solved[1][0]), (name, trans)
    # DGESV: INFO from the factorization, no solve on a singular matrix
    for name, matrix in _cases().items():
        out = []
        for lib, routine in ((tw, "tw_dgesv_"), (ref, "dgesv_")):
            a = np.asfortranarray(matrix.copy())
            n = a.shape[0]
            b = np.asfortranarray(np.arange(1.0, n + 1)[:, None])
            ipiv, info = np.zeros(n, np.int32), C.c_int(0)
            getattr(lib, routine)(i(n), i(1), _p(a), i(n), _p(ipiv), _p(b), i(n), C.byref(info))
            out.append((b, info.value))
        assert out[0][1] == out[1][1], name
        assert np.array_equal(out[0][0], out[1][0], equal_nan=True), name


@needs_reference
def test_dgetri_and_dsyev_twins_agree_with_reference_lapack_to_rounding(tmp_path):
    tw, ref = _twin_library(tmp_path), C.CDLL(str(REFERENCE_LAPACK))
    i = lambda v: C.byref(C.c_int(v))
    rng = np.random.default_rng(3)
    for k in range(20):
        n = (3, 6)[k % 2]
        matrix = rng.standard_normal((n, n)) + n * np.eye(n)
        inverses = []
        for lib, prefix in ((tw, "tw_"), (ref, "")):
            a = np.asfortranarray(matrix.copy())
            ipiv, info, work = np.zeros(n, np.int32), C.c_int(0), np.zeros(n * 8)
            getattr(lib, prefix + "dgetrf_")(i(n), i(n), _p(a), i(n), _p(ipiv), C.byref(info))
            getattr(lib, prefix + "dgetri_")(i(n), _p(a), i(n), _p(ipiv), _p(work), i(n * 8), C.byref(info))
            assert info.value == 0
            inverses.append(a)
        np.testing.assert_allclose(inverses[0], inverses[1], rtol=1e-12, atol=1e-14)
        sym = matrix + matrix.T
        eig = []
        for lib, routine in ((tw, "tw_dsyev_"), (ref, "dsyev_")):
            a = np.asfortranarray(sym.copy())
            w, work, info = np.zeros(n), np.zeros(10 * n), C.c_int(0)
            getattr(lib, routine)(C.c_char_p(b"V"), C.c_char_p(b"U"), i(n), _p(a), i(n), _p(w), _p(work),
                                  i(10 * n), C.byref(info), C.c_size_t(1), C.c_size_t(1))
            assert info.value == 0
            eig.append((w, a))
        np.testing.assert_allclose(eig[0][0], eig[1][0], rtol=1e-12, atol=1e-12 * abs(eig[1][0]).max())
        for col in range(n):                       # eigenvectors up to sign
            v1, v2 = eig[0][1][:, col], eig[1][1][:, col]
            np.testing.assert_allclose(v1 * np.sign(v1 @ v2), v2, atol=1e-10)


@needs_reference
def test_blas_twins_give_the_reference_blas_bits(tmp_path):
    tw, ref = _twin_library(tmp_path), C.CDLL(str(REFERENCE_BLAS))
    i = lambda v: C.byref(C.c_int(v))
    d = lambda v: C.byref(C.c_double(v))
    rng = np.random.default_rng(4)
    for ta in (b"N", b"T"):
        for tb in (b"N", b"T"):
            for alpha, beta in ((1.0, 0.0), (0.7, 1.0), (-1.3, 0.4)):
                a, b = rng.standard_normal((4, 4)), rng.standard_normal((4, 4))
                c0 = rng.standard_normal((4, 4))
                out = []
                for lib, routine in ((tw, "tw_dgemm_"), (ref, "dgemm_")):
                    c = np.asfortranarray(c0.copy())
                    getattr(lib, routine)(C.c_char_p(ta), C.c_char_p(tb), i(4), i(4), i(4), d(alpha),
                                          _p(np.asfortranarray(a)), i(4), _p(np.asfortranarray(b)), i(4),
                                          d(beta), _p(c), i(4), C.c_size_t(1), C.c_size_t(1))
                    out.append(c)
                assert np.array_equal(*out), (ta, tb, alpha, beta)
        for alpha, beta in ((1.0, 0.0), (0.5, -2.0)):
            a, x, y0 = rng.standard_normal((5, 4)), rng.standard_normal(5), rng.standard_normal(5)
            out = []
            for lib, routine in ((tw, "tw_dgemv_"), (ref, "dgemv_")):
                y = y0.copy()
                getattr(lib, routine)(C.c_char_p(ta), i(5), i(4), d(alpha), _p(np.asfortranarray(a)), i(5),
                                      _p(x.copy()), i(1), d(beta), _p(y), i(1), C.c_size_t(1))
                out.append(y)
            assert np.array_equal(*out), (ta, alpha, beta)
    x, y0 = rng.standard_normal(7), rng.standard_normal(7)
    for routine, args in (("dscal_", lambda v, w: (i(7), d(0.3), _p(v), i(1))),
                          ("dcopy_", lambda v, w: (i(7), _p(v), i(1), _p(w), i(1))),
                          ("daxpy_", lambda v, w: (i(7), d(-1.7), _p(v), i(1), _p(w), i(1)))):
        out = []
        for lib, name in ((tw, "tw_" + routine), (ref, routine)):
            v, w = x.copy(), y0.copy()
            getattr(lib, name)(*args(v, w))
            out.append((v, w))
        assert np.array_equal(out[0][0], out[1][0]) and np.array_equal(out[0][1], out[1][1]), routine
    # the functions: DDOT, and DNRM2 over ordinary, tiny, huge, zero and single entries
    for function in (tw.tw_ddot_, tw.tw_dnrm2_, ref.ddot_, ref.dnrm2_):
        function.restype = C.c_double
    vectors = [rng.standard_normal(9), rng.standard_normal(9) * 1e-170, rng.standard_normal(9) * 1e170,
               np.zeros(9), np.array([0.0, 3.0, 0.0, -4.0, 0, 0, 0, 0, 0]), np.array([-2.5] + [0.0] * 8)]
    for v in vectors:
        for n, inc in ((9, 1), (4, 2), (1, 1)):
            assert tw.tw_dnrm2_(i(n), _p(v.copy()), i(inc)) == ref.dnrm2_(i(n), _p(v.copy()), i(inc)), (v, n)
            w = rng.standard_normal(9)
            assert tw.tw_ddot_(i(n), _p(v.copy()), i(inc), _p(w), i(inc)) == \
                ref.ddot_(i(n), _p(v.copy()), i(inc), _p(w), i(inc)), (v, n)


# --------------------------------------------------------------------------- OTI copies

@pytest.mark.parametrize("name, umat, complex_step", [("lu", LU_UMAT, True), ("blas", BLAS_UMAT, False)],
                         ids=["lu", "blas"])
def test_the_oti_copies_reduce_to_the_twins_and_their_derivatives_are_right(tmp_path, name, umat,
                                                                             complex_step):
    out = _transformed(tmp_path, umat, name)
    transformed = C.CDLL(str(_transformed_library(out)))
    original = C.CDLL(str(_original_library(tmp_path, umat, name)))
    props = [2.5]
    dstran = np.array([1e-3, -2e-3, 1.5e-3, 3e-3, -1e-3, 2e-3])
    s_oti, tangent = call_umat(transformed, props, dstran)
    s_real, _ = call_umat(original, props, dstran)
    # The real parts run the twin's algorithm. They are not always its bits: the
    # OTI algebra divides as x*y**(-1), so a quotient can differ in the last
    # place from the real x/y (measured: at most 2 ulps on these toys).
    np.testing.assert_allclose(s_oti, s_real, rtol=8 * np.finfo(float).eps, atol=0)
    h = 1e-7
    fd = np.zeros((6, 6))
    for j in range(6):
        e = np.zeros(6)
        e[j] = h
        fd[:, j] = (call_umat(original, props, dstran + e)[0] - call_umat(original, props, dstran - e)[0]) / (2 * h)
    np.testing.assert_allclose(tangent, fd, rtol=1e-6, atol=1e-6 * abs(fd).max())
    if complex_step:
        cs_lib = C.CDLL(str(_original_library(tmp_path, umat, name, complex_step=True)))
        cs = np.zeros((6, 6))
        for j in range(6):
            e = np.zeros(6, dtype=complex)
            e[j] = 1e-30j
            cs[:, j] = call_umat(cs_lib, np.array(props, dtype=complex), dstran + e, dtype=np.complex128)[0].imag / 1e-30
        np.testing.assert_allclose(tangent, cs, rtol=1e-12, atol=1e-12 * abs(cs).max())


# --------------------------------------------------------------------------- symbols

def _defined(path: Path) -> set:
    listed = subprocess.run(["nm", "--defined-only", str(path)], capture_output=True, text=True).stdout
    return {line.split()[-1].lower() for line in listed.splitlines() if len(line.split()) == 3}


STANDARD_SYMBOLS = {name.lower() + "_" for name in STANDARD_LAPACK_BLAS}


@pytest.mark.parametrize("name, umat", [("lu", LU_UMAT), ("blas", BLAS_UMAT)], ids=["lu", "blas"])
def test_no_generated_object_defines_a_standard_lapack_or_blas_name(tmp_path, name, umat):
    out = _transformed(tmp_path, umat, name)
    _transformed_library(out)
    objects = list(out.glob("*.o"))
    combined = next(out.glob("*_oti_combined.f90"))
    subprocess.run(["gfortran", "-c", "-fPIC", "-ffree-line-length-none", f"-J{tmp_path}", str(combined),
                    "-o", str(tmp_path / "combined.o")], check=True, cwd=tmp_path)
    objects.append(tmp_path / "combined.o")
    for obj in objects:
        assert not (_defined(obj) & STANDARD_SYMBOLS), obj
    privates = set().union(*(_defined(o) for o in objects))
    assert {f"umatoti_{r.lower()}_oti_" for r in ("DGESV",) if name == "lu"} <= privates
    text = combined.read_text().upper()
    assert not re.search(r"^\s*SUBROUTINE\s+D(GESV|GETRF|GETRS|GEMM|GEMV|SYEV|SPEVD|COPY|SCAL|AXPY)\s*\(",
                         text, re.M)


@pytest.mark.fortran
def test_the_provider_defines_no_standard_name_and_its_regular_object_keeps_the_hosts(tmp_path):
    from umat_oti.provider.build import build_provider

    model = tmp_path / "model"
    model.mkdir()
    (model / "umat.f").write_text(LU_UMAT)
    (model / "contract.json").write_text(json.dumps({
        "schema": "resasm_umat_transform_v2", "source": {"main_file": "umat.f"},
        "kinematics": "small_strain", "dimensions": {"ntens": 6, "nprops": 1, "nstatev": 0},
        "parameters": [{"name": "E", "props_index": 1}],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": False},
        "output": {"object": "lu.obj", "contract": "lu.json"}}))
    built = build_provider(model / "contract.json", tmp_path / "out", regular_object="REAL_UMAT.obj")
    assert not (_defined(Path(built["object"])) & STANDARD_SYMBOLS)
    assert {"umatoti_dgesv_r_", "umatoti_dgetrf_r_", "umatoti_dgetri_r_"} <= _defined(Path(built["object"]))
    undefined = subprocess.run(["nm", "-u", built["regular_object"]], capture_output=True, text=True).stdout
    assert "dgesv_" in undefined and "dgetri_" in undefined          # for the host's LAPACK
    contract = json.loads(Path(built["contract"]).read_text())
    routines = contract["build"]["library_routines"]
    assert routines["called_by_the_original"] == ["DGESV", "DGETRF", "DGETRI"]
    assert routines["bundled_as"]["DGESV"] == "UMATOTI_DGESV_R"


# --------------------------------------------------------------------------- the author's own standard names

def _hosted_original(tmp_path: Path, umat: str, name: str, *, objects=()) -> Path:
    """The original as a shared library linked the way the stand-alone builds link it
    (:func:`umat_oti.abaqus.replay.library_link`): the host LAPACK, or the twins."""
    from umat_oti.abaqus.replay import library_link, library_twin_block
    from umat_oti.abaqus.single_call import drop_stubs_defined_by

    work = tmp_path / f"{name}_hosted"
    work.mkdir()
    (work / "ABA_PARAM.INC").write_text(ABA_PARAM)
    flags, twins, _ = library_link("gfortran", source_text=umat)
    sources = []
    if not objects:
        (work / "umat.f").write_text(umat)
        sources.append(work / "umat.f")
    if twins:
        (work / "twins.f90").write_text(drop_stubs_defined_by(library_twin_block(), umat)[0])
        sources.append(work / "twins.f90")
    built = []
    for source in sources:
        form = ["-ffixed-form"] if source.suffix == ".f" else ["-ffree-form", "-ffree-line-length-none"]
        subprocess.run(["gfortran", "-O1", "-fPIC", "-std=legacy", *form, f"-I{work}", "-c", str(source),
                        "-o", str(source.with_suffix(".o"))], check=True, cwd=work)
        built.append(str(source.with_suffix(".o")))
    lib = work / f"lib{name}.so"
    subprocess.run(["gfortran", "-shared", *built, *map(str, objects), *flags, "-o", str(lib)],
                   check=True, cwd=work)
    return lib


def _fd_tangent(lib, props, dstran, h=1e-7):
    fd = np.zeros((6, 6))
    for j in range(6):
        e = np.zeros(6)
        e[j] = h
        fd[:, j] = (call_umat(lib, props, dstran + e)[0] - call_umat(lib, props, dstran - e)[0]) / (2 * h)
    return fd


def test_an_authors_own_standard_name_is_renamed_and_the_library_chain_stays_whole(tmp_path):
    out = _transformed(tmp_path, AUTHOR_UMAT, "author")
    report = json.loads((out / "transform_report.json").read_text())
    assert report["author_library_definitions_renamed"]["renamed"] == {"DGETRF": "UMATOTI_AUTH_DGETRF"}
    transformed = C.CDLL(str(_transformed_library(out)))
    objects = list(out.glob("*.o"))
    for obj in objects:
        assert not (_defined(obj) & STANDARD_SYMBOLS), obj
    defined = set().union(*(_defined(o) for o in objects))
    assert {"umatoti_auth_dgetrf_", "umatoti_auth_dgetrf_oti_", "umatoti_dgetrf_oti_"} <= defined
    helpers_text = (out / "umat_oti_helpers.f90").read_text()
    assert helpers_text.startswith("! The bodies of DGESV, DGETRF, DGETRI, DGETRS in this file")
    assert "! Copyright (c) 1992-2023 The University of Tennessee" in helpers_text
    assert "University of Tennessee" in next(out.glob("*_oti_combined.f90")).read_text()
    helpers = helpers_text.upper()
    dgesv = helpers[helpers.index("SUBROUTINE UMATOTI_DGESV_OTI"):helpers.index("END SUBROUTINE UMATOTI_DGESV_OTI")]
    assert "CALL UMATOTI_DGETRF_OTI(" in dgesv and "AUTH" not in dgesv
    original = C.CDLL(str(_hosted_original(tmp_path, AUTHOR_UMAT, "author")))
    props, dstran = [2.5], np.array([1e-3, -2e-3, 1.5e-3, 3e-3, -1e-3, 2e-3])
    s_oti, tangent = call_umat(transformed, props, dstran)
    s_real, _ = call_umat(original, props, dstran)
    # one call of the author's DGETRF in each: the library's DGESV ran its own LU
    assert 1.0e3 < s_oti[0] - s_oti[1] < 2.0e3 and 1.0e3 < s_real[0] - s_real[1] < 2.0e3
    np.testing.assert_allclose(s_oti, s_real, rtol=1e-12, atol=0)
    fd = _fd_tangent(original, props, dstran)
    np.testing.assert_allclose(tangent, fd, rtol=1e-6, atol=1e-6 * abs(fd).max())


@pytest.mark.parametrize("name, umat, renamed", [("author_dgemm", AUTHOR_DGEMM_UMAT, "DGEMM"),
                                                  ("author_ddot", AUTHOR_DDOT_UMAT, "DDOT")],
                         ids=["dgemm", "ddot"])
def test_an_authors_own_library_routine_is_transformed_like_any_helper(tmp_path, name, umat, renamed):
    """The author's DGEMM (DDOT) is promoted, lifted and checked under its own
    name exactly as a helper called MYGEMM would be, then written under a
    private name; its constant arguments (S0) are given shadows like any helper's."""
    out = _transformed(tmp_path, umat, name)
    report = json.loads((out / "transform_report.json").read_text())
    assert report["success"] is True
    assert report["author_library_definitions_renamed"]["renamed"] == {renamed: f"UMATOTI_AUTH_{renamed}"}
    transformed = C.CDLL(str(_transformed_library(out)))
    for obj in out.glob("*.o"):
        assert not (_defined(obj) & STANDARD_SYMBOLS), obj
    defined = set().union(*(_defined(o) for o in out.glob("*.o")))
    assert {f"umatoti_auth_{renamed.lower()}_", f"umatoti_auth_{renamed.lower()}_oti_"} <= defined
    original = C.CDLL(str(_hosted_original(tmp_path, umat, name)))
    props, dstran = [2.5], np.array([1e-3, -2e-3, 1.5e-3, 3e-3, -1e-3, 2e-3])
    s_oti, tangent = call_umat(transformed, props, dstran)
    np.testing.assert_allclose(s_oti, call_umat(original, props, dstran)[0], rtol=1e-13, atol=0)
    fd = _fd_tangent(original, props, dstran)
    np.testing.assert_allclose(tangent, fd, rtol=1e-6, atol=1e-6 * abs(fd).max())


def test_the_library_functions_ddot_and_dnrm2_are_supplied(tmp_path):
    """DDOT and DNRM2 referenced in expressions, not defined: read as functions,
    lifted under private names, their real bodies left to the host's library."""
    out = _transformed(tmp_path, FUNCTIONS_UMAT, "functions")
    report = json.loads((out / "transform_report.json").read_text())
    assert report["success"] is True and "author_library_definitions_renamed" not in report
    emitted = next(out.glob("functions_oti.f")).read_text().upper()
    assert not re.search(r"^\s*DOUBLE PRECISION\s+FUNCTION\s+D(DOT|NRM2)\b", emitted, re.M)
    helpers = (out / "umat_oti_helpers.f90").read_text().upper()
    assert "FUNCTION UMATOTI_DNRM2_OTI" in helpers and "FUNCTION UMATOTI_DDOT_OTI" in helpers
    transformed = C.CDLL(str(_transformed_library(out)))
    for obj in out.glob("*.o"):
        assert not (_defined(obj) & STANDARD_SYMBOLS), obj
    original = C.CDLL(str(_hosted_original(tmp_path, FUNCTIONS_UMAT, "functions")))
    props = [2.5]
    for dstran in (np.array([1e-3, -2e-3, 1.5e-3, 3e-3, -1e-3, 2e-3]), np.zeros(6)):
        s_oti, tangent = call_umat(transformed, props, dstran)
        assert np.all(np.isfinite(tangent))
        # the host's DNRM2 (MKL) need not round like the reference algorithm
        np.testing.assert_allclose(s_oti, call_umat(original, props, dstran)[0], rtol=1e-14, atol=1e-300)
        if dstran.any():
            fd = _fd_tangent(original, props, dstran)
            np.testing.assert_allclose(tangent, fd, rtol=1e-6, atol=1e-6 * abs(fd).max())
        else:
            # at the zero vector the norm has no derivative; its contribution is zero
            expected = np.zeros((6, 6))
            for i in range(6):
                expected[i, i] = props[0]
                expected[i, (i + 1) % 6] += 0.1 * (i + 1)
            np.testing.assert_allclose(tangent, expected, rtol=1e-14, atol=1e-14)


def test_stand_alone_builds_of_a_source_defining_a_standard_name_keep_the_library_chain(monkeypatch):
    """Reference LAPACK's DGESV would call the author's dgetrf_; such a source links
    MKL or the twins, whose chain calls private names only."""
    from umat_oti.abaqus.replay import library_link
    from umat_oti.core.host_lapack import host_lapack

    try:
        if REFERENCE_LAPACK.is_file():
            monkeypatch.setenv("UMAT_OTI_LAPACK", "reference")
            host_lapack.cache_clear()
            assert library_link("gfortran", source_text=LU_UMAT)[1] is False
            flags, twins, record = library_link("gfortran", source_text=AUTHOR_UMAT)
            assert twins and flags == [] and "DGETRF" in record["description"]
            # DNRM2 and DSCAL differ between MKL and reference BLAS for INCX <= 0
            flags, twins, record = library_link("gfortran", source_text=INCREMENT_UMAT)
            assert twins and "DNRM2" in record["description"] and "DSCAL" in record["description"]
        monkeypatch.setenv("UMAT_OTI_LAPACK", "auto")
        host_lapack.cache_clear()
        if host_lapack("gfortran").kind == "mkl":
            assert library_link("gfortran", source_text=AUTHOR_UMAT)[2]["kind"] == "mkl"
    finally:
        host_lapack.cache_clear()
    bodies = library_twin_sources()
    assert "CALL UMATOTI_DGETRF_R(" in bodies["DGESV"] and "CALL DGETRF(" not in bodies["DGESV"].upper()


@needs_reference
def test_without_mkl_every_stand_alone_build_runs_the_library_chain(tmp_path, monkeypatch):
    """With reference LAPACK forced, a source that defines DGETRF and calls DGESV:
    linked plainly, reference DGESV calls the author's DGETRF (two calls); every
    stand-alone build umat-oti makes runs the library's own chain (one call, the
    author's own), as Abaqus's MKL does and as the transformed code does."""
    from umat_oti.core.host_lapack import host_lapack
    from umat_oti.validation.parameter_sensitivity_validation import build_original_driver, replay

    monkeypatch.setenv("UMAT_OTI_LAPACK", "reference")
    host_lapack.cache_clear()
    try:
        props, dstran = [2.5], np.array([1e-3, -2e-3, 1.5e-3, 3e-3, -1e-3, 2e-3])
        calls = lambda stress: round((stress[0] - stress[1] - (s_ref[0] - s_ref[1])) / 1.0e3)
        s_ref = call_umat(C.CDLL(str(_transformed_library(_transformed(tmp_path, AUTHOR_UMAT, "author")))),
                          props, dstran)[0] - np.array([1.0e3, 0, 0, 0, 0, 0])   # the stress without NCALL
        assert calls(call_umat(C.CDLL(str(_hosted_original(tmp_path, AUTHOR_UMAT, "author"))),
                               props, dstran)[0]) == 1
        model = tmp_path / "model"
        model.mkdir()
        (model / "umat.f").write_text(AUTHOR_UMAT)
        # an executable linked plainly against reference LAPACK: its DGESV runs the author's DGETRF
        plain = build_original_driver(model / "umat.f", tmp_path / "plain", ntens=6, nstatv=1, nprops=1,
                                      library_twins=False,
                                      link_libraries=[str(REFERENCE_LAPACK), str(REFERENCE_BLAS)])
        stress = np.asarray(replay(plain, props, [dstran], ntens=6, nstatv=1).stress)[-1]
        assert calls(stress) == 2
        driver = build_original_driver(model / "umat.f", tmp_path / "original", ntens=6, nstatv=1, nprops=1)
        assert json.loads((tmp_path / "original" / "lapack.json").read_text())["kind"] == "twins"
        stress = np.asarray(replay(driver, props, [dstran], ntens=6, nstatv=1).stress)[-1]
        assert calls(stress) == 1
    finally:
        host_lapack.cache_clear()


def test_the_provider_verifier_names_the_missing_state_for_the_j2_branch_check(tmp_path):
    """No state variable and no --elastic: a clear refusal, not an IndexError."""
    from umat_oti.validation import parameter_sensitivity_provider as verifier

    model = tmp_path / "model"
    model.mkdir()
    (model / "umat.f").write_text(HEADER + """      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + PROPS(1)*DSTRAN(I)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      RETURN
      END
""")
    (model / "contract.json").write_text(json.dumps({
        "schema": "resasm_umat_transform_v2", "source": {"main_file": "umat.f"},
        "kinematics": "small_strain", "dimensions": {"ntens": 6, "nprops": 1, "nstatev": 0},
        "parameters": [{"name": "E", "props_index": 1}],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": False},
        "validation": {"props_values": [2.5],
                       "check_path": {"dstran_per_increment": [1e-4, 0, 0, 0, 0, 0], "n_increments": 3}},
        "output": {"object": "lu.obj", "contract": "lu.json"}}))
    with pytest.raises(ValueError, match="no state variables.*--elastic"):
        verifier.verify_provider(model / "contract.json", tmp_path / "out")
    with pytest.raises(SystemExit) as stopped:
        verifier.main([str(model / "contract.json"), "--out", str(tmp_path / "cli")])
    assert stopped.value.code == 2
    record = json.loads((tmp_path / "cli" / "verification.json").read_text())
    assert record["passed"] is False and "--elastic" in record["error"]
    passed = verifier.verify_provider(model / "contract.json", tmp_path / "elastic", require_j2_branches=False)
    assert passed["passed"] is True


#: Calls with increments 1, 2, -1, -2 and 0, N <= 0, and invalid leading
#: dimensions or option letters, printed so two builds can be compared.
_ARGUMENT_PROBE = """      PROGRAM P
      DOUBLE PRECISION X(6), Y(6), Z(6), DNRM2, DDOT, A(3,3), B(3,3), C(3,3)
      DOUBLE PRECISION S(3,3), W(3)
      INTEGER I, J, K, INC(5), IPIV(3), INFO
      DATA X /0.7D0,-1.3D0,0.2D0,2.1D0,-0.4D0,0.9D0/
      DATA Y /1.1D0,0.3D0,-0.8D0,0.5D0,1.7D0,-0.6D0/
      DATA INC /1,2,-1,-2,0/
      DO K = 1, 9
        A(MOD(K-1,3)+1,(K-1)/3+1) = 0.1D0*K - 0.35D0
        B(MOD(K-1,3)+1,(K-1)/3+1) = 0.2D0*K + 0.15D0
      END DO
      DO I = 1, 5
        DO K = -1, 6
          WRITE(*,*) 'NRM2', K, INC(I), DNRM2(K,X,INC(I))
        END DO
        Z = X
        CALL DSCAL(3, 0.7D0, Z, INC(I))
        WRITE(*,*) 'SCAL', INC(I), Z
        DO J = 1, 5
          WRITE(*,*) 'DOT', INC(I), INC(J), DDOT(3,X,INC(I),Y,INC(J))
          Z = Y
          CALL DAXPY(3, 0.7D0, X, INC(I), Z, INC(J))
          WRITE(*,*) 'AXPY', INC(I), INC(J), Z
          Z = Y
          CALL DCOPY(3, X, INC(I), Z, INC(J))
          WRITE(*,*) 'COPY', INC(I), INC(J), Z
          Z = Y
          CALL DGEMV('N', 3, 3, 0.9D0, A, 3, X, INC(I), 0.4D0, Z,
     &               INC(J))
          WRITE(*,*) 'GEMVN', INC(I), INC(J), Z
          Z = Y
          CALL DGEMV('T', 3, 3, 0.9D0, A, 3, X, INC(I), 0.4D0, Z,
     &               INC(J))
          WRITE(*,*) 'GEMVT', INC(I), INC(J), Z
        END DO
      END DO
      Z = Y
      CALL DGEMV('N', 3, 3, 0.9D0, A, 2, X, 1, 0.4D0, Z, 1)
      WRITE(*,*) 'GEMV LDA', Z
      Z = Y
      CALL DGEMV('X', 3, 3, 0.9D0, A, 3, X, 1, 0.4D0, Z, 1)
      WRITE(*,*) 'GEMV TRANS', Z
      C = B
      CALL DGEMM('N','N',3,3,3,1.0D0,A,2,B,3,0.0D0,C,3)
      WRITE(*,*) 'GEMM LDA', C
      C = B
      CALL DGEMM('N','N',3,3,3,1.0D0,A,3,B,3,0.0D0,C,2)
      WRITE(*,*) 'GEMM LDC', C
      C = B
      CALL DGEMM('X','N',3,3,3,1.0D0,A,3,B,3,0.0D0,C,3)
      WRITE(*,*) 'GEMM TRANS', C
      C = B
      CALL DGEMM('N','N',3,3,-1,1.0D0,A,3,B,3,0.5D0,C,3)
      WRITE(*,*) 'GEMM K', C
      S = A
      W = X(1:3)
      CALL DGESV(3, 1, S, 2, IPIV, W, 3, INFO)
      WRITE(*,*) 'GESV LDA', INFO, W
      S = A
      CALL DGETRF(3, 3, S, 2, IPIV, INFO)
      WRITE(*,*) 'GETRF LDA', INFO
      END
      SUBROUTINE XERBLA(SRNAME, INFO)
      CHARACTER*(*) SRNAME
      INTEGER INFO
      END
"""


def _probe_output(work: Path, flags, sources=()) -> list:
    work.mkdir()
    (work / "probe.f").write_text(_ARGUMENT_PROBE)
    subprocess.run(["gfortran", "-ffixed-line-length-none", "probe.f", *map(str, sources), *flags, "-o", "probe"],
                   cwd=work, check=True)
    lines = subprocess.run(["./probe"], cwd=work, capture_output=True, text=True, check=True).stdout
    return [line.split() for line in lines.splitlines()]


def test_the_twins_follow_mkl_for_every_increment_and_invalid_argument(tmp_path):
    """The library Abaqus links a UMAT against is MKL: where it and reference BLAS
    disagree (DNRM2 and DSCAL for INCX <= 0), the twins follow MKL; for invalid
    leading dimensions and options every routine leaves its output alone. MKL's
    arithmetic differs from reference BLAS's in the last bits even for unit
    increments, so values are compared to a few ulps, labels and counts exactly."""
    from umat_oti.core.host_lapack import host_lapack

    host = host_lapack("gfortran")
    if host.kind != "mkl":
        pytest.skip("needs MKL")
    twins = tmp_path / "twins.f90"
    twins.write_text("".join(library_twin_sources().values()))
    mkl = _probe_output(tmp_path / "mkl", host.flags)
    ours = _probe_output(tmp_path / "twins", [], [twins])
    assert len(mkl) == len(ours) and len(mkl) > 150
    for left, right in zip(mkl, ours):
        assert len(left) == len(right), (left, right)
        for a, b in zip(left, right):
            try:
                x, y = float(a), float(b)
            except ValueError:
                assert a == b
                continue
            assert x == y or abs(x - y) <= 4 * np.finfo(float).eps * max(abs(x), abs(y)), (left, right)


def test_negative_and_zero_increments_are_differentiated_as_mkl_computes_them(tmp_path):
    from umat_oti.core.host_lapack import host_lapack

    out = _transformed(tmp_path, INCREMENT_UMAT, "increments")
    report = json.loads((out / "transform_report.json").read_text())
    assert report["success"] is True
    transformed = C.CDLL(str(_transformed_library(out)))
    props, dstran = [2.5], np.array([1e-3, -2e-3, 1.5e-3, 3e-3, -1e-3, 2e-3])
    s_oti, tangent = call_umat(transformed, props, dstran)
    assert abs(s_oti).max() > 0
    if host_lapack("gfortran").kind == "mkl":
        original = C.CDLL(str(_hosted_original(tmp_path, INCREMENT_UMAT, "increments")))
        np.testing.assert_allclose(s_oti, call_umat(original, props, dstran)[0], rtol=1e-14, atol=0)
    reference = C.CDLL(str(_original_library(tmp_path, INCREMENT_UMAT, "increments")))
    np.testing.assert_allclose(s_oti, call_umat(reference, props, dstran)[0], rtol=1e-15, atol=0)
    fd = _fd_tangent(reference, props, dstran)
    np.testing.assert_allclose(tangent, fd, rtol=1e-6, atol=1e-6 * abs(fd).max())


def test_the_primal_tolerance_scales_with_the_run_and_a_function_result_keeps_its_derivative(tmp_path):
    """A stress component that cancels to about zero carries the rounding of the
    large terms it came from; the verifier's absolute tolerance is relative to
    the run's largest stress (never tighter than before). MYNRM2, a DOUBLE
    PRECISION function whose name begins with I-N, is lifted with an OTI result
    (its stores were wrapped in REAL(), dropping the derivative)."""
    from umat_oti.validation.parameter_sensitivity_provider import primal_atol, verify_provider

    assert primal_atol(np.zeros((3, 6)), 1e-10) == 1e-10
    assert primal_atol(np.array([[2.0e5, -1.0, 0.0]]), 1e-10) == pytest.approx(2.0e-7)
    assert primal_atol(np.array([[np.nan, 3.0]]), 1e-14) == pytest.approx(3.0e-12)
    model = tmp_path / "model"
    model.mkdir()
    (model / "umat.f").write_text(MYNRM2_UMAT)
    (model / "contract.json").write_text(json.dumps({
        "schema": "resasm_umat_transform_v2", "source": {"main_file": "umat.f"},
        "kinematics": "small_strain", "dimensions": {"ntens": 6, "nprops": 1, "nstatev": 0},
        "parameters": [{"name": "E", "props_index": 1}],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": False},
        "validation": {"props_values": [200000.0],
                       "check_path": {"dstran_per_increment": [0.003, -0.0009, -0.0009, 0.002, 0.0, 0.001],
                                      "n_increments": 6}},
        "output": {"object": "m.obj", "contract": "m.json"}}))
    report = verify_provider(model / "contract.json", tmp_path / "out", require_j2_branches=False)
    assert report["passed"] is True
    assert report["primal_tolerance"]["stress_atol"] > 1e-10
    assert "units in the last place" in report["primal_tolerance"]["not_detected"]
    lifted = next((tmp_path / "out").glob("build-*/umat_oti_lifted.f90")).read_text().upper()
    assert "REAL(MYNRM2" not in lifted


# --------------------------------------------------------------------------- the provider

def _provider(tmp_path: Path, umat: str, name: str) -> dict:
    from umat_oti.provider.build import build_provider

    model = tmp_path / f"{name}_model"
    model.mkdir()
    (model / "umat.f").write_text(umat)
    (model / "contract.json").write_text(json.dumps({
        "schema": "resasm_umat_transform_v2", "source": {"main_file": "umat.f"},
        "kinematics": "small_strain", "dimensions": {"ntens": 6, "nprops": 1, "nstatev": 0},
        "parameters": [{"name": "E", "props_index": 1}],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": False},
        "output": {"object": f"{name}.obj", "contract": f"{name}.json"}}))
    return build_provider(model / "contract.json", tmp_path / f"{name}_out", regular_object="REAL_UMAT.obj")


def call_provider(lib, props, dstran):
    """``(STRESS, DSIGMA_DP)`` from the provider's umat_oti_eval_."""
    f = lambda *shape: np.zeros(shape, order="F")
    stress, statev, ddsdde = f(6), f(1), f(6, 6)
    stran, ds, time = f(6), np.asarray(dstran, dtype=float), f(2)
    dtime, temp, dtemp = np.ones(1), f(1), f(1)
    pr = np.asarray(props, dtype=float)
    dsigma, dstatev = f(6, len(pr)), f(1, len(pr))
    i = lambda v: C.byref(C.c_int(v))
    lib.umat_oti_eval_(_p(stress), _p(statev), _p(ddsdde), _p(stran), _p(ds), _p(time), _p(dtime),
                       _p(temp), _p(dtemp), _p(pr), i(len(pr)), i(6), i(0), i(len(pr)),
                       _p(dsigma), _p(dstatev))
    return stress, dsigma


@pytest.mark.fortran
@pytest.mark.parametrize("name, umat", [("blas", BLAS_UMAT), ("blas_expressions", BLAS_EXPRESSION_UMAT),
                                        ("author", AUTHOR_UMAT), ("author_dgemm", AUTHOR_DGEMM_UMAT),
                                        ("author_ddot", AUTHOR_DDOT_UMAT), ("functions", FUNCTIONS_UMAT)],
                         ids=["blas", "blas_expressions", "author", "author_dgemm", "author_ddot",
                              "functions"])
def test_the_provider_builds_and_differentiates_library_calls(tmp_path, name, umat):
    built = _provider(tmp_path, umat, name)
    for obj in (built["object"], built["regular_object"]):
        assert not (_defined(Path(obj)) & STANDARD_SYMBOLS), obj
    routines = json.loads(Path(built["contract"]).read_text())["build"]["library_routines"]
    if routines["called_by_the_original"]:
        assert "BSD-3-Clause" in routines["licence"]["note"]
        assert routines["licence"]["text"].startswith("Copyright (c) 1992-2023 The University of Tennessee")
    if name in ("author_dgemm", "author_ddot"):
        own = name.split("_")[1].upper()
        assert routines["author_definitions_renamed"] == {own: f"UMATOTI_AUTH_{own}"}
        assert f"umatoti_auth_{own.lower()}_" in _defined(Path(built["regular_object"]))
    elif name == "functions":
        assert routines["called_by_the_original"] == ["DDOT", "DNRM2"]
        assert {"umatoti_ddot_r_", "umatoti_dnrm2_r_"} <= _defined(Path(built["object"]))
    elif name == "author":
        assert routines["author_definitions_renamed"] == {"DGETRF": "UMATOTI_AUTH_DGETRF"}
        assert routines["called_by_the_original"] == ["DGESV", "DGETRI"]
        # the whole chain, though the author defines DGETRF
        assert {"umatoti_dgetrf_r_", "umatoti_auth_dgetrf_"} <= _defined(Path(built["object"]))
        assert "umatoti_auth_dgetrf_" in _defined(Path(built["regular_object"]))
    else:
        assert set(routines["called_by_the_original"]) == {"DGEMV", "DCOPY", "DSCAL", "DAXPY", "DGEMM",
                                                           "DSYEV"}
    provider = C.CDLL(str(Path(built["build_dir"]) / "provider_link_check.so"))
    regular = C.CDLL(str(_hosted_original(tmp_path, umat, name, objects=[built["regular_object"]])))
    props, dstran = [2.5], np.array([1e-3, -2e-3, 1.5e-3, 3e-3, -1e-3, 2e-3])
    stress, dsigma = call_provider(provider, props, dstran)
    np.testing.assert_allclose(stress, call_umat(regular, props, dstran)[0], rtol=1e-12, atol=0)
    # STRESS(1) of the BLAS toys is ~600 with a derivative ~2e-3: a step of 1e-4
    # keeps the rounding in the difference (~600*eps/h) well below the tolerance.
    h = 1e-4
    fd = (call_umat(regular, [props[0] + h], dstran)[0] - call_umat(regular, [props[0] - h], dstran)[0]) / (2 * h)
    np.testing.assert_allclose(dsigma[:, 0], fd, rtol=1e-6, atol=1e-6 * abs(fd).max())


def test_the_licence_of_the_reference_bodies_is_the_one_in_the_notices():
    from umat_oti.transform.abaqus_utility_definitions import REFERENCE_LAPACK_LICENCE

    notices = (Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md").read_text()
    assert REFERENCE_LAPACK_LICENCE.rstrip("\n") in notices
    for module in ("lu_definitions.py", "blas_definitions.py", "abaqus_utility_definitions.py"):
        assert f"src/umat_oti/transform/{module}" in notices


# --------------------------------------------------------------------------- host LAPACK and refusals

def test_the_host_lapack_is_recorded_and_the_twins_are_only_a_fallback(monkeypatch):
    from umat_oti.abaqus.replay import library_link, library_twin_block, utility_stub_block
    from umat_oti.core.host_lapack import host_lapack

    monkeypatch.setenv("UMAT_OTI_LAPACK", "twins")
    host_lapack.cache_clear()
    try:
        flags, twins, record = library_link("gfortran")
        assert flags == [] and twins and record["kind"] == "twins"
        assert library_twin_block() in utility_stub_block("gfortran")
        if REFERENCE_LAPACK.is_file():
            monkeypatch.setenv("UMAT_OTI_LAPACK", "reference")
            host_lapack.cache_clear()
            flags, twins, record = library_link("gfortran")
            assert record["kind"] == "reference" and not twins and str(REFERENCE_LAPACK) in flags
            assert "SUBROUTINE DGESV(" not in utility_stub_block("gfortran")
            # a REAL(16) build is never served by a library
            assert library_link("gfortran", quad=True)[1] is True
    finally:
        host_lapack.cache_clear()


@needs_reference
def test_the_host_lapack_is_found_without_ldconfig_on_path_and_its_version_recorded(monkeypatch):
    """ldconfig is in /sbin, often not on a user's PATH; the standard library
    directories are read directly as well."""
    from umat_oti.core import host_lapack as module

    real_which = shutil.which
    monkeypatch.setattr(module.shutil, "which", lambda name, *a, **k: None if name == "ldconfig"
                        else real_which(name, *a, **k))
    for ldconfig_paths in (module.LDCONFIG_PATHS, ()):
        monkeypatch.setattr(module, "LDCONFIG_PATHS", ldconfig_paths)
        assert [os.path.realpath(p) for p in module._ldconfig("liblapack.so")][:1] == \
            [os.path.realpath(REFERENCE_LAPACK)]
    monkeypatch.setenv("UMAT_OTI_LAPACK", "reference")
    module.host_lapack.cache_clear()
    try:
        record = module.host_lapack("gfortran").as_dict()
    finally:
        module.host_lapack.cache_clear()
    assert record["kind"] == "reference"
    assert record["version"]["files"][0] == os.path.realpath(REFERENCE_LAPACK)
    assert re.fullmatch(r"\d+\.\d+\.\d+", record["version"]["lapack_version"])


@pytest.mark.parametrize("routine, call", [
    ("DPOTRS", "CALL DPOTRS('U', 3, 1, A, 3, B, 3, INFO)"),
    ("DGEEV", "CALL DGEEV('N','N',3,A,3,WR,WI,VL,3,VR,3,WK,9,INFO)"),
    # functions, referenced in expressions: refused by name, not as arrays
    ("DASUM", "B(1) = B(1) + DASUM(3, B, 1)"),
    ("DLAMCH", "B(1) = B(1)*(1.0D0 + DLAMCH('E'))"),
], ids=["DPOTRS", "DGEEV", "DASUM", "DLAMCH"])
def test_a_routine_with_no_supplied_body_is_refused_by_name(tmp_path, routine, call):
    umat = HEADER + """      DIMENSION A(3,3), B(3), WR(3), WI(3), VL(3,3), VR(3,3), WK(9)
      INTEGER INFO
      DO I = 1, 3
        DO J = 1, 3
          A(I,J) = 0.1D0*I*J
        END DO
        A(I,I) = PROPS(1) + DSTRAN(I)
        B(I) = DSTRAN(I)
      END DO
      """ + call + """
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + B(MIN(I,3))*A(1,1)
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      RETURN
      END
"""
    src = tmp_path / "src" / "u.f"
    src.parent.mkdir()
    src.write_text(umat)
    done = subprocess.run([sys.executable, "-m", "umat_oti.cli", "jacobian", str(src), "--ntens", "6",
                           "--out", str(tmp_path / "out")], capture_output=True, text=True)
    assert done.returncode != 0
    summary = json.loads(done.stdout)
    message = " ".join(summary["blockers"])
    assert routine in message and "LAPACK/BLAS routine" in message and "DGESV" in message
    assert "no confirmed shape" not in message


@pytest.mark.abaqus
@pytest.mark.skipif(shutil.which("abaqus") is None, reason="needs Abaqus")
@pytest.mark.parametrize("name, umat", [("lu", LU_UMAT), ("blas", BLAS_UMAT), ("author", AUTHOR_UMAT),
                                        ("author_dgemm", AUTHOR_DGEMM_UMAT), ("author_ddot", AUTHOR_DDOT_UMAT),
                                        ("functions", FUNCTIONS_UMAT)],
                         ids=["lu", "blas", "author", "author_dgemm", "author_ddot", "functions"])
def test_the_transformed_umat_builds_the_abaqus_way_without_standard_names(tmp_path, name, umat):
    out = _transformed(tmp_path, umat, name)
    combined = next(out.glob("*_oti_combined.f90"))
    work = tmp_path / "make"
    work.mkdir()
    shutil.copy2(combined, work / combined.name)
    done = subprocess.run(["abaqus", "make", f"library={combined.name}", "directory=."], cwd=work,
                          capture_output=True, text=True)
    library = work / "libstandardU.so"
    assert done.returncode == 0 and library.is_file(), done.stdout[-2000:]
    dynamic = subprocess.run(["nm", "-D", "--defined-only", str(library)], capture_output=True, text=True).stdout
    assert not ({line.split()[-1] for line in dynamic.splitlines() if line.split()} & STANDARD_SYMBOLS)
