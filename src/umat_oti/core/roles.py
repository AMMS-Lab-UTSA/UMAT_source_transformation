from __future__ import annotations

import re
from typing import Any


OTIS_ROLES = ("Seed", "Promote", "Constant", "Keep real", "Unknown")
ROUTINE_ROLES = (
    "Stress update",
    "State update",
    "Tangent only",
    "Utility",
    "External or unsupported",
    "Ignore",
    "Unknown",
)
HELPER_KINDS = ("Pure arithmetic helper", "Branch/control helper", "External/Abaqus helper", "Unknown")
ABAQUS_UTILITY_CALLS = {"SPRINC", "SINV", "ROTSIG", "GETVRM"}
PURE_ARITHMETIC_HELPERS = {"DOTPROD", "DYADICPROD", "KDEVIA", "KEFFP", "KINVER", "KMLT", "KMLT1", "KTRACE", "KTRANS"}

KEEP_REAL_NAMES = {
    "DDSDDE",
    "DDSDDT",
    "DRPLDE",
    "DRPLDT",
    "SSE",
    "SPD",
    "SCD",
    "RPL",
    "PNEWDT",
    "CELENT",
    "CMNAME",
    "NTENS",
    "NDI",
    "NSHR",
    "NSTATV",
    "NPROPS",
    "NOEL",
    "NPT",
    "LAYER",
    "KSPT",
    "KSTEP",
    "JSTEP",
    "KINC",
    "DFGRD0",
    "DFGRD1",
}
CONSTANT_NAMES = {
    "PROPS",
    "TIME",
    "DTIME",
    "TEMP",
    "DTEMP",
    "PREDEF",
    "DPRED",
    "COORDS",
    "DROT",
}
FINITE_STRAIN_CONSTANTS = {"DFGRD0", "DFGRD1"}
LOOP_COUNTER_NAMES = {"I", "J", "K", "K1", "K2", "K3", "L", "M", "N", "II", "JJ", "KK", "ITER", "IT", "COUNT"}


#: Fortran's own default: a name that is never declared takes its type from
#: its first letter, and I through N are INTEGER. Nearly every UMAT either
#: relies on that default or includes ABA_PARAM.INC, whose
#: ``implicit real*8(a-h,o-z)`` leaves the integer range exactly where the
#: default puts it.
_DEFAULT_IMPLICIT_INTEGER = frozenset("IJKLMN")

_IMPLICIT_STATEMENT = re.compile(
    r"^\s*IMPLICIT\s+(.*)$", re.IGNORECASE)
_IMPLICIT_SPEC = re.compile(
    r"(?P<type>[A-Z][A-Z0-9_*()\s]*?)\s*\((?P<letters>[^)]*)\)", re.IGNORECASE)



_COMMON_STATEMENT = re.compile(r"^\s*common\b(.*)$", re.IGNORECASE)


def common_block_names(source_text: str | None) -> frozenset[str]:
    """Names this source places in a COMMON block.

    A COMMON block is a storage layout agreed between routines. Promoting one
    of its names to the differentiated type changes that layout in the routine
    being transformed and in no other, so every routine sharing the block
    would then disagree with it about where its own variables are. The
    transformer already declares COMMON unsupported; this keeps a name that
    lives in one out of the differentiated set rather than promoting it and
    failing later for an unrelated-looking reason.

    Writing to such a name still works: the value is cast on the way out, the
    way STRESS and STATEV are. Reading one on the stress path is a real
    truncation, and the seed-consumption and structural-zero checks report it
    as one -- which is the honest answer, because the derivative genuinely
    does not flow through storage this transform cannot type.
    """
    if not source_text:
        return frozenset()
    names: set[str] = set()
    for line in source_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("c", "C", "*", "!")) and not stripped[:6].lower().startswith("common"):
            continue
        match = _COMMON_STATEMENT.match(stripped)
        if not match:
            continue
        # Strip the block names: COMMON /BLOCK/ A, B(3,4) and the blank form
        # COMMON // A both leave the variable list behind. A block boundary
        # separates names exactly as a comma does -- COMMON /X/ A, B /Y/ C
        # declares three -- so it is replaced by one.
        body = re.sub(r"/[^/]*/", ",", match.group(1))
        depth = 0
        current: list[str] = []
        for character in body:
            if character == "(":
                depth += 1
                continue
            if character == ")":
                depth = max(0, depth - 1)
                continue
            if depth:
                # Inside a dimension declarator: COMMON /BLK/ A(NELEM, NGAUSS)
                # declares its bounds here, and the comma between them is not
                # a separator between names.
                continue
            if character == ",":
                names.add("".join(current).strip().upper())
                current = []
                continue
            current.append(character)
        names.add("".join(current).strip().upper())
    return frozenset(name for name in names if name and name.isidentifier())


def implicit_integer_letters(source_text: str) -> frozenset[str]:
    """Which first letters make an undeclared name an INTEGER.

    A variable the source never declares is not untyped, and treating it as
    one is how an integer ends up promoted to a differentiated type: the
    Oxford-lineage crystal plasticity source computes ``IJ2 = I + J - 2`` and
    asks ``MOD(IJ2,2)``, and promoting IJ2 turns an integer parity test into
    an unsupported intrinsic on a derived type. Read the source's own IMPLICIT
    statements where it has them, and fall back to Fortran's default -- which
    is also what ABA_PARAM.INC's ``implicit real*8(a-h,o-z)`` leaves in place.
    """
    letters: set[str] = set()
    saw_specification = False
    for line in source_text.splitlines():
        if line[:1] in "Cc*!":
            continue
        match = _IMPLICIT_STATEMENT.match(line[6:] if len(line) > 6 else line)
        if not match:
            continue
        remainder = match.group(1)
        if remainder.strip().upper().startswith("NONE"):
            return frozenset()
        for spec in _IMPLICIT_SPEC.finditer(remainder):
            saw_specification = True
            is_integer = spec.group("type").strip().upper().startswith("INTEGER")
            for group in spec.group("letters").split(","):
                bounds = [b.strip().upper() for b in group.split("-")]
                if not bounds or not bounds[0]:
                    continue
                start = bounds[0][0]
                end = bounds[-1][0] if len(bounds) > 1 else start
                covered = {chr(c) for c in range(ord(start), ord(end) + 1)}
                if is_integer:
                    letters |= covered
                else:
                    letters -= covered
    if not saw_specification:
        return _DEFAULT_IMPLICIT_INTEGER
    # Letters no IMPLICIT statement mentioned keep the language default.
    mentioned: set[str] = set()
    for line in source_text.splitlines():
        match = _IMPLICIT_STATEMENT.match(line[6:] if len(line) > 6 else line)
        if match:
            for spec in _IMPLICIT_SPEC.finditer(match.group(1)):
                for group in spec.group("letters").split(","):
                    bounds = [b.strip().upper() for b in group.split("-")]
                    if bounds and bounds[0]:
                        start = bounds[0][0]
                        end = bounds[-1][0] if len(bounds) > 1 else start
                        mentioned |= {chr(c) for c in range(ord(start), ord(end) + 1)}
    return frozenset(letters | (_DEFAULT_IMPLICIT_INTEGER - mentioned))



#: Intrinsics that appear as ``NAME(...)``. A call is not a variable, and a
#: promoted intrinsic gets renamed like one: FLOAT(NSLPTL) became
#: FLOAT_OTI(NSLPTL), which is not declared anywhere and does not compile.
INTRINSIC_CALL_NAMES = frozenset({
    "ABS", "ACOS", "AIMAG", "AINT", "ANINT", "ASIN", "ATAN", "ATAN2", "COS",
    "COSH", "DABS", "DBLE", "DEXP", "DFLOAT", "DIM", "DLOG", "DMAX1", "DMIN1",
    "DSIGN", "DSQRT", "EXP", "FLOAT", "IABS", "IDINT", "IDNINT", "INT", "LOG",
    "LOG10", "MAX", "MAX0", "MAX1", "MIN", "MIN0", "MIN1", "MOD", "NINT",
    "REAL", "SIGN", "SIN", "SINH", "SQRT", "TAN", "TANH", "CMPLX", "CONJG",
})


def defined_function_names(source_text: str) -> frozenset[str]:
    """Names this source defines as FUNCTIONs. Calls, not arrays or variables."""
    try:
        from umat_oti.fortran.parser import (  # noqa: PLC0415
            logical_lines_from_text, parse_function_subprograms,
        )
        lines = logical_lines_from_text(source_text, "fixed")
        return frozenset(f.upper_name for f in parse_function_subprograms(lines))
    except Exception:
        return frozenset()



def suggest_variable_roles(analysis: dict[str, Any],
                           source_text: str | None = None) -> list[dict[str, object]]:
    """Classify each variable. ``source_text`` enables implicit-typing checks.

    Optional, and left out by callers that cannot supply it, because guessing
    the implicit rule would be worse than not applying it: a source declaring
    ``IMPLICIT REAL*8 (A-Z)`` has no implicit integers at all, and refusing to
    promote its real variables because their names begin with I would be a
    regression, not a fix.
    """
    return _suggest_variable_roles(analysis, source_text)


def _suggest_variable_roles(analysis: dict[str, Any],
                            source_text: str | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    variables = analysis.get("detected_variables", [])
    region_summary = analysis.get("region_summary", {})
    tangent_only_names = set(region_summary.get("tangent_only_variables", []))
    stress_path_names = set(region_summary.get("stress_path_variables", []))
    constant_names = set(region_summary.get("constant_variables", []))
    ignored_or_unused_names = set(region_summary.get("ignored_or_unused_variables", []))
    statev_path_names = set(region_summary.get("statev_path_variables", []))
    integer_letters = (implicit_integer_letters(source_text)
                       if source_text is not None else frozenset())
    not_variables = (INTRINSIC_CALL_NAMES | defined_function_names(source_text)
                     if source_text is not None else frozenset())
    common_names = common_block_names(source_text)
    helper_local_names = _pure_helper_local_variables(analysis)
    helper_output_names = _pure_helper_output_variables(analysis)
    plasticity = analysis.get("plasticity_indicators", {}) or {}
    plasticity_names = set(plasticity.get("variables", [])) if plasticity.get("is_plasticity_candidate") else set()
    for variable in variables:
        name = str(variable.get("variable_name", "")).upper()
        detected_type = str(variable.get("detected_type", "unknown"))
        usage = set(variable.get("detected_usage", []))
        role, notes = _suggest_role(
            name,
            detected_type,
            usage,
            variable,
            tangent_only_names,
            stress_path_names,
            constant_names,
            ignored_or_unused_names,
            plasticity_names,
            statev_path_names,
            helper_local_names,
            helper_output_names,
        )
        # The same escape hatch _is_implicitly_integer uses: an explicit
        # declaration always wins. A source may legally name a variable DIM or
        # AINT, and demoting a declared one would wrap it in REAL() and take
        # its derivative silently to zero.
        if (role in ("Promote", "Seed") and name in not_variables
                and str(detected_type or "").strip().lower() in ("", "unknown")
                and not str(variable.get("detected_shape") or "").strip()):
            role = "Keep real"
            notes = (
                f"{name} is a call, not a variable -- "
                + ("a Fortran intrinsic" if name in INTRINSIC_CALL_NAMES
                   else "a function this source defines")
                + ". Promoting it renames the call itself, and the renamed "
                  "name is declared nowhere."
            )
        elif role == "Promote" and "*" in str(variable.get("detected_shape") or ""):
            role = "Keep real"
            notes = (
                f"{name} is declared assumed-size, so this routine does not "
                "know its extent and neither does the transform. A shadow "
                "cannot be declared without one, and the initialisation loop "
                "written for it came out as DO OTI_HI = 1, *. The extent is "
                "the caller's, and guessing which other argument carries it "
                "would be inventing an interface this source does not state."
            )
        elif role == "Promote" and name in common_names:
            role = "Keep real"
            notes = (
                f"{name} lives in a COMMON block. Promoting it would change "
                "that block's storage layout in this routine and in no other, "
                "so every routine sharing it would disagree about where its "
                "own variables are. Values written to it are cast on the way "
                "out, as STRESS and STATEV are."
            )
        elif role in ("Promote", "Seed") and _is_implicitly_integer(
                name, detected_type, variable, integer_letters):
            role = "Keep real"
            notes = (
                f"Undeclared and implicitly INTEGER ({name[0]} is in the "
                "integer range for this source), so it carries no derivative "
                "and must not be promoted: an integer promoted to the "
                "differentiated type turns index and parity arithmetic into "
                "unsupported operations on a derived type."
            )
        rows.append(
            {
                "appears in UMAT arguments yes/no": "yes" if variable.get("appears_in_umat_arguments") else "no",
                "detected shape/dimension": variable.get("detected_shape", ""),
                "detected type": detected_type,
                "detected usage": ", ".join(sorted(usage)),
                "notes": notes,
                "read/write/unknown": variable.get("read_write", "unknown"),
                "suggested OTIS role": role,
                "user-selected OTIS role": role,
                "variable name": name,
            }
        )
    return sorted(rows, key=lambda row: str(row["variable name"]))


def suggest_routine_roles(analysis: dict[str, Any]) -> list[dict[str, object]]:
    defined = {str(row.get("name", "")).upper() for row in analysis.get("detected_subroutines", [])}
    calls = {str(row.get("callee", "")).upper() for row in analysis.get("calls", [])}
    names = sorted(defined | calls)
    effects = {
        str(row.get("name", "")).upper(): row
        for row in analysis.get("routine_effects", [])
    }
    stress_path_helpers = {str(row.get("callee", "")).upper() for row in analysis.get("stress_path_helpers", []) or []}
    rows: list[dict[str, object]] = []
    for name in names:
        role = "Unknown"
        notes = ""
        routine_effect = effects.get(name, {})
        arguments = {str(arg).upper() for arg in routine_effect.get("arguments", [])}
        helper_kind = _suggest_helper_kind(name, name in defined, routine_effect)
        if name in ABAQUS_UTILITY_CALLS:
            role = "Utility"
            notes = "Recognized Abaqus utility routine."
        elif name in PURE_ARITHMETIC_HELPERS and name in defined:
            if name in stress_path_helpers:
                role = "Stress update"
                notes = "Pure arithmetic helper on the DSTRAN to STRESS path; the transformer can inline/OTIS-overload it."
            else:
                role = "Utility"
                notes = "Pure arithmetic helper; transform if a promoted call path uses it."
        elif routine_effect.get("writes_stress") or ("STRESS" in name and "DDSDDE" not in name):
            role = "Stress update"
        elif routine_effect.get("writes_statev"):
            role = "State update"
        elif routine_effect.get("writes_ddsdde") or "DDSDDE" in name or "TANGENT" in name or "JAC" in name:
            role = "Tangent only"
        elif any(token in name for token in ("PRINT", "WRITE", "LOG", "DEBUG")):
            role = "Utility"
        elif name not in defined:
            role = "External or unsupported"
            notes = "Call target is not defined in the uploaded file."
        elif "STRESS" in arguments:
            role = "Stress update"
            notes = "Routine has a STRESS argument; verify whether it participates in the update path."
        elif "STATEV" in arguments:
            role = "State update"
        rows.append(
            {
                "helper_kind": helper_kind,
                "routine_name": name,
                "selected_role": role,
                "selected_helper_kind": helper_kind,
                "suggested_helper_kind": helper_kind,
                "suggested_role": role,
                "notes": notes,
            }
        )
    return rows


def _suggest_helper_kind(name: str, is_defined: bool, routine_effect: dict[str, Any]) -> str:
    if name in PURE_ARITHMETIC_HELPERS and is_defined:
        return "Pure arithmetic helper"
    if name in ABAQUS_UTILITY_CALLS or not is_defined or routine_effect.get("has_file_io"):
        return "External/Abaqus helper"
    if routine_effect.get("has_branch_control"):
        return "Branch/control helper"
    return "Unknown"


def apply_bulk_action(rows: list[dict[str, object]], action: str) -> list[dict[str, object]]:
    result = [dict(row) for row in rows]
    for row in result:
        name = str(row.get("variable name", "")).upper()
        detected_type = str(row.get("detected type", "")).lower()
        usage = str(row.get("detected usage", "")).lower()
        is_argument = str(row.get("appears in UMAT arguments yes/no", "no")).lower() == "yes"
        if action == "promote_local_real" and not is_argument and _is_real_type(detected_type):
            row["user-selected OTIS role"] = "Promote"
        elif action == "constant_props_derived" and "props-derived" in usage:
            row["user-selected OTIS role"] = "Constant"
        elif action == "keep_integer" and (_is_integer_type(detected_type) or name in LOOP_COUNTER_NAMES):
            row["user-selected OTIS role"] = "Keep real"
        elif action == "reset":
            row["user-selected OTIS role"] = row.get("suggested OTIS role", "Unknown")
    return result


def _is_implicitly_integer(name: str, detected_type: str, variable: dict[str, Any],
                           integer_letters: frozenset[str]) -> bool:
    """An undeclared name whose first letter makes it an INTEGER.

    Only undeclared names: an explicit declaration always wins, and a variable
    the scanner typed is not being guessed at here.
    """
    if not name or not integer_letters:
        return False
    if name[0].upper() not in integer_letters:
        return False
    if str(detected_type or "").strip().lower() not in ("", "unknown"):
        return False
    return not str(variable.get("detected_shape") or "").strip()



def role_summary(rows: list[dict[str, object]]) -> dict[str, list[str]]:
    summary = {
        "constant_variables": [],
        "keep_real_variables": [],
        "promoted_variables": [],
        "seed_variables": [],
        "unknown_variables": [],
    }
    target_by_role = {
        "Seed": "seed_variables",
        "Promote": "promoted_variables",
        "Constant": "constant_variables",
        "Keep real": "keep_real_variables",
        "Unknown": "unknown_variables",
    }
    for row in rows:
        role = str(row.get("user-selected OTIS role", "Unknown"))
        target = target_by_role.get(role, "unknown_variables")
        summary[target].append(str(row.get("variable name", "")).upper())
    return {key: sorted(set(value)) for key, value in summary.items()}


def _suggest_role(
    name: str,
    detected_type: str,
    usage: set[str],
    variable: dict[str, object],
    tangent_only_names: set[str],
    stress_path_names: set[str],
    constant_names: set[str],
    ignored_or_unused_names: set[str],
    plasticity_names: set[str],
    statev_path_names: set[str],
    helper_local_names: set[str],
    helper_output_names: set[str],
) -> tuple[str, str]:
    lowered_type = detected_type.lower()
    if name == "DSTRAN":
        return "Seed", "Jacobian mode seeds DSTRAN as the independent variable."
    if name == "STRESS":
        return "Promote", "STRESS is the dependent variable whose derivatives fill DDSDDE."
    if name == "DDSDDE":
        return "Keep real", "DDSDDE will later be overwritten by derivative extraction."
    if name == "STATEV":
        if str(variable.get("read_write", "")).find("write") >= 0:
            return "Promote", "STATEV is updated; promote for conservative derivative propagation review."
        return "Constant", "STATEV appears read-only in this scan."
    path_names = statev_path_names | stress_path_names | plasticity_names
    if _is_integer_type(lowered_type) or lowered_type.startswith("logical") or lowered_type.startswith("character"):
        return "Keep real", "Integer, logical, and character values do not carry OTIS derivatives."
    if _is_loop_counter(name):
        return "Keep real", "Loop/index variables do not carry OTIS derivatives."
    if name in KEEP_REAL_NAMES and name not in FINITE_STRAIN_CONSTANTS:
        return "Keep real", "Abaqus dimension, index, step, or tangent variable should remain real/integer."
    if name in FINITE_STRAIN_CONSTANTS and name in stress_path_names:
        return "Promote", "Finite-strain deformation-gradient input feeds STRESS and is copied into an OTIS shadow."
    if name in constant_names and name not in helper_output_names and not _depends_on_path(variable, path_names, constant_names):
        return "Constant", "Variable is deterministic setup/input data with zero DSTRAN derivative in this scan."
    if name in statev_path_names and name not in KEEP_REAL_NAMES and not _is_loop_counter(name) and not _is_integer_type(lowered_type):
        return "Promote", "Variable carries the STATEV read/update path and needs OTIS propagation."
    if name in stress_path_names and name != "DSTRAN":
        return "Promote", "Variable is on the executable DSTRAN to STRESS propagation path."
    if name in tangent_only_names:
        return "Keep real", "Detected only in the old tangent/Jacobian block; it can stay real or be removed from the transformed path later."
    if name in plasticity_names and name not in KEEP_REAL_NAMES and not _is_loop_counter(name) and not _is_integer_type(lowered_type):
        return "Promote", "Variable appears in detected plasticity/return-mapping logic and needs OTIS propagation review."
    if name in helper_local_names:
        return "Keep real", "Local dummy/work variable belongs only to a pure arithmetic helper; promoted call sites are inlined or overloaded separately."
    if name in ignored_or_unused_names:
        return "Keep real", "Bookkeeping, index, declaration-only, or unused optional Abaqus value."
    if name == "STRAN":
        if "stress-update-path" in usage:
            return "Promote", "STRAN appears on a detected stress-update dependency path."
        return "Constant", "STRAN is not detected as downstream of DSTRAN in this scan."
    if name in CONSTANT_NAMES:
        return "Constant", "Default fixed input with zero derivative for Jacobian mode."
    if name in FINITE_STRAIN_CONSTANTS:
        return "Constant", "Finite-strain deformation-gradient input is not on the selected STRESS path."
    if _is_real_type(lowered_type):
        if "stress-update-path" in usage:
            return "Promote", "Local real appears downstream of DSTRAN or on a stress-update path."
        if "props-derived" in usage:
            return "Constant", "Local real appears derived only from PROPS in this simple scan."
        return "Unknown", "Local floating-point variable needs user review."
    return "Unknown", "No deterministic role rule matched this variable."


def _is_real_type(detected_type: str) -> bool:
    return bool(re.match(r"\s*(real|double\s+precision)", detected_type, flags=re.IGNORECASE))


def _is_integer_type(detected_type: str) -> bool:
    return bool(re.match(r"\s*integer", detected_type, flags=re.IGNORECASE))


def _is_loop_counter(name: str) -> bool:
    return name in LOOP_COUNTER_NAMES or bool(re.match(r"^[IJKLMN]\d+$", name))


def _pure_helper_local_variables(analysis: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for variable in analysis.get("detected_variables", []) or []:
        name = str(variable.get("variable_name", "")).upper()
        routines = {str(routine).upper() for routine in variable.get("routines", []) or []}
        if routines and routines <= PURE_ARITHMETIC_HELPERS:
            result.add(name)
    return result


def _pure_helper_output_variables(analysis: dict[str, Any]) -> set[str]:
    output_index = {"DOTPROD": 2, "DYADICPROD": 2, "KDEVIA": 2, "KEFFP": 1, "KINVER": 1, "KMLT": 2, "KMLT1": 2, "KTRACE": 1, "KTRANS": 1}
    outputs: set[str] = set()
    for call in analysis.get("calls", []) or []:
        callee = str(call.get("callee", "")).upper()
        index = output_index.get(callee)
        arguments = list(call.get("arguments", []) or [])
        if index is None or index >= len(arguments):
            continue
        match = re.match(r"\s*([A-Za-z_]\w*)", str(arguments[index]))
        if match:
            outputs.add(match.group(1).upper())
    return outputs


def _depends_on_path(variable: dict[str, object], path_names: set[str], constant_names: set[str]) -> bool:
    assigned_from = {str(value).upper() for value in variable.get("assigned_from", []) or []}
    if not assigned_from:
        return False
    own_name = str(variable.get("variable_name", "")).upper()
    dynamic_dependencies = assigned_from - {own_name} - constant_names
    return bool(dynamic_dependencies & path_names)
