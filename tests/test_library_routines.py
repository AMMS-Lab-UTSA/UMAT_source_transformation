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


# --------------------------------------------------------------------------- OTI copies

@pytest.mark.parametrize("name, umat, complex_step", [("lu", LU_UMAT, True), ("blas", BLAS_UMAT, False)])
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


@pytest.mark.parametrize("name, umat", [("lu", LU_UMAT), ("blas", BLAS_UMAT)])
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


@pytest.mark.parametrize("routine, call", [
    ("DPOTRS", "CALL DPOTRS('U', 3, 1, A, 3, B, 3, INFO)"),
    ("DGEEV", "CALL DGEEV('N','N',3,A,3,WR,WI,VL,3,VR,3,WK,9,INFO)"),
])
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


@pytest.mark.abaqus
@pytest.mark.skipif(shutil.which("abaqus") is None, reason="needs Abaqus")
@pytest.mark.parametrize("name, umat", [("lu", LU_UMAT), ("blas", BLAS_UMAT)])
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
