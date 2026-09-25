"""Stage source dependencies with output-relative include references."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from umat_oti.fortran.parser import logical_lines_from_text
from umat_oti.fortran.normalize import detect_source_form


_INCLUDE = re.compile(r"^\s*(?:INCLUDE\s*|#\s*include\s*)['\"]([^'\"]+)['\"]\s*$", re.IGNORECASE)


def bundle_sources(sources, out_dir: Path, *, roots=(), runtime_calls=(), library_calls=None):
    out_dir = out_dir.resolve()
    roots = tuple(Path(root).resolve() for root in roots)
    paths = {}
    texts = {}
    edges = {}
    missing = []
    runtime_includes = []

    def visit(path, inherited_form=None):
        path = Path(path).resolve()
        if path in paths:
            return
        paths[path] = Path("dependencies") / path.name
        text = path.read_text(encoding="utf-8")
        form = inherited_form if path.suffix.lower() not in {".f", ".for", ".f77", ".f90", ".f95"} and inherited_form else detect_source_form(path, text)
        texts[path] = (text, form)
        edges[path] = []
        for line in logical_lines_from_text(text, form):
            match = _INCLUDE.fullmatch(line.text)
            if not match:
                continue
            name = match.group(1)
            local = (path.parent / name).resolve()
            if local.is_file():
                target = local
            else:
                candidates = set()
                for root in roots:
                    base = root if root.is_dir() else root.parent
                    direct = base / name
                    if direct.is_file():
                        candidates.add(direct.resolve())
                    elif not Path(name).is_absolute():
                        candidates.update(item.resolve() for item in base.rglob(Path(name).name)
                                          if item.is_file() and out_dir not in item.resolve().parents
                                          and item.as_posix().endswith('/' + name))
                if len({candidate.read_bytes() for candidate in candidates}) > 1:
                    raise ValueError(f"Ambiguous include {name!r} required by {path.name}")
                target = min(candidates, key=str) if candidates else None
            if target is None:
                record = {"source": str(path), "include": name}
                (runtime_includes if Path(name).name.lower() == "aba_param.inc" else missing).append(record)
                continue
            edges[path].append((line.line_numbers, name, target))
            visit(target, form)

    for source in sources:
        visit(source)
    reserved = {path.name.casefold() for path in paths}
    allocated = set()
    for original in sorted(paths, key=str):
        name = original.name
        if name.casefold() in allocated:
            digest = hashlib.sha256(str(original).encode("utf-8")).hexdigest()[:12]
            name = f"{original.stem}__{digest}{original.suffix}"
            serial = 1
            while name.casefold() in allocated or name.casefold() in reserved:
                name = f"{original.stem}__{digest}_{serial}{original.suffix}"
                serial += 1
        allocated.add(name.casefold())
        paths[original] = Path("dependencies") / name
    records = []
    for original, relative in paths.items():
        text, form = texts[original]
        lines = text.splitlines()
        for numbers, name, target in reversed(edges[original]):
            rewritten = f"INCLUDE '{paths[target].as_posix()}'"
            if lines[numbers[0]-1].lstrip().startswith('#'):
                rewritten = f'#include "{paths[target].as_posix()}"'
            elif form == "fixed":
                from umat_oti.transform.source_transform import _wrap_fixed_form_line
                rewritten = _wrap_fixed_form_line("      " + rewritten)
            lines[numbers[0]-1:numbers[-1]] = [rewritten]
        destination = out_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        records.append({"original": str(original), "bundled": relative.as_posix(),
                "original_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                "bundled_sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
    manifest = {"files": records, "missing_includes": missing, "runtime_includes": runtime_includes,
            "source_includes_complete": not missing,
                "runtime_calls": list(runtime_calls), "external_library_calls": library_calls or {},
                "include_base": ".", "compile_sources": "compile_order.txt",
                "note": "Dependency sources are staged for provenance/reuse; do not compile them again alongside the resolved UMAT."}
    manifest_path = out_dir / "dependency_bundle.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {original: out_dir / relative for original, relative in paths.items()}, manifest_path