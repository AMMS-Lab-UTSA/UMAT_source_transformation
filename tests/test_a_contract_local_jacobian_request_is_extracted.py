"""A local-Jacobian request in a contract is honoured, and its value is right.

A contract's ``constitutive_jacobians`` entry names a local Newton solve inside
the UMAT: the iterate to seed, the residual to differentiate, the line after
which the residual is known, and the hand-coded Jacobian it replaces. These
tests transform the bundled Kocks-type viscoplastic UMAT
(``parameter_sensitivity/models/m5_cpflow/umat.for``, Example 5 part A) from
such a contract, compile and run the result, and check the Jacobian the
transformed UMAT extracted and used against centred finite differences of the
residual of the separately compiled, untransformed source.

The value is read through the recording probe of
:mod:`umat_oti.transform.local_jacobian_probe`, which copies the iterate, the
residual and the Jacobian the Newton update is about to use into spare state
slots. In the transformed build that Jacobian is the one the contract put
there; in the original build it is the hand-coded one. The finite-difference
reference evaluates the untransformed residual at the recorded iterate, with the
same probe in its seeding mode, exactly as ``verify_internal_jacobian`` does.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.transform.internal_jacobian import discover_local_solves
from umat_oti.transform.local_jacobian_probe import (
    inject_local_solve_probe, plan_probe_slots)
from umat_oti.validation.parameter_sensitivity_validation import (
    build_original_driver, centered_fd, driver_source, replay)

pytestmark = [
    pytest.mark.fortran,
    pytest.mark.skipif(shutil.which("gfortran") is None,
                       reason="gfortran is not on PATH; the transformed UMAT is compiled and run"),
]

REPO_ROOT = Path(__file__).resolve().parents[1]
M5_UMAT = REPO_ROOT / "parameter_sensitivity" / "models" / "m5_cpflow" / "umat.for"
#: (E, nu, TAU0, DG, p, q, GAM0, H), the constants of Example 5 part A.
PROPS = [200000.0, 0.3, 1500.0, 25.0, 0.4, 1.6, 0.1, 60000.0]
PATH = [[1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0]] * 20
NTENS = 6
TOLERANCE = 1.0e-8
HAND_CODED_LINE = "DF=ONE-DTIME*DGDOT"


def _line_of(lines: list[str], statement: str) -> int:
    """The 1-based line holding ``statement``, blanks ignored; exactly one."""
    hits = [number for number, line in enumerate(lines, start=1)
            if line.strip().replace(" ", "").upper() == statement]
    assert len(hits) == 1, (statement, hits)
    return hits[0]


def _run_contract(tmp_path: Path, source_text: str, jacobian_statement: str,
                  *, promote: tuple[str, ...] = ("STRESS",)) -> dict:
    """Transform, compile and run ``source_text`` from a local-Jacobian contract."""
    solve = discover_local_solves(source_text)[0]
    assert (solve.iterate, solve.residual, solve.jacobian) == ("DEQPL", "F", "DF")
    slots = plan_probe_slots(nstatv=1, nprops=len(PROPS))
    observed = inject_local_solve_probe(source_text, solve, slots,
                                        target_increment=1, override_iterate=False)
    model = tmp_path / "m5_observed.for"
    model.write_text(observed.source, encoding="utf-8")
    lines = observed.source.splitlines()

    contract = {
        "name": "m5_local_jacobian",
        "source": model.name,
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        # The request's seed, residual and replaced variable are promoted by
        # the transform itself; the contract does not have to list them.
        "promote": list(promote),
        "replace": [],
        "ntens": NTENS,
        "order": 1,
        "constitutive_jacobians": [{
            "id": "newton_slope",
            "description": "dF/dDEQPL of the local Newton residual",
            "seed": solve.iterate,
            "output": solve.residual,
            "loop": {"top": _line_of(lines, "DOKNEWT=1,60")},
            "extract_after": _line_of(lines, "F=DEQPL-DTIME*GDOT"),
            "replace_variable": solve.jacobian,
            "replace_lines": [_line_of(lines, jacobian_statement)],
        }],
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

    out = tmp_path / "oti"
    summary, code = run_transformation(
        contract_path, out, TransformationOptions(compile_generated=True))
    assert code == 0, summary
    assert summary["transform_success"] and not summary["blockers"], summary
    assert summary["compilation"]["status"] == "compiled", summary["compilation"]

    # Link the transformed UMAT and its OTI modules into a material-point driver.
    objects = []
    for unit in (out / "compile_order.txt").read_text().split():
        stem = Path(unit).stem
        candidate = out / f"{stem}.o"
        objects.append(str(candidate if candidate.exists() else out / "transformed_umat.o"))
    driver = out / "driver.f90"
    driver.write_text(driver_source(ntens=NTENS, nstatv=slots.nstatv, nprops=slots.nprops),
                      encoding="utf-8")
    executable = out / "oti_driver"
    linked = subprocess.run(["gfortran", "-ffree-line-length-none", str(driver),
                             *objects, "-o", str(executable)],
                            cwd=out, capture_output=True, text=True)
    assert linked.returncode == 0, linked.stderr
    transformed = replay(executable, PROPS + [0.0], PATH, ntens=NTENS, nstatv=slots.nstatv)

    original_exe = build_original_driver(model, tmp_path / "original", ntens=NTENS,
                                         nstatv=slots.nstatv, nprops=slots.nprops)
    original = replay(original_exe, PROPS + [0.0], PATH, ntens=NTENS, nstatv=slots.nstatv)

    increment = len(PATH)
    iterate = transformed.statev[increment - 1][slots.iterate - 1]
    seeded = inject_local_solve_probe(source_text, solve, slots,
                                      target_increment=increment, override_iterate=True)
    seeded_path = tmp_path / "m5_seeded.for"
    seeded_path.write_text(seeded.source, encoding="utf-8")
    seeded_exe = build_original_driver(seeded_path, tmp_path / "seeded", ntens=NTENS,
                                       nstatv=slots.nstatv, nprops=slots.nprops)
    reference = centered_fd(seeded_exe, PROPS + [iterate], PATH, ntens=NTENS,
                            nstatv=slots.nstatv, props_indices=[slots.seed_props])
    return {
        "summary": summary,
        "report": json.loads(Path(summary["report_path"]).read_text()),
        "transformed_source": Path(summary["transformed_source"]).read_text(),
        "slots": slots,
        "transformed": transformed,
        "original": original,
        "oti": transformed.statev[increment - 1][slots.jacobian - 1],
        "hand_coded": original.statev[increment - 1][slots.jacobian - 1],
        "finite_difference":
            reference[slots.seed_props]["dstatev"][increment - 1][slots.residual - 1],
    }


def _relative(value: float, reference: float) -> float:
    return abs(value - reference) / abs(reference)


def test_the_contract_request_is_transformed_extracted_and_matches_finite_differences(tmp_path):
    source = M5_UMAT.read_text(encoding="utf-8")
    run = _run_contract(tmp_path, source, HAND_CODED_LINE)

    # The request is read as a local Jacobian, beside the material tangent.
    requests = {(r["kind"], tuple(r["seed"]), r["response"])
                for r in run["summary"]["derivative_requests"]}
    assert ("local_jacobian", ("DEQPL",), "F") in requests
    assert ("material_tangent", ("DSTRAN",), "STRESS") in requests
    # It takes the first direction after the NTENS tangent directions.
    slots = run["report"]["directions_required"]["slot_assignments"]
    assert slots == [{"id": "newton_slope", "seed_variable": "DEQPL", "directions": 1,
                      "slot_start": NTENS + 1, "slot_end": NTENS + 1}]
    # The loop reseeds the iterate, the residual's derivative becomes the
    # Jacobian, and the hand-coded Jacobian is switched off.
    text = run["transformed_source"]
    assert f"DEQPL_OTI = REAL(DEQPL_OTI) + OTI_E{NTENS + 1}" in text
    assert f"DF_OTI = GETIM(F_OTI, {NTENS + 1})" in text
    assert f"OTIS-SKIP: {HAND_CODED_LINE}" in text
    assert "DEQPL_OTI=DEQPL_OTI-F_OTI/DF_OTI" in text

    # The extracted Jacobian is the derivative of the residual.
    assert run["oti"] != 0.0
    assert _relative(run["oti"], run["finite_difference"]) < TOLERANCE, run
    # Every increment ran its Newton loop, and the transformed build computes
    # the same stress as the original.
    assert all(row[run["slots"].counter - 1] == 60.0 for row in run["transformed"].statev)
    worst = max(abs(a - b) / max(abs(b), 1.0)
                for got, want in zip(run["transformed"].stress, run["original"].stress)
                for a, b in zip(got, want))
    assert worst < 1.0e-12


def test_the_contract_request_replaces_a_wrong_hand_coded_jacobian(tmp_path):
    """The value used is the extracted one, not whatever the source computed.

    In the published source the hand-coded ``DF`` is right, so agreement with
    finite differences cannot tell the two apart. Here the source's own ``DF``
    is replaced by the constant 1 -- still a convergent iteration, with the
    wrong slope -- and the contract's extraction must supply the right one.
    """
    source = M5_UMAT.read_text(encoding="utf-8")
    assert source.count(HAND_CODED_LINE) == 1
    wrong = source.replace(HAND_CODED_LINE, "DF=ONE")
    # Listing the replaced variable in ``promote`` as well is accepted; the
    # next test shows the same result without it.
    run = _run_contract(tmp_path, wrong, "DF=ONE", promote=("STRESS", "DF"))

    assert run["hand_coded"] == 1.0
    assert _relative(run["hand_coded"], run["finite_difference"]) > 0.1
    assert _relative(run["oti"], run["finite_difference"]) < TOLERANCE, run


def test_the_replaced_jacobian_need_not_be_listed_in_promote(tmp_path):
    """The variable a request replaces is promoted by the request itself.

    ``DF=ONE`` depends on nothing seeded, so only the request can make ``DF``
    differentiated. When the transform promoted just the request's seed and
    residual, the extracted slope went into an undeclared, implicitly REAL
    ``DF_OTI``, the hand-coded line was switched off, and the Newton update
    divided by a ``DF`` that nothing assigned, while the transform and the
    compile both reported success.
    """
    source = M5_UMAT.read_text(encoding="utf-8")
    wrong = source.replace(HAND_CODED_LINE, "DF=ONE")
    run = _run_contract(tmp_path, wrong, "DF=ONE", promote=("STRESS",))

    contract = json.loads((tmp_path / "contract.json").read_text(encoding="utf-8"))
    assert "DF" not in contract["promote"]
    assert "DF" in run["report"]["promoted_variables"]
    text = run["transformed_source"]
    # The extraction target is declared as the differentiated type, and the
    # Newton update divides by it rather than by the switched-off REAL DF.
    assert re.search(rf"TYPE\(ONUMM{NTENS + 1}N1\)\s*::\s*DF_OTI\s*$", text, re.MULTILINE)
    assert f"DF_OTI = GETIM(F_OTI, {NTENS + 1})" in text
    assert "DEQPL_OTI=DEQPL_OTI-F_OTI/DF_OTI" in text
    assert not re.search(r"(?<![\w%])DF(?![\w(])", _active_text(text))

    # The value the update used is the derivative of the untransformed
    # residual, not the hand-coded constant.
    assert run["hand_coded"] == 1.0
    assert _relative(run["hand_coded"], run["finite_difference"]) > 0.1
    assert _relative(run["oti"], run["finite_difference"]) < TOLERANCE, run
    # And the solve that used it reaches the root the original build reaches.
    worst = max(abs(a - b) / max(abs(b), 1.0)
                for got, want in zip(run["transformed"].stress, run["original"].stress)
                for a, b in zip(got, want))
    assert worst < 1.0e-12


def _active_text(source: str) -> str:
    """The source without its comment lines (fixed form: C, c, * or ! in column 1)."""
    return "\n".join(line for line in source.splitlines()
                     if line[:1] not in {"C", "c", "*", "!"} and not line.lstrip().startswith("!"))
