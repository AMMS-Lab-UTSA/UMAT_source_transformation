"""A local-Jacobian request with a vector seed returns the analytic Jacobian exactly.

The fixture (tests/fixtures/local_jacobian_vector/vec.for) solves a two-unknown
residual R(X) by Newton iteration, with an auxiliary Q updated from X after
each step, and records X and the extracted Jacobian at the second pass of the
third increment. Its Jacobian is known in closed form:

    dR1/dX1 = 1 + 0.3 X1**2 + 0.2 X2,  dR1/dX2 = 0.2 X1,
    dR2/dX1 = 0.6 X1,                  dR2/dX2 = 1 + 0.3 X2**2.

The per-pass reseed used to set only each component's own direction, so X(1)
kept the value of X(2)'s direction that the previous pass had propagated into
it, and dR2/dX1 came out 16 % off. Every extra direction of every seeded
component is now cleared before its own is set to 1. The extracted Jacobian
must equal the closed form exactly, and the request must leave DDSDDE as the
tangent-only build computes it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.validation.parameter_sensitivity_validation import driver_source, replay

pytestmark = [
    pytest.mark.fortran, pytest.mark.regression,
    pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required"),
]

SOURCE = Path(__file__).resolve().parent / "fixtures" / "local_jacobian_vector" / "vec.for"
PROPS = [100.0]
PATH = [[0.01, 0.02, 0.0]] * 5


def _build(work: Path, name: str, jint: bool):
    lines = SOURCE.read_text().splitlines()

    def line(start: str) -> int:
        return next(n for n, text in enumerate(lines, 1) if text.strip().startswith(start))

    contract = {"name": name, "source": str(SOURCE), "ntens": 3, "order": 1,
                "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
                "promote": ["STRESS"], "replace": []}
    if jint:
        contract["constitutive_jacobians"] = [{
            "id": "vec", "seed": "X", "seed_shape": "vector", "seed_directions": 2,
            "output": "R", "output_shape": "vector", "loop": {"top": line("DO IT")},
            "additional_extractions": [{
                "target_variable": "XJ", "from_output_variable": "R", "after_line": line("R(2) ="),
                "extract_kind": "component_map",
                "components": [{"target_indices": [i, j], "output_indices": [i],
                                "seed_direction_offset": j - 1} for i in (1, 2) for j in (1, 2)]}]}]
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
    text = driver_source(ntens=3, nstatv=10, nprops=1)
    text = text.replace("  READ(*,*) NINC", f"  READ(*,*) NINC\n  OPEN(77,FILE='{tangents}',STATUS='REPLACE')")
    text = text.replace("STRESS,STATEV\n", "STRESS,STATEV\n    WRITE(77,'(9(ES26.17E3,1X))') DDSDDE\n", 1)
    (out / "driver.f90").write_text(text)
    linked = subprocess.run(["gfortran", "-ffree-line-length-none", str(out / "driver.f90"), *objects,
                             "-o", str(out / "driver")], cwd=out, capture_output=True, text=True)
    assert linked.returncode == 0, linked.stderr[-2000:]
    run = replay(out / "driver", PROPS, PATH, ntens=3, nstatv=10)
    ddsdde = [[float(v) for v in row.split()] for row in tangents.read_text().splitlines()]
    return run, ddsdde, out


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    work = tmp_path_factory.mktemp("vector_jint")
    return _build(work, "c1", False), _build(work, "c2", True)


def test_every_extra_direction_of_every_component_is_reset(builds):
    _c1, (_run, _dd, out) = builds
    text = (out / "vec_oti.for").read_text().upper()
    for component, own, other in ((1, "E4", "E5"), (2, "E5", "E4")):
        assert f"X_OTI({component})%{other} = 0.0D0" in text
        assert f"X_OTI({component})%{own} = 1.0D0" in text


def test_the_vector_jacobian_equals_the_closed_form(builds):
    _c1, (run, _dd, _out) = builds
    state = run.statev[2]
    x1, x2 = state[4], state[5]
    expected = [[1 + 0.3 * x1 ** 2 + 0.2 * x2, 0.2 * x1], [0.6 * x1, 1 + 0.3 * x2 ** 2]]
    extracted = [[state[0], state[2]], [state[1], state[3]]]
    for row, want in zip(extracted, expected):
        assert row == pytest.approx(want, rel=1e-14, abs=1e-14)


def test_the_request_leaves_ddsdde_as_the_tangent_only_build(builds):
    (_r1, ddsdde1, _o1), (_r2, ddsdde2, _o2) = builds
    assert ddsdde1 == ddsdde2
