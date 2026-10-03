"""Which builds the binary32 judging rule applies to, and the double variant
of the original it needs (Vera B10, B32-0 and B32-3; :data:`fd.B32_RULE`).

B32-0: a source is in scope only if the transform's binary32 map lists a
store of an OTI-carrying value. The map is the transform's own record
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
    """B32-0 for one build: in scope iff the map lists a store."""
    if not isinstance(binary32_map, dict) or "stores" not in binary32_map:
        return {"in_scope": None, "origin": origin,
                "reason": "no binary32 map for this build: the B32 rule is not applied"}
    names = [s.get("name") for s in binary32_map.get("stores") or []]
    return {"in_scope": bool(names), "origin": origin, "stores": names,
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
