"""The complex OTI type (oti_complex): values and first derivatives.

Every operator and intrinsic the corpus's DOUBLE COMPLEX sources use is
evaluated on ``z = (x + e1) + i (y + e2)``, ``w = (u + e3) + i (v + e4)`` and a
real OTI ``t = s + e5``. So the five OTI parts of a result are its partial
derivatives with respect to x, y, u, v and s. They are compared with central
finite differences of the same expression in 60-digit mpmath arithmetic (step
1e-25, so the reference is exact to far below double precision). Values are
compared with the Fortran intrinsic complex arithmetic of the same expression,
evaluated in the same program, and with mpmath.

Holomorphic operations must give f'(z) (and i f'(z) along y); REAL/DBLE,
AIMAG, CONJG and ABS are checked as the real maps they are. The tolerance is
1e-12 relative to the size of the derivative row.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

mpmath = pytest.importorskip("mpmath")

from umat_oti.oti.complex_oti import generate_complex_oti_module  # noqa: E402
from umat_oti.oti.module_generator import generate_otilib_module  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")

NDIR = 5
mp = mpmath.mp

#: (name, complex-OTI expression, intrinsic expression, result kind, mpmath reference)
#: The intrinsic expression uses zc, wc (COMPLEX(8)) and tc (REAL(8)).
CASES = [
    ("add_zz", "z + w", "zc + wc", "Z", lambda z, w, t: z + w),
    ("add_zt", "z + t", "zc + tc", "Z", lambda z, w, t: z + t),
    ("add_tz", "t + z", "tc + zc", "Z", lambda z, w, t: t + z),
    ("add_zr", "z + 2.5d0", "zc + 2.5d0", "Z", lambda z, w, t: z + 2.5),
    ("add_zc", "z + (1.5d0,-0.5d0)", "zc + (1.5d0,-0.5d0)", "Z", lambda z, w, t: z + mp.mpc(1.5, -0.5)),
    ("add_zi", "z + 3", "zc + 3", "Z", lambda z, w, t: z + 3),
    ("sub_zz", "z - w", "zc - wc", "Z", lambda z, w, t: z - w),
    ("sub_tz", "t - z", "tc - zc", "Z", lambda z, w, t: t - z),
    ("sub_cz", "(1.5d0,-0.5d0) - z", "(1.5d0,-0.5d0) - zc", "Z", lambda z, w, t: mp.mpc(1.5, -0.5) - z),
    ("neg", "-z", "-zc", "Z", lambda z, w, t: -z),
    ("mul_zz", "z * w", "zc * wc", "Z", lambda z, w, t: z * w),
    ("mul_zt", "z * t", "zc * tc", "Z", lambda z, w, t: z * t),
    ("mul_rz", "2.5d0 * z", "2.5d0 * zc", "Z", lambda z, w, t: 2.5 * z),
    ("mul_cz", "(1.5d0,-0.5d0) * z", "(1.5d0,-0.5d0) * zc", "Z", lambda z, w, t: mp.mpc(1.5, -0.5) * z),
    ("mul_tc", "t * (0.25d0,2.0d0)", "tc * (0.25d0,2.0d0)", "Z", lambda z, w, t: t * mp.mpc(0.25, 2.0)),
    ("mul_iz", "3 * z", "3 * zc", "Z", lambda z, w, t: 3 * z),
    ("div_zz", "z / w", "zc / wc", "Z", lambda z, w, t: z / w),
    ("div_zt", "z / t", "zc / tc", "Z", lambda z, w, t: z / t),
    ("div_tz", "t / z", "tc / zc", "Z", lambda z, w, t: t / z),
    ("div_rz", "2.5d0 / z", "2.5d0 / zc", "Z", lambda z, w, t: 2.5 / z),
    ("div_zc", "z / (1.5d0,-0.5d0)", "zc / (1.5d0,-0.5d0)", "Z", lambda z, w, t: z / mp.mpc(1.5, -0.5)),
    ("div_cz", "(1.5d0,-0.5d0) / z", "(1.5d0,-0.5d0) / zc", "Z", lambda z, w, t: mp.mpc(1.5, -0.5) / z),
    ("div_zi", "z / 3", "zc / 3", "Z", lambda z, w, t: z / 3),
    ("pow_2", "z**2", "zc**2", "Z", lambda z, w, t: z ** 2),
    ("pow_3", "z**3", "zc**3", "Z", lambda z, w, t: z ** 3),
    ("pow_m2", "z**(-2)", "zc**(-2)", "Z", lambda z, w, t: z ** -2),
    ("pow_r_int", "z**2.0d0", "zc**2.0d0", "Z", lambda z, w, t: z ** 2),
    ("pow_half", "z**0.5d0", "zc**0.5d0", "Z", lambda z, w, t: mp.exp(0.5 * mp.log(z))),
    ("pow_r", "z**1.7d0", "zc**1.7d0", "Z", lambda z, w, t: mp.exp(mp.mpf("1.7") * mp.log(z))),
    ("pow_zz", "z**w", "zc**wc", "Z", lambda z, w, t: mp.exp(w * mp.log(z))),
    ("pow_zt", "z**t", "zc**tc", "Z", lambda z, w, t: mp.exp(t * mp.log(z))),
    ("pow_zc", "z**(0.3d0,0.2d0)", "zc**(0.3d0,0.2d0)", "Z",
     lambda z, w, t: mp.exp(mp.mpc(0.3, 0.2) * mp.log(z))),
    ("pow_rz", "2.5d0**z", "2.5d0**zc", "Z", lambda z, w, t: mp.exp(z * mp.log(2.5))),
    ("pow_tz", "t**z", "tc**zc", "Z", lambda z, w, t: mp.exp(z * mp.log(t))),
    ("sqrt", "SQRT(z)", "SQRT(zc)", "Z", lambda z, w, t: mp.sqrt(z)),
    ("log", "LOG(z)", "LOG(zc)", "Z", lambda z, w, t: mp.log(z)),
    ("exp", "EXP(z)", "EXP(zc)", "Z", lambda z, w, t: mp.exp(z)),
    ("sin", "SIN(z)", "SIN(zc)", "Z", lambda z, w, t: mp.sin(z)),
    ("cos", "COS(z)", "COS(zc)", "Z", lambda z, w, t: mp.cos(z)),
    ("tan", "TAN(z)", "TAN(zc)", "Z", lambda z, w, t: mp.tan(z)),
    ("sinh", "SINH(z)", "SINH(zc)", "Z", lambda z, w, t: mp.sinh(z)),
    ("cosh", "COSH(z)", "COSH(zc)", "Z", lambda z, w, t: mp.cosh(z)),
    ("conjg", "CONJG(z)", "CONJG(zc)", "Z", lambda z, w, t: mp.conj(z)),
    ("dcmplx_tt", "DCMPLX(t, t*t)", "DCMPLX(tc, tc*tc)", "Z", lambda z, w, t: mp.mpc(t, t * t)),
    ("dcmplx_rt", "DCMPLX(1.5d0, t)", "DCMPLX(1.5d0, tc)", "Z", lambda z, w, t: mp.mpc(1.5, t)),
    ("cmplx_tr", "CMPLX(t, 2.0d0)", "CMPLX(tc, 2.0d0, 8)", "Z", lambda z, w, t: mp.mpc(t, 2.0)),
    ("cmplx_ttk", "CMPLX(t, t, 8)", "CMPLX(tc, tc, 8)", "Z", lambda z, w, t: mp.mpc(t, t)),
    # Composite: the arccos of the corpus's eigenvalue solver.
    ("zacos", "-(0.0d0,1.0d0) * LOG(z + (0.0d0,1.0d0) * SQRT(1.0d0 - z*z))",
     "-(0.0d0,1.0d0) * LOG(zc + (0.0d0,1.0d0) * SQRT(1.0d0 - zc*zc))", "Z",
     lambda z, w, t: -1j * mp.log(z + 1j * mp.sqrt(1 - z * z))),
    # Real-valued (non-holomorphic, real-differentiable) maps.
    ("dble", "DBLE(z)", "DBLE(zc)", "T", lambda z, w, t: mp.re(z)),
    ("real", "REAL(z)", "REAL(zc, 8)", "T", lambda z, w, t: mp.re(z)),
    ("aimag", "AIMAG(z)", "AIMAG(zc)", "T", lambda z, w, t: mp.im(z)),
    ("abs", "ABS(z)", "ABS(zc)", "T", lambda z, w, t: abs(z)),
    ("abs_zw", "ABS(z*w - t)", "ABS(zc*wc - tc)", "T", lambda z, w, t: abs(z * w - t)),
    ("atan2", "ATAN2(AIMAG(z), DBLE(z))", "ATAN2(AIMAG(zc), DBLE(zc))", "T",
     lambda z, w, t: mp.atan2(mp.im(z), mp.re(z))),
    ("atan2_tr", "ATAN2(t, -0.5d0)", "ATAN2(tc, -0.5d0)", "T", lambda z, w, t: mp.atan2(t, -0.5)),
    ("atan2_rt", "ATAN2(-0.5d0, t)", "ATAN2(-0.5d0, tc)", "T", lambda z, w, t: mp.atan2(-0.5, t)),
    ("dble_t", "DBLE(t*t)", "DBLE(tc*tc)", "T", lambda z, w, t: t * t),
    # Assigning a complex to a real keeps the real part, derivative and all.
    ("assign_t_from_z", "z*w", "DBLE(zc*wc)", "TZ", lambda z, w, t: mp.re(z * w)),
]

#: (x, y, u, v, s): off the negative real axis, in every quadrant, and on the
#: positive real axis (where the imaginary part is zero but its derivative is not).
POINTS = [
    (1.3, 0.7, 0.4, -0.9, 0.8),
    (-0.8, 0.4, 1.1, 0.3, 1.7),
    (-0.6, -1.1, -0.7, 0.5, 0.45),
    (0.9, -0.2, 2.0, 0.1, 2.3),
    (2.0, 0.0, 0.5, 0.0, 1.2),
]


def _program(type_name: str, cases, points) -> str:
    ztype = "Z" + type_name
    lines = [
        "program complex_oti_check",
        "  use otim%dn1" % NDIR,
        "  use oti_complex",
        "  implicit none",
        f"  type({ztype}) :: z, w, rz",
        f"  type({type_name}) :: t, rt",
        "  complex(8) :: zc, wc, rc",
        "  real(8) :: tc, rtc, x, y, u, v, s",
        "  integer :: k, ip",
        f"  do ip = 1, {len(points)}",
        "    read(*,*) x, y, u, v, s",
        "    z%RE = x + E1",
        "    z%IM = y + E2",
        "    w%RE = u + E3",
        "    w%IM = v + E4",
        "    t = s + E5",
        "    zc = CMPLX(x, y, 8)",
        "    wc = CMPLX(u, v, 8)",
        "    tc = s",
    ]
    for name, expr, native, kind, _ in cases:
        if kind == "Z":
            lines += [f"    rz = {expr}", f"    rc = {native}",
                      f"    write(*,'(A,1X,I0,40ES26.17)') '{name}', ip, REAL(rz%RE), "
                      f"(GETIM(rz%RE,k), k=1,{NDIR}), REAL(rz%IM), (GETIM(rz%IM,k), k=1,{NDIR}), "
                      "DBLE(rc), AIMAG(rc)"]
        else:
            lines += [f"    rt = {expr}", f"    rtc = {native}",
                      f"    write(*,'(A,1X,I0,40ES26.17)') '{name}', ip, REAL(rt), "
                      f"(GETIM(rt,k), k=1,{NDIR}), rtc"]
    lines += ["  end do", "end program complex_oti_check"]
    return "\n".join(lines) + "\n"


def build_and_run(tmp: Path, program: str, stdin: str) -> str:
    module = generate_otilib_module(output_dir=tmp, ntens=NDIR, order=1)
    (tmp / "oti_complex.f90").write_text(
        generate_complex_oti_module(module.module_name, module.type_name))
    (tmp / "check.f90").write_text(program)
    flags = ["-ffree-form", "-ffree-line-length-none", "-O0"]
    for unit in ("master_parameters.f90", "real_utils.f90", f"{module.module_name}.f90",
                 "oti_complex.f90", "check.f90"):
        done = subprocess.run(["gfortran", *flags, "-c", unit], cwd=tmp, capture_output=True, text=True)
        assert done.returncode == 0, f"{unit}:\n{done.stderr[-3000:]}"
    objects = sorted(str(p.name) for p in tmp.glob("*.o"))
    done = subprocess.run(["gfortran", *objects, "-o", "check"], cwd=tmp, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-3000:]
    run = subprocess.run([str(tmp / "check")], input=stdin, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-3000:]
    return run.stdout


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("complex_oti")
    module = generate_otilib_module(output_dir=tmp / "probe", ntens=NDIR, order=1)
    program = _program(module.type_name, CASES, POINTS)
    stdin = "".join(" ".join(repr(v) for v in p) + "\n" for p in POINTS)
    out = build_and_run(tmp, program, stdin)
    parsed = {}
    for line in out.splitlines():
        parts = line.split()
        parsed[(parts[0], int(parts[1]))] = [float(v) for v in parts[2:]]
    return parsed


def _reference(func, point, kind):
    """Value and the five partials of ``func`` in 60-digit arithmetic."""
    mp.dps = 60
    h = mp.mpf("1e-25")
    x, y, u, v, s = [mp.mpf(repr(c)) for c in point]

    def at(dx=0, dy=0, du=0, dv=0, ds=0):
        value = func(mp.mpc(x + dx, y + dy), mp.mpc(u + du, v + dv), s + ds)
        return mp.mpc(value)

    base = at()
    partials = []
    for index in range(NDIR):
        step = [0] * NDIR
        step[index] = h
        plus = at(*step)
        step[index] = -h
        minus = at(*step)
        partials.append((plus - minus) / (2 * h))
    if kind != "Z":
        return float(mp.re(base)), [float(mp.re(p)) for p in partials]
    return complex(base), [complex(p) for p in partials]


def _close(actual, expected, scale, rtol=1e-12):
    return abs(actual - expected) <= rtol * max(scale, 1e-300) + 1e-300


#: (case, point) pairs that sit on the case's own branch cut, where a central
#: difference across the cut is not a derivative: acos is cut on the real axis
#: for |x| > 1, and point 5 is z = 2. Values are still checked there.
ON_A_CUT = {("zacos", 4)}


@pytest.mark.parametrize("name,expr,native,kind,func", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("point_index", range(len(POINTS)))
def test_value_and_first_derivatives(results, name, expr, native, kind, func, point_index):
    point = POINTS[point_index]
    row = results[(name, point_index + 1)]
    value_ref, partials_ref = _reference(func, point, kind)
    if kind == "Z":
        value = complex(row[0], row[NDIR + 1])
        partials = [complex(row[1 + k], row[NDIR + 2 + k]) for k in range(NDIR)]
        intrinsic = complex(row[2 * NDIR + 2], row[2 * NDIR + 3])
    else:
        value = row[0]
        partials = row[1:1 + NDIR]
        intrinsic = row[1 + NDIR]
    scale_value = max(abs(value_ref), 1e-300)
    # The OTI value is the intrinsic's arithmetic (up to rounding) and the true value.
    assert _close(value, intrinsic, scale_value, 1e-13), (name, value, intrinsic)
    if (name, point_index) in ON_A_CUT:
        return
    assert _close(value, value_ref, scale_value, 1e-13), (name, value, value_ref)
    scale = max(abs(p) for p in partials_ref) or 1.0
    for k in range(NDIR):
        assert _close(partials[k], partials_ref[k], scale), (
            f"{name} d/d{'xyuvs'[k]} at {point}: OTI {partials[k]!r} vs FD {partials_ref[k]!r}")


def test_holomorphic_derivative_along_y_is_i_times_along_x(results):
    """Cauchy-Riemann, read straight off the OTI parts: d/dy f = i d/dx f."""
    for name, _, _, kind, _ in CASES:
        if kind != "Z" or name in {"conjg", "dcmplx_tt", "dcmplx_rt", "cmplx_tr", "cmplx_ttk"}:
            continue
        for point_index in range(len(POINTS)):
            if (name, point_index) in ON_A_CUT:
                continue
            row = results[(name, point_index + 1)]
            dx = complex(row[1], row[NDIR + 2])
            dy = complex(row[2], row[NDIR + 3])
            assert abs(dy - 1j * dx) <= 1e-12 * max(abs(dx), 1e-300), (name, dx, dy)


# ---------------------------------------------------------------- branch cuts

CUT_PROGRAM = """
program cuts
  use otim{n}n1
  use oti_complex
  implicit none
  type({z}) :: z, r
  type({t}) :: a
  complex(8) :: c
  ! SQRT and LOG on the cut, both signs of zero, against the intrinsic
  z%RE = -4.0d0 + E1
  z%IM = 0.0d0 + E2
  r = SQRT(z); c = SQRT(CMPLX(-4.0d0, 0.0d0, 8))
  write(*,'(A,8ES26.17)') 'sqrt+', REAL(r%RE), REAL(r%IM), DBLE(c), AIMAG(c), GETIM(r%RE,1), GETIM(r%IM,1), GETIM(r%RE,2), GETIM(r%IM,2)
  z%IM = -1.0d0*E2
  r = SQRT(z); c = SQRT(CMPLX(-4.0d0, -0.0d0, 8))
  write(*,'(A,8ES26.17)') 'sqrt-', REAL(r%RE), REAL(r%IM), DBLE(c), AIMAG(c), GETIM(r%RE,1), GETIM(r%IM,1), GETIM(r%RE,2), GETIM(r%IM,2)
  z%RE = -1.0d0 + E1
  z%IM = 0.0d0 + E2
  r = LOG(z); c = LOG(CMPLX(-1.0d0, 0.0d0, 8))
  write(*,'(A,8ES26.17)') 'log+', REAL(r%RE), REAL(r%IM), DBLE(c), AIMAG(c), GETIM(r%RE,1), GETIM(r%IM,1), GETIM(r%RE,2), GETIM(r%IM,2)
  z%IM = -1.0d0*E2
  r = LOG(z); c = LOG(CMPLX(-1.0d0, -0.0d0, 8))
  write(*,'(A,8ES26.17)') 'log-', REAL(r%RE), REAL(r%IM), DBLE(c), AIMAG(c), GETIM(r%RE,1), GETIM(r%IM,1), GETIM(r%RE,2), GETIM(r%IM,2)
  ! zero: ABS and SQRT are not differentiable there; value 0, derivative 0
  z%RE = 0.0d0 + E1
  z%IM = 0.0d0 + E2
  a = ABS(z)
  r = SQRT(z)
  write(*,'(A,6ES26.17)') 'zero', REAL(a), GETIM(a,1), GETIM(a,2), REAL(r%RE), GETIM(r%RE,1), GETIM(r%IM,2)
  ! a primal on the real axis: imaginary part and its derivative stay zero
  z%RE = 2.0d0 + E1
  z%IM = 0.0d0
  r = SQRT(LOG(z)*EXP(z)) / (z**3 + 1.0d0)
  write(*,'(A,4ES26.17)') 'realaxis', REAL(r%IM), GETIM(r%IM,1), GETIM(r%IM,2), GETIM(r%IM,3)
  ! the author's complex step inside OTI: i is never an OTI direction
  a = 0.7d0 + E1
  r = SIN(DCMPLX(a, 1.0d-10))
  write(*,'(A,4ES26.17)') 'cstep', REAL(AIMAG(r)/1.0d-10), GETIM(AIMAG(r)/1.0d-10, 1), REAL(DBLE(r)), GETIM(DBLE(r), 1)
end program cuts
"""


@pytest.fixture(scope="module")
def cuts(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("complex_oti_cuts")
    module = generate_otilib_module(output_dir=tmp / "probe", ntens=3, order=1)
    global NDIR
    saved, NDIR = NDIR, 3
    try:
        out = build_and_run(tmp, CUT_PROGRAM.format(n=3, z="Z" + module.type_name, t=module.type_name), "")
    finally:
        NDIR = saved
    return {line.split()[0]: [float(v) for v in line.split()[1:]] for line in out.splitlines()}


def test_sqrt_on_the_cut_follows_the_sign_of_zero_like_the_intrinsic(cuts):
    for key, sign in (("sqrt+", 1.0), ("sqrt-", -1.0)):
        re_, im_, cre, cim, dre_dx, dim_dx, dre_dy, dim_dy = cuts[key]
        assert (re_, im_) == pytest.approx((cre, cim), abs=1e-15)
        assert im_ == pytest.approx(sign * 2.0, abs=1e-15)
        # along the axis: d/dx sqrt(z) = 1/(2 sqrt z) = -i sign/4
        assert (dre_dx, dim_dx) == pytest.approx((0.0, -sign * 0.25), abs=1e-15)
        # across it, the one-sided derivative from the side the zero's sign picks,
        # i/(2 sqrt z) along +y; the -0 case is seeded along -y (z%IM = -e2)
        assert (dre_dy, dim_dy) == pytest.approx((0.25, 0.0), abs=1e-15)


def test_log_on_the_cut_follows_the_sign_of_zero_like_the_intrinsic(cuts):
    import math
    for key, sign in (("log+", 1.0), ("log-", -1.0)):
        re_, im_, cre, cim, dre_dx, dim_dx, dre_dy, dim_dy = cuts[key]
        assert (re_, im_) == pytest.approx((cre, cim), abs=1e-15)
        assert im_ == pytest.approx(sign * math.pi, abs=1e-15)
        # d/dx log z = 1/z = -1; along the seeded y direction (+y, or -y for -0): -+i
        assert (dre_dx, dim_dx, dre_dy, dim_dy) == pytest.approx((-1.0, 0.0, 0.0, -sign), abs=1e-15)


def test_abs_and_sqrt_at_zero_return_zero_derivative(cuts):
    assert cuts["zero"] == pytest.approx([0.0] * 6, abs=0.0)


def test_a_real_primal_stays_real_with_its_derivative(cuts):
    assert cuts["realaxis"] == pytest.approx([0.0] * 4, abs=0.0)


def test_an_authors_complex_step_inside_oti_is_not_an_oti_direction(cuts):
    """Im sin(a + ih)/h = cos(a) sinh(h)/h; its OTI part is d/da of that."""
    import math
    h = 1e-10
    cs_value, cs_deriv, re_value, re_deriv = cuts["cstep"]
    assert cs_value == pytest.approx(math.cos(0.7) * math.sinh(h) / h, rel=1e-14)
    assert cs_deriv == pytest.approx(-math.sin(0.7) * math.sinh(h) / h, rel=1e-14)
    assert re_value == pytest.approx(math.sin(0.7) * math.cosh(h), rel=1e-15)
    assert re_deriv == pytest.approx(math.cos(0.7) * math.cosh(h), rel=1e-15)
