"""Independent validation of DSIGMA_DP / DSTATEV_DP against the original UMAT.

The OTI driver produced by the parameter-sensitivity transform reports
``d(STRESS)/dp`` and ``d(STATEV)/dp`` directly from imaginary coefficients. To
check them, this compiles the **original, untransformed** Fortran and replays
the same loading path with each parameter perturbed, forming a centred finite
difference.

The reference must be the original UMAT. A Python re-implementation of the same
constitutive equations would share every modelling assumption with the thing
being checked, so agreement would prove only that the two transcriptions match
-- not that the transformation is correct. The independence here comes from the
reference being a separate compilation of the author's own source.

Order of operations matters and is enforced by the caller: primal parity first,
derivatives only after. If the original and transformed builds disagree about
STRESS along the path, their derivatives are not comparable quantities.

Algorithm provenance: the centred-difference-of-the-original approach, the
relative-RMSE score and the parameter-weighted ``p * d(.)/dp`` presentation are
taken from ``results/program1_material_validation.py`` at commit ``c49ffcc`` of
the divergent Residual_Assembler copy. Only the algorithm was reused; that
script's ABI plumbing, figure generation and report artifacts were not.
"""

from __future__ import annotations

import csv
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

ABA_PARAM = "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n"

#: Relative perturbation for the centred difference. Large enough to clear
#: double-precision round-off in the stress update, small enough that the
#: second-order truncation term stays far below the agreement threshold.
DEFAULT_REL_STEP = 1.0e-4

#: A derivative whose magnitude is below this (relative to the largest in its
#: column) is judged by absolute agreement: a relative error against zero is
#: meaningless.
NEAR_ZERO_FRACTION = 1.0e-10

#: Double-precision unit round-off.
_EPS = 2.220446049250313e-16
#: How many multiples of the estimated centred-difference noise floor a reference
#: value must exceed before it is treated as resolved. A centred difference of
#: two responses that agree to within round-off carries no information, however
#: small the number it produces looks.
FD_RESOLUTION_MARGIN = 8.0


@dataclass
class ReplayResult:
    """Per-increment primal response from one run of the original UMAT."""

    stress: list[list[float]]
    statev: list[list[float]]

    @property
    def increments(self) -> int:
        return len(self.stress)


@dataclass
class ValidationRow:
    """One (increment, response component, parameter) comparison."""

    increment: int
    array: str
    component: int
    parameter: str
    props_index: int
    oti_direction: int
    oti: float
    reference: float
    absolute_error: float
    relative_error: float | None
    judged_by: str
    #: ``None`` means the reference could not resolve this row: neither verified
    #: nor failed.
    agrees: bool | None
    branch: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def driver_source(*, ntens: int, nstatv: int, nprops: int,
                  finite_strain: bool = False) -> str:
    """A driver that replays a path through the ORIGINAL UMAT.

    Reads NPROPS values then the increment count and each DSTRAN row from stdin,
    so one compiled executable serves every perturbation without recompiling.

    With ``finite_strain`` the deformation gradient is driven as well. Holding
    DFGRD at the identity is correct only for a small-strain model: a
    hyperelastic UMAT computes its stress from DFGRD1 alone and would return
    zero stress for every increment, which looks like a working run producing
    trivial output. Each increment then reads nine additional values, the
    row-major increment of F, and advances DFGRD0 -> DFGRD1 by it.
    """
    nsv = max(nstatv, 1)
    read_gradient = ("    READ(*,*) DFGRDINC\n"
                     "    DFGRD0=DFGRD1\n"
                     "    DFGRD1=DFGRD1+RESHAPE(DFGRDINC,[3,3],ORDER=[2,1])\n"
                     if finite_strain else "")
    declare_gradient = ("  REAL(8) :: DFGRDINC(9)\n" if finite_strain else "")
    return f"""PROGRAM original_reference_driver
  IMPLICIT NONE
  INTEGER, PARAMETER :: NTENS={ntens}, NSTATV={nsv}, NPROPS={max(nprops, 1)}
  REAL(8) :: STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),SSE,SPD,SCD,RPL
  REAL(8) :: DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT,STRAN(NTENS),DSTRAN(NTENS)
  REAL(8) :: TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3)
  REAL(8) :: DROT(3,3),PNEWDT,CELENT,DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NDI,NSHR,NOEL,NPT,LAYER,KSPT,KSTEP,KINC,I,NINC
{declare_gradient}  CHARACTER(80) :: CMNAME
  STRESS=0.0_8;STATEV=0.0_8;DDSDDE=0.0_8;STRAN=0.0_8;DSTRAN=0.0_8
  SSE=0.0_8;SPD=0.0_8;SCD=0.0_8;RPL=0.0_8;DDSDDT=0.0_8;DRPLDE=0.0_8;DRPLDT=0.0_8
  TIME=0.0_8;DTIME=1.0_8;TEMP=293.15_8;DTEMP=0.0_8;PREDEF=0.0_8;DPRED=0.0_8
  COORDS=0.0_8;DROT=0.0_8;DFGRD0=0.0_8;DFGRD1=0.0_8
  DO I=1,3
    DROT(I,I)=1.0_8;DFGRD0(I,I)=1.0_8;DFGRD1(I,I)=1.0_8
  END DO
  PNEWDT=1.0_8;CELENT=1.0_8;CMNAME='ORIGINAL_REFERENCE'
  NDI=3;NSHR={max(ntens - 3, 0)};NOEL=1;NPT=1;LAYER=1;KSPT=1;KSTEP=1
  READ(*,*) PROPS
  READ(*,*) NINC
  DO KINC=1,NINC
    READ(*,*) DSTRAN
{read_gradient}    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV, &
      PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
    WRITE(*,'({ntens + nsv}(ES26.17E3,1X))') STRESS,STATEV
    STRAN=STRAN+DSTRAN;TIME=TIME+DTIME
  END DO
END PROGRAM original_reference_driver
SUBROUTINE GETOUTDIR(PATH,NCHAR)
  CHARACTER(*) :: PATH
  INTEGER :: NCHAR
  PATH='.';NCHAR=1
END SUBROUTINE GETOUTDIR
SUBROUTINE XIT
  WRITE(0,'(A)') 'original UMAT called XIT (local solve did not converge)'
  STOP 3
END SUBROUTINE XIT
"""


def build_original_driver(source: Path, out_dir: Path, *, ntens: int, nstatv: int,
                          nprops: int, compiler: str = "gfortran",
                          finite_strain: bool = False,
                          link_libraries: Sequence[str] = (),
                          extra_sources: Sequence[Path] = ()) -> Path:
    """Compile the untransformed source into a replayable reference executable."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("aba_param.inc", "ABA_PARAM.INC", "ABA_PARAM.inc", "aba_param.INC"):
        (out_dir / name).write_text(ABA_PARAM, encoding="utf-8")

    obj = out_dir / "original_umat.o"
    fixed = source.suffix.lower() in {".f", ".for", ".f77"}
    form = ["-ffixed-form", "-ffixed-line-length-none"] if fixed else \
        ["-ffree-line-length-none"]
    compile_umat = subprocess.run(
        [compiler, "-O1", "-std=legacy", *form, "-I", str(out_dir),
         "-c", str(source), "-o", str(obj)],
        cwd=out_dir, capture_output=True, text=True)
    if compile_umat.returncode != 0:
        raise RuntimeError(f"original UMAT compile failed:\n{compile_umat.stderr[:3000]}")

    driver = out_dir / "original_reference_driver.f90"
    driver.write_text(
        driver_source(ntens=ntens, nstatv=nstatv, nprops=nprops,
                      finite_strain=finite_strain),
        encoding="utf-8")

    extra_objects = []
    for index, extra in enumerate(extra_sources):
        extra = Path(extra)
        extra_object = out_dir / f"extra_{index}.o"
        extra_fixed = extra.suffix.lower() in {".f", ".for", ".f77"}
        extra_form = (["-ffixed-form", "-ffixed-line-length-none"] if extra_fixed
                      else ["-ffree-line-length-none"])
        built = subprocess.run(
            [compiler, "-O1", "-std=legacy", *extra_form, "-I", str(out_dir),
             "-c", str(extra), "-o", str(extra_object)],
            cwd=out_dir, capture_output=True, text=True)
        if built.returncode != 0:
            raise RuntimeError(
                f"supporting source {extra.name} failed to compile:\n"
                f"{built.stderr[:2000]}")
        extra_objects.append(str(extra_object))

    executable = out_dir / "original_reference_driver"
    link = subprocess.run(
        [compiler, "-O1", "-std=legacy", "-ffree-line-length-none",
         str(driver), str(obj), *extra_objects, *link_libraries,
         "-o", str(executable)],
        cwd=out_dir, capture_output=True, text=True)
    if link.returncode != 0:
        raise RuntimeError(f"reference driver link failed:\n{link.stderr[:3000]}")
    return executable


def replay(executable: Path, props: Sequence[float],
           path: Sequence[Sequence[float]], *, ntens: int, nstatv: int,
           deformation_gradient_increment: Optional[Sequence[float]] = None
           ) -> ReplayResult:
    """Run the original UMAT over the path with the given PROPS.

    ``deformation_gradient_increment`` is a row-major 3x3 added to F each
    increment, for drivers built with ``finite_strain=True``.
    """
    payload = " ".join(f"{v:.17e}" for v in props) + "\n"
    payload += f"{len(path)}\n"
    rows = []
    for entry in path:
        line = " ".join(f"{v:.17e}" for v in entry)
        if deformation_gradient_increment is not None:
            line += "\n" + " ".join(
                f"{v:.17e}" for v in deformation_gradient_increment)
        rows.append(line)
    payload += "\n".join(rows) + "\n"
    result = subprocess.run([str(executable)], input=payload,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"original driver failed (rc={result.returncode}): "
                           f"{result.stderr[:800]}")
    stress, statev = [], []
    nsv = max(nstatv, 1)
    for line in result.stdout.strip().splitlines():
        try:
            values = [float(v) for v in line.split()]
        except ValueError as exc:
            # Fortran drops the "E" when an exponent will not fit the field, so
            # "1.0E+207" prints as "1.0+207". Seeing that means the model
            # produced a value around 1e100 or larger, which is divergence, not
            # a formatting curiosity -- say so rather than surfacing a bare
            # float() error from deep inside the parser.
            raise RuntimeError(
                "the original UMAT produced a value too large to represent: "
                f"{exc}. This is numerical divergence along the requested "
                "loading path, not a reporting problem; the property vector or "
                "the path is not usable for this model.") from exc
        if len(values) != ntens + nsv:
            raise RuntimeError(
                f"reference driver returned {len(values)} values, expected {ntens + nsv}")
        stress.append(values[:ntens])
        statev.append(values[ntens:])
    return ReplayResult(stress=stress, statev=statev)


def centered_fd(executable: Path, props: Sequence[float],
                path: Sequence[Sequence[float]], *, ntens: int, nstatv: int,
                props_indices: Sequence[int],
                rel_step: float = DEFAULT_REL_STEP,
                deformation_gradient_increment: Optional[Sequence[float]] = None
                ) -> dict[int, dict[str, list]]:
    """Centred differences of the ORIGINAL UMAT w.r.t. each seeded property.

    Two extra replays per parameter, at ``p*(1+h)`` and ``p*(1-h)``. A property
    that is exactly zero falls back to an absolute step, since a relative one
    would not perturb it at all.
    """
    out: dict[int, dict[str, list]] = {}
    for index in props_indices:
        base = float(props[index - 1])
        step = rel_step * abs(base) if base != 0.0 else rel_step
        plus, minus = list(props), list(props)
        plus[index - 1] = base + step
        minus[index - 1] = base - step
        high = replay(executable, plus, path, ntens=ntens, nstatv=nstatv,
                      deformation_gradient_increment=deformation_gradient_increment)
        low = replay(executable, minus, path, ntens=ntens, nstatv=nstatv,
                     deformation_gradient_increment=deformation_gradient_increment)
        denominator = 2.0 * step
        out[index] = {
            "step": step,
            "dsigma": [[(h - l) / denominator for h, l in zip(hs, ls)]
                       for hs, ls in zip(high.stress, low.stress)],
            "dstatev": [[(h - l) / denominator for h, l in zip(hs, ls)]
                        for hs, ls in zip(high.statev, low.statev)],
        }
    return out


def read_oti_csv(path: Path) -> dict[tuple[int, int], dict[str, float]]:
    """OTI derivatives keyed by (increment, component), value per parameter name."""
    values: dict[tuple[int, int], dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        names = [f for f in (reader.fieldnames or [])
                 if f not in ("increment", "stress_component", "state_variable", "method")]
        for row in reader:
            component = int(row.get("stress_component") or row.get("state_variable"))
            values[(int(row["increment"]), component)] = {
                name: float(row[name]) for name in names}
    return values


def fd_noise_floor(response_scale: float, step: float) -> float:
    """Smallest derivative a centred difference of this response can resolve.

    The difference of two doubles carries an absolute error of order
    ``eps * |f|``; dividing by ``2h`` turns that into ``eps * |f| / (2h)`` on the
    derivative. A reference value at or below that is round-off, not signal.
    """
    if step <= 0.0:
        return math.inf
    return _EPS * max(abs(response_scale), 1.0) / (2.0 * step)


def compare(oti: dict[tuple[int, int], dict[str, float]],
            reference: dict[int, dict[str, list]],
            *, array: str, parameters: Sequence[dict[str, Any]],
            branches: Sequence[str],
            relative_tolerance: float = 1.0e-6,
            response_scale: float | None = None) -> list[ValidationRow]:
    """One row per (increment, component, parameter).

    Three outcomes, not two. A row whose reference magnitude sits at the
    centred-difference noise floor is *unresolved*: the reference cannot say
    whether the OTI value is right, so the row is neither verified nor failed.
    Counting such a row as agreement would inflate the verified total; counting
    it as disagreement would blame the transformation for the reference's
    limits.
    """
    key = "dsigma" if array == "DSIGMA_DP" else "dstatev"
    scale: dict[str, float] = {}
    floor: dict[str, float] = {}
    for parameter in parameters:
        entry = reference[parameter["props_index"]]
        column = entry[key]
        scale[parameter["name"]] = max(
            (abs(v) for row in column for v in row), default=0.0)
        floor[parameter["name"]] = fd_noise_floor(
            response_scale if response_scale is not None else 1.0, entry["step"])

    rows: list[ValidationRow] = []
    for (increment, component), by_name in sorted(oti.items()):
        for parameter in parameters:
            name = parameter["name"]
            # The OTI CSV header uses the contract's parameter names uppercased.
            oti_value = by_name.get(name.upper(), by_name.get(name))
            if oti_value is None:
                continue
            reference_value = reference[parameter["props_index"]][key][increment - 1][component - 1]
            absolute = abs(oti_value - reference_value)
            column_scale = scale[name]
            magnitude = max(abs(oti_value), abs(reference_value))
            noise = floor[name]

            if absolute <= noise:
                # The two values differ by less than the centred difference can
                # distinguish. This is the reference's own uncertainty acting as
                # the agreement tolerance, exactly as a plateau spread does for
                # the higher-order study -- not a widened tolerance.
                relative = (absolute / abs(reference_value)
                            if abs(reference_value) > 0.0 else None)
                agrees = True
                judged = "within_reference_resolution"
            elif magnitude > NEAR_ZERO_FRACTION * column_scale and column_scale > 0.0:
                if magnitude < FD_RESOLUTION_MARGIN * noise:
                    # Non-trivial next to its own column, but still at the
                    # centred-difference noise floor, and the two do NOT agree to
                    # within it: the reference cannot settle this row either way.
                    relative = absolute / max(abs(reference_value), 1.0e-300)
                    agrees = None
                    judged = "reference_unresolved"
                else:
                    relative = absolute / max(abs(reference_value), 1.0e-300)
                    agrees = relative <= relative_tolerance
                    judged = "relative"
            else:
                relative = None
                # Absolute agreement is measured against the column's own scale,
                # not against an arbitrary constant.
                agrees = absolute <= max(column_scale, 1.0) * relative_tolerance
                judged = "absolute_near_zero"
            rows.append(ValidationRow(
                increment=increment, array=array, component=component,
                parameter=name, props_index=parameter["props_index"],
                oti_direction=parameter.get("oti_direction", 0),
                oti=oti_value, reference=reference_value,
                absolute_error=absolute, relative_error=relative,
                judged_by=judged, agrees=agrees,
                branch=branches[increment - 1] if increment <= len(branches) else "unknown",
            ))
    return rows


def primal_parity(original: ReplayResult, oti_primal_csv: Path, *,
                  ntens: int, nstatv: int,
                  relative_tolerance: float = 1.0e-9) -> dict[str, Any]:
    """Compare the original and transformed primal responses, increment by increment.

    Derivatives are not comparable until this agrees: two builds that compute a
    different stress are not the same model.
    """
    transformed_stress, transformed_state = [], []
    with oti_primal_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            transformed_stress.append(
                [float(row[f"stress_{i}"]) for i in range(1, ntens + 1)])
            transformed_state.append(
                [float(v) for k, v in row.items()
                 if k not in ("increment", "method") and not k.startswith("stress_")])

    per_increment, agrees_all = [], True
    for index, (orig, trans) in enumerate(zip(original.stress, transformed_stress), start=1):
        scale = max([abs(v) for v in orig] + [1.0])
        deltas = [abs(a - b) for a, b in zip(orig, trans)]
        state_deltas = [
            abs(a - b) for a, b in zip(original.statev[index - 1],
                                       transformed_state[index - 1])] \
            if index <= len(transformed_state) else []
        worst = max(deltas + state_deltas) if (deltas or state_deltas) else 0.0
        agrees = worst / scale <= relative_tolerance
        agrees_all = agrees_all and agrees
        per_increment.append({
            "increment": index,
            "max_absolute_difference": worst,
            "max_relative_difference": worst / scale,
            "agrees": agrees,
            "original_stress": orig,
            "transformed_stress": trans,
        })
    return {"agrees": agrees_all, "relative_tolerance": relative_tolerance,
            "per_increment": per_increment}
