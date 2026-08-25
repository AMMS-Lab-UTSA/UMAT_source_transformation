"""Resolve a UMAT's routine closure across multiple source files.

A single-file UMAT is the easy case. Real ones frequently call helpers that live
beside them: UMAT_PCO calls KCLEAR, KMMULT, KMTRAN, KMAVEC, KUPDVEC, KSMULT and
KMATSUB and defines none of them, so compiling it alone fails at link time with
seven undefined symbols and no indication of where the definitions might be.

Two things make this more than a file search.

**Duplication.** In the upstream ABAQUS-US repository each of those helpers is
defined in more than thirty files. Picking one arbitrarily would be a numerical
decision disguised as a build decision, so every definition found is recorded,
their bodies are compared, and a choice is only made silently when the
candidates agree. Where they disagree the resolver refuses and says which files
differ.

**Diagnostics.** A missing symbol is reported with the routine that calls it,
every root that was searched, and any near-miss candidates, because "undefined
reference to kmmult_" tells the user nothing they can act on.

Nothing here fabricates a definition. A helper that cannot be found is an
unresolved dependency and the caller is told exactly that; stubbing an
arithmetic routine would silently change the numbers.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from umat_oti.core.model import ParsedFortranSource, ParsedSubroutine
from umat_oti.fortran.normalize import detect_source_form
from umat_oti.fortran.parser import logical_lines_from_text, parse_subroutines

__all__ = [
    "RoutineDefinition",
    "MissingDependency",
    "DuplicateDefinition",
    "DependencyGraph",
    "SourceIndex",
    "index_sources",
    "resolve_closure",
    "DependencyResolutionError",
]

FORTRAN_SUFFIXES = (".for", ".f", ".f90", ".f77", ".FOR", ".F", ".F90")

_CALL_RE = re.compile(r"(?:^|\W)CALL\s+([A-Za-z_]\w*)", re.IGNORECASE)
_EXTERNAL_RE = re.compile(r"^\s*EXTERNAL\s+(.+)$", re.IGNORECASE)
_INCLUDE_RE = re.compile(r"^\s*INCLUDE\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)
_DEF_RE = re.compile(
    r"^\s*(?:\d+\s+)?(?:(?:RECURSIVE|PURE|ELEMENTAL|IMPURE)\s+)*"
    r"(?:(?P<kind>SUBROUTINE)\s+(?P<sname>[A-Za-z_]\w*)"
    r"|(?:[A-Za-z0-9_()*\s]*?\s)?(?P<fkind>FUNCTION)\s+(?P<fname>[A-Za-z_]\w*))",
    re.IGNORECASE)
#: End of a program unit, and nothing else. Writing this as "END" followed by a
#: negative lookahead does not work: the optional whitespace can match zero
#: characters, the lookahead then passes on " DO", and the trailing name group
#: happily consumes "DO". So "END DO" was accepted as the end of the routine and
#: every dependency below the first loop vanished -- UMAT_PCO appeared to call
#: one helper when it calls seven. Only the real forms are matched.
_END_RE = re.compile(
    r"^\s*(?:\d+\s+)?(?:"
    r"END"                                        # bare END
    r"|END\s*SUBROUTINE(?:\s+[A-Za-z_]\w*)?"      # END SUBROUTINE [name]
    r"|END\s*FUNCTION(?:\s+[A-Za-z_]\w*)?"        # END FUNCTION [name]
    r")\s*$",
    re.IGNORECASE)

#: Routines supplied by the Abaqus runtime rather than by any source file. They
#: are not missing dependencies; a standalone build stubs or omits them.
ABAQUS_RUNTIME_ROUTINES = frozenset({
    "XIT", "STDB_ABQERR", "GETOUTDIR", "GETJOBNAME", "GETNUMCPUS",
    "SPRINC", "SPRIND", "ROTSIG", "SINV", "GETPARTINFO", "GETVRM",
    # Compiler intrinsics some sources call as subroutines. They need no
    # definition from any file and must not be reported as missing.
    "MUTEXLOCK", "MUTEXUNLOCK", "MUTEXINIT", "GETNUMTHREADS", "GETTHREADID",
    "EXIT", "ABORT", "FLUSH", "SYSTEM", "GETENV", "DATE_AND_TIME",
    "RANDOM_NUMBER", "RANDOM_SEED", "CPU_TIME",
})


class DependencyResolutionError(RuntimeError):
    """A closure could not be resolved; the message names what and where."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _normalise_body(lines: Sequence[str], fixed: bool) -> str:
    """Body text with comments, blank lines and spacing removed, for comparison."""
    out: list[str] = []
    for line in lines:
        if fixed and line[:1] in {"C", "c", "*", "!", "d", "D"}:
            continue
        code = line[:72] if fixed else line
        code = code.split("!", 1)[0] if not fixed else code
        stripped = "".join(code.split()).upper()
        if stripped:
            out.append(stripped)
    return "\n".join(out)


@dataclass(frozen=True)
class RoutineDefinition:
    name: str
    kind: str
    path: Path
    start_line: int
    end_line: int
    body_sha256: str
    fixed_form: bool

    def as_dict(self, *, relative_to: Optional[Path] = None) -> dict:
        path = str(self.path)
        if relative_to is not None:
            try:
                path = str(self.path.relative_to(relative_to))
            except ValueError:
                pass
        return {
            "name": self.name, "kind": self.kind, "path": path,
            "start_line": self.start_line, "end_line": self.end_line,
            "body_sha256": self.body_sha256,
        }

    def text(self) -> str:
        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[self.start_line - 1:self.end_line])


@dataclass(frozen=True)
class MissingDependency:
    symbol: str
    called_by: tuple[str, ...]
    searched_roots: tuple[str, ...]
    near_misses: tuple[str, ...] = ()

    def as_dict(self, *, relative_to: Optional[Path] = None) -> dict:
        roots = []
        for root in self.searched_roots:
            shown = root
            if relative_to is not None:
                try:
                    shown = str(Path(root).relative_to(relative_to))
                except ValueError:
                    pass
            roots.append(shown)
        return {
            "symbol": self.symbol,
            "called_by": list(self.called_by),
            "searched_roots": roots,
            "near_misses": list(self.near_misses),
            "diagnostic": (
                f"{self.symbol} is called by {', '.join(self.called_by)} but no "
                f"source under {len(roots)} searched root(s) defines it"
                + (f"; did you mean {', '.join(self.near_misses)}?"
                   if self.near_misses else "")),
        }

    def _unused(self) -> dict:
        return {
            "symbol": self.symbol,
            "called_by": list(self.called_by),
            "searched_roots": list(self.searched_roots),
            "near_misses": list(self.near_misses),
            "diagnostic": (
                f"{self.symbol} is called by {', '.join(self.called_by)} but no "
                f"source under {len(self.searched_roots)} searched root(s) defines "
                f"it" + (f"; did you mean {', '.join(self.near_misses)}?"
                         if self.near_misses else "")),
        }


@dataclass(frozen=True)
class DuplicateDefinition:
    symbol: str
    definitions: tuple[RoutineDefinition, ...]
    bodies_agree: bool
    #: How the ambiguity was settled. "local" means the entry file defines the
    #: routine itself, so whatever other files contain is irrelevant -- the
    #: compiler would never see them. "identical" means every candidate has the
    #: same body. "ambiguous" means a real choice had to be made between
    #: differing bodies, which can change the numbers and is the only case that
    #: should block.
    resolution: str = "identical"

    @property
    def is_ambiguous(self) -> bool:
        return self.resolution == "ambiguous"

    def as_dict(self, *, relative_to: Optional[Path] = None) -> dict:
        return {
            "symbol": self.symbol,
            "count": len(self.definitions),
            "bodies_agree": self.bodies_agree,
            "distinct_bodies": sorted({d.body_sha256[:16] for d in self.definitions}),
            "definitions": [d.as_dict(relative_to=relative_to)
                            for d in self.definitions[:8]],
            "resolution": self.resolution,
            "note": {
                "local": ("the entry file defines this routine itself, so the "
                          "other definitions are never compiled and cannot "
                          "affect the result"),
                "identical": ("all definitions are textually identical once "
                              "comments and spacing are removed, so the choice "
                              "cannot change the numbers"),
                "ambiguous": ("definitions DIFFER and none is local; choosing one "
                              "would change the numerics, so a donor must be "
                              "selected explicitly"),
            }[self.resolution],
        }


@dataclass
class DependencyGraph:
    entry: str
    entry_path: Path
    resolved: dict[str, RoutineDefinition] = field(default_factory=dict)
    edges: dict[str, tuple[str, ...]] = field(default_factory=dict)
    missing: tuple[MissingDependency, ...] = ()
    duplicates: tuple[DuplicateDefinition, ...] = ()
    runtime_calls: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    searched_roots: tuple[Path, ...] = ()

    @property
    def external_definitions(self) -> tuple[RoutineDefinition, ...]:
        """Resolved routines that live outside the entry file."""
        return tuple(d for d in self.resolved.values() if d.path != self.entry_path)

    @property
    def is_multi_file(self) -> bool:
        return bool(self.external_definitions)

    @property
    def conflicts(self) -> tuple[DuplicateDefinition, ...]:
        """Duplicates that actually forced a numerics-changing choice."""
        return tuple(d for d in self.duplicates if d.is_ambiguous)

    def as_dict(self, *, relative_to: Optional[Path] = None) -> dict:
        def rel(path: Path) -> str:
            if relative_to is not None:
                try:
                    return str(path.relative_to(relative_to))
                except ValueError:
                    pass
            return str(path)

        return {
            "entry": self.entry,
            "entry_path": rel(self.entry_path),
            "multi_file": self.is_multi_file,
            "searched_roots": [rel(r) for r in self.searched_roots],
            "resolved": {name: d.as_dict(relative_to=relative_to)
                         for name, d in sorted(self.resolved.items())},
            "external_files": sorted({rel(d.path) for d in self.external_definitions}),
            "edges": {caller: list(callees)
                      for caller, callees in sorted(self.edges.items())},
            "missing": [m.as_dict(relative_to=relative_to) for m in self.missing],
            "duplicates": [d.as_dict(relative_to=relative_to) for d in self.duplicates],
            "conflicts": [d.symbol for d in self.conflicts],
            "abaqus_runtime_calls": list(self.runtime_calls),
            "includes": list(self.includes),
        }


@dataclass
class SourceIndex:
    """Every routine definition found under the searched roots."""

    definitions: dict[str, list[RoutineDefinition]] = field(default_factory=dict)
    roots: tuple[Path, ...] = ()
    files: tuple[Path, ...] = ()

    def get(self, name: str) -> list[RoutineDefinition]:
        return self.definitions.get(name.upper(), [])


def _definitions_in(path: Path) -> list[RoutineDefinition]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    fixed = path.suffix.lower() in {".for", ".f", ".f77"}
    lines = text.splitlines()
    found: list[RoutineDefinition] = []
    open_definition: Optional[tuple[str, str, int]] = None
    for index, raw in enumerate(lines, start=1):
        if fixed and raw[:1] in {"C", "c", "*", "!"}:
            continue
        if fixed and len(raw) > 5 and raw[5] not in {" ", "0"}:
            continue  # continuation line
        match = _DEF_RE.match(raw)
        if match:
            if open_definition is not None:
                name, kind, start = open_definition
                found.append(_make_definition(name, kind, path, start, index - 1,
                                              lines, fixed))
            name = (match.group("sname") or match.group("fname") or "").upper()
            kind = "subroutine" if match.group("kind") else "function"
            open_definition = (name, kind, index)
            continue
        if open_definition is not None and _END_RE.match(raw):
            name, kind, start = open_definition
            found.append(_make_definition(name, kind, path, start, index, lines, fixed))
            open_definition = None
    if open_definition is not None:
        name, kind, start = open_definition
        found.append(_make_definition(name, kind, path, start, len(lines), lines, fixed))
    return found


def _make_definition(name: str, kind: str, path: Path, start: int, end: int,
                     lines: Sequence[str], fixed: bool) -> RoutineDefinition:
    body = _normalise_body(lines[start - 1:end], fixed)
    return RoutineDefinition(
        name=name, kind=kind, path=path, start_line=start, end_line=end,
        body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        fixed_form=fixed)


def index_sources(roots: Iterable[Path]) -> SourceIndex:
    """Index every Fortran routine definition under ``roots``, deterministically.

    Roots are searched in the order given and files within a root in sorted
    order, so the same inputs always produce the same index and therefore the
    same donor choice.
    """
    index = SourceIndex()
    root_list: list[Path] = []
    files: list[Path] = []
    for root in roots:
        root = Path(root)
        root_list.append(root)
        if root.is_file():
            candidates = [root]
        else:
            candidates = sorted(
                p for p in root.rglob("*")
                if p.is_file() and p.suffix in FORTRAN_SUFFIXES)
        for path in candidates:
            files.append(path)
            for definition in _definitions_in(path):
                index.definitions.setdefault(definition.name, []).append(definition)
    index.roots = tuple(root_list)
    index.files = tuple(files)
    return index


def _statements_of(definition: RoutineDefinition) -> list[str]:
    lines = definition.path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = lines[definition.start_line - 1:definition.end_line]
    if not definition.fixed_form:
        return [line.split("!", 1)[0] for line in body]
    out = []
    for raw in body:
        if raw[:1] in {"C", "c", "*", "!"}:
            continue
        out.append(raw[:72])
    return out


def _referenced_symbols(definition: RoutineDefinition,
                        index: SourceIndex) -> tuple[set[str], set[str], set[str]]:
    """Called subroutines, referenced functions, and include files.

    Function references are resolved only against names the index already knows
    to be functions. Treating every ``NAME(`` as a call would drag in array
    references, which look identical in Fortran.
    """
    calls: set[str] = set()
    functions: set[str] = set()
    includes: set[str] = set()
    for statement in _statements_of(definition):
        for match in _CALL_RE.finditer(statement):
            calls.add(match.group(1).upper())
        include = _INCLUDE_RE.match(statement)
        if include:
            includes.add(include.group(1))
        external = _EXTERNAL_RE.match(statement)
        if external:
            for name in re.split(r"[,\s]+", external.group(1)):
                if name.strip():
                    calls.add(name.strip().upper())
        for candidate in re.finditer(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*\(", statement):
            name = candidate.group(1).upper()
            if name == definition.name:
                continue
            if any(d.kind == "function" for d in index.get(name)):
                functions.add(name)
    return calls, functions, includes


def resolve_closure(entry_path: Path, *, entry: str = "UMAT",
                    roots: Sequence[Path] = ()) -> DependencyGraph:
    """Build the transitive routine closure of ``entry`` across ``roots``.

    The entry file is always searched first and implicitly, so a self-contained
    source resolves with no roots at all and produces an identical result to the
    single-file path.
    """
    entry_path = Path(entry_path)
    search_roots = [entry_path, *[Path(r) for r in roots]]
    index = index_sources(search_roots)

    entry_definitions = [d for d in index.get(entry) if d.path == entry_path]
    if not entry_definitions:
        raise DependencyResolutionError(
            "entry_routine_not_found",
            f"{entry_path} does not define {entry}; it defines "
            f"{', '.join(sorted({d.name for d in _definitions_in(entry_path)})) or 'nothing'}")

    graph = DependencyGraph(entry=entry.upper(), entry_path=entry_path,
                            searched_roots=tuple(Path(r) for r in search_roots))
    graph.resolved[entry.upper()] = entry_definitions[0]

    missing: dict[str, set[str]] = {}
    duplicates: dict[str, DuplicateDefinition] = {}
    runtime: set[str] = set()
    includes: set[str] = set()
    pending = [entry.upper()]
    visited: set[str] = set()

    while pending:
        current = pending.pop(0)
        if current in visited:
            continue
        visited.add(current)
        definition = graph.resolved.get(current)
        if definition is None:
            continue
        calls, functions, found_includes = _referenced_symbols(definition, index)
        includes.update(found_includes)
        callees = sorted(calls | functions)
        graph.edges[current] = tuple(callees)
        for symbol in callees:
            if symbol in graph.resolved or symbol in visited:
                continue
            if symbol in ABAQUS_RUNTIME_ROUTINES:
                runtime.add(symbol)
                continue
            candidates = index.get(symbol)
            if not candidates:
                missing.setdefault(symbol, set()).add(current)
                continue
            # Prefer a definition in the entry file, then the first root that
            # supplies one; within a file, the first definition. Deterministic.
            local = [c for c in candidates if c.path == entry_path]
            chosen = (local or candidates)[0]
            if len(candidates) > 1:
                agree = len({c.body_sha256 for c in candidates}) == 1
                if local:
                    resolution = "local"
                elif agree:
                    resolution = "identical"
                else:
                    resolution = "ambiguous"
                duplicates[symbol] = DuplicateDefinition(
                    symbol=symbol, definitions=tuple(candidates),
                    bodies_agree=agree, resolution=resolution)
            graph.resolved[symbol] = chosen
            pending.append(symbol)

    root_names = [str(r) for r in search_roots]
    known = set(index.definitions)
    graph.missing = tuple(
        MissingDependency(
            symbol=symbol, called_by=tuple(sorted(callers)),
            searched_roots=tuple(root_names),
            near_misses=tuple(sorted(
                name for name in known
                if name != symbol and (name.startswith(symbol[:4])
                                       or symbol.startswith(name[:4])))[:5]))
        for symbol, callers in sorted(missing.items()))
    graph.duplicates = tuple(duplicates[s] for s in sorted(duplicates))
    graph.runtime_calls = tuple(sorted(runtime))
    graph.includes = tuple(sorted(includes))
    return graph


def combined_source(graph: DependencyGraph) -> str:
    """Entry file followed by every external definition its closure needs.

    Definitions already present in the entry file are not repeated, so the
    result compiles as a single translation unit with no duplicate symbols.
    """
    entry_text = graph.entry_path.read_text(encoding="utf-8", errors="replace")
    parts = [entry_text.rstrip("\n")]
    seen_files: set[Path] = {graph.entry_path}
    header = ("C" if graph.entry_path.suffix.lower() in {".for", ".f", ".f77"} else "!")
    for definition in sorted(graph.external_definitions,
                             key=lambda d: (str(d.path), d.start_line)):
        parts.append(
            f"{header}" + "=" * 68 + f"\n{header} {definition.name} resolved from "
            f"{definition.path.name} lines {definition.start_line}-{definition.end_line}\n"
            f"{header}" + "=" * 68)
        parts.append(definition.text().rstrip("\n"))
        seen_files.add(definition.path)
    return "\n".join(parts) + "\n"


_LITERAL_INDEX_RE = re.compile(
    r"(?<![A-Za-z0-9_])(DDSDDE|STRESS|STATEV|STRAN|DSTRAN)\s*\(\s*"
    r"(\d+)\s*(?:,\s*(\d+)\s*)?\)", re.IGNORECASE)
_NTENS_EXPR_RE = re.compile(
    r"(?<![A-Za-z0-9_])STATEV\s*\(\s*(\d+)\s*\*\s*NTENS\s*\+\s*(\d+)\s*\)",
    re.IGNORECASE)
#: DO loops whose upper bound is a literal or "a*NTENS+b". A state block is
#: frequently copied with such a loop rather than by literal subscripts --
#: UMAT_PCL copies its back stress with "DO K1=10,2*NTENS+5" -- so reading only
#: literal subscripts understates NSTATV and the driver allocates too little.
#: The result is a read past the end of the array whose real part happens to be
#: zero, so primal parity passes while the imaginary parts are garbage and the
#: derivatives come back around 1e222.
_DO_BOUND_RE = re.compile(
    r"(?<![A-Za-z0-9_])DO\s+([A-Za-z_]\w*)\s*=\s*[^,]+,\s*"
    r"(?:(\d+)\s*\*\s*NTENS\s*\+\s*(\d+)|(\d+))\s*$",
    re.IGNORECASE)


def infer_minimum_dimensions(sources: Sequence[Path]) -> dict:
    """Smallest NTENS and NSTATV a source can be driven with without corruption.

    A UMAT that writes ``DDSDDE(6,6)`` cannot be run at NTENS=4: the write lands
    outside the array the driver allocated and the process dies inside malloc
    with "double free or corruption", which points nowhere near the cause. That
    is a two-line fact in the source, so it is read rather than guessed.

    ``STATEV(2*NTENS+2)`` is handled symbolically because the bound depends on
    the NTENS finally chosen.
    """
    literal_tens = 0
    literal_statev = 0
    statev_terms: list[tuple[int, int]] = []
    for path in sources:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _LITERAL_INDEX_RE.finditer(text):
            array = match.group(1).upper()
            first = int(match.group(2))
            second = int(match.group(3)) if match.group(3) else 0
            largest = max(first, second)
            if array == "STATEV":
                literal_statev = max(literal_statev, largest)
            else:
                literal_tens = max(literal_tens, largest)
        for match in _NTENS_EXPR_RE.finditer(text):
            statev_terms.append((int(match.group(1)), int(match.group(2))))
        for line in text.splitlines():
            bound = _DO_BOUND_RE.search(line.split("!", 1)[0].rstrip())
            if not bound:
                continue
            variable = bound.group(1)
            # Only count the bound when that loop variable is actually used to
            # index STATEV somewhere in the source.
            if not re.search(rf"STATEV\s*\(\s*{re.escape(variable)}\s*\)",
                             text, re.IGNORECASE):
                continue
            if bound.group(2) is not None:
                statev_terms.append((int(bound.group(2)), int(bound.group(3))))
            elif bound.group(4) is not None:
                literal_statev = max(literal_statev, int(bound.group(4)))

    def statev_for(ntens: int) -> int:
        symbolic = max((a * ntens + b for a, b in statev_terms), default=0)
        return max(symbolic, literal_statev)

    return {
        "minimum_ntens": literal_tens or None,
        "literal_statev_index": literal_statev or None,
        "statev_terms": [f"{a}*NTENS+{b}" for a, b in sorted(set(statev_terms))],
        "minimum_nstatv_for": {str(n): statev_for(n) for n in (3, 4, 6)},
        "note": ("minimum_ntens is the largest literal index written into a "
                 "tensor-shaped argument; driving the source with a smaller "
                 "NTENS writes out of bounds"),
    }
