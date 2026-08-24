"""Adapt ``resasm_umat_transform_v2`` contracts to the canonical schema.

The parameter-sensitivity model set was authored against a different contract
schema. Rewriting eighteen JSON files by hand would be unreviewable and would
lose the original; this adapter is a tested function instead, and the v2
contracts stay in the repository verbatim as the source of truth.

Three v2 shapes exist in the wild and all three are handled:

``derivative: {response, export}``
    17 models. The response and the export name are given; the seed is implied
    to be ``PROPS`` because the export is a parameter derivative.
``derivative: {of, wrt, order}``
    3 models. Seed and response are explicit.
``derivative_requests: [...]`` with an ``interface`` block
    1 model (m2_elastic3d). Fully explicit, including per-component OTI
    direction assignments.

**Nothing is silently dropped.** Every v2 key the canonical schema has no home
for is returned in ``unmapped``, so a reader can see what was left behind rather
than having to diff the two files to find out.

**Finite strain is refused rather than guessed.** A small-strain contract seeds
``DSTRAN``; a finite-strain one must seed the deformation gradient. The canonical
request model has no deformation-gradient seed today, so rather than emit a
contract that would silently differentiate the wrong quantity, this raises. All
21 models in the current set declare ``small_strain``, so nothing is blocked by
that today -- but a finite-strain contract must not quietly become a wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

V2_SCHEMA = "resasm_umat_transform_v2"
CANONICAL_SCHEMA_VERSION = "1.1"

SMALL_STRAIN = "small_strain"
#: Kinematics values that require a deformation-gradient seed rather than DSTRAN.
FINITE_STRAIN = {"finite_strain", "large_strain", "finite", "total_lagrangian",
                 "updated_lagrangian"}

#: v2 keys that carry no information the canonical contract needs. Listed
#: explicitly so that "unmapped" means "we looked at it", not "we missed it".
DELIBERATELY_DROPPED = {
    "schema": "identifies the source schema; the canonical contract declares its own",
    "output.object": "names a prebuilt .obj from another run; this pipeline rebuilds",
    "output.contract": "names another run's generated contract",
    "resasm_provider": "line numbers into a specific source revision, not portable",
    "transformation_hints": "hints for a different transformer implementation",
    "oti.number_of_directions": "derived here from the parameter count",
}


class ContractAdaptationError(ValueError):
    """The v2 contract cannot be expressed canonically without guessing."""


@dataclass
class AdaptedContract:
    contract: dict[str, Any]
    unmapped: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"contract": self.contract, "unmapped": self.unmapped, "notes": self.notes}


def _kinematics(v2: dict[str, Any]) -> str:
    interface = v2.get("interface") or {}
    return str(v2.get("kinematics") or interface.get("kinematics") or SMALL_STRAIN)


def _dimensions(v2: dict[str, Any]) -> dict[str, Any]:
    block = v2.get("dimensions") or v2.get("interface") or {}
    return {
        "ntens": block.get("ntens"),
        "nprops": block.get("nprops"),
        "nstatev": block.get("nstatev"),
    }


def _parameters(v2: dict[str, Any]) -> list[dict[str, Any]]:
    """Parameter list with PROPS indices and, where given, validation values."""
    values = ((v2.get("validation") or {}).get("props_values")
              or (v2.get("resasm_provider") or {}).get("props_values") or [])
    declared = v2.get("parameters")
    if not declared:
        # The fully explicit variant carries them inside the request's seed block.
        for request in v2.get("derivative_requests") or []:
            components = ((request.get("seed") or {}).get("components")) or []
            if components:
                declared = [{"name": c.get("name"), "props_index": c.get("index"),
                             "units": c.get("units")} for c in components]
                break
    out = []
    for entry in declared or []:
        index = entry.get("props_index")
        record = {"name": entry.get("name"), "props_index": index}
        if entry.get("units"):
            record["units"] = entry["units"]
        if isinstance(index, int) and 1 <= index <= len(values):
            record["value"] = values[index - 1]
        out.append(record)
    return out


def _seed_argument(v2: dict[str, Any], kinematics: str) -> str:
    """Which argument the derivative is taken with respect to."""
    derivative = v2.get("derivative") or {}
    explicit = derivative.get("wrt")
    if explicit:
        return str(explicit).upper()
    for request in v2.get("derivative_requests") or []:
        seed = (request.get("seed") or {}).get("argument")
        if seed:
            return str(seed).upper()
    # A parameter-derivative export with no explicit seed means PROPS.
    if derivative.get("export") in ("DSIGMA_DP", "DSTATEV_DP"):
        return "PROPS"
    if kinematics in FINITE_STRAIN:
        raise ContractAdaptationError(
            f"kinematics {kinematics!r} requires a deformation-gradient seed "
            f"(DFGRD1), which the canonical request model cannot express yet. "
            f"Refusing to emit a DSTRAN-seeded contract, which would "
            f"differentiate the wrong quantity.")
    return "DSTRAN"


def _requests(v2: dict[str, Any], kinematics: str) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    seed = _seed_argument(v2, kinematics)
    derivative = v2.get("derivative") or {}
    history = v2.get("history") or {}
    requests: list[dict[str, Any]] = []

    explicit = v2.get("derivative_requests") or []
    if explicit:
        for entry in explicit:
            export = (entry.get("export") or {}).get("name") or "DSIGMA_DP"
            response = (entry.get("response") or {}).get("argument") or "STRESS"
            requests.append({
                "id": entry.get("id") or f"{export.lower()}_request",
                "target": export,
                "seed": (entry.get("seed") or {}).get("argument", seed),
                "response": response,
                "order": int(entry.get("order", 1) or 1),
            })
        notes.append("built from the explicit derivative_requests block")
    elif derivative:
        response = str(derivative.get("response") or derivative.get("of") or "STRESS")
        target = str(derivative.get("export") or "DSIGMA_DP")
        requests.append({
            "id": "stress_parameter_sensitivity",
            "target": target,
            "seed": seed,
            "response": response,
            "order": int(derivative.get("order", 1) or 1),
        })
    else:
        raise ContractAdaptationError(
            "the v2 contract declares neither 'derivative' nor 'derivative_requests', "
            "so there is no derivative to request")

    # A state export is a second request, not a flag on the first: it has its own
    # response argument and its own target.
    state_export = history.get("export") or history.get("export_derivatives_as")
    if state_export and not any(r["target"] == state_export for r in requests):
        requests.append({
            "id": "state_parameter_sensitivity",
            "target": str(state_export),
            "seed": seed,
            "response": str(history.get("state") or history.get("argument") or "STATEV"),
            "order": 1,
        })
    return requests, notes


def _state_variables(v2: dict[str, Any]) -> list[dict[str, Any]]:
    """State-variable names, handling ``history.state`` being a list.

    Three contracts give ``history.state`` as a list (``["EQPLAS"]``,
    ``["g_alpha"]``). Interpolating that directly produced names like
    ``"['EQPLAS']_1"``, which flowed into the generated driver's CSV headers and
    into the derivative manifest as the canonical state-variable name.
    """
    nstatev = int(_dimensions(v2).get("nstatev") or 0)
    raw = (v2.get("history") or {}).get("state")
    if isinstance(raw, (list, tuple)):
        names = [str(n) for n in raw if n]
    elif raw:
        names = [str(raw)]
    else:
        names = []
    base = names[0] if names else "STATEV"
    out = []
    for index in range(1, nstatev + 1):
        if len(names) >= nstatev:
            name = names[index - 1]
        elif nstatev == 1:
            # A single slot takes the bare name; suffixing it would invent a
            # component index the model does not have.
            name = base
        else:
            name = f"{base}_{index}"
        out.append({"name": name, "statev_index": index})
    return out


def _collect_unmapped(v2: dict[str, Any], mapped: set[str]) -> dict[str, Any]:
    """Every v2 leaf with no canonical destination, by dotted path.

    This previously compared top-level keys only, so nested information --
    ``history.propagate`` in 17 contracts, ``history.path_dependent`` in 3,
    ``dimensions.nprops`` in 20 -- disappeared while the module claimed nothing
    was silently dropped. Walking leaves is what makes that claim true.
    """
    unmapped: dict[str, Any] = {}

    def walk(node: Any, path: str) -> None:
        if path in mapped:
            return
        if isinstance(node, dict) and node:
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
            return
        if not path:
            return
        unmapped[path] = {
            "value": node,
            "reason": DELIBERATELY_DROPPED.get(path, "no canonical equivalent"),
        }

    walk(v2, "")
    return unmapped


def adapt_v2_contract(v2: dict[str, Any], *, model: str,
                      source_path: str) -> AdaptedContract:
    """Convert one v2 contract into a canonical schema-1.1 contract."""
    schema = v2.get("schema")
    if schema != V2_SCHEMA:
        raise ContractAdaptationError(
            f"{model}: expected schema {V2_SCHEMA!r}, found {schema!r}")

    kinematics = _kinematics(v2)
    if kinematics in FINITE_STRAIN:
        raise ContractAdaptationError(
            f"{model}: kinematics {kinematics!r} needs a deformation-gradient seed, "
            f"which the canonical model cannot express. Refusing to guess.")
    if kinematics != SMALL_STRAIN:
        raise ContractAdaptationError(
            f"{model}: unrecognised kinematics {kinematics!r}; it is neither "
            f"small strain nor a known finite-strain value, so the correct seed "
            f"cannot be determined")

    dimensions = _dimensions(v2)
    requests, notes = _requests(v2, kinematics)
    parameters = _parameters(v2)

    contract: dict[str, Any] = {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "name": model,
        "source": source_path,
        "entry_routine": (v2.get("source") or {}).get("entry_point", "UMAT"),
        "ntens": dimensions.get("ntens"),
        "parameters": parameters,
        "state_variables": _state_variables(v2),
        "derivatives": requests,
        "provenance": {
            "adapted_from": V2_SCHEMA,
            "kinematics": kinematics,
            "seed_selected": requests[0]["seed"] if requests else None,
            "seed_rationale": (
                "small-strain parameter derivative: the seed is PROPS, not DSTRAN"
                if requests and requests[0]["seed"] == "PROPS"
                else f"small-strain kinematics: seeding {requests[0]['seed']}"
                if requests else "no request"),
        },
    }

    # The full PROPS vector, not only the seeded parameters. A model may declare
    # more properties than it differentiates; without these the driver would run
    # with them unassigned. Emitted by the adapter so any caller gets it, not
    # only the sweep runner.
    props_values = (v2.get("validation") or {}).get("props_values") or \
        (v2.get("resasm_provider") or {}).get("props_values") or []
    if props_values:
        contract.setdefault("material_point_driver", {})["static_props"] = [
            float(value) for value in props_values]
        seeded = {p["props_index"] for p in parameters if p.get("props_index")}
        unseeded = sorted(set(range(1, len(props_values) + 1)) - seeded)
        if unseeded:
            notes.append(
                f"PROPS {unseeded} are declared but not differentiated; their values "
                f"are carried in material_point_driver.static_props so the driver does "
                f"not run with them unassigned")

    # Direction order is list order, not PROPS order: the transformer assigns OTI
    # direction k to parameters[k-1]. Recording it removes any doubt about which
    # column of DSIGMA_DP belongs to which parameter.
    for direction, parameter in enumerate(parameters, start=1):
        parameter["oti_direction"] = direction

    additional = (v2.get("source") or {}).get("additional_files")
    if additional:
        contract["sources"] = [source_path, *additional]
        notes.append(f"{len(additional)} additional source file(s) declared")

    # Dotted paths whose information reaches the canonical contract. Anything
    # not listed here is reported as unmapped, including nested leaves.
    mapped = {
        "schema", "kinematics", "parameters", "validation",
        "source.main_file", "source.entry_point", "source.additional_files",
        "dimensions.ntens", "interface.ntens", "interface.kinematics",
        "dimensions.nstatev", "interface.nstatev",
        "derivative", "derivative_requests",
        "history.state", "history.argument",
        "history.export", "history.export_derivatives_as",
    }
    unmapped = _collect_unmapped(v2, mapped)

    nstatev = dimensions.get("nstatev") or 0
    history = v2.get("history") or {}
    has_state_request = any(r["target"] == "DSTATEV_DP" for r in requests)
    if nstatev == 0 and has_state_request:
        notes.append(
            "a DSTATEV_DP request is present but nstatev is 0: the model carries no "
            "state, so that request has nothing to differentiate and will produce no rows")
    if nstatev > 0 and not has_state_request:
        # Do not invent the request. The v2 contract declares path dependence but
        # never asks for the state derivative to be exported, and silently adding
        # one would put a request in the contract that its author did not write.
        notes.append(
            f"the model declares {nstatev} state variable(s)"
            + (" and path_dependent=true" if history.get("path_dependent") else "")
            + ", but the v2 contract declares no state export, so no DSTATEV_DP "
              "request was created. Add one explicitly if the state sensitivity is "
              "wanted; it is not inferred here.")
    return AdaptedContract(contract=contract, unmapped=unmapped, notes=notes)
