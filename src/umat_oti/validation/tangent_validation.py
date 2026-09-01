"""Verify the consistent tangent an OTI build returns, for an arbitrary source.

DDSDDE was the one derivative family nothing checked numerically. The Abaqus
paired runs compare it between two builds that carry the same tangent, and the
higher-order study starts at order two, so a tangent that both builds got wrong
in the same way would have passed everything we had.

The check here is a real one because the two sides share no code path. The
value under test comes from a transformation seeded on the strain increment, so
the tangent is the first-order OTI coefficient of the stress. The reference
comes from the *original* untransformed source, compiled on its own and
replayed with a perturbed strain increment -- ordinary real arithmetic.

A centred difference does not determine a derivative equally well at every step,
so each entry is swept over a ladder and adjudicated by how tightly the method
pins the value down, the same discipline the parameter-sensitivity and
higher-order studies use. Where the ladder cannot decide, the entry is reported
as unresolved rather than counted as agreement.

**Which input is driven is read off the transformed file, not guessed.** A
source that receives the strain increment is driven and perturbed through
DSTRAN. A source whose kinematic input is the deformation gradient is driven
and perturbed through DFGRD1, by exactly the map the transform seeded it with
-- the six strain directions added to the diagonal of F and half of each to
both members of an off-diagonal pair. The map is read back out of the emitted
seed lines by :func:`umat_oti.transform.source_transform.seeded_kinematics`,
so the reference differentiates with respect to the same perturbation the OTI
side carries rather than a second transcription of it. A source that reads
both inputs is perturbed in both, because that is what the transform seeds.

What a verified finite-strain row therefore establishes is
``d(STRESS)/d(that perturbation of F)``, which is what the transform claims to
compute -- and no more. It is not, in general, the DDSDDE Abaqus asks a
finite-strain UMAT for: Abaqus's tangent is taken with respect to a strain
increment whose effect on the deformation gradient is ``dF = de . F``, and the
map used here is ``dF = de``. The two coincide at ``F = I`` and differ by the
push-forward everywhere else. This module compares the transform against the
derivative it is computing; it does not certify the constitutive convention.

A driver that leaves the model undeformed makes every entry zero on both sides
and every comparison vacuous, so the reference is required to be non-trivial --
to resolve at least one entry above the noise floor of its own construction --
before any entry is counted.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from umat_oti.validation.reference_resolution import ResolutionLadder

__all__ = ["TangentCase", "TangentResult", "STAGE_ORDER",
           "DEFAULT_STRAIN_LADDER", "verify_tangent", "read_tangent_csv"]

#: Step sizes relative to the size of the strain increment being perturbed.
#: Spans truncation-dominated at the top to cancellation-dominated at the
#: bottom, so the ladder shows its own turning point rather than assuming one.
DEFAULT_STRAIN_LADDER = (1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6)

#: Gates in order. A case that fails one cannot contribute verified entries.
STAGE_ORDER = (
    "contract_constructed",
    "transformed",
    "kinematic_seed_identified",
    "generated_compiled",
    "original_compiled",
    "transformed_executed",
    "original_executed",
    "primal_parity",
    "tangent_emitted",
    "reference_resolved",
    "reference_nontrivial",
    "tangent_verified",
)

#: Relative agreement demanded where the reference resolves an entry.
DEFAULT_RELATIVE_TOLERANCE = 1.0e-6

#: Below this fraction of the largest entry of the same tangent, an entry is
#: not a small number, it is a zero of the matrix. Without a scale the zero
#: test has nothing to compare against and rounding dust reads as a total
#: disagreement.
ZERO_FRACTION = 1.0e-12

_BUILD_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class TangentCase:
    """One source whose returned tangent is to be checked."""

    name: str
    source_path: Path
    props: tuple[float, ...]
    dstran_per_increment: tuple[float, ...]
    n_increments: int
    ntens: int
    nstatv: int
    ndi: int = 3
    nshr: int = 3
    entry: str = "UMAT"
    parameters: tuple[tuple[str, int], ...] = ()
    state_names: tuple[str, ...] = ()
    ladder: tuple[float, ...] = DEFAULT_STRAIN_LADDER
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE
    extra_sources: tuple[Path, ...] = ()
    link_libraries: tuple[str, ...] = ()


@dataclass
class TangentResult:
    """What happened, gate by gate, plus every adjudicated entry."""

    name: str
    stages: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    furthest_stage: Optional[str] = None
    blocker: Optional[str] = None

    def passed(self, stage: str, **detail) -> None:
        self.stages[stage] = {"status": "succeeded", **detail}
        self.furthest_stage = stage

    def stopped(self, stage: str, reason: str, **detail) -> None:
        self.stages[stage] = {"status": "failed", "reason": reason, **detail}
        self.blocker = reason

    def as_dict(self) -> dict:
        return {"name": self.name, "stages": self.stages, "rows": self.rows,
                "summary": self.summary, "furthest_stage": self.furthest_stage,
                "blocker": self.blocker}


def read_tangent_csv(path: Path) -> dict[tuple[int, int, int], float]:
    """Read a tangent file, keyed (increment, row, column)."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return {(int(r["increment"]), int(r["row"]), int(r["column"])):
                float(r["value"]) for r in csv.DictReader(handle)}


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _contract(case: TangentCase, source: Path) -> dict:
    """A strain-seeded, order-one derivative request for this source.

    Seeding DSTRAN is what makes the returned DDSDDE an OTI result rather than
    whatever the source hand-coded: the transformation fills the tangent from
    the first-order coefficient of the stress.
    """
    parameters = case.parameters or tuple(
        (f"P{i}", i) for i in range(1, len(case.props) + 1))
    names = case.state_names or tuple(
        f"SDV{i}" for i in range(1, case.nstatv + 1))
    return {
        "schema_version": "1.1",
        "name": f"{case.name}_tangent",
        "source": str(source),
        "entry_routine": case.entry,
        "ntens": case.ntens,
        "parameters": [{"name": name, "props_index": index,
                        "value": float(case.props[index - 1])}
                       for name, index in parameters],
        "state_variables": [{"name": name, "statev_index": index}
                            for index, name in enumerate(names, start=1)],
        "derivatives": [{"id": "consistent_tangent", "target": "DDSDDE",
                         "seed": "DSTRAN", "response": "STRESS", "order": 1}],
    }


# --------------------------------------------------------------------------- #
# Which input this source is driven through
# --------------------------------------------------------------------------- #
def _kinematic_drive(transformed_source: Path):
    """What the transform seeded, read back out of the file it emitted.

    The decision of which driver a source gets is made here and nowhere else,
    and it is made from the source's own interface as the transform resolved
    it: a routine that receives the strain increment carries DSTRAN seed
    lines, one whose kinematic input is the deformation gradient carries
    DFGRD1 seed lines, one that reads both carries both. No name, no file
    list, and no second copy of the map.
    """
    from umat_oti.transform.source_transform import (  # noqa: PLC0415
        seeded_kinematics,
    )

    return seeded_kinematics(
        transformed_source.read_text(encoding="utf-8", errors="replace"))


def _gradient_increment(drive, strain_increment: Sequence[float]) -> list[list[float]]:
    """The 3x3 advance of F that carries ``strain_increment``, by the seeded map.

    The same map the seed uses, applied to the increment rather than to a
    direction. Driving the base path with it and perturbing a component of it
    with it are then the same operation at two magnitudes, which is what makes
    the reference a derivative of the quantity the OTI side differentiated.
    """
    matrix = [[0.0] * 3 for _ in range(3)]
    for direction, terms in drive.dfgrd1.items():
        if direction > len(strain_increment):
            continue
        amount = float(strain_increment[direction - 1])
        for row, column, coefficient in terms:
            matrix[row - 1][column - 1] += coefficient * amount
    return matrix


def _gradient_perturbation(drive, direction: int, step: float) -> list[float]:
    """One direction's DFGRD1 seed, at a finite size, row-major."""
    matrix = [[0.0] * 3 for _ in range(3)]
    for row, column, coefficient in drive.dfgrd1.get(direction, ()):
        matrix[row - 1][column - 1] += coefficient * step
    return [value for row in matrix for value in row]


def _flat(matrix: Sequence[Sequence[float]]) -> list[float]:
    return [float(value) for row in matrix for value in row]


def _driver_source(case: TangentCase, drive) -> str:
    """A driver that walks the path and writes the tangent each increment.

    When the transform seeded the deformation gradient, this advances DFGRD1
    by the seeded map of the same strain increment the path is written in, and
    hands DFGRD0 the value it held before. Holding DFGRD1 at the identity
    instead would leave a source that computes its stress from F undeformed
    for the whole run: its stress would never move, its tangent would be zero,
    and the comparison would be between two zeros.
    """
    from umat_oti.validation.actual_umat_higher_order_generic import (  # noqa: PLC0415
        _abaqus_utility_stubs,
    )

    props = "; ".join(f"PROPS({i})={value!r}_8"
                      for i, value in enumerate(case.props, start=1))
    path = ", ".join(f"{value!r}_8" for value in case.dstran_per_increment)
    statev_header = ",".join(f"statev_{i}" for i in range(1, case.nstatv + 1))
    stress_header = ",".join(f"stress_{i}" for i in range(1, case.ntens + 1))
    fields = case.ntens + case.nstatv
    gradient = _gradient_increment(drive, case.dstran_per_increment)
    if drive.drives_deformation_gradient:
        declare_gradient = "  REAL(8) :: DFGRDINC(3,3)\n"
        set_gradient = "  DFGRDINC=0.0_8\n" + "".join(
            f"  DFGRDINC({r + 1},{c + 1})={gradient[r][c]!r}_8\n"
            for r in range(3) for c in range(3) if gradient[r][c])
        advance_gradient = "    DFGRD0=DFGRD1\n    DFGRD1=DFGRD1+DFGRDINC\n"
    else:
        declare_gradient = set_gradient = advance_gradient = ""
    return f"""PROGRAM tangent_driver
  IMPLICIT NONE
  INTEGER, PARAMETER :: NTENS={case.ntens}, NSTATV={max(case.nstatv, 1)}
  INTEGER, PARAMETER :: NPROPS={len(case.props)}, NINC={case.n_increments}
  REAL(8) :: STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),SSE,SPD,SCD,RPL
  REAL(8) :: DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT,STRAN(NTENS),DSTRAN(NTENS)
  REAL(8) :: TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3)
  REAL(8) :: DROT(3,3),PNEWDT,CELENT,DFGRD0(3,3),DFGRD1(3,3),STEP(NTENS)
  INTEGER :: NDI,NSHR,NOEL,NPT,LAYER,KSPT,KSTEP,KINC,I,INC,U,UT,IR,IC
{declare_gradient}  CHARACTER(80) :: CMNAME
  DATA STEP / {path} /
  STRESS=0.0_8; STATEV=0.0_8; DDSDDE=0.0_8; STRAN=0.0_8; DSTRAN=0.0_8
  SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8; DDSDDT=0.0_8
  DRPLDE=0.0_8; DRPLDT=0.0_8; TIME=0.0_8; DTIME=1.0_8
  TEMP=293.15_8; DTEMP=0.0_8; PREDEF=0.0_8; DPRED=0.0_8
  PROPS=0.0_8; {props}
  COORDS=0.0_8; DROT=0.0_8; DFGRD0=0.0_8; DFGRD1=0.0_8
  DO I=1,3
    DROT(I,I)=1.0_8; DFGRD0(I,I)=1.0_8; DFGRD1(I,I)=1.0_8
  END DO
{set_gradient}  PNEWDT=1.0_8; CELENT=1.0_8; CMNAME='{case.name.upper()[:60]}'
  NDI={case.ndi}; NSHR={case.nshr}; NOEL=1; NPT=1; LAYER=1; KSPT=1; KSTEP=1
  OPEN(NEWUNIT=U,FILE='tangent_primal.csv',STATUS='REPLACE',ACTION='WRITE')
  WRITE(U,'(A)') 'increment,{stress_header},{statev_header}'
  OPEN(NEWUNIT=UT,FILE='tangent_DDSDDE_OTI.csv',STATUS='REPLACE',ACTION='WRITE')
  WRITE(UT,'(A)') 'increment,row,column,value'
  DO INC=1,NINC
    DSTRAN=STEP; KINC=INC
{advance_gradient}    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
      NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
      NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
    WRITE(U,'(I0,{fields}(",",ES24.16))') INC,STRESS,STATEV
    DO IR=1,NTENS
      DO IC=1,NTENS
        WRITE(UT,'(I0,",",I0,",",I0,",",ES24.16)') INC,IR,IC,DDSDDE(IR,IC)
      END DO
    END DO
    STRAN=STRAN+DSTRAN; TIME(1)=TIME(1)+DTIME; TIME(2)=TIME(2)+DTIME
  END DO
  CLOSE(U); CLOSE(UT)
END PROGRAM tangent_driver

{_abaqus_utility_stubs()}"""


def _run(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in command], cwd=str(cwd), check=False,
                          capture_output=True, text=True,
                          timeout=_BUILD_TIMEOUT_SECONDS)


def verify_tangent(case: TangentCase, work_dir: Path) -> TangentResult:
    """Build both sides, compare, and record every gate. Never raises for a failure."""
    from umat_oti.services.transformation import (  # noqa: PLC0415
        TransformationOptions, run_transformation,
    )
    from umat_oti.validation.parameter_sensitivity_validation import (  # noqa: PLC0415
        build_original_driver, replay,
    )

    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    result = TangentResult(name=case.name)
    source = Path(case.source_path).resolve()

    contract_path = work_dir / "tangent_contract.json"
    try:
        contract_path.write_text(
            json.dumps(_contract(case, source), indent=2) + "\n", encoding="utf-8")
    except (OSError, IndexError) as error:
        result.stopped("contract_constructed", f"{type(error).__name__}: {error}")
        return result
    result.passed("contract_constructed", contract=contract_path.name)

    build = work_dir / "oti"
    try:
        summary, code = run_transformation(
            contract_path, build, TransformationOptions(compile_generated=True))
    except Exception as error:  # noqa: BLE001 - a build failure is a result
        result.stopped("transformed", f"{type(error).__name__}: {error}"[:600])
        return result
    if code != 0:
        result.stopped("transformed",
                       str(summary.get("error") or summary)[:600])
        return result
    result.passed("transformed",
                  transformed_source=Path(summary["transformed_source"]).name)

    drive = _kinematic_drive(Path(summary["transformed_source"]))
    if not drive.directions():
        result.stopped(
            "kinematic_seed_identified",
            "the transformed build injects the OTI directions into no "
            "kinematic input, so there is nothing for a reference to perturb "
            "and no derivative to compare")
        return result
    result.passed(
        "kinematic_seed_identified",
        driven_through=_driven_through(drive),
        seeded_directions=list(drive.directions()),
        dfgrd1_seed_map={str(direction): [list(term) for term in terms]
                         for direction, terms in sorted(drive.dfgrd1.items())},
        dstran_seed_components=dict(sorted(drive.dstran.items())),
        map_provenance="read back from the seed lines the transform emitted")

    driver = build / "tangent_driver.f90"
    driver.write_text(_driver_source(case, drive), encoding="utf-8")
    objects = sorted(str(p) for p in build.glob("*.o"))
    if not objects:
        result.stopped("generated_compiled",
                       "the transformation produced no object files to link")
        return result
    executable = build / "tangent_driver"
    compiled = _run(["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none",
                     "-I", str(build), str(driver), *objects,
                     *case.link_libraries, "-o", str(executable)], build)
    if compiled.returncode != 0:
        result.stopped("generated_compiled",
                       f"driver link failed: {compiled.stderr[-800:]}")
        return result
    result.passed("generated_compiled")

    reference_dir = work_dir / "original"
    try:
        reference = build_original_driver(
            source, reference_dir, ntens=case.ntens, nstatv=case.nstatv,
            nprops=len(case.props), extra_sources=case.extra_sources,
            link_libraries=case.link_libraries,
            finite_strain=drive.drives_deformation_gradient)
    except RuntimeError as error:
        result.stopped("original_compiled", str(error)[:600])
        return result
    result.passed("original_compiled")

    executed = _run([str(executable)], build)
    if executed.returncode != 0:
        result.stopped("transformed_executed",
                       f"the OTI driver failed (rc={executed.returncode}): "
                       f"{executed.stderr[-600:]}")
        return result
    result.passed("transformed_executed")

    path = [list(case.dstran_per_increment) for _ in range(case.n_increments)]
    # The same advance of F the OTI driver applies, by the same map, so the two
    # builds walk one path and not two.
    gradient_path = (
        [_flat(_gradient_increment(drive, case.dstran_per_increment))
         for _ in range(case.n_increments)]
        if drive.drives_deformation_gradient else None)
    try:
        original = replay(reference, list(case.props), path,
                          ntens=case.ntens, nstatv=case.nstatv,
                          deformation_gradient_increment=gradient_path)
    except RuntimeError as error:
        result.stopped("original_executed", str(error)[:600])
        return result
    result.passed("original_executed", increments=original.increments)

    parity = _primal_parity(original, build / "tangent_primal.csv", case)
    if not parity["agrees"]:
        detail = dict(parity)
        result.stopped(
            "primal_parity",
            detail.pop("reason", None) or
            "the transformed and original builds disagree on stress "
            f"(worst relative difference {parity['worst_relative']:.3e}), so a "
            "tangent comparison would not be between comparable quantities",
            **detail)
        return result
    result.passed("primal_parity", **parity)

    tangent_path = build / "tangent_DDSDDE_OTI.csv"
    if not tangent_path.is_file():
        result.stopped("tangent_emitted", "the OTI driver wrote no tangent file")
        return result
    oti = read_tangent_csv(tangent_path)
    if not oti:
        result.stopped("tangent_emitted", "the tangent file is empty")
        return result
    result.passed("tangent_emitted", entries=len(oti))

    rows = _compare(case, reference, path, gradient_path, drive, oti, replay)
    result.rows = rows
    if not any(r["reference_classification"] == "resolved" for r in rows):
        result.stopped("reference_resolved",
                       "no entry was resolved by the reference at any step on "
                       "the ladder")
        result.summary = _summarise(rows, drive)
        return result
    result.passed("reference_resolved")

    nontrivial = _nontriviality(case, original, rows)
    if not nontrivial["nontrivial"]:
        result.stopped(
            "reference_nontrivial",
            "every entry of the reference tangent sits at or below the noise "
            f"floor of its own centred difference ({nontrivial['noise_floor']:.3e}), "
            "so the reference determines nothing: a driver that leaves the "
            "model undeformed makes every entry zero on both sides and every "
            "comparison vacuous",
            **nontrivial)
        result.summary = _summarise(rows, drive)
        return result
    result.passed("reference_nontrivial", **nontrivial)

    disagreeing = [r for r in rows if r["agrees"] is False]
    result.summary = _summarise(rows, drive)
    if disagreeing:
        result.stopped("tangent_verified",
                       f"{len(disagreeing)} of {len(rows)} entries disagree "
                       "with the independent reference")
    else:
        result.passed("tangent_verified")
    return result


def _primal_parity(original, primal_csv: Path, case: TangentCase) -> dict:
    """Do the two builds agree on stress before any derivative is compared?

    Agreement is not the only thing asked. A stress that is not a finite
    number fails every comparison silently -- NaN is neither greater than the
    tolerance nor less than it -- so two builds that both return NaN would
    pass a parity test written only as a difference, and the run would go on
    to difference NaN against NaN and report the result as a derivative. A
    response that is not a number is reported here, where it happened.
    """
    if not primal_csv.is_file():
        return {"agrees": False, "worst_relative": float("inf"),
                "reason": "the OTI driver wrote no primal file"}
    with primal_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    worst = 0.0
    not_a_number: Optional[tuple] = None
    for index, row in enumerate(rows):
        if index >= len(original.stress):
            break
        for component in range(1, case.ntens + 1):
            mine = float(row[f"stress_{component}"])
            theirs = original.stress[index][component - 1]
            if not (math.isfinite(mine) and math.isfinite(theirs)):
                if not_a_number is None:
                    not_a_number = (index + 1, component, mine, theirs)
                continue
            scale = max(abs(mine), abs(theirs))
            if scale:
                worst = max(worst, abs(mine - theirs) / scale)
    compared = min(len(rows), len(original.stress))
    if not_a_number is not None:
        increment, component, mine, theirs = not_a_number
        return {
            "agrees": False, "worst_relative": float("inf"),
            "increments_compared": compared,
            "reason": f"stress component {component} is not a finite number at "
                      f"increment {increment} ({mine} from the transformed "
                      f"build, {theirs} from the original), so neither build "
                      "produced a response a derivative could be taken of",
        }
    return {"agrees": worst <= 1.0e-9, "worst_relative": worst,
            "increments_compared": compared}


def _compare(case: TangentCase, reference: Path, path: list,
             gradient_path: Optional[list], drive, oti: dict,
             replay) -> list[dict]:
    """Sweep each column over the step ladder and adjudicate every entry."""
    rows: list[dict] = []
    for increment in range(1, case.n_increments + 1):
        ladders, scale = {}, 0.0
        for column in range(1, case.ntens + 1):
            ladder = _sweep(case, reference, path, gradient_path, drive,
                            increment, column, replay)
            ladders[column] = ladder
            for row_index in range(1, case.ntens + 1):
                estimate = ladder.best_estimate(1, row_index)
                if estimate is not None:
                    scale = max(scale, abs(estimate))
        for value in oti.values():
            scale = max(scale, abs(value))
        for row_index in range(1, case.ntens + 1):
            for column in range(1, case.ntens + 1):
                rows.append(_adjudicate(
                    ladders[column], increment, row_index, column,
                    oti.get((increment, row_index, column)),
                    case.relative_tolerance, scale))
    return rows


def _step_magnitude(increment_row: Sequence[float]) -> float:
    """The size a relative step on the ladder is relative to."""
    return max((abs(value) for value in increment_row), default=0.0) or 1.0e-4


def _sweep(case: TangentCase, reference: Path, path: list,
           gradient_path: Optional[list], drive, increment: int,
           column: int, replay) -> ResolutionLadder:
    """Central differences of every stress component w.r.t. one seed direction.

    The perturbation is whatever the transform injected direction ``column``
    into, at the same magnitude in each: the strain-increment component where
    DSTRAN was seeded, the deformation gradient by the seeded map where DFGRD1
    was, and both where the source reads both. A direction the transform
    injected nowhere perturbs nothing, and returns an empty ladder rather than
    a zero derivative -- there is no reference for it, so its entries are
    reported unresolved.
    """
    ladder = ResolutionLadder(props_index=column, array="DDSDDE", steps=())
    seeds_strain = column in set(drive.dstran.values())
    seeds_gradient = bool(drive.dfgrd1.get(column))
    if not (seeds_strain or seeds_gradient):
        return ladder
    base = path[increment - 1][column - 1] if seeds_strain else 0.0
    magnitude = _step_magnitude(path[increment - 1])
    steps, per_step = [], []
    for relative in case.ladder:
        step = relative * magnitude
        high_path = [list(row) for row in path]
        low_path = [list(row) for row in path]
        if seeds_strain:
            high_path[increment - 1][column - 1] = base + step
            low_path[increment - 1][column - 1] = base - step
        high_gradient = low_gradient = None
        if gradient_path is not None:
            high_gradient = [list(row) for row in gradient_path]
            low_gradient = [list(row) for row in gradient_path]
            if seeds_gradient:
                # One increment only. Spreading the perturbation over the whole
                # path would differentiate with respect to the history, not
                # with respect to the increment whose tangent is being checked.
                shift = _gradient_perturbation(drive, column, step)
                high_gradient[increment - 1] = [
                    value + delta for value, delta
                    in zip(high_gradient[increment - 1], shift)]
                low_gradient[increment - 1] = [
                    value - delta for value, delta
                    in zip(low_gradient[increment - 1], shift)]
        try:
            high = replay(reference, list(case.props), high_path,
                          ntens=case.ntens, nstatv=case.nstatv,
                          deformation_gradient_increment=high_gradient)
            low = replay(reference, list(case.props), low_path,
                         ntens=case.ntens, nstatv=case.nstatv,
                         deformation_gradient_increment=low_gradient)
        except RuntimeError:
            # A step the model cannot run contributes nothing. It must not
            # silently become a zero derivative.
            continue
        if len(high.stress) < increment or len(low.stress) < increment:
            continue
        steps.append(relative)
        per_step.append([
            (high.stress[increment - 1][i] - low.stress[increment - 1][i])
            / (2.0 * step) for i in range(case.ntens)])
    ladder.steps = tuple(steps)
    for row_index in range(1, case.ntens + 1):
        ladder.values[(1, row_index)] = tuple(
            table[row_index - 1] for table in per_step)
    return ladder


def _driven_through(drive) -> str:
    """How this source is driven, in the interface's own terms."""
    inputs = []
    if drive.drives_strain_increment:
        inputs.append("DSTRAN")
    if drive.drives_deformation_gradient:
        inputs.append("DFGRD1")
    return " and ".join(inputs)


def _nontriviality(case: TangentCase, original, rows: list[dict]) -> dict:
    """Did the reference resolve anything at all above its own round-off?

    A zero tangent is not an agreement. If the driver leaves the model
    undeformed -- a finite-strain source held at ``F = I``, a path of zero
    increments -- every entry is zero on both sides and every entry "agrees",
    including the ones that would have caught a wrong tangent. The reference
    has to be shown to carry signal before any of its verdicts are counted.

    The bar is the smallest derivative a centred difference of this response
    could resolve at the coarsest step on the ladder: the most generous noise
    floor the sweep could have had. A reference that cannot clear even that is
    round-off from end to end.
    """
    from umat_oti.validation.parameter_sensitivity_validation import (  # noqa: PLC0415
        fd_noise_floor,
    )

    response_scale = max(
        (abs(value) for row in original.stress for value in row), default=0.0)
    step = max(case.ladder, default=0.0) * _step_magnitude(
        case.dstran_per_increment)
    floor = fd_noise_floor(response_scale, step)
    largest = max((abs(row["reference"]) for row in rows
                   if row["reference"] is not None
                   and math.isfinite(row["reference"])), default=0.0)
    return {
        "nontrivial": largest > floor,
        "largest_reference_entry": largest,
        "noise_floor": floor,
        "response_scale": response_scale,
        "coarsest_step": step,
        "criterion": "the largest entry the reference resolved must exceed the "
                     "centred-difference noise floor of the response at the "
                     "coarsest step on the ladder",
    }


def _adjudicate(ladder: ResolutionLadder, increment: int, row_index: int,
                column: int, value: Optional[float], relative_tolerance: float,
                matrix_scale: float) -> dict[str, Any]:
    """Decide one entry: agrees, disagrees, or the reference cannot say."""
    floor = matrix_scale * ZERO_FRACTION
    estimate = ladder.best_estimate(1, row_index)
    resolution = ladder.resolution(1, row_index)
    envelope = ladder.envelope(1, row_index)
    row: dict[str, Any] = {
        "increment": increment, "row": row_index, "column": column,
        "oti": value, "reference": estimate,
        "reference_resolution": resolution,
        "reference_envelope": list(envelope) if envelope else None,
        "steps_admissible": len(ladder.steps),
        "relative_steps": ";".join(f"{s:g}" for s in ladder.steps) or None,
        "matrix_scale": matrix_scale,
        "structural_zero_floor": floor,
        "relative_tolerance": relative_tolerance,
    }
    if value is None:
        row.update({"reference_classification": "unresolved", "agrees": None,
                    "absolute_error": None, "relative_error": None,
                    "judged_by": None,
                    "justification": "the OTI build emitted no value here"})
        return row
    if estimate is None or resolution is None:
        row.update({"reference_classification": "unresolved", "agrees": None,
                    "absolute_error": None, "relative_error": None,
                    "judged_by": None,
                    "justification": "fewer than two admissible steps, so the "
                                     "centred difference does not determine "
                                     "this entry"})
        return row

    absolute = abs(value - estimate)
    denominator = max(abs(estimate), abs(value))
    row["absolute_error"] = absolute
    row["relative_error"] = absolute / denominator if denominator else 0.0
    row["reference_classification"] = "resolved"

    if abs(estimate) <= floor:
        # Whether an entry is a zero of the matrix is a property of the
        # reference, not of the value being checked -- deciding it from
        # max(|reference|,|value|) would let a large bogus value escape the
        # zero test simply by being large.
        row["judged_by"] = "structural_zero"
        row["agrees"] = abs(value) <= floor
        row["justification"] = (
            f"the reference places this entry below {floor:.3e}, which is "
            f"{ZERO_FRACTION:.0e} of the largest entry of the same tangent "
            f"({matrix_scale:.6e}), so it is a zero of the matrix")
        return row

    # The tolerance-free criterion first: if the reference's own answers over
    # its flattest window straddle the value, the reference cannot call it wrong.
    if ladder.brackets(1, row_index, value):
        row.update({"judged_by": "within_reference_resolution", "agrees": True,
                    "justification": "the reference's own answers straddle the "
                                     "value, so no tolerance is involved"})
        return row
    if absolute <= resolution:
        row.update({"judged_by": "within_reference_resolution", "agrees": True,
                    "justification":
                        f"the gap is {absolute:.3e}, no larger than the "
                        f"{resolution:.3e} the reference resolves"})
        return row

    row["judged_by"] = "relative"
    row["agrees"] = row["relative_error"] <= relative_tolerance
    row["justification"] = (
        f"the gap {absolute:.3e} exceeds the {resolution:.3e} the reference "
        f"resolves, so the entry is judged on relative error against a "
        f"denominator of max(|reference|,|oti|) = {denominator:.6e}")
    return row


def _summarise(rows: list[dict], drive=None) -> dict[str, Any]:
    resolved = [r for r in rows if r["reference_classification"] == "resolved"]
    measured = [r for r in resolved if r["judged_by"] == "relative"]
    zeros = [r for r in resolved if r["judged_by"] == "structural_zero"]
    return {
        "entries": len(rows),
        "resolved": len(resolved),
        "unresolved": len(rows) - len(resolved),
        "agreeing": sum(1 for r in resolved if r["agrees"]),
        "disagreeing": sum(1 for r in resolved if r["agrees"] is False),
        "structural_zeros": len(zeros),
        "structural_zeros_disagreeing":
            sum(1 for r in zeros if r["agrees"] is False),
        "judged_within_reference_resolution":
            len(resolved) - len(measured) - len(zeros),
        "measured": len(measured),
        "worst_measured_relative_error":
            max((r["relative_error"] for r in measured), default=None),
        "reference_method":
            "centred differences of the original untransformed build over a "
            f"ladder of steps in {_driven_through(drive) if drive else 'DSTRAN'}"
            "; the resolution is the spread of the flattest three-point window "
            "and uses no value from the OTI side",
        "reference_perturbation":
            "the same injection the transform seeded, read back from the "
            "emitted seed lines"
            + (": the strain directions mapped into DFGRD1 on the diagonal and "
               "at half size into both members of each off-diagonal pair"
               if drive is not None and drive.drives_deformation_gradient
               else ""),
        "driven_through": _driven_through(drive) if drive else "DSTRAN",
    }


def write_tangent_evidence(result: TangentResult, out_dir: Path) -> None:
    """Write the adjudicated entries and the gate record."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if result.rows:
        with (out_dir / "tangent_rows.csv").open("w", newline="",
                                                 encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(result.rows[0]),
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(result.rows)
    (out_dir / "tangent_evidence.json").write_text(
        json.dumps(result.as_dict(), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8")
