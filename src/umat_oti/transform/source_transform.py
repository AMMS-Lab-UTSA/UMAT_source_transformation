from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from umat_oti.core.model import ParsedFortranSource
from umat_oti.core.transformation_anchors import anchor_completion_status
from umat_oti.fortran.callgraph import build_call_graph, undefined_delegate_call
from umat_oti.fortran.literals import (
    atomic_real_literals,
    mask_character_literals,
    mask_real_literals,
    unmask_character_literals,
    unmask_real_literals,
    without_real_literals,
)
from umat_oti.fortran.normalize import detect_source_form
from umat_oti.fortran.parser import (
    logical_lines_from_text, parse_entity, parse_subroutines, split_top_level,
)
from umat_oti.fortran.regions import INTRINSIC_TOKEN_NAMES, _is_executable_line
from umat_oti.oti.module_generator import OtilibGenerationError, generate_otilib_module
from umat_oti.transform.helper_lifting import HelperLiftingError, helper_lift_closure, lift_helper_set_source, wrap_free_form
# The intrinsic extension module is generated in one place and used by
# both transform paths; no cycle, that module imports nothing from here.
from umat_oti.transform.parameter_sensitivity_transform import (
    _emit_intrinsic_extensions,
)


INLINEABLE_HELPERS = {"DOTPROD", "DYADICPROD", "KCLEAR", "KDAMACAL", "KDEVIA", "KEFFP", "KINVER", "KMATSUB", "KMAVEC", "KMLT", "KMLT1", "KMMULT", "KMTRAN", "KPROYECTOR", "KSMULT", "KTRACE", "KTRANS", "KUPDVEC", "VSPRATE"}
TYPED_INTRINSIC_NORMALIZATIONS = {
    "DABS": "ABS",
    "DMAX1": "MAX",
    "DMIN1": "MIN",
    "DSQRT": "SQRT",
    "DEXP": "EXP",
    "DLOG": "LOG",
    "DSIN": "SIN",
    "DCOS": "COS",
    "DTAN": "TAN",
}
FINITE_KINEMATIC_CATEGORIES = {
    "deformation_gradient_variables": {"DFGRD0", "DFGRD1", "DFGR", "DFGI"},
    "velocity_gradient_variables": {"VEG", "TVEG", "DFRT", "TRVAL"},
    "spin_variables": {"SPIN", "SPINW", "WS", "SW"},
    "finite_strain_measures": {"STR", "STRR", "DSTR"},
}
IMPLICIT_INTEGER_FIRST_LETTERS = frozenset("IJKLMN")


@dataclass
class TransformResult:
    success: bool
    output_dir: Path
    transformed_source: str = ""
    transformed_source_path: Path | None = None
    report_path: Path | None = None
    generated_files: list[Path] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformRewrite:
    source: str
    extraction_insertion_region_id: str = ""
    extraction_inserted_after_stress_update: bool = False
    ddsdde_output_method: str = "GETIM(STRESS_OTI(i), j)"
    tangent_helper_regions_skipped: list[dict[str, Any]] = field(default_factory=list)
    tangent_output_regions_replaced: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TangentRegionContext:
    helper_regions: list[dict[str, Any]] = field(default_factory=list)
    output_regions: list[dict[str, Any]] = field(default_factory=list)
    extraction_region: dict[str, Any] | None = None
    blockers: list[str] = field(default_factory=list)
    real_output_insert_after_line: int = 0
    ddsdde_insert_after_line: int = 0
    anchor_status: str = "heuristic"


def transform_umat_to_oti_from_config(
    source_text: str,
    config: dict,
    output_dir: Path,
    ntens: int,
) -> TransformResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if ntens <= 0:
        ntens = _as_int(_dict(config.get("transformation_settings")).get("ntens"))
    roles = _roles_from_config(config)
    regions = _regions_from_config(config)
    mappings = _mapping(config)
    selected_umat = _selected_umat(config)
    source_file = _source_file(config)
    roles = _roles_with_stress_path_promotions(config, roles, source_text)
    roles = _roles_with_finite_strain_promotions(config, roles)
    roles = _roles_with_extra_jacobian_promotions(config, roles)
    parsed = _parse_source(source_text, source_file)
    umat_span = _selected_routine_span(parsed, selected_umat)
    # The floor is the first executable line, not the routine's first line.
    # A finite-strain UMAT names DFGRD1 in its own argument list and again in
    # its DIMENSION statement, and those count as lines that read the
    # deformation gradient. Starting the propagation region there put the
    # subroutine header inside a stress region, so the header was rewritten
    # along with the body and the routine's dummy arguments came out renamed:
    # subroutine umat_area_stretch(STRESS_OTI,STATEV_OTI,...), which no caller
    # can satisfy. It only surfaced on a delegating source, where the caller
    # is in the same file and passes real arrays.
    if umat_span:
        first_executable = _first_executable_line(parsed, selected_umat)
        if first_executable:
            umat_span = (max(umat_span[0], first_executable), umat_span[1])
    regions = _regions_with_finite_strain_path(config, regions, source_text, umat_span)
    regions = _regions_with_local_stress_bridges(regions, source_text)
    order = int(_dict(config.get("transformation_settings")).get("order", 1) or 1)
    directions_required = _directions_required(ntens, config)
    oti_directions = int(directions_required["total_directions"] or ntens)
    module_name = f"otim{oti_directions}n{order}" if oti_directions else ""
    type_name = f"ONUMM{oti_directions}N{order}" if oti_directions else ""
    tangent_context = _tangent_region_context(config, regions["old_tangent"], regions["stress"], source_text)
    helper_roots = _liftable_helper_roots(config, roles, regions["stress"])
    helper_lift_names: tuple[str, ...] = ()
    helper_lift_issue = ""
    if helper_roots:
        try:
            helper_lift_names = helper_lift_closure(parsed, helper_roots, selected_umat=selected_umat)
        except HelperLiftingError as exc:
            helper_lift_issue = str(exc)
    blockers = _readiness_blockers(config, roles, regions, mappings, ntens, selected_umat, source_text, helper_lift_issue="", parsed=parsed)
    blockers.extend(tangent_context.blockers)
    warnings: list[str] = []
    if helper_lift_issue:
        for message in _completed_json_helper_call_blockers(
            _dict(config.get("analysis")), regions["stress"], roles, helper_lift_issue
        ):
            warnings.append(f"Helper subroutine pass-through used despite lifting limitation: {message}")
    report_base = _report_base(
        config=config,
        selected_umat=selected_umat,
        source_file=source_file,
        ntens=ntens,
        order=order,
        module_name=module_name,
        type_name=type_name,
        roles=roles,
        regions=regions,
        tangent_context=tangent_context,
    )
    if blockers:
        report = {**report_base, "success": False, "warnings": warnings, "blockers": blockers, "generated_files": []}
        report_path = _write_report(output_dir, report)
        return TransformResult(False, output_dir, report_path=report_path, blockers=blockers, warnings=warnings, report=report)

    try:
        module_result = generate_otilib_module(output_dir=output_dir, ntens=oti_directions, order=order)
        warnings.extend(module_result.warnings)
    except OtilibGenerationError as exc:
        blockers.append(str(exc))
        report = {**report_base, "success": False, "warnings": warnings, "blockers": blockers, "generated_files": []}
        report_path = _write_report(output_dir, report)
        return TransformResult(False, output_dir, report_path=report_path, blockers=blockers, warnings=warnings, report=report)

    variable_shapes = _variable_shapes(config, mappings, ntens)
    argument_variables = _argument_variables(config, selected_umat)
    shape_blockers = _shape_blockers(source_text, roles, regions, mappings, variable_shapes, parsed)
    shape_blockers.extend(_data_initialised_shadow_blockers(source_text, roles))
    if shape_blockers:
        blockers.extend(shape_blockers)
        report = {**report_base, "success": False, "warnings": warnings, "blockers": blockers, "generated_files": []}
        report_path = _write_report(output_dir, report)
        return TransformResult(False, output_dir, report_path=report_path, blockers=blockers, warnings=warnings, report=report)

    rewrite = _transform_source_text(
        source_text=source_text,
        parsed=parsed,
        selected_umat=selected_umat,
        ntens=ntens,
        oti_directions=oti_directions,
        module_name=module_result.module_name,
        type_name=module_result.type_name,
        roles=roles,
        regions=regions,
        mappings=mappings,
        variable_shapes=variable_shapes,
        argument_variables=argument_variables,
        lifted_helper_names=set(helper_lift_names),
        tangent_context=tangent_context,
        config=config,
    )
    transformed_source = rewrite.source
    transformed_name = _transformed_filename(source_file)
    transformed_path = output_dir / transformed_name
    transformed_path.write_text(transformed_source, encoding="utf-8")

    helper_source_path: Path | None = None
    if helper_lift_names:
        lifted_helpers = lift_helper_set_source(
            parsed,
            helper_lift_names,
            module_name=module_result.module_name,
            type_name=module_result.type_name,
            helper_output_copies=_helper_output_copies(config),
            helper_output_surfaces=_helper_output_surfaces(config),
        )
        helper_source_path = output_dir / "umat_oti_helpers.f90"
        # Wrapped before it is written. gfortran is given
        # -ffree-line-length-none and would take the file as it stands, but
        # Abaqus compiles user subroutines with ifort, which truncates at 7200
        # characters; stitching a source's fixed-form continuations into single
        # free-form statements produced one line of 14858. The wrap only moves
        # line breaks, so the statement text is unchanged.
        helper_source_path.write_text(
            wrap_free_form(lifted_helpers.source), encoding="utf-8")

    # The extension module that supplies what the vendored algebra leaves out:
    # SIGN, SQRT, MIN, MAX and the mixed-kind arithmetic Fortran would have
    # done itself before the type was replaced. The parameter-sensitivity path
    # has always emitted it; this one never did, so a source calling SIGN or
    # SQRT on a differentiated value compiled there and failed here.
    intrinsics_path = output_dir / "oti_intrinsics.f90"
    intrinsics_path.write_text(
        _emit_intrinsic_extensions(module_result.module_name,
                                   module_result.type_name),
        encoding="utf-8")

    compile_order = output_dir / "compile_order.txt"
    compile_units = ["master_parameters.f90", "real_utils.f90",
                     f"{module_result.module_name}.f90", "oti_intrinsics.f90"]
    if helper_source_path is not None:
        compile_units.append(helper_source_path.name)
    compile_units.append(transformed_name)
    compile_order.write_text("\n".join(compile_units) + "\n", encoding="utf-8")
    higher_order_directions = _write_higher_order_directions(output_dir, oti_directions, order)
    compile_hint = output_dir / "compile_hint.sh"
    compile_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "OBJDIR=${OBJDIR:-.}",
        'gfortran -c -ffree-form -ffree-line-length-none master_parameters.f90 -J"$OBJDIR" -o "$OBJDIR/master_parameters.o"',
        'gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" real_utils.f90 -J"$OBJDIR" -o "$OBJDIR/real_utils.o"',
        f'gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" {module_result.module_name}.f90 -J"$OBJDIR" -o "$OBJDIR/{module_result.module_name}.o"',
        'gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" oti_intrinsics.f90 -J"$OBJDIR" -o "$OBJDIR/oti_intrinsics.o"',
    ]
    if helper_source_path is not None:
        compile_lines.append('gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" umat_oti_helpers.f90 -J"$OBJDIR" -o "$OBJDIR/umat_oti_helpers.o"')
    compile_lines.append(
        f'gfortran -c -ffixed-form -ffixed-line-length-none -I"$OBJDIR" {transformed_name} -J"$OBJDIR" -o "$OBJDIR/transformed_umat.o"'
    )
    compile_hint.write_text("\n".join(compile_lines) + "\n", encoding="utf-8")
    compile_hint.chmod(0o755)

    semantic_checks, sanity_warnings = _semantic_checks(
        transformed_source=transformed_source,
        form=parsed.form,
        module_name=module_result.module_name,
        type_name=module_result.type_name,
        roles=roles,
        regions=regions,
        mappings=mappings,
        tangent_context=tangent_context,
        extraction_insertion_region_id=rewrite.extraction_insertion_region_id,
        config=config,
    )
    warnings.extend(sanity_warnings)
    generated_files = [
        module_result.master_parameters_path,
        module_result.real_utils_path,
        module_result.module_path,
        compile_order,
        compile_hint,
    ]
    if helper_source_path is not None:
        generated_files.append(helper_source_path)
    if higher_order_directions is not None:
        generated_files.append(higher_order_directions)
    generated_files.append(transformed_path)
    report = {
        **report_base,
        "success": not sanity_warnings,
        "warnings": warnings,
        "blockers": [],
        "generated_files": [str(path) for path in generated_files],
        "extraction_method": rewrite.ddsdde_output_method,
        "extraction_inserted_after_stress_update": rewrite.extraction_inserted_after_stress_update,
        "extraction_insertion_region_id": rewrite.extraction_insertion_region_id,
        "tangent_helper_regions_skipped": rewrite.tangent_helper_regions_skipped,
        "tangent_output_regions_replaced": rewrite.tangent_output_regions_replaced,
        "old_tangent_regions_replaced": rewrite.tangent_output_regions_replaced,
        "semantic_checks": semantic_checks,
    }
    report_path = _write_report(output_dir, report)
    generated_files.append(report_path)
    return TransformResult(
        success=not sanity_warnings,
        output_dir=output_dir,
        transformed_source=transformed_source,
        transformed_source_path=transformed_path,
        report_path=report_path,
        generated_files=generated_files,
        warnings=warnings,
        report=report,
    )


def _parse_source(source_text: str, source_file: str) -> ParsedFortranSource:
    path = Path(source_file or "uploaded_umat.f")
    form = detect_source_form(path, source_text)
    logical_lines = logical_lines_from_text(source_text, form)
    return ParsedFortranSource(path, form, source_text, logical_lines, parse_subroutines(logical_lines))


def _roles_from_config(config: dict[str, Any]) -> dict[str, set[str]]:
    review = _dict(config.get("transformation_review"))
    roles = {
        "seed": _upper_set(review.get("seed_variables", [])),
        "promote": _upper_set(review.get("promoted_variables", [])),
        "constant": _upper_set(review.get("constant_variables", [])),
        "keep_real": _upper_set(review.get("keep_real_variables", [])),
    }
    for names in roles.values():
        names.difference_update(INTRINSIC_TOKEN_NAMES)
    if roles["seed"] or roles["promote"] or roles["constant"] or roles["keep_real"]:
        return roles
    for name, row in _variable_role_items(config).items():
        selected = str(row.get("selected_role") or row.get("user-selected OTIS role") or "Unknown")
        target = {"Seed": "seed", "Promote": "promote", "Constant": "constant", "Keep real": "keep_real"}.get(selected)
        if target:
            roles[target].add(name.upper())
    for names in roles.values():
        names.difference_update(INTRINSIC_TOKEN_NAMES)
    return roles


def _regions_from_config(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    anchor_regions = _regions_from_anchors(config)
    if anchor_regions is not None:
        return anchor_regions
    review = _dict(config.get("transformation_review"))
    stress = _region_rows(review.get("stress_update_regions_to_transform", []))
    old_tangent = _region_rows(review.get("old_tangent_regions_to_replace", []))
    shared_setup = _region_rows(review.get("shared_setup_regions_to_keep", []))
    if stress or old_tangent or shared_setup:
        return {"stress": stress, "old_tangent": old_tangent, "shared_setup": shared_setup}
    stress = []
    old_tangent = []
    shared_setup = []
    for region_id, row in _region_classification_items(config).items():
        region_type = str(row.get("region_type") or row.get("region type") or "")
        classification = str(row.get("selected_classification") or row.get("user-selected classification") or "")
        if classification.lower() in {"", "ignore", "unknown"}:
            continue
        region = {
            "region_id": region_id,
            "start_line": _as_int(row.get("start_line") or row.get("start line")),
            "end_line": _as_int(row.get("end_line") or row.get("end line")),
            "reason": str(row.get("detected_reason") or row.get("detected reason") or ""),
            "classification": classification,
            "variables": _upper_list(row.get("detected_variables") or row.get("detected variables") or []),
            "preview": str(row.get("preview") or row.get("short code preview") or ""),
        }
        if region_type == "stress":
            stress.append(region)
        elif region_type == "tangent":
            old_tangent.append(region)
        elif region_type == "shared_setup":
            shared_setup.append(region)
    return {"stress": stress, "old_tangent": old_tangent, "shared_setup": shared_setup}


def _regions_from_anchors(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    anchors = _dict(config.get("transformation_anchors"))
    if not anchors:
        return None
    stress = _anchor_region_rows(_dict(anchors.get("stress_update")).get("regions", []), include_roles={"transform_with_oti"})
    old_tangent: list[dict[str, Any]] = []
    old = _dict(anchors.get("old_tangent"))
    output_regions = [r for r in (old.get("output_regions") or []) if isinstance(r, dict) and r]
    if not output_regions:
        single = _dict(old.get("output_region"))
        if single:
            output_regions = [single]
    if output_regions:
        old_tangent.extend(_anchor_region_rows(output_regions, include_roles={"ddsdde_output_replace"}))
    old_tangent.extend(
        _anchor_region_rows(
            old.get("helper_regions", []),
            include_roles={"tangent_helper_skip_only", "validation_only_ignore"},
        )
    )
    shared_setup = _anchor_region_rows(
        anchors.get("shared_setup_regions_to_keep", []),
        include_roles={"keep_real", "keep_real_required_by_stress_update"},
    )
    return {"stress": stress, "old_tangent": old_tangent, "shared_setup": shared_setup}


def _anchor_region_rows(rows: Any, include_roles: set[str] | None = None) -> list[dict[str, Any]]:
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role", ""))
        if include_roles is not None and role not in include_roles:
            continue
        start = _as_int(row.get("start_line") or row.get("start line"))
        end = _as_int(row.get("end_line") or row.get("end line"))
        if start <= 0 or end <= 0:
            continue
        result.append(
            {
                "region_id": str(row.get("region_id") or row.get("region id") or ""),
                "start_line": start,
                "end_line": end,
                "reason": str(row.get("reason") or row.get("detected reason") or ""),
                "classification": str(row.get("classification") or row.get("user-selected classification") or role),
                "role": role,
                "variables": _upper_list(row.get("variables") or row.get("detected variables") or []),
                "preview": str(row.get("preview") or row.get("short code preview") or ""),
            }
        )
    return result


def _mapping(config: dict[str, Any]) -> dict[str, str]:
    raw = _dict(config.get("mapping"))
    result = {str(key).lower(): str(value).upper() for key, value in raw.items() if key != "optional_variables" and value}
    optional = _dict(raw.get("optional_variables"))
    result.update({str(key).lower(): str(value).upper() for key, value in optional.items() if value})
    return result


def _selected_umat(config: dict[str, Any]) -> str:
    source = _dict(config.get("source"))
    return str(source.get("selected_umat_name") or source.get("detected_umat_name") or "UMAT").upper()


def _source_file(config: dict[str, Any]) -> str:
    source = _dict(config.get("source"))
    return str(source.get("selected_umat_file") or source.get("uploaded_file") or "umat.f")


def _readiness_blockers(
    config: dict[str, Any],
    roles: dict[str, set[str]],
    regions: dict[str, list[dict[str, Any]]],
    mappings: dict[str, str],
    ntens: int,
    selected_umat: str,
    source_text: str,
    helper_lift_issue: str = "",
    parsed: ParsedFortranSource | None = None,
) -> list[str]:
    blockers: list[str] = []
    review = _dict(config.get("transformation_review"))
    analysis = _dict(config.get("analysis"))
    has_completed_anchors = bool(config.get("transformation_anchors"))
    # Named first, because it explains every other blocker this source
    # produces. A wrapper that hands its whole job to a routine defined in
    # another file has no stress update and no tangent here to find, and the
    # checks below can only report the absence as a list of symptoms.
    missing_delegate = (
        undefined_delegate_call(parsed, selected_umat or "UMAT") if parsed is not None else None
    )
    if missing_delegate:
        blockers.append(
            f"{(selected_umat or 'UMAT').upper()} delegates its whole body to "
            f"{missing_delegate}, which this source does not define: the stress "
            "update and the tangent are in another file, so there is nothing "
            "here to transform."
        )
    if has_completed_anchors:
        completion = anchor_completion_status(config)
        if completion.get("status") == "needs_json_completion":
            for issue in completion.get("completion_issues", []) or []:
                message = issue.get("message", issue) if isinstance(issue, dict) else issue
                blockers.append(f"Configuration needs JSON completion: {message}")
    if ntens <= 0:
        blockers.append("Enter NTENS, the number of strain/stress components for this UMAT.")
    seed_variables = sorted(roles["seed"])
    if len(seed_variables) != 1:
        blockers.append("Exactly one seed variable is required for this milestone.")
    elif seed_variables[0] == "DFGRD1":
        # The deformation gradient is a seed the emitter knows how to inject
        # into -- _finite_dfgrd1_seed_lines maps the six strain directions
        # into DFGRD1 -- but only under the finite-strain setting that turns
        # those lines on. Without it nothing would perturb anything and the
        # tangent would come out structurally zero, so it is refused here
        # rather than emitted.
        if not _validation_uses_finite_geometry(config):
            blockers.append(
                "DFGRD1 is the seed, which requires the finite-strain seed: set "
                "transformation_settings.seed_dfgrd1."
            )
    elif seed_variables[0] != mappings.get("dstran", "DSTRAN") or seed_variables[0] != "DSTRAN":
        blockers.append("The only seed variable must be mapped to DSTRAN.")
    if not mappings.get("stress"):
        blockers.append("Dependent output STRESS is not mapped.")
    if not mappings.get("ddsdde"):
        blockers.append("DDSDDE output is not mapped.")
    if not regions["stress"]:
        blockers.append("At least one user-confirmed stress update region is required.")
    if not has_completed_anchors:
        blockers.extend(_unknown_region_blockers(config))
    blockers.extend(_stress_path_io_blockers(config, analysis, regions["stress"]))
    if has_completed_anchors:
        blockers.extend(_completed_json_helper_call_blockers(analysis, regions["stress"], roles, helper_lift_issue))
    blockers.extend(_local_newton_blockers(config, roles))
    blockers.extend(_unsupported_intrinsic_blockers(source_text, roles, regions["stress"]))
    blockers.extend(_uncovered_ddsdde_blockers(
        analysis, regions["old_tangent"], regions["stress"], regions["shared_setup"],
        _reachable_routine_regions(parsed, selected_umat)))
    if not source_text.strip():
        blockers.append("Selected UMAT source text is empty.")
    if not has_completed_anchors:
        for action in review.get("action_needed", []) or []:
            message = action.get("message", action) if isinstance(action, dict) else action
            if isinstance(action, dict) and action.get("kind") == "finite_strain":
                continue
            if isinstance(action, dict) and action.get("kind") == "stress_path_helpers":
                continue
            blockers.append(f"Unresolved action_needed item: {message}")
        for item in review.get("ambiguous_items", []) or []:
            if isinstance(item, dict) and item.get("kind") == "routine":
                continue
            message = item.get("reason", item) if isinstance(item, dict) else item
            blockers.append(f"Unresolved ambiguous item: {message}")
    return blockers


def _unknown_region_blockers(config: dict[str, Any]) -> list[str]:
    blockers = []
    for region_id, row in _region_classification_items(config).items():
        role = str(row.get("selected_classification") or row.get("user-selected classification") or "Unknown")
        region_type = str(row.get("region_type") or row.get("region type") or "")
        if region_type in {"stress", "tangent"} and role == "Unknown":
            blockers.append(f"Region {region_id} remains ambiguous.")
    return blockers


def _completed_json_helper_call_blockers(
    analysis: dict[str, Any],
    stress_regions: list[dict[str, Any]],
    roles: dict[str, set[str]],
    helper_lift_issue: str = "",
) -> list[str]:
    blockers: list[str] = []
    active_names = roles["seed"] | roles["promote"]
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for row in analysis.get("stress_path_helpers", []) or []:
        if not isinstance(row, dict):
            continue
        callee = str(row.get("callee", "")).upper()
        line_numbers = tuple(_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value))
        if not callee or not line_numbers or callee in INLINEABLE_HELPERS:
            continue
        if not _line_numbers_intersect(line_numbers, stress_regions):
            continue
        rewritten_arguments = sorted(_helper_argument_base_names(row.get("arguments", []) or []) & active_names)
        if not rewritten_arguments:
            continue
        key = (callee, line_numbers)
        if key in seen:
            continue
        seen.add(key)
        if helper_lift_issue:
            blockers.append(
                f"Completed JSON transforms helper call {callee} at lines {list(line_numbers)}, rewriting {rewritten_arguments}, but helper lifting is not yet safe here: {helper_lift_issue}"
            )
    return blockers


def _liftable_helper_roots(
    config: dict[str, Any],
    roles: dict[str, set[str]],
    stress_regions: list[dict[str, Any]],
) -> tuple[str, ...]:
    analysis = _dict(config.get("analysis"))
    active_names = roles["seed"] | roles["promote"]
    roots: list[str] = []
    seen: set[str] = set()
    for row in analysis.get("stress_path_helpers", []) or []:
        if not isinstance(row, dict):
            continue
        callee = str(row.get("callee", "")).upper()
        line_numbers = tuple(_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value))
        if not callee or not line_numbers or callee in INLINEABLE_HELPERS:
            continue
        if not _line_numbers_intersect(line_numbers, stress_regions):
            continue
        rewritten_arguments = _helper_argument_base_names(row.get("arguments", []) or []) & active_names
        if not rewritten_arguments or callee in seen:
            continue
        seen.add(callee)
        roots.append(callee)
    return tuple(roots)


def _local_newton_blockers(config: dict[str, Any], roles: dict[str, set[str]]) -> list[str]:
    return []


def _unsupported_intrinsic_blockers(source_text: str, roles: dict[str, set[str]], stress_regions: list[dict[str, Any]]) -> list[str]:
    unsupported = {"SIGN", "MOD", "ATAN2"}
    promoted = roles["seed"] | roles["promote"]
    if not promoted or not stress_regions:
        return []
    line_numbers = _line_set(stress_regions)
    blockers: list[str] = []
    for number, line in enumerate(source_text.splitlines(), start=1):
        if number not in line_numbers:
            continue
        upper_line = line.upper()
        if not any(re.search(rf"\b{re.escape(name)}\b", upper_line) for name in promoted):
            continue
        for intrinsic in sorted(unsupported):
            if re.search(rf"\b{intrinsic}\s*\(", upper_line):
                blockers.append(f"Unsupported intrinsic {intrinsic} is used with promoted variables on stress path line {number}.")
    return blockers


def _stress_path_io_blockers(config: dict[str, Any], analysis: dict[str, Any], stress_regions: list[dict[str, Any]]) -> list[str]:
    blockers = []
    anchors = _dict(config.get("transformation_anchors"))
    if anchors:
        for row in anchors.get("file_io_regions", []) or []:
            if not isinstance(row, dict):
                continue
            action = str(row.get("action", "user_review_required"))
            if action == "unsafe_block":
                blockers.append(f"File I/O marked unsafe by JSON at lines {row.get('line_numbers', []) or [row.get('start_line', '')]}.")
            elif action == "user_review_required" and _line_numbers_intersect(row.get("line_numbers", [row.get("start_line")]), stress_regions):
                blockers.append(f"File I/O requires JSON classification at lines {row.get('line_numbers', []) or [row.get('start_line', '')]}.")
        return blockers
    for row in analysis.get("file_io", []) or []:
        if _line_numbers_intersect(row.get("line_numbers", []), stress_regions):
            blockers.append(f"File I/O on stress path at lines {row.get('line_numbers', [])}.")
    return blockers


def _uncovered_ddsdde_blockers(
    analysis: dict[str, Any],
    old_tangent_regions: list[dict[str, Any]],
    stress_regions: list[dict[str, Any]],
    shared_setup_regions: list[dict[str, Any]],
    reachable_regions: list[dict[str, Any]] | None = None,
) -> list[str]:
    """DDSDDE assignments the transform would leave writing the old tangent.

    ``reachable_regions``, when given, is the selected routine and the
    routines it can call. An assignment outside all of them is in code this
    transform never executes -- a second model shipped in the same file that
    nothing calls -- and reporting it says nothing true about the source. One
    file lists twenty-two such assignments in a routine its UMAT does not
    call, and they were the whole of its blocker text.
    """
    blockers = []
    first_stress_start = min((region.get("start_line", 0) for region in stress_regions), default=0)
    for assignment in analysis.get("assignments_to_ddsdde", []) or []:
        line_numbers = assignment.get("line_numbers", [])
        try:
            last_assignment_line = max(int(value) for value in line_numbers)
        except (TypeError, ValueError):
            last_assignment_line = 0
        if reachable_regions and not _line_numbers_intersect(line_numbers, reachable_regions):
            continue
        if first_stress_start and last_assignment_line and last_assignment_line < first_stress_start:
            continue
        if _line_numbers_intersect(line_numbers, shared_setup_regions):
            continue
        if not _line_numbers_intersect(assignment.get("line_numbers", []), old_tangent_regions):
            blockers.append(f"DDSDDE assignment is not covered by an old tangent replacement region: {assignment.get('text', '')}")
    return blockers


def _reachable_routine_regions(
    parsed: ParsedFortranSource | None, selected_umat: str
) -> list[dict[str, Any]]:
    """Line spans of the selected routine and every routine it can reach.

    Empty when the source could not be parsed or the routine is not found, and
    an empty result means "do not scope" at every call site -- a span this
    cannot compute must not silently narrow a check.
    """
    if parsed is None or not parsed.subroutines:
        return []
    routines = {routine.upper_name: routine for routine in parsed.subroutines}
    start = (selected_umat or "UMAT").upper()
    if start not in routines:
        return []
    reached: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        for call in build_call_graph(parsed, current):
            callee = call.callee.upper()
            if callee in routines and callee not in reached:
                pending.append(callee)
    regions: list[dict[str, Any]] = []
    for name in sorted(reached):
        span = _selected_routine_span(parsed, name)
        if span:
            regions.append({"region_id": name, "start_line": span[0], "end_line": span[1]})
    return regions


def _tangent_region_context(
    config: dict[str, Any],
    old_tangent_regions: list[dict[str, Any]],
    stress_regions: list[dict[str, Any]],
    source_text: str,
) -> TangentRegionContext:
    anchor_context = _tangent_region_context_from_anchors(config, source_text)
    if anchor_context is not None:
        return anchor_context
    context = TangentRegionContext()
    for region in sorted(old_tangent_regions, key=lambda row: (row.get("start_line", 0), row.get("end_line", 0))):
        helper = is_tangent_helper_region(region, config, source_text)
        output = is_tangent_output_region(region, config, source_text)
        if helper and output:
            context.helper_regions.append(region)
            context.blockers.append(
                f"Region {region.get('region_id', '')} is classified as a tangent helper but directly assigns DDSDDE; select the DDSDDE replacement point explicitly."
            )
        elif output:
            context.output_regions.append(region)
        else:
            context.helper_regions.append(region)
            if "replace" in str(region.get("classification", "")).lower():
                context.blockers.append(
                    f"Region {region.get('region_id', '')} is marked for DDSDDE replacement but no direct DDSDDE assignment was detected."
                )
    last_stress_end = max((region.get("end_line", 0) for region in stress_regions), default=0)
    valid_output_regions = [region for region in context.output_regions if _as_int(region.get("start_line")) > last_stress_end]
    if valid_output_regions:
        context.extraction_region = max(valid_output_regions, key=lambda row: (_as_int(row.get("end_line")), _as_int(row.get("start_line"))))
    return context


def _tangent_region_context_from_anchors(config: dict[str, Any], source_text: str) -> TangentRegionContext | None:
    anchors = _dict(config.get("transformation_anchors"))
    if not anchors:
        return None
    context = TangentRegionContext(anchor_status=str(anchors.get("status", "unknown")))
    old = _dict(anchors.get("old_tangent"))
    context.helper_regions = _anchor_region_rows(
        old.get("helper_regions", []),
        include_roles={"tangent_helper_skip_only", "validation_only_ignore"},
    )
    output_region = _dict(old.get("output_region"))
    output_regions = [r for r in (old.get("output_regions") or []) if isinstance(r, dict) and r]
    if not output_regions and output_region:
        output_regions = [output_region]
    context.output_regions = _anchor_region_rows(output_regions, include_roles={"ddsdde_output_replace"}) if output_regions else []
    # Insert the GETIM extraction after the last (largest end-line) output region.
    context.extraction_region = max(context.output_regions, key=lambda r: _as_int(r.get("end_line"))) if context.output_regions else None
    real_output = _dict(anchors.get("real_output_extraction"))
    ddsdde = _dict(anchors.get("ddsdde_extraction"))
    context.real_output_insert_after_line = _as_int(real_output.get("insert_after_line"))
    context.ddsdde_insert_after_line = _as_int(ddsdde.get("insert_after_line"))
    for row in old.get("helper_regions", []) or []:
        if isinstance(row, dict) and row.get("role") == "user_review_required":
            context.blockers.append(f"Tangent region {row.get('region_id', '')} requires JSON DDSDDE classification.")
    if output_region and output_region.get("role") == "user_review_required":
        context.blockers.append(f"Tangent region {output_region.get('region_id', '')} requires JSON DDSDDE replacement-point classification.")
    return context


def is_tangent_helper_region(region: dict[str, Any], config: dict[str, Any], source_text: str) -> bool:
    classification = str(region.get("classification", "")).lower()
    return "helper" in classification or not is_tangent_output_region(region, config, source_text)


def is_tangent_output_region(region: dict[str, Any], config: dict[str, Any], source_text: str) -> bool:
    if _region_directly_assigns_ddsdde(region, _dict(config.get("analysis"))):
        return True
    preview = str(region.get("preview", ""))
    if _contains_ddsdde_assignment(preview):
        return True
    lines = source_text.splitlines()
    start = _as_int(region.get("start_line"))
    end = _as_int(region.get("end_line"))
    if start > 0 and end >= start:
        return _contains_ddsdde_assignment("\n".join(lines[start - 1 : end]))
    return False


def _region_directly_assigns_ddsdde(region: dict[str, Any], analysis: dict[str, Any]) -> bool:
    for assignment in analysis.get("assignments_to_ddsdde", []) or []:
        if _line_numbers_intersect(assignment.get("line_numbers", []), [region]):
            return True
    return False


def _contains_ddsdde_assignment(text: str) -> bool:
    for line in text.splitlines() or [text]:
        if _is_commented(line):
            continue
        if re.search(r"\bDDSDDE\s*(?:\([^=]*\))?\s*=", line, flags=re.IGNORECASE):
            return True
    return False


def _variable_shapes(config: dict[str, Any], mappings: dict[str, str], ntens: int) -> dict[str, str]:
    shapes: dict[str, str] = {}
    for name, row in _variable_role_items(config).items():
        shape = str(row.get("detected_shape") or row.get("detected shape/dimension") or "").strip()
        shapes[name.upper()] = shape
    for name, shape in _synthetic_real_surface_variables(config).items():
        shapes[name.upper()] = shape
    # NTENS and NSTATV are the names Abaqus uses in its own documentation, not
    # names the source is obliged to use. This file calls its state-variable
    # count NSTATEV:
    #
    #     SUBROUTINE UMAT(...,NTENS,NSTATEV,PROPS,...)
    #     DIMENSION STRESS(NTENS),STATEV(NSTATEV),
    #
    # and declaring the shadow as STATEV_OTI(NSTATV) names a variable the
    # routine does not have. Under the IMPLICIT REAL*8(A-H,O-Z) that
    # ABA_PARAM.INC installs it is not even an error at the point of use --
    # it is a real variable, and the array bound is rejected later with
    # "Variable 'nstatv' cannot appear in the expression". Thirty-six of the
    # discovered sources failed to compile on exactly that.
    #
    # The source's own declared bound wins; the conventional name is the
    # fallback for a source that declares none.
    for key, conventional in (("dstran", "NTENS"), ("stress", "NTENS"),
                              ("statev", "NSTATV")):
        name = mappings.get(key)
        if name:
            shapes[name] = shapes.get(name) or conventional
    return shapes


def _argument_variables(config: dict[str, Any], selected_umat: str) -> set[str]:
    selected = selected_umat.upper() or "UMAT"
    analysis = _dict(config.get("analysis"))
    for row in analysis.get("detected_umat_routines", []) or []:
        if not isinstance(row, dict) or str(row.get("name", "")).upper() != selected:
            continue
        return {str(argument).upper() for argument in row.get("arguments", []) or [] if str(argument)}
    return {name for name, row in _variable_role_items(config).items() if bool(row.get("is_argument"))}


def _finite_strain_enabled(config: dict[str, Any]) -> bool:
    analysis = _dict(config.get("analysis"))
    finite_strain = _dict(analysis.get("finite_strain"))
    return bool(finite_strain.get("dfgrd_driven_stress_update") or finite_strain.get("executable_dfgrd_use"))


def _validation_uses_finite_geometry(config: dict[str, Any]) -> bool:
    validation_settings = _dict(config.get("validation_settings"))
    mode = str(validation_settings.get("material_test_mode", "")).lower()
    if any(token in mode for token in ("finite", "large", "nlgeom")):
        return True
    transformation_settings = _dict(config.get("transformation_settings"))
    return bool(transformation_settings.get("seed_dfgrd1"))


def _roles_with_finite_strain_promotions(config: dict[str, Any], roles: dict[str, set[str]]) -> dict[str, set[str]]:
    updated = {key: set(value) for key, value in roles.items()}
    if not _finite_strain_enabled(config):
        return updated
    analysis = _dict(config.get("analysis"))
    summary = _dict(analysis.get("region_summary"))
    candidates = _upper_set(summary.get("stress_path_variables", [])) | _upper_set(summary.get("upstream_to_stress", []))
    for name in candidates | _finite_kinematic_names_from_analysis(analysis):
        if name in _finite_kinematic_name_set() or name in {"STRESS", "STATEV"}:
            updated["promote"].add(name)
            updated["constant"].discard(name)
            updated["keep_real"].discard(name)
    if "DSTRAN" in updated["seed"]:
        updated["promote"].discard("DSTRAN")
        updated["constant"].discard("DSTRAN")
        updated["keep_real"].discard("DSTRAN")
    return updated


def _roles_with_extra_jacobian_promotions(config: dict[str, Any], roles: dict[str, set[str]]) -> dict[str, set[str]]:
    updated = {key: set(value) for key, value in roles.items()}
    for contract in _parse_extra_jacobian_contracts(config):
        names: set[str] = set()
        seed = str(contract.get("seed_variable") or "").upper()
        out = str(contract.get("output_variable") or "").upper()
        if seed:
            names.add(seed)
        if out:
            names.add(out)
        for ext in contract.get("additional_extractions") or []:
            from_var = str(ext.get("from_output_variable") or "").upper()
            if from_var:
                names.add(from_var)
        for name in names:
            if name in INTRINSIC_TOKEN_NAMES:
                continue
            updated["promote"].add(name)
            updated["constant"].discard(name)
            updated["keep_real"].discard(name)
    return updated


def _written_names_from_analysis(analysis: dict[str, Any]) -> set[str]:
    """Names the source assigns to somewhere."""
    written: set[str] = set()
    for row in analysis.get("detected_variables", []) or []:
        if not isinstance(row, dict):
            continue
        access = row.get("read_write") or row.get("access") or ""
        usage = row.get("detected_usage") or []
        text = f"{access} {' '.join(str(u) for u in usage)}".lower()
        if "write" in text:
            written.add(str(row.get("variable_name", "")).upper())
    return written


def subscript_names(source_text: str, arrays: set[str]) -> set[str]:
    """Names that appear as an array subscript somewhere in this source.

    A Fortran subscript must be of type INTEGER, so a name used as one carries
    no derivative -- there is nothing for it to carry. Promoting one produces
    ``A1_OTI = A1IMP_OTI(TMPELEM_OTI)`` and gfortran refuses it outright:
    "Array index at (1) must be of INTEGER type, found DERIVED".

    That is worth a rule of its own because the usual signals miss it. The
    name in the source that prompted this is TmpElem, assigned from the
    element number NOEL: it begins with T, so the implicit rule makes it REAL
    rather than INTEGER, and it sits on the stress path, so the promotion that
    runs after the classifier picks it up. Its being a subscript is the only
    thing that says what it is.

    Only references to names known to be arrays are read as subscripting, so
    an argument to a function call is not mistaken for one.
    """
    if not arrays:
        return set()
    found: set[str] = set()
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(name) for name in sorted(arrays, key=len, reverse=True))
        + r")\s*\(([^()]*)\)", re.IGNORECASE)
    for line in source_text.splitlines():
        if _is_commented(line):
            continue
        for match in pattern.finditer(line):
            for token in re.findall(r"[A-Za-z_]\w*", match.group(2)):
                found.add(token.upper())
    return found


def _roles_with_stress_path_promotions(
    config: dict[str, Any], roles: dict[str, set[str]], source_text: str = "",
) -> dict[str, set[str]]:
    updated = {key: set(value) for key, value in roles.items()}
    analysis = _dict(config.get("analysis"))
    # A DATA statement is not an assignment, so a name initialised by one and
    # never written again reads here as a variable with no value at all. It is
    # the opposite: a compile-time constant. Being on the stress path promoted
    # it anyway, its shadow was zeroed by the initialiser, and the DATA values
    # never arrived -- so a Voigt identity declared
    #     real*8 xi(6)
    #     data xi/1.d0,1.d0,1.d0,0.d0,0.d0,0.d0/
    # multiplied its whole term by zero, in the stress written back and in
    # every derivative taken from it, with the file compiling and no check
    # failing. The classifier declines these too; this promotion runs after it
    # and overrides it, so declining in both places is what actually keeps
    # them out.
    written = _written_names_from_analysis(analysis)
    data_constants = {
        name for name in data_initialised_names(source_text) if name not in written}
    # A subscript is an INTEGER by the language's own rule, so a name used as
    # one carries no derivative and promoting it emits code gfortran refuses.
    known_arrays = {
        str(name).upper() for name, row in _variable_role_items(config).items()
        if str(row.get("detected_shape") or row.get("detected shape/dimension") or "").strip()}
    subscripts = subscript_names(source_text, known_arrays)
    # Removed, not merely skipped. A subscript can already be in "promote"
    # when this runs -- the contract's own role list carries it -- so
    # declining to add it again leaves it exactly where it was. A name cannot
    # be both an INTEGER subscript and a value carrying a derivative, so this
    # takes it out and says what it is instead.
    for name in sorted(subscripts & updated["promote"]):
        updated["promote"].discard(name)
        updated["keep_real"].add(name)
    summary = _dict(analysis.get("region_summary"))
    path_names = _upper_set(summary.get("stress_path_variables", []))
    role_items = _variable_role_items(config)
    known_variables = set(role_items)
    # An assumed-size dummy has no extent in this routine, so there is nothing
    # to declare a shadow with. This promotion runs after the classifier and
    # overrides it, so declining here as well as there is what actually keeps
    # PROPS(*) out: the classifier had called it constant, and being on the
    # stress path promoted it anyway. The emitted declaration was
    # TYPE(ONUMM6N1) :: PROPS_OTI(*) and its initialisation loop
    # DO OTI_HI = 1, *, which is not a loop. Seven sources failed to compile
    # on that. Guessing which other argument carries the extent would be
    # inventing an interface the source does not state.
    assumed_size = {
        str(name).upper() for name, row in role_items.items()
        if "*" in str(row.get("detected_shape")
                      or row.get("detected shape/dimension") or "")}
    # A Fortran intrinsic is not a variable, and promoting one renames it like
    # one: STRESS = MATMUL(DDSDDE, STRAN + DSTRAN) was emitted as
    # STRESS_OTI = MATMUL_OTI(...), a name declared nowhere, and the file
    # stopped at "Unclassifiable statement" rather than at anything to do with
    # MATMUL. INTRINSIC_TOKEN_NAMES, tested just below, is the region reader's
    # list of scalar maths intrinsics and holds none of the array ones;
    # core.roles keeps the full set the classifier already declines, together
    # with the companion test that makes it safe -- a name the source ever
    # assigns is a variable whatever the set says, so a UMAT may still keep an
    # undeclared accumulator called SUM. This promotion runs after the
    # classifier and overrides it, so declining here as well as there is what
    # actually keeps the name out.
    intrinsic_calls = _INTRINSIC_CALLS - _assigned_names(source_text)
    for name in path_names:
        if (
            name in {"DDSDDE"}
            or name in updated["seed"]
            or name in updated["keep_real"]
            or name in assumed_size
            or name in data_constants
            or name in subscripts
            or name in INTRINSIC_TOKEN_NAMES
            or name in intrinsic_calls
            or (known_variables and name not in known_variables)
        ):
            continue
        updated["promote"].add(name)
        updated["constant"].discard(name)
        updated["keep_real"].discard(name)
    return updated


def _regions_with_finite_strain_path(
    config: dict[str, Any],
    regions: dict[str, list[dict[str, Any]]],
    source_text: str,
    umat_span: tuple[int, int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    updated = {key: list(value) for key, value in regions.items()}
    if not _finite_strain_enabled(config) or not updated["stress"]:
        return updated
    finite_lines = _finite_strain_use_lines(_dict(config.get("analysis")))
    # The deformation gradient is read wherever the file happens to read it,
    # and in a file holding a UEL above its UMAT the element routine reads it
    # first. Spanning from there to the end of the material stress update
    # produced a single region covering both routines, which put the UEL's
    # own helper calls -- and its call to UMAT -- on the material stress path.
    # A line outside the routine being transformed is not on that path.
    if umat_span:
        finite_lines = [line for line in finite_lines
                        if umat_span[0] <= line <= umat_span[1]]
    if not finite_lines:
        return updated
    source_lines = source_text.splitlines()
    path_start = _first_finite_path_assignment_line(source_text, _dict(config.get("analysis")), umat_span)
    if all(_line_numbers_intersect([line], updated["stress"]) for line in finite_lines):
        if not path_start or _line_numbers_intersect([path_start], updated["stress"]):
            return updated
    start_line = min(min(finite_lines), path_start or min(finite_lines), min(_as_int(region.get("start_line")) for region in updated["stress"] if _as_int(region.get("start_line"))))
    end_line = max(max(finite_lines), max(_as_int(region.get("end_line")) for region in updated["stress"] if _as_int(region.get("end_line"))))
    lowest = max(1, umat_span[0]) if umat_span else 1
    highest = min(len(source_lines), umat_span[1]) if umat_span else len(source_lines)
    start_line = max(lowest, int(start_line))
    end_line = min(highest, int(end_line))
    if end_line < start_line:
        return updated
    # The propagation region is one contiguous span from the first
    # finite-strain line to the last stress line, and in a source whose author
    # wrote the tangent between them it swallows the tangent whole. Membership
    # in a stress region wins over membership in a tangent region downstream,
    # so the old DDSDDE block was rewritten in place instead of being
    # commented out, and the keep-real setup between them was rewritten too.
    # A span this synthesises to bridge a gap must not reclassify lines the
    # anchor stage has already classified; it is filled in around them.
    claimed = _line_set(updated["old_tangent"]) | _line_set(updated["shared_setup"])
    claimed = _claimed_lines_whose_result_is_dead(
        source_text, claimed, (start_line, end_line))
    variables = sorted(_finite_kinematic_names_from_analysis(_dict(config.get("analysis"))))
    for index, (span_start, span_end) in enumerate(
            _spans_excluding(start_line, end_line, claimed), start=1):
        updated["stress"].append(
            {
                "region_id": ("FINITE-STRAIN-PROPAGATION" if index == 1
                              else f"FINITE-STRAIN-PROPAGATION-{index}"),
                "start_line": span_start,
                "end_line": span_end,
                "reason": "Executable finite-strain kinematics detected on stress path",
                "classification": "Main stress update, transform with OTIS",
                "variables": variables,
                "preview": "",
            }
        )
    return updated


def _claimed_lines_whose_result_is_dead(
    source_text: str, claimed: set[int], span: tuple[int, int]
) -> set[int]:
    """``claimed`` minus the lines whose assigned name is still read live.

    A span synthesised to bridge a gap must not reclassify lines the anchor
    stage has already classified -- but the anchor stage's old-tangent
    classification is a guess, and where it is too wide it covers a statement
    the rest of the routine depends on. Carving such a line out of the stress
    span hands it to the commenting path, and the transform then emits a
    routine that reads a variable nothing assigns.

    mholla/growth's umat_iso_morph_Abaqus.f is the case: lines 92-94 compute
    ``detf = +dfgrd1(1,1)*(...)`` and are classified as tangent region
    TANGENT-005. Commented out, ``detf`` keeps its declaration, loses its only
    assignment, and is still read by ``sse = (k*(detf - 1.d0)**2 + ...)`` --
    so SSE, a UMAT output argument, was computed from an uninitialised
    variable. The transform reported success, emitted no warning, and the file
    compiled.

    Intermediates that feed only the old tangent stay claimed and are still
    commented out, which is the point of the classification: ``vol`` is
    assigned and read entirely inside the tangent block, so nothing live
    depends on it. The question asked here is only whether a name assigned by
    a claimed line is read by a line that will remain active.
    """
    lines = source_text.splitlines()
    start, end = span
    assigned: dict[int, str] = {}
    for number in sorted(claimed):
        if not (start <= number <= end) or number > len(lines):
            continue
        text = lines[number - 1]
        if _is_commented(text):
            continue
        match = re.match(r"^\s*([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=(?!=)", text)
        if match:
            assigned[number] = match.group(1).upper()
    if not assigned:
        return claimed
    live_reads: set[str] = set()
    for number, text in enumerate(lines, start=1):
        if number in claimed or _is_commented(text):
            continue
        for token in re.findall(r"[A-Za-z_]\w*", text):
            live_reads.add(token.upper())
    return {number for number in claimed
            if assigned.get(number) is None or assigned[number] not in live_reads}


def _spans_excluding(start: int, end: int, excluded: set[int]) -> list[tuple[int, int]]:
    """``start..end`` split into the runs of lines that are not excluded."""
    spans: list[tuple[int, int]] = []
    run_start: int | None = None
    for line in range(start, end + 1):
        if line in excluded:
            if run_start is not None:
                spans.append((run_start, line - 1))
                run_start = None
            continue
        if run_start is None:
            run_start = line
    if run_start is not None:
        spans.append((run_start, end))
    return spans


def _regions_with_local_stress_bridges(regions: dict[str, list[dict[str, Any]]], source_text: str) -> dict[str, list[dict[str, Any]]]:
    updated = {key: list(value) for key, value in regions.items()}
    stress_regions = sorted(updated.get("stress", []), key=lambda row: (_as_int(row.get("start_line")), _as_int(row.get("end_line"))))
    if len(stress_regions) < 2:
        return updated
    source_lines = source_text.splitlines()
    additions: list[dict[str, Any]] = []
    for previous_region, next_region in zip(stress_regions, stress_regions[1:]):
        gap_start = _as_int(previous_region.get("end_line")) + 1
        gap_end = _as_int(next_region.get("start_line")) - 1
        if gap_end < gap_start:
            continue
        executable_lines = [
            line_number
            for line_number in range(gap_start, gap_end + 1)
            if not _is_commented(source_lines[line_number - 1]) and _is_executable_line(source_lines[line_number - 1])
        ]
        if not executable_lines or len(executable_lines) > 3:
            continue
        neighboring_variables = {
            str(name).upper()
            for region in (previous_region, next_region)
            for name in region.get("variables", []) or []
            if str(name)
        }
        assigned_variables: set[str] = set()
        allowed_gap = True
        for line_number in executable_lines:
            line = source_lines[line_number - 1]
            if _is_do_line(line) or _is_end_do_line(line):
                continue
            if re.match(r"^\s*CALL\b", line, flags=re.IGNORECASE):
                allowed_gap = False
                break
            if _is_if_then_line(line) or _is_end_if_line(line) or re.match(r"^\s*ELSE\b", line, flags=re.IGNORECASE):
                allowed_gap = False
                break
            if _is_return_line(line) or re.match(r"^\s*GOTO\b", line, flags=re.IGNORECASE):
                allowed_gap = False
                break
            match = re.match(r"^\s*([A-Za-z_]\w*)(?:\([^=]*\))?\s*=", line, flags=re.IGNORECASE)
            if not match:
                allowed_gap = False
                break
            assigned_variables.add(match.group(1).upper())
        if not allowed_gap or not (assigned_variables & neighboring_variables):
            continue
        additions.append(
            {
                "region_id": f"STRESS-BRIDGE-{gap_start:03d}-{gap_end:03d}",
                "start_line": gap_start,
                "end_line": gap_end,
                "reason": "Short executable bridge between adjacent selected stress regions",
                "classification": "Main stress update, transform with OTIS",
                "variables": sorted(assigned_variables | neighboring_variables),
                "preview": "\n".join(source_lines[gap_start - 1 : gap_end]),
            }
        )
    if additions:
        updated["stress"].extend(additions)
    return updated


def _first_finite_path_assignment_line(
    source_text: str, analysis: dict[str, Any],
    span: tuple[int, int] | None = None,
) -> int:
    """First line in the selected routine that assigns a finite-strain name.

    Scanning the whole file finds assignments in routines that are not being
    transformed. In a source shipping SDVINI above its UMAT the first match is
    ``statev(1)=1.0d0``, thirty lines before the material routine begins, and
    the propagation region built from it began at the subroutine header --
    which is how the routine's dummy arguments came to be renamed to the
    shadow names, leaving a call no caller in the file could satisfy.
    """
    names = _finite_kinematic_names_from_analysis(analysis) | {"STATEV", "STRESS"}
    if not names:
        return 0
    pattern = re.compile(r"^\s*(?:" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")\s*(?:\([^=]*\))?\s*=", flags=re.IGNORECASE)
    for line_number, line in enumerate(source_text.splitlines(), start=1):
        if span and not (span[0] <= line_number <= span[1]):
            continue
        if _is_commented(line) or not _is_executable_line(line):
            continue
        if pattern.search(line):
            return line_number
    return 0


# One definition, in core.roles, so the classifier and this check cannot drift
# apart about what counts as a call rather than a variable.
from umat_oti.core.roles import (  # noqa: E402
    INTRINSIC_CALL_NAMES as _INTRINSIC_CALLS,
    assigned_names as _assigned_names,
    data_initialised_names, defined_function_names as _defined_function_names,
)


def _used_modules_not_defined_here(source_text: str) -> list[str]:
    """Modules this source USEs and does not itself define.

    A USE brings in names -- derived types, generic functions, operators --
    that are not in this file at all. Every one of them reads as ``NAME(...)``
    at a call site, which is indistinguishable from indexing an array unless
    the module can be read, and it cannot be.
    """
    defined = {
        match.group(1).upper()
        for match in re.finditer(r"^\s*MODULE\s+([A-Za-z_]\w*)\s*$", source_text,
                                 flags=re.IGNORECASE | re.MULTILINE)
    }
    used: list[str] = []
    for match in re.finditer(r"^\s*USE\s+([A-Za-z_]\w*)", source_text,
                             flags=re.IGNORECASE | re.MULTILINE):
        name = match.group(1).upper()
        if name not in defined and name not in used:
            used.append(name)
    return used


def _declared_names(parsed: ParsedFortranSource | None) -> set[str]:
    """Every name this source declares, in any routine."""
    if parsed is None:
        return set()
    names: set[str] = set()
    for routine in parsed.subroutines:
        names.update(argument.upper() for argument in routine.args)
        for declaration in routine.declarations:
            names.update(entity.upper_name for entity in declaration.entities)
    return names


def _shape_blockers(
    source_text: str,
    roles: dict[str, set[str]],
    regions: dict[str, list[dict[str, Any]]],
    mappings: dict[str, str],
    variable_shapes: dict[str, str],
    parsed: ParsedFortranSource | None = None,
) -> list[str]:
    blockers: list[str] = []
    region_text = _selected_region_text(source_text, regions["stress"])
    mapped_arrays = {mappings.get("dstran"), mappings.get("stress"), mappings.get("statev")}
    # NAME(...) is indexing only if NAME is an array. A call to an intrinsic,
    # or to a function the source itself defines, reads identically and was
    # being reported as a promoted array with no shape -- FLOAT(NSLPTL) and a
    # crystal-plasticity flow rule named F both blocked a source that has
    # nothing wrong with it.
    # Minus what the source assigns, for the same reason the classifier
    # subtracts it: the intrinsic set includes names a UMAT may legitimately
    # use for its own variables, and a name that carries a value is a variable
    # whatever the set says.
    not_arrays = ((_INTRINSIC_CALLS | _defined_function_names(source_text))
                  - _assigned_names(source_text))
    used_modules = _used_modules_not_defined_here(source_text)
    declared = _declared_names(parsed)
    for name in sorted(roles["seed"] | roles["promote"]):
        if name in mapped_arrays or name.upper() in not_arrays:
            continue
        shape = variable_shapes.get(name, "")
        if shape or not re.search(rf"\b{re.escape(name)}\s*\(", region_text, flags=re.IGNORECASE):
            continue
        # "No confirmed shape" is what a missing declaration looks like from
        # here; it is not why the declaration is missing. When the name is not
        # declared in this source at all and the source USEs a module this
        # source does not contain, the name is a call into that module, and
        # saying "no confirmed shape" sends the reader to look for a DIMENSION
        # statement that was never going to be there.
        if used_modules and name.upper() not in declared:
            blockers.append(
                f"{name} appears as {name}(...) on the stress path but is not "
                f"declared anywhere in this source, which USEs "
                f"{', '.join(used_modules)} without defining it. The "
                f"transformer cannot read that module, so it cannot tell "
                f"whether {name} is an array to promote or a call into it."
            )
            continue
        blockers.append(f"Promoted variable {name} is indexed in a stress region but has no confirmed shape.")
    return blockers


def _data_initialised_shadow_blockers(
    source_text: str, roles: dict[str, set[str]]
) -> list[str]:
    """Refuse to shadow a name whose starting value comes from a DATA statement.

    A shadow is declared and zeroed by the initialiser; nothing carries a DATA
    value into it, and there is no DATA rewriting anywhere in this transformer
    (it is listed among the declared unsupported constructs). A name that is
    DATA-initialised and never assigned is handled before this point -- it is a
    constant and stays real. What is left is the genuinely unhandled case: a
    name that starts from a DATA value and is then assigned. Its shadow would
    begin at zero instead, and every result computed from it before the first
    assignment would be wrong with nothing to show for it.

    Refused rather than emitted, because the alternative is a file that
    compiles, passes every semantic check, and returns a wrong stress.
    """
    initialised = data_initialised_names(source_text)
    if not initialised:
        return []
    return [
        f"{name} takes its starting value from a DATA statement and is also "
        "assigned, so it needs an OTI shadow, and nothing carries a DATA "
        "value into a shadow. The shadow would start at zero instead of the "
        "declared value. DATA initialisation of a promoted variable is not "
        "supported."
        for name in sorted((roles["seed"] | roles["promote"]) & initialised)
    ]


def _transform_source_text(
    *,
    source_text: str,
    parsed: ParsedFortranSource,
    selected_umat: str,
    ntens: int,
    oti_directions: int,
    module_name: str,
    type_name: str,
    roles: dict[str, set[str]],
    regions: dict[str, list[dict[str, Any]]],
    mappings: dict[str, str],
    variable_shapes: dict[str, str],
    argument_variables: set[str],
    lifted_helper_names: set[str],
    tangent_context: TangentRegionContext,
    config: dict[str, Any],
) -> TransformRewrite:
    lines = source_text.splitlines()
    form = parsed.form
    oti_order = int(_dict(config.get("transformation_settings")).get("order", 1) or 1)
    helper_output_surfaces = _helper_output_surfaces(config)
    header_end = _selected_header_end(parsed, selected_umat) or 1
    selected_routine_span = _selected_routine_span(parsed, selected_umat) or (1, len(lines))
    declaration_insert_before = _first_executable_line(parsed, selected_umat) or min(_first_region_start(regions), len(lines) + 1)
    first_stress_start = min(region["start_line"] for region in regions["stress"])
    extraction_region = _expanded_tangent_output_region(lines, tangent_context.extraction_region)
    if extraction_region is not None and (
        _as_int(extraction_region.get("end_line")) < first_stress_start
        or _region_intersects_regions(extraction_region, regions["shared_setup"])
    ):
        extraction_region = None
    extraction_insert_after_line = _post_tangent_insertion_line(lines, extraction_region)
    real_output_insert_after_line = tangent_context.real_output_insert_after_line or extraction_insert_after_line
    ddsdde_insert_after_line = tangent_context.ddsdde_insert_after_line or extraction_insert_after_line
    seed_dfgrd1_enabled = _validation_uses_finite_geometry(config)
    seed_insert_before_line = _seed_insert_before_line(config) or declaration_insert_before
    if seed_insert_before_line and seed_insert_before_line < declaration_insert_before:
        seed_insert_before_line = declaration_insert_before
    seed_insert_before_line = _safe_seed_insert_before_line(lines, seed_insert_before_line or first_stress_start, declaration_insert_before)
    tangent_regions_to_skip = _tangent_skip_regions(
        lines,
        tangent_context,
        extraction_region,
        regions["stress"],
        regions["shared_setup"],
    )
    old_region_by_line = _region_by_line(tangent_regions_to_skip)
    removable_io_by_line = _removable_file_io_by_line(config)
    stress_line_numbers = _line_set(regions["stress"])
    lifted_helper_argument_shadows = _lifted_helper_argument_shadow_names(config, regions["stress"], lifted_helper_names, variable_shapes)
    # Shapes are collected across the whole file under bare names, and two
    # routines may declare the same name differently -- these UEL files
    # declare AUX1(NTENS,NDOFEL) in the element routine and AUX1(NTENS,NTENS)
    # in the material routine below it. The file-wide answer won, so the
    # shadow emitted inside UMAT carried the UEL's second bound, and NDOFEL is
    # a dummy argument of the UEL. The routine's own declaration is the one
    # that governs its own declarations.
    variable_shapes = _shapes_declared_in_selected_routine(parsed, selected_umat, variable_shapes)
    shadow_variable_names = _shadow_variable_names_for_selected_routine(lines, selected_routine_span, roles, argument_variables)
    # Lifted-helper argument surfaces are shadowed in the lifted module, not
    # here, so only the ones this routine actually mentions belong in its
    # declarations. Adding them unfiltered declared AUX1_OTI(NTENS, NDOFEL)
    # inside a UMAT that has no NDOFEL -- it is a dummy argument of the UEL
    # above it -- and gfortran rejected the bound rather than the name, in
    # nine sources.
    shadow_variable_names.update(
        _names_present_in_span(lines, selected_routine_span,
                               lifted_helper_argument_shadows, argument_variables))
    shadow_variable_names.update(_synthetic_real_surface_variables(config))
    # A name with no extent cannot be given a shadow. An assumed-size dummy --
    # PROPS(*), SVARS(*) -- has its extent only in the caller, so
    # TYPE(ONUMM6N1) :: PROPS_OTI(*) is not a declaration and the
    # initialisation written beside it, DO OTI_HI = 1, *, is not a loop.
    # Filtered here rather than at each contributor because shadows arrive
    # from three places -- the role classifier, the stress-path promotion that
    # overrides it, and the lifted-helper argument surfaces -- and PROPS
    # reached the emitter through the third after the first two had both
    # declined it. Guessing which other argument carries the extent would be
    # inventing an interface the source does not state; the name stays real,
    # and if the stress path reads it the seed-consumption and structural-zero
    # checks report the truncation.
    assumed_size = {
        str(name).upper() for name, shape in variable_shapes.items()
        if "*" in str(shape or "")}
    shadow_variable_names.difference_update(assumed_size)
    replacement_names = {name: f"{name}_OTI" for name in sorted(shadow_variable_names)}
    sprinc_equivalent_stress_rewrites, sprinc_formula_skip_lines = _sprinc_equivalent_stress_rewrites(
        source_lines=lines,
        stress_line_numbers=stress_line_numbers,
    )
    shadow_variables = sorted(shadow_variable_names)

    output: list[str] = []
    initialization_inserted = False
    real_extraction_inserted = False
    tangent_extraction_inserted = False
    pure_seed_tangent_bridge_inserted = False
    extraction_insertion_region_id = ""
    helper_continuation_skip_lines: set[int] = set()
    projected_vector_sources: dict[str, str] = {}
    helper_call_sync_names = shadow_variable_names - (roles["seed"] | roles["promote"])
    shadow_sync_dirty_names: set[str] = set()
    shadow_sync_dirty_branch_stack: list[set[str]] = []
    pure_seed_tangent_bridge_lines = _pure_seed_tangent_bridge_lines(
        source_lines=lines,
        form=form,
        config=config,
        stress_regions=regions["stress"],
        shared_setup_regions=regions["shared_setup"],
        tangent_output_regions=tangent_context.output_regions,
        mappings=mappings,
        replacement_names=replacement_names,
        type_name=type_name,
        ntens=ntens,
        seed_dfgrd1_active=_dfgrd1_carries_the_seed(roles, mappings, seed_dfgrd1_enabled),
    )
    preserved_ddsdde_output_lines = _preserved_ddsdde_output_lines(
        form=form,
        config=config,
        extraction_region=extraction_region,
        mappings=mappings,
        replacement_names=replacement_names,
        type_name=type_name,
    )
    ddsdde_output_method = "REAL(explicit DDSDDE output formula)" if preserved_ddsdde_output_lines else "GETIM(STRESS_OTI(i), j)"
    ddsdde_uses_getim = not preserved_ddsdde_output_lines
    extra_jacobian_after_line_inserts, extra_jacobian_replace_lines = _extra_jacobian_splice_maps(
        config=config,
        ntens=ntens,
        form=form,
    )
    original_line_to_output_index: dict[int, int] = {}

    for line_number, line in enumerate(lines, start=1):
        output.append(line)
        original_line_to_output_index[line_number] = len(output) - 1
        if _line_in_span(line_number, selected_routine_span):
            branch_kind = _branch_block_kind(line)
            if branch_kind == "if_then":
                shadow_sync_dirty_branch_stack.append(set(shadow_sync_dirty_names))
            elif branch_kind in ("else", "else_if") and shadow_sync_dirty_branch_stack:
                shadow_sync_dirty_names = set(shadow_sync_dirty_branch_stack[-1]) | shadow_sync_dirty_names
            elif branch_kind == "end_if" and shadow_sync_dirty_branch_stack:
                shadow_sync_dirty_names |= shadow_sync_dirty_branch_stack.pop()
        if line_number == header_end:
            output.append(_module_use_line(form, module_name, oti_directions))
        if line_number + 1 == declaration_insert_before:
            output.extend(
                _declaration_lines(
                    form,
                    type_name,
                    shadow_variables,
                    variable_shapes,
                    synthetic_real_variables={
                        **_synthetic_real_surface_variables(config),
                        **_synthetic_real_jacobian_targets(config),
                    },
                    order=oti_order,
                )
            )
        if line_number + 1 == seed_insert_before_line and not initialization_inserted:
            output.extend(
                _initialization_lines(
                    form,
                    mappings,
                    roles,
                    ntens,
                    shadow_variables,
                    variable_shapes,
                    argument_variables,
                    lifted_helper_argument_shadows,
                    seed_dfgrd1=seed_dfgrd1_enabled,
                )
            )
            initialization_inserted = True
        if line_number in helper_continuation_skip_lines:
            output.pop()
            output.append(_comment_old_line(form, line))
            continue
        if line_number in removable_io_by_line:
            output.pop()
            output.append(_comment_old_line(form, line))
            continue
        if line_number in sprinc_formula_skip_lines:
            output.pop()
            output.append(_comment_old_line(form, line))
            continue
        logical_branch_line, branch_continuation_lines = _logical_branch_line(lines, line_number, form)
        # Never rewrite a comment into code. A commented-out branch still reads
        # as one once the marker is dropped while stitching continuations, and
        # this source carries "C      IF (STATEV(1).EQ.0.) THEN" as a note
        # about a change its author made. Emitting that as a live statement is
        # not a formatting slip: it puts a condition the author deliberately
        # removed back into the model.
        if (_line_in_span(line_number, selected_routine_span)
                and not _is_commented(line)
                and _is_promoted_branch_line(logical_branch_line or line, replacement_names)):
            output[-1] = _transform_executable_line(logical_branch_line or line, replacement_names, type_name, lifted_helper_names)
            helper_continuation_skip_lines.update(branch_continuation_lines)
            if real_output_insert_after_line == line_number and not real_extraction_inserted:
                if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                    output.extend(pure_seed_tangent_bridge_lines)
                    pure_seed_tangent_bridge_inserted = True
                output.extend(_real_extraction_lines(form, mappings, roles, ntens, variable_shapes))
                real_extraction_inserted = True
            if ddsdde_insert_after_line == line_number and not tangent_extraction_inserted:
                if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                    output.extend(pure_seed_tangent_bridge_lines)
                    pure_seed_tangent_bridge_inserted = True
                output.extend(preserved_ddsdde_output_lines or _ddsdde_extraction_lines(form, mappings, ntens, oti_order, oti_directions))
                tangent_extraction_inserted = True
                extraction_insertion_region_id = str(extraction_region.get("region_id", "")) if extraction_region else "before RETURN"
            continue
        if line_number in old_region_by_line and line_number not in stress_line_numbers:
            output.pop()
            output.append(_comment_old_line(form, line))
            if real_output_insert_after_line == line_number and not real_extraction_inserted:
                if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                    output.extend(pure_seed_tangent_bridge_lines)
                    pure_seed_tangent_bridge_inserted = True
                output.extend(_real_extraction_lines(form, mappings, roles, ntens, variable_shapes))
                real_extraction_inserted = True
            if ddsdde_insert_after_line == line_number and not tangent_extraction_inserted:
                if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                    output.extend(pure_seed_tangent_bridge_lines)
                    pure_seed_tangent_bridge_inserted = True
                output.extend(preserved_ddsdde_output_lines or _ddsdde_extraction_lines(form, mappings, ntens, oti_order, oti_directions))
                tangent_extraction_inserted = True
                extraction_insertion_region_id = str(extraction_region.get("region_id", "")) if extraction_region else "before RETURN"
            continue
        if _line_in_span(line_number, selected_routine_span) and line_number not in stress_line_numbers:
            dirty_assignment_line, _ = _logical_assignment_line(lines, line_number, form)
            shadow_sync_dirty_names.update(_assigned_shadow_names(dirty_assignment_line or line, helper_call_sync_names))
            promoted_assignment_targets = _assigned_shadow_names(dirty_assignment_line or line, roles["promote"])
            # Also rewrite an assignment to a genuine kept-real variable (one
            # with no OTI shadow of its own, e.g. the output SPD) whose RHS reads
            # promoted shadow variables: SPD = DEQPL*(SYIEL0+SYIELD)/TWO. The
            # reads must become the OTI shadows wrapped in REAL(...), otherwise
            # they reference the now-undefined original names. Deliberately
            # narrow: skip comments, control flow, WRITE/READ/CALL, and any LHS
            # that itself has a shadow (those keep their real value / shadow copy).
            reads_promoted_reference = False
            candidate = dirty_assignment_line or line
            if replacement_names and not promoted_assignment_targets and not _is_commented(candidate):
                assign = re.match(r"^\s*([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=\s*(.+)$", candidate)
                if (
                    assign
                    and assign.group(1).upper() not in replacement_names
                    and not re.match(r"^\s*(?:IF|DO|ELSE|END|WRITE|READ|CALL|GO\s*TO|GOTO)\b", candidate, flags=re.IGNORECASE)
                ):
                    # Two ways a promoted name appears without being read.
                    # The note the author left beside the statement --
                    # "cr_pos = props(4)  ! critical stress for growth" reads
                    # no promoted name, the word is in the comment -- and the
                    # interior of a literal, where the D of "1.d-12" is not a
                    # reference to a variable named D. Strip the comment, then
                    # the literals; what is left is what the statement reads.
                    rhs = without_real_literals(
                        _statement_without_inline_comment(assign.group(2)))
                    reads_promoted_reference = any(
                        re.search(rf"\b{re.escape(name)}\b", rhs, flags=re.IGNORECASE) for name in replacement_names
                    )
            if (
                (promoted_assignment_targets or reads_promoted_reference)
                and not re.match(r"^\s*CALL\b", line, flags=re.IGNORECASE)
                and seed_insert_before_line
                and line_number >= seed_insert_before_line
            ):
                output[-1] = _transform_executable_line(line, replacement_names, type_name, lifted_helper_names)
                shadow_sync_dirty_names.difference_update(_assigned_shadow_names(line, helper_call_sync_names))
        if line_number in stress_line_numbers:
            sprinc_rewrite = sprinc_equivalent_stress_rewrites.get(line_number)
            if sprinc_rewrite is not None:
                output.pop()
                output.extend(
                    _sprinc_equivalent_stress_lines(
                        form,
                        stress_name=_replace_role_references(sprinc_rewrite["stress_name"], replacement_names),
                        pj_name=_replace_role_references(sprinc_rewrite["pj_name"], replacement_names),
                    )
                )
                continue
            projected_dstres_lines, projected_dstres_skip_lines = _rewrite_projected_dstres_bundle(
                source_lines=lines,
                start_line=line_number,
                form=form,
                replacement_names=replacement_names,
                projected_vector_sources=projected_vector_sources,
            )
            if projected_dstres_lines:
                output.pop()
                output.extend(
                    _transform_executable_line(inline_line, {}, type_name, set())
                    for inline_line in projected_dstres_lines
                )
                helper_continuation_skip_lines.update(projected_dstres_skip_lines)
                continue
            # Same guard as the branch stitcher above: stitching drops the
            # fixed-form comment marker, so a commented-out assignment reads
            # as a live one. A plain comment still falls through to
            # _transform_executable_line below, which keeps its marker while
            # renaming tokens inside it -- that is harmless and is left alone.
            logical_assignment_line, assignment_continuation_lines = (
                (None, []) if _is_commented(line)
                else _logical_assignment_line(lines, line_number, form))
            if logical_assignment_line:
                output[-1] = _transform_executable_line(logical_assignment_line, replacement_names, type_name, lifted_helper_names)
                shadow_sync_dirty_names.difference_update(_assigned_shadow_names(logical_assignment_line, helper_call_sync_names))
                helper_continuation_skip_lines.update(assignment_continuation_lines)
                continue
            helper_call_line, continuation_lines = (
                (None, []) if _is_commented(line)
                else _logical_helper_call_line(lines, line_number, form))
            projected_ddstra_capture = _capture_projected_ddstra_helper_call(helper_call_line or line, replacement_names, ntens)
            if projected_ddstra_capture is not None:
                input_name, output_name = projected_ddstra_capture
                projected_vector_sources[output_name] = input_name
                output.pop()
                output.append(_comment_line(form, "OTIS deferred projected DSTRAN vector; DSTRES rewritten directly downstream"))
                helper_continuation_skip_lines.update(continuation_lines)
                continue
            helper_sync_lines, synced_helper_names = _helper_shadow_sync_lines(
                helper_call_line or line,
                helper_call_sync_names,
                shadow_sync_dirty_names,
                form,
                variable_shapes,
            )
            inlined_helper = _inline_pure_arithmetic_helper_call(helper_call_line or line, replacement_names, form, variable_shapes, ntens)
            if inlined_helper:
                output.pop()
                output.extend(helper_sync_lines)
                shadow_sync_dirty_names.difference_update(synced_helper_names)
                output.extend(
                    _transform_executable_line(inline_line, {}, type_name, set())
                    for inline_line in inlined_helper
                )
                helper_continuation_skip_lines.update(continuation_lines)
                continue
            if helper_sync_lines:
                output.pop()
                output.extend(helper_sync_lines)
                shadow_sync_dirty_names.difference_update(synced_helper_names)
                output.append(
                    _transform_executable_line(
                        helper_call_line or line,
                        replacement_names,
                        type_name,
                        lifted_helper_names,
                        helper_output_surfaces,
                    )
                )
                output.extend(_helper_surface_sync_lines(form, helper_call_line or line, helper_output_surfaces))
                helper_continuation_skip_lines.update(continuation_lines)
                continue
            output[-1] = _transform_executable_line(
                helper_call_line or line,
                replacement_names,
                type_name,
                lifted_helper_names,
                helper_output_surfaces,
            )
            output.extend(_helper_surface_sync_lines(form, helper_call_line or line, helper_output_surfaces))
            shadow_sync_dirty_names.difference_update(_assigned_shadow_names(helper_call_line or line, helper_call_sync_names))
            helper_continuation_skip_lines.update(continuation_lines)
        elif _line_in_span(line_number, selected_routine_span) and _is_promoted_branch_line(line, replacement_names):
            output[-1] = _transform_executable_line(line, replacement_names, type_name, lifted_helper_names)
            shadow_sync_dirty_names.difference_update(_assigned_shadow_names(line, helper_call_sync_names))
        if real_output_insert_after_line == line_number and not real_extraction_inserted:
            if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                output.extend(pure_seed_tangent_bridge_lines)
                pure_seed_tangent_bridge_inserted = True
            output.extend(_real_extraction_lines(form, mappings, roles, ntens, variable_shapes))
            real_extraction_inserted = True
        if ddsdde_insert_after_line == line_number and not tangent_extraction_inserted:
            if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                output.extend(pure_seed_tangent_bridge_lines)
                pure_seed_tangent_bridge_inserted = True
            output.extend(preserved_ddsdde_output_lines or _ddsdde_extraction_lines(form, mappings, ntens, oti_order, oti_directions))
            tangent_extraction_inserted = True
            extraction_insertion_region_id = str(extraction_region.get("region_id", "")) if extraction_region else "before RETURN"
        # "Before RETURN" means before the selected routine's RETURN. A file
        # that holds the UMAT below a UEL, or below any other subprogram,
        # reaches a RETURN long before the routine being transformed begins,
        # and the fallback fired there: the real STRESS copy and the GETIM
        # tangent extraction were written into the element routine, which has
        # neither STRESS_OTI nor DDSDDE in scope, and the material routine ran
        # to its own RETURN with no extraction at all. Both flags were then
        # set, so nothing downstream reported a gap.
        if (_is_return_line(line) and not real_extraction_inserted
                and _line_in_span(line_number, selected_routine_span)):
            output.insert(len(output) - 1, _comment_line(form, "OTIS real extraction inserted before RETURN"))
            if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                output[len(output) - 1:len(output) - 1] = pure_seed_tangent_bridge_lines
                pure_seed_tangent_bridge_inserted = True
            output[len(output) - 1:len(output) - 1] = _real_extraction_lines(form, mappings, roles, ntens, variable_shapes)
            real_extraction_inserted = True
        if (_is_return_line(line) and not tangent_extraction_inserted
                and _line_in_span(line_number, selected_routine_span)):
            output.insert(len(output) - 1, _comment_line(form, "OTIS derivative extraction inserted before RETURN"))
            if ddsdde_uses_getim and pure_seed_tangent_bridge_lines and not pure_seed_tangent_bridge_inserted:
                output[len(output) - 1:len(output) - 1] = pure_seed_tangent_bridge_lines
                pure_seed_tangent_bridge_inserted = True
            output[len(output) - 1:len(output) - 1] = preserved_ddsdde_output_lines or _ddsdde_extraction_lines(form, mappings, ntens, oti_order, oti_directions)
            tangent_extraction_inserted = True
            extraction_insertion_region_id = "before RETURN"
        if line_number >= selected_routine_span[1]:
            if line_number < len(lines):
                output.extend(lines[line_number:])
            break
    if not initialization_inserted:
        insert_line = _safe_seed_insert_before_line(lines, first_stress_start, declaration_insert_before)
        insert_at = max(min(insert_line - 1, len(output)), 0)
        output[insert_at:insert_at] = _initialization_lines(
            form,
            mappings,
            roles,
            ntens,
            shadow_variables,
            variable_shapes,
            argument_variables,
            lifted_helper_argument_shadows,
            seed_dfgrd1=seed_dfgrd1_enabled,
        )
    _apply_extra_jacobian_splices(
        output=output,
        original_line_to_output_index=original_line_to_output_index,
        after_inserts=extra_jacobian_after_line_inserts,
        replace_inserts=extra_jacobian_replace_lines,
        original_lines=lines,
        form=form,
    )
    transformed_source = "\n".join(output) + "\n"
    if form == "fixed":
        transformed_source = _wrap_fixed_form_source(transformed_source)
    semantic_checks, _ = _semantic_checks(
        transformed_source=transformed_source,
        form=form,
        module_name=module_name,
        type_name=type_name,
        roles=roles,
        regions=regions,
        mappings=mappings,
        tangent_context=tangent_context,
        extraction_insertion_region_id=extraction_insertion_region_id,
        ddsdde_output_method=ddsdde_output_method,
        config={},
    )
    return TransformRewrite(
        source=transformed_source,
        extraction_insertion_region_id=extraction_insertion_region_id,
        extraction_inserted_after_stress_update=bool(semantic_checks.get("ddsdde_extraction_after_selected_stress_regions")),
        ddsdde_output_method=ddsdde_output_method,
        tangent_helper_regions_skipped=tangent_context.helper_regions,
        tangent_output_regions_replaced=tangent_context.output_regions,
    )


def _tangent_skip_regions(
    source_lines: list[str],
    tangent_context: TangentRegionContext,
    extraction_region: dict[str, Any] | None,
    stress_regions: list[dict[str, Any]],
    shared_setup_regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    first_stress_start = min((_as_int(region.get("start_line")) for region in stress_regions), default=0)
    regions: list[dict[str, Any]] = []
    for region in tangent_context.helper_regions:
        expanded_region = _expanded_tangent_helper_region(source_lines, region)
        if first_stress_start and _as_int(expanded_region.get("end_line")) < first_stress_start:
            continue
        if _region_intersects_regions(expanded_region, shared_setup_regions):
            continue
        regions.append(expanded_region)
    extraction_region_id = str((tangent_context.extraction_region or {}).get("region_id", ""))
    for region in tangent_context.output_regions:
        expanded_region = _expanded_tangent_output_region(source_lines, region) or region
        if first_stress_start and _as_int(expanded_region.get("end_line")) < first_stress_start:
            continue
        if _region_intersects_regions(expanded_region, shared_setup_regions):
            continue
        if extraction_region and str(region.get("region_id", "")) == extraction_region_id:
            regions.append(extraction_region)
            continue
        regions.append(expanded_region)
    if not extraction_region or not tangent_context.helper_regions:
        return regions
    helper_start = min(_as_int(region.get("start_line")) for region in tangent_context.helper_regions)
    extraction_start = _as_int(extraction_region.get("start_line"))
    gap_end = extraction_start - 1
    for line_number in range(extraction_start - 1, helper_start - 1, -1):
        if _is_end_if_line(source_lines[line_number - 1]):
            gap_end = line_number - 1
            break
    if helper_start and gap_end >= helper_start:
        legacy_body_region = {
            "region_id": f"{extraction_region.get('region_id', 'TANGENT')}-LEGACY-BODY",
            "start_line": helper_start,
            "end_line": gap_end,
            "classification": "Legacy tangent helper/body skipped for OTIS extraction",
        }
        if not _region_intersects_regions(legacy_body_region, stress_regions):
            regions.append(legacy_body_region)
    return regions


def _seed_insert_before_line(config: dict[str, Any]) -> int:
    anchors = _dict(config.get("transformation_anchors"))
    if not anchors:
        return 0
    return _as_int(_dict(anchors.get("seed_insertion")).get("line_before"))


def _removable_file_io_by_line(config: dict[str, Any]) -> dict[int, dict[str, Any]]:
    anchors = _dict(config.get("transformation_anchors"))
    result: dict[int, dict[str, Any]] = {}
    for row in anchors.get("file_io_regions", []) or []:
        if not isinstance(row, dict) or row.get("action") != "remove_from_transformed_path":
            continue
        start = _as_int(row.get("start_line"))
        end = _as_int(row.get("end_line")) or start
        for line_number in range(start, end + 1):
            result[line_number] = row
    return result


def _region_assigns_output(source_lines: list[str], region: dict[str, Any]) -> bool:
    start = _as_int(region.get("start_line"))
    end = _as_int(region.get("end_line"))
    if not start or not end or end < start:
        return False
    for line in source_lines[start - 1 : end]:
        if _is_commented(line):
            continue
        if re.search(r"\b(?:STRESS|STATEV)\s*(?:\([^=]*\))?\s*=", line, flags=re.IGNORECASE):
            return True
    return False


def _expanded_tangent_output_region(source_lines: list[str], region: dict[str, Any] | None) -> dict[str, Any] | None:
    if not region:
        return None
    start = _as_int(region.get("start_line"))
    end = _as_int(region.get("end_line"))
    if not start or not end:
        return region
    while start > 1 and _is_do_line(source_lines[start - 2]):
        start -= 1
    while end < len(source_lines) and _is_end_do_line(source_lines[end]):
        end += 1
    if_balance = _if_block_balance(source_lines[start - 1 : end])
    while if_balance > 0 and end < len(source_lines):
        end += 1
        if_balance = _if_block_balance(source_lines[start - 1 : end])
    expanded = dict(region)
    expanded["start_line"] = start
    expanded["end_line"] = end
    return expanded


def _expanded_tangent_helper_region(source_lines: list[str], region: dict[str, Any]) -> dict[str, Any]:
    start = _as_int(region.get("start_line"))
    end = _as_int(region.get("end_line"))
    if not start or not end:
        return region
    bridge_steps = 0
    while start > 1 and bridge_steps < 6:
        previous_line_number = _previous_executable_line_number(source_lines, start - 1)
        if previous_line_number != start - 1:
            break
        previous_line = source_lines[previous_line_number - 1]
        current_text = "\n".join(source_lines[start - 1 : end])
        lhs = _simple_assignment_lhs(previous_line)
        helper_names = _helper_call_base_names(previous_line)
        if lhs and re.search(rf"\b{re.escape(lhs)}\b", current_text, flags=re.IGNORECASE):
            start = previous_line_number
            bridge_steps += 1
            continue
        if helper_names and any(re.search(rf"\b{re.escape(name)}\b", current_text, flags=re.IGNORECASE) for name in helper_names):
            start = previous_line_number
            bridge_steps += 1
            continue
        break
    do_balance = _do_block_balance(source_lines[start - 1 : end])
    while do_balance > 0 and end < len(source_lines):
        end += 1
        do_balance = _do_block_balance(source_lines[start - 1 : end])
    if_balance = _if_block_balance(source_lines[start - 1 : end])
    while if_balance > 0 and end < len(source_lines):
        end += 1
        if_balance = _if_block_balance(source_lines[start - 1 : end])
    bridge_steps = 0
    while end < len(source_lines) and bridge_steps < 4:
        next_line_number = _next_executable_line_number(source_lines, end + 1)
        if next_line_number != end + 1:
            break
        next_line = source_lines[next_line_number - 1]
        current_text = "\n".join(source_lines[start - 1 : end])
        lhs = _simple_assignment_lhs(next_line)
        helper_names = _helper_call_base_names(next_line)
        if lhs and re.search(rf"\b{re.escape(lhs)}\b", current_text, flags=re.IGNORECASE):
            end = next_line_number
            bridge_steps += 1
            continue
        if helper_names and any(re.search(rf"\b{re.escape(name)}\b", current_text, flags=re.IGNORECASE) for name in helper_names):
            end = next_line_number
            bridge_steps += 1
            continue
        break
    expanded = dict(region)
    expanded["start_line"] = start
    expanded["end_line"] = end
    return expanded


def _if_block_balance(lines: list[str]) -> int:
    balance = 0
    for line in lines:
        if _is_end_if_line(line):
            balance -= 1
        elif _is_if_then_line(line):
            balance += 1
    return balance


def _do_block_balance(lines: list[str]) -> int:
    balance = 0
    for line in lines:
        if _is_end_do_line(line):
            balance -= 1
        elif _is_do_line(line):
            balance += 1
    return balance


def _post_tangent_insertion_line(source_lines: list[str], extraction_region: dict[str, Any] | None) -> int:
    if not extraction_region:
        return 0
    end = _as_int(extraction_region.get("end_line"))
    if not end:
        return 0
    for line_number in range(end + 1, len(source_lines) + 1):
        line = source_lines[line_number - 1]
        if _is_return_line(line):
            break
        if _is_end_if_line(line):
            return line_number
    return end


def _safe_seed_insert_before_line(source_lines: list[str], requested_line: int, declaration_insert_before: int) -> int:
    insert_before = requested_line or declaration_insert_before or 1
    if insert_before < 1:
        insert_before = 1
    previous_line = _previous_executable_line_number(source_lines, insert_before - 1)
    while previous_line >= declaration_insert_before and previous_line > 0:
        line = source_lines[previous_line - 1]
        if not (_is_do_line(line) or _is_if_then_line(line)):
            break
        insert_before = previous_line
        previous_line = _previous_executable_line_number(source_lines, previous_line - 1)
    return max(insert_before, declaration_insert_before or 1)


def _previous_executable_line_number(source_lines: list[str], end_line: int) -> int:
    for line_number in range(end_line, 0, -1):
        line = source_lines[line_number - 1]
        if _is_commented(line) or not _is_executable_line(line):
            continue
        return line_number
    return 0


def _next_executable_line_number(source_lines: list[str], start_line: int) -> int:
    for line_number in range(start_line, len(source_lines) + 1):
        line = source_lines[line_number - 1]
        if _is_commented(line) or not _is_executable_line(line):
            continue
        return line_number
    return 0


def _simple_assignment_lhs(line: str) -> str:
    if _is_commented(line) or re.match(r"^\s*CALL\b", line, flags=re.IGNORECASE):
        return ""
    if _is_do_line(line) or _is_end_do_line(line) or _is_if_then_line(line) or _is_end_if_line(line):
        return ""
    match = re.match(r"^\s*([A-Za-z_]\w*)(?:\([^=]*\))?\s*=", line, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _helper_call_base_names(line: str) -> set[str]:
    match = re.match(r"^\s*CALL\s+\w+\s*\((.*)\)\s*$", line, flags=re.IGNORECASE)
    if not match:
        return set()
    names = set()
    for argument in _split_call_arguments(match.group(1)):
        name = _base_argument_name(argument)
        if name:
            names.add(name)
    return names


def _declaration_lines(
    form: str,
    type_name: str,
    shadow_variables: list[str],
    variable_shapes: dict[str, str],
    synthetic_real_variables: dict[str, str] | None = None,
    order: int = 1,
) -> list[str]:
    lines = [_stmt(form, "INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK")]
    lines.append(_stmt(form, f"TYPE({type_name}) :: OTI_HX, OTI_HY, OTI_HTR"))
    if order and order > 1:
        # Scratch for the higher-order Jacobian side file (see
        # _higher_order_jacobian_lines). GETOUTDIR gives Abaqus's output directory
        # so the file lands there regardless of the solver's working directory.
        lines.append(_stmt(form, "INTEGER :: IOTIHJ, IOTILN"))
        lines.append(_stmt(form, "CHARACTER(256) :: OTI_OUTDIR"))
    for name, shape in sorted((synthetic_real_variables or {}).items()):
        suffix = f"({shape})" if shape else ""
        lines.append(_stmt(form, f"REAL(8) :: {name}{suffix}"))
    for name in shadow_variables:
        shape = variable_shapes.get(name, "")
        suffix = f"({shape})" if shape else ""
        lines.append(_stmt(form, f"TYPE({type_name}) :: {name}_OTI{suffix}"))
    return lines


def _bound(variable_shapes: dict[str, str], name: str, conventional: str) -> str:
    """The extent to count to for ``name``, as this source declares it.

    A copy loop has to agree with the declaration it copies into. Emitting
    ``DO OTI_I = 1, NSTATV`` beside ``STATEV_OTI(NSTATEV)`` disagrees with it
    twice over -- once about the name, once about the length.
    """
    shape = (variable_shapes or {}).get(name, "").strip()
    if not shape or "," in shape or "*" in shape:
        return conventional
    return shape


def _initialization_lines(
    form: str,
    mappings: dict[str, str],
    roles: dict[str, set[str]],
    ntens: int,
    shadow_variables: list[str],
    variable_shapes: dict[str, str],
    argument_variables: set[str],
    lifted_helper_argument_shadows: set[str],
    seed_dfgrd1: bool = False,
) -> list[str]:
    lines = [_comment_line(form, "OTIS seed initialization from GUI configuration")]
    lines.extend(_shadow_default_lines(form, shadow_variables, variable_shapes))
    dstran = mappings.get("dstran", "DSTRAN")
    stress = mappings.get("stress", "STRESS")
    statev = mappings.get("statev", "STATEV")
    # DSTRAN_OTI can only exist where DSTRAN does. A material routine reached
    # through an Abaqus wrapper is handed the deformation gradient and not the
    # strain increment -- thirteen of the discovered sources are written that
    # way -- and there this copy read a dummy argument the routine does not
    # have while assigning a shadow that was never declared. gfortran reported
    # both as undeclared functions, which is the last thing they are.
    dstran_in_scope = dstran in set(shadow_variables)
    if dstran in roles["seed"] and dstran_in_scope:
        lines.extend(
            [
                _stmt(form, "DO OTI_I = 1, NTENS"),
                _stmt(form, f"   {dstran}_OTI(OTI_I) = {dstran}(OTI_I)"),
                _stmt(form, "END DO"),
            ]
        )
    if stress in roles["promote"]:
        lines.extend(
            [
                _stmt(form, "DO OTI_I = 1, NTENS"),
                _stmt(form, f"   {stress}_OTI(OTI_I) = {stress}(OTI_I)"),
                _stmt(form, "END DO"),
            ]
        )
    if statev in roles["promote"]:
        lines.extend(
            [
                _stmt(form, f"DO OTI_I = 1, {_bound(variable_shapes, statev, 'NSTATV')}"),
                _stmt(form, f"   {statev}_OTI(OTI_I) = {statev}(OTI_I)"),
                _stmt(form, "END DO"),
            ]
        )
    copied = {dstran, stress, statev}
    copy_shadow_names = set(argument_variables)
    for name in shadow_variables:
        if name in copied or name not in copy_shadow_names:
            continue
        lines.extend(_copy_real_shadow_lines(form, name, variable_shapes.get(name, "")))
    if _dfgrd1_carries_the_seed(roles, mappings, seed_dfgrd1):
        lines.extend(_finite_dfgrd1_seed_lines(form, ntens))
    # Both conditions, matching the copy-in above. The directions used to be
    # injected into DSTRAN_OTI unconditionally, which wrote that name into
    # finite-strain model routines whose argument list has no DSTRAN at all;
    # under the "implicit none" those routines declare, gfortran read
    # DSTRAN_OTI as an untyped function. Requiring the seed as well as the
    # scope keeps a direction from perturbing an input that is present but is
    # not what the tangent is taken with respect to.
    if dstran in roles["seed"] and dstran_in_scope:
        for direction in range(1, ntens + 1):
            lines.append(_stmt(form, f"{dstran}_OTI({direction}) = {dstran}_OTI({direction}) + {_seed_basis_name(direction)}"))
    return lines


def _dfgrd1_carries_the_seed(
    roles: dict[str, set[str]], mappings: dict[str, str], seed_dfgrd1_enabled: bool
) -> bool:
    """Whether the OTI directions are injected into DFGRD1.

    Two shapes reach here, and both are finite-strain. A conventional UMAT
    receives DSTRAN and is seeded through it; because its stress update reads
    the deformation gradient as well, the same directions are ALSO mapped into
    DFGRD1 so that neither input is left at its unperturbed value. A model
    routine that receives DFGRD1 and no DSTRAN has DFGRD1 as its only seed,
    and DSTRAN must not be named anywhere in the emitted routine.
    """
    if not seed_dfgrd1_enabled:
        return False
    if "DFGRD1" in roles["seed"]:
        return True
    return "DFGRD1" in roles["promote"] and mappings.get("dstran", "DSTRAN") in roles["seed"]


def _finite_dfgrd1_seed_lines(form: str, ntens: int) -> list[str]:
    lines = [_comment_line(form, "OTIS finite-strain seed: map DSTRAN directions into DFGRD1")]
    diagonal_entries = [(1, 1, 1), (2, 2, 2), (3, 3, 3)]
    for row, column, direction in diagonal_entries[: min(ntens, 3)]:
        lines.append(_stmt(form, f"DFGRD1_OTI({row},{column}) = DFGRD1_OTI({row},{column}) + {_seed_basis_name(direction)}"))
    shear_entries = [(1, 2, 4), (2, 1, 4), (1, 3, 5), (3, 1, 5), (2, 3, 6), (3, 2, 6)]
    for row, column, direction in shear_entries:
        if ntens >= direction:
            lines.append(_stmt(form, f"DFGRD1_OTI({row},{column}) = DFGRD1_OTI({row},{column}) + 0.5D0*{_seed_basis_name(direction)}"))
    return lines


# The inverse of the two emitters above, kept beside them so the pair cannot
# drift apart. Anything that has to perturb the same inputs the transform
# seeded -- an independent reference for the returned tangent, above all --
# must know *which* map was used, and reading it back off the emitted code is
# the only way to know that without maintaining a second copy of it.
_DFGRD1_SEED_LINE = re.compile(
    r"\bDFGRD1_OTI\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*"
    r"DFGRD1_OTI\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*\+\s*"
    r"(0\.5D0\s*\*)?(?:OTI_)?E(\d+)\b",
    flags=re.IGNORECASE,
)


def parse_finite_dfgrd1_seed_line(line: str) -> tuple[int, int, float, int] | None:
    """``(row, column, coefficient, direction)`` for one emitted DFGRD1 seed line.

    ``None`` for any other line. The accumulated entry has to be the same one
    being read, or the line is an injection into a different entry and is not
    part of this map.
    """
    match = _DFGRD1_SEED_LINE.search(line)
    if not match:
        return None
    row, column, read_row, read_column = (int(match.group(i)) for i in (1, 2, 3, 4))
    if (row, column) != (read_row, read_column):
        return None
    return row, column, 0.5 if match.group(5) else 1.0, int(match.group(6))


def parse_dstran_seed_line(line: str, dstran: str = "DSTRAN") -> tuple[int, int] | None:
    """``(component, direction)`` for one emitted strain-increment seed line."""
    match = re.search(
        rf"\b{re.escape(dstran)}_OTI\s*\(\s*(\d+)\s*\)\s*=\s*"
        rf"{re.escape(dstran)}_OTI\s*\(\s*(\d+)\s*\)\s*\+\s*(?:OTI_)?E(\d+)\b",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    component, read_component = int(match.group(1)), int(match.group(2))
    if component != read_component:
        return None
    return component, int(match.group(3))


@dataclass(frozen=True)
class SeededKinematics:
    """Which kinematic inputs a transformed source injects the directions into.

    This is read from the transformed file, so it is what the transform *did*
    for this source and not a second guess at what it should have done. A
    routine that receives the strain increment is seeded through it; one whose
    kinematic input is the deformation gradient is seeded through that; a
    routine that reads both is seeded through both, and then neither may be
    left at its unperturbed value.
    """

    #: Strain-increment component -> the direction injected into it.
    dstran: dict[int, int] = field(default_factory=dict)
    #: Direction -> the ``(row, column, coefficient)`` terms it adds to DFGRD1.
    dfgrd1: dict[int, tuple[tuple[int, int, float], ...]] = field(default_factory=dict)

    @property
    def drives_deformation_gradient(self) -> bool:
        return bool(self.dfgrd1)

    @property
    def drives_strain_increment(self) -> bool:
        return bool(self.dstran)

    def directions(self) -> tuple[int, ...]:
        return tuple(sorted(set(self.dstran.values()) | set(self.dfgrd1)))


def seeded_kinematics(transformed_source: str, dstran: str = "DSTRAN") -> SeededKinematics:
    """Read back the seed injections a transformed source carries."""
    strain: dict[int, int] = {}
    gradient: dict[int, list[tuple[int, int, float]]] = {}
    for line in transformed_source.splitlines():
        if _is_commented(line):
            continue
        strain_seed = parse_dstran_seed_line(line, dstran)
        if strain_seed is not None:
            component, direction = strain_seed
            strain[component] = direction
            continue
        gradient_seed = parse_finite_dfgrd1_seed_line(line)
        if gradient_seed is not None:
            row, column, coefficient, direction = gradient_seed
            gradient.setdefault(direction, []).append((row, column, coefficient))
    return SeededKinematics(
        dstran=strain,
        dfgrd1={direction: tuple(sorted(terms)) for direction, terms in sorted(gradient.items())},
    )


def _copy_real_shadow_lines(form: str, name: str, shape: str) -> list[str]:
    dims = _shape_dimensions(shape)
    if not dims:
        return [_stmt(form, f"{name}_OTI = {name}")]
    if len(dims) == 1:
        return [
            _stmt(form, f"DO OTI_HI = 1, {dims[0]}"),
            _stmt(form, f"   {name}_OTI(OTI_HI) = {name}(OTI_HI)"),
            _stmt(form, "END DO"),
        ]
    if len(dims) == 2:
        return [
            _stmt(form, f"DO OTI_HI = 1, {dims[0]}"),
            _stmt(form, f"   DO OTI_HJ = 1, {dims[1]}"),
            _stmt(form, f"      {name}_OTI(OTI_HI,OTI_HJ) = {name}(OTI_HI,OTI_HJ)"),
            _stmt(form, "   END DO"),
            _stmt(form, "END DO"),
        ]
    return [_stmt(form, f"{name}_OTI = {name}")]


def _shadow_default_lines(form: str, shadow_variables: list[str], variable_shapes: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for name in shadow_variables:
        dims = _shape_dimensions(variable_shapes.get(name, ""))
        if not dims:
            lines.append(_stmt(form, f"{name}_OTI = 0.0D0"))
            continue
        if len(dims) == 1:
            lines.extend(
                [
                    _stmt(form, f"DO OTI_HI = 1, {dims[0]}"),
                    _stmt(form, f"   {name}_OTI(OTI_HI) = 0.0D0"),
                    _stmt(form, "END DO"),
                ]
            )
            continue
        if len(dims) == 2:
            lines.extend(
                [
                    _stmt(form, f"DO OTI_HI = 1, {dims[0]}"),
                    _stmt(form, f"   DO OTI_HJ = 1, {dims[1]}"),
                    _stmt(form, f"      {name}_OTI(OTI_HI,OTI_HJ) = 0.0D0"),
                    _stmt(form, "   END DO"),
                    _stmt(form, "END DO"),
                ]
            )
            continue
        lines.append(_stmt(form, f"{name}_OTI = 0.0D0"))
    return lines


def _shape_dimensions(shape: str) -> list[str]:
    cleaned = str(shape or "").strip()
    if not cleaned:
        return []
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    return [part.strip() for part in cleaned.split(",") if part.strip()]


def _real_extraction_lines(form: str, mappings: dict[str, str], roles: dict[str, set[str]], ntens: int,
                           variable_shapes: dict[str, str] | None = None) -> list[str]:
    lines = [_comment_line(form, "Copy real-valued OTIS outputs back to Abaqus arrays")]
    stress = mappings.get("stress", "STRESS")
    statev = mappings.get("statev", "STATEV")
    if stress in roles["promote"]:
        lines.extend(
            [
                _stmt(form, "DO OTI_I = 1, NTENS"),
                _stmt(form, f"   {stress}(OTI_I) = REAL({stress}_OTI(OTI_I))"),
                _stmt(form, "END DO"),
            ]
        )
    if statev in roles["promote"]:
        lines.extend(
            [
                _stmt(form, f"DO OTI_I = 1, {_bound(variable_shapes or {}, statev, 'NSTATV')}"),
                _stmt(form, f"   {statev}(OTI_I) = REAL({statev}_OTI(OTI_I))"),
                _stmt(form, "END DO"),
            ]
        )
    return lines


def _preserved_ddsdde_output_lines(
    *,
    form: str,
    config: dict[str, Any],
    extraction_region: dict[str, Any] | None,
    mappings: dict[str, str],
    replacement_names: dict[str, str],
    type_name: str,
) -> list[str]:
    if not extraction_region or not _should_preserve_explicit_ddsdde_output(config, extraction_region):
        return []
    rows = _explicit_ddsdde_assignment_rows(config, extraction_region)
    if not rows:
        return []
    ddsdde = mappings.get("ddsdde", "DDSDDE")
    lines = [_comment_line(form, "OTIS DDSDDE output preserved from explicit UMAT assignments")]
    for row in rows:
        match = re.match(
            r"^\s*DDSDDE\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*(.+?)\s*$",
            str(row.get("text", "")),
            flags=re.IGNORECASE,
        )
        if not match:
            return []
        stress_index = int(match.group(1))
        direction = int(match.group(2))
        rhs = match.group(3).strip()
        assignment = _stmt(form, f"{ddsdde}({stress_index},{direction}) = REAL({rhs})")
        lines.append(_transform_executable_line(assignment, replacement_names, type_name, set()))
    return lines


def _should_preserve_explicit_ddsdde_output(config: dict[str, Any], extraction_region: dict[str, Any]) -> bool:
    artifact_variables = _explicit_ddsdde_artifact_variables(config)
    if not artifact_variables:
        return False
    region_variables = {str(value).upper() for value in (extraction_region.get("variables") or []) if str(value).strip()}
    if not region_variables.intersection(artifact_variables):
        return False
    return bool(_explicit_ddsdde_assignment_rows(config, extraction_region))


def _explicit_ddsdde_artifact_variables(config: dict[str, Any]) -> set[str]:
    variables: set[str] = set()
    for contract in _parse_extra_jacobian_contracts(config):
        output_variable = str(contract.get("output_variable") or "").upper()
        if output_variable:
            variables.add(output_variable)
        for extraction in contract.get("additional_extractions", []) or []:
            if not isinstance(extraction, dict):
                continue
            target_variable = str(extraction.get("target_variable") or "").upper()
            if target_variable:
                variables.add(target_variable)
    return variables


def _explicit_ddsdde_assignment_rows(config: dict[str, Any], extraction_region: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = _dict(config.get("analysis"))
    rows: list[dict[str, Any]] = []
    for row in analysis.get("assignments_to_ddsdde", []) or []:
        if not isinstance(row, dict):
            continue
        if not _line_numbers_intersect(row.get("line_numbers", []), [extraction_region]):
            continue
        text = str(row.get("text", ""))
        if not re.match(r"^\s*DDSDDE\s*\(\s*\d+\s*,\s*\d+\s*\)\s*=", text, flags=re.IGNORECASE):
            return []
        rows.append(row)
    return sorted(rows, key=lambda row: min((_as_int(value) for value in (row.get("line_numbers") or []) if _as_int(value)), default=0))


def _ddsdde_extraction_lines(
    form: str, mappings: dict[str, str], ntens: int, order: int = 1, nbases: int | None = None
) -> list[str]:
    stress = mappings.get("stress", "STRESS")
    ddsdde = mappings.get("ddsdde", "DDSDDE")
    if form == "fixed":
        lines = [
            _comment_line(form, "OTIS DDSDDE extraction: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)"),
            "      DO OTI_I = 1, NTENS",
            "         DO OTI_J = 1, NTENS",
            f"            {ddsdde}(OTI_I,OTI_J) =",
            f"     1      GETIM({stress}_OTI(OTI_I),OTI_J)",
            "         END DO",
            "      END DO",
        ]
    else:
        lines = [
            _comment_line(form, "OTIS DDSDDE extraction: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)"),
            _stmt(form, "DO OTI_I = 1, NTENS"),
            _stmt(form, "   DO OTI_J = 1, NTENS"),
            _stmt(form, f"      {ddsdde}(OTI_I, OTI_J) = GETIM({stress}_OTI(OTI_I), OTI_J)"),
            _stmt(form, "   END DO"),
            _stmt(form, "END DO"),
        ]
    if order and order > 1:
        lines.extend(_higher_order_jacobian_lines(form, mappings, ntens, order, nbases or ntens))
    return lines


def _write_higher_order_directions(output_dir: Path, nbases: int, order: int) -> Path | None:
    if order <= 1:
        return None
    from umat_oti.oti.oti_directions import imaginary_directions

    path = output_dir / "higher_order_directions.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["order", "member_name", "flat_getim_index", "bases_multiindex", "recovery_factor"])
        for entry in imaginary_directions(nbases, order):
            writer.writerow(
                [
                    entry["order"],
                    entry["name"],
                    entry["flat"],
                    "|".join(str(basis) for basis in entry["bases"]),
                    entry["factor"],
                ]
            )
    return path


def _higher_order_jacobian_lines(
    form: str, mappings: dict[str, str], ntens: int, order: int, nbases: int
) -> list[str]:
    """Emit code that, after the first-order DDSDDE fill, writes the higher-order
    stress Jacobians (d^k STRESS(i)/dDSTRAN... for k=2..order) to a side file at
    Abaqus runtime. The UMAT interface has no slot to return these, so they are
    written to 'oti_hjac.dat' (one labelled value per stress component per mixed
    strain direction; rows tagged with NOEL/NPT/KSTEP/KINC). Each emitted record
    is: stress_component, order, base_indices..., derivative_value.

    The OTI imaginary coefficient stores the Taylor term, so the true partial
    derivative is recovered by multiplying by the repeated-index factorial
    (e.g. d2/dDSTRAN_i^2 needs x2, mixed d2/dDSTRAN_i dDSTRAN_j needs x1)."""
    from itertools import combinations_with_replacement
    from umat_oti.oti import oti_directions as _dirs

    stress = mappings.get("stress", "STRESS")
    # NEWUNIT picks a guaranteed-free unit (dodging Abaqus's reserved units) and
    # GETOUTDIR gives Abaqus's output directory, so the file lands there regardless
    # of the solver's working directory. IOTIHJ/IOTILN/OTI_OUTDIR are declared in
    # _declaration_lines for order > 1.
    unit = "IOTIHJ"
    fname = "oti_hjac.dat"
    lines = [_comment_line(form, f"OTIS higher-order stress Jacobians (orders 2..{order}) -> {fname}")]
    lines.append(_stmt(form, "CALL GETOUTDIR(OTI_OUTDIR, IOTILN)"))
    # The OPEN spans two lines (path concatenation is long); emit a continuation
    # appropriate to the source form so it stays valid in fixed-form's 72 columns.
    if form == "fixed":
        lines.append(f"      OPEN(NEWUNIT={unit},FILE=OTI_OUTDIR(1:IOTILN)//")
        lines.append(f"     1     '/{fname}',POSITION='APPEND')")
    else:
        lines.append(_stmt(form, f"OPEN(NEWUNIT={unit},FILE=OTI_OUTDIR(1:IOTILN)// &"))
        lines.append(_stmt(form, f"     '/{fname}',POSITION='APPEND')"))
    lines.append(_stmt(form, f"WRITE({unit},*)'#',NOEL,NPT,KSTEP,KINC"))
    lines.append(_stmt(form, "DO OTI_I = 1, NTENS"))
    for k in range(2, order + 1):
        for multiset in combinations_with_replacement(range(1, ntens + 1), k):
            flat = _dirs.flat_index(nbases, k, _dirs.dir_index(multiset))
            factor = _dirs.deriv_factor(multiset)
            value = f"GETIM({stress}_OTI(OTI_I),{flat})"
            if factor != 1:
                value = f"{value}*{factor}.0D0"
            bases = ",".join(str(b) for b in multiset)
            lines.append(_stmt(form, f"   WRITE({unit},*)OTI_I,{k},{bases},{value}"))
    lines.append(_stmt(form, "END DO"))
    lines.append(_stmt(form, f"CLOSE({unit})"))
    return lines


@atomic_real_literals
def _replace_role_references(line: str, replacement_names: dict[str, str]) -> str:
    """Point every reference to a promoted variable at its OTI shadow.

    Decorated, because a real literal is one token and this substitution works
    on characters. ``1.d-12`` offers the substituter a ``\\bD\\b`` between a dot
    and a minus sign, and a model that names a variable ``D`` -- damage, most of
    them -- had ``xtol = 1.d-12`` emitted as ``XTOL_OTI = 1.D_OTI-12``. The same
    hole is open for ``E`` in ``1.E-6``, ``D0`` in ``2.D0`` and ``E2`` in
    ``1.E2``, so the fix is atomicity rather than a lookaround for ``D``.
    """
    if not replacement_names:
        return line
    pattern = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(replacement_names, key=len, reverse=True)) + r")\b", re.IGNORECASE)
    # A character literal is text the author wrote for a reader, not a
    # reference to anything: 'STRESS is negative' became
    # 'STRESS_OTI is negative'. Harmless in a message and not harmless in a
    # comparison -- a UMAT that switches on CMNAME with
    # IF (CMNAME(1:6) .EQ. 'ELAST1') stops matching the moment a promoted
    # variable is called ELAST1. Masked here rather than inside the pattern
    # because a name is a name wherever it appears; what changes is whether
    # the surrounding text is code.
    masked, store = mask_character_literals(line)
    rewritten = pattern.sub(
        lambda match: replacement_names[match.group(1).upper()], masked)
    return unmask_character_literals(rewritten, store)


def _transform_executable_line(
    line: str,
    replacement_names: dict[str, str],
    type_name: str,
    lifted_helper_names: set[str] | None = None,
    helper_output_surfaces: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    # A trailing ! comment is not part of the statement, and treating it as
    # one does more than rename words inside prose: wrapping an assignment's
    # right-hand side in REAL(...) put the closing parenthesis after the
    # comment, so "cr_pos = props(4)   ! critical stress for growth" was
    # emitted as "cr_pos = REAL(props(4)   ! critical STRESS_OTI for growth"
    # and the file stopped being Fortran. Split off, transformed without it,
    # and reattached exactly as the author wrote it.
    statement = _statement_without_inline_comment(line)
    if statement != line:
        if not statement.strip():
            return line
        return _transform_executable_line(
            statement, replacement_names, type_name,
            lifted_helper_names, helper_output_surfaces) + line[len(statement):]
    replaced = _replace_role_references(line, replacement_names)
    replaced = _rewrite_lifted_helper_call(replaced, lifted_helper_names or set(), helper_output_surfaces or {})
    replaced = _wrap_oti_condition_with_real(replaced)
    replaced = _normalize_typed_intrinsics_in_oti_expression(replaced)
    replaced = _normalize_mixed_minmax_intrinsics_in_oti_expression(replaced)
    replaced = _normalize_safe_sqrt_intrinsics_in_oti_expression(replaced)
    replaced = _wrap_real_assignment_rhs(replaced)
    return _normalize_numeric_literals_in_oti_expression(replaced, type_name)


def _wrap_real_assignment_rhs(line: str) -> str:
    if "_OTI" not in line.upper():
        return line
    if re.match(r"^\s*CALL\b", line, flags=re.IGNORECASE):
        return line
    inline_if_prefix = ""
    assignment_text = line
    inline_if_split = _split_inline_if_assignment(line)
    if inline_if_split is not None:
        inline_if_prefix, assignment_text = inline_if_split
    elif re.match(r"^\s*(?:ELSE\s*)?IF\b", line, flags=re.IGNORECASE):
        return line
    match = re.match(r"^(\s*([A-Za-z_]\w*)(?:\([^=]*\))?\s*=\s*)(.+)$", assignment_text)
    if not match:
        return line
    lhs_name = match.group(2).upper()
    rhs = match.group(3).strip()
    if lhs_name.endswith("_OTI") or lhs_name in {"OTI_HX", "OTI_HY", "OTI_HTR"} or rhs.upper().startswith("REAL("):
        return line
    return f"{inline_if_prefix}{match.group(1)}REAL({rhs})"


def _split_inline_if_assignment(line: str) -> tuple[str, str] | None:
    if not re.match(r"^\s*(?:ELSE\s*)?IF\b", line, flags=re.IGNORECASE):
        return None
    open_paren = line.find("(")
    if open_paren < 0:
        return None
    depth = 0
    for index in range(open_paren, len(line)):
        char = line[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return line[: index + 1] + " ", line[index + 1 :]
    return None


def _rewrite_lifted_helper_call(
    line: str,
    lifted_helper_names: set[str],
    helper_output_surfaces: dict[str, list[dict[str, Any]]],
) -> str:
    if not lifted_helper_names and not helper_output_surfaces:
        return line
    match = re.match(r"^(\s*CALL\s+)([A-Z_][A-Z0-9_]*)(\s*\((.*)\)\s*)$", line, flags=re.IGNORECASE)
    if not match:
        return line
    callee = match.group(2).upper()
    appended_surfaces = helper_output_surfaces.get(callee, [])
    if callee not in lifted_helper_names and not appended_surfaces:
        return line
    arguments = _split_call_arguments(match.group(4))
    arguments.extend(f"{spec['caller_variable']}_OTI" for spec in appended_surfaces if spec.get("caller_variable"))
    rewritten_callee = f"{callee}_OTI" if callee in lifted_helper_names else callee
    return f"{match.group(1)}{rewritten_callee}({', '.join(arguments)})"


def _helper_surface_sync_lines(
    form: str,
    call_line: str,
    helper_output_surfaces: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Copy a lifted helper's surfaced OTI output back to its REAL shadow.

    A helper_output_surface passes ``VAR_OTI`` into the lifted helper as an
    output argument, but the caller's REAL ``VAR`` is never updated unless the
    original UMAT later reads it. Emit ``VAR = REAL(VAR_OTI)`` (element-wise for
    arrays) right after the call so the surfaced analytic value is usable.
    """
    if not helper_output_surfaces:
        return []
    match = re.match(r"^\s*CALL\s+([A-Z_][A-Z0-9_]*)\s*\(", call_line, flags=re.IGNORECASE)
    if not match:
        return []
    callee = match.group(1).upper()
    lines: list[str] = []
    for spec in helper_output_surfaces.get(callee, []):
        name = str(spec.get("caller_variable") or "").upper()
        if not name:
            continue
        dims = [dim.strip() for dim in str(spec.get("declared_shape") or "").split(",") if dim.strip()]
        if not dims:
            lines.append(_stmt(form, f"{name} = REAL({name}_OTI)"))
            continue
        loop_vars = ["OTI_HI", "OTI_HJ", "OTI_HK"][: len(dims)]
        for loop_var, extent in zip(loop_vars, dims):
            lines.append(_stmt(form, f"DO {loop_var} = 1, {extent}"))
        index = ", ".join(loop_vars)
        lines.append(_stmt(form, f"   {name}({index}) = REAL({name}_OTI({index}))"))
        for _ in dims:
            lines.append(_stmt(form, "END DO"))
    return lines


def _normalize_typed_intrinsics_in_oti_expression(line: str) -> str:
    if "_OTI" not in line.upper():
        return line
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(name) for name in sorted(TYPED_INTRINSIC_NORMALIZATIONS, key=len, reverse=True)) + r")\s*\(",
        flags=re.IGNORECASE,
    )
    return pattern.sub(lambda match: TYPED_INTRINSIC_NORMALIZATIONS[match.group(1).upper()] + "(", line)


def _normalize_mixed_minmax_intrinsics_in_oti_expression(line: str) -> str:
    if "_OTI" not in line.upper() or not re.search(r"\b(?:MIN|MAX)\s*\(", line, flags=re.IGNORECASE):
        return line
    result = line
    search_from = 0
    while True:
        match = re.search(r"\b(MIN|MAX)\s*\(", result[search_from:], flags=re.IGNORECASE)
        if not match:
            return result
        call_start = search_from + match.start()
        open_paren = search_from + match.end() - 1
        close_paren = _matching_paren_index(result, open_paren)
        if close_paren < 0:
            return result
        args_text = result[open_paren + 1 : close_paren]
        args = [arg.strip() for arg in split_top_level(args_text) if arg.strip()]
        oti_args = [arg for arg in args if _contains_oti_value_reference(arg)]
        if not oti_args or len(oti_args) == len(args):
            search_from = close_paren + 1
            continue
        anchor = oti_args[0]
        normalized_args = [arg if _contains_oti_value_reference(arg) else f"(({arg}) + 0.0D0*({anchor}))" for arg in args]
        result = result[: open_paren + 1] + ", ".join(normalized_args) + result[close_paren:]
        search_from = close_paren + 1


def _normalize_safe_sqrt_intrinsics_in_oti_expression(line: str) -> str:
    if "_OTI" not in line.upper() or not re.search(r"\bSQRT\s*\(", line, flags=re.IGNORECASE):
        return line
    result = line
    search_from = 0
    while True:
        match = re.search(r"\bSQRT\s*\(", result[search_from:], flags=re.IGNORECASE)
        if not match:
            return result
        open_paren = search_from + match.end() - 1
        close_paren = _matching_paren_index(result, open_paren)
        if close_paren < 0:
            return result
        argument = result[open_paren + 1 : close_paren].strip()
        if not _contains_oti_value_reference(argument):
            search_from = close_paren + 1
            continue
        safe_argument = f"(((MAX(REAL({argument}), 1.0D-30)) - REAL({argument})) + ({argument}))"
        result = result[: open_paren + 1] + safe_argument + result[close_paren:]
        search_from = open_paren + 1 + len(safe_argument)


def _matching_paren_index(text: str, open_paren: int) -> int:
    depth = 0
    for index in range(open_paren, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _contains_oti_value_reference(text: str) -> bool:
    return "_OTI" in text.upper() or bool(re.search(r"\bOTI_H(?:X|Y|TR)\b", text, flags=re.IGNORECASE))


def _wrap_fixed_form_source(source: str) -> str:
    return "\n".join(_wrap_fixed_form_line(line) for line in source.splitlines()) + "\n"


def _wrap_fixed_form_line(line: str) -> str:
    if len(line.rstrip("\n")) <= 72 or _is_commented(line):
        return line
    # An over-long line whose overflow is a trailing ! comment is not an
    # over-long statement. Wrapping it put the tail of the comment in column 7
    # of a continuation line -- "     1growth" -- and the statement above it
    # stopped being classifiable. The comment moves to a line of its own, and
    # only the statement is measured against the 72-column limit.
    statement = _statement_without_inline_comment(line).rstrip()
    if statement != line.rstrip("\n") and statement.strip():
        comment = line.rstrip("\n")[len(statement):].lstrip()
        wrapped_statement = _wrap_fixed_form_line(statement)
        if not comment:
            return wrapped_statement
        return "\n".join([wrapped_statement,
                          *_split_fixed_form_comment(comment)])
    prefix = line[:6] if len(line) >= 6 else "      "
    payload = line[6:].rstrip() if len(line) >= 6 else line.strip()
    if not payload:
        return line
    chunks = _split_fixed_form_payload(payload, 66)
    if len(chunks) <= 1:
        return prefix + (chunks[0] if chunks else payload.strip())
    wrapped = [prefix + chunks[0]]
    wrapped.extend("     1" + chunk for chunk in chunks[1:])
    return "\n".join(wrapped)


def _split_fixed_form_comment(comment: str) -> list[str]:
    """The author's trailing comment, as full comment lines within 72 columns."""
    body = comment.lstrip("!").strip()
    if not body:
        return ["C"]
    return [f"C     {chunk}" for chunk in _split_fixed_form_payload(body, 66)]


def _split_fixed_form_payload(payload: str, width: int) -> list[str]:
    chunks: list[str] = []
    remaining = payload.strip()
    while len(remaining) > width:
        split_at = _fixed_form_split_index(remaining, width)
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _fixed_form_split_index(text: str, width: int) -> int:
    if len(text) <= width:
        return len(text)
    for index in range(width, 10, -1):
        char = text[index - 1]
        if char in {",", "+", "-", "*", "/"}:
            return index
        if char.isspace():
            return index
    return width


def _inline_pure_arithmetic_helper_call(
    line: str,
    replacement_names: dict[str, str],
    form: str,
    variable_shapes: dict[str, str],
    configured_ntens: int,
) -> list[str]:
    match = re.match(r"^\s*CALL\s+(\w+)\s*\((.*)\)\s*$", line, flags=re.IGNORECASE)
    if not match:
        return []
    callee = match.group(1).upper()
    arguments = [_replace_role_references(argument, replacement_names) for argument in _split_call_arguments(match.group(2))]
    if callee == "KMAVEC" and len(arguments) >= 5:
        return _inline_kmavec(form, arguments[0], arguments[1], arguments[2], arguments[3], arguments[4])
    if callee == "VSPRATE" and len(arguments) >= 11:
        return _inline_vsprate(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            arguments[5],
            arguments[6],
            arguments[7],
            arguments[8],
            arguments[9],
            theta=arguments[4],
            gamhard=arguments[10],
        )
    if callee == "VSPRATE" and len(arguments) >= 9:
        return _inline_vsprate(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            arguments[4],
            arguments[5],
            arguments[6],
            arguments[7],
            arguments[8],
        )
    if callee == "KPROYECTOR" and len(arguments) >= 1:
        return _inline_kproyector(form, arguments[0], _argument_shape(arguments[0], variable_shapes), configured_ntens)
    if callee == "KMATSUB" and len(arguments) >= 5:
        return _inline_kmatsub(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            arguments[4],
            arguments[5] if len(arguments) >= 6 else "0",
        )
    if callee == "KCLEAR" and len(arguments) >= 3:
        return _inline_kclear(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            _argument_shape(arguments[0], variable_shapes),
        )
    if callee == "KMMULT" and len(arguments) >= 7:
        return _inline_kmmult(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            arguments[4],
            arguments[5],
            arguments[6],
            _argument_shape(arguments[0], variable_shapes),
            _argument_shape(arguments[3], variable_shapes),
            _argument_shape(arguments[6], variable_shapes),
            configured_ntens,
        )
    if callee == "KTMULT" and len(arguments) >= 8:
        return _inline_ktmult(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            arguments[4],
            arguments[5],
            arguments[6],
            arguments[7],
        )
    if callee == "KMTRAN" and len(arguments) >= 4:
        return _inline_kmtran(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            _argument_shape(arguments[0], variable_shapes),
            _argument_shape(arguments[3], variable_shapes),
        )
    if callee == "KUPDVEC" and len(arguments) >= 3:
        return _inline_kupdvec(form, arguments[0], arguments[1], arguments[2])
    if callee == "KMLT1" and len(arguments) >= 4:
        return _inline_kmlt1(form, arguments[0], arguments[1], arguments[2], arguments[3])
    if callee == "KSMULT" and len(arguments) >= 4:
        return _inline_ksmult(form, arguments[0], arguments[1], arguments[2], arguments[3])
    if callee == "KDEVIA" and len(arguments) >= 3:
        return _inline_kdevia(form, arguments[0], arguments[1], arguments[2])
    if callee == "KEFFP" and len(arguments) >= 2:
        return _inline_keffp(form, arguments[0], arguments[1])
    if callee == "KINVER" and len(arguments) >= 2:
        return _inline_kinver(form, arguments[0], arguments[1])
    if callee == "KMLT" and len(arguments) >= 3:
        return _inline_kmlt(form, arguments[0], arguments[1], arguments[2])
    if callee == "DOTPROD" and len(arguments) >= 4:
        return _inline_dotprod(form, arguments[0], arguments[1], arguments[2], arguments[3])
    if callee == "DYADICPROD" and len(arguments) >= 4:
        return _inline_dyadicprod(form, arguments[0], arguments[1], arguments[2], arguments[3])
    if callee == "KTRACE" and len(arguments) >= 2:
        return _inline_ktrace(form, arguments[0], arguments[1])
    if callee == "KTRANS" and len(arguments) >= 2:
        return _inline_ktrans(form, arguments[0], arguments[1])
    if callee == "KDAMACAL" and len(arguments) >= 9:
        return _inline_kdamacal(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            arguments[4],
            arguments[5],
            arguments[6],
            arguments[7],
            arguments[8],
        )
    if callee == "KDAMACAL" and len(arguments) >= 7:
        return _inline_kdamacal_damage_only(
            form,
            arguments[0],
            arguments[1],
            arguments[2],
            arguments[3],
            arguments[4],
            arguments[5],
            arguments[6],
        )
    if callee == "KTNORM" and len(arguments) >= 5:
        return _inline_ktnorm(form, arguments[0], arguments[1], arguments[2], arguments[3], arguments[4])
    if callee == "KSPECTRAL" and len(arguments) >= 10:
        return _inline_kspectral_damage(form, arguments[0], arguments[1], arguments[2], arguments[3], arguments[4], arguments[5], arguments[6], arguments[7], arguments[8], arguments[9])
    if callee == "KUHARDNLIN" and len(arguments) >= 9:
        return _inline_kuhardnlin(form, arguments[0], arguments[1], arguments[2], arguments[3], arguments[4], arguments[5], arguments[6], arguments[7], arguments[8])
    if callee == "KUHARDNLIN" and len(arguments) >= 6:
        return _inline_kuhardnlin_simple(form, arguments[0], arguments[1], arguments[2], arguments[3], arguments[4], arguments[5])
    return []


def _sprinc_equivalent_stress_rewrites(source_lines: list[str], stress_line_numbers: set[int]) -> tuple[dict[int, dict[str, str]], set[int]]:
    rewrites: dict[int, dict[str, str]] = {}
    skip_lines: set[int] = set()
    for line_number, line in enumerate(source_lines, start=1):
        if line_number not in stress_line_numbers:
            continue
        match = re.match(r"^\s*CALL\s+SPRINC\s*\((.*)\)\s*$", line, flags=re.IGNORECASE)
        if not match:
            continue
        arguments = _split_call_arguments(match.group(1))
        if len(arguments) < 2:
            continue
        stress_name = _base_argument_name(arguments[0])
        ps_name = _base_argument_name(arguments[1])
        if not stress_name or not ps_name:
            continue
        pj_line = 0
        pj_name = ""
        formula_lines: list[int] = []
        for candidate_line in range(line_number + 1, min(line_number + 8, len(source_lines)) + 1):
            candidate = source_lines[candidate_line - 1]
            if re.search(rf"\b{re.escape(ps_name)}\s*\(", candidate, flags=re.IGNORECASE):
                formula_lines.append(candidate_line)
                if not pj_line:
                    lhs_match = re.match(r"^\s*([A-Za-z_]\w*)\s*=", candidate, flags=re.IGNORECASE)
                    if lhs_match:
                        pj_line = candidate_line
                        pj_name = lhs_match.group(1).upper()
        if not pj_line or not pj_name or len(formula_lines) < 2:
            continue
        rewrites[line_number] = {"pj_name": pj_name, "stress_name": stress_name}
        skip_lines.update(formula_lines)
    return rewrites, skip_lines


def _sprinc_equivalent_stress_lines(form: str, stress_name: str, pj_name: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline equivalent stress invariant in place of SPRINC principal stresses"),
        _stmt(
            form,
            f"{pj_name} = SQRT(0.5D0*((({stress_name}(1)-{stress_name}(2))**2.0D0) + (({stress_name}(2)-{stress_name}(3))**2.0D0) + (({stress_name}(3)-{stress_name}(1))**2.0D0)) + 3.0D0*{stress_name}(4)**2.0D0)",
        ),
    ]


def _base_argument_name(argument: str) -> str:
    match = re.match(r"\s*([A-Za-z_]\w*)", argument)
    return match.group(1).upper() if match else ""


def _fixed_form_physical_line(line: str) -> str:
    if not line.startswith("\t"):
        return line
    remainder = line[1:]
    if remainder[:1] in "123456789":
        return "     " + remainder
    return "      " + remainder


def _statement_line_segment(line: str, form: str) -> str:
    if form == "fixed":
        line = _fixed_form_physical_line(line)
        return line[6:] if len(line) > 6 else ""
    segment = line.rstrip()
    stripped = segment.lstrip()
    if stripped.startswith("&"):
        segment = stripped[1:]
    if segment.rstrip().endswith("&"):
        segment = segment.rstrip()[:-1]
    return segment


def _is_continuation_line(line: str, form: str) -> bool:
    """Whether this physical line continues the statement above it.

    A comment is never a continuation, whatever stands in column 6. In fixed
    form the comment marker in column 1 settles the question before the
    continuation field is looked at, and skipping that test reads

        ReadDetF(NOEL, NPT) = DetF
    C store coordinate from STATEV

    as one statement, because the "r" of "store" happens to fall in column 6.
    The label field is then stripped along with the marker and the assignment
    is emitted as
    ``ReadDetF(NOEL,NPT) = REAL(DETF_OTI e coordinate from STATEV_OTI)``:
    not Fortran at all, in a file the transform had just reported as
    successful. Nothing downstream re-reads the emitted text, so a prose
    comment whose sixth character is not a space silently ends the run.
    """
    if form == "fixed":
        line = _fixed_form_physical_line(line)
        if _is_commented(line):
            return False
        return len(line) > 5 and line[5] not in {" ", "0"}
    return not _is_commented(line) and line.lstrip().startswith("&")


def _logical_helper_call_line(lines: list[str], start_line: int, form: str) -> tuple[str, list[int]]:
    # A comment is never a statement. _statement_line_segment strips the
    # fixed-form marker along with the label field, so without this a
    # commented-out branch, assignment or CALL is stitched into executable
    # text and rewritten as code. Guarded here rather than only at the call
    # sites, so a future caller inherits the guard instead of the bug.
    if _is_commented(lines[start_line - 1]):
        return "", []
    first_segment = _statement_line_segment(lines[start_line - 1], form)
    if not re.match(r"^\s*CALL\s+\w+\s*\(", first_segment, flags=re.IGNORECASE):
        return "", []
    segments = [first_segment]
    consumed_lines: list[int] = []
    paren_depth = first_segment.count("(") - first_segment.count(")")
    next_line_number = start_line + 1
    while paren_depth > 0 and next_line_number <= len(lines):
        candidate = lines[next_line_number - 1]
        if not _is_continuation_line(candidate, form):
            break
        candidate_segment = _statement_line_segment(candidate, form)
        segments.append(candidate_segment)
        consumed_lines.append(next_line_number)
        paren_depth += candidate_segment.count("(") - candidate_segment.count(")")
        next_line_number += 1
    if paren_depth != 0:
        return "", []
    leading = re.match(r"^(\s*)", lines[start_line - 1]).group(1)
    logical_line = " ".join(segment.strip() for segment in segments if segment.strip())
    return f"{leading}{logical_line}", consumed_lines


def _capture_projected_ddstra_helper_call(line: str, replacement_names: dict[str, str], configured_ntens: int) -> tuple[str, str] | None:
    if configured_ntens >= 6:
        return None
    match = re.match(r"^\s*CALL\s+(\w+)\s*\((.*)\)\s*$", line, flags=re.IGNORECASE)
    if not match or match.group(1).upper() != "KMMULT":
        return None
    arguments = [_replace_role_references(argument, replacement_names) for argument in _split_call_arguments(match.group(2))]
    if len(arguments) < 7:
        return None
    if _base_argument_name(arguments[0]) != "P":
        return None
    if _base_argument_name(arguments[3]) != "DSTRAN_OTI":
        return None
    output_name = _base_argument_name(arguments[6])
    if not output_name.startswith("DDSTRA"):
        return None
    return arguments[3].strip(), output_name


def _rewrite_projected_dstres_bundle(
    source_lines: list[str],
    start_line: int,
    form: str,
    replacement_names: dict[str, str],
    projected_vector_sources: dict[str, str],
) -> tuple[list[str], set[int]]:
    if not projected_vector_sources or start_line + 5 > len(source_lines):
        return [], set()
    if not re.match(r"^\s*DO\s+\w+\s*=\s*1\s*,\s*NDI\s*$", source_lines[start_line - 1], flags=re.IGNORECASE):
        return [], set()
    normal_assignment = _replace_role_references(source_lines[start_line], replacement_names)
    if not re.match(r"^\s*END\s*DO\s*$", source_lines[start_line + 1], flags=re.IGNORECASE):
        return [], set()
    if not re.match(r"^\s*DO\s+\w+\s*=\s*NDI\s*\+\s*1\s*,\s*NTENS\s*$", source_lines[start_line + 2], flags=re.IGNORECASE):
        return [], set()
    shear_assignment = _replace_role_references(source_lines[start_line + 3], replacement_names)
    if not re.match(r"^\s*END\s*DO\s*$", source_lines[start_line + 4], flags=re.IGNORECASE):
        return [], set()
    output_match = re.match(r"^\s*([A-Za-z_]\w*(?:_OTI)?)\s*\(\s*\w+\s*\)\s*=", normal_assignment, flags=re.IGNORECASE)
    if not output_match:
        return [], set()
    output_name = output_match.group(1)
    input_name = ""
    ddstra_name = ""
    for candidate_name, candidate_input in projected_vector_sources.items():
        if re.search(rf"\b{re.escape(candidate_name)}\s*\(", normal_assignment, flags=re.IGNORECASE) and re.search(
            rf"\b{re.escape(candidate_name)}\s*\(", shear_assignment, flags=re.IGNORECASE
        ):
            ddstra_name = candidate_name
            input_name = candidate_input
            break
    if not input_name:
        return [], set()
    projected_vector_sources.pop(ddstra_name, None)
    return (
        _inline_projected_dstres_from_dstran(
            form=form,
            input_name=input_name,
            output_name=output_name,
            normal_scale=_replace_role_references("EG2*(ONE-D)", replacement_names),
            shear_scale=_replace_role_references("EG*(ONE-D)", replacement_names),
        ),
        {start_line + 1, start_line + 2, start_line + 3, start_line + 4, start_line + 5},
    )


def _inline_projected_dstres_from_dstran(
    form: str,
    input_name: str,
    output_name: str,
    normal_scale: str,
    shear_scale: str,
) -> list[str]:
    return [
        _comment_line(form, "OTIS inline DSTRES from projected DSTRAN"),
        _stmt(form, "DO OTI_HI = 1, NTENS"),
        _stmt(form, f"   {output_name}(OTI_HI) = 0.0D0"),
        _stmt(form, "END DO"),
        _stmt(form, "IF (NDI .GE. 3) THEN"),
        _stmt(form, f"   {output_name}(1) = {normal_scale}*((TWO/THREE)*{input_name}(1)-(ONE/THREE)*{input_name}(2)-(ONE/THREE)*{input_name}(3))"),
        _stmt(form, f"   {output_name}(2) = {normal_scale}*(-(ONE/THREE)*{input_name}(1)+(TWO/THREE)*{input_name}(2)-(ONE/THREE)*{input_name}(3))"),
        _stmt(form, f"   {output_name}(3) = {normal_scale}*(-(ONE/THREE)*{input_name}(1)-(ONE/THREE)*{input_name}(2)+(TWO/THREE)*{input_name}(3))"),
        _stmt(form, "END IF"),
        _stmt(form, "IF (NTENS .GE. 6) THEN"),
        _stmt(form, f"   {output_name}(4) = {shear_scale}*TWO*{input_name}(4)"),
        _stmt(form, f"   {output_name}(5) = {shear_scale}*{input_name}(5)"),
        _stmt(form, f"   {output_name}(6) = {shear_scale}*{input_name}(6)"),
        _stmt(form, "ELSE IF (NTENS .GE. 4) THEN"),
        _stmt(form, f"   {output_name}(4) = {shear_scale}*{input_name}(4)"),
        _stmt(form, "END IF"),
        _stmt(form, "IF (NTENS .GE. 5 .AND. NTENS .LT. 6) THEN"),
        _stmt(form, f"   {output_name}(5) = {shear_scale}*{input_name}(5)"),
        _stmt(form, "END IF"),
    ]


def _logical_branch_line(lines: list[str], start_line: int, form: str) -> tuple[str, list[int]]:
    # A comment is never a statement. _statement_line_segment strips the
    # fixed-form marker along with the label field, so without this a
    # commented-out branch, assignment or CALL is stitched into executable
    # text and rewritten as code. Guarded here rather than only at the call
    # sites, so a future caller inherits the guard instead of the bug.
    if _is_commented(lines[start_line - 1]):
        return "", []
    first_segment = _statement_line_segment(lines[start_line - 1], form)
    if not re.match(r"^\s*(?:ELSE\s*)?IF\s*\(", first_segment, flags=re.IGNORECASE):
        return "", []
    segments = [first_segment]
    consumed_lines: list[int] = []
    paren_depth = first_segment.count("(") - first_segment.count(")")
    next_line_number = start_line + 1
    while paren_depth > 0 and next_line_number <= len(lines):
        candidate = lines[next_line_number - 1]
        if not _is_continuation_line(candidate, form):
            break
        candidate_segment = _statement_line_segment(candidate, form)
        segments.append(candidate_segment)
        consumed_lines.append(next_line_number)
        paren_depth += candidate_segment.count("(") - candidate_segment.count(")")
        next_line_number += 1
    if paren_depth != 0:
        return "", []
    leading = re.match(r"^(\s*)", lines[start_line - 1]).group(1)
    logical_line = " ".join(segment.strip() for segment in segments if segment.strip())
    return f"{leading}{logical_line}", consumed_lines


def _logical_assignment_line(lines: list[str], start_line: int, form: str) -> tuple[str, list[int]]:
    # A comment is never a statement. _statement_line_segment strips the
    # fixed-form marker along with the label field, so without this a
    # commented-out branch, assignment or CALL is stitched into executable
    # text and rewritten as code. Guarded here rather than only at the call
    # sites, so a future caller inherits the guard instead of the bug.
    if _is_commented(lines[start_line - 1]):
        return "", []
    first_segment = _statement_line_segment(lines[start_line - 1], form)
    if re.match(r"^\s*(?:CALL|(?:ELSE\s*)?IF|DO|RETURN|END\b|GOTO\b)", first_segment, flags=re.IGNORECASE):
        return "", []
    if not re.match(r"^\s*[A-Za-z_]\w*(?:\([^=]*\))?\s*=", first_segment, flags=re.IGNORECASE):
        return "", []
    segments = [first_segment]
    consumed_lines: list[int] = []
    next_line_number = start_line + 1
    while next_line_number <= len(lines):
        candidate = lines[next_line_number - 1]
        if not _is_continuation_line(candidate, form):
            break
        candidate_segment = _statement_line_segment(candidate, form)
        segments.append(candidate_segment)
        consumed_lines.append(next_line_number)
        next_line_number += 1
    if not consumed_lines:
        return "", []
    leading = re.match(r"^(\s*)", lines[start_line - 1]).group(1)
    logical_line = " ".join(segment.strip() for segment in segments if segment.strip())
    return f"{leading}{logical_line}", consumed_lines


def _argument_shape(argument: str, variable_shapes: dict[str, str]) -> str:
    name = _base_argument_name(argument)
    if name.endswith("_OTI"):
        name = name[:-4]
    return variable_shapes.get(name, "")


def _is_oti_argument(argument: str) -> bool:
    return _base_argument_name(argument).endswith("_OTI")


def _inline_kinver(form: str, matrix: str, output: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline finite-strain helper KINVER"),
        _stmt(form, "DO OTI_HI = 1, 3"),
        _stmt(form, "   DO OTI_HJ = 1, 3"),
        _stmt(form, f"      {output}(OTI_HI,OTI_HJ) = {matrix}(OTI_HI,OTI_HJ)"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
        _stmt(form, "DO OTI_HK = 1, 3"),
        _stmt(form, f"   OTI_HX = {output}(OTI_HK,OTI_HK)"),
        _stmt(form, f"   {output}(OTI_HK,OTI_HK) = 1.0D0"),
        _stmt(form, "   DO OTI_HJ = 1, 3"),
        _stmt(form, f"      {output}(OTI_HK,OTI_HJ) = {output}(OTI_HK,OTI_HJ)/OTI_HX"),
        _stmt(form, "   END DO"),
        _stmt(form, "   DO OTI_HI = 1, 3"),
        _stmt(form, "      IF(OTI_HI .NE. OTI_HK) THEN"),
        _stmt(form, f"         OTI_HX = {output}(OTI_HI,OTI_HK)"),
        _stmt(form, f"         {output}(OTI_HI,OTI_HK) = 0.0D0"),
        _stmt(form, "         DO OTI_HJ = 1, 3"),
        _stmt(form, f"            OTI_HY = {output}(OTI_HK,OTI_HJ)*OTI_HX"),
        _stmt(form, f"            OTI_HY = {output}(OTI_HI,OTI_HJ)-OTI_HY"),
        _stmt(form, f"            {output}(OTI_HI,OTI_HJ) = OTI_HY"),
        _stmt(form, "         END DO"),
        _stmt(form, "      END IF"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_kclear(form: str, target: str, nra: str, nca: str, target_shape: str) -> list[str]:
    dims = _shape_dimensions(target_shape)
    if len(dims) == 2 or str(nca).strip() != "1":
        return [
            _comment_line(form, "OTIS inline helper KCLEAR"),
            _stmt(form, f"DO OTI_HI = 1, {nra}"),
            _stmt(form, f"   DO OTI_HJ = 1, {nca}"),
            _stmt(form, f"      {target}(OTI_HI,OTI_HJ) = 0.0D0"),
            _stmt(form, "   END DO"),
            _stmt(form, "END DO"),
        ]
    return [
        _comment_line(form, "OTIS inline helper KCLEAR"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   {target}(OTI_HI) = 0.0D0"),
        _stmt(form, "END DO"),
    ]


def _inline_kproyector(form: str, target: str, target_shape: str, configured_ntens: int) -> list[str]:
    # Always populate the deviatoric projector matrix. It is a constant (2/3,
    # -1/3 entries) and is used both as KMMULT(P, vector) (rewritten directly by
    # _inline_projector_kmmult, which ignores P's values) AND as a plain matrix
    # operand, e.g. KMMULT(QT, P, ...). Leaving P unpopulated for ntens<6 zeroed
    # those matrix-operand uses and collapsed the in-loop spectral FBAR.
    del configured_ntens
    dims = _shape_dimensions(target_shape)
    rows = dims[0] if len(dims) >= 1 else "6"
    cols = dims[1] if len(dims) >= 2 else rows
    lines = [_comment_line(form, "OTIS inline helper KPROYECTOR")]
    lines.extend(_zero_matrix_lines(form, target, rows, cols))
    entries = (
        (1, 1, "TWO/THREE"),
        (1, 2, "-ONE/THREE"),
        (1, 3, "-ONE/THREE"),
        (2, 1, "-ONE/THREE"),
        (2, 2, "TWO/THREE"),
        (2, 3, "-ONE/THREE"),
        (3, 1, "-ONE/THREE"),
        (3, 2, "-ONE/THREE"),
        (3, 3, "TWO/THREE"),
        (4, 4, "TWO"),
        (5, 5, "ONE"),
        (6, 6, "ONE"),
    )
    for row, column, value in entries:
        lines.append(_stmt(form, f"IF ({rows} .GE. {row} .AND. {cols} .GE. {column}) {target}({row},{column})={value}"))
    return lines


def _inline_kmatsub(form: str, a: str, nra: str, nca: str, b: str, c: str, iflag: str) -> list[str]:
    # KMATSUB(A,NRA,NCA,B,C,IFLAG): C = A + B*SCALAR, SCALAR=-1 (default) or +1
    # if IFLAG==1. Pure arithmetic; inlined so it never blocks helper lifting
    # (PCO/VPDCO call it but omit its definition).
    op = "+" if str(iflag).strip() == "1" else "-"
    rhs = f"{a}(OTI_HI,OTI_HJ) {op} {b}(OTI_HI,OTI_HJ)"
    if not _is_oti_argument(c) and (_is_oti_argument(a) or _is_oti_argument(b)):
        rhs = f"REAL({rhs})"
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KMATSUB"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   DO OTI_HJ = 1, {nca}"),
        _stmt(form, f"      {c}(OTI_HI,OTI_HJ) = {rhs}"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_projector_kmmult(
    form: str,
    right: str,
    output: str,
    nra: str,
    right_shape: str,
    output_shape: str,
) -> list[str]:
    right_dims = _shape_dimensions(right_shape)
    output_dims = _shape_dimensions(output_shape)
    right_is_vector = len(right_dims) == 1
    output_is_vector = len(output_dims) == 1

    def right_ref(index: int) -> str:
        return f"{right}({index})" if right_is_vector else f"{right}({index},1)"

    def output_ref(index: int) -> str:
        return f"{output}({index})" if output_is_vector else f"{output}({index},1)"

    lines = [_comment_line(form, "OTIS inline pure arithmetic helper KMMULT (deviatoric projector)")]
    lines.extend(
        [
            _stmt(form, f"DO OTI_HI = 1, {nra}"),
            _stmt(form, f"   {_output_ref_expr(output, output_is_vector)} = 0.0D0"),
            _stmt(form, "END DO"),
        ]
    )
    lines.extend(
        [
            _stmt(form, f"IF ({nra} .GE. 3) THEN"),
            _stmt(form, f"   {output_ref(1)} = (TWO/THREE)*{right_ref(1)}-(ONE/THREE)*{right_ref(2)}-(ONE/THREE)*{right_ref(3)}"),
            _stmt(form, f"   {output_ref(2)} = -(ONE/THREE)*{right_ref(1)}+(TWO/THREE)*{right_ref(2)}-(ONE/THREE)*{right_ref(3)}"),
            _stmt(form, f"   {output_ref(3)} = -(ONE/THREE)*{right_ref(1)}-(ONE/THREE)*{right_ref(2)}+(TWO/THREE)*{right_ref(3)}"),
            _stmt(form, "END IF"),
            _stmt(form, f"IF ({nra} .GE. 6) THEN"),
            _stmt(form, f"   {output_ref(4)} = TWO*{right_ref(4)}"),
            _stmt(form, f"   {output_ref(5)} = {right_ref(5)}"),
            _stmt(form, f"   {output_ref(6)} = {right_ref(6)}"),
            _stmt(form, f"ELSE IF ({nra} .GE. 4) THEN"),
            _stmt(form, f"   {output_ref(4)} = {right_ref(4)}"),
            _stmt(form, "END IF"),
            _stmt(form, f"IF ({nra} .GE. 5 .AND. {nra} .LT. 6) THEN"),
            _stmt(form, f"   {output_ref(5)} = {right_ref(5)}"),
            _stmt(form, "END IF"),
        ]
    )
    return lines


def _output_ref_expr(output: str, output_is_vector: bool) -> str:
    return f"{output}(OTI_HI)" if output_is_vector else f"{output}(OTI_HI,1)"


def _inline_ktnorm(form: str, left: str, right: str, output: str, ntens: str, ndi: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline helper KTNORM"),
        _stmt(form, f"{output} = 0.0D0"),
        _stmt(form, f"DO OTI_HI = 1, {ndi}"),
        _stmt(form, f"   {output} = {output} + {left}(OTI_HI)*{right}(OTI_HI)"),
        _stmt(form, "END DO"),
        _stmt(form, f"DO OTI_HI = {ndi}+1, {ntens}"),
        _stmt(form, f"   {output} = {output} + 2.0D0*{left}(OTI_HI)*{right}(OTI_HI)"),
        _stmt(form, "END DO"),
    ]


def _inline_ktmult(
    form: str,
    left: str,
    nra: str,
    nca: str,
    right: str,
    nrb: str,
    ncb: str,
    output: str,
    ndi: str,
) -> list[str]:
    del nca
    return [
        _comment_line(form, "OTIS inline helper KTMULT"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   DO OTI_HJ = 1, {ncb}"),
        _stmt(form, "      OTI_HX = 0.0D0"),
        _stmt(form, f"      DO OTI_HK = 1, {ndi}"),
        _stmt(form, f"         OTI_HY = {left}(OTI_HI,OTI_HK)*{right}(OTI_HK,OTI_HJ)"),
        _stmt(form, "         OTI_HX = OTI_HX + OTI_HY"),
        _stmt(form, "      END DO"),
        _stmt(form, f"      DO OTI_HK = {ndi}+1, {nrb}"),
        _stmt(form, f"         OTI_HY = 2.0D0*{left}(OTI_HI,OTI_HK)*{right}(OTI_HK,OTI_HJ)"),
        _stmt(form, "         OTI_HX = OTI_HX + OTI_HY"),
        _stmt(form, "      END DO"),
        _stmt(form, f"      {output}(OTI_HI,OTI_HJ) = OTI_HX"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_kmlt(form: str, left: str, right: str, output: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline finite-strain helper KMLT"),
        _stmt(form, "DO OTI_HI = 1, 3"),
        _stmt(form, "   DO OTI_HJ = 1, 3"),
        _stmt(form, "      OTI_HX = 0.0D0"),
        _stmt(form, "      DO OTI_HK = 1, 3"),
        _stmt(form, f"         OTI_HY = {left}(OTI_HI,OTI_HK)*{right}(OTI_HK,OTI_HJ)"),
        _stmt(form, "         OTI_HX = OTI_HX + OTI_HY"),
        _stmt(form, "      END DO"),
        _stmt(form, f"      {output}(OTI_HI,OTI_HJ) = OTI_HX"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_ktrace(form: str, matrix: str, output: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline finite-strain helper KTRACE"),
        _stmt(form, f"{output} = 0.0D0"),
        _stmt(form, "DO OTI_HI = 1, 3"),
        _stmt(form, f"   {output} = {output} + {matrix}(OTI_HI,OTI_HI)"),
        _stmt(form, "END DO"),
    ]


def _inline_kdamacal(
    form: str,
    stress: str,
    gam_par: str,
    flow: str,
    props: str,
    nprops: str,
    ntens: str,
    este: str,
    theta: str,
    damage: str,
) -> list[str]:
    del nprops
    return [
        _comment_line(form, "OTIS inline helper KDAMACAL"),
        _stmt(form, f"OTI_HX = {props}(24)/({props}(23)*{props}(17))/10.0D0"),
        _stmt(form, f"DO OTI_HI = 1, MIN(3,{ntens})"),
        _stmt(form, f"   OTI_HY = {gam_par}*{flow}(OTI_HI)"),
        _stmt(form, f"   {este} = {este} + ABS({stress}(OTI_HI)*OTI_HY/{theta})"),
        _stmt(form, "END DO"),
        _stmt(form, f"IF ({ntens} .GE. 4) THEN"),
        _stmt(form, f"   OTI_HY = TWO*{gam_par}*{flow}(4)"),
        _stmt(form, f"   {este} = {este} + ABS({stress}(4)*OTI_HY/{theta})"),
        _stmt(form, "END IF"),
        _stmt(form, f"{damage} = ONE-EXP(-OTI_HX*{este})"),
    ]


def _inline_kdamacal_damage_only(
    form: str,
    stress: str,
    flow: str,
    ntens: str,
    props: str,
    nprops: str,
    este: str,
    damage: str,
) -> list[str]:
    del nprops
    return [
        _comment_line(form, "OTIS inline helper KDAMACAL"),
        _stmt(form, f"OTI_HX = {props}(24)/({props}(23)*{props}(17))/10.0D0"),
        _stmt(form, f"OTI_HY = {props}(1)"),
        _stmt(form, f"DO OTI_HI = 1, MIN(3,{ntens})"),
        _stmt(form, f"   {este} = {este} + ABS({stress}(OTI_HI)*{flow}(OTI_HI)/OTI_HY)"),
        _stmt(form, "END DO"),
        _stmt(form, f"{damage} = ONE-EXP(-OTI_HX*{este})"),
    ]


def _inline_ktrans(form: str, original: str, transposed: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline finite-strain helper KTRANS"),
        _stmt(form, "DO OTI_HI = 1, 3"),
        _stmt(form, "   DO OTI_HJ = 1, 3"),
        _stmt(form, f"      {transposed}(OTI_HJ,OTI_HI) = {original}(OTI_HI,OTI_HJ)"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_kmlt1(form: str, matrix: str, vector: str, output: str, ntens: str) -> list[str]:
    output_expr = "OTI_HX" if _is_oti_argument(output) else "REAL(OTI_HX)"
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KMLT1"),
        _stmt(form, f"DO OTI_HI = 1, {ntens}"),
        _stmt(form, "   OTI_HX = 0.0D0"),
        _stmt(form, f"   DO OTI_HK = 1, {ntens}"),
        _stmt(form, f"      OTI_HY = {matrix}(OTI_HI,OTI_HK)*{vector}(OTI_HK)"),
        _stmt(form, "      OTI_HX = OTI_HX + OTI_HY"),
        _stmt(form, "   END DO"),
        _stmt(form, f"   {output}(OTI_HI) = {output_expr}"),
        _stmt(form, "END DO"),
    ]


def _inline_ksmult(form: str, matrix: str, nra: str, nca: str, scalar: str) -> list[str]:
    if str(nca).strip() == "1":
        return [
            _comment_line(form, "OTIS inline pure arithmetic helper KSMULT"),
            _stmt(form, f"DO OTI_HI = 1, {nra}"),
            _stmt(form, f"   {matrix}(OTI_HI) = {matrix}(OTI_HI)*{scalar}"),
            _stmt(form, "END DO"),
        ]
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KSMULT"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   DO OTI_HJ = 1, {nca}"),
        _stmt(form, f"      {matrix}(OTI_HI,OTI_HJ) = {matrix}(OTI_HI,OTI_HJ)*{scalar}"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _zero_matrix_lines(form: str, matrix: str, rows: str, cols: str) -> list[str]:
    return [
        _stmt(form, f"DO OTI_HI = 1, {rows}"),
        _stmt(form, f"   DO OTI_HJ = 1, {cols}"),
        _stmt(form, f"      {matrix}(OTI_HI,OTI_HJ) = 0.0D0"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_kuhardnlin(
    form: str,
    syieldi: str,
    syieldk: str,
    hmod: str,
    sig0: str,
    sigsat: str,
    hrdrate: str,
    ehardi: str,
    ehardk: str,
    eqplas: str,
) -> list[str]:
    return [
        _comment_line(form, "OTIS inline helper KUHARDNLIN"),
        _stmt(form, f"{syieldi}=SQRT(TWO/THREE)*({sig0}+{sigsat}*(ONE-EXP(-{hrdrate}*{eqplas})))"),
        _stmt(form, f"{ehardi}={sigsat}*{hrdrate}*(EXP(-{hrdrate}*{eqplas}))"),
        _stmt(form, f"{syieldk}={hmod}*{eqplas}"),
        _stmt(form, f"{ehardk}={hmod}"),
    ]


def _inline_kuhardnlin_simple(
    form: str,
    syieldi: str,
    sig0: str,
    sigsat: str,
    ehardi: str,
    eqplas: str,
    hrdrate: str,
) -> list[str]:
    return [
        _comment_line(form, "OTIS inline helper KUHARDNLIN"),
        _stmt(form, f"{syieldi}=SQRT(TWO/THREE)*({sig0}+{sigsat}*(ONE-EXP(-{hrdrate}*{eqplas})))"),
        _stmt(form, f"{ehardi}={sigsat}*{hrdrate}*(EXP(-{hrdrate}*{eqplas}))"),
    ]


def _inline_kspectral_damage(
    form: str,
    q: str,
    dp: str,
    dc: str,
    diag: str,
    gdia: str,
    gam_par: str,
    e: str,
    enu: str,
    ek: str,
    damage: str,
) -> list[str]:
    eg2 = f"({e}/(ONE+{enu}))"
    eg = f"(({e}/(ONE+{enu}))/TWO)"
    elam = f"(({e}/(ONE+{enu}))*{enu}/(ONE-TWO*{enu}))"
    teta1 = f"(ONE+(TWO/THREE)*{gam_par}*(ONE-{damage})*{ek})"
    cbeta2 = f"(({e}/(ONE+{enu}))+(TWO/THREE)*(ONE-{damage})*{ek})"
    lines = [_comment_line(form, "OTIS inline helper KSPECTRAL")]
    lines.extend(_zero_matrix_lines(form, q, "NTENS", "NTENS"))
    lines.extend(_zero_matrix_lines(form, dp, "NTENS", "NTENS"))
    lines.extend(_zero_matrix_lines(form, dc, "NTENS", "NTENS"))
    lines.extend(_zero_matrix_lines(form, diag, "NTENS", "NTENS"))
    lines.extend(_zero_matrix_lines(form, gdia, "NTENS", "NTENS"))
    lines.extend(
        [
            _stmt(form, f"{q}(1,1)=ZERO"),
            _stmt(form, f"IF (NTENS .GE. 2) {q}(1,2)=TWO/SQRT(SIX)"),
            _stmt(form, f"IF (NTENS .GE. 3) {q}(1,3)=ONE/SQRT(THREE)"),
            _stmt(form, f"IF (NTENS .GE. 2) {q}(2,1)=-SQRT(TWO)/TWO"),
            _stmt(form, f"IF (NTENS .GE. 2) {q}(2,2)=-ONE/SQRT(SIX)"),
            _stmt(form, f"IF (NTENS .GE. 3) {q}(2,3)=ONE/SQRT(THREE)"),
            _stmt(form, f"IF (NTENS .GE. 3) {q}(3,1)=SQRT(TWO)/TWO"),
            _stmt(form, f"IF (NTENS .GE. 3) {q}(3,2)=-ONE/SQRT(SIX)"),
            _stmt(form, f"IF (NTENS .GE. 3) {q}(3,3)=ONE/SQRT(THREE)"),
            _stmt(form, f"IF (NTENS .GE. 4) {q}(4,4)=ONE"),
            _stmt(form, f"IF (NTENS .GE. 5) {q}(5,5)=ONE"),
            _stmt(form, f"IF (NTENS .GE. 6) {q}(6,6)=ONE"),
            _stmt(form, f"{dp}(1,1)=ONE"),
            _stmt(form, f"IF (NTENS .GE. 2) {dp}(2,2)=ONE"),
            _stmt(form, f"IF (NTENS .GE. 3) {dp}(3,3)=ZERO"),
            _stmt(form, f"IF (NTENS .GE. 4) {dp}(4,4)=TWO"),
            _stmt(form, f"IF (NTENS .GE. 5) {dp}(5,5)=ONE"),
            _stmt(form, f"IF (NTENS .GE. 6) {dp}(6,6)=ONE"),
            _stmt(form, f"{dc}(1,1)={eg2}"),
            _stmt(form, f"IF (NTENS .GE. 2) {dc}(2,2)={eg2}"),
            _stmt(form, f"IF (NTENS .GE. 3) {dc}(3,3)=THREE*{elam}+{eg2}"),
            _stmt(form, f"IF (NTENS .GE. 4) {dc}(4,4)={eg}"),
            _stmt(form, f"IF (NTENS .GE. 5) {dc}(5,5)={eg2}"),
            _stmt(form, f"IF (NTENS .GE. 6) {dc}(6,6)={eg2}"),
            _stmt(form, f"{diag}(1,1)=ONE/(ONE+{cbeta2}*{gam_par})"),
            _stmt(form, f"IF (NTENS .GE. 2) {diag}(2,2)=ONE/(ONE+{cbeta2}*{gam_par})"),
            _stmt(form, f"IF (NTENS .GE. 3) {diag}(3,3)=ONE/{teta1}"),
            _stmt(form, f"IF (NTENS .GE. 4) {diag}(4,4)=ONE/(ONE+{cbeta2}*{gam_par})"),
            _stmt(form, f"IF (NTENS .GE. 5) {diag}(5,5)=ONE/(ONE+{cbeta2}*{gam_par})"),
            _stmt(form, f"IF (NTENS .GE. 6) {diag}(6,6)=ONE/(ONE+{cbeta2}*{gam_par})"),
            _stmt(form, f"{gdia}(1,1)=-({cbeta2}/((ONE+{cbeta2}*{gam_par})**2.0D0))"),
            _stmt(form, f"IF (NTENS .GE. 2) {gdia}(2,2)=-({cbeta2}/((ONE+{cbeta2}*{gam_par})**2.0D0))"),
            _stmt(form, f"IF (NTENS .GE. 3) {gdia}(3,3)=-((TWO/THREE)*{ek})/({teta1}**2.0D0)"),
            _stmt(form, f"IF (NTENS .GE. 4) {gdia}(4,4)=-({cbeta2}/((ONE+{cbeta2}*{gam_par})**2.0D0))"),
            _stmt(form, f"IF (NTENS .GE. 5) {gdia}(5,5)=-({cbeta2}/((ONE+{cbeta2}*{gam_par})**2.0D0))"),
            _stmt(form, f"IF (NTENS .GE. 6) {gdia}(6,6)=-({cbeta2}/((ONE+{cbeta2}*{gam_par})**2.0D0))"),
        ]
    )
    return lines


def _inline_kmmult(
    form: str,
    left: str,
    nra: str,
    nca: str,
    right: str,
    nrb: str,
    ncb: str,
    output: str,
    left_shape: str,
    right_shape: str,
    output_shape: str,
    configured_ntens: int,
) -> list[str]:
    del nrb
    left_dims = _shape_dimensions(left_shape)
    right_dims = _shape_dimensions(right_shape)
    output_dims = _shape_dimensions(output_shape)
    left_is_vector = len(left_dims) == 1
    right_is_vector = len(right_dims) == 1
    output_is_vector = len(output_dims) == 1
    output_is_oti = _is_oti_argument(output)
    left_base_name = _base_argument_name(left)
    if left_base_name.endswith("_OTI"):
        left_base_name = left_base_name[:-4]
    if configured_ntens < 6 and left_base_name == "P" and not left_is_vector and str(ncb).strip() == "1":
        return _inline_projector_kmmult(form, right, output, nra, right_shape, output_shape)
    left_ref = f"{left}(OTI_HK)" if left_is_vector else f"{left}(OTI_HI,OTI_HK)"
    right_ref_vector = f"{right}(OTI_HK)" if right_is_vector else f"{right}(OTI_HK,1)"
    right_ref_matrix = f"{right}(OTI_HK)" if right_is_vector else f"{right}(OTI_HK,OTI_HJ)"
    output_expr = "OTI_HX" if output_is_oti else "REAL(OTI_HX)"
    if output_is_vector:
        return [
            _comment_line(form, "OTIS inline pure arithmetic helper KMMULT"),
            _stmt(form, f"DO OTI_HI = 1, {nra}"),
            _stmt(form, "   OTI_HX = 0.0D0"),
            _stmt(form, f"   DO OTI_HK = 1, {nca}"),
            _stmt(form, f"      OTI_HY = {left_ref}*{right_ref_vector}"),
            _stmt(form, "      OTI_HX = OTI_HX + OTI_HY"),
            _stmt(form, "   END DO"),
            _stmt(form, f"   {output}(OTI_HI) = {output_expr}"),
            _stmt(form, "END DO"),
        ]
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KMMULT"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   DO OTI_HJ = 1, {ncb}"),
        _stmt(form, "      OTI_HX = 0.0D0"),
        _stmt(form, f"      DO OTI_HK = 1, {nca}"),
        _stmt(form, f"         OTI_HY = {left_ref}*{right_ref_matrix}"),
        _stmt(form, "         OTI_HX = OTI_HX + OTI_HY"),
        _stmt(form, "      END DO"),
        _stmt(form, f"      {output}(OTI_HI,OTI_HJ) = {output_expr}"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_kmtran(form: str, matrix: str, nra: str, nca: str, output: str, matrix_shape: str, output_shape: str) -> list[str]:
    matrix_dims = _shape_dimensions(matrix_shape)
    output_dims = _shape_dimensions(output_shape)
    matrix_is_vector = len(matrix_dims) == 1
    output_is_vector = len(output_dims) == 1
    source_vector_ref = f"{matrix}(OTI_HI)"
    source_row_ref = f"{matrix}(1,OTI_HJ)"
    source_matrix_ref = f"{matrix}(OTI_HI,OTI_HJ)"
    if not _is_oti_argument(output) and _is_oti_argument(matrix):
        source_vector_ref = f"REAL({source_vector_ref})"
        source_row_ref = f"REAL({source_row_ref})"
        source_matrix_ref = f"REAL({source_matrix_ref})"
    if matrix_is_vector and not output_is_vector:
        return [
            _comment_line(form, "OTIS inline pure arithmetic helper KMTRAN"),
            _stmt(form, f"DO OTI_HI = 1, {nra}"),
            _stmt(form, f"   {output}(1,OTI_HI) = {source_vector_ref}"),
            _stmt(form, "END DO"),
        ]
    if not matrix_is_vector and output_is_vector:
        return [
            _comment_line(form, "OTIS inline pure arithmetic helper KMTRAN"),
            _stmt(form, f"DO OTI_HJ = 1, {nca}"),
            _stmt(form, f"   {output}(OTI_HJ) = {source_row_ref}"),
            _stmt(form, "END DO"),
        ]
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KMTRAN"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   DO OTI_HJ = 1, {nca}"),
        _stmt(form, f"      {output}(OTI_HJ,OTI_HI) = {source_matrix_ref}"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_vsprate(
    form: str,
    props: str,
    nprops: str,
    emod: str,
    enu: str,
    sneta: str,
    sig0: str,
    sigsat: str,
    hmod: str,
    hrdrate: str,
    theta: str | None = None,
    gamhard: str | None = None,
) -> list[str]:
    del nprops
    theta_expr = f"REAL({theta})" if theta else f"REAL({props}(1))"
    gmod = f"((REAL({props}(4))+REAL({props}(5))*({theta_expr}))*1000.0D0)"
    r_infi = f"(REAL({props}(11))+REAL({props}(12))*({theta_expr}))"
    x_infi = f"REAL({props}(9))"
    fluidity = (
        f"((((REAL({props}(14))*REAL({props}(15))*REAL({emod})*REAL({props}(16)))"
        f"/(REAL({props}(17))*({theta_expr})))*(REAL({emod})**REAL({props}(20))))"
        f"*((REAL({props}(16))/REAL({props}(18)))**REAL({props}(19))))*OTI_HX"
    )
    def mirrored_assignment(target: str, expr: str) -> list[str]:
        lines: list[str] = []
        base_name = _base_argument_name(target)
        if base_name.endswith("_OTI"):
            lines.append(_stmt(form, f"{base_name[:-4]} = {expr}"))
        lines.append(_stmt(form, f"{target} = {expr}"))
        return lines

    def mirrored_conditional_assignment(condition: str, target: str, expr: str) -> list[str]:
        lines: list[str] = []
        base_name = _base_argument_name(target)
        if base_name.endswith("_OTI"):
            lines.append(_stmt(form, f"IF ({condition}) {base_name[:-4]} = {expr}"))
        lines.append(_stmt(form, f"IF ({condition}) {target} = {expr}"))
        return lines

    lines = [_comment_line(form, "OTIS inline helper VSPRATE")]
    lines.extend(mirrored_assignment(emod, f"((REAL({props}(2))+REAL({props}(3))*({theta_expr}))*1000.0D0)"))
    lines.extend(mirrored_assignment(enu, f"(({emod})/(TWO*({gmod})))-ONE"))
    lines.extend(mirrored_assignment(sig0, f"REAL({props}(6))+REAL({props}(7))*({theta_expr})"))
    lines.extend(mirrored_assignment(sigsat, r_infi))
    lines.extend(mirrored_assignment(hrdrate, f"REAL({props}(13))"))
    lines.extend(mirrored_assignment(sneta, "0.0D0"))
    lines.append(_stmt(form, f"OTI_HX = EXP(-REAL({props}(21))/(REAL({props}(22))*({theta_expr})))"))
    lines.append(_stmt(form, f"OTI_HY = {fluidity}"))
    lines.extend(mirrored_conditional_assignment("REAL(OTI_HY) .NE. 0.0D0", sneta, "REAL(ONE/OTI_HY)"))
    if gamhard:
        lines[4:4] = mirrored_assignment(gamhard, f"SQRT(TWO/THREE)*REAL({props}(10))")
        lines[4 + len(mirrored_assignment(gamhard, f"SQRT(TWO/THREE)*REAL({props}(10))")):4 + len(mirrored_assignment(gamhard, f"SQRT(TWO/THREE)*REAL({props}(10))"))] = mirrored_assignment(hmod, f"TWO*{x_infi}/THREE")
    else:
        lines[4:4] = mirrored_assignment(hmod, f"REAL({props}(10))*{x_infi}")
    return lines


def _inline_kmavec(form: str, matrix: str, nra: str, nca: str, vector: str, output: str) -> list[str]:
    output_expr = "OTI_HX" if _is_oti_argument(output) else "REAL(OTI_HX)"
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KMAVEC"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   {output}(OTI_HI) = 0.0D0"),
        _stmt(form, "END DO"),
        _stmt(form, f"DO OTI_HI = 1, {nra}"),
        _stmt(form, f"   DO OTI_HK = 1, {nca}"),
        _stmt(form, f"      OTI_HX = {matrix}(OTI_HI,OTI_HK)*{vector}(OTI_HK)"),
        _stmt(form, f"      {output}(OTI_HI) = {output}(OTI_HI) + {output_expr}"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_kupdvec(form: str, vector: str, size: str, increment: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KUPDVEC"),
        _stmt(form, f"DO OTI_HI = 1, {size}"),
        _stmt(form, f"   {vector}(OTI_HI) = {vector}(OTI_HI) + {increment}(OTI_HI)"),
        _stmt(form, "END DO"),
    ]


def _inline_kdevia(form: str, stress_matrix: str, identity: str, output: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KDEVIA"),
        _stmt(form, "OTI_HTR = 0.0D0"),
        _stmt(form, "DO OTI_HI = 1, 3"),
        _stmt(form, f"   OTI_HTR = OTI_HTR + {stress_matrix}(OTI_HI,OTI_HI)"),
        _stmt(form, "END DO"),
        _stmt(form, "DO OTI_HI = 1, 3"),
        _stmt(form, "   DO OTI_HJ = 1, 3"),
        _stmt(form, "      IF(OTI_HI .EQ. OTI_HJ) THEN"),
        _stmt(form, f"         OTI_HY = (1.0D0/3.0D0)*OTI_HTR*{identity}(OTI_HI,OTI_HJ)"),
        _stmt(form, f"         {output}(OTI_HI,OTI_HJ) = {stress_matrix}(OTI_HI,OTI_HJ)-OTI_HY"),
        _stmt(form, "      ELSE"),
        _stmt(form, f"         {output}(OTI_HI,OTI_HJ) = {stress_matrix}(OTI_HI,OTI_HJ)"),
        _stmt(form, "      END IF"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _inline_keffp(form: str, effective_matrix: str, output: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper KEFFP"),
        _stmt(form, f"{output} = 0.0D0"),
        _stmt(form, "OTI_HX = 0.0D0"),
        _stmt(form, "DO OTI_HI = 1, 3"),
        _stmt(form, "   DO OTI_HJ = 1, 3"),
        _stmt(form, f"      OTI_HY = {effective_matrix}(OTI_HI,OTI_HJ)*{effective_matrix}(OTI_HI,OTI_HJ)"),
        _stmt(form, "      OTI_HX = OTI_HX + OTI_HY"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
        _stmt(form, "IF(REAL(OTI_HX) .GT. 0.0D0) THEN"),
        _stmt(form, f"   {output} = SQRT((3.0D0/2.0D0)*OTI_HX)"),
        _stmt(form, "END IF"),
    ]


def _inline_dotprod(form: str, left: str, right: str, output: str, ntens: str) -> list[str]:
    output_expr = "OTI_HY" if _is_oti_argument(output) else "REAL(OTI_HY)"
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper DOTPROD"),
        _stmt(form, "OTI_HY = 0.0D0"),
        _stmt(form, f"DO OTI_HK = 1, {ntens}"),
        _stmt(form, f"   OTI_HX = {left}(OTI_HK)*{right}(OTI_HK)"),
        _stmt(form, "   OTI_HY = OTI_HY + OTI_HX"),
        _stmt(form, "END DO"),
        _stmt(form, f"{output} = {output_expr}"),
    ]


def _inline_dyadicprod(form: str, left: str, right: str, output: str, ntens: str) -> list[str]:
    return [
        _comment_line(form, "OTIS inline pure arithmetic helper DYADICPROD"),
        _stmt(form, f"DO OTI_HI = 1, {ntens}"),
        _stmt(form, f"   DO OTI_HJ = 1, {ntens}"),
        _stmt(form, f"      {output}(OTI_HI,OTI_HJ) = {left}(OTI_HI)*{right}(OTI_HJ)"),
        _stmt(form, "   END DO"),
        _stmt(form, "END DO"),
    ]


def _split_call_arguments(text: str) -> list[str]:
    result: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            result.append(text[start:index].strip())
            start = index + 1
    result.append(text[start:].strip())
    return [item for item in result if item]


def _wrap_oti_condition_with_real(line: str) -> str:
    if "_OTI" not in line.upper():
        return line
    match = re.match(r"^(\s*(?:ELSE\s*)?IF\s*)\(", line, flags=re.IGNORECASE)
    if not match:
        return line
    prefix = match.group(1)
    condition_start = match.end()
    depth = 1
    condition_end = -1
    for index in range(condition_start, len(line)):
        char = line[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                condition_end = index
                break
    if condition_end < 0:
        return line
    condition = line[condition_start:condition_end]
    suffix = line[condition_end + 1 :]
    return f"{prefix}({_real_wrapped_oti_tokens(condition)}){suffix}"


def _is_promoted_branch_line(line: str, replacement_names: dict[str, str]) -> bool:
    if not replacement_names or not re.match(r"^\s*(?:ELSE\s*)?IF\s*\(", line, flags=re.IGNORECASE):
        return False
    # ``IF (ABS(RES).GT.1.D-12)`` mentions no promoted variable, whatever a
    # model happens to have called D.
    scanned = without_real_literals(line)
    return any(re.search(rf"\b{re.escape(name)}\b", scanned, flags=re.IGNORECASE) for name in replacement_names)


def _real_wrapped_oti_tokens(condition: str) -> str:
    token_pattern = re.compile(r"\b[A-Za-z_]\w*_OTI(?:\([^()]*\))?", flags=re.IGNORECASE)

    def replacement(match: re.Match[str]) -> str:
        token = match.group(0)
        before = condition[: match.start()].upper()
        if before.endswith("REAL("):
            return token
        return f"REAL({token})"

    return token_pattern.sub(replacement, condition)


def _normalize_numeric_literals_in_oti_expression(line: str, type_name: str = "") -> str:
    if "_OTI" not in line.upper():
        return line
    normalized = re.sub(
        r"(?<![A-Za-z0-9_])((?:\d+\.\d*)|(?:\d+\.))(?![A-Za-z0-9_.dDeE])",
        lambda match: match.group(1) if match.group(1).upper().endswith("D0") else match.group(1).rstrip(".") + (".0" if match.group(1).endswith(".") else "") + "D0",
        line,
    )
    # From here on only *bare integers* are promoted, so the complete real
    # literals are masked out first. Their digits are not factors: in
    # 3.8019047483079793e-6*Sin(...) the exponent's 6 was read as an integer
    # multiplying Sin and rewritten, leaving 3.8019047483079793e-6.0D0.
    #
    # This used to be a (?<![eEdD][+-]) lookbehind rather than a mask. A
    # lookbehind reads spelling where the property is position, so it also
    # fired on D-6*Y_OTI -- an ordinary variable D, minus six times Y -- and
    # left an INTEGER factor the OTI library has no overload for. It also has
    # to be written out again at every rewrite that could reach a literal,
    # which is how the substitution above came to be missing one.
    normalized, literals = mask_real_literals(normalized)
    normalized = re.sub(r"(?<![A-Za-z0-9_.)])(\d+)(?![A-Za-z0-9_.])(?=\s*[*\/])", r"\1.0D0", normalized)
    normalized = re.sub(r"([*\/])\s*(\d+)(?![A-Za-z0-9_.])", r"\1\2.0D0", normalized)
    return unmask_real_literals(normalized, literals)


def _selected_header_end(parsed: ParsedFortranSource, selected_umat: str) -> int | None:
    for routine in parsed.subroutines:
        if routine.upper_name == selected_umat.upper() and routine.lines:
            return routine.lines[0].line_numbers[-1]
    return None


def _selected_routine_span(parsed: ParsedFortranSource, selected_umat: str) -> tuple[int, int] | None:
    for routine in parsed.subroutines:
        if routine.upper_name == selected_umat.upper() and routine.lines:
            return routine.lines[0].line_numbers[0], routine.lines[-1].line_numbers[-1]
    return None


def _first_executable_line(parsed: ParsedFortranSource, selected_umat: str) -> int | None:
    for routine in parsed.subroutines:
        if routine.upper_name != selected_umat.upper():
            continue
        for line in routine.lines[1:]:
            if _is_executable_line(line.text):
                return line.line_numbers[0]
    return None


def _names_present_in_span(
    source_lines: list[str],
    selected_routine_span: tuple[int, int],
    names: set[str],
    argument_variables: set[str],
) -> set[str]:
    """Those of ``names`` the selected routine mentions, or receives as an argument.

    A declaration emitted into a routine has to be about that routine. A name
    belonging to another subprogram brings that subprogram's bounds with it,
    and those resolve to nothing here.
    """
    start_line, end_line = selected_routine_span
    selected_text = "\n".join(
        line
        for line in source_lines[max(start_line - 1, 0) : min(end_line, len(source_lines))]
        if not _is_commented(line)
    )
    result: set[str] = set()
    for name in names:
        if name in argument_variables or re.search(
                rf"\b{re.escape(name)}\b", selected_text, flags=re.IGNORECASE):
            result.add(name)
    return result


def _shapes_declared_in_selected_routine(
    parsed: ParsedFortranSource,
    selected_umat: str,
    variable_shapes: dict[str, str],
) -> dict[str, str]:
    """``variable_shapes`` with the selected routine's own declarations on top.

    Only names the routine declares are overridden; everything else keeps the
    file-wide answer, which is all there is for a name declared nowhere.
    """
    for routine in parsed.subroutines:
        if routine.upper_name != selected_umat.upper():
            continue
        updated = dict(variable_shapes)
        for declaration in routine.declarations:
            for entity in declaration.entities:
                if entity.dimensions:
                    updated[entity.upper_name] = ", ".join(entity.dimensions)
        for line in routine.lines:
            match = re.match(r"^\s*dimension\s+(.+)$", line.text, flags=re.IGNORECASE)
            if not match:
                continue
            for item in split_top_level(match.group(1)):
                entity = parse_entity(item)
                if entity.dimensions:
                    updated[entity.upper_name] = ", ".join(entity.dimensions)
        return updated
    return variable_shapes


def _shadow_variable_names_for_selected_routine(
    source_lines: list[str],
    selected_routine_span: tuple[int, int],
    roles: dict[str, set[str]],
    argument_variables: set[str],
) -> set[str]:
    return _names_present_in_span(
        source_lines, selected_routine_span,
        roles["seed"] | roles["promote"], argument_variables)


def _lifted_helper_argument_shadow_names(
    config: dict[str, Any],
    stress_regions: list[dict[str, Any]],
    lifted_helper_names: set[str],
    variable_shapes: dict[str, str],
) -> set[str]:
    helper_names = set(INLINEABLE_HELPERS) | set(lifted_helper_names)
    if not helper_names:
        return set()
    analysis = _dict(config.get("analysis"))
    keep_real_names = _roles_from_config(config)["keep_real"]
    known_variables = set(_variable_role_items(config)) | {name.upper() for name in variable_shapes}
    result: set[str] = set()
    for row in analysis.get("stress_path_helpers", []) or []:
        if not isinstance(row, dict):
            continue
        callee = str(row.get("callee", "")).upper()
        line_numbers = tuple(_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value))
        if callee not in helper_names or not line_numbers:
            continue
        if not _line_numbers_intersect(line_numbers, stress_regions):
            continue
        for name in _helper_argument_base_names(row.get("arguments", []) or []):
            if name in INTRINSIC_TOKEN_NAMES or _is_implicit_integer_name(name):
                continue
            if name in keep_real_names:
                continue
            if known_variables and name not in known_variables:
                continue
            result.add(name)
    return result


def _is_implicit_integer_name(name: str) -> bool:
    return bool(name) and name[0].upper() in IMPLICIT_INTEGER_FIRST_LETTERS


def _line_in_span(line_number: int, span: tuple[int, int]) -> bool:
    return span[0] <= line_number <= span[1]


def _first_region_start(regions: dict[str, list[dict[str, Any]]]) -> int:
    starts = [region["start_line"] for rows in regions.values() for region in rows if region.get("start_line")]
    return min(starts) if starts else 1


def _region_rows(rows: Any) -> list[dict[str, Any]]:
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        start = _as_int(row.get("start_line") or row.get("start line"))
        end = _as_int(row.get("end_line") or row.get("end line"))
        if start <= 0 or end <= 0:
            continue
        result.append(
            {
                "region_id": str(row.get("region_id") or row.get("region id") or ""),
                "start_line": start,
                "end_line": end,
                "reason": str(row.get("reason") or row.get("detected reason") or ""),
                "classification": str(row.get("classification") or row.get("user-selected classification") or ""),
                "variables": _upper_list(row.get("variables") or row.get("detected variables") or []),
                "preview": str(row.get("preview") or row.get("short code preview") or ""),
            }
        )
    return result


def _line_set(regions: list[dict[str, Any]]) -> set[int]:
    result: set[int] = set()
    for region in regions:
        result.update(range(region["start_line"], region["end_line"] + 1))
    return result


def _region_by_line(regions: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for region in regions:
        for line_number in range(region["start_line"], region["end_line"] + 1):
            result[line_number] = region
    return result


def _line_numbers_intersect(line_numbers: Any, regions: list[dict[str, Any]]) -> bool:
    try:
        numbers = [int(value) for value in line_numbers]
    except (TypeError, ValueError):
        return False
    for number in numbers:
        for region in regions:
            if region["start_line"] <= number <= region["end_line"]:
                return True
    return False


def _region_intersects_regions(region: dict[str, Any], other_regions: list[dict[str, Any]]) -> bool:
    start = _as_int(region.get("start_line"))
    end = _as_int(region.get("end_line"))
    if not start or not end or end < start:
        return False
    for other in other_regions:
        other_start = _as_int(other.get("start_line"))
        other_end = _as_int(other.get("end_line"))
        if not other_start or not other_end or other_end < other_start:
            continue
        if start <= other_end and other_start <= end:
            return True
    return False


def _selected_region_text(source_text: str, regions: list[dict[str, Any]]) -> str:
    lines = source_text.splitlines()
    chunks = []
    for region in regions:
        chunks.extend(lines[region["start_line"] - 1 : region["end_line"]])
    return "\n".join(chunks)


def _routine_role_items(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("routine_roles", {})
    if isinstance(raw, dict):
        return {str(name).upper(): _dict(row) for name, row in raw.items()}
    if isinstance(raw, list):
        return {str(row.get("routine_name", "")).upper(): dict(row) for row in raw if isinstance(row, dict)}
    return {}


def _variable_role_items(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("variable_roles", {})
    if isinstance(raw, dict):
        return {str(name).upper(): _dict(row) for name, row in raw.items()}
    if isinstance(raw, list):
        return {str(row.get("variable name", "")).upper(): dict(row) for row in raw if isinstance(row, dict)}
    return {}


def _region_classification_items(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("region_classifications", {})
    if isinstance(raw, dict):
        return {str(name): _dict(row) for name, row in raw.items()}
    if isinstance(raw, list):
        return {str(row.get("region id", "")): dict(row) for row in raw if isinstance(row, dict)}
    return {}


def _semantic_checks(
    *,
    transformed_source: str,
    form: str,
    module_name: str,
    type_name: str,
    roles: dict[str, set[str]],
    regions: dict[str, list[dict[str, Any]]],
    mappings: dict[str, str],
    tangent_context: TangentRegionContext,
    extraction_insertion_region_id: str,
    ddsdde_output_method: str = "GETIM(STRESS_OTI(i), j)",
    config: dict[str, Any],
) -> tuple[dict[str, bool], list[str]]:
    warnings: list[str] = []
    # There is no needle here for the seeded shadow. Testing that the text
    # "DSTRAN_OTI" appears somewhere passed on the word occurring in a comment
    # and failed on a routine that has no strain increment to shadow; the
    # check that replaced it asks, below, whether any derivative direction is
    # actually injected -- which is the thing the needle stood in for.
    checks = {
        f"USE {module_name}": f"transformed file does not contain USE {module_name}",
        f"TYPE({type_name})": f"transformed file does not contain TYPE({type_name})",
        "STRESS_OTI": "transformed file does not contain STRESS_OTI",
        "SUBROUTINE UMAT": "transformed file does not contain SUBROUTINE UMAT",
    }
    upper_source = transformed_source.upper()
    for needle, message in checks.items():
        if needle.upper() not in upper_source:
            warnings.append(message)
    active_lines = _active_lines_with_numbers(transformed_source)
    selected_active_lines = _active_lines_in_selected_subroutine(active_lines, _selected_umat(config) if config else "UMAT")
    dstran = mappings.get("dstran", "DSTRAN")
    stress = mappings.get("stress", "STRESS")
    ddsdde = mappings.get("ddsdde", "DDSDDE")
    dstran_seed_lines = [line_number for line_number, line in selected_active_lines if _is_dstran_seed_line(line, dstran)]
    stress_expression_lines = _stress_expression_lines(selected_active_lines, roles, mappings)
    first_stress_expression_line = stress_expression_lines[0][0] if stress_expression_lines else 0
    last_stress_expression_line = stress_expression_lines[-1][0] if stress_expression_lines else 0
    last_stress_update_line = _last_line_matching(stress_expression_lines, lambda line: _is_stress_oti_update_line(line, stress))
    if not last_stress_update_line:
        last_stress_update_line = last_stress_expression_line
    ddsdde_output_line = _last_ddsdde_output_line(
        selected_active_lines,
        stress=stress,
        ddsdde=ddsdde,
    )
    # Whichever variable was actually seeded. A finite-strain transform seeds
    # the deformation gradient, not the strain increment, and looking only for
    # DSTRAN_OTI found no consumers at all there -- which turned "nothing
    # consumes the seed", the condition these checks exist to catch, into the
    # verdict for a source that was seeding correctly all along.
    dfgrd1_seed_lines = [number for number, line in selected_active_lines
                         if _is_finite_dfgrd1_seed_line(line)]
    seed_names = {dstran} | ({"DFGRD1"} if dfgrd1_seed_lines else set())
    seed_lines = sorted(set(dstran_seed_lines) | set(dfgrd1_seed_lines))
    # The same correction, applied to the initialisation these checks pair
    # with the seed. A material routine reached through an Abaqus wrapper has
    # no DSTRAN at all -- thirteen discovered sources take the deformation
    # gradient instead -- so asking for DSTRAN_OTI's initialisation asked
    # about a variable the routine does not have, and its absence was reported
    # as an ordering failure. The keys keep their names because published
    # reports carry them; what they ask is the ordering of the variable that
    # was actually seeded. The last initialisation must precede the first
    # injection, so this takes the maximum, never the minimum: a check that
    # would pass on the earliest of several initialisations is weaker than the
    # one it replaces, and this has to be at least as strong.
    seeded_initialization_lines = [
        _first_line_matching(selected_active_lines,
                             lambda line, variable=name: _is_shadow_initialization_line(line, variable))
        for name in sorted(seed_names)
        if (dstran_seed_lines if name == dstran else dfgrd1_seed_lines)
    ]
    seed_init_line = (max(seeded_initialization_lines)
                      if seeded_initialization_lines and all(seeded_initialization_lines) else 0)
    # Replaces a needle test for the literal text "DSTRAN_OTI" anywhere in the
    # file. That passed on the word appearing in a comment and failed on a
    # routine that has no strain increment to shadow; this asks for a seed
    # injection, which is the thing the needle was standing in for.
    if not seed_lines:
        warnings.append(
            f"transformed file injects no derivative direction: neither "
            f"{dstran}_OTI nor DFGRD1_OTI is seeded")
    seed_consuming_lines = _seed_consuming_stress_lines(stress_expression_lines, seed_names)
    real_stress_extraction_line = _first_line_matching(selected_active_lines, lambda line: _is_real_stress_extraction_line(line, stress))
    helper_region_ids = {str(region.get("region_id", "")) for region in tangent_context.helper_regions}
    semantic_checks = {
        "dstran_initialization_before_seed": bool(seed_init_line and seed_lines and seed_init_line < min(seed_lines)),
        # The ordering is asked of every stress expression, not only of the
        # ones that name the seed. Restricting it to consumers is strictly
        # weaker -- consumers are a subset -- and it would pass a promoted
        # variable fed from the un-renamed argument before the seed and read
        # downstream afterwards. The seed set is the one that was actually
        # seeded, which is what the finite-strain fix bought; the consumption
        # check below is an addition beside it, not a replacement for it.
        "dstran_initialization_before_stress_use": bool(
            seed_init_line and first_stress_expression_line
            and seed_init_line < first_stress_expression_line),
        "stress_path_consumes_the_seed": bool(seed_consuming_lines),
        "dstran_seed_before_stress_update": bool(
            seed_lines and first_stress_expression_line
            and max(seed_lines) < first_stress_expression_line),
        "dstran_seed_before_transformed_stress_update": bool(seed_lines and last_stress_update_line and max(seed_lines) < last_stress_update_line),
        "stress_oti_update_before_real_stress_extraction": bool(last_stress_update_line and real_stress_extraction_line and last_stress_update_line < real_stress_extraction_line),
        "ddsdde_output_present": bool(ddsdde_output_line),
        "real_stress_extraction_before_ddsdde_extraction": bool(real_stress_extraction_line and ddsdde_output_line and real_stress_extraction_line < ddsdde_output_line),
        "stress_oti_update_before_ddsdde_extraction": bool(last_stress_update_line and ddsdde_output_line and last_stress_update_line < ddsdde_output_line),
        "ddsdde_extraction_after_selected_stress_regions": bool(last_stress_expression_line and ddsdde_output_line and last_stress_expression_line < ddsdde_output_line),
        "ddsdde_extraction_after_final_selected_stress_update": bool(last_stress_update_line and ddsdde_output_line and last_stress_update_line < ddsdde_output_line),
        "old_ddsdde_assignments_disabled": _old_ddsdde_assignments_disabled(
            transformed_source,
            config,
            last_stress_update_line=last_stress_update_line,
        ),
        "no_extraction_in_tangent_helper_region": extraction_insertion_region_id not in helper_region_ids,
        "fixed_form_line_lengths_ok": _fixed_form_line_lengths_ok(transformed_source, form),
        "integer_literals_normalized_in_oti_expressions": _integer_literals_normalized_in_oti_expressions(transformed_source, form),
        "promoted_dfgrd_variables_initialized_before_use": _promoted_dfgrd_variables_initialized_before_use(selected_active_lines, roles),
        "finite_strain_path_uses_oti_versions": _finite_strain_path_uses_oti_versions(selected_active_lines, roles),
    }
    validation_settings = _dict(config.get("validation_settings"))
    compare_outputs_raw = validation_settings.get("compare_outputs")
    compare_outputs = {
        str(value).upper()
        for value in (compare_outputs_raw if isinstance(compare_outputs_raw, (list, tuple, set)) else [])
        if str(value).strip()
    }
    requires_ddsdde_validation = not compare_outputs or "DDSDDE" in compare_outputs
    for name, passed in semantic_checks.items():
        if not passed:
            if name == "finite_strain_path_uses_oti_versions" and not requires_ddsdde_validation:
                continue
            warnings.append(f"Semantic check failed: {name}.")
    return semantic_checks, warnings


def _is_ddsdde_output_line(line: str, *, stress: str, ddsdde: str) -> bool:
    if re.search(
        rf"\b{re.escape(ddsdde)}\s*\(\s*OTI_I\s*,\s*OTI_J\s*\)\s*=\s*GETIM\s*\(\s*{re.escape(stress)}_OTI\s*\(\s*OTI_I\s*\)",
        line,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            rf"\b{re.escape(ddsdde)}\s*\(\s*\d+\s*,\s*\d+\s*\)\s*=\s*REAL\s*\(",
            line,
            flags=re.IGNORECASE,
        )
    )


def _last_ddsdde_output_line(lines: list[tuple[int, str]], *, stress: str, ddsdde: str) -> int:
    last_match = 0
    for index, (line_number, line) in enumerate(lines):
        if _is_ddsdde_output_line(line, stress=stress, ddsdde=ddsdde):
            last_match = line_number
            continue
        if not re.search(
            rf"\b{re.escape(ddsdde)}\s*\(\s*OTI_I\s*,\s*OTI_J\s*\)\s*=\s*$",
            line,
            flags=re.IGNORECASE,
        ):
            continue
        if index + 1 >= len(lines):
            continue
        next_line = lines[index + 1][1]
        if re.search(
            rf"\bGETIM\s*\(\s*{re.escape(stress)}_OTI\s*\(\s*OTI_I\s*\)\s*,\s*OTI_J\s*\)",
            next_line,
            flags=re.IGNORECASE,
        ):
            last_match = line_number
    return last_match


def _active_lines_with_numbers(source: str) -> list[tuple[int, str]]:
    return [(index, line) for index, line in enumerate(source.splitlines(), start=1) if not _is_commented(line)]


def _active_lines_in_selected_subroutine(active_lines: list[tuple[int, str]], selected_umat: str) -> list[tuple[int, str]]:
    selected = selected_umat.upper() or "UMAT"
    result: list[tuple[int, str]] = []
    in_selected = False
    for line_number, line in active_lines:
        if not in_selected and re.match(rf"^\s*SUBROUTINE\s+{re.escape(selected)}\b", line, flags=re.IGNORECASE):
            in_selected = True
        if not in_selected:
            continue
        result.append((line_number, line))
        if _is_subroutine_end_line(line):
            break
    return result or active_lines


def _is_subroutine_end_line(line: str) -> bool:
    return bool(re.match(r"^\s*END\s*(?:SUBROUTINE(?:\s+\w+)?\s*)?$", line, flags=re.IGNORECASE))


def _first_line_matching(lines: list[tuple[int, str]], predicate) -> int:
    for line_number, line in lines:
        if predicate(line):
            return line_number
    return 0


def _last_line_matching(lines: list[tuple[int, str]], predicate) -> int:
    for line_number, line in reversed(lines):
        if predicate(line):
            return line_number
    return 0


def _is_dstran_initialization_line(line: str, dstran: str) -> bool:
    return bool(re.search(rf"\b{re.escape(dstran)}_OTI\s*\(\s*OTI_I\s*\)\s*=\s*{re.escape(dstran)}\s*\(\s*OTI_I\s*\)", line, flags=re.IGNORECASE))


def _seed_consuming_stress_lines(
    stress_expression_lines: list[tuple[int, str]], seed_names: set[str],
) -> list[int]:
    """Stress expressions that actually read the seeded variable.

    The invariant worth checking is that the seed is established before
    everything that consumes it, and that something does consume it. Comparing
    against the first line touching *any* promoted variable checks neither: a
    source that builds its elastic stiffness out of material constants before
    it looks at the strain increment trips it while being perfectly correct,
    and a transform that seeded a variable nothing ever reads -- the failure
    that yields a silently zero derivative -- sails through it.

    After transformation the consumer is the OTI-typed name, not the original
    argument: the crystal-plasticity source mentions DSTRAN three times, all
    of them the signature, the declaration and the initialisation, and does
    its work on DSTRAN_OTI.
    """
    if not seed_names:
        return []
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(name) for name in sorted(seed_names))
        + r")_OTI\b", re.IGNORECASE)
    return [number for number, line in stress_expression_lines
            if pattern.search(line)]



def _is_dstran_seed_line(line: str, dstran: str) -> bool:
    return parse_dstran_seed_line(line, dstran) is not None


def _is_finite_dfgrd1_seed_line(line: str) -> bool:
    return parse_finite_dfgrd1_seed_line(line) is not None


def _is_do_line(line: str) -> bool:
    return not _is_commented(line) and bool(re.match(r"^\s*DO(?:\s+\d+)?\b", line, flags=re.IGNORECASE))


def _is_end_do_line(line: str) -> bool:
    return not _is_commented(line) and bool(re.match(r"^\s*END\s*DO\b", line, flags=re.IGNORECASE))


def _is_end_if_line(line: str) -> bool:
    return not _is_commented(line) and bool(re.match(r"^\s*END\s*IF\b", line, flags=re.IGNORECASE))


def _is_if_then_line(line: str) -> bool:
    return not _is_commented(line) and bool(re.match(r"^\s*IF\s*\(.+\)\s*THEN\b", line, flags=re.IGNORECASE))


def _is_stress_oti_update_line(line: str, stress: str) -> bool:
    if re.search(rf"^\s*CALL\s+\w+\s*\([^)]*\b{re.escape(stress)}_OTI\b", line, flags=re.IGNORECASE):
        return True
    if re.search(rf"\b{re.escape(stress)}_OTI\s*\(\s*OTI_I\s*\)\s*=\s*{re.escape(stress)}\s*\(\s*OTI_I\s*\)", line, flags=re.IGNORECASE):
        return False
    return bool(re.search(rf"\b{re.escape(stress)}_OTI\s*\([^)]*\)\s*=", line, flags=re.IGNORECASE))


def _is_real_stress_extraction_line(line: str, stress: str) -> bool:
    return bool(
        re.search(
            rf"\b{re.escape(stress)}\s*\(\s*OTI_I\s*\)\s*=\s*REAL\s*\(\s*{re.escape(stress)}_OTI\s*\(\s*OTI_I\s*\)\s*\)",
            line,
            flags=re.IGNORECASE,
        )
    )


def _stress_expression_lines(active_lines: list[tuple[int, str]], roles: dict[str, set[str]], mappings: dict[str, str]) -> list[tuple[int, str]]:
    dstran = mappings.get("dstran", "DSTRAN")
    stress = mappings.get("stress", "STRESS")
    result: list[tuple[int, str]] = []
    for line_number, line in active_lines:
        upper = line.upper()
        if "_OTI" not in upper:
            continue
        if "TYPE(" in upper or "GETIM(" in upper or "REAL(" in upper:
            continue
        if "=" not in line and not re.match(r"^\s*CALL\b", line, flags=re.IGNORECASE):
            continue
        if _is_dstran_initialization_line(line, dstran) or _is_dstran_seed_line(line, dstran):
            continue
        if _is_finite_dfgrd1_seed_line(line):
            continue
        if _is_any_shadow_initialization_line(line) or _is_any_shadow_default_line(line):
            continue
        if any(_is_shadow_initialization_line(line, name) for name in roles["seed"] | roles["promote"]):
            continue
        if any(_is_shadow_default_line(line, name) for name in roles["seed"] | roles["promote"]):
            continue
        if re.search(rf"\b{re.escape(stress)}_OTI\s*\(\s*OTI_I\s*\)\s*=\s*{re.escape(stress)}\s*\(\s*OTI_I\s*\)", line, flags=re.IGNORECASE):
            continue
        result.append((line_number, line))
    return result


def _is_any_shadow_initialization_line(line: str) -> bool:
    indexed = re.search(r"\b([A-Za-z_]\w*)_OTI\s*\([^)]*\)\s*=\s*\1\s*\([^)]*\)", line, flags=re.IGNORECASE)
    scalar = re.search(r"\b([A-Za-z_]\w*)_OTI\s*=\s*\1\b", line, flags=re.IGNORECASE)
    return bool(indexed or scalar)


def _is_any_shadow_default_line(line: str) -> bool:
    return bool(re.search(r"\b[A-Za-z_]\w*_OTI(?:\s*\(\s*(?:OTI_HI|OTI_HJ)(?:\s*,\s*(?:OTI_HI|OTI_HJ))*\s*\))?\s*=\s*0\.0D0\b", line, flags=re.IGNORECASE))


def _helper_shadow_sync_lines(
    line: str,
    sync_names: set[str],
    dirty_names: set[str],
    form: str,
    variable_shapes: dict[str, str],
) -> tuple[list[str], set[str]]:
    if not sync_names or not dirty_names:
        return [], set()
    match = re.match(r"^\s*CALL\s+([A-Z_][A-Z0-9_]*)\s*\((.*)\)\s*$", line, flags=re.IGNORECASE)
    if not match:
        return [], set()
    lines: list[str] = []
    synced_names: set[str] = set()
    for argument in _split_call_arguments(match.group(2)):
        name = _base_argument_name(argument)
        if not name or name not in sync_names or name not in dirty_names or name in synced_names:
            continue
        synced_names.add(name)
        lines.extend(_copy_real_shadow_lines(form, name, variable_shapes.get(name, "")))
    return lines, synced_names


def _assigned_shadow_names(line: str, candidate_names: set[str]) -> set[str]:
    if not candidate_names:
        return set()
    match = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*(?:\([^=]*\))?\s*=", line, flags=re.IGNORECASE)
    if not match:
        return set()
    name = match.group(1).upper()
    if name not in candidate_names:
        return set()
    return {name}


def _branch_block_kind(line: str) -> str:
    text = line.strip()
    if not text or text.startswith(("!", "C", "c", "*")):
        return ""
    upper = text.upper()
    # Skip statement labels (fixed form may have leading digits in cols 1-5; line stripped already loses them, but handle inline label)
    upper = re.sub(r"^\d+\s+", "", upper)
    if re.match(r"^END\s*IF\b", upper):
        return "end_if"
    if re.match(r"^ELSE\s*IF\b.*\bTHEN\s*$", upper):
        return "else_if"
    if re.match(r"^ELSE\s*$", upper):
        return "else"
    if re.match(r"^IF\b.*\bTHEN\s*$", upper):
        return "if_then"
    return ""


def _pure_seed_tangent_bridge_lines(
    *,
    source_lines: list[str],
    form: str,
    config: dict[str, Any],
    stress_regions: list[dict[str, Any]],
    shared_setup_regions: list[dict[str, Any]],
    tangent_output_regions: list[dict[str, Any]],
    mappings: dict[str, str],
    replacement_names: dict[str, str],
    type_name: str,
    ntens: int,
    seed_dfgrd1_active: bool = False,
) -> list[str]:
    if ntens <= 0 or not tangent_output_regions:
        return []
    # When the finite-strain DFGRD1 seed is active, every DSTRAN direction is
    # routed through the executable stress path via DFGRD1 (see
    # _finite_dfgrd1_seed_lines), so no direction is "omitted". Emitting the
    # pure-seed fallback here would double-count those directions in DDSDDE
    # (e.g. doubling the shear-diagonal tangent).
    if seed_dfgrd1_active:
        return []
    dstran = mappings.get("dstran", "DSTRAN")
    stress = mappings.get("stress", "STRESS")
    used_directions = _explicit_dstran_used_directions(source_lines, stress_regions, dstran)
    if used_directions is None:
        return []
    missing_directions = {direction for direction in range(1, ntens + 1) if direction not in used_directions}
    if not missing_directions:
        return []

    bridge_lines: list[str] = []
    for row in _dict(config.get("analysis")).get("assignments_to_ddsdde", []) or []:
        if not isinstance(row, dict):
            continue
        if _line_numbers_intersect(row.get("line_numbers", []), shared_setup_regions):
            continue
        if not _line_numbers_intersect(row.get("line_numbers", []), tangent_output_regions):
            continue
        match = re.match(
            r"^\s*DDSDDE\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*(.+?)\s*$",
            str(row.get("text", "")),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        stress_index = int(match.group(1))
        direction = int(match.group(2))
        if direction not in missing_directions:
            continue
        rhs = match.group(3).strip()
        bridge_lines.append(
            _transform_executable_line(
                _stmt(form, f"{stress}_OTI({stress_index}) = {stress}_OTI({stress_index}) + ({rhs})*{_seed_basis_name(direction)}"),
                replacement_names,
                type_name,
                set(),
            )
        )
    if not bridge_lines:
        return []
    return [_comment_line(form, "OTIS pure-seed tangent bridge for DSTRAN directions omitted on the executable stress path"), *bridge_lines]


def _explicit_dstran_used_directions(
    source_lines: list[str],
    stress_regions: list[dict[str, Any]],
    dstran: str,
) -> set[int] | None:
    used: set[int] = set()
    pattern = re.compile(rf"\b{re.escape(dstran)}\s*\(\s*([^)]*?)\s*\)", flags=re.IGNORECASE)
    bare_token_pattern = re.compile(rf"\b{re.escape(dstran)}\b(?!\s*\()", flags=re.IGNORECASE)
    for region in stress_regions:
        start = _as_int(region.get("start_line"))
        end = _as_int(region.get("end_line"))
        if not start or not end or end < start:
            continue
        for line in source_lines[start - 1 : end]:
            if _is_commented(line):
                continue
            if bare_token_pattern.search(line):
                return None
            for match in pattern.finditer(line):
                index_expr = match.group(1).strip()
                if not index_expr:
                    continue
                if re.fullmatch(r"\d+", index_expr):
                    used.add(int(index_expr))
                    continue
                return None
    return used


def _is_shadow_initialization_line(line: str, name: str) -> bool:
    indexed = re.search(rf"\b{re.escape(name)}_OTI\s*\([^)]*\)\s*=\s*{re.escape(name)}\s*\([^)]*\)", line, flags=re.IGNORECASE)
    scalar = re.search(rf"\b{re.escape(name)}_OTI\s*=\s*{re.escape(name)}\b", line, flags=re.IGNORECASE)
    return bool(indexed or scalar)


def _is_shadow_default_line(line: str, name: str) -> bool:
    return bool(
        re.search(
            rf"\b{re.escape(name)}_OTI(?:\s*\(\s*(?:OTI_HI|OTI_HJ)(?:\s*,\s*(?:OTI_HI|OTI_HJ))*\s*\))?\s*=\s*0\.0D0\b",
            line,
            flags=re.IGNORECASE,
        )
    )


def _old_ddsdde_assignments_disabled(
    transformed_source: str,
    config: dict[str, Any],
    *,
    last_stress_update_line: int = 0,
) -> bool:
    assignments = _dict(config.get("analysis")).get("assignments_to_ddsdde", []) if config else []
    regions = _regions_from_config(config) if config else {}
    old_tangent_regions = regions.get("old_tangent", [])
    shared_setup_regions = regions.get("shared_setup", [])
    expected_disabled = {
        _canonical_fortran_text(str(row.get("text", "")))
        for row in assignments
        if isinstance(row, dict)
        and _line_numbers_intersect(row.get("line_numbers", []), old_tangent_regions)
        and not _line_numbers_intersect(row.get("line_numbers", []), shared_setup_regions)
    }
    if not expected_disabled:
        return True
    active = [
        (line_number, _canonical_fortran_text(line))
        for line_number, line in _active_lines_with_numbers(transformed_source)
    ]
    if last_stress_update_line > 0:
        active = [
            (line_number, text)
            for line_number, text in active
            if line_number >= last_stress_update_line
        ]
    # No dominance escape hatch. An earlier version accepted a surviving
    # assignment when the OTI extraction appeared to dominate every RETURN,
    # but that analysis only recognised a statement-initial RETURN: a one-line
    # "IF (KSTEP.EQ.0) RETURN", a GO TO, a computed GO TO, an ENTRY, an
    # arithmetic IF or a SELECT CASE all slipped past it, and it answered
    # "dominates" while the old assignment was live on that path. A guard that
    # fails open is worse than one that fails noisily, and the only source it
    # bought cannot execute here anyway. Real dominance would have to fail
    # closed on every form it does not model.
    return not any(text and text in expected_disabled for _, text in active)


def _canonical_fortran_text(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def _fixed_form_line_lengths_ok(source: str, form: str) -> bool:
    if form != "fixed":
        return True
    return all(len(line.rstrip("\n")) <= 72 for _, line in _active_lines_with_numbers(source))


#: A Fortran real literal, exponent included. Deliberately does not match a
#: bare integer: the check below exists to find those, and blanking them would
#: blind it. The exponent form is the point -- "3.8019047483079793e-6" ends in
#: digits that are part of the literal, not an integer literal of their own.
_REAL_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:\d+\.\d*(?:[dDeEqQ][-+]?\d+)?"
    r"|\.\d+(?:[dDeEqQ][-+]?\d+)?"
    r"|\d+[dDeEqQ][-+]?\d+)"
)


def _statement_without_inline_comment(segment: str) -> str:
    """The statement text with any trailing ``!`` comment removed.

    Quoted text is respected, so a ``!`` inside a CHARACTER literal is not
    read as a comment marker.
    """
    quote = ""
    for index, character in enumerate(segment):
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character == "!":
            return segment[:index]
    return segment


def _logical_statements_with_numbers(source: str, form: str) -> list[tuple[int, str]]:
    """Active statements with fixed-form continuations joined, comments dropped.

    A real literal may straddle a fixed-form continuation -- gfortran reads
    ``2.7026494317808357e-`` and ``6*Sin(...)`` on the next line as one number
    -- and a reader that looks at one physical line at a time sees the tail as
    a bare integer multiplying something. Joining before scanning is what makes
    the statement the compiler sees the statement the check sees. No space is
    inserted at the join, because fixed form does not insert one.
    """
    statements: list[tuple[int, str]] = []
    for line_number, line in _active_lines_with_numbers(source):
        segment = _statement_without_inline_comment(_statement_line_segment(line, form))
        if form == "fixed" and statements and _is_continuation_line(line, form):
            first_line, text = statements[-1]
            statements[-1] = (first_line, text + segment)
            continue
        statements.append((line_number, segment))
    return statements


def _integer_literals_normalized_in_oti_expressions(source: str, form: str = "fixed") -> bool:
    """No bare integer literal multiplies or divides an OTI expression.

    The OTI type has no operator against a default INTEGER, so ``2*X_OTI``
    does not compile and this catches it before the compiler does. It reads
    the joined statement with real literals blanked out first: without that,
    ``3.8019047483079793e-6*Sin(Pi*X_OTI)`` reported an unnormalised integer
    -- the exponent's digits -- in a file that compiles cleanly, and the
    source was refused for a defect that was not in it.
    """
    for _, statement in _logical_statements_with_numbers(source, form):
        if "_OTI" not in statement.upper():
            continue
        scanned = _REAL_LITERAL_RE.sub(lambda match: " " * len(match.group(0)), statement)
        if re.search(r"(?<![A-Za-z0-9_.)])\d+(?![A-Za-z0-9_.])\s*[*\/]", scanned):
            return False
        if re.search(r"[*\/]\s*\d+(?![A-Za-z0-9_.])", scanned):
            return False
    return True


def _promoted_dfgrd_variables_initialized_before_use(active_lines: list[tuple[int, str]], roles: dict[str, set[str]]) -> bool:
    # Seeded counts as carried. A deformation gradient that is the seed rather
    # than a promotion has exactly the same shadow to establish before its
    # first use, and reading only "promote" skipped the check on the sources
    # where it is the only kinematic input there is.
    for name in sorted({"DFGRD0", "DFGRD1"} & (roles["seed"] | roles["promote"])):
        init_line = _first_line_matching(active_lines, lambda line, variable=name: _is_shadow_initialization_line(line, variable))
        use_line = _first_line_matching(
            active_lines,
            lambda line, variable=name: f"{variable}_OTI" in line.upper()
            and _line_is_transform_executable(line)
            and not _is_shadow_default_line(line, variable)
            and not _is_shadow_initialization_line(line, variable),
        )
        if not init_line or not use_line or init_line >= use_line:
            return False
    return True


def _finite_strain_path_uses_oti_versions(active_lines: list[tuple[int, str]], roles: dict[str, set[str]]) -> bool:
    promoted_kinematics = _finite_kinematic_name_set() & (roles["seed"] | roles["promote"])
    if not promoted_kinematics:
        return True
    for _, line in active_lines:
        if not _line_is_transform_executable(line):
            continue
        for name in promoted_kinematics:
            if _is_allowed_real_shadow_source(line, name):
                continue
            if re.search(rf"\b{re.escape(name)}\s*\(", line, flags=re.IGNORECASE):
                return False
    return True


def _line_is_non_executable_declaration(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^(SUBROUTINE|INCLUDE|PARAMETER|DIMENSION|CHARACTER|INTEGER|REAL|DOUBLE\s+PRECISION|TYPE\b|USE\b)", stripped, flags=re.IGNORECASE))


def _line_is_transform_executable(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _line_is_non_executable_declaration(line):
        return False
    return "=" in stripped or bool(re.match(r"^CALL\b", stripped, flags=re.IGNORECASE))


def _is_allowed_real_shadow_source(line: str, name: str) -> bool:
    return bool(re.search(rf"\b{re.escape(name)}_OTI\s*\([^)]*\)\s*=\s*{re.escape(name)}\s*\([^)]*\)", line, flags=re.IGNORECASE))


def _active_region_lines(source: str, start_line: int, end_line: int) -> list[str]:
    lines = source.splitlines()[start_line - 1 : end_line]
    return [line for line in lines if not _is_commented(line)]


def _is_commented(line: str) -> bool:
    stripped = line.lstrip()
    return not stripped or stripped.startswith("!") or (line and line[0] in {"C", "c", "*"})


def _parse_extra_jacobian_contracts(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw = config.get("extra_jacobian_contracts")
    if not isinstance(raw, list):
        return []
    parsed: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        seed = _dict(entry.get("seed"))
        output = _dict(entry.get("output"))
        loop = _dict(entry.get("loop"))
        extraction = _dict(entry.get("extraction"))
        internal_use = _dict(entry.get("internal_use"))
        post_loop_restore = _dict(entry.get("post_loop_restore"))
        debug_dump = _dict(entry.get("debug_dump"))
        directions = int(seed.get("directions") or 1)
        seed_shape = str(seed.get("shape") or "scalar")
        normalized = {
            "id": str(entry.get("id") or f"jacobian_request_{index+1}"),
            "selected_umat": str(entry.get("selected_umat") or _selected_umat(config)),
            "description": str(entry.get("description") or ""),
            "seed_variable": str(seed.get("variable") or "").upper(),
            "seed_shape": seed_shape,
            "seed_directions": directions,
            "seed_components": _seed_component_specs(seed_shape, directions, seed.get("components")),
            "seed_operating_point": str(seed.get("operating_point_expression") or seed.get("variable") or ""),
            "output_variable": str(output.get("variable") or "").upper(),
            "output_shape": str(output.get("shape") or "scalar"),
            "loop_top_line": _as_int(loop.get("loop_top_line")),
            "reseed_after_line": _as_int(loop.get("reseed_after_line")) or _as_int(loop.get("loop_top_line")),
            "loop_exit_label": str(loop.get("loop_exit_label") or ""),
            "loop_exit_line": _as_int(loop.get("loop_exit_line")),
            "extract_after_line": _as_int(extraction.get("extract_after_line")),
            "extract_kind": str(extraction.get("extract_kind") or "diagonal_scalar"),
            "replace_variable": str(internal_use.get("replace_variable") or "").upper(),
            "replace_lines": [_as_int(value) for value in (internal_use.get("replace_lines") or []) if _as_int(value)],
            "post_loop_restore_enabled": bool(post_loop_restore.get("enabled", False)),
            "post_loop_restore_method": str(post_loop_restore.get("method") or "implicit_function_step"),
            "post_loop_restore_after_line": _as_int(post_loop_restore.get("after_line")),
            "post_loop_residual_variable": str(post_loop_restore.get("residual_variable") or output.get("variable") or "").upper(),
            "post_loop_jacobian_variable": str(post_loop_restore.get("jacobian_variable") or internal_use.get("replace_variable") or "").upper(),
            "debug_dump_enabled": bool(debug_dump.get("enabled", False)),
            "debug_dump_fields": [str(field) for field in (debug_dump.get("fields") or [])],
            # Raw Fortran statements spliced in immediately AFTER the loop-top
            # reseed of the seed variable. Used to propagate the freshly seeded
            # value through an update (e.g. a hardening recompute) so that
            # variables read by the residual carry the seed's derivative even
            # when the natural code order updates them only after the residual.
            "reseed_prelude": [str(line) for line in (loop.get("reseed_prelude") or []) if str(line).strip()],
            # Mid-loop preludes: raw Fortran spliced after a specific line (e.g.
            # after FBAR is computed) so a residual that reads a frozen
            # intermediate computed later in the natural code order can instead
            # read a seed-carrying recompute. Each entry: {after_line, statements}.
            "loop_preludes": [
                {
                    "after_line": int(block.get("after_line") or 0),
                    "statements": [str(line) for line in (block.get("statements") or []) if str(line).strip()],
                }
                for block in (loop.get("preludes") or [])
                if isinstance(block, dict) and int(block.get("after_line") or 0) > 0 and (block.get("statements") or [])
            ],
        }
        post_loop_extractions = _normalize_auxiliary_extractions(entry.get("post_loop_extractions") or [], default_kind="scalar_from_scalar")
        additional_extractions = _normalize_auxiliary_extractions(entry.get("additional_extractions") or [])
        normalized["post_loop_extractions"] = post_loop_extractions
        normalized["additional_extractions"] = [*additional_extractions, *post_loop_extractions]
        parsed.append(normalized)
    return parsed


def _seed_component_specs(seed_shape: str, directions: int, raw_components: Any) -> list[list[int]]:
    components = _normalize_index_lists(raw_components)
    if components:
        return components[: max(directions, 0)]
    if directions <= 0:
        return []
    if seed_shape.lower() == "scalar":
        return [[]]
    return [[index] for index in range(1, directions + 1)]


def _helper_output_copies(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw = config.get("helper_output_copies")
    if not isinstance(raw, list):
        return {}
    mapping: dict[str, list[dict[str, Any]]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        helper_name = str(entry.get("helper_name") or "").upper()
        target_argument = str(entry.get("target_argument") or "").upper()
        source_local = str(entry.get("source_local") or "").upper()
        components = _normalize_extraction_components(entry.get("components"))
        if not (helper_name and target_argument and source_local and components):
            continue
        mapping.setdefault(helper_name, []).append(
            {
                "target_argument": target_argument,
                "source_local": source_local,
                "components": components,
            }
        )
    return mapping


def _helper_output_surfaces(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw = config.get("helper_output_surfaces")
    if not isinstance(raw, list):
        return {}
    mapping: dict[str, list[dict[str, Any]]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        helper_name = str(entry.get("helper_name") or "").upper()
        caller_variable = str(entry.get("caller_variable") or "").upper()
        source_local = str(entry.get("source_local") or "").upper()
        declared_shape = str(entry.get("declared_shape") or entry.get("shape") or "").strip()
        components = _normalize_extraction_components(entry.get("components"))
        if not components:
            components = _default_component_specs_for_shape(declared_shape)
        if not (helper_name and caller_variable and source_local and declared_shape and components):
            continue
        mapping.setdefault(helper_name, []).append(
            {
                "caller_variable": caller_variable,
                "source_local": source_local,
                "declared_shape": declared_shape,
                "components": components,
            }
        )
    return mapping


def _default_component_specs_for_shape(shape: str) -> list[dict[str, Any]]:
    dims = [_as_int(value) for value in _shape_dimensions(shape)]
    if not dims:
        return [{"target_indices": [], "output_indices": [], "seed_direction_offset": 0}]
    if any(value <= 0 for value in dims):
        return []
    if len(dims) == 1:
        return [
            {"target_indices": [index], "output_indices": [index], "seed_direction_offset": 0}
            for index in range(1, dims[0] + 1)
        ]
    if len(dims) == 2:
        return [
            {"target_indices": [row, column], "output_indices": [row, column], "seed_direction_offset": 0}
            for row in range(1, dims[0] + 1)
            for column in range(1, dims[1] + 1)
        ]
    return []


def _synthetic_real_surface_variables(config: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for specs in _helper_output_surfaces(config).values():
        for spec in specs:
            name = str(spec.get("caller_variable") or "").upper()
            shape = str(spec.get("declared_shape") or "").strip()
            if name and shape:
                result[name] = shape
    return result


def _synthetic_real_jacobian_targets(config: dict[str, Any]) -> dict[str, str]:
    """Real arrays that receive extracted constitutive-Jacobian values.

    Targets named in a contract's ``additional_extractions`` (e.g. G1JAC) are
    new variables that hold REAL extracted derivatives (like DDSDDE), so they
    must be declared. The Fortran extent is inferred from the component
    target_indices.
    """
    result: dict[str, str] = {}
    for contract in _parse_extra_jacobian_contracts(config):
        for extraction in contract.get("additional_extractions") or []:
            name = str(extraction.get("target_variable") or "").upper()
            if not name:
                continue
            shape = _indexed_dimension_shape(extraction.get("components") or [], "target_indices")
            if shape and name not in result:
                result[name] = shape
    return result


def _indexed_dimension_shape(components: list[dict[str, Any]], index_key: str) -> str:
    """Infer a Fortran dimension string (e.g. "4,4") from component indices."""
    extents: list[int] = []
    for component in components:
        indices = component.get(index_key) or []
        for position, value in enumerate(indices):
            extent = _as_int(value)
            if position >= len(extents):
                extents.append(extent)
            else:
                extents[position] = max(extents[position], extent)
    return ",".join(str(extent) for extent in extents)


def _jacobian_artifact_manifest(config: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    helper_output_copies = _helper_output_copies(config)
    helper_output_surfaces = _helper_output_surfaces(config)
    for contract in _parse_extra_jacobian_contracts(config):
        artifacts.append(
            {
                "id": contract["id"],
                "artifact_class": "contract_output",
                "selected_umat": contract["selected_umat"],
                "description": contract["description"],
                "target_variable": contract["output_variable"],
                "target_shape": contract["output_shape"],
                "source_variable": contract["output_variable"],
                "source_kind": contract["extract_kind"],
                "seed_variable": contract["seed_variable"],
                "seed_shape": contract["seed_shape"],
                "seed_directions": contract["seed_directions"],
                "extract_after_line": contract["extract_after_line"],
                "component_count": len(contract.get("seed_components") or []),
            }
        )
        for index, extraction in enumerate(contract.get("additional_extractions") or [], start=1):
            artifacts.append(
                {
                    "id": f"{contract['id']}::aux::{index}",
                    "artifact_class": "contract_auxiliary_extraction",
                    "parent_contract_id": contract["id"],
                    "selected_umat": contract["selected_umat"],
                    "target_variable": extraction.get("target_variable", ""),
                    "target_shape": _component_shape(extraction.get("components") or [], "target_indices"),
                    "source_variable": extraction.get("from_output_variable", ""),
                    "source_shape": _component_shape(extraction.get("components") or [], "output_indices"),
                    "source_kind": extraction.get("extract_kind", ""),
                    "extract_after_line": extraction.get("after_line", 0),
                    "component_count": len(extraction.get("components") or []),
                }
            )
    for helper_name in sorted(helper_output_copies):
        for index, copy_spec in enumerate(helper_output_copies[helper_name], start=1):
            components = copy_spec.get("components") or []
            artifacts.append(
                {
                    "id": f"{helper_name}::helper_output::{index}",
                    "artifact_class": "helper_output_copy",
                    "helper_name": helper_name,
                    "target_variable": copy_spec.get("target_argument", ""),
                    "target_shape": _component_shape(components, "target_indices"),
                    "source_variable": copy_spec.get("source_local", ""),
                    "source_shape": _component_shape(components, "output_indices"),
                    "source_kind": "helper_local_copy",
                    "component_count": len(components),
                }
            )
    for helper_name in sorted(helper_output_surfaces):
        for index, surface_spec in enumerate(helper_output_surfaces[helper_name], start=1):
            components = surface_spec.get("components") or []
            artifacts.append(
                {
                    "id": f"{helper_name}::helper_surface::{index}",
                    "artifact_class": "helper_output_surface",
                    "helper_name": helper_name,
                    "target_variable": surface_spec.get("caller_variable", ""),
                    "target_shape": _component_shape(components, "target_indices"),
                    "source_variable": surface_spec.get("source_local", ""),
                    "source_shape": _component_shape(components, "output_indices"),
                    "source_kind": "helper_local_surface",
                    "component_count": len(components),
                }
            )
    return artifacts


def _component_shape(components: list[dict[str, Any]], index_key: str) -> str:
    rank = 0
    for component in components:
        rank = max(rank, len(component.get(index_key) or []))
    if rank <= 0:
        return "scalar"
    if rank == 1:
        return "vector"
    if rank == 2:
        return "matrix"
    return f"rank_{rank}"


def _normalize_auxiliary_extractions(raw_entries: Any, *, default_kind: str = "component_map") -> list[dict[str, Any]]:
    if not isinstance(raw_entries, list):
        return []
    parsed: list[dict[str, Any]] = []
    for raw_ext in raw_entries:
        if not isinstance(raw_ext, dict):
            continue
        components = _normalize_extraction_components(raw_ext.get("components"))
        if not components:
            components = [
                {
                    "target_indices": _normalize_index_list(raw_ext.get("target_indices")),
                    "output_indices": _normalize_index_list(raw_ext.get("output_indices")),
                    "seed_direction_offset": _as_int(raw_ext.get("seed_direction_offset")),
                }
            ]
        parsed.append(
            {
                "target_variable": str(raw_ext.get("target_variable") or "").upper(),
                "from_output_variable": str(raw_ext.get("from_output_variable") or "").upper(),
                "after_line": _as_int(raw_ext.get("after_line")),
                "extract_kind": str(raw_ext.get("extract_kind") or default_kind),
                "components": components,
            }
        )
    return parsed


def _normalize_extraction_components(raw_components: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_components, list):
        return []
    components: list[dict[str, Any]] = []
    for raw_component in raw_components:
        if not isinstance(raw_component, dict):
            continue
        components.append(
            {
                "target_indices": _normalize_index_list(raw_component.get("target_indices")),
                "output_indices": _normalize_index_list(raw_component.get("output_indices")),
                "seed_direction_offset": _as_int(raw_component.get("seed_direction_offset")),
            }
        )
    return components


def _normalize_index_lists(raw_indices: Any) -> list[list[int]]:
    if not isinstance(raw_indices, list):
        return []
    return [_normalize_index_list(item) for item in raw_indices if _normalize_index_list(item)]


def _normalize_index_list(raw_indices: Any) -> list[int]:
    if not isinstance(raw_indices, (list, tuple)):
        return []
    result: list[int] = []
    for item in raw_indices:
        index = _as_int(item)
        if index > 0:
            result.append(index)
    return result


def _indexed_name(name: str, indices: list[int]) -> str:
    if not indices:
        return name
    joined = ", ".join(str(index) for index in indices)
    return f"{name}({joined})"


def _extra_jacobian_reseed_lines(form: str, *, seed_var: str, slot_start: int, seed_components: list[list[int]]) -> list[str]:
    lines = [_comment_line(form, f"OTIS extra-Jacobian reseed: {seed_var}_OTI directions starting at {slot_start}")]
    for offset, component in enumerate(seed_components):
        target = _indexed_name(f"{seed_var}_OTI", component)
        lines.append(_stmt(form, f"{target} = REAL({target}) + {_seed_basis_name(slot_start + offset)}"))
    return lines


def _auxiliary_extraction_lines(
    form: str,
    *,
    seed_var: str,
    slot_start: int,
    directions: int,
    target_variable: str,
    from_output_variable: str,
    extract_kind: str,
    components: list[dict[str, Any]],
) -> list[str]:
    if not target_variable or not from_output_variable:
        return []
    kind = extract_kind.lower()
    if kind not in {"scalar_from_scalar", "component_map", "diagonal_scalar", "real_copy_map"}:
        return []
    if not components:
        components = [{"target_indices": [], "output_indices": [], "seed_direction_offset": 0}]
    if kind == "real_copy_map":
        lines = [_comment_line(form, f"OTIS constitutive matrix copy: {target_variable} from REAL({from_output_variable}_OTI)")]
    else:
        lines = [_comment_line(form, f"OTIS constitutive Jacobian extract: {target_variable} from {from_output_variable} w.r.t. {seed_var}")]
    max_offset = max(directions - 1, 0)
    for component in components:
        offset = int(component.get("seed_direction_offset") or 0)
        target_ref = _indexed_name(target_variable, list(component.get("target_indices") or []))
        output_ref = _indexed_name(f"{from_output_variable}_OTI", list(component.get("output_indices") or []))
        if kind == "real_copy_map":
            lines.append(_stmt(form, f"{target_ref} = REAL({output_ref})"))
            continue
        if offset < 0 or offset > max_offset:
            continue
        slot = slot_start + offset
        lines.append(_stmt(form, f"{target_ref} = GETIM({output_ref}, {slot})"))
    return lines


def _directions_required(ntens: int, config: dict[str, Any]) -> dict[str, Any]:
    extras = _parse_extra_jacobian_contracts(config)
    extra_total = sum(int(item.get("seed_directions") or 0) for item in extras)
    total = int(ntens or 0) + extra_total
    slot_assignments: list[dict[str, Any]] = []
    cursor = int(ntens or 0)
    for item in extras:
        directions = int(item.get("seed_directions") or 0)
        start = cursor + 1
        end = cursor + directions
        slot_assignments.append({"id": item["id"], "seed_variable": item["seed_variable"], "directions": directions, "slot_start": start, "slot_end": end})
        cursor = end
    return {
        "ddsdde_directions": int(ntens or 0),
        "extra_directions": extra_total,
        "total_directions": total,
        "slot_assignments": slot_assignments,
    }


def _report_base(
    *,
    config: dict[str, Any],
    selected_umat: str,
    source_file: str,
    ntens: int,
    order: int,
    module_name: str,
    type_name: str,
    roles: dict[str, set[str]],
    regions: dict[str, list[dict[str, Any]]],
    tangent_context: TangentRegionContext,
) -> dict[str, Any]:
    analysis = _dict(config.get("analysis"))
    return {
        "source_file": source_file,
        "selected_umat": selected_umat,
        "ntens": ntens,
        "oti_order": order,
        "oti_module_name": module_name,
        "oti_type_name": type_name,
        "jacobian_contract": _dict(config.get("jacobian_contract")),
        "extra_jacobian_contracts": _parse_extra_jacobian_contracts(config),
        "jacobian_artifacts": _jacobian_artifact_manifest(config),
        "directions_required": _directions_required(ntens, config),
        "seed_variables": sorted(roles["seed"]),
        "promoted_variables": sorted(roles["promote"]),
        "constant_variables": sorted(roles["constant"]),
        "keep_real_variables": sorted(roles["keep_real"]),
        "branch_conditions": analysis.get("branch_conditions", []),
        "finite_strain": analysis.get("finite_strain", {}),
        "finite_strain_mode": _finite_strain_mode_report(config, roles),
        "helper_policy": _helper_policy_report(config),
        "transformation_anchors": _dict(config.get("transformation_anchors")),
        "anchor_completion": anchor_completion_status(config) if config.get("transformation_anchors") else {"status": "legacy_inferred_regions", "completion_issues": []},
        "plasticity_indicators": analysis.get("plasticity_indicators", {}),
        "statev_accesses": analysis.get("statev_accesses", {}),
        "stress_path_helpers": analysis.get("stress_path_helpers", []),
        "stress_regions_transformed": regions["stress"],
        "old_tangent_regions_replaced": tangent_context.output_regions,
        "tangent_helper_regions_skipped": tangent_context.helper_regions,
        "tangent_output_regions_replaced": tangent_context.output_regions,
        "shared_setup_regions_kept": regions["shared_setup"],
    }


def _helper_policy_report(config: dict[str, Any]) -> dict[str, Any]:
    policy = _dict(config.get("helper_policy"))
    if policy:
        return policy
    calls: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for row in _dict(config.get("analysis")).get("stress_path_helpers", []) or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("callee", "")).upper()
        line_numbers = tuple(_as_int(value) for value in row.get("line_numbers", []) or [] if _as_int(value))
        key = (name, line_numbers)
        if not name or key in seen:
            continue
        seen.add(key)
        calls.append(
            {
                "name": name,
                "classification": "pass_through",
                "reason": "Helper call preserved; promoted arguments rewritten where needed.",
                "blocking": False,
                "line_numbers": list(line_numbers),
                "arguments": list(row.get("arguments", []) or []),
            }
        )
    return {
        "default": "pass_through",
        "helper_calls": calls,
        "notes": "Stress-path helper names are not readiness blockers. Compilation and validation determine whether pass-through is valid.",
    }


def _finite_strain_mode_report(config: dict[str, Any], roles: dict[str, set[str]]) -> dict[str, Any]:
    enabled = _finite_strain_enabled(config)
    categories: dict[str, list[str]] = {}
    for category, names in FINITE_KINEMATIC_CATEGORIES.items():
        selected = sorted(names & roles["promote"])
        if selected:
            categories[category] = selected
    promoted = sorted({name for names in categories.values() for name in names})
    return {
        "enabled": enabled,
        "promoted_kinematic_variables": promoted,
        "categories": categories,
        "reason": "Executable finite-strain kinematics detected on stress path" if enabled else "No executable finite-strain kinematics detected on stress path",
    }


def _finite_kinematic_name_set() -> set[str]:
    result: set[str] = set()
    for names in FINITE_KINEMATIC_CATEGORIES.values():
        result.update(names)
    return result


def _finite_kinematic_names_from_analysis(analysis: dict[str, Any]) -> set[str]:
    summary = _dict(analysis.get("region_summary"))
    names = _upper_set(summary.get("upstream_to_stress", [])) | _upper_set(summary.get("stress_path_variables", []))
    return names & _finite_kinematic_name_set()


def _finite_strain_use_lines(analysis: dict[str, Any]) -> list[int]:
    finite = _dict(analysis.get("finite_strain"))
    lines: list[int] = []
    for key in ("dfgrd0_executable_uses", "dfgrd1_executable_uses"):
        for row in finite.get(key, []) or []:
            if not isinstance(row, dict):
                continue
            for value in row.get("line_numbers", []) or []:
                try:
                    lines.append(int(value))
                except (TypeError, ValueError):
                    continue
    return lines


def _write_report(output_dir: Path, report: dict[str, Any]) -> Path:
    path = output_dir / "transform_report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    # Human-readable companion report. The JSON remains for machine consumption
    # (validation pipeline); the .txt is the report a person actually reads.
    (output_dir / "transform_report.txt").write_text(_render_report_text(report), encoding="utf-8")
    return path


def _render_report_text(report: dict[str, Any]) -> str:
    def region_span(row: dict[str, Any]) -> str:
        start, end = row.get("start_line"), row.get("end_line")
        if start and end:
            return f"lines {start}-{end}"
        return str(row.get("region_id") or row.get("classification") or "").strip()

    lines: list[str] = []
    umat = str(report.get("selected_umat") or "UMAT")
    bar = "=" * 76
    lines.append(bar)
    lines.append(f"  UMAT to OTI/HYPAD TRANSFORMATION REPORT  --  {umat}")
    lines.append(bar)
    lines.append("")
    lines.append(f"Source file       : {report.get('source_file', '')}")
    status = "SUCCESS" if report.get("success") else "FAILED"
    lines.append(f"Transformation    : {status}")
    lines.append(f"Anchor completion : {_dict(report.get('anchor_completion')).get('status', '')}")
    blockers = report.get("blockers") or []
    warnings = report.get("warnings") or []
    if blockers:
        lines.append("Blockers          :")
        lines.extend(f"    - {b}" for b in blockers)
    if warnings:
        lines.append("Warnings          :")
        lines.extend(f"    - {w}" for w in warnings)
    if not blockers and not warnings:
        lines.append("Blockers/Warnings : none")

    lines.append("")
    lines.append("-- OTI configuration " + "-" * 55)
    lines.append(f"ntens = {report.get('ntens')}   order = {report.get('oti_order')}   "
                 f"type = {report.get('oti_type_name', '')}   module = {report.get('oti_module_name', '')}")
    directions = _dict(report.get("directions_required"))
    if directions:
        lines.append(f"OTI directions required: {directions.get('total_directions', directions)}")

    lines.append("")
    lines.append("-- Variable roles " + "-" * 58)
    for label, key in (("Seeded", "seed_variables"), ("Promoted to OTI", "promoted_variables"),
                       ("Kept constant", "constant_variables"), ("Kept real", "keep_real_variables")):
        vals = report.get(key) or []
        preview = ", ".join(str(v) for v in vals[:12]) + (" ..." if len(vals) > 12 else "")
        lines.append(f"{label:<16}: {len(vals):>3}   {preview}")

    lines.append("")
    lines.append("-- Main tangent (DDSDDE) " + "-" * 51)
    jc = _dict(report.get("jacobian_contract"))
    if jc:
        lines.append(f"Contract : {jc.get('contract', '')}")
        lines.append(f"seed = {jc.get('independent_variable', '')}   "
                     f"output = {jc.get('dependent_variable', '')}   target = {jc.get('output_variable', 'DDSDDE')}")
    old_tan = report.get("old_tangent_regions_replaced") or []
    stress_regions = report.get("stress_regions_transformed") or []
    lines.append(f"Old tangent blocks replaced: {len(old_tan)}  ({'; '.join(region_span(r) for r in old_tan)})")
    lines.append(f"Stress-update regions transformed: {len(stress_regions)}")

    extra = report.get("extra_jacobian_contracts") or []
    if extra:
        lines.append("")
        lines.append("-- Internal / constitutive Jacobians " + "-" * 39)
        for c in extra:
            aux_targets = [str(e.get("target_variable") or "") for e in (c.get("additional_extractions") or []) if e.get("target_variable")]
            target = c.get("replace_variable") or c.get("post_loop_jacobian_variable") or ", ".join(aux_targets)
            lines.append(f"  [{c.get('id', '')}] {c.get('description', '')}")
            lines.append(f"      seed = {c.get('seed_variable', '')}  ->  output = {c.get('output_variable', '')}"
                         f"  ->  target = {target}   (dirs={c.get('seed_directions', 1)})")
            loop_top = c.get("loop_top_line")
            if loop_top:
                lines.append(f"      loop top line {loop_top}, extract after line {c.get('extract_after_line', '')}")

    checks = _dict(report.get("semantic_checks"))
    if checks:
        passed = sum(1 for v in checks.values() if v)
        lines.append("")
        lines.append(f"-- Semantic checks ({passed}/{len(checks)} passed) " + "-" * 40)
        for name in sorted(checks):
            lines.append(f"    [{'PASS' if checks[name] else 'FAIL'}] {name}")

    generated = report.get("generated_files") or []
    if generated:
        lines.append("")
        lines.append("-- Generated files " + "-" * 57)
        lines.extend(f"    {Path(str(f)).name}" for f in generated)

    lines.append("")
    return "\n".join(lines) + "\n"


def _transformed_filename(source_file: str) -> str:
    path = Path(source_file)
    suffix = path.suffix or ".f"
    return f"{path.stem}_oti{suffix}"


def _module_use_line(form: str, module_name: str, ntens: int) -> str:
    renamed_seeds = ", ".join(f"{_seed_basis_name(direction)} => E{direction}" for direction in range(1, max(ntens, 0) + 1))
    suffix = f", {renamed_seeds}" if renamed_seeds else ""
    return (_stmt(form, f"USE {module_name}, OTI_MODULE_DP => DP{suffix}")
            + "\n" + _stmt(form, "USE oti_intrinsics"))


def _seed_basis_name(direction: int) -> str:
    return f"OTI_E{direction}"


def _extra_jacobian_splice_maps(
    *,
    config: dict[str, Any],
    ntens: int,
    form: str,
) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    after_inserts: dict[int, list[str]] = {}
    replace_inserts: dict[int, list[str]] = {}
    contracts = _parse_extra_jacobian_contracts(config)
    if not contracts:
        return after_inserts, replace_inserts
    cursor = int(ntens or 0)
    for contract in contracts:
        directions = int(contract.get("seed_directions") or 1)
        slot = cursor + 1
        cursor += directions
        seed_var = str(contract.get("seed_variable") or "").upper()
        output_var = str(contract.get("output_variable") or "").upper()
        replace_var = str(contract.get("replace_variable") or "").upper()
        loop_top = int(contract.get("loop_top_line") or 0)
        extract_after_line = int(contract.get("extract_after_line") or 0)
        seed_components = [list(component) for component in (contract.get("seed_components") or [])]
        if loop_top and seed_var and seed_components:
            reseed = _extra_jacobian_reseed_lines(form, seed_var=seed_var, slot_start=slot, seed_components=seed_components)
            prelude_raw = contract.get("reseed_prelude") or []
            if prelude_raw:
                reseed.append(_comment_line(form, f"OTIS reseed prelude: propagate seeded {seed_var} before residual"))
                for raw_line in prelude_raw:
                    reseed.append(_stmt(form, str(raw_line).strip()))
            after_inserts.setdefault(loop_top, []).extend(reseed)
        for prelude_block in contract.get("loop_preludes") or []:
            after_line = int(prelude_block.get("after_line") or 0)
            statements = prelude_block.get("statements") or []
            if after_line and statements:
                block_lines = [_comment_line(form, f"OTIS mid-loop prelude: recompute seed-carrying intermediates after line {after_line}")]
                for raw_line in statements:
                    block_lines.append(_stmt(form, str(raw_line).strip()))
                after_inserts.setdefault(after_line, []).extend(block_lines)
        if directions == 1 and extract_after_line and replace_var and output_var:
            extract = _auxiliary_extraction_lines(
                form,
                seed_var=seed_var,
                slot_start=slot,
                directions=directions,
                target_variable=f"{replace_var}_OTI",
                from_output_variable=output_var,
                extract_kind=str(contract.get("extract_kind") or "scalar_from_scalar"),
                components=[{"target_indices": [], "output_indices": [], "seed_direction_offset": 0}],
            )
            after_inserts.setdefault(extract_after_line, []).extend(extract)
        if contract.get("replace_lines"):
            for line_no in contract.get("replace_lines") or []:
                if int(line_no) > 0:
                    replace_inserts[int(line_no)] = []
        for ext in contract.get("additional_extractions") or []:
            target = str(ext.get("target_variable") or "").upper()
            from_output = str(ext.get("from_output_variable") or "").upper()
            after_line = int(ext.get("after_line") or 0) or int(contract.get("loop_exit_line") or 0)
            if not (target and from_output and after_line):
                continue
            inserts = _auxiliary_extraction_lines(
                form,
                seed_var=seed_var,
                slot_start=slot,
                directions=directions,
                target_variable=target,
                from_output_variable=from_output,
                extract_kind=str(ext.get("extract_kind") or "component_map"),
                components=list(ext.get("components") or []),
            )
            after_inserts.setdefault(after_line, []).extend(inserts)
    return after_inserts, replace_inserts


def _apply_extra_jacobian_splices(
    *,
    output: list[str],
    original_line_to_output_index: dict[int, int],
    after_inserts: dict[int, list[str]],
    replace_inserts: dict[int, list[str]],
    original_lines: list[str],
    form: str,
) -> None:
    if not after_inserts and not replace_inserts:
        return
    operations: list[tuple[int, str, list[str], int]] = []
    for original_line, new_lines in replace_inserts.items():
        out_index = original_line_to_output_index.get(original_line)
        if out_index is None:
            continue
        operations.append((out_index, "replace", new_lines, original_line))
    for original_line, new_lines in after_inserts.items():
        out_index = original_line_to_output_index.get(original_line)
        if out_index is None:
            continue
        operations.append((out_index, "after", new_lines, original_line))
    operations.sort(key=lambda item: item[0], reverse=True)
    for out_index, kind, new_lines, original_line in operations:
        if kind == "replace":
            original_text = original_lines[original_line - 1] if 1 <= original_line <= len(original_lines) else ""
            replacement = [_comment_old_line(form, original_text), *new_lines]
            output[out_index : out_index + 1] = replacement
        else:
            output[out_index + 1 : out_index + 1] = new_lines


def _stmt(form: str, text: str) -> str:
    return f"      {text}" if form == "fixed" else f"  {text}"


def _comment_line(form: str, text: str) -> str:
    return f"C     {text}" if form == "fixed" else f"! {text}"


def _comment_old_line(form: str, line: str) -> str:
    if _is_commented(line):
        return line
    if form != "fixed":
        return "! OTIS-SKIP: " + line.strip()
    stripped = line.rstrip()
    prefixed = "C     OTIS-SKIP: " + stripped.lstrip()
    if len(prefixed) <= 72:
        return prefixed
    return "C" + stripped[1:] if stripped else "C"


def _is_return_line(line: str) -> bool:
    return bool(re.match(r"^\s*RETURN\b", line, flags=re.IGNORECASE))


def _upper_set(values: Any) -> set[str]:
    return {str(value).upper() for value in values or [] if str(value)}


def _helper_argument_base_names(arguments: Any) -> set[str]:
    names: set[str] = set()
    for argument in arguments or []:
        match = re.match(r"\s*([A-Za-z_]\w*)", str(argument))
        if match:
            names.add(match.group(1).upper())
    return names


def _upper_list(values: Any) -> list[str]:
    return sorted(_upper_set(values))


def _as_int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
