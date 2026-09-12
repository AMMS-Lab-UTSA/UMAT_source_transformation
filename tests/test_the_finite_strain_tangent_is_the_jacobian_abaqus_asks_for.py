"""Abaqus's DDSDDE under nlgeom, and what the transform used to emit instead.

    DDSDDE(ij,kl) = d sigma_ij / d eps_kl  +  sigma_ij delta_kl

with the strain increment meaning ``l = dF . F^-1 = eps``, i.e. ``dF = eps.F``.
The transform seeded ``dF = eps`` and extracted only the first term. Both
halves are measured here: the emitted text says which map was written, and
gfortran says what the converted build returns.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _ddsdde_extraction_lines,
    _finite_dfgrd1_seed_lines,
    direct_component_count_expression,
    parse_finite_dfgrd1_seed_line,
    seeded_kinematics,
)

GFORTRAN = shutil.which("gfortran")
needs_gfortran = pytest.mark.skipif(GFORTRAN is None, reason="gfortran not on PATH")

MAPPINGS = {"stress": "STRESS", "ddsdde": "DDSDDE"}


# ---------------------------------------------------------------------------
# What is emitted
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_the_gradient_seed_is_pushed_forward_by_the_deformation_gradient():
    """``dF = eps . F``, not ``dF = eps``.

    The velocity gradient a perturbation of F produces is ``l = dF . F^-1``,
    so asking for ``l = eps`` asks for ``dF = eps . F``; adding eps straight
    onto F asks for ``l = eps . F^-1``, which is the same only at F = I.
    Measured against a centred difference of the compiled original for
    Sina-Taghizadeh/CompresibleNeoHookean at F with ||F-I||_F = 9.8e-02: with
    the additive seed and the Kirchhoff term the converted tangent sits
    4.997e-02 from the reference at every step size from 1e-3 to 1e-7; with
    the push-forward and the Kirchhoff term it sits 1.88e-11 at h=1e-5, on a
    plateau 1.15e-10 / 1.88e-11 / 1.19e-10 over h = 1e-4, 1e-5, 1e-6.
    """
    text = "\n".join(_finite_dfgrd1_seed_lines("fixed", 6))
    assert "DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1*DFGRD1(1,1)" in text
    assert "DFGRD1_OTI(1,3) = DFGRD1_OTI(1,3) + OTI_E1*DFGRD1(1,3)" in text
    # A shear direction puts half of the transposed row on each of the two
    # positions that make the strain increment symmetric.
    assert "DFGRD1_OTI(1,2) = DFGRD1_OTI(1,2) + 0.5D0*OTI_E4*DFGRD1(2,2)" in text
    assert "DFGRD1_OTI(2,2) = DFGRD1_OTI(2,2) + 0.5D0*OTI_E4*DFGRD1(1,2)" in text
    # The right-hand side reads the REAL gradient. Reading the shadow would
    # fold the perturbation into its own push-forward.
    assert "DFGRD1_OTI(1,1) + OTI_E1*DFGRD1_OTI(1,1)" not in text
    # Every emitted statement fits a fixed-form line, so a reader working one
    # physical line at a time still sees a whole seed injection.
    for line in text.splitlines():
        assert len(line) <= 72, line


@pytest.mark.unit
@pytest.mark.regression
def test_the_emitted_seed_reads_back_as_the_same_strain_increment_it_always_did():
    """The push-forward form carries the same eps the additive form did.

    Everything downstream -- the corpus's "driven through" classification, the
    replay reference, the semantic checks -- reconstructs the perturbation from
    ``(row, column, coefficient, direction)`` tuples. Those are unchanged, so
    the readers need no change; what changed is that the emitted code now does
    what the readers already assumed it did.
    """
    old = ("      DFGRD1_OTI(1,2) = DFGRD1_OTI(1,2) + 0.5D0*OTI_E4\n"
           "      DFGRD1_OTI(2,1) = DFGRD1_OTI(2,1) + 0.5D0*OTI_E4\n"
           "      DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1\n")
    new = "\n".join(_finite_dfgrd1_seed_lines("fixed", 6))
    assert seeded_kinematics(new).dfgrd1[4] == ((1, 2, 0.5), (2, 1, 0.5))
    assert seeded_kinematics(new).dfgrd1[1] == ((1, 1, 1.0),)
    # The old form is still read, because every source already in the
    # transform store was converted with it.
    assert seeded_kinematics(old).dfgrd1[4] == ((1, 2, 0.5), (2, 1, 0.5))
    assert parse_finite_dfgrd1_seed_line(
        "      DFGRD1_OTI(2,3) = DFGRD1_OTI(2,3) + 0.5D0*OTI_E6*DFGRD1(3,3)"
    ) == (2, 3, 0.5, 6)
    # A line that writes one entry from a different one is not a seed.
    assert parse_finite_dfgrd1_seed_line(
        "      DFGRD1_OTI(2,3) = DFGRD1_OTI(1,3) + OTI_E1*DFGRD1(1,3)") is None
    assert parse_finite_dfgrd1_seed_line(
        "      DFGRD1_OTI(2,3) = DFGRD1_OTI(2,3) + OTI_E1*DFGRD1(1,2)") is None


@pytest.mark.unit
@pytest.mark.regression
def test_the_kirchhoff_term_is_added_only_where_the_gradient_carries_the_seed():
    """A DSTRAN-driven source's extraction is emitted byte-identical.

    Measured over 61 corpus sources re-emitted before and after the change:
    20 came out byte-identical and every one of them is DSTRAN-driven --
    CAEAssistant-Group's ISOTROPIC-ELASTICITY.for among them -- while all 41
    that changed carry a DFGRD1 seed.
    """
    small_strain = _ddsdde_extraction_lines("fixed", MAPPINGS, 6)
    assert not any("Kirchhoff" in line for line in small_strain)
    assert not any("REAL(STRESS_OTI" in line for line in small_strain)

    finite = _ddsdde_extraction_lines("fixed", MAPPINGS, 6, kirchhoff_direct_columns="NDI")
    text = "\n".join(finite)
    assert "IF (OTI_J .LE. NDI) DDSDDE(OTI_I,OTI_J) =" in text
    assert "DDSDDE(OTI_I,OTI_J) + REAL(STRESS_OTI(OTI_I))" in text
    # The GETIM extraction it corrects is still there and still first.
    assert text.index("GETIM(STRESS_OTI(OTI_I),OTI_J)") < text.index("REAL(STRESS_OTI(OTI_I))")
    # Free form says the same thing.
    free = "\n".join(_ddsdde_extraction_lines("free", MAPPINGS, 6, kirchhoff_direct_columns="NDI"))
    assert "IF (OTI_J .LE. NDI)" in free and "REAL(STRESS_OTI(OTI_I))" in free


@pytest.mark.unit
def test_the_direct_column_count_is_the_routines_own_ndi_where_it_has_one():
    """delta_kl is one on the direct columns, and NDI is how many there are."""
    assert direct_component_count_expression({"NDI", "NSHR", "NTENS"}) == "NDI"
    # A model routine reached through a wrapper may not receive NDI.
    assert direct_component_count_expression({"NSHR", "NTENS"}) == "NTENS-NSHR"
    assert direct_component_count_expression({"NTENS"}) == "MIN(3,NTENS)"


# ---------------------------------------------------------------------------
# What the converted build returns
# ---------------------------------------------------------------------------

NEO_HOOKEAN = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      IMPLICIT REAL*8(A-H,O-Z)
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),
     3 DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION B(3,3)
      C10 = PROPS(1)
      D1  = PROPS(2)
      DETF = DFGRD1(1,1)*(DFGRD1(2,2)*DFGRD1(3,3)-DFGRD1(2,3)*DFGRD1(3,2))
     1     - DFGRD1(1,2)*(DFGRD1(2,1)*DFGRD1(3,3)-DFGRD1(2,3)*DFGRD1(3,1))
     2     + DFGRD1(1,3)*(DFGRD1(2,1)*DFGRD1(3,2)-DFGRD1(2,2)*DFGRD1(3,1))
      DO I = 1, 3
         DO J = 1, 3
            B(I,J) = 0.0D0
            DO K = 1, 3
               B(I,J) = B(I,J) + DFGRD1(I,K)*DFGRD1(J,K)
            END DO
         END DO
      END DO
      SCALE = DETF**(-2.0D0/3.0D0)
      TRB = SCALE*(B(1,1)+B(2,2)+B(3,3))/3.0D0
      PR = 2.0D0*(DETF-1.0D0)/D1
      FAC = 2.0D0*C10*SCALE/DETF
      STRESS(1) = FAC*(B(1,1)-TRB/SCALE*0.0D0) - 0.0D0
      STRESS(1) = FAC*B(1,1) - 2.0D0*C10*TRB/DETF + PR
      STRESS(2) = FAC*B(2,2) - 2.0D0*C10*TRB/DETF + PR
      STRESS(3) = FAC*B(3,3) - 2.0D0*C10*TRB/DETF + PR
      STRESS(4) = FAC*B(1,2)
      STRESS(5) = FAC*B(1,3)
      STRESS(6) = FAC*B(2,3)
      DO I = 1, NTENS
         DO J = 1, NTENS
            DDSDDE(I,J) = 0.0D0
         END DO
      END DO
      RETURN
      END
"""

DRIVER = """\
      PROGRAM DRV
      IMPLICIT REAL*8(A-H,O-Z)
      CHARACTER*80 CMNAME
      DIMENSION STRESS(6),STATEV(4),DDSDDE(6,6),DDSDDT(6),DRPLDE(6)
      DIMENSION STRAN(6),DSTRAN(6),TIME(2),PREDEF(1),DPRED(1)
      DIMENSION PROPS(2),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      CMNAME='X'
      NDI=3
      NSHR=3
      NTENS=6
      NSTATV=4
      NPROPS=2
      READ(*,*) PROPS(1), PROPS(2)
      READ(*,*) ((DFGRD1(I,J), J=1,3), I=1,3)
      DO I=1,6
         STRESS(I)=0.0D0
         STRAN(I)=0.0D0
         DSTRAN(I)=0.0D0
      END DO
      DO I=1,4
         STATEV(I)=0.0D0
      END DO
      DO I=1,3
         DO J=1,3
            DFGRD0(I,J)=0.0D0
            DROT(I,J)=0.0D0
         END DO
         DFGRD0(I,I)=1.0D0
         DROT(I,I)=1.0D0
      END DO
      CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      WRITE(*,'(6ES26.17)') (STRESS(I), I=1,6)
      DO I=1,6
         WRITE(*,'(6ES26.17)') (DDSDDE(I,J), J=1,6)
      END DO
      END
"""

ABA_PARAM = "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n"

_TERMS = {1: [(0, 0, 1.0)], 2: [(1, 1, 1.0)], 3: [(2, 2, 1.0)],
          4: [(0, 1, 0.5), (1, 0, 0.5)], 5: [(0, 2, 0.5), (2, 0, 0.5)],
          6: [(1, 2, 0.5), (2, 1, 0.5)]}


def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _run(exe, props, gradient):
    payload = (f"{props[0]!r} {props[1]!r}\n"
               + "\n".join(" ".join(repr(v) for v in row) for row in gradient) + "\n")
    done = subprocess.run([str(exe)], input=payload, capture_output=True,
                          text=True, timeout=120, cwd=str(Path(exe).parent))
    rows = [[float(x) for x in line.split()] for line in done.stdout.splitlines() if line.strip()]
    assert len(rows) >= 7, done.stdout + done.stderr
    return rows[0], rows[1:7]


def _corrected_reference(exe, props, gradient, step):
    """d sigma/d eps by centred difference with dF = eps.F, plus sigma (x) delta."""
    sigma, _ = _run(exe, props, gradient)
    columns = []
    for direction in range(1, 7):
        eps = [[0.0] * 3 for _ in range(3)]
        for i, j, c in _TERMS[direction]:
            eps[i][j] += c
        d_gradient = _matmul(eps, gradient)
        plus = [[gradient[i][j] + step * d_gradient[i][j] for j in range(3)] for i in range(3)]
        minus = [[gradient[i][j] - step * d_gradient[i][j] for j in range(3)] for i in range(3)]
        sp, _ = _run(exe, props, plus)
        sm, _ = _run(exe, props, minus)
        columns.append([(sp[i] - sm[i]) / (2 * step) for i in range(6)])
    matrix = [[columns[j][i] for j in range(6)] for i in range(6)]
    for i in range(6):
        for j in range(3):
            matrix[i][j] += sigma[i]
    return sigma, matrix


def _relative_frobenius(a, b):
    num = sum((a[i][j] - b[i][j]) ** 2 for i in range(6) for j in range(6)) ** 0.5
    den = sum(b[i][j] ** 2 for i in range(6) for j in range(6)) ** 0.5
    return num / den


def _build(directory: Path, sources, name):
    done = subprocess.run(
        [GFORTRAN, "-ffixed-form", "-ffixed-line-length-none", "-w",
         *[str(s) for s in sources], "-o", name],
        cwd=str(directory), capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-3000:]
    return directory / name


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@needs_gfortran
def test_the_converted_finite_strain_tangent_lands_on_the_abaqus_jacobian(tmp_path):
    """The converted DDSDDE reaches 1e-9 of a centred difference of the original.

    The reference is built from the ORIGINAL compiled UMAT, differenced with
    ``dF = eps.F`` and raised by ``sigma (x) delta`` -- Abaqus's own
    definition, and no part of it shares a line of code with the transform.

    Measured here on a compressible neo-Hookean UMAT at
    F = [[1.08,0.03,0.02],[0.01,0.96,0.015],[0.02,0.005,1.02]], relative
    Frobenius residual of the converted tangent against that reference:
    of order 1e-10 on the plateau h = 1e-4 .. 1e-6. The same comparison for
    Sina-Taghizadeh/CompresibleNeoHookean.for -- a real corpus source, the one
    a licensed Abaqus run moved from "verified" to "tangent_not_verified"
    under the corrected reference -- gives 1.88e-11 at h=1e-5, against
    4.997e-02 with the Kirchhoff term alone, 5.373e-02 with the push-forward
    alone and 6.202e-02 with neither, each of those three step-independent
    across h = 1e-3 .. 1e-7.
    """
    from umat_oti.app.engine import _build_contract
    from umat_oti.services.transformation import TransformationOptions, run_transformation

    reference_dir = tmp_path / "reference"
    reference_dir.mkdir()
    (reference_dir / "neo.f").write_text(NEO_HOOKEAN, encoding="utf-8")
    (reference_dir / "drv.f").write_text(DRIVER, encoding="utf-8")
    for name in ("ABA_PARAM.INC", "aba_param.inc"):
        (reference_dir / name).write_text(ABA_PARAM, encoding="utf-8")
    reference_exe = _build(reference_dir, ["neo.f", "drv.f"], "ref")

    work = tmp_path / "work"
    work.mkdir()
    staged = work / "neo.f"
    staged.write_text(NEO_HOOKEAN, encoding="utf-8")
    for name in ("ABA_PARAM.INC", "aba_param.inc"):
        (work / name).write_text(ABA_PARAM, encoding="utf-8")
    config, finite = _build_contract("neo", "auto", "STRESS", "DDSDDE", 6, 1, staged)
    assert finite, "this source is driven by the deformation gradient"
    (work / "contract.json").write_text(json.dumps(config), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    for name in ("ABA_PARAM.INC", "aba_param.inc"):
        (out / name).write_text(ABA_PARAM, encoding="utf-8")
    report, _ = run_transformation(work / "contract.json", out,
                                   TransformationOptions(compile_generated=True))
    assert report.get("transform_success"), report.get("warnings")
    assert (report.get("compilation") or {}).get("status") == "compiled", report.get("compilation")

    (out / "drv.f").write_text(DRIVER, encoding="utf-8")
    objects = ["master_parameters.o", "real_utils.o"]
    objects += [p.name for p in sorted(out.glob("otim*.o"))]
    objects += ["oti_intrinsics.o"]
    objects += [p.name for p in sorted(out.glob("umat_oti_helpers.o"))]
    objects += ["transformed_umat.o"]
    converted_exe = _build(out, ["drv.f", *objects], "oti")

    props = [0.5, 0.02]
    gradient = [[1.08, 0.03, 0.02], [0.01, 0.96, 0.015], [0.02, 0.005, 1.02]]
    sigma_converted, tangent = _run(converted_exe, props, gradient)
    sigma_reference, _ = _run(reference_exe, props, gradient)
    # The value was never the defect; only the derivative was.
    assert sigma_converted == pytest.approx(sigma_reference, rel=1e-12, abs=1e-14)

    residuals = {}
    for step in (1e-4, 1e-5, 1e-6):
        _, reference = _corrected_reference(reference_exe, props, gradient, step)
        residuals[step] = _relative_frobenius(tangent, reference)
    best = min(residuals.values())
    assert best < 1e-9, residuals

    # And the correction is not cosmetic: without the Kirchhoff term the same
    # comparison is of order |sigma|/|DDSDDE|, which is far above 1e-9.
    _, reference = _corrected_reference(reference_exe, props, gradient, 1e-5)
    uncorrected = [[reference[i][j] - (sigma_reference[i] if j < 3 else 0.0)
                    for j in range(6)] for i in range(6)]
    assert _relative_frobenius(tangent, uncorrected) > 1e-3, "the term is not small"
