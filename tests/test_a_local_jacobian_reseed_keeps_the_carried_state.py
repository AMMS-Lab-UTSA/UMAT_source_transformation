"""A local-Jacobian request differentiates the residual at fixed carried state.

The per-pass reseed of a ``constitutive_jacobians`` request used to write the
iterate as ``X_OTI = REAL(X_OTI) + E_k``. That cleared every direction of the
iterate, the strain directions included, and left the extra direction k in
the state carried from one pass to the next. UVCplanestress's local Newton
updates ep_eq from the iterate after the Newton step, so on the second pass:

* J_int was the derivative of nothing the pass evaluates (1.5 % off the
  centred difference at the same state);
* DDSDDE of the J_int build was wrong by up to 20 % (relative), because the
  strain sensitivities carried through the loop were destroyed.

The reseed now sets only the extra direction: 1 in the iterate, 0 in every
name the loop body may carry across its back edge. These tests transform
UVCplanestress with a J_int request on its Newton loop (c2) and without one
(c1), run both along a path that yields, and check that

* J_int at the second pass of a plastic increment equals the centred
  difference of the residual of the separately compiled original, evaluated at
  the c2 build's own iterate and ep_eq (ep_eq held fixed), and
* c2's DDSDDE equals c1's on every increment.

Source probes (state slots 11-14 and PROPS(12)) record the values; the
upstream file itself stays byte-identical.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.transform.abaqus_utility_definitions import ROTSIG_DEFINITION
from umat_oti.validation.parameter_sensitivity_validation import (
    build_original_driver, driver_source, replay)

pytestmark = [
    pytest.mark.fortran, pytest.mark.regression,
    pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required"),
]

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "UMATs" / "UMATs" / "UVC_MatMod" / "UVCplanestress.for"
PROPS = [179800.0, 0.3, 318.5, 100.7, 8.0, 0.0, 200.0, 11608.2, 145.2, 1026.3, 4.7]
PATH = [[4.0e-4, 0.0, 0.0]] * 10
KINC, PASS = 8, 2
NSTATV = 14


def _literal(value: float) -> str:
    text = repr(float(value))
    return (text if "e" in text else text + "e0").replace("e", "D")


def _probed_source(path: Path, override: tuple[float, float] | None = None) -> Path:
    """UVCplanestress with the probes; ``override`` prescribes the pass's iterate and ep_eq."""
    lines = SOURCE.read_text().splitlines()
    denom_end = next(n for n, line in enumerate(lines, 1)
                     if line.strip().startswith("3  - SQRT23*TWO/THREE * hard_iso_total"))
    out = []
    for number, line in enumerate(lines, 1):
        out.append(line)
        if line.strip() == "it_num = it_num + 1":
            out += [f"        IF (KINC .EQ. {KINC} .AND. it_num .EQ. {PASS}) THEN",
                    "          STATEV(13) = consist_param", "          STATEV(14) = ep_eq"]
            if override:
                out += [f"          consist_param = {_literal(override[0])}",
                        f"          ep_eq = {_literal(override[1])}"]
            out += ["          consist_param = consist_param + PROPS(12)", "        END IF"]
        if number == denom_end:
            out += [f"        IF (KINC .EQ. {KINC} .AND. it_num .EQ. {PASS}) THEN",
                    "          STATEV(11) = denom", "          STATEV(12) = yield_condition",
                    "        END IF"]
    path.write_text("\n".join(out) + "\n")
    return path


def _line(lines: list[str], start: str, after: int = 0) -> int:
    return next(n for n, line in enumerate(lines, 1) if n > after and line.strip().startswith(start))


def _build_and_run(work: Path, source: Path, name: str, jint: bool):
    lines = source.read_text().splitlines()
    top = _line(lines, "DO WHILE")
    contract = {"name": name, "source": str(source), "ntens": 3, "order": 1,
                "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
                "promote": ["STRESS"], "replace": []}
    if jint:
        denom = _line(lines, "denom = DOT_PRODUCT", after=top)
        contract["constitutive_jacobians"] = [{
            "id": "uvc_newton", "description": "d yield_condition / d consist_param",
            "seed": "CONSIST_PARAM", "output": "YIELD_CONDITION", "loop": {"top": top},
            "extract_after": _line(lines, "yield_condition = ONE/TWO*f_bar_2", after=top),
            "replace_variable": "DENOM", "replace_lines": [denom, denom + 1, denom + 2, denom + 3]}]
    path = work / f"{name}.json"
    path.write_text(json.dumps(contract))
    out = work / name
    summary, code = run_transformation(path, out, TransformationOptions(compile_generated=True))
    assert code == 0 and summary["compilation"]["status"] == "compiled", \
        (summary.get("blockers"), (summary["compilation"].get("stderr") or "")[:2000])
    objects = []
    for unit in (out / "compile_order.txt").read_text().split():
        candidate = out / f"{Path(unit).stem}.o"
        objects.append(str(candidate if candidate.exists() else out / "transformed_umat.o"))
    tangents = out / "ddsdde.txt"
    text = driver_source(ntens=3, nstatv=NSTATV, nprops=12)
    text = text.replace("  READ(*,*) NINC", "  READ(*,*) NINC\n"
                        f"  OPEN(77,FILE='{tangents}',STATUS='REPLACE')")
    text = text.replace("STRESS,STATEV\n", "STRESS,STATEV\n    WRITE(77,'(9(ES26.17E3,1X))') DDSDDE\n", 1)
    driver = out / "driver.f90"
    driver.write_text(text)
    executable = out / "driver"
    linked = subprocess.run(["gfortran", "-ffree-line-length-none", str(driver), *objects,
                             "-o", str(executable)], cwd=out, capture_output=True, text=True)
    assert linked.returncode == 0, linked.stderr[-2000:]
    run = replay(executable, PROPS + [0.0], PATH, ntens=3, nstatv=NSTATV)
    ddsdde = [[float(v) for v in line.split()] for line in tangents.read_text().splitlines()]
    return run, ddsdde


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    work = tmp_path_factory.mktemp("jint")
    probed = _probed_source(work / "uvc_probe.for")
    c1 = _build_and_run(work, probed, "c1", jint=False)
    c2 = _build_and_run(work, probed, "c2", jint=True)
    return work, c1, c2


def test_the_reseed_touches_only_the_extra_direction(builds):
    work, _c1, _c2 = builds
    text = (work / "c2" / "uvc_probe_oti.for").read_text().upper()
    assert "CONSIST_PARAM_OTI%E4 = 1.0D0" in text
    assert "EP_EQ_OTI%E4 = 0.0D0" in text
    assert "= REAL(CONSIST_PARAM_OTI) + OTI_E4" not in text


def test_j_int_is_the_residual_derivative_at_fixed_carried_state(builds):
    work, _c1, (c2, _tangents) = builds
    j_int = c2.statev[KINC - 1][10]
    state = (c2.statev[KINC - 1][12], c2.statev[KINC - 1][13])
    assert c2.statev[KINC - 1][0] > 0.0          # the increment yields
    rotsig = work / "rotsig.for"
    rotsig.write_text(ROTSIG_DEFINITION)
    reference = _probed_source(work / "uvc_fd.for", override=state)
    executable = build_original_driver(reference, work / "fd", ntens=3, nstatv=NSTATV,
                                       nprops=12, extra_sources=[rotsig])
    step = 1.0e-6 * abs(state[0])
    plus = replay(executable, PROPS + [step], PATH, ntens=3, nstatv=NSTATV).statev[KINC - 1][11]
    minus = replay(executable, PROPS + [-step], PATH, ntens=3, nstatv=NSTATV).statev[KINC - 1][11]
    fd = (plus - minus) / (2.0 * step)
    assert abs(j_int - fd) <= 1.0e-7 * abs(fd), (j_int, fd)


def test_the_j_int_build_tangent_equals_the_tangent_only_build(builds):
    _work, (_c1, ddsdde1), (_c2, ddsdde2) = builds
    assert len(ddsdde1) == len(ddsdde2) == len(PATH)
    for one, two in zip(ddsdde1, ddsdde2):
        scale = max(abs(v) for v in one)
        assert max(abs(a - b) for a, b in zip(one, two)) <= 1.0e-10 * scale
