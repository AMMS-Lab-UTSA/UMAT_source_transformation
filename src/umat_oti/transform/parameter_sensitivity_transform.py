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

from umat_oti.oti.oti_directions import member_name

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from umat_oti.core.model import ParsedFortranSource
from umat_oti.fortran.literals import without_real_literals
from umat_oti.fortran.normalize import detect_source_form
from umat_oti.fortran.parser import logical_lines_from_text, parse_subroutines
from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.helper_lifting import (
    HelperLiftingError,
    _routine_callees,
    function_names,
    lift_helper_set_source,
    routines_by_name,
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
    #: Row-major 3x3 added to the deformation gradient each increment. Required
    #: for a finite-strain UMAT: one that computes its stress from DFGRD1 sees
    #: an unchanging identity otherwise and returns zero stress for every
    #: increment, which looks like a successful run with trivial output.
    deformation_gradient_increment: tuple[float, ...] = field(default_factory=tuple)


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
    validate_parameter_paths(source_text, contract.parameters)

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
        _wrap_lifted_in_module(lifted.source, module_name=module_result.module_name,
                               n_param=n_param),
        encoding="utf-8",
    )

    driver_path = output_dir / "ps_driver.f90"
    driver_path.write_text(
        _emit_driver(contract, module_result.module_name, module_result.type_name),
        encoding="utf-8",
    )

    (output_dir / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module_result.module_name,
                                   module_result.type_name), encoding="utf-8")

    stubs = _required_utility_stubs(source_text)
    (output_dir / "abaqus_stubs.f90").write_text(
        "".join(_STUBBABLE_UTILITIES[name] for name in stubs), encoding="utf-8")

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


def validate_parameter_paths(source_text: str, parameters: tuple[tuple[str, int], ...]) -> None:
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
    routines = routines_by_name(parsed)
    defined_functions = function_names(parsed)
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
        for callee in _routine_callees(routine, parsed.form, source_lines,
                                       function_names=defined_functions):
            if callee not in seen and callee in routines:
                pending.append(callee)
    return tuple(ordered)


#: Identifier occurrences outside comments. Fortran is case-insensitive, so the
#: scan is too.
_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)")


def _strip_comments(source: str) -> str:
    return "\n".join(line.split("!", 1)[0] for line in source.splitlines())


def oti_direction_names(n_param: int, order: int = 1) -> tuple[str, ...]:
    """Named constants the generated OTI module exports for its directions."""
    from umat_oti.oti.oti_directions import member_name

    return tuple(member_name([k]) for k in range(1, n_param + 1))


def _colliding_direction_names(body: str, n_param: int) -> tuple[str, ...]:
    """Direction constants whose names the UMAT already uses for its own data.

    ``E1``, ``E2``, ``E3`` are ordinary names for elastic moduli, and a UMAT that
    declares one cannot also import a module constant of that name: gfortran
    rejects the assignment with "Named constant 'e1' in variable definition
    context". Seeding happens in the driver, never inside the lifted routine, so
    the constant is not needed here and the import can rename it away.
    """
    # Literals are masked out of the scan: ``1.E1`` is a number, and reading its
    # letter and digit as a mention of E1 renames a constant nothing collides
    # with. Same atomicity the rewrites hold, applied to the scan that drives
    # one.
    used = {name.upper() for name in
            _IDENTIFIER_RE.findall(without_real_literals(_strip_comments(body)))}
    return tuple(name for name in oti_direction_names(n_param) if name in used)


def _wrap_lifted_in_module(body: str, *, module_name: str, n_param: int = 0) -> str:
    collisions = _colliding_direction_names(body, n_param) if n_param else ()
    if collisions:
        renames = ", ".join(f"OTI_{name} => {name}" for name in collisions)
        use_line = f"  USE {module_name}, {renames}\n"
        note = ("! Direction constants renamed on import because this UMAT uses\n"
                f"! those names for its own variables: {', '.join(collisions)}.\n")
    else:
        use_line = f"  USE {module_name}\n"
        note = ""
    header = (
        "!===============================================================\n"
        "! OTI-lifted UMAT + helper closure.\n"
        "! Generated by umat_oti.transform.parameter_sensitivity_transform.\n"
        f"{note}"
        "!===============================================================\n"
        "MODULE umat_oti_lifted_mod\n"
        "  USE master_parameters, ONLY: DP\n"
        f"{use_line}"
        "  USE oti_intrinsics\n"
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
        # The OTI module names basis directions in base 36 -- direction 10 is
        # EA, not E10 -- so ask the same helper the module generator uses.
        # Writing f"E{k}" silently worked up to nine parameters and then emitted
        # a symbol that does not exist.
        seed_lines.append(
            f"  PROPS({props_index}) = {value:.17e}_DP + {member_name([k])}"
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
    stress_fmt = f'(I0,",oti",{n_fields_primal}(",",ES24.15E3))'
    sigma_fmt = f'(I0,",",I0,",oti",{n_param}(",",ES24.15E3))'
    statev_fmt = f'(I0,",",I0,",oti",{n_param}(",",ES24.15E3))'

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
    lines.append(f"  TYPE({type_name}) :: DFGRDINC(3,3)")
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
    lines.append("  DFGRDINC = 0.0_DP")
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
    increment = contract.deformation_gradient_increment
    if increment:
        if len(increment) != 9:
            raise ValueError(
                "deformation_gradient_increment must hold nine row-major values")
        lines.append("  ! -- Finite-strain deformation gradient increment -------------")
        for index, value in enumerate(increment):
            row, column = divmod(index, 3)
            lines.append(f"  DFGRDINC({row + 1},{column + 1}) = {value:.17e}_DP")
        lines.append("")

    lines.append("  DO INC = 1, N_INC")
    # The increment number is a UMAT argument that models legitimately branch on
    # (first-increment initialisation, step-dependent logic).  Pinning it at 1
    # would make the transformed build see a different loading history from the
    # untransformed reference and silently break primal parity for such models.
    lines.append("     KINC = INC")
    if increment:
        lines.append("     DFGRD0 = DFGRD1")
        lines.append("     DFGRD1 = DFGRD1 + DFGRDINC")
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
    # The untransformed reference driver advances step and total time together
    # with the strain.  Rate- and time-dependent models read TIME directly, so
    # leaving it at zero here would drive the two builds along different
    # loading histories and make primal parity compare unlike responses.
    lines.append("     TIME(1) = TIME(1) + DTIME")
    lines.append("     TIME(2) = TIME(2) + DTIME")
    lines.append("  END DO")
    lines.append("")
    lines.append("  CLOSE(U_PRIMAL); CLOSE(U_SIGMA); CLOSE(U_STATE)")
    lines.append("END PROGRAM ps_driver")
    return "\n".join(lines) + "\n"


#: Abaqus utility routines that a UMAT may call but that no standalone build
#: provides. Only routines whose contract is independent of the OTI arithmetic
#: can be stubbed here: XIT takes no arguments and only aborts. Routines that
#: consume or return material quantities (SPRINC, ROTSIG, SINV) would need
#: OTI-aware implementations, so they are reported as unsupported rather than
#: given a stub that silently returns wrong values.
_STUBBABLE_UTILITIES = {
    "XIT": """SUBROUTINE XIT
  WRITE(0,'(A)') 'UMAT called XIT (the model aborted the increment)'
  STOP 3
END SUBROUTINE XIT
""",
}

_UNSUPPORTED_UTILITIES = ("SPRINC", "SPRIND", "ROTSIG", "SINV", "STDB_ABQERR")

_CALL_RE = re.compile(r"(?:^|\W)CALL\s+([A-Za-z_]\w*)", re.IGNORECASE)
_DEFINITION_RE = re.compile(
    r"^\s*(?:\d+\s+)?(?:RECURSIVE\s+|PURE\s+|ELEMENTAL\s+)*SUBROUTINE\s+([A-Za-z_]\w*)",
    re.IGNORECASE | re.MULTILINE)


class UnsupportedAbaqusUtilityError(RuntimeError):
    """The source calls an Abaqus utility that cannot be stubbed faithfully."""

    code = "unsupported_abaqus_utility"


def _required_utility_stubs(source_text: str) -> tuple[str, ...]:
    """Utility routines the source calls but neither defines nor can obtain.

    A standalone material-point build has no Abaqus runtime to link against, so
    any such call is an unresolved symbol at link time. Detecting it here turns
    a raw linker error into a named, actionable outcome.
    """
    defined = {m.group(1).upper() for m in _DEFINITION_RE.finditer(source_text)}
    called = {m.group(1).upper() for m in _CALL_RE.finditer(source_text)}
    missing = called - defined
    blocked = sorted(missing.intersection(_UNSUPPORTED_UTILITIES))
    if blocked:
        raise UnsupportedAbaqusUtilityError(
            f"{UnsupportedAbaqusUtilityError.code}: this source calls "
            f"{', '.join(blocked)}, which operate on material quantities and "
            "would have to be reimplemented in OTI arithmetic; stubbing them "
            "would silently return wrong values")
    return tuple(sorted(missing.intersection(_STUBBABLE_UTILITIES)))



def _emit_intrinsic_extensions(module_name: str, type_name: str) -> str:
    """Mixed OTI/real forms of MIN, MAX and SIGN.

    The generated OTI module defines MIN and MAX only for two OTI operands, but
    UMATs routinely clamp against a real constant -- ``ENU=MIN(PROPS(2),ENUMAX)``
    with ENUMAX a REAL parameter is the idiom that first exposed this. gfortran
    then reports the generic as not matching any specific interface, which reads
    like a transformation bug and is really a missing overload.

    The semantics are the ones the mathematics requires rather than a
    convenience: MIN and MAX are piecewise, so the result carries the derivative
    of whichever operand was selected, and a real constant contributes a zero
    derivative. Generic interfaces are additive across modules, so declaring
    these here extends MIN and MAX rather than shadowing them.
    """
    lines = [
        "!===============================================================",
        "! Mixed OTI/real intrinsic overloads. Generic interfaces are",
        "! additive across modules, so these extend MIN/MAX/SIGN.",
        "!===============================================================",
        f"MODULE oti_intrinsics",
        "  USE master_parameters, ONLY: DP",
        f"  USE {module_name}",
        "  IMPLICIT NONE",
        # PRIVATE by default, then only the generics are re-exported. A blanket
        # PUBLIC would re-export everything this module imports, including the
        # direction constants E1, E2, ... -- which puts them straight back into
        # any scope that renamed them away to avoid colliding with a UMAT's own
        # variables of the same name.
        "  PRIVATE",
        "  PUBLIC :: MIN, MAX, SIGN, NINT, INT, ASSIGNMENT(=)",
        "  PUBLIC :: OPERATOR(+), OPERATOR(-), OPERATOR(*), OPERATOR(/)",
        "  INTERFACE MIN",
        "    MODULE PROCEDURE oti_min_or, oti_min_ro",
        "  END INTERFACE MIN",
        "  INTERFACE MAX",
        "    MODULE PROCEDURE oti_max_or, oti_max_ro",
        "  END INTERFACE MAX",
        "  INTERFACE SIGN",
        "    MODULE PROCEDURE oti_sign_oo, oti_sign_or, oti_sign_ro",
        "  END INTERFACE SIGN",
        # NINT of a differentiated value. A rounded value is piecewise
        # constant, so its derivative is zero wherever it is defined and the
        # integer it returns carries none. Without this a source that reads a
        # count out of its own state array -- NSLPTL=NINT(STATEV(...)) in a
        # crystal-plasticity model, which is how many slip systems there are --
        # fails to compile with "argument of NINT must be REAL".
        "  INTERFACE NINT",
        "    MODULE PROCEDURE oti_nint",
        "  END INTERFACE NINT",
        "  INTERFACE INT",
        "    MODULE PROCEDURE oti_int",
        "  END INTERFACE INT",
        # Unary plus. The generated module defines the binary operators but not
        # this one, so an expression like COFACTOR(2,2) = +(A(1,1)*A(3,3)-...)
        # -- ordinary in cofactor and adjugate code, and legal Fortran -- fails
        # with "Operand of unary numeric operator '+' is UNKNOWN".
        "  INTERFACE OPERATOR(+)",
        # Unary plus is not here. It belongs beside the unary minus, in the
        # generated algebra that defines the type, so that it is available on
        # every path rather than only where this extension module is emitted --
        # the corpus and Abaqus paths never emit it. Defining it in both places
        # makes the generic ambiguous and nothing compiles.
        "    MODULE PROCEDURE oti_add_io, oti_add_oi, oti_add_so, oti_add_os",
        "  END INTERFACE",
        # Integer meets differentiated value. Fortran's own mixed-mode rule
        # converts the integer and evaluates in the real type, and retyping the
        # real operand to a derived type takes that rule away: SLPNOR(K,N) =
        # IWKNOR(K,J)/RMONOR -- an integer Miller index over the norm of one --
        # stops the build with "Unexpected derived-type entities in binary
        # intrinsic numeric operator". The conversion is what the language would
        # have done, and an integer carries no derivative, so nothing but the
        # missing overload is being supplied here. (** already has integer forms
        # in the generated algebra.)
        "  INTERFACE OPERATOR(-)",
        "    MODULE PROCEDURE oti_sub_io, oti_sub_oi, oti_sub_so, oti_sub_os",
        "  END INTERFACE",
        "  INTERFACE OPERATOR(*)",
        "    MODULE PROCEDURE oti_mul_io, oti_mul_oi, oti_mul_so, oti_mul_os",
        "  END INTERFACE",
        "  INTERFACE OPERATOR(/)",
        "    MODULE PROCEDURE oti_div_io, oti_div_oi, oti_div_so, oti_div_os",
        "  END INTERFACE",
        # Mixed-kind assignment. The generated algebra assigns from REAL(DP)
        # only, so a REAL(4)-valued expression -- FLOAT(N), the F77 spelling of
        # an integer-to-real conversion, and anything built on one -- stops the
        # build with "Cannot convert REAL(4) to TYPE(...)". Widening the value
        # is exactly what the source's own REAL*8 assignment did with it, so the
        # number that reaches the variable is bit-for-bit the one the original
        # build stores. Rewriting FLOAT to DBLE instead would have computed the
        # expression in double and changed it: on this corpus that moved the
        # primal 8.9e-9, nine times the parity gate.
        "  INTERFACE ASSIGNMENT(=)",
        "    MODULE PROCEDURE oti_assign_s, oti_assign_i",
        "  END INTERFACE",
        "CONTAINS",
    ]

    def selector(name: str, first: str, second: str, comparison: str) -> list[str]:
        a_type = f"TYPE({type_name})" if first == "o" else "REAL(DP)"
        b_type = f"TYPE({type_name})" if second == "o" else "REAL(DP)"
        a_value = "A%R" if first == "o" else "A"
        b_value = "B%R" if second == "o" else "B"
        return [
            f"  FUNCTION {name}(A, B) RESULT(RES)",
            "    IMPLICIT NONE",
            f"    {a_type}, INTENT(IN) :: A",
            f"    {b_type}, INTENT(IN) :: B",
            f"    TYPE({type_name}) :: RES",
            f"    IF ({b_value} {comparison} {a_value}) THEN",
            "      RES = B",
            "    ELSE",
            "      RES = A",
            "    END IF",
            f"  END FUNCTION {name}",
        ]

    def mixed_operand(name: str, operator: str, other: str, other_first: bool) -> list[str]:
        a_type = other if other_first else f"TYPE({type_name})"
        b_type = f"TYPE({type_name})" if other_first else other
        a_value = "DBLE(A)" if other_first else "A"
        b_value = "B" if other_first else "DBLE(B)"
        return [
            f"  ELEMENTAL FUNCTION {name}(A, B) RESULT(RES)",
            "    IMPLICIT NONE",
            f"    {a_type}, INTENT(IN) :: A",
            f"    {b_type}, INTENT(IN) :: B",
            f"    TYPE({type_name}) :: RES",
            f"    RES = {a_value} {operator} {b_value}",
            f"  END FUNCTION {name}",
        ]

    lines += selector("oti_min_or", "o", "r", "<")
    lines += selector("oti_min_ro", "r", "o", "<")
    lines += selector("oti_max_or", "o", "r", ">")
    lines += selector("oti_max_ro", "r", "o", ">")
    for suffix, operator in (("add", "+"), ("sub", "-"), ("mul", "*"), ("div", "/")):
        lines += mixed_operand(f"oti_{suffix}_io", operator, "INTEGER", True)
        lines += mixed_operand(f"oti_{suffix}_oi", operator, "INTEGER", False)
        lines += mixed_operand(f"oti_{suffix}_so", operator, "REAL(KIND=4)", True)
        lines += mixed_operand(f"oti_{suffix}_os", operator, "REAL(KIND=4)", False)
    for name, other in (("oti_assign_s", "REAL(KIND=4)"), ("oti_assign_i", "INTEGER")):
        lines += [
            f"  ELEMENTAL SUBROUTINE {name}(RES, LHS)",
            "    IMPLICIT NONE",
            f"    {other}, INTENT(IN) :: LHS",
            f"    TYPE({type_name}), INTENT(OUT) :: RES",
            "    RES = DBLE(LHS)",
            f"  END SUBROUTINE {name}",
        ]
    # SIGN(a, b) is |a| with the sign of b; b contributes no derivative because
    # only its sign is used.
    lines += [
        "  FUNCTION oti_sign_oo(A, B) RESULT(RES)",
        "    IMPLICIT NONE",
        f"    TYPE({type_name}), INTENT(IN) :: A, B",
        f"    TYPE({type_name}) :: RES",
        "    IF (B%R < 0.0_DP) THEN",
        "      RES = -ABS(A)",
        "    ELSE",
        "      RES = ABS(A)",
        "    END IF",
        "  END FUNCTION oti_sign_oo",
        "  FUNCTION oti_sign_or(A, B) RESULT(RES)",
        "    IMPLICIT NONE",
        f"    TYPE({type_name}), INTENT(IN) :: A",
        "    REAL(DP), INTENT(IN) :: B",
        f"    TYPE({type_name}) :: RES",
        "    IF (B < 0.0_DP) THEN",
        "      RES = -ABS(A)",
        "    ELSE",
        "      RES = ABS(A)",
        "    END IF",
        "  END FUNCTION oti_sign_or",
        # SIGN(real, differentiated). The magnitude is a real constant and the
        # sign is piecewise constant, so the result is a real number with no
        # derivative to carry -- SIGN(1.D0, FSLIP(J)) is the usual way a flow
        # rule asks which way a slip system is going.
        "  FUNCTION oti_sign_ro(A, B) RESULT(RES)",
        "    IMPLICIT NONE",
        "    REAL(DP), INTENT(IN) :: A",
        f"    TYPE({type_name}), INTENT(IN) :: B",
        "    REAL(DP) :: RES",
        "    IF (B%R < 0.0_DP) THEN",
        "      RES = -ABS(A)",
        "    ELSE",
        "      RES = ABS(A)",
        "    END IF",
        "  END FUNCTION oti_sign_ro",
        "  FUNCTION oti_nint(A) RESULT(RES)",
        "    IMPLICIT NONE",
        f"    TYPE({type_name}), INTENT(IN) :: A",
        "    INTEGER :: RES",
        "    RES = NINT(A%R)",
        "  END FUNCTION oti_nint",
        "  FUNCTION oti_int(A) RESULT(RES)",
        "    IMPLICIT NONE",
        f"    TYPE({type_name}), INTENT(IN) :: A",
        "    INTEGER :: RES",
        "    RES = INT(A%R)",
        "  END FUNCTION oti_int",
        "END MODULE oti_intrinsics",
        "",
    ]
    return "\n".join(lines)


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

oti_intrinsics.o: oti_intrinsics.f90 {module_name}.o master_parameters.o
\t$(FC) $(FCFLAGS) -c $<

umat_oti_lifted.o: umat_oti_lifted.f90 {module_name}.o oti_intrinsics.o
\t$(FC) $(FCFLAGS) -c $<

ps_driver.o: ps_driver.f90 umat_oti_lifted.o {module_name}.o
\t$(FC) $(FCFLAGS) -c $<

abaqus_stubs.o: abaqus_stubs.f90
\t$(FC) $(FCFLAGS) -c $<

ps_driver: master_parameters.o real_utils.o {module_name}.o oti_intrinsics.o umat_oti_lifted.o abaqus_stubs.o ps_driver.o
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
