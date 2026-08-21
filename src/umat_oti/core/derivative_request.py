"""Canonical unified derivative-request model for UMAT-OTI.

This module introduces the ``DerivativeRequest`` canonical model that the
SoftwareX paper describes as the single internal representation for every
derivative product produced by UMAT-OTI:

* ``material_tangent`` — the standard Abaqus tangent ``DDSDDE`` (order 1,
  seed ``DSTRAN``, response ``STRESS``).
* ``local_jacobian`` — a routine-local Jacobian used inside a return-mapping
  loop (e.g. ``FJAC``, ``DETDG``, ``GDIA``, ``ANP1P``, ``BNP1P``, ``CEVPI``).
* ``higher_order`` — repeated / mixed higher-order derivatives (orders 2--4).
* ``parameter_sensitivity`` — point-wise sensitivities of ``STRESS`` and
  ``STATEV`` with respect to named ``PROPS`` entries (``DSIGMA_DP``,
  ``DSTATEV_DP``).

The transformer already accepts the historical contract shapes (compact
``jacobian`` block, ``extra_jacobian_contracts`` / ``constitutive_jacobians``,
``advanced``). This module *normalizes* each of those shapes onto a single
list of :class:`DerivativeRequest` values without rewriting the transformer,
so downstream reporting, validation, and the manifest emitter can rely on one
canonical vocabulary. Legacy contracts continue to load and transform through
the pre-existing code paths.

The new unified contract format described in the SoftwareX task
(``schema_version: 1.1``, top-level ``derivatives: [...]``) is also loaded
into the same canonical form.
"""

from __future__ import annotations

import copy
import json
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Optional


UNIFIED_SCHEMA_VERSION = "1.1"


# Recognised derivative kinds. These are advisory tags; the transformer decides
# how to satisfy them from the individual fields.
KIND_MATERIAL_TANGENT = "material_tangent"
KIND_LOCAL_JACOBIAN = "local_jacobian"
KIND_HIGHER_ORDER = "higher_order"
KIND_PARAMETER_SENSITIVITY = "parameter_sensitivity"
KIND_STATE_SENSITIVITY = "state_sensitivity"

_KNOWN_KINDS = frozenset({
    KIND_MATERIAL_TANGENT,
    KIND_LOCAL_JACOBIAN,
    KIND_HIGHER_ORDER,
    KIND_PARAMETER_SENSITIVITY,
    KIND_STATE_SENSITIVITY,
})


class DerivativeRequestError(ValueError):
    """Raised when a derivative request cannot be interpreted."""


@dataclass(frozen=True)
class DerivativeRequest:
    """Canonical UMAT-OTI derivative-request record.

    All arrays are stored as tuples so instances are hashable and safe to
    place inside sets / dict keys.
    """

    id: str
    target: str
    seed: tuple[str, ...]
    response: str
    order: int
    kind: str = KIND_MATERIAL_TANGENT
    scope: Optional[str] = None
    components: Optional[tuple[int, ...]] = None
    parameter_map: tuple[tuple[str, int], ...] = ()
    state_map: tuple[tuple[str, int], ...] = ()
    output_layout: str = "jacobian"
    output_shape: Optional[tuple[int, ...]] = None
    source_contract: str = "compact"
    description: str = ""
    origin: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "seed": list(self.seed),
            "response": self.response,
            "order": self.order,
            "output_layout": self.output_layout,
            "source_contract": self.source_contract,
        }
        if self.scope:
            payload["scope"] = self.scope
        if self.components is not None:
            payload["components"] = list(self.components)
        if self.parameter_map:
            payload["parameters"] = [
                {"name": name, "props_index": index}
                for name, index in self.parameter_map
            ]
        if self.state_map:
            payload["state_variables"] = [
                {"name": name, "statev_index": index}
                for name, index in self.state_map
            ]
        if self.output_shape is not None:
            payload["output_shape"] = list(self.output_shape)
        if self.description:
            payload["description"] = self.description
        return payload


# ---------------------------------------------------------------------------
# Loading + normalization
# ---------------------------------------------------------------------------

def load_project_derivative_requests(
    config: dict[str, Any],
    *,
    emit_deprecations: bool = True,
) -> list[DerivativeRequest]:
    """Normalize any legacy project-config into canonical DerivativeRequests.

    Recognized shapes (all supported, all normalized to the same output):

    * Compact / expanded contract with a top-level ``jacobian`` block plus
      optional ``constitutive_jacobians`` / ``extra_jacobian_contracts``
      and ``advanced``.
    * A "unified" contract (``schema_version: 1.1``) with a top-level
      ``derivatives: [...]`` array. This form also carries top-level
      ``parameters`` and ``state_variables`` blocks that populate each
      request's parameter / state maps.

    Unknown keys are ignored. When ``emit_deprecations`` is true, a
    :class:`DeprecationWarning` is issued for each legacy shape encountered so
    the user is nudged toward the unified schema without breaking anything.
    """

    if not isinstance(config, dict):
        raise DerivativeRequestError("project config must be a dict")

    # Unified format (schema_version >= 1.1) takes precedence if present.
    if str(config.get("schema_version", "")).strip() == UNIFIED_SCHEMA_VERSION:
        return _from_unified_contract(config)

    requests: list[DerivativeRequest] = []

    # 1) Compact "jacobian" block -> the material tangent request.
    tangent_request = _material_tangent_from_config(config)
    if tangent_request is not None:
        requests.append(tangent_request)

    parameter_map = _parameter_map_from_config(config)
    state_map = _state_map_from_config(config)

    # 2) Legacy constitutive_jacobians / extra_jacobian_contracts lists.
    #    extra_jacobian_contracts is the older key; both are still supported.
    for source_key in ("constitutive_jacobians", "extra_jacobian_contracts"):
        entries = config.get(source_key)
        if not isinstance(entries, list) or not entries:
            continue
        if source_key == "extra_jacobian_contracts" and emit_deprecations:
            warnings.warn(
                "'extra_jacobian_contracts' is a legacy alias for "
                "'constitutive_jacobians'; both still load, but new contracts "
                "should use 'derivatives' under the unified schema.",
                DeprecationWarning,
                stacklevel=2,
            )
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                continue
            requests.append(
                _local_jacobian_from_entry(
                    entry,
                    default_id=f"{source_key}_{index}",
                    parameter_map=parameter_map,
                    state_map=state_map,
                    source_contract=source_key,
                )
            )

    # 3) Higher-order block ("advanced" — loader-implemented, codegen deferred).
    advanced = config.get("advanced")
    if isinstance(advanced, dict) and advanced:
        for advanced_request in _requests_from_advanced_block(
            advanced,
            parameter_map=parameter_map,
            state_map=state_map,
        ):
            requests.append(advanced_request)

    return requests


def load_unified_contract(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    """Parse the unified contract JSON payload into its dict form.

    The returned dict is ready to feed :func:`load_project_derivative_requests`,
    which will detect the ``schema_version`` and take the unified path.
    """
    if isinstance(payload, dict):
        data = payload
    else:
        if isinstance(payload, bytes):
            text = payload.decode("utf-8")
        else:
            text = payload
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DerivativeRequestError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DerivativeRequestError("unified contract must be a JSON object")
    if str(data.get("schema_version", "")).strip() != UNIFIED_SCHEMA_VERSION:
        raise DerivativeRequestError(
            f"unified contract requires schema_version='{UNIFIED_SCHEMA_VERSION}'; "
            f"got '{data.get('schema_version')}'"
        )
    return data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_derivative_requests(
    requests: Iterable[DerivativeRequest],
    *,
    supported_orders: Iterable[int] = (1, 2, 3, 4),
) -> list[str]:
    """Return a list of human-readable validation errors (empty if all valid).

    Checks:
    * duplicate request ids
    * empty or missing ``seed`` / ``target`` / ``response``
    * unsupported ``order`` (outside ``supported_orders``)
    * unknown ``kind`` tag
    * PROPS indices are 1-based positive ints; STATEV indices likewise
    * duplicate PROPS / STATEV indices within a single request
    """
    supported_orders = set(supported_orders)
    errors: list[str] = []
    seen_ids: set[str] = set()
    for request in requests:
        if not request.id:
            errors.append("a derivative request is missing an 'id'")
            continue
        if request.id in seen_ids:
            errors.append(f"duplicate derivative-request id: {request.id!r}")
        seen_ids.add(request.id)
        if not request.target:
            errors.append(f"{request.id}: 'target' is empty")
        if not request.response:
            errors.append(f"{request.id}: 'response' is empty")
        if not request.seed:
            errors.append(f"{request.id}: at least one seed variable is required")
        if request.order not in supported_orders:
            errors.append(
                f"{request.id}: order={request.order} not in supported set "
                f"{sorted(supported_orders)}"
            )
        if request.kind not in _KNOWN_KINDS:
            errors.append(
                f"{request.id}: unknown kind {request.kind!r}; expected one of "
                f"{sorted(_KNOWN_KINDS)}"
            )
        for kind, mapping in (
            ("PROPS", request.parameter_map),
            ("STATEV", request.state_map),
        ):
            seen_indices: set[int] = set()
            for name, index in mapping:
                if not name:
                    errors.append(f"{request.id}: {kind} entry has empty name")
                    continue
                if not isinstance(index, int) or index < 1:
                    errors.append(
                        f"{request.id}: {kind} index for {name!r} must be a "
                        f"1-based positive integer, got {index!r}"
                    )
                    continue
                if index in seen_indices:
                    errors.append(
                        f"{request.id}: {kind} index {index} appears twice"
                    )
                seen_indices.add(index)
    return errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _upper_str(value: Any) -> str:
    return _as_str(value).upper()


def _seed_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(_upper_str(item) for item in value if _upper_str(item))
    text = _upper_str(value)
    return (text,) if text else ()


def _material_tangent_from_config(config: dict[str, Any]) -> Optional[DerivativeRequest]:
    jacobian = config.get("jacobian")
    source_contract = "compact"
    origin: dict[str, Any] = {}
    seed = "DSTRAN"
    response = "STRESS"
    target = "DDSDDE"
    order = int(config.get("order", 1) or 1)
    ntens_hint: Any = config.get("ntens")

    if isinstance(jacobian, dict) and jacobian:
        seed = _upper_str(jacobian.get("seed") or seed)
        response = _upper_str(jacobian.get("output") or response)
        target = _upper_str(jacobian.get("target") or target)
        origin = copy.deepcopy(jacobian)
    else:
        expanded = config.get("jacobian_contract")
        if isinstance(expanded, dict) and expanded:
            seed = _upper_str(expanded.get("independent_variable") or seed)
            response = _upper_str(expanded.get("dependent_variable") or response)
            target = _upper_str(expanded.get("output_variable") or target)
            source_contract = "expanded"
            origin = copy.deepcopy(expanded)
        elif isinstance(config.get("mapping"), dict):
            mapping = config["mapping"]
            seed = _upper_str(mapping.get("dstran") or seed)
            response = _upper_str(mapping.get("stress") or response)
            target = _upper_str(mapping.get("ddsdde") or target)
            source_contract = "expanded"
            origin = copy.deepcopy(mapping)
        else:
            return None

    settings = config.get("transformation_settings")
    if isinstance(settings, dict):
        if not ntens_hint:
            ntens_hint = settings.get("ntens")
        if source_contract == "expanded" and not config.get("order"):
            order = int(settings.get("order", order) or order)

    output_shape: Optional[tuple[int, ...]] = None
    if isinstance(ntens_hint, int) and ntens_hint > 0:
        output_shape = (ntens_hint, ntens_hint)
    elif isinstance(ntens_hint, str) and ntens_hint.strip().isdigit():
        n = int(ntens_hint)
        if n > 0:
            output_shape = (n, n)

    return DerivativeRequest(
        id="material_tangent",
        kind=KIND_HIGHER_ORDER if order > 1 else KIND_MATERIAL_TANGENT,
        target=target,
        seed=(seed,) if seed else (),
        response=response,
        order=order,
        output_layout="jacobian",
        output_shape=output_shape,
        source_contract=source_contract,
        description="Standard Abaqus consistent tangent.",
        origin=origin,
    )


def _local_jacobian_from_entry(
    entry: dict[str, Any],
    *,
    default_id: str,
    parameter_map: tuple[tuple[str, int], ...],
    state_map: tuple[tuple[str, int], ...],
    source_contract: str,
) -> DerivativeRequest:
    request_id = _as_str(entry.get("id")) or default_id
    seed = entry.get("seed")
    if isinstance(seed, dict):
        seed_variable = _upper_str(seed.get("variable"))
    else:
        seed_variable = _upper_str(seed)
    output = entry.get("output")
    if isinstance(output, dict):
        response = _upper_str(output.get("variable"))
    else:
        response = _upper_str(output)
    replace_variable = _upper_str(entry.get("replace_variable"))
    # In the legacy contract the "target" (where the derivative array lives)
    # is the routine-local variable being replaced; when that is empty we fall
    # back to the response variable itself.
    target = replace_variable or response or "FJAC"
    scope = _upper_str(entry.get("selected_umat") or entry.get("routine") or "UMAT")
    return DerivativeRequest(
        id=request_id,
        kind=KIND_LOCAL_JACOBIAN,
        target=target,
        seed=(seed_variable,) if seed_variable else (),
        response=response or "RESID",
        order=1,
        scope=scope,
        parameter_map=parameter_map,
        state_map=state_map,
        output_layout="jacobian",
        source_contract=source_contract,
        description=_as_str(entry.get("description")),
        origin=copy.deepcopy(entry),
    )


def _requests_from_advanced_block(
    advanced: dict[str, Any],
    *,
    parameter_map: tuple[tuple[str, int], ...],
    state_map: tuple[tuple[str, int], ...],
) -> list[DerivativeRequest]:
    seed = advanced.get("seed") or advanced.get("seed_variables") or ()
    if isinstance(seed, (list, tuple)):
        seed_vars = tuple(_upper_str(item) for item in seed if _upper_str(item))
    else:
        text = _upper_str(seed)
        seed_vars = (text,) if text else ()
    response = _upper_str(advanced.get("output"))
    default_target = _upper_str(advanced.get("target"))
    extract = advanced.get("extract")
    if not isinstance(extract, list) or not extract:
        extract = [{"order": 1, "target": default_target, "layout": "jacobian"}]
    routine = _upper_str(advanced.get("routine"))
    description = _as_str(advanced.get("description"))

    results: list[DerivativeRequest] = []
    for index, item in enumerate(extract, start=1):
        item_dict = _dict(item)
        order = int(item_dict.get("order") or 1)
        target = _upper_str(item_dict.get("target") or default_target)
        layout = _as_str(item_dict.get("layout") or "jacobian").lower() or "jacobian"
        kind = KIND_HIGHER_ORDER if order > 1 else KIND_MATERIAL_TANGENT
        request_id = _as_str(item_dict.get("id")) or f"advanced_extract_{index}"
        results.append(
            DerivativeRequest(
                id=request_id,
                kind=kind,
                target=target,
                seed=seed_vars,
                response=response,
                order=order,
                scope=routine or None,
                parameter_map=parameter_map,
                state_map=state_map,
                output_layout=layout,
                source_contract="advanced",
                description=description,
                origin=copy.deepcopy(item_dict),
            )
        )
    return results


def _parameter_map_from_config(config: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    raw = config.get("parameters")
    if not isinstance(raw, list):
        return ()
    entries: list[tuple[str, int]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = _upper_str(row.get("name"))
        idx = row.get("props_index")
        if not name or not isinstance(idx, int) or idx < 1:
            continue
        entries.append((name, idx))
    return tuple(entries)


def _state_map_from_config(config: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    raw = config.get("state_variables")
    if not isinstance(raw, list):
        return ()
    entries: list[tuple[str, int]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = _upper_str(row.get("name"))
        idx = row.get("statev_index")
        if not name or not isinstance(idx, int) or idx < 1:
            continue
        entries.append((name, idx))
    return tuple(entries)


def _from_unified_contract(config: dict[str, Any]) -> list[DerivativeRequest]:
    parameter_map = _parameter_map_from_config(config)
    state_map = _state_map_from_config(config)
    derivatives = config.get("derivatives")
    if not isinstance(derivatives, list) or not derivatives:
        raise DerivativeRequestError(
            "unified contract must contain a non-empty 'derivatives' list"
        )
    results: list[DerivativeRequest] = []
    for index, entry in enumerate(derivatives, start=1):
        if not isinstance(entry, dict):
            raise DerivativeRequestError(
                f"derivatives[{index}] must be an object"
            )
        request_id = _as_str(entry.get("id")) or f"derivative_{index}"
        target = _upper_str(entry.get("target"))
        seed = _seed_tuple(entry.get("seed"))
        response = _upper_str(entry.get("response"))
        order = int(entry.get("order") or 1)
        kind = _classify_kind(entry, seed=seed, target=target, order=order)
        parameter_selection = _select_from_seed(seed, parameter_map)
        state_selection = _select_from_seed(seed, state_map)
        results.append(
            DerivativeRequest(
                id=request_id,
                kind=kind,
                target=target,
                seed=seed,
                response=response,
                order=order,
                scope=_upper_str(entry.get("scope")) or None,
                components=_components(entry.get("components")),
                parameter_map=parameter_selection,
                state_map=state_selection,
                output_layout=_as_str(entry.get("output_layout") or "jacobian").lower(),
                output_shape=_shape(entry.get("output_shape")),
                source_contract="unified",
                description=_as_str(entry.get("description")),
                origin=copy.deepcopy(entry),
            )
        )
    return results


def _classify_kind(
    entry: dict[str, Any],
    *,
    seed: tuple[str, ...],
    target: str,
    order: int,
) -> str:
    explicit = _as_str(entry.get("kind"))
    if explicit and explicit in _KNOWN_KINDS:
        return explicit
    scope = _upper_str(entry.get("scope"))
    if target in {"DSIGMA_DP", "DSTATEV_DP"}:
        return KIND_STATE_SENSITIVITY if target == "DSTATEV_DP" else KIND_PARAMETER_SENSITIVITY
    if scope and scope != "UMAT":
        return KIND_LOCAL_JACOBIAN
    if order > 1:
        return KIND_HIGHER_ORDER
    return KIND_MATERIAL_TANGENT


def _components(value: Any) -> Optional[tuple[int, ...]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(int(item) for item in value)
    return None


def _shape(value: Any) -> Optional[tuple[int, ...]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(int(item) for item in value)
    return None


def _select_from_seed(
    seed: tuple[str, ...],
    mapping: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    if not seed or not mapping:
        return mapping
    seed_set = {name.upper() for name in seed}
    filtered = tuple((name, idx) for name, idx in mapping if name.upper() in seed_set)
    return filtered or mapping


__all__ = [
    "DerivativeRequest",
    "DerivativeRequestError",
    "KIND_HIGHER_ORDER",
    "KIND_LOCAL_JACOBIAN",
    "KIND_MATERIAL_TANGENT",
    "KIND_PARAMETER_SENSITIVITY",
    "KIND_STATE_SENSITIVITY",
    "UNIFIED_SCHEMA_VERSION",
    "load_project_derivative_requests",
    "load_unified_contract",
    "validate_derivative_requests",
]
