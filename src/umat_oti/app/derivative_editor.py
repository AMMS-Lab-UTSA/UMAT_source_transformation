from __future__ import annotations

import copy
from typing import Any, Iterable

from umat_oti.core.derivative_request import (
    DerivativeRequestError,
    UNIFIED_SCHEMA_VERSION,
    load_project_derivative_requests,
    validate_derivative_requests,
)

DERIVATIVE_KINDS = (
    "material_tangent",
    "local_jacobian",
    "higher_order",
    "parameter_sensitivity",
    "state_sensitivity",
)


def request_editor_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": request.id,
            "kind": request.kind,
            "target": request.target,
            "seed": ", ".join(request.seed),
            "response": request.response,
            "order": request.order,
            "scope": request.scope or "",
        }
        for request in load_project_derivative_requests(config, emit_deprecations=False)
    ]


def mapping_editor_rows(config: dict[str, Any], key: str) -> list[dict[str, Any]]:
    index_key = "props_index" if key == "parameters" else "statev_index"
    return [
        {
            "name": str(entry.get("name", "")),
            index_key: entry.get(index_key),
            **({"value": entry.get("value")} if key == "parameters" else {}),
        }
        for entry in config.get(key, [])
        if isinstance(entry, dict)
    ]


def build_unified_config(
    config: dict[str, Any],
    derivative_rows: Iterable[dict[str, Any]],
    parameter_rows: Iterable[dict[str, Any]],
    state_rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    updated = copy.deepcopy(config)
    derivatives = []
    for row in derivative_rows:
        if not isinstance(row, dict) or not str(row.get("id", "")).strip():
            continue
        seed = [part.strip().upper() for part in str(row.get("seed", "")).split(",") if part.strip()]
        entry = {
            "id": str(row["id"]).strip(),
            "kind": str(row.get("kind", "")).strip(),
            "target": str(row.get("target", "")).strip().upper(),
            "seed": seed,
            "response": str(row.get("response", "")).strip().upper(),
            "order": int(row.get("order") or 1),
        }
        scope = str(row.get("scope", "")).strip().upper()
        if scope:
            entry["scope"] = scope
        derivatives.append(entry)
    updated["schema_version"] = UNIFIED_SCHEMA_VERSION
    updated["derivatives"] = derivatives
    updated["parameters"] = _mapping_rows(parameter_rows, "props_index", include_value=True)
    updated["state_variables"] = _mapping_rows(state_rows, "statev_index", include_value=False)

    try:
        requests = load_project_derivative_requests(updated, emit_deprecations=False)
    except (TypeError, ValueError) as exc:
        raise DerivativeRequestError(str(exc)) from exc
    errors = validate_derivative_requests(requests)
    if errors:
        raise DerivativeRequestError("; ".join(errors))
    return updated


def _mapping_rows(
    rows: Iterable[dict[str, Any]], index_key: str, *, include_value: bool
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("name", "")).strip():
            continue
        entry = {
            "name": str(row["name"]).strip().upper(),
            index_key: int(row.get(index_key)),
        }
        if include_value and row.get("value") is not None:
            entry["value"] = float(row["value"])
        result.append(entry)
    return result
