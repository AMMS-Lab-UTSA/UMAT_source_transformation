from __future__ import annotations

from pathlib import Path


FIXED_FORM_EXTENSIONS = {".f", ".for", ".ftn"}


#: Compiler directives that state the source form outright. Intel's ifort --
#: which is what Abaqus uses -- honours these regardless of the file's
#: extension, so a .f file carrying !DIR$ FREEFORM really is free form and the
#: extension is the weaker evidence. Reading it as fixed finds no statements at
#: all: every line begins in column 1, so the whole file looks like a label
#: field. Twenty cached sources were recorded as "not a UMAT" that way while
#: declaring SUBROUTINE UMAT on their sixth line.
_FORM_DIRECTIVES: tuple[tuple[str, str], ...] = (
    ("!dir$ freeform", "free"),
    ("!dir$ fixedform", "fixed"),
    ("cdir$ freeform", "free"),
    ("cdir$ fixedform", "fixed"),
)


def declared_source_form(text: str) -> str | None:
    """The form the file states for itself, or None if it states none.

    Only an explicit directive counts. Guessing from indentation or from a
    line ending in "&" would put the two hundred genuinely fixed-form sources
    at risk to rescue the handful that say what they are.
    """
    for line in text.splitlines()[:40]:
        stripped = line.strip().lower()
        for needle, form in _FORM_DIRECTIVES:
            if stripped.startswith(needle):
                return form
    return None


def detect_source_form(path: Path, text: str) -> str:
    declared = declared_source_form(text)
    if declared:
        return declared
    suffix = path.suffix.lower()
    if suffix in FIXED_FORM_EXTENSIONS:
        return "fixed"
    if suffix in {".f90", ".f95", ".f03", ".f08"}:
        return "free"
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if stripped.endswith("&") or stripped.lower().startswith("subroutine "):
            return "free"
    return "fixed"


def strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "!" and not in_single and not in_double:
            return line[:index]
    return line
