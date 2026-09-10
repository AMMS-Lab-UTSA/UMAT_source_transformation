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
    # Both prefixes, because ifort honours both: !DIR$ is the Intel spelling
    # and !DEC$ the older Compaq/DEC one that it still accepts. Sources in the
    # wild use each, and reading only the first left three files declaring
    # "!DEC$ FREEFORM" on their first line parsed as fixed form.
    ("!dir$ freeform", "free"),
    ("!dir$ fixedform", "fixed"),
    ("!dec$ freeform", "free"),
    ("!dec$ fixedform", "fixed"),
    ("cdir$ freeform", "free"),
    ("cdir$ fixedform", "fixed"),
    ("cdec$ freeform", "free"),
    ("cdec$ fixedform", "fixed"),
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


#: How many lines of unambiguous evidence settle the form against the suffix.
#: One is not enough: a single line ending in "&" could be inside a string, and
#: a single character in column 6 could be a typo in a comment nobody compiled.
#: Two independent lines saying the same thing is not a typo.
_FORM_EVIDENCE_NEEDED = 2


def form_evidence(text: str) -> dict[str, int]:
    """How many lines of this text can only be one form or the other.

    Free-form evidence, either of which is a syntax error in fixed form:

    * a statement beginning in columns 1-5 with a letter that is not a fixed
      form comment marker -- ``include 'modules.f90'`` in column 1, or
      ``subroutine umat(...`` there;
    * a non-comment line ending in ``&``, which is free form's continuation
      and is nothing at all in fixed form.

    Fixed-form evidence, which is a syntax error in free form:

    * a non-blank, non-zero character in column 6 with columns 1-5 blank or
      numeric, which is fixed form's continuation marker.
    """
    free = fixed = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped[0] in "!":
            continue
        if line[0] in "cC*":                      # a fixed-form comment
            continue
        head, marker = line[:5], line[5:6]
        # A tab in the first six columns makes column counting meaningless:
        # ifort treats a leading tab as "the statement starts here", which is
        # neither a label field nor a continuation marker. Counting such a
        # line as fixed-form evidence read 34 tab-indented statements in
        # UMAT_SSMCWStrainRates_Zambrano.for as continuations, and outvoted
        # the 608 lines that could only be free form.
        if "\t" in line[:6]:
            if line.split("!")[0].rstrip().endswith("&"):
                free += 1
            continue
        if marker.strip() and marker != "0" and (not head.strip()
                                                 or head.strip().isdigit()):
            fixed += 1
            continue
        # Columns 1-5 may hold only a label in fixed form. A letter there is
        # not a label, and the line cannot be fixed form.
        if head.strip() and not head.strip().isdigit():
            free += 1
            continue
        body = line.split("!")[0].rstrip()
        if body.endswith("&"):
            free += 1
    return {"free": free, "fixed": fixed}


def detect_source_form(path: Path, text: str) -> str:
    """Which form this source is written in: declared, then measured, then named.

    The suffix used to decide, and it is the weakest of the three. Eight corpus
    sources are free-form Fortran in a file called ``.f`` or ``.for``:
    ``RafalMichalczyk__PavementDesign/Subroutines/umat_gmaxwell.for`` opens with
    ``subroutine umat(stress,... &`` in column 1. Compiled as fixed form,
    ifort rejects line 1 with "Illegal character in statement label field", the
    compile aborts before the analysis starts, and the job leaves no .sta, no
    .msg and no .odb -- which the ladder reads as the ORIGINAL failing to run.

    Evidence outranks the suffix only when it is unambiguous and repeated; see
    :func:`form_evidence`. Where the two disagree weakly, the suffix stands,
    because 336 of the corpus's 391 sources are fixed form and a rule that
    rescued the handful at the cost of those would be a bad trade.
    """
    declared = declared_source_form(text)
    if declared:
        return declared
    evidence = form_evidence(text)
    if evidence["free"] >= _FORM_EVIDENCE_NEEDED and not evidence["fixed"]:
        return "free"
    if evidence["fixed"] >= _FORM_EVIDENCE_NEEDED and not evidence["free"]:
        return "fixed"
    suffix = path.suffix.lower()
    if suffix in FIXED_FORM_EXTENSIONS:
        return "fixed"
    if suffix in {".f90", ".f95", ".f03", ".f08"}:
        return "free"
    return "fixed" if evidence["fixed"] >= evidence["free"] else "free"


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
