"""B17 rule G2c: SPRIND / SPRINC / SINV / ROTSIG / GETRANK stubs of the offline drivers.

The reference is the real Abaqus 2021.HF5: tests/fixtures/utility_semantics holds the
probe UMAT, the three decks, and the 148 tensors it measured. The order of the
principal values is not documented and is not ascending; the stub reproduces what
was measured and STOPS where the solver's order is algorithm-dependent.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "utility_semantics"
sys.path.insert(0, str(REPO / "tools"))

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")

PROGRAM = """
PROGRAM t
  IMPLICIT NONE
  INTEGER :: n, ndi, nshr, k, i, j
  REAL(8) :: s(6), ps(3), pc(3), an(3,3), s1, s2, r(3,3), o(6)
  READ(*,*) n
  DO k = 1, n
    READ(*,*) ndi, nshr, (s(i), i=1,6)
    CALL SPRIND(s, ps, an, 1, ndi, nshr)
    CALL SPRINC(s, pc, 1, ndi, nshr)
    CALL SINV(s, s1, s2, ndi, nshr)
    WRITE(*,'(A,20(1X,ES24.16))') 'R', (ps(i),i=1,3), (pc(i),i=1,3), s1, s2, ((an(i,j),j=1,3),i=1,3)
  END DO
END PROGRAM t
"""


def _build(tmp_path):
    from umat_oti.abaqus.replay import utility_stub_block
    src = tmp_path / "t.f90"
    src.write_text(PROGRAM + utility_stub_block())
    exe = tmp_path / "t"
    done = subprocess.run(["gfortran", "-O0", "-w", str(src), "-o", str(exe)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    return exe


def _run(exe, cases):
    text = f"{len(cases)}\n" + "\n".join(
        f"{c['ndi']} {c['nshr']} " + " ".join(repr(float(x)) for x in c["s"]) for c in cases)
    return subprocess.run([str(exe)], input=text, capture_output=True, text=True)



def test_the_stub_reproduces_the_solver_on_every_measured_tensor(tmp_path):
    exe = _build(tmp_path)
    data = json.loads((FIX / "abaqus_2021_measured.json").read_text())
    stopped = 0
    checked = 0
    for case in data["cases"]:
        done = _run(exe, [case])
        if done.returncode == 7:
            # a 3-D repeated value with a shear: refused, never guessed
            s = np.array(case["s"][:6])
            m = np.diag(s[:3]); m[0, 1] = m[1, 0] = s[3]; m[0, 2] = m[2, 0] = s[4]; m[1, 2] = m[2, 1] = s[5]
            w = np.linalg.eigvalsh(m)
            assert case["ndi"] == 3 and case["nshr"] == 3
            assert np.min(np.diff(w)) <= 1e-9 * max(abs(w).max(), 1e-300), case["tag"]
            stopped += 1
            continue
        assert done.returncode == 0, (case["tag"], done.stderr)
        v = [float(x) for x in done.stdout.split()[1:]]
        ps, pc, sinv, an = v[0:3], v[3:6], v[6:8], np.array(v[8:17]).reshape(3, 3)
        assert np.allclose(ps, case["ps"], atol=1e-9, rtol=1e-9), (case["tag"], ps, case["ps"])
        assert np.allclose(pc, case["pc"], atol=1e-9, rtol=1e-9), case["tag"]
        assert np.allclose(sinv, case["sinv"], atol=1e-9, rtol=1e-9), case["tag"]
        # the direction is the solver's up to sign
        ref = np.array(case["an"]).reshape(3, 3)
        for k in range(3):
            ok_sign = np.allclose(an[k], ref[k], atol=1e-8) or np.allclose(an[k], -ref[k], atol=1e-8)
            # a repeated value has no unique direction: only require an eigenvector
            s = np.array(case["s"][:6]); nd = case["ndi"]
            m = np.zeros((3, 3))
            for i in range(nd):
                m[i, i] = s[i]
            if nd == 2:
                m[0, 1] = m[1, 0] = s[2]
            else:
                m[0, 1] = m[1, 0] = s[3]
                if case["nshr"] == 3:
                    m[0, 2] = m[2, 0] = s[4]; m[1, 2] = m[2, 1] = s[5]
            assert np.allclose(m @ an[k], ps[k] * an[k], atol=1e-8), case["tag"]
            if len(set(np.round(ps, 9))) == 3:
                assert ok_sign, (case["tag"], an[k], ref[k])
        checked += 1
    assert checked >= 140 and stopped >= 4, (checked, stopped)


def test_hand_computed_values(tmp_path):
    exe = _build(tmp_path)
    cases = [
        {"ndi": 3, "nshr": 3, "s": [10, 0, 0, 0, 0, 0]},      # uniaxial: mean 10/3, Mises 10
        {"ndi": 3, "nshr": 3, "s": [0, 0, 0, 3, 0, 0]},       # pure shear 3: values (3,-3,0), Mises 3*sqrt(3)
        {"ndi": 3, "nshr": 3, "s": [1, 2, 3, 0, 0, 0]},       # no shear: storage order
    ]
    done = _run(exe, cases)
    rows = [[float(x) for x in line.split()[1:]] for line in done.stdout.splitlines()]
    assert np.allclose(rows[0][6:8], [10 / 3, 10.0])
    assert np.allclose(rows[1][0:3], [3.0, -3.0, 0.0])
    assert np.isclose(rows[1][7], 3 * np.sqrt(3))
    assert np.allclose(rows[2][0:3], [1, 2, 3])
    assert np.allclose(rows[0][8:17], np.eye(3).reshape(-1))


def test_a_repeated_value_with_a_shear_stops_instead_of_guessing(tmp_path):
    exe = _build(tmp_path)
    q = np.linalg.qr(np.random.default_rng(3).normal(size=(3, 3)))[0]
    m = q @ np.diag([5.0, 5.0, 2.0]) @ q.T
    case = {"ndi": 3, "nshr": 3, "s": [m[0, 0], m[1, 1], m[2, 2], m[0, 1], m[0, 2], m[1, 2]]}
    done = _run(exe, [case])
    assert done.returncode == 7 and "repeated principal value" in done.stderr


def test_rotsig_matches_the_solvers_r_s_rt(tmp_path):
    from umat_oti.abaqus.replay import utility_stub_block
    prog = """
PROGRAM t
  IMPLICIT NONE
  REAL(8) :: s(6), r(3,3), o(6)
  INTEGER :: lstr
  READ(*,*) lstr, s, r
  CALL ROTSIG(s, r, o, lstr, 3, 3)
  WRITE(*,'(6(1X,ES24.16))') o
END PROGRAM t
"""
    src = tmp_path / "r.f90"
    src.write_text(prog + utility_stub_block())
    exe = tmp_path / "r"
    assert subprocess.run(["gfortran", "-w", str(src), "-o", str(exe)]).returncode == 0
    c1, s1 = np.cos(np.pi / 6), np.sin(np.pi / 6)
    c2, s2 = np.cos(0.3490658503988659), np.sin(0.3490658503988659)
    R = np.array([[c1, -s1 * c2, s1 * s2], [s1, c1 * c2, -c1 * s2], [0, s2, c2]])
    for lstr, half in ((1, 1.0), (2, 0.5)):
        s = np.array([1.0, -2.0, 3.0, 0.7, -0.4, 0.2])
        m = np.diag(s[:3]); m[0, 1] = m[1, 0] = s[3] * half; m[0, 2] = m[2, 0] = s[4] * half
        m[1, 2] = m[2, 1] = s[5] * half
        r = R @ m @ R.T
        hand = [r[0, 0], r[1, 1], r[2, 2], r[0, 1] / half, r[0, 2] / half, r[1, 2] / half]
        done = subprocess.run([str(exe)], input=f"{lstr} " + " ".join(repr(float(x)) for x in s) + " " +
                              " ".join(repr(float(x)) for x in R.reshape(-1, order="F")), capture_output=True, text=True)
        assert np.allclose([float(x) for x in done.stdout.split()], hand, atol=1e-12)


UNSET_AFTER_SPRIND = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION PS(3), AN(3,3)
      DO I=1,NTENS
        STRESS(I) = STRESS(I) + PROPS(1)*DSTRAN(I)
        DO J=1,NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      CALL SPRIND(STRESS, PS, AN, 1, NDI, NSHR)
      STRESS(1) = STRESS(1) + 1.D-3*PS(1)
@UNSET@
      STATEV(1) = STATEV(1) + 1.D0
      RETURN
      END
"""


def _check(tmp_path, text):
    import verify_store_in_abaqus as V
    source = tmp_path / "original_probed.for"
    source.write_text(text)
    include = tmp_path / "inc"
    include.mkdir()
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (include / name).write_text("      implicit real*8(a-h,o-z)\n")
    entries = [{"NTENS": 6, "NSTATV": 1, "NPROPS": 1, "NDI": 3, "NSHR": 3,
                "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [1.0, 2.0, 3.0, 0.5, 0.2, 0.1],
                "STATEV0": [0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3, 2e-3, 3e-3, 5e-4, 2e-4, 1e-4],
                "PROPS": [10.0], "COORDS": [0.0, 0.0, 0.0, 1.0]}] * 2
    return V.init_variant_check(source, entries, tmp_path / "work", ntens=6,
                                include_dirs=[include])


def test_a_clean_source_that_calls_sprind_links_and_is_not_flagged(tmp_path):
    check = _check(tmp_path, UNSET_AFTER_SPRIND.replace("@UNSET@", ""))
    assert check["established"], check
    assert not (check["undefined"]["STRESS"] or check["undefined"]["DDSDDE"])


def test_a_source_that_reads_an_uninitialised_variable_after_sprind_is_still_flagged(tmp_path):
    # PLANTED ERROR: UNSET is never assigned and reaches STRESS(2).
    check = _check(tmp_path, UNSET_AFTER_SPRIND.replace(
        "@UNSET@", "      STRESS(2) = STRESS(2) + UNSET"))
    assert check["established"], check
    assert check["undefined"]["STRESS"] == [2], check["undefined"]
