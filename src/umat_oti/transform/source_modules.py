"""Modules a source defines for itself, carried into a lifted build.

``AlexanderJFDR/NeoHookean_umat.for`` opens with ``module NumKind`` -- three
kind parameters -- and its UMAT says ``use NumKind``. The lifted build wrote
the UMAT and its helper closure into ``umat_oti_lifted.f90`` and nothing else,
so ``use NumKind`` named a module that did not exist there and the lifted
build did not compile (Gauss, B1 F4).

A module the source defines is part of the source. :func:`modules_used_by`
finds the ones a set of lifted routines USE (transitively), and
:func:`module_text` writes each one out in free form, unchanged in content, so
it compiles in front of the lifted module. The original module is emitted
REAL as the author wrote it: its procedures, if any, keep their real
interfaces, and the lifted closure calls lifted copies of whatever it
differentiates through, so the two do not meet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

_MODULE_OPEN = re.compile(r"^\s*MODULE\s+(?!PROCEDURE\b)([A-Za-z_]\w*)\s*(?:!.*)?$", re.IGNORECASE)
_MODULE_CLOSE = re.compile(r"^\s*END\s*MODULE\b", re.IGNORECASE)
_END_BARE = re.compile(r"^\s*END\s*$", re.IGNORECASE)
_USE = re.compile(r"^\s*USE\b\s*(?:,\s*(?:NON_)?INTRINSIC\s*)?(?:::)?\s*([A-Za-z_]\w*)", re.IGNORECASE)


@dataclass
class SourceModule:
    name: str
    statements: list[str] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)
    first_line: int = 0


def source_modules(logical_lines: Sequence) -> dict[str, SourceModule]:
    """Every ``MODULE name ... END MODULE`` in the source, by upper-case name."""
    modules: dict[str, SourceModule] = {}
    current: SourceModule | None = None
    for line in logical_lines:
        text = line.text.strip()
        if current is None:
            match = _MODULE_OPEN.match(text)
            if match:
                current = SourceModule(match.group(1).upper(), [text], [],
                                       line.line_numbers[0] if line.line_numbers else 0)
            continue
        current.statements.append(text)
        use = _USE.match(text)
        if use:
            current.uses.append(use.group(1).upper())
        if _MODULE_CLOSE.match(text):
            modules.setdefault(current.name, current)
            current = None
    return modules


def modules_used_by(routine_lines: Iterable[Sequence], modules: dict[str, SourceModule]) -> list[str]:
    """Source-defined modules the given routines USE, dependencies first."""
    wanted: list[str] = []
    for lines in routine_lines:
        for line in lines:
            use = _USE.match(getattr(line, "text", str(line)).strip())
            if use and use.group(1).upper() in modules:
                wanted.append(use.group(1).upper())
    ordered: list[str] = []

    def visit(name: str, trail: tuple[str, ...] = ()) -> None:
        if name in ordered or name in trail or name not in modules:
            return
        for dependency in modules[name].uses:
            visit(dependency, trail + (name,))
        ordered.append(name)

    for name in wanted:
        visit(name)
    return ordered


def module_text(module: SourceModule) -> str:
    """The module as free-form Fortran, one logical statement per line."""
    from umat_oti.transform.helper_lifting import wrap_free_form

    body = "\n".join(module.statements) + "\n"
    return wrap_free_form(body)
