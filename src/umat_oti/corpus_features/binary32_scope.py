"""Which builds the binary32 judging rule applies to, and the double variant
of the original it needs (Vera B10, B32-0 and B32-3; :data:`fd.B32_RULE`).

Scope is decided per derivative entry (fd.B32_RULE; Vera's ruling replacing
B32-0). Its static half needs the transform's binary32 map: the stores of
OTI-carrying values the generated code rounds. The map is the transform's own record
(``umat_oti.transform.binary32.binary32_store_report``, field
``binary32_stores``: ``present`` and ``stores[*].name``), read from

* a transform-store entry: ``transform_report.json["binary32_stores"]``;
* a lifted (parameter-sensitivity) build: ``binary32_stores.json`` beside it.

An entry or build that predates the map has it computed from its generated
code by the same function when that function is available; otherwise the
scope is unknown and the rule is not applied (recorded as such).

B32-3 needs the double variant of the ORIGINAL: every explicit
single-precision REAL declaration widened to REAL*8 (``abaqus.precision.
widen``), no OTI. A name single only by Fortran's default implicit typing is
not widened -- that would write a declaration the author never wrote -- and
is recorded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

#: The map's field name, as the transform writes it
#: (umat_oti.transform.binary32.BINARY32_STORES_FIELD).
FIELD = "binary32_stores"
LIFTED_FILE = "binary32_stores.json"


def _report(generated_texts: Iterable[str], original_text: str) -> Optional[dict]:
    try:
        from umat_oti.transform.binary32 import binary32_store_report
    except ImportError:                       # a transform without the map
        return None
    return binary32_store_report(list(generated_texts), original_text)


def scope(binary32_map: Optional[dict], origin: str) -> dict:
    """The binary32 map of one build: whether it lists a store (the
    precondition of the per-entry scope test, Vera's B32 ruling)."""
    if not isinstance(binary32_map, dict) or "stores" not in binary32_map:
        return {"lists_stores": None, "origin": origin,
                "reason": "no binary32 map for this build: the B32 rule is not applied"}
    names = [s.get("name") for s in binary32_map.get("stores") or []]
    return {"lists_stores": bool(names), "origin": origin, "stores": names,
            "rounded_operations": binary32_map.get("rounded_operations"),
            "schema": binary32_map.get("schema"),
            "reason": (f"the transform rounds {len(names)} binary32 value(s) on the derivative "
                       f"path ({', '.join(names[:8])}{', ...' if len(names) > 8 else ''})"
                       if names else "no binary32 store on the derivative path")}


def store_scope(store_dir: Path, units: Iterable[Path], original_text: str) -> dict:
    report = Path(store_dir) / "transform_report.json"
    try:
        found = json.loads(report.read_text()).get(FIELD)
    except (OSError, ValueError, AttributeError):
        found = None
    if isinstance(found, dict):
        return scope(found, f"{report.name}[{FIELD}]")
    texts = [Path(u).read_text(errors="replace") for u in units]
    return scope(_report(texts, original_text),
                 "computed from the store's generated code (entry predates the map)")


def lifted_scope(work_dir: Path, layout=None, original_text: str = "") -> dict:
    found = getattr(layout, FIELD, None) if layout is not None else None
    if isinstance(found, dict) and found:
        return scope(found, f"lifted layout.{FIELD}")
    path = Path(work_dir) / LIFTED_FILE
    if path.is_file():
        try:
            return scope(json.loads(path.read_text()), LIFTED_FILE)
        except ValueError:
            pass
    lifted = getattr(layout, "lifted_umat", None) if layout is not None else None
    text = Path(lifted).read_text(errors="replace") if lifted and Path(lifted).is_file() else ""
    return scope(_report([text], original_text) if text else None,
                 "computed from the lifted code (build predates the map)")


def double_variant(original_text: str) -> tuple[str, dict]:
    """The original with every explicit single-precision REAL declaration
    widened to REAL*8; and what changed."""
    from umat_oti.abaqus import precision as P

    names: list[str] = []
    for line in original_text.splitlines():
        if P._COMMENT_FIXED.match(line):
            continue
        split = P._declaration_split(line)
        if split is not None:
            names += [n.upper() for n in P._entity_names(split[1])]
    narrow = P.narrow_declarations(original_text, names)
    widened = tuple(sorted({n.upper() for found in narrow for n in found.names}))
    finding = P.PrecisionFinding(promoted=widened, narrow=narrow, widened=widened)
    text, changes = P.widen(original_text, finding)
    return text, {"widened": list(widened), "changes": list(changes),
                  "rule": "every explicit single-precision REAL declaration -> REAL*8 "
                          "(abaqus.precision.widen); no OTI; implicit single typing unchanged"}


#: The routine's arguments each derivative input enters through.
INPUT_NAMES = {"strain": ("DSTRAN", "STRAN", "DFGRD1", "DFGRD0"),
               "props": ("PROPS",), "statev": ("STATEV",)}
OUTPUT_NAMES = {"stress": ("STRESS",), "statev": ("STATEV",)}


def static_paths(source: Path, stores: Iterable[str]) -> dict:
    """Vera's static scope condition, per (output, input) kind: does the
    output depend on a binary32 store of the map that itself depends on the
    input? Read off the ORIGINAL's assignment and CALL-effect edges
    (umat_oti.fortran.regions), flow-insensitive and at whole-variable
    granularity: data dependence only, so a store reached only through a
    branch condition is out of the static path (the stricter double model).

    Returns ``{"stress|strain": {"static_path": bool, "stores": [...]}, ...,
    "edges": n}`` or ``{"error": ...}``."""
    from umat_oti.fortran import regions as R
    from umat_oti.fortran.parser import parse_fortran_file

    stores = [str(s).upper() for s in stores]
    try:
        parsed = parse_fortran_file(Path(source))
        edges = R._assignments(parsed.logical_lines) + R._call_effect_assignments(
            parsed.logical_lines, R._routine_effect_table(parsed))
    except Exception as error:                                   # noqa: BLE001
        return {"error": f"{type(error).__name__}: {error}"}
    upstream = {s: R._upstream_dependencies_for(s, edges) for s in stores}
    out: dict = {"edges": len(edges)}
    for okind, onames in OUTPUT_NAMES.items():
        feeding = set()
        for name in onames:
            feeding |= R._upstream_dependencies_for(name, edges)
        for ikind, inames in INPUT_NAMES.items():
            via = [s for s in stores if s in feeding and set(inames) & upstream[s]]
            out[f"{okind}|{ikind}"] = {"static_path": bool(via), "stores": via}
    return out


def static_for(table: Optional[dict], output_kind: str, input_kind: str) -> bool:
    """The static condition for one cell; True when it could not be read
    (the dynamic condition then decides alone -- never laxer than having
    no static test)."""
    if not table or "error" in table:
        return True
    return bool((table.get(f"{output_kind}|{input_kind}") or {}).get("static_path"))
