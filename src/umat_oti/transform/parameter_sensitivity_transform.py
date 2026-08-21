"""Generic PROPS-seeded parameter-sensitivity transformer.

Priority 1 of the SoftwareX continuation: a *generic* transformer that
takes any well-formed Abaqus UMAT source plus a contract with a
``parameters`` block and produces the same OTI Fortran outputs
(``DSIGMA_DP``, ``DSTATEV_DP``) that the J2-specific reference emitter
(:mod:`umat_oti.fortran_emit.parameter_sensitivity_j2`) produces — but
without any hard-coded J2 equations, material constants, or four-parameter
assumption.

Pipeline
--------

1. Parse the UMAT source with the repository parser
   (:mod:`umat_oti.fortran.parser`).
2. Walk the callee closure starting from ``SUBROUTINE UMAT`` and lift each
   subroutine (UMAT included) through
   :func:`umat_oti.transform.helper_lifting.lift_helper_set_source`. The
   lifter converts implicit typing to OTI, replaces ``REAL`` /
   ``DIMENSION`` declarations by ``TYPE(<ONUMM*N1>)``, and leaves the
   physics untouched.
3. Wrap the lifted set inside a Fortran module ``umat_oti_lifted_mod``.
4. Generate the OTI algebra module (:func:`generate_otilib_module`) with
   one basis per selected parameter (``nbases = NPARAM``, ``order = 1``).
5. Emit a material-point driver that seeds every named parameter's
   ``PROPS`` slot with the matching OTI direction, replays the loading
   path defined by the contract, and extracts
   ``DSIGMA_DP(i, k) = GETIM(STRESS(i), k)`` and
   ``DSTATEV_DP(l, k) = GETIM(STATEV(l), k)``.
6. Emit a ``Makefile`` for gfortran.

Nothing in this module hard-codes J2 equations, four parameters, or any
material-specific behaviour. The J2-specific hand-lifted emitter under
:mod:`umat_oti.fortran_emit.parameter_sensitivity_j2` remains as a
reference fixture that this transformer's output is compared against.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from umat_oti.core.model import ParsedFortranSource
from umat_oti.fortran.normalize import detect_source_form
from umat_oti.fortran.parser import logical_lines_from_text, parse_subroutines
from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.helper_lifting import (
    HelperLiftingError,
    _routine_callees,
    lift_helper_set_source,
)


@dataclass
class GenericPSContract:
    """Validated inputs for the generic transformer."""

    name: str
    umat_source_path: Path
    parameters: tuple[tuple[str, int], ...]
    parameter_values: tuple[float, ...]
    state_variables: tuple[tuple[str, int], ...]
    ntens: int
    nstatv: int
    ndi: int
    nshr: int
    dstran_per_increment: tuple[float, ...]
    n_increments: int
    static_props: tuple[float, ...] = field(default_factory=tuple)


@dataclass
class GenericPSLayout:
    root: Path
    master_parameters: Path
    real_utils: Path
    otim_module: Path
    lifted_umat: Path
    driver: Path
    makefile: Path
    module_name: str
    type_name: str
    n_param: int
    umat_and_helpers: tuple[str, ...]


@dataclass
class GenericPSRunResult:
    executable: Path
    returncode: int
    stdout: str
    stderr: str
    primal_csv: Path
    dsigma_csv: Path
    dstatev_csv: Path


class NonDifferentiableParameterPathError(ValueError):
    code = "non_differentiable_integer_parameter_path"

    def __init__(self, variable: str, props_index: int):
        self.variable = variable
        self.props_index = props_index
        self.suggested_patch = f"Declare {variable} as REAL(8) if integer typing was unintended."
        super().__init__(
            f"{self.code}: PROPS({props_index}) flows through INTEGER variable {variable}; "
            f"integer conversion is non-differentiable. Suggested source preparation (not applied): "
            f"{self.suggested_patch}"
        )


def transform_umat_for_parameter_sensitivity(
    *, contract: GenericPSContract, output_dir: Path | str
) -> GenericPSLayout:
    """Emit the OTI-lifted UMAT + driver + Makefile for a generic UMAT."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    n_param = len(contract.parameters)
    if n_param == 0:
        raise ValueError("contract.parameters must not be empty")
    if len(contract.parameter_values) != n_param:
        raise ValueError("parameter_values length must match parameters length")

    source_text = contract.umat_source_path.read_text(encoding="utf-8", errors="replace")
    _reject_integer_parameter_paths(source_text, contract.parameters)

    module_result = generate_otilib_module(
        output_dir=output_dir, ntens=n_param, order=1
    )
    parsed = _parse_umat_source(contract.umat_source_path)
    umat_and_helpers = _closure_including_umat(parsed)

    try:
        lifted = lift_helper_set_source(
            parsed,
            umat_and_helpers,
            module_name=module_result.module_name,
            type_name=module_result.type_name,
        )
    except HelperLiftingError as exc:
        raise RuntimeError(
            f"could not lift UMAT '{contract.umat_source_path.name}': {exc}"
        ) from exc

    lifted_path = output_dir / "umat_oti_lifted.f90"
    lifted_path.write_text(
        _wrap_lifted_in_module(lifted.source, module_name=module_result.module_name),
        encoding="utf-8",
    )

    driver_path = output_dir / "ps_driver.f90"
    driver_path.write_text(
        _emit_driver(contract, module_result.module_name, module_result.type_name),
        encoding="utf-8",
    )

    (output_dir / "Makefile").write_text(
        _emit_makefile(module_result.module_name), encoding="utf-8"
    )

    return GenericPSLayout(
        root=output_dir,
        master_parameters=module_result.master_parameters_path,
        real_utils=module_result.real_utils_path,
        otim_module=module_result.module_path,
        lifted_umat=lifted_path,
        driver=driver_path,
        makefile=output_dir / "Makefile",
        module_name=module_result.module_name,
        type_name=module_result.type_name,
        n_param=n_param,
        umat_and_helpers=umat_and_helpers,
    )


def compile_generic_ps(
    layout: GenericPSLayout, *, gfortran: str = "gfortran"
) -> Path:
    if shutil.which(gfortran) is None:
        raise RuntimeError(f"compiler {gfortran!r} not on PATH")
    proc = subprocess.run(
        ["make", f"FC={gfortran}"],
        cwd=str(layout.root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"generic PS build failed:\n{proc.stdout}\n{proc.stderr}"
        )
    exe = layout.root / "ps_driver"
    if not exe.is_file():
        raise RuntimeError(f"driver not built at {exe}")
    return exe


def run_generic_ps(
    executable: Path, *, out_dir: Optional[Path] = None
) -> GenericPSRunResult:
    out_dir = Path(out_dir) if out_dir is not None else executable.parent
    proc = subprocess.run(
        [str(executable)],
        cwd=str(out_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    return GenericPSRunResult(
        executable=executable,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        primal_csv=out_dir / "primal_stress_state_OTI.csv",
        dsigma_csv=out_dir / "DSIGMA_DP_OTI.csv",
        dstatev_csv=out_dir / "DSTATEV_DP_OTI.csv",
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _parse_umat_source(path: Path) -> ParsedFortranSource:
    text = path.read_text(encoding="utf-8", errors="replace")
    form = detect_source_form(path, text)
    logical = logical_lines_from_text(text, form)
    subroutines = parse_subroutines(logical)
    return ParsedFortranSource(
        path=path,
        form=form,
        text=text,
        logical_lines=tuple(logical),
        subroutines=tuple(subroutines),
    )


def _reject_integer_parameter_paths(source_text: str, parameters: tuple[tuple[str, int], ...]) -> None:
    selected_indices = {index for _, index in parameters}
    explicit_real = _declared_names(source_text, r"^\s*(?:REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?|DOUBLE\s+PRECISION)\b")
    explicit_integer = _declared_names(source_text, r"^\s*INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?\b")
    assignment = re.compile(
        r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(?:INT\s*\(\s*)?PROPS\s*\(\s*(\d+)\s*\)",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in assignment.finditer(source_text):
        variable = match.group(1).upper()
        props_index = int(match.group(2))
        if props_index not in selected_indices:
            continue
        explicitly_converted = "INT" in match.group(0).upper().split("PROPS", 1)[0]
        implicitly_integer = variable[0] in "IJKLMN" and variable not in explicit_real
        if explicitly_converted or variable in explicit_integer or implicitly_integer:
            raise NonDifferentiableParameterPathError(variable, props_index)


def _declared_names(source_text: str, declaration_pattern: str) -> set[str]:
    declarations = re.compile(declaration_pattern, re.IGNORECASE | re.MULTILINE)
    names: set[str] = set()
    for match in declarations.finditer(source_text):
        line = source_text[match.end():].splitlines()[0].split("!", 1)[0]
        line = line.split("::", 1)[-1]
        for token in line.split(","):
            name_match = re.match(r"\s*([A-Z][A-Z0-9_]*)", token, re.IGNORECASE)
            if name_match:
                names.add(name_match.group(1).upper())
    return names


def _closure_including_umat(parsed: ParsedFortranSource) -> tuple[str, ...]:
    routines = {r.upper_name: r for r in parsed.subroutines}
    if "UMAT" not in routines:
        raise RuntimeError(
            "the source does not contain SUBROUTINE UMAT; this transformer "
            "expects a standard Abaqus UMAT entry"
        )
    ordered: list[str] = []
    seen: set[str] = set()
    pending = ["UMAT"]
    source_lines = parsed.text.splitlines()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        routine = routines.get(current)
        if routine is None:
            continue
        for callee in _routine_callees(routine, parsed.form, source_lines):
            if callee not in seen and callee in routines:
                pending.append(callee)
    return tuple(ordered)


def _wrap_lifted_in_module(body: str, *, module_name: str) -> str:
    header = (
        "!===============================================================\n"
        "! OTI-lifted UMAT + helper closure.\n"
        "! Generated by umat_oti.transform.parameter_sensitivity_transform.\n"
        "!===============================================================\n"
        "MODULE umat_oti_lifted_mod\n"
        "  USE master_parameters, ONLY: DP\n"
        f"  USE {module_name}\n"
        "  IMPLICIT NONE\n"
        "  PUBLIC\n"
        "CONTAINS\n\n"
    )
    footer = "\nEND MODULE umat_oti_lifted_mod\n"
    return header + body + footer


def _emit_driver(
    contract: GenericPSContract, module_name: str, type_name: str
) -> str:
    n_param = len(contract.parameters)
    ntens = contract.ntens
    nstatv = contract.nstatv
    nprops_from_indices = max((idx for _, idx in contract.parameters), default=0)
    nprops = max(nprops_from_indices, len(contract.static_props), n_param)

    seed_lines: list[str] = []
    seen_indices: set[int] = set()
    for k, ((_name, props_index), value) in enumerate(
        zip(contract.parameters, contract.parameter_values), start=1
    ):
        seed_lines.append(
            f"  PROPS({props_index}) = {value:.17e}_DP + E{k}"
        )
        seen_indices.add(props_index)
    for j, val in enumerate(contract.static_props, start=1):
        if j in seen_indices:
            continue
        seed_lines.append(f"  PROPS({j}) = {val:.17e}_DP")

    dstran_lines = "\n".join(
        f"     DSTRAN({i + 1}) = {v:.17e}_DP"
        for i, v in enumerate(contract.dstran_per_increment)
    )

    param_names = [name for name, _ in contract.parameters]
    state_names = [name for name, _ in contract.state_variables] or [f"S{i + 1}" for i in range(nstatv)]

    header_sigma_row = ",".join(param_names)
    header_state_row = ",".join(param_names)

    stress_write_terms = ", ".join(f"STRESS({i + 1})%R" for i in range(ntens))
    statev_write_terms = ", ".join(f"STATEV({i + 1})%R" for i in range(nstatv))

    sigma_getim_terms = ", ".join(
        f"GETIM(STRESS(I), {k})" for k in range(1, n_param + 1)
    )
    statev_getim_terms = ", ".join(
        f"GETIM(STATEV(I), {k})" for k in range(1, n_param + 1)
    )

    n_fields_primal = ntens + nstatv
    stress_fmt = f'(I0,",oti",{n_fields_primal}(",",ES23.15))'
    sigma_fmt = f'(I0,",",I0,",oti",{n_param}(",",ES23.15))'
    statev_fmt = f'(I0,",",I0,",oti",{n_param}(",",ES23.15))'

    header_primal = (
        "increment,method,"
        + ",".join(f"stress_{i + 1}" for i in range(ntens))
        + ","
        + ",".join(state_names)
    )
    header_sigma = "increment,stress_component,method," + header_sigma_row
    header_state = "increment,state_variable,method," + header_state_row

    lines: list[str] = []
    lines.append("!===============================================================")
    lines.append("! Generic OTI parameter-sensitivity material-point driver.")
    lines.append("! Generated by umat_oti.transform.parameter_sensitivity_transform.")
    lines.append("!===============================================================")
    lines.append("PROGRAM ps_driver")
    lines.append("  USE master_parameters, ONLY: DP")
    lines.append(f"  USE {module_name}")
    lines.append("  USE umat_oti_lifted_mod")
    lines.append("  IMPLICIT NONE")
    lines.append("")
    lines.append(f"  INTEGER, PARAMETER :: N_INC     = {contract.n_increments}")
    lines.append(f"  INTEGER, PARAMETER :: NTENS_    = {ntens}")
    lines.append(f"  INTEGER, PARAMETER :: NSTATV_   = {nstatv}")
    lines.append(f"  INTEGER, PARAMETER :: NPROPS_   = {nprops}")
    lines.append(f"  INTEGER, PARAMETER :: NDI_      = {contract.ndi}")
    lines.append(f"  INTEGER, PARAMETER :: NSHR_     = {contract.nshr}")
    lines.append("")
    lines.append(f"  TYPE({type_name}) :: STRESS(NTENS_), STATEV(NSTATV_), PROPS(NPROPS_)")
    lines.append(f"  TYPE({type_name}) :: DSTRAN(NTENS_), STRAN(NTENS_)")
    lines.append(f"  TYPE({type_name}) :: DDSDDE(NTENS_,NTENS_)")
    lines.append(f"  TYPE({type_name}) :: SSE, SPD, SCD, RPL")
    lines.append(f"  TYPE({type_name}) :: DDSDDT(NTENS_), DRPLDE(NTENS_), DRPLDT")
    lines.append(f"  TYPE({type_name}) :: PNEWDT, CELENT")
    lines.append(f"  TYPE({type_name}) :: DFGRD0(3,3), DFGRD1(3,3)")
    lines.append(f"  TYPE({type_name}) :: TIME(2), DTIME, TEMP, DTEMP, PREDEF(1), DPRED(1)")
    lines.append(f"  TYPE({type_name}) :: COORDS(3), DROT(3,3)")
    lines.append("  CHARACTER(len=80) :: CMNAME")
    lines.append("  INTEGER :: NOEL, NPT, LAYER, KSPT, KSTEP, KINC")
    lines.append("  INTEGER :: I, K, INC")
    lines.append("  INTEGER :: U_PRIMAL, U_SIGMA, U_STATE")
    lines.append("")
    lines.append("  ! -- Seed PROPS with OTI directions --------------------------")
    lines.extend(seed_lines)
    lines.append("")
    lines.append("  ! -- Initialise state -----------------------------------------")
    lines.append("  DO I = 1, NTENS_")
    lines.append("     STRESS(I) = 0.0_DP")
    lines.append("     STRAN(I)  = 0.0_DP")
    lines.append("     DSTRAN(I) = 0.0_DP")
    lines.append("  END DO")
    lines.append("  DO I = 1, NSTATV_")
    lines.append("     STATEV(I) = 0.0_DP")
    lines.append("  END DO")
    lines.append("")
    lines.append("  DDSDDE = 0.0_DP")
    lines.append("  DDSDDT = 0.0_DP; DRPLDE = 0.0_DP; DRPLDT = 0.0_DP")
    lines.append("  SSE = 0.0_DP; SPD = 0.0_DP; SCD = 0.0_DP; RPL = 0.0_DP")
    lines.append("  TIME = 0.0_DP; DTIME = 1.0_DP")
    lines.append("  TEMP = 293.15_DP; DTEMP = 0.0_DP")
    lines.append("  PREDEF = 0.0_DP; DPRED = 0.0_DP")
    lines.append("  COORDS = 0.0_DP; DROT = 0.0_DP")
    lines.append("  DFGRD0 = 0.0_DP; DFGRD1 = 0.0_DP")
    lines.append("  DO I = 1, 3")
    lines.append("     DROT(I,I) = 1.0_DP")
    lines.append("     DFGRD0(I,I) = 1.0_DP")
    lines.append("     DFGRD1(I,I) = 1.0_DP")
    lines.append("  END DO")
    lines.append("  PNEWDT = 1.0_DP; CELENT = 1.0_DP")
    lines.append('  CMNAME = "MATERIAL_OTI"')
    lines.append("  NOEL = 1; NPT = 1; LAYER = 1; KSPT = 1; KSTEP = 1; KINC = 1")
    lines.append("")
    lines.append("  ! -- CSV headers ----------------------------------------------")
    lines.append('  OPEN(NEWUNIT=U_PRIMAL, FILE="primal_stress_state_OTI.csv", STATUS="REPLACE", ACTION="WRITE")')
    lines.append(f'  WRITE(U_PRIMAL, \'(A)\') "{header_primal}"')
    lines.append('  OPEN(NEWUNIT=U_SIGMA, FILE="DSIGMA_DP_OTI.csv", STATUS="REPLACE", ACTION="WRITE")')
    lines.append(f'  WRITE(U_SIGMA, \'(A)\') "{header_sigma}"')
    lines.append('  OPEN(NEWUNIT=U_STATE, FILE="DSTATEV_DP_OTI.csv", STATUS="REPLACE", ACTION="WRITE")')
    lines.append(f'  WRITE(U_STATE, \'(A)\') "{header_state}"')
    lines.append("")
    lines.append("  ! -- Loading loop ---------------------------------------------")
    lines.append("  DO INC = 1, N_INC")
    lines.append(dstran_lines)
    lines.append("")
    lines.append("     CALL umat_oti(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, &")
    lines.append("                   RPL, DDSDDT, DRPLDE, DRPLDT, &")
    lines.append("                   STRAN, DSTRAN, TIME, DTIME, TEMP, DTEMP, &")
    lines.append("                   PREDEF, DPRED, CMNAME, &")
    lines.append("                   NDI_, NSHR_, NTENS_, NSTATV_, PROPS, NPROPS_, &")
    lines.append("                   COORDS, DROT, PNEWDT, CELENT, DFGRD0, DFGRD1, &")
    lines.append("                   NOEL, NPT, LAYER, KSPT, KSTEP, KINC)")
    lines.append("")
    lines.append(f"     WRITE(U_PRIMAL, '{stress_fmt}') INC, {stress_write_terms}, {statev_write_terms}")
    lines.append("     DO I = 1, NTENS_")
    lines.append(f"        WRITE(U_SIGMA, '{sigma_fmt}') INC, I, {sigma_getim_terms}")
    lines.append("     END DO")
    lines.append("     DO I = 1, NSTATV_")
    lines.append(f"        WRITE(U_STATE, '{statev_fmt}') INC, I, {statev_getim_terms}")
    lines.append("     END DO")
    lines.append("")
    lines.append("     DO I = 1, NTENS_")
    lines.append("        STRAN(I) = STRAN(I) + DSTRAN(I)")
    lines.append("     END DO")
    lines.append("  END DO")
    lines.append("")
    lines.append("  CLOSE(U_PRIMAL); CLOSE(U_SIGMA); CLOSE(U_STATE)")
    lines.append("END PROGRAM ps_driver")
    return "\n".join(lines) + "\n"


def _emit_makefile(module_name: str) -> str:
    return f"""FC      ?= gfortran
FCFLAGS ?= -O1 -std=legacy -ffree-line-length-none -fno-align-commons

.PHONY: all clean
all: ps_driver

master_parameters.o: master_parameters.f90
\t$(FC) $(FCFLAGS) -c $<

real_utils.o: real_utils.f90 master_parameters.o
\t$(FC) $(FCFLAGS) -c $<

{module_name}.o: {module_name}.f90 master_parameters.o real_utils.o
\t$(FC) $(FCFLAGS) -c $<

umat_oti_lifted.o: umat_oti_lifted.f90 {module_name}.o
\t$(FC) $(FCFLAGS) -c $<

ps_driver.o: ps_driver.f90 umat_oti_lifted.o {module_name}.o
\t$(FC) $(FCFLAGS) -c $<

ps_driver: master_parameters.o real_utils.o {module_name}.o umat_oti_lifted.o ps_driver.o
\t$(FC) $(FCFLAGS) $^ -o $@

clean:
\trm -f *.o *.mod ps_driver *.csv
"""


__all__ = [
    "GenericPSContract",
    "GenericPSLayout",
    "GenericPSRunResult",
    "NonDifferentiableParameterPathError",
    "compile_generic_ps",
    "run_generic_ps",
    "transform_umat_for_parameter_sensitivity",
]
