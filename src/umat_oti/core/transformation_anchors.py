from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from umat_oti.core.roles import INTRINSIC_CALL_NAMES, assigned_names
from umat_oti.fortran.normalize import detect_source_form
from umat_oti.fortran.parser import logical_lines_from_text
from umat_oti.fortran.regions import TRANSFORMABLE_HELPER_EFFECTS


ANCHOR_SCHEMA_VERSION = 1
FILE_IO_ACTIONS = (
    "keep_real_side_effect",
    "initialization_only_keep",
    "remove_from_transformed_path",
    "unsafe_block",
    "user_review_required",
)
TANGENT_REGION_ROLES = (
    "tangent_helper_skip_only",
    "ddsdde_output_replace",
    "keep_real_required_by_stress_update",
    "validation_only_ignore",
    "user_review_required",
)
COMPLETED_KEEP_REAL_ARGUMENT_NAMES = {"IFLAG", "NUMFIELDV", "NVALUE"}


def build_transformation_anchors(config: dict[str, Any], source_text: str = "") -> dict[str, Any]:
    analysis = _dict(config.get("analysis"))
    review = _dict(config.get("transformation_review"))
    mappings = _mapping(config)
    helper_dependency_names = _stress_helper_dependency_names(review, mappings)
    selected_umat = _selected_umat(config, analysis)
    umat_span = _selected_umat_span(analysis, selected_umat)
    source_lines = source_text.splitlines()
    source_line_count = len(source_lines)
    logical_statement_spans = _logical_statement_spans(config, source_text)

    raw_stress = _expand_regions_to_logical_statements(
        _region_rows(review.get("stress_update_regions_to_transform", [])),
        logical_statement_spans,
        source_lines,
        umat_span,
    )
    raw_tangent = _expand_regions_to_logical_statements(
        _region_rows(review.get("old_tangent_regions_to_replace", [])),
        logical_statement_spans,
        source_lines,
        umat_span,
    )
    raw_shared = _expand_regions_to_logical_statements(
        _region_rows(review.get("shared_setup_regions_to_keep", [])),
        logical_statement_spans,
        source_lines,
        umat_span,
    )

    stress_regions = [_with_role(region, "transform_with_oti") for region in _within_span(raw_stress, umat_span)]
    if not stress_regions:
        stress_regions = _infer_helper_call_stress_regions(analysis, source_lines, umat_span, mappings)
    stress_regions = _augment_stress_regions_with_helper_calls(
        analysis,
        source_lines,
        umat_span,
        stress_regions,
        logical_statement_spans,
        helper_dependency_names,
    )
    stress_regions = _expand_regions_to_logical_statements(stress_regions, logical_statement_spans, source_lines, umat_span)

    first_stress_start = min((_as_int(region.get("start_line")) for region in stress_regions), default=0)
    last_stress_end = max((_as_int(region.get("end_line")) for region in stress_regions), default=0)

    tangent_in_umat = _within_span(raw_tangent, umat_span)
    helper_regions: list[dict[str, Any]] = []
    output_regions: list[dict[str, Any]] = []
    shared_regions = [_with_role(region, "keep_real") for region in _within_span(raw_shared, umat_span)]
    for region in tangent_in_umat:
        direct_ddsdde = _region_directly_assigns_ddsdde(region, analysis)
        if direct_ddsdde and first_stress_start and _as_int(region.get("end_line")) < first_stress_start:
            shared_regions.append(
                _expand_keep_real_required_region(
                    source_lines,
                    _with_role(region, "keep_real_required_by_stress_update"),
                    umat_span,
                )
            )
            continue
        if direct_ddsdde:
            # A consistent tangent may be written as several separate DDSDDE
            # assignments (e.g. an elastic-like block built in DO loops followed
            # by a correction term). Replace ALL of them, not just the last,
            # otherwise the earlier assignments are left uncovered and block the
            # transform.
            output_regions.append(_with_role(region, "ddsdde_output_replace"))
            continue
        role = "tangent_helper_skip_only"
        if "validation" in str(region.get("classification", "")).lower():
            role = "validation_only_ignore"
        helper_regions.append(_with_role(region, role))

    ddsdde_keep_regions = _ddsdde_setup_regions_before_stress(analysis, source_lines, first_stress_start, umat_span, source_line_count)
    for region in ddsdde_keep_regions:
        if not _same_span_exists(region, shared_regions):
            shared_regions.append(region)
    helper_regions = [
        region
        for region in helper_regions
        if not any(
            shared.get("role") == "keep_real_required_by_stress_update" and _regions_overlap(region, shared)
            for shared in shared_regions
        )
    ]

    # Primary output region (the last one) drives the GETIM insertion point.
    output_region = max(output_regions, key=lambda r: _as_int(r.get("end_line"))) if output_regions else None
    if output_region is None:
        output_region = _infer_ddsdde_output_region(analysis, first_stress_start, last_stress_end, umat_span, source_line_count)
        if output_region:
            output_regions = [output_region]

    ddsdde_insert_after = _post_output_insert_line(source_lines, output_region) or last_stress_end
    real_output_line = _real_output_insert_after_line(source_lines, stress_regions, mappings)
    real_insert_after = _branch_safe_real_output_insert_after_line(source_lines, real_output_line, output_region) or real_output_line or last_stress_end or ddsdde_insert_after
    ddsdde_insert_after = max(ddsdde_insert_after, real_insert_after)
    # Never inside a loop the stress update runs in. Both extractions are
    # moved past the outermost enclosing DO, together, so the real copy and
    # the tangent stay in the order the semantic checks require.
    # After every CALL that could write DDSDDE, for the same reason it goes
    # after the last direct assignment: whatever writes the old tangent last
    # is what the extraction has to overwrite.
    for call_line in _ddsdde_writing_call_lines(config, source_text, umat_span):
        ddsdde_insert_after = max(ddsdde_insert_after, call_line)
    for candidate in (real_insert_after, ddsdde_insert_after):
        loop_end = _enclosing_do_end(source_lines, candidate, umat_span)
        if loop_end:
            real_insert_after = max(real_insert_after, loop_end)
            ddsdde_insert_after = max(ddsdde_insert_after, loop_end)
    seed_line_before = first_stress_start or _first_executable_line_in_span(source_lines, umat_span)
    finite_seed_line = _first_finite_strain_use_line(analysis, umat_span)
    if finite_seed_line:
        first_executable = _first_executable_line_in_span(source_lines, umat_span)
        seed_line_before = min(value for value in (seed_line_before, finite_seed_line, first_executable) if value)

    completion_issues: list[dict[str, Any]] = []
    # Asked before anything else, and returned alone when it fires. Every
    # anchor below is a place inside the Abaqus UMAT interface; if the routine
    # does not have that interface there is no such place, and listing four
    # missing anchors describes the consequence while leaving the cause unsaid.
    not_a_umat = _not_an_abaqus_umat_issue(analysis, mappings, selected_umat)
    if not_a_umat is not None:
        completion_issues.append(not_a_umat)
    elif not stress_regions:
        completion_issues.append(
            {
                "kind": "missing_stress_update_region",
                "message": "Select the executable DSTRAN/state/input to STRESS update lines.",
                "required_json_field": "transformation_anchors.stress_update.regions",
            }
        )
    if _assignments_to_ddsdde_in_span(analysis, umat_span) and not (output_region or shared_regions):
        completion_issues.append(
            {
                "kind": "missing_ddsdde_decision",
                "message": "Classify DDSDDE assignments as output replacement, keep-real setup, skip-only helper, validation-only, or unsafe.",
                "required_json_field": "transformation_anchors.old_tangent",
            }
        )
    if _assignments_to_ddsdde_in_span(analysis, umat_span) and not ddsdde_insert_after:
        completion_issues.append(
            {
                "kind": "missing_ddsdde_extraction_point",
                "message": "Choose where the GETIM DDSDDE extraction must be inserted.",
                "required_json_field": "transformation_anchors.ddsdde_extraction",
            }
        )

    file_io_regions = _file_io_regions(analysis, source_lines, umat_span, stress_regions)
    for row in file_io_regions:
        if row.get("action") == "user_review_required":
            completion_issues.append(
                {
                    "kind": "unclassified_file_io",
                    "message": f"Classify file I/O at lines {row.get('line_numbers', [])}.",
                    "required_json_field": "transformation_anchors.file_io_regions",
                }
            )

    status = "ready_with_json_contract" if not completion_issues else "needs_json_completion"
    return {
        "schema_version": ANCHOR_SCHEMA_VERSION,
        "status": status,
        "completion_issues": completion_issues,
        "selected_umat": selected_umat,
        "selected_umat_span": {"start_line": umat_span[0], "end_line": umat_span[1]},
        "seed_insertion": {
            "line_before": seed_line_before,
            "reason": "Insert OTIS shadow initialization before the first user-confirmed stress-update line.",
        },
        "stress_update": {
            "regions": stress_regions,
            "reason": "Explicit source lines to transform with OTIS roles; generated from detected/user-selected regions and UMAT-local helper-call stress updates.",
        },
        "old_tangent": {
            "helper_regions": helper_regions,
            "output_region": output_region or {},
            "output_regions": output_regions,
            "reason": "Explicit DDSDDE-region contract. Helper regions are skipped only when the role says skip_only; keep-real setup is preserved.",
        },
        "tangent_helper_regions_to_skip": helper_regions,
        "shared_setup_regions_to_keep": shared_regions,
        "real_output_extraction": {
            "insert_after_line": real_insert_after,
            "reason": "Copy real STRESS/STATEV after the last transformed stress update.",
        },
        "ddsdde_extraction": {
            "insert_at_region": str((output_region or {}).get("region_id", "")),
            "insert_after_line": ddsdde_insert_after,
            "reason": "Insert GETIM DDSDDE extraction at the explicit old tangent output region or after the stress update when DDSDDE setup is kept real.",
        },
        "statev_read_regions": _statev_regions(analysis, "reads", umat_span, source_lines),
        "statev_write_regions": _statev_regions(analysis, "writes", umat_span, source_lines),
        "file_io_regions": file_io_regions,
        "branch_regions": _branch_regions(analysis, umat_span),
        "helper_call_regions": _helper_call_regions(analysis, stress_regions, umat_span),
    }


def merge_completed_anchors_into_config(config: dict[str, Any], source_text: str = "") -> dict[str, Any]:
    updated = dict(config)
    anchors = build_transformation_anchors(updated, source_text)
    updated["transformation_anchors"] = anchors
    review = dict(_dict(updated.get("transformation_review")))
    review["stress_update_regions_to_transform"] = anchors.get("stress_update", {}).get("regions", [])
    old_tangent = []
    output_regions = anchors.get("old_tangent", {}).get("output_regions") or []
    old_tangent.extend([r for r in output_regions if isinstance(r, dict) and r])
    if not old_tangent:
        output_region = anchors.get("old_tangent", {}).get("output_region", {})
        if isinstance(output_region, dict) and output_region:
            old_tangent.append(output_region)
    old_tangent.extend(anchors.get("old_tangent", {}).get("helper_regions", []) or [])
    review["old_tangent_regions_to_replace"] = old_tangent
    review["tangent_helper_regions_to_skip"] = anchors.get("old_tangent", {}).get("helper_regions", [])
    review["shared_setup_regions_to_keep"] = anchors.get("shared_setup_regions_to_keep", [])
    review["completion_status"] = anchors.get("status", "needs_json_completion")
    review["completion_issues"] = anchors.get("completion_issues", [])
    normalized_roles = _finalize_completed_variable_roles(
        updated.get("variable_roles", {}), anchors, source_text)
    updated["variable_roles"] = normalized_roles
    review.update(_review_role_lists(normalized_roles))
    review["ready_for_transformation"] = anchors.get("status") == "ready_with_json_contract" and not review.get("action_needed")
    updated["transformation_review"] = review
    updated["validation_settings"] = _validation_settings(updated)
    updated["transformation_anchors"] = {**anchors, "status": anchor_completion_status(updated)["status"], "completion_issues": anchor_completion_status(updated)["completion_issues"]}
    return updated


def _finalize_completed_variable_roles(
    raw_roles: Any, anchors: dict[str, Any], source_text: str = "",
) -> Any:
    updated = _promote_anchor_stress_variables(raw_roles, anchors)
    updated = _normalize_intrinsic_variable_roles(updated, source_text)
    return _normalize_completed_keep_real_roles(updated)


def _review_role_lists(raw_roles: Any) -> dict[str, list[str]]:
    if not isinstance(raw_roles, dict):
        return {}
    role_lists = {
        "seed_variables": set(),
        "promoted_variables": set(),
        "constant_variables": set(),
        "keep_real_variables": set(),
    }
    role_map = {
        "Seed": "seed_variables",
        "Promote": "promoted_variables",
        "Constant": "constant_variables",
        "Keep real": "keep_real_variables",
    }
    for name, row in raw_roles.items():
        if not isinstance(row, dict):
            continue
        target = role_map.get(str(row.get("selected_role", "")))
        if target:
            role_lists[target].add(str(name).upper())
    return {key: sorted(values) for key, values in role_lists.items()}


def anchor_completion_status(config: dict[str, Any]) -> dict[str, Any]:
    anchors = _dict(config.get("transformation_anchors"))
    if not anchors:
        return {
            "status": "needs_json_completion",
            "completion_issues": [
                {
                    "kind": "missing_transformation_anchors",
                    "message": "Configuration does not contain a completed transformation_anchors contract.",
                    "required_json_field": "transformation_anchors",
                }
            ],
        }
    issues = [dict(row) for row in anchors.get("completion_issues", []) if isinstance(row, dict)]
    # One issue answers all the others. Every required field below names a
    # place inside the Abaqus UMAT interface, and a routine that does not have
    # that interface is missing all of them for one reason. Reporting the
    # reason alone is the whole point of detecting it.
    not_a_umat = next(
        (row for row in issues
         if row.get("kind") == "selected_routine_is_not_an_abaqus_umat"), None)
    if not_a_umat is not None:
        return {"status": "needs_json_completion", "completion_issues": [not_a_umat]}
    issues.extend(_required_contract_issues(config, anchors))
    status = "needs_json_completion" if issues else str(anchors.get("status") or "ready_with_json_contract")
    return {"status": status, "completion_issues": issues}


def _required_contract_issues(config: dict[str, Any], anchors: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    review = _dict(config.get("transformation_review"))
    for field in ("seed_variables", "promoted_variables", "constant_variables", "keep_real_variables"):
        if field not in review or not isinstance(review.get(field), list):
            issues.append(_missing_contract_issue(f"missing_{field}", f"transformation_review.{field}"))
    if not review.get("seed_variables"):
        issues.append(_missing_contract_issue("missing_seed_variables", "transformation_review.seed_variables"))
    if not review.get("promoted_variables"):
        issues.append(_missing_contract_issue("missing_promoted_variables", "transformation_review.promoted_variables"))

    if _as_int(_dict(anchors.get("seed_insertion")).get("line_before")) <= 0:
        issues.append(_missing_contract_issue("missing_seed_insertion_point", "transformation_anchors.seed_insertion.line_before"))
    if not _dict(anchors.get("stress_update")).get("regions"):
        issues.append(_missing_contract_issue("missing_stress_update_regions", "transformation_anchors.stress_update.regions"))
    if "shared_setup_regions_to_keep" not in anchors or not isinstance(anchors.get("shared_setup_regions_to_keep"), list):
        issues.append(_missing_contract_issue("missing_shared_setup_regions", "transformation_anchors.shared_setup_regions_to_keep"))
    old_tangent = _dict(anchors.get("old_tangent"))
    if "helper_regions" not in old_tangent or not isinstance(old_tangent.get("helper_regions"), list):
        issues.append(_missing_contract_issue("missing_tangent_helper_regions", "transformation_anchors.old_tangent.helper_regions"))
    if "output_region" not in old_tangent or not isinstance(old_tangent.get("output_region"), dict):
        issues.append(_missing_contract_issue("missing_ddsdde_output_region_decision", "transformation_anchors.old_tangent.output_region"))
    if _as_int(_dict(anchors.get("real_output_extraction")).get("insert_after_line")) <= 0:
        issues.append(_missing_contract_issue("missing_real_output_extraction_point", "transformation_anchors.real_output_extraction.insert_after_line"))
    if _as_int(_dict(anchors.get("ddsdde_extraction")).get("insert_after_line")) <= 0:
        issues.append(_missing_contract_issue("missing_ddsdde_extraction_point", "transformation_anchors.ddsdde_extraction.insert_after_line"))
    if "file_io_regions" not in anchors or not isinstance(anchors.get("file_io_regions"), list):
        issues.append(_missing_contract_issue("missing_file_io_decisions", "transformation_anchors.file_io_regions"))

    validation_settings = _dict(config.get("validation_settings"))
    if not validation_settings:
        issues.append(_missing_contract_issue("missing_validation_settings", "validation_settings"))
    elif not validation_settings.get("material_test_mode"):
        issues.append(_missing_contract_issue("missing_validation_material_test_mode", "validation_settings.material_test_mode"))
    return issues


def _missing_contract_issue(kind: str, field: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "message": f"Completed transformation JSON must define {field}.",
        "required_json_field": field,
    }


def _validation_settings(config: dict[str, Any]) -> dict[str, Any]:
    existing = _dict(config.get("validation_settings"))
    if existing:
        return existing
    material_test_mode = _material_test_mode(config)
    analysis = _dict(config.get("analysis"))
    plastic = _dict(analysis.get("plasticity_indicators"))
    finite = _dict(analysis.get("finite_strain"))
    return {
        "enabled": True,
        "material_test_mode": material_test_mode,
        "jacobian_contract": "DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)",
        "compare_outputs": ["STRESS", "STATEV", "DDSDDE", "convergence"],
        "expected_plasticity": bool(plastic.get("is_plasticity_candidate")),
        "finite_strain": bool(finite.get("dfgrd_driven_stress_update") or finite.get("executable_dfgrd_use")),
    }


def _material_test_mode(config: dict[str, Any]) -> str:
    analysis = _dict(config.get("analysis"))
    finite = _dict(analysis.get("finite_strain"))
    plastic = _dict(analysis.get("plasticity_indicators"))
    if plastic.get("is_plasticity_candidate") and finite.get("executable_dfgrd_use"):
        return "single element plastic finite strain tension"
    if plastic.get("is_plasticity_candidate"):
        return "single element plastic tension"
    if finite.get("executable_dfgrd_use"):
        return "single element plastic finite strain tension"
    return "single element tension"


def _selected_umat(config: dict[str, Any], analysis: dict[str, Any]) -> str:
    source = _dict(config.get("source"))
    selected = str(source.get("selected_umat_name") or source.get("detected_umat_name") or "").upper()
    if selected:
        return selected
    for routine in analysis.get("detected_umat_routines", []) or analysis.get("detected_subroutines", []):
        name = str(routine.get("name", "")).upper()
        if name == "UMAT":
            return name
    routines = analysis.get("detected_subroutines", [])
    return str(routines[0].get("name", "UMAT")).upper() if routines else "UMAT"


def _selected_routine_arguments(
    analysis: dict[str, Any], selected_umat: str
) -> tuple[str, ...] | None:
    """The selected routine's dummy argument names, or None if it was not found."""
    target = (selected_umat or "UMAT").upper()
    for routine in analysis.get("detected_subroutines", []) or []:
        if str(routine.get("name", "")).upper() == target:
            return tuple(str(name).upper() for name in (routine.get("arguments") or []))
    return None


def _not_an_abaqus_umat_issue(
    analysis: dict[str, Any], mappings: dict[str, str], selected_umat: str
) -> dict[str, Any] | None:
    """The routine carries the UMAT name but not the UMAT interface.

    Abaqus calls a UMAT with one fixed argument list, and the contract is
    written against two of its arrays. A file can hold a routine named UMAT
    that is something else entirely -- a four-argument demonstration routine
    called from a ``program`` in the same file is one -- and there the anchor
    search reports four missing anchors, each true and none of them the
    reason. Fires only when the routine receives neither output, so a UMAT
    whose delegate spells the arguments differently is not caught by it.
    """
    arguments = _selected_routine_arguments(analysis, selected_umat)
    if arguments is None:
        return None
    stress = str(mappings.get("stress") or "STRESS").upper()
    ddsdde = str(mappings.get("ddsdde") or "DDSDDE").upper()
    if stress in arguments or ddsdde in arguments:
        return None
    return {
        "kind": "selected_routine_is_not_an_abaqus_umat",
        "message": (
            f"SUBROUTINE {(selected_umat or 'UMAT').upper()} is declared as "
            f"({', '.join(arguments)}) and receives neither {stress} nor "
            f"{ddsdde}. That is not the argument list Abaqus calls a UMAT "
            "with, so this routine has no stress or tangent output for the "
            "transform to write into."
        ),
        "required_json_field": "source.selected_umat_name",
    }


def _selected_umat_span(analysis: dict[str, Any], selected_umat: str) -> tuple[int, int]:
    for routine in analysis.get("detected_subroutines", []) or []:
        if str(routine.get("name", "")).upper() != selected_umat.upper():
            continue
        numbers = routine.get("line_numbers", []) or []
        if len(numbers) >= 2:
            return _as_int(numbers[0]), _as_int(numbers[-1])
    return 1, 10**9


def _region_rows(rows: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        start = _as_int(row.get("start_line") or row.get("start line"))
        end = _as_int(row.get("end_line") or row.get("end line"))
        if not start or not end:
            continue
        result.append(
            {
                "region_id": str(row.get("region_id") or row.get("region id") or ""),
                "start_line": start,
                "end_line": end,
                "role": str(row.get("role", "")),
                "classification": str(row.get("classification") or row.get("user-selected classification") or row.get("selected_classification") or ""),
                "variables": _upper_list(row.get("variables") or row.get("detected variables") or row.get("detected_variables") or []),
                "reason": str(row.get("reason") or row.get("detected reason") or row.get("detected_reason") or ""),
                "preview": str(row.get("preview") or row.get("short code preview") or ""),
            }
        )
    return result


def _within_span(regions: list[dict[str, Any]], span: tuple[int, int]) -> list[dict[str, Any]]:
    start, end = span
    return [region for region in regions if start <= _as_int(region.get("start_line")) and _as_int(region.get("end_line")) <= end]


def _with_role(region: dict[str, Any], role: str) -> dict[str, Any]:
    updated = dict(region)
    updated["role"] = role
    if role == "transform_with_oti":
        updated["classification"] = updated.get("classification") or "Main stress update, transform with OTIS"
    elif role == "ddsdde_output_replace":
        updated["classification"] = "DDSDDE output replacement, replace with GETIM extraction"
    elif role == "tangent_helper_skip_only":
        updated["classification"] = "Tangent helper skip only"
    elif role == "keep_real_required_by_stress_update":
        updated["classification"] = "DDSDDE setup required by stress update, keep real"
    return updated


def _infer_helper_call_stress_regions(
    analysis: dict[str, Any],
    source_lines: list[str],
    span: tuple[int, int],
    mappings: dict[str, str],
) -> list[dict[str, Any]]:
    stress = mappings.get("stress", "STRESS")
    dstran = mappings.get("dstran", "DSTRAN")
    candidates: list[int] = []
    variables: set[str] = {stress, dstran}
    for call in analysis.get("calls", []) or analysis.get("detected_calls", []) or []:
        if not isinstance(call, dict):
            continue
        lines = [_as_int(value) for value in call.get("line_numbers", []) or [] if _as_int(value)]
        if not lines or not all(span[0] <= line <= span[1] for line in lines):
            continue
        arguments = [str(argument).upper() for argument in call.get("arguments", []) or []]
        callee = str(call.get("callee", "")).upper()
        if stress in arguments or dstran in arguments or callee in {"KUPDVEC", "KMAVEC"}:
            candidates.extend(lines)
            variables.update(_base_names(arguments))
    for use in _uses_in_span(analysis, dstran, span):
        candidates.extend(use.get("line_numbers", []) or [])
    if candidates:
        start_hint = min(_as_int(value) for value in candidates if _as_int(value))
        for line_number in range(max(span[0], start_hint - 16), min(span[1], start_hint) + 1):
            if line_number - 1 >= len(source_lines):
                continue
            if dstran in _tokens(source_lines[line_number - 1]):
                candidates.append(line_number)
                variables.update(_tokens(source_lines[line_number - 1]))
    if not candidates:
        return []
    start = max(span[0], min(candidates))
    end = min(span[1], max(candidates))
    for line_number in range(start, end + 1):
        if line_number - 1 >= len(source_lines):
            continue
        variables.update(_tokens(source_lines[line_number - 1]))
    region = {
        "region_id": "USER-STRESS-HELPER-CALLS",
        "start_line": start,
        "end_line": end,
        "role": "transform_with_oti",
        "classification": "Main stress update, transform with OTIS",
        "variables": sorted(variable for variable in variables if variable and not _is_passive_name(variable)),
        "reason": "UMAT-local helper call updates STRESS from DSTRAN-derived data; selected as explicit stress update anchor.",
        "preview": _preview(source_lines, start, end),
    }
    return [region]


def _augment_stress_regions_with_helper_calls(
    analysis: dict[str, Any],
    source_lines: list[str],
    span: tuple[int, int],
    stress_regions: list[dict[str, Any]],
    logical_statement_spans: dict[int, tuple[int, int]],
    helper_dependency_names: set[str],
) -> list[dict[str, Any]]:
    updated = list(stress_regions)
    calls = analysis.get("stress_path_helpers", []) or analysis.get("calls", []) or analysis.get("detected_calls", []) or []
    call_rows_by_line = _helper_call_rows_by_line(calls, logical_statement_spans)
    helper_index = 1
    for row in calls:
        if not isinstance(row, dict):
            continue
        line_numbers = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        if not line_numbers or not (span[0] <= min(line_numbers) <= span[1]):
            continue
        start_line = min(line_numbers)
        end_line = max(line_numbers)
        for line_number in line_numbers:
            statement_span = logical_statement_spans.get(line_number)
            if not statement_span:
                continue
            start_line = min(start_line, statement_span[0])
            end_line = max(end_line, statement_span[1])
        start_line = _expand_helper_call_dependency_start(
            source_lines,
            start_line,
            span,
            row,
            helper_dependency_names,
            call_rows_by_line,
            logical_statement_spans,
        )
        variables = _base_names([str(argument) for argument in row.get("arguments", []) or []])
        for line_number in range(start_line, end_line + 1):
            if line_number - 1 >= len(source_lines):
                continue
            variables.update(name for name in _tokens(source_lines[line_number - 1]) if not _is_passive_name(name))
        overlap_indexes = [index for index, region in enumerate(updated) if _line_numbers_intersect(line_numbers, [region])]
        if overlap_indexes:
            for index in overlap_indexes:
                existing = dict(updated[index])
                merged_start = min(_as_int(existing.get("start_line")), start_line)
                merged_end = max(_as_int(existing.get("end_line")), end_line)
                existing_variables = set(str(value).upper() for value in existing.get("variables", []) or [] if str(value))
                existing_variables.update(variables)
                existing["start_line"] = merged_start
                existing["end_line"] = merged_end
                if existing_variables:
                    existing["variables"] = sorted(existing_variables)
                existing["preview"] = _preview(source_lines, merged_start, merged_end)
                updated[index] = existing
            continue
        updated.append(
            {
                "region_id": f"STRESS-HELPER-CALL-{helper_index:03d}",
                "start_line": start_line,
                "end_line": end_line,
                "role": "transform_with_oti",
                "classification": "Main stress update helper call, transform with OTIS",
                "variables": sorted(variable for variable in variables if variable and not _is_passive_name(variable)),
                "reason": "Completed transformation anchors expanded the stress path to include a UMAT-local helper call and its continued argument lines.",
                "preview": _preview(source_lines, start_line, end_line),
            }
        )
        helper_index += 1
    return sorted(updated, key=lambda region: (_as_int(region.get("start_line")), _as_int(region.get("end_line")), str(region.get("region_id", ""))))


def _logical_statement_spans(config: dict[str, Any], source_text: str) -> dict[int, tuple[int, int]]:
    if not source_text:
        return {}
    form = detect_source_form(Path(_source_file(config)), source_text)
    result: dict[int, tuple[int, int]] = {}
    for logical_line in logical_lines_from_text(source_text, form):
        if not logical_line.line_numbers:
            continue
        span = (min(logical_line.line_numbers), max(logical_line.line_numbers))
        for line_number in logical_line.line_numbers:
            result[line_number] = span
    return result


def _expand_regions_to_logical_statements(
    regions: list[dict[str, Any]],
    logical_statement_spans: dict[int, tuple[int, int]],
    source_lines: list[str],
    span: tuple[int, int],
) -> list[dict[str, Any]]:
    expanded_regions: list[dict[str, Any]] = []
    for region in regions:
        start_line = _as_int(region.get("start_line"))
        end_line = _as_int(region.get("end_line"))
        if start_line <= 0 or end_line <= 0:
            expanded_regions.append(region)
            continue
        expanded_start = start_line
        expanded_end = end_line
        for line_number in range(start_line, end_line + 1):
            statement_span = logical_statement_spans.get(line_number)
            if not statement_span:
                continue
            expanded_start = min(expanded_start, statement_span[0])
            expanded_end = max(expanded_end, statement_span[1])
        expanded_start = max(span[0], expanded_start)
        expanded_end = min(span[1], expanded_end)
        if expanded_end < expanded_start:
            # Clamping is right for a region that straddles the routine
            # boundary and wrong for one that lies wholly outside it: the two
            # bounds then cross, and the result is not a small region but an
            # impossible one. A file holding a UEL above its UMAT produced
            # (379, 250) this way -- start pulled up to the UMAT's first line,
            # end left in the element routine. Nothing downstream reads such a
            # span as empty. _line_numbers_intersect matched calls against it,
            # so KGPOINTS3X3 and KSTDM were harvested as stress-path helpers
            # from a routine that is not being transformed, and UMAT itself
            # was harvested from the UEL's call to it -- which is how the
            # lifter came to demand a source definition for the very routine
            # it was transforming, on fourteen sources.
            continue
        updated = dict(region)
        updated["start_line"] = expanded_start
        updated["end_line"] = expanded_end
        variables = set(str(value).upper() for value in updated.get("variables", []) or [] if str(value))
        for line_number in range(expanded_start, expanded_end + 1):
            if line_number - 1 >= len(source_lines):
                continue
            variables.update(name for name in _tokens(source_lines[line_number - 1]) if not _is_passive_name(name))
        if variables:
            updated["variables"] = sorted(variables)
        updated["preview"] = _preview(source_lines, expanded_start, expanded_end)
        expanded_regions.append(updated)
    return expanded_regions


def _stress_helper_dependency_names(review: dict[str, Any], mappings: dict[str, str]) -> set[str]:
    names = set(_upper_list(review.get("promoted_variables", [])))
    names.discard(mappings.get("stress", ""))
    names.discard(mappings.get("statev", ""))
    return {name for name in names if name and not _is_passive_name(name)}


def _helper_call_rows_by_line(
    calls: list[dict[str, Any]],
    logical_statement_spans: dict[int, tuple[int, int]],
) -> dict[int, dict[str, Any]]:
    rows_by_line: dict[int, dict[str, Any]] = {}
    for row in calls:
        if not isinstance(row, dict):
            continue
        line_numbers = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        for line_number in line_numbers:
            rows_by_line[line_number] = row
            statement_span = logical_statement_spans.get(line_number)
            if not statement_span:
                continue
            for statement_line in range(statement_span[0], statement_span[1] + 1):
                rows_by_line.setdefault(statement_line, row)
    return rows_by_line


def _expand_helper_call_dependency_start(
    source_lines: list[str],
    start_line: int,
    span: tuple[int, int],
    helper_call: dict[str, Any],
    helper_dependency_names: set[str],
    call_rows_by_line: dict[int, dict[str, Any]],
    logical_statement_spans: dict[int, tuple[int, int]],
) -> int:
    pending = _helper_argument_dependency_names(helper_call, "inputs", helper_dependency_names)
    if not pending:
        return start_line
    earliest = start_line
    for line_number in range(start_line - 1, span[0] - 1, -1):
        if line_number - 1 >= len(source_lines):
            continue
        line = source_lines[line_number - 1]
        if _is_source_comment_or_blank(line):
            continue
        call_row = call_rows_by_line.get(line_number)
        if call_row is not None:
            output_names = _helper_argument_dependency_names(call_row, "output", helper_dependency_names)
            if output_names & pending:
                statement_span = logical_statement_spans.get(line_number, (line_number, line_number))
                earliest = min(earliest, statement_span[0])
                pending.difference_update(output_names)
                pending.update(_helper_argument_dependency_names(call_row, "inputs", helper_dependency_names))
                if not pending:
                    break
                continue
        assignment = _simple_assignment_parts(line)
        if assignment is None:
            continue
        lhs_name, rhs_text = assignment
        if lhs_name not in pending:
            continue
        earliest = min(earliest, _earliest_matching_assignment_line(source_lines, line_number, span, lhs_name))
        pending.discard(lhs_name)
        pending.update(name for name in _tokens(rhs_text) if name in helper_dependency_names and not _is_passive_name(name))
        if not pending:
            break
    return earliest


def _earliest_matching_assignment_line(
    source_lines: list[str],
    line_number: int,
    span: tuple[int, int],
    lhs_name: str,
) -> int:
    earliest = line_number
    for previous_line in range(line_number - 1, span[0] - 1, -1):
        if previous_line - 1 >= len(source_lines):
            continue
        line = source_lines[previous_line - 1]
        if _is_source_comment_or_blank(line) or _is_structure_only_line(line):
            continue
        assignment = _simple_assignment_parts(line)
        if assignment is None:
            break
        previous_lhs, _ = assignment
        if previous_lhs != lhs_name:
            break
        earliest = previous_line
    return earliest


def _is_structure_only_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(
        re.match(
            r"^(DO\b|END\s*DO\b|IF\b.*\bTHEN\b|ELSE\s*IF\b.*\bTHEN\b|ELSE\b|END\s*IF\b|CONTINUE\b)",
            stripped,
            flags=re.IGNORECASE,
        )
    )


def _helper_argument_dependency_names(row: dict[str, Any], kind: str, helper_dependency_names: set[str]) -> set[str]:
    callee = str(row.get("callee", "")).upper()
    effects = TRANSFORMABLE_HELPER_EFFECTS.get(callee, {})
    positions = effects.get(kind)
    if positions is None:
        return set()
    if not isinstance(positions, tuple):
        positions = (positions,)
    arguments = [str(argument) for argument in row.get("arguments", []) or []]
    names: set[str] = set()
    for position in positions:
        if not isinstance(position, int) or position < 0 or position >= len(arguments):
            continue
        names.update(_base_names([arguments[position]]))
    return {name for name in names if name in helper_dependency_names}


def _promote_anchor_stress_variables(raw_roles: Any, anchors: dict[str, Any]) -> Any:
    if not isinstance(raw_roles, dict):
        return raw_roles
    updated = {str(name): dict(role) if isinstance(role, dict) else role for name, role in raw_roles.items()}
    stress_regions = (anchors.get("stress_update", {}) or {}).get("regions", []) or []
    names: set[str] = set()
    for region in stress_regions:
        if isinstance(region, dict):
            names.update(str(value).upper() for value in region.get("variables", []) or [] if str(value))
    for name in sorted(names):
        if name == "DSTRAN" or _is_passive_name(name):
            continue
        row = updated.get(name)
        if not isinstance(row, dict):
            continue
        selected = str(row.get("selected_role", row.get("user-selected OTIS role", "Unknown")))
        if selected in {"Constant", "Keep real", "Seed"}:
            continue
        row["selected_role"] = "Promote"
        row["suggested_role"] = row.get("suggested_role", "Promote")
        row["notes"] = _append_note(row.get("notes", ""), "Promoted by completed transformation anchors because this variable is on the explicit stress-update helper path.")
    return updated


def _anchor_promoted_names(raw_roles: Any, anchors: dict[str, Any]) -> set[str]:
    if not isinstance(raw_roles, dict):
        return set()
    names: set[str] = set()
    for region in (anchors.get("stress_update", {}) or {}).get("regions", []) or []:
        if isinstance(region, dict):
            names.update(str(value).upper() for value in region.get("variables", []) or [] if str(value))
    result: set[str] = set()
    for name in names:
        row = raw_roles.get(name)
        if not isinstance(row, dict):
            continue
        if str(row.get("selected_role", "")) == "Promote":
            result.add(name)
    return result


def _normalize_intrinsic_variable_roles(raw_roles: Any, source_text: str = "") -> Any:
    if not isinstance(raw_roles, dict):
        return raw_roles
    updated = {str(name): dict(role) if isinstance(role, dict) else role for name, role in raw_roles.items()}
    for name in _intrinsic_names(source_text):
        row = updated.get(name)
        if isinstance(row, dict) and row.get("selected_role") == "Promote":
            row["selected_role"] = "Keep real"
            row["notes"] = _append_note(row.get("notes", ""), "Fortran intrinsic name; not an OTIS promoted variable.")
    return updated


def _normalize_completed_keep_real_roles(raw_roles: Any) -> Any:
    if not isinstance(raw_roles, dict):
        return raw_roles
    updated = {str(name): dict(role) if isinstance(role, dict) else role for name, role in raw_roles.items()}
    protected_names = set(COMPLETED_KEEP_REAL_ARGUMENT_NAMES)
    changed = True
    while changed:
        changed = False
        for name, row in updated.items():
            if not isinstance(row, dict):
                continue
            if str(row.get("selected_role", "")) != "Promote":
                continue
            if not _should_keep_real_completed_argument(str(name).upper(), row, protected_names):
                continue
            row["selected_role"] = "Keep real"
            row["suggested_role"] = "Keep real"
            row["notes"] = _append_note(
                row.get("notes", ""),
                "Completed JSON keeps control/specification arguments real so OTIS promotion stays on executable constitutive value flow.",
            )
            protected_names.add(str(name).upper())
            changed = True
    return updated


def _should_keep_real_completed_argument(name: str, row: dict[str, Any], protected_names: set[str]) -> bool:
    if not bool(row.get("is_argument")):
        return False
    if name in protected_names:
        return True
    shape_names = _shape_symbol_names(
        str(
            row.get("detected_shape")
            or row.get("detected shape/dimension")
            or row.get("declared_shape")
            or row.get("declared shape/dimension")
            or ""
        )
    )
    return bool(shape_names & protected_names)


def _shape_symbol_names(shape: str) -> set[str]:
    return {token.upper() for token in re.findall(r"\b[A-Za-z_]\w*\b", str(shape or ""))}


def _intrinsic_names(source_text: str = "") -> set[str]:
    """Names that are calls rather than variables in this source.

    One definition, in core.roles, so this and the role classifier cannot
    drift apart about what counts as a call. The list this replaced held
    fourteen scalar maths intrinsics and no array ones, so MATMUL, TRANSPOSE
    and DOT_PRODUCT were promoted like variables and renamed like variables:
    STRESS = MATMUL(DDSDDE, STRAN + DSTRAN) came out as
    STRESS_OTI = MATMUL_OTI(...), a name declared nowhere.

    Subtracting the names the source assigns is what makes the wider set safe:
    several standard intrinsics -- SUM, COUNT, SIZE, INDEX -- are also
    perfectly ordinary names for a UMAT's own undeclared accumulator, and a
    name that carries a value is a variable whatever the set says.
    """
    return set(INTRINSIC_CALL_NAMES) - set(assigned_names(source_text))


def _append_note(existing: object, note: str) -> str:
    text = str(existing or "")
    if note in text:
        return text
    return f"{text}; {note}" if text else note


def _base_names(arguments: list[str]) -> set[str]:
    names = set()
    for argument in arguments:
        match = re.match(r"\s*([A-Za-z_]\w*)", argument)
        if match:
            names.add(match.group(1).upper())
    return names


def _uses_in_span(analysis: dict[str, Any], name: str, span: tuple[int, int]) -> list[dict[str, Any]]:
    uses = _dict(analysis.get("uses")).get(name.upper(), []) or []
    rows = []
    for row in uses:
        if not isinstance(row, dict):
            continue
        numbers = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        if numbers and span[0] <= min(numbers) <= span[1]:
            rows.append(row)
    return rows


def _tokens(text: str) -> set[str]:
    result = set()
    for token in re.findall(r"\b[A-Za-z_]\w*\b", text):
        upper = token.upper()
        if upper in {"CALL", "DO", "END", "IF", "THEN", "ELSE", "RETURN", "CONTINUE", "SUBROUTINE"}:
            continue
        result.add(upper)
    return result


def _is_passive_name(name: str) -> bool:
    return name in {
        "DDSDDE",
        "PROPS",
        "STRAN",
        "TIME",
        "DTIME",
        "TEMP",
        "DTEMP",
        "PREDEF",
        "DPRED",
        "COORDS",
        "DROT",
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
        "KINC",
        "CMNAME",
        "ABS",
        "DABS",
        "SQRT",
        "DSQRT",
        "EXP",
        "DEXP",
        "LOG",
        "DLOG",
        "SIN",
        "DSIN",
        "COS",
        "DCOS",
        "SINH",
        "COSH",
    } or bool(re.match(r"^[IJKLMN]\d*$", name))


def _ddsdde_setup_regions_before_stress(
    analysis: dict[str, Any],
    source_lines: list[str],
    first_stress_start: int,
    span: tuple[int, int],
    source_line_count: int,
) -> list[dict[str, Any]]:
    if not first_stress_start:
        return []
    lines = []
    for row in analysis.get("assignments_to_ddsdde", []) or []:
        row_lines = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        if row_lines and span[0] <= min(row_lines) <= span[1] and max(row_lines) < first_stress_start:
            lines.extend(row_lines)
    if not lines:
        return []
    start, end = _expanded_assignment_span(min(lines), max(lines), source_line_count)
    start = _expand_ddsdde_setup_start(source_lines, start, end, span)
    return [
        {
            "region_id": "DDSDDE-SETUP-KEEP-REAL",
            "start_line": start,
            "end_line": end,
            "role": "keep_real_required_by_stress_update",
            "classification": "DDSDDE setup required by stress update, keep real",
            "variables": ["DDSDDE"],
            "reason": "DDSDDE is assembled before the stress update and is used as real stiffness/setup data; do not skip this block.",
        }
    ]


def _expand_ddsdde_setup_start(source_lines: list[str], start_line: int, end_line: int, span: tuple[int, int]) -> int:
    if not source_lines or start_line <= span[0]:
        return start_line
    required_names = _ddsdde_setup_dependency_names(source_lines[start_line - 1 : end_line])
    if not required_names:
        return start_line
    earliest = start_line
    for line_number in range(start_line - 1, span[0] - 1, -1):
        line = source_lines[line_number - 1]
        if _is_source_comment_or_blank(line):
            continue
        assignment = _simple_assignment_parts(line)
        if assignment is None:
            break
        lhs_name, rhs_text = assignment
        if lhs_name in required_names:
            earliest = line_number
            required_names.discard(lhs_name)
            required_names.update(name for name in _tokens(rhs_text) if not _is_passive_name(name))
            if not required_names:
                break
    return earliest


def _expand_keep_real_required_region(source_lines: list[str], region: dict[str, Any], span: tuple[int, int]) -> dict[str, Any]:
    expanded = dict(region)
    start_line = _as_int(expanded.get("start_line"))
    end_line = _as_int(expanded.get("end_line"))
    if start_line and end_line:
        expanded["start_line"] = _expand_ddsdde_setup_start(source_lines, start_line, end_line, span)
        if source_lines:
            expanded["preview"] = _preview(source_lines, expanded["start_line"], end_line)
    return expanded


def _ddsdde_setup_dependency_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        names.update(name for name in _tokens(line) if not _is_passive_name(name))
    return names


def _simple_assignment_parts(line: str) -> tuple[str, str] | None:
    if _is_source_comment_or_blank(line):
        return None
    match = re.match(r"^\s*([A-Za-z_]\w*)(?:\s*\([^=]*\))?\s*=\s*(.+?)\s*$", line)
    if not match:
        return None
    return match.group(1).upper(), match.group(2)


def _is_source_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("!"):
        return True
    return bool(line) and line[0] in {"C", "c", "*", "!"}


def _regions_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start = _as_int(left.get("start_line"))
    left_end = _as_int(left.get("end_line"))
    right_start = _as_int(right.get("start_line"))
    right_end = _as_int(right.get("end_line"))
    return left_start <= right_end and right_start <= left_end


def _ddsdde_writing_call_lines(
    config: dict[str, Any], source_text: str, span: tuple[int, int],
) -> list[int]:
    """Last lines of CALLs inside the UMAT that hand DDSDDE to a routine.

    A Fortran dummy argument is writable unless the callee declares otherwise,
    so a CALL that passes DDSDDE is a place DDSDDE may be written -- and it is
    a place the extraction point has to sit after, or the callee's old tangent
    lands on top of the GETIM values and the generated UMAT quietly returns
    the tangent it was supposed to replace.

    Asked of the caller, not the callee, so it holds whether or not the callee
    is defined in this file. One source calls
    ``voigt_notation_tangent(CC, NTENS, indices, DDSDDE)`` one line after its
    stress update ends, and the extraction was being placed in between.
    """
    if not span:
        return []
    form = detect_source_form(Path(config.get("source_file") or "x.f"), source_text)
    lines: list[int] = []
    for logical in logical_lines_from_text(source_text, form):
        numbers = [int(value) for value in logical.line_numbers]
        if not numbers or not (span[0] <= numbers[0] <= span[1]):
            continue
        text = logical.text.strip()
        match = re.match(r"^CALL\s+\w+\s*\((.*)\)\s*$", text, re.IGNORECASE)
        if not match:
            continue
        if re.search(r"\bDDSDDE\b", match.group(1), re.IGNORECASE):
            lines.append(max(numbers))
    return lines


def _infer_ddsdde_output_region(
    analysis: dict[str, Any],
    first_stress_start: int,
    last_stress_end: int,
    span: tuple[int, int],
    source_line_count: int,
) -> dict[str, Any] | None:
    if not last_stress_end:
        return None
    lines = []
    for row in analysis.get("assignments_to_ddsdde", []) or []:
        row_lines = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        if not row_lines or not (span[0] <= min(row_lines) <= span[1]):
            continue
        if max(row_lines) > last_stress_end:
            lines.extend(row_lines)
    if not lines:
        return None
    start, end = _expanded_assignment_span(min(lines), max(lines), source_line_count)
    return {
        "region_id": "DDSDDE-OUTPUT-REPLACE",
        "start_line": start,
        "end_line": end,
        "role": "ddsdde_output_replace",
        "classification": "DDSDDE output replacement, replace with GETIM extraction",
        "variables": ["DDSDDE"],
        "reason": "DDSDDE assignments occur after the stress update and are the explicit old tangent output replacement point.",
    }


def _expanded_assignment_span(start_line: int, end_line: int, source_line_count: int) -> tuple[int, int]:
    return max(1, start_line), min(source_line_count or end_line, end_line)


def _region_directly_assigns_ddsdde(region: dict[str, Any], analysis: dict[str, Any]) -> bool:
    for assignment in analysis.get("assignments_to_ddsdde", []) or []:
        if _line_numbers_intersect(assignment.get("line_numbers", []), [region]):
            return True
    return False


def _assignments_to_ddsdde_in_span(analysis: dict[str, Any], span: tuple[int, int]) -> list[dict[str, Any]]:
    rows = []
    for assignment in analysis.get("assignments_to_ddsdde", []) or []:
        numbers = [_as_int(value) for value in assignment.get("line_numbers", []) or [] if _as_int(value)]
        if numbers and span[0] <= min(numbers) <= span[1]:
            rows.append(assignment)
    return rows


def _same_span_exists(region: dict[str, Any], regions: list[dict[str, Any]]) -> bool:
    return any(
        _as_int(region.get("start_line")) == _as_int(other.get("start_line"))
        and _as_int(region.get("end_line")) == _as_int(other.get("end_line"))
        for other in regions
    )


def _enclosing_do_end(source_lines: list[str], line_number: int,
                      span: tuple[int, int]) -> int:
    """The END DO of the outermost DO loop containing ``line_number``, or 0.

    An extraction inserted inside a loop runs once per iteration, and the two
    things it does are both destroyed by that. The real copy
    ``STRESS(I) = REAL(STRESS_OTI(I))`` is merely repeated; the tangent
    extraction ``DDSDDE(i,j) = GETIM(STRESS_OTI(i), j)`` overwrites the array
    the loop is still reading.

    That is not hypothetical. A UMAT whose whole stress update is

        DO K1=1, NTENS
          DO K2=1, NTENS
            STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)
          END DO
        END DO

    puts the last stress statement inside two loops. Inserting after it landed
    the extraction between the two END DOs, so on the first pass GETIM
    replaced the elastic stiffness the remaining passes then read back as
    though it were the stiffness. The file compiled, ran, and returned a
    tangent whose first column was right and whose other five were zero,
    together with a wrong stress. Only a numerical comparison against the
    untransformed original found it.

    A tab in the label field is expanded before the columns are read, because
    that source -- like others written for ifort -- indents with tabs, and the
    loop keywords are invisible otherwise.
    """
    from umat_oti.fortran.parser import expand_fixed_form_tabs

    start, end = span
    if not (start <= line_number <= end):
        return 0
    depth = 0
    outermost_open = 0
    for number in range(start, min(end, len(source_lines)) + 1):
        text = expand_fixed_form_tabs(source_lines[number - 1]).strip()
        if _is_comment_or_blank(text):
            continue
        if re.match(r"^end\s*do\b", text, flags=re.IGNORECASE):
            depth = max(0, depth - 1)
            # Inside means between the DO and its END DO, not merely before
            # the END DO: a statement above the loop entirely is not enclosed
            # by it and must not be pushed past it.
            if depth == 0 and outermost_open <= line_number <= number and outermost_open:
                return number
            if depth == 0:
                outermost_open = 0
            continue
        if re.match(r"^(?:\w+\s*:\s*)?do\b", text, flags=re.IGNORECASE):
            if depth == 0:
                outermost_open = number
            depth += 1
    return 0



def _post_output_insert_line(source_lines: list[str], output_region: dict[str, Any] | None) -> int:
    if not output_region:
        return 0
    end = _as_int(output_region.get("end_line"))
    if not end:
        return 0
    for line_number in range(end + 1, len(source_lines) + 1):
        line = source_lines[line_number - 1]
        if re.match(r"^\s*RETURN\b", line, flags=re.IGNORECASE):
            break
        if re.match(r"^\s*END\s*IF\b", line, flags=re.IGNORECASE):
            return line_number
    return end


def _real_output_insert_after_line(source_lines: list[str], stress_regions: list[dict[str, Any]], mappings: dict[str, str]) -> int:
    output_names = {mappings.get("stress", "STRESS"), mappings.get("statev", "STATEV")}
    output_names = {name for name in output_names if name}
    selected_line = 0
    for region in sorted(stress_regions, key=lambda row: (_as_int(row.get("start_line")), _as_int(row.get("end_line")))):
        start = _as_int(region.get("start_line"))
        end = _as_int(region.get("end_line"))
        if not start or not end:
            continue
        for line_number in range(start, min(end, len(source_lines)) + 1):
            line = source_lines[line_number - 1]
            if _is_comment_or_blank(line):
                continue
            if _line_mentions_any_output(line, output_names):
                selected_line = end
                break
    return selected_line


def _branch_safe_real_output_insert_after_line(source_lines: list[str], real_output_line: int, output_region: dict[str, Any] | None) -> int:
    if not real_output_line or not output_region:
        return 0
    post_output_line = _post_output_insert_line(source_lines, output_region)
    if post_output_line <= real_output_line:
        return 0
    return post_output_line if _if_depth_at_line(source_lines, real_output_line) > 0 else 0


def _if_depth_at_line(source_lines: list[str], line_number: int) -> int:
    depth = 0
    for line in source_lines[:line_number]:
        if _is_comment_or_blank(line):
            continue
        stripped = line.strip()
        if re.match(r"^END\s*IF\b", stripped, flags=re.IGNORECASE):
            depth = max(0, depth - 1)
        if re.match(r"^IF\b.*\bTHEN\b", stripped, flags=re.IGNORECASE):
            depth += 1
    return depth


def _line_mentions_any_output(line: str, output_names: set[str]) -> bool:
    for name in output_names:
        if re.search(rf"\b{re.escape(name)}\b", line, flags=re.IGNORECASE):
            return True
    return False


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or line[0:1] in {"C", "c", "*"} or stripped.startswith("!")


def _file_io_regions(
    analysis: dict[str, Any],
    source_lines: list[str],
    span: tuple[int, int],
    stress_regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in analysis.get("file_io", []) or []:
        if not isinstance(row, dict):
            continue
        line_numbers = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        if not line_numbers or not (span[0] <= min(line_numbers) <= span[1]):
            continue
        text = str(row.get("text", ""))
        in_stress = _line_numbers_intersect(line_numbers, stress_regions)
        action = _classify_file_io(text, in_stress)
        rows.append(
            {
                "start_line": min(line_numbers),
                "end_line": max(line_numbers),
                "line_numbers": line_numbers,
                "kind": str(row.get("kind", "")),
                "text": text,
                "action": action,
                "reason": _file_io_reason(text, in_stress, action),
                "preview": _preview(source_lines, min(line_numbers), max(line_numbers)),
            }
        )
    return rows


def _classify_file_io(text: str, in_stress: bool) -> str:
    upper = text.upper()
    if "READ" in upper or "OPEN" in upper:
        return "user_review_required" if in_stress else "initialization_only_keep"
    if "WRITE" in upper:
        if any(token in upper for token in ("LOCAL PLASTICITY", "GAUSS POINT", "ITERATIONS", "LAST CORRECTION")):
            return "keep_real_side_effect"
        if re.search(r"WRITE\s*\(\s*\*", upper) or re.search(r"WRITE\s*\(\s*\d+", upper):
            return "keep_real_side_effect"
    return "user_review_required" if in_stress else "initialization_only_keep"


def _file_io_reason(text: str, in_stress: bool, action: str) -> str:
    if action == "keep_real_side_effect":
        return "Diagnostic/error reporting side effect; it does not provide constitutive input and may remain real-side-effect code."
    if action == "initialization_only_keep":
        return "I/O is outside the selected stress update anchor and is kept outside the transformed OTIS path."
    if action == "remove_from_transformed_path":
        return "User/config marked this I/O as removable logging in transformed code."
    if action == "unsafe_block":
        return "User/config marked this I/O as unsafe for deterministic transformation."
    return "Stress-path I/O requires user classification before transformation."


def _statev_regions(analysis: dict[str, Any], key: str, span: tuple[int, int], source_lines: list[str]) -> list[dict[str, Any]]:
    accesses = _dict(analysis.get("statev_accesses"))
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(accesses.get(key, []) or [], start=1):
        if not isinstance(row, dict):
            continue
        line_numbers = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        if not line_numbers or not (span[0] <= min(line_numbers) <= span[1]):
            continue
        rows.append(
            {
                "region_id": f"STATEV-{key.upper()}-{index:03d}",
                "start_line": min(line_numbers),
                "end_line": max(line_numbers),
                "role": "promote_statev" if key == "writes" else "read_statev_shadow_or_real",
                "reason": f"Detected STATEV {key[:-1] if key.endswith('s') else key} in selected UMAT.",
                "text": str(row.get("text", "")),
                "preview": _preview(source_lines, min(line_numbers), max(line_numbers)),
            }
        )
    return rows


def _branch_regions(analysis: dict[str, Any], span: tuple[int, int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(analysis.get("branch_conditions", []) or [], start=1):
        if not isinstance(row, dict):
            continue
        line_numbers = [_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value)]
        if not line_numbers or not (span[0] <= min(line_numbers) <= span[1]):
            continue
        rows.append(
            {
                "region_id": f"BRANCH-{index:03d}",
                "start_line": min(line_numbers),
                "end_line": max(line_numbers),
                "role": "normalize_condition_real_parts" if row.get("is_convergence_check") else "preserve_branch_condition",
                "reason": "Promoted values in branch/convergence logic must use REAL(...) for control flow." if row.get("is_convergence_check") else "Branch condition is preserved; promoted variables are normalized if present.",
                "condition": row.get("condition", ""),
                "tokens": row.get("tokens", []),
                "text": row.get("text", ""),
            }
        )
    return rows


def _helper_call_regions(analysis: dict[str, Any], stress_regions: list[dict[str, Any]], span: tuple[int, int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    calls = analysis.get("stress_path_helpers", []) or analysis.get("calls", []) or []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for index, row in enumerate(calls, start=1):
        if not isinstance(row, dict):
            continue
        line_numbers = tuple(_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value))
        if not line_numbers or not (span[0] <= min(line_numbers) <= span[1]):
            continue
        if stress_regions and not _line_numbers_intersect(line_numbers, stress_regions):
            continue
        callee = str(row.get("callee", "")).upper()
        key = (callee, line_numbers)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "region_id": f"HELPER-CALL-{index:03d}",
                "start_line": min(line_numbers),
                "end_line": max(line_numbers),
                "callee": callee,
                "arguments": list(row.get("arguments", []) or []),
                "role": "pass_through_rewrite_promoted_arguments",
                "reason": "Helper call is preserved; promoted arguments are rewritten to OTIS shadows.",
            }
        )
    return rows


def _first_executable_line_in_span(source_lines: list[str], span: tuple[int, int]) -> int:
    for line_number in range(max(1, span[0]), min(len(source_lines), span[1]) + 1):
        stripped = source_lines[line_number - 1].strip()
        if not stripped or source_lines[line_number - 1][0:1] in {"C", "c", "*"}:
            continue
        if re.match(r"^(SUBROUTINE|INCLUDE|IMPLICIT|DIMENSION|PARAMETER|CHARACTER|INTEGER|REAL|DOUBLE\s+PRECISION)\b", stripped, flags=re.IGNORECASE):
            continue
        return line_number
    return 0


def _first_finite_strain_use_line(analysis: dict[str, Any], span: tuple[int, int]) -> int:
    finite = _dict(analysis.get("finite_strain"))
    lines: list[int] = []
    for key in ("dfgrd0_executable_uses", "dfgrd1_executable_uses"):
        for row in finite.get(key, []) or []:
            if not isinstance(row, dict):
                continue
            for value in row.get("line_numbers", []) or []:
                number = _as_int(value)
                if number and span[0] <= number <= span[1]:
                    lines.append(number)
    return min(lines) if lines else 0


def _mapping(config: dict[str, Any]) -> dict[str, str]:
    raw = _dict(config.get("mapping"))
    result = {str(key).lower(): str(value).upper() for key, value in raw.items() if key != "optional_variables" and value}
    result.update({str(key).lower(): str(value).upper() for key, value in _dict(raw.get("optional_variables")).items() if value})
    return result


def _source_file(config: dict[str, Any]) -> str:
    source = _dict(config.get("source"))
    return str(source.get("selected_umat_file") or source.get("uploaded_file") or "umat.f")


def _line_numbers_intersect(line_numbers: Any, regions: list[dict[str, Any]]) -> bool:
    numbers = [_as_int(value) for value in line_numbers or [] if _as_int(value)]
    return any(_as_int(region.get("start_line")) <= number <= _as_int(region.get("end_line")) for number in numbers for region in regions)


def _preview(source_lines: list[str], start_line: int, end_line: int) -> str:
    if not source_lines or not start_line or not end_line:
        return ""
    selected = source_lines[max(start_line - 1, 0) : min(end_line, len(source_lines))]
    if len(selected) > 8:
        selected = selected[:4] + ["..."] + selected[-3:]
    return "\n".join(line.rstrip() for line in selected)


def _upper_list(values: Any) -> list[str]:
    return sorted({str(value).upper() for value in values or [] if str(value)})


def _as_int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}