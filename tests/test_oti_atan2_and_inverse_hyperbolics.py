"""ATAN2 and the inverse hyperbolics over the hypercomplex type are exact.

umatCP.for / umatCP_RD2.for (ntnu crystal plasticity) call ATAN2 and ASINH on
differentiated values; the lifter refused ATAN2 because the OTI algebra had no
form of it. Rule (B20 RULES.md R7): oti_intrinsics declares ATAN2 (OTI/OTI,
OTI/real, real/OTI) and ASINH, ACOSH, ATANH over the type, ONLY for a file that
hands them a shadow (so every other output is byte-identical), with the value
of the real intrinsic and the closed-form derivative.

Here each is run against the closed form at points over all quadrants, close to
the branch cut and on the axes. Canaries: a wrong derivative (the sign of the
cross term flipped) is caught by the same comparison; the generic is absent from
a module emitted for a file that does not use it.
"""
import math
import shutil
import subprocess

import pytest

from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions

POINTS = [(1.0, 2.0), (-1.0, 2.0), (-1.0, -2.0), (1.0, -2.0), (0.0, 1.5), (0.0, -1.5),
          (3.0, 0.0), (-3.0, 1e-12), (-3.0, -1e-12), (1e-6, 1e-6), (50.0, 0.3), (0.3, 50.0)]
SEEDS = [(0.7, -0.4), (-0.2, 0.9)]          # (dy, dx) along e1 and e2

DRIVER = """program check
  use otim2n1
  use oti_intrinsics
  implicit none
  type(onumm2n1) :: y, x, r, a
  real(8) :: yy, xx, v1, v2, w1, w2, ay
  do
    read (*, *, end=10) yy, xx, v1, v2, w1, w2
    y = yy; x = xx
    y%e1 = v1; y%e2 = v2; x%e1 = w1; x%e2 = w2
    r = atan2(y, x)
    write (*, '(A,3ES26.17E3)') 'TT ', r%r, r%e1, r%e2
    r = atan2(y, xx)
    write (*, '(A,3ES26.17E3)') 'TR ', r%r, r%e1, r%e2
    r = atan2(yy, x)
    write (*, '(A,3ES26.17E3)') 'RT ', r%r, r%e1, r%e2
    a = y
    r = asinh(a)
    write (*, '(A,3ES26.17E3)') 'ASINH ', r%r, r%e1, r%e2
    a = 1.5d0 + abs(yy)
    a%e1 = v1; a%e2 = v2
    r = acosh(a)
    write (*, '(A,3ES26.17E3)') 'ACOSH ', r%r, r%e1, r%e2
    a = 0.9d0*sin(yy)
    a%e1 = v1; a%e2 = v2
    r = atanh(a)
    write (*, '(A,3ES26.17E3)') 'ATANH ', r%r, r%e1, r%e2
  end do
10 continue
end program check
"""


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required")
    out = tmp_path_factory.mktemp("atan2_oti")
    module = generate_otilib_module(output_dir=out, ntens=2)
    (out / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name, atan2=True,
                                   inverse_hyperbolic=("ASINH", "ACOSH", "ATANH")),
        encoding="ascii")
    (out / "driver.f90").write_text(DRIVER, encoding="ascii")
    done = subprocess.run([compiler, "-O0", "-ffree-line-length-none", module.master_parameters_path.name,
                           module.real_utils_path.name, module.module_path.name, "oti_intrinsics.f90",
                           "driver.f90", "-o", "check"], cwd=out, text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return out / "check"


def _run(executable):
    rows = []
    for (y, x) in POINTS:
        for (dy, dx), (ey, ex) in [(SEEDS[0], SEEDS[1])]:
            rows.append((y, x, dy, ey, dx, ex))
    text = "".join(" ".join(repr(float(v)) for v in row) + "\n" for row in rows)
    result = subprocess.run([str(executable)], input=text, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    lines = [line.split() for line in result.stdout.splitlines()]
    return rows, lines


def _atan2_exact(y, x, dy, dx):
    d = x * x + y * y
    return math.atan2(y, x), (x * dy - y * dx) / d


def test_atan2_value_and_both_partials_match_the_closed_form(build):
    rows, lines = _run(build)
    per_point = 6
    worst = 0.0
    for index, (y, x, dy1, dy2, dx1, dx2) in enumerate(rows):
        block = {ln[0]: [float(v) for v in ln[1:]] for ln in lines[index * per_point:(index + 1) * per_point]}
        for key, ydual, xdual in (("TT", True, True), ("TR", True, False), ("RT", False, True)):
            v, e1, e2 = block[key]
            exp1 = _atan2_exact(y, x, dy1 if ydual else 0.0, dx1 if xdual else 0.0)
            exp2 = _atan2_exact(y, x, dy2 if ydual else 0.0, dx2 if xdual else 0.0)
            assert v == pytest.approx(exp1[0], abs=1e-14), (key, y, x)
            worst = max(worst, abs(e1 - exp1[1]) / (1 + abs(exp1[1])), abs(e2 - exp2[1]) / (1 + abs(exp2[1])))
    assert worst < 1e-12, worst


def test_inverse_hyperbolics_match_the_closed_form(build):
    rows, lines = _run(build)
    per_point = 6
    for index, (y, x, dy1, dy2, dx1, dx2) in enumerate(rows):
        block = {ln[0]: [float(v) for v in ln[1:]] for ln in lines[index * per_point:(index + 1) * per_point]}
        v, e1, e2 = block["ASINH"]
        assert v == pytest.approx(math.asinh(y), rel=1e-13, abs=1e-15)
        assert e1 == pytest.approx(dy1 / math.sqrt(y * y + 1.0), rel=1e-11, abs=1e-14)
        a = 1.5 + abs(y)
        v, e1, e2 = block["ACOSH"]
        assert v == pytest.approx(math.acosh(a), rel=1e-13)
        assert e2 == pytest.approx(dy2 / math.sqrt(a * a - 1.0), rel=1e-11)
        t = 0.9 * math.sin(y)
        v, e1, e2 = block["ATANH"]
        assert v == pytest.approx(math.atanh(t), rel=1e-12, abs=1e-15)
        assert e1 == pytest.approx(dy1 / (1.0 - t * t), rel=1e-10)


def test_canary_a_flipped_cross_term_is_caught_by_the_same_comparison(build):
    rows, lines = _run(build)
    y, x, dy1, dy2, dx1, dx2 = rows[0]
    got = [float(v) for v in lines[0][1:]][1]
    wrong = (x * dy1 + y * dx1) / (x * x + y * y)
    assert got != pytest.approx(wrong, rel=1e-6)


def test_the_generics_are_absent_unless_asked_for():
    plain = _emit_intrinsic_extensions("otim2n1", "ONUMM2N1")
    assert "ATAN2" not in plain and "oti_asinh" not in plain
    asked = _emit_intrinsic_extensions("otim2n1", "ONUMM2N1", atan2=True, inverse_hyperbolic=("ASINH",))
    assert "oti_atan2_tt" in asked and "oti_asinh" in asked and "oti_acosh" not in asked


from pathlib import Path  # noqa: E402

from _b20_support import transform_text, failed_checks  # noqa: E402

CP = Path(__file__).resolve().parents[2] / "discovery_cache" / "gitlab.com__ntnu-physmet__crystal-plasticity"


@pytest.mark.skipif(not (CP / "umatCP.for").is_file(), reason="needs the discovery cache")
@pytest.mark.parametrize("name", ["umatCP.for", "Rate Dependent Model/umatCP_RD2.for"])
def test_the_crystal_plasticity_umats_are_no_longer_refused_for_atan2(tmp_path, name):
    report = transform_text(tmp_path, (CP / name).read_text(errors="replace"), ".for")
    assert report["transform_success"], failed_checks(report)
    emitted = (tmp_path / "out" / "oti_intrinsics.f90").read_text()
    assert "oti_atan2_tt" in emitted


def test_a_mention_in_a_comment_does_not_add_a_generic():
    """CereusForbesiiSpiralis mentions ASINH only in commented-out lines (and calls it on reals)."""
    from umat_oti.transform.source_transform import _calls_on_oti_values, _without_comments

    fixed = ("      X = 1.D0\n"
             "!      Y_OTI = ASINH(Z_OTI)\n"
             "C      W_OTI = ASINH(Z_OTI)\n"
             "      V = ASINH(Q)   ! was ASINH(Z_OTI)\n")
    assert not _calls_on_oti_values("ASINH", _without_comments(fixed, True))
    assert _calls_on_oti_values("ASINH", _without_comments(fixed + "      Y_OTI = ASINH(Z_OTI)\n", True))
