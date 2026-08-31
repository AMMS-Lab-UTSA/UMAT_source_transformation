from __future__ import annotations

import re

from umat_oti.core.model import CallSite, FortranLogicalLine, UnsupportedFeature


UNSUPPORTED_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("common_block", r"^\s*common\b", "COMMON blocks are not supported in the MVP transformer."),
    ("equivalence", r"^\s*equivalence\b", "EQUIVALENCE storage aliasing is not supported."),
    ("save", r"^\s*save\b", "SAVE state is not supported by deterministic material point validation."),
    ("data", r"^\s*data\b", "DATA initialization is not rewritten for OTIS shadow variables."),
    ("io_open", r"^\s*open\b", "Runtime file I/O is not supported in transformed UMAT kernels."),
    ("io_read", r"^\s*read\b", "Runtime input I/O is not supported in transformed UMAT kernels."),
    ("io_write", r"^\s*write\b", "Runtime output I/O is not supported in transformed UMAT kernels."),
    # A USE brings in derived types, generic interfaces and defined operators
    # from a file the transformer never reads, and every one of them reads as
    # NAME(...) at the point of use -- identical to indexing an array. Declared
    # here so the limitation is stated where the others are, instead of
    # surfacing downstream as a promoted variable with no confirmed shape.
    ("module_use", r"^\s*use\s+[A-Za-z_]\w*\s*(?:,|::|$)",
     "Names imported from a Fortran module are not resolved by the transformer."),
)
def _commented_line_numbers(source_text: str, form: str = "fixed") -> frozenset[int]:
    """Physical lines that are comments, in either source form.

    The logical lines these patterns are matched against have already had the
    comment marker removed, so a note the author wrote is indistinguishable
    from a statement by the time it arrives. That is not a small difference:

        \t\t\t!I use Newton-Raphson to retrieve the initial state parameters

    reaches the matcher as text beginning "use ", and a source containing no
    USE statement anywhere was reported as importing from a module. Every
    pattern here has the same exposure -- a commented-out DATA, COMMON or
    WRITE is not a construct the source uses.
    """
    numbers: set[int] = set()
    for number, raw in enumerate(source_text.splitlines(), start=1):
        stripped = raw.lstrip()
        if not stripped:
            continue
        if stripped.startswith("!"):
            numbers.add(number)
            continue
        # The column-1 marker is a fixed-form rule and only a fixed-form rule:
        # no statement may begin before column 7 there, so a letter in column 1
        # can only be a comment. In free form the same line is ordinary code --
        # "c = 1.0" assigns to a variable named c -- so applying the rule to
        # both forms would silently discard statements.
        if form == "fixed" and raw[:1] in ("c", "C", "*", "d", "D"):
            numbers.add(number)
    return frozenset(numbers)


def scan_unsupported_features(
    logical_lines: tuple[FortranLogicalLine, ...], call_sites: tuple[CallSite, ...],
    source_text: str = "", form: str = "fixed",
) -> tuple[UnsupportedFeature, ...]:
    features: list[UnsupportedFeature] = []
    commented = (_commented_line_numbers(source_text, form) if source_text
                 else frozenset())
    for line in logical_lines:
        if commented and line.line_numbers and line.line_numbers[0] in commented:
            continue
        text = line.text.strip()
        for code, pattern, message in UNSUPPORTED_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                features.append(UnsupportedFeature(code, message, "error", line.line_numbers))
        if re.search(r"\bif\s*\(.*\bdstran\b", text, flags=re.IGNORECASE):
            features.append(
                UnsupportedFeature(
                    "active_dstran_branch",
                    "Branch conditions depending directly on DSTRAN are not supported in the MVP.",
                    "warning",
                    line.line_numbers,
                )
            )
    if source_text:
        local = _modules_defined_here(source_text)
        if local:
            features = [f for f in features
                        if f.code != "module_use"
                        or not _use_names_only(f, logical_lines) <= local]
    return tuple(features)


def _modules_defined_here(source_text: str) -> frozenset[str]:
    """Modules this file defines, so a USE of one is resolvable in front of us."""
    return frozenset(
        match.group(1).upper()
        for match in re.finditer(r"^\s*module\s+([A-Za-z_]\w*)\s*$", source_text,
                                 flags=re.IGNORECASE | re.MULTILINE))


def _use_names_only(feature: "UnsupportedFeature",
                    logical_lines: tuple[FortranLogicalLine, ...]) -> frozenset[str]:
    """The module names the USE statements behind this feature import."""
    wanted = set(feature.line_numbers or ())
    names: set[str] = set()
    for line in logical_lines:
        if not wanted & set(line.line_numbers or ()):
            continue
        match = re.match(r"^\s*use\s+([A-Za-z_]\w*)", line.text.strip(),
                         flags=re.IGNORECASE)
        if match:
            names.add(match.group(1).upper())
    return frozenset(names)


def unsupported_report(features: tuple[UnsupportedFeature, ...]) -> dict[str, object]:
    return {
        "features": [feature.to_json() for feature in features],
        "has_errors": any(feature.severity == "error" for feature in features),
        "schema_version": 1,
    }
