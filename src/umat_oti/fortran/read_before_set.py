"""Locals a routine can read before it has assigned them.

A local that is read on some path before any statement has given it a value
holds whatever the stack held: Abaqus compiles user subroutines with ``-auto``,
so such a read is undefined behaviour, and the build flags decide what it
returns (``-init=zero`` makes it 0, the default leaves it to chance). A plasticity
UMAT that sets its plastic-strain increment only inside its Newton loop and adds it
to the state on every call is the example this module was written for: in an
elastic increment the state receives whatever was in that memory.

The analysis is a forward "definitely assigned" data flow over the routine's
executable statements:

* the control flow graph follows IF/ELSE IF/ELSE, block and labelled DO (a
  DO body may run zero times), DO WHILE, SELECT CASE, EXIT, CYCLE, GO TO,
  computed GO TO, arithmetic IF, RETURN and STOP;
* a name is assigned by an assignment to it (an array by an assignment to
  any element), by being a DO variable, by a READ, or by being passed as a
  bare actual argument to a CALL (the callee may set it); a counted DO with
  literal bounds runs its body at least once;
* a read is any other appearance in an executable statement;
* a scalar is reported when SOME path reaches a read without assigning it;
  an array only when NO path to the read assigns any element of it (element
  assignments in loops whose trip count is only known at run time would
  otherwise be reported everywhere).

The candidates are the routine's own locals: dummy arguments, PARAMETERs,
COMMON, SAVE, DATA, EQUIVALENCE, initialised, ALLOCATABLE and POINTER names
are excluded, and so is every name when a bare ``SAVE`` makes all locals
static (a value carried between calls is the point there, and starting it at
zero would change what the routine computes). An undeclared name counts only
when the routine's implicit typing is fully known and it USEs no module.

What a finding is used for: the generated code starts each initialisable
finding at zero at the routine's entry (before its first executable statement),
explicitly, so the generated code's behaviour does not depend on build flags,
and the transform report names every finding.

What it does NOT do -- it is not a proof that every undefined read is found:

* a bare actual argument of a CALL counts as assigned by the callee, so a
  read of an input the callee needs set is not reported;
* an array is reported only when no element can have been assigned (above);
* an undeclared name nothing in the routine assigns is reported but not
  started at zero (it may be a misspelt variable, or a name this reader took
  for one);
* only the selected routine is analysed, not the helpers it calls;
* an ENTRY statement, an assigned GO TO or a jump to a label that is not found
  stops it (``undecided``), and nothing is reported then.

So the generated code computes what the original computes under
``-init=zero`` for the locals reported and started at zero, and only for them;
a read the analysis does not see remains as undefined as in the original.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from umat_oti.core.model import FortranLogicalLine
from umat_oti.fortran.normalize import detect_source_form, strip_inline_comment
from umat_oti.fortran.parser import (
    logical_lines_from_text,
    parse_declaration_line,
    parse_subroutines,
    split_top_level,
)

#: The literal each type starts at. Whole-variable assignment, so arrays of
#: any rank (and the OTI type, whose assignment from a REAL is elemental) take
#: the same statement.
ZERO_LITERAL = {
    "real": "0.0D0",
    "integer": "0",
    "logical": ".FALSE.",
    "complex": "(0.0D0, 0.0D0)",
    "character": "' '",
}

_SPEC_KEYWORDS = re.compile(
    r"^(IMPLICIT|DIMENSION|PARAMETER|COMMON|SAVE|DATA|EQUIVALENCE|EXTERNAL|INTRINSIC|"
    r"INCLUDE|USE|IMPORT|INTERFACE|END\s*INTERFACE|PROCEDURE|ALLOCATABLE|POINTER|TARGET|"
    r"OPTIONAL|INTENT|VALUE|VOLATILE|ASYNCHRONOUS|PROTECTED|PUBLIC|PRIVATE|NAMELIST|FORMAT|"
    r"SEQUENCE|CHARACTER|INTEGER|LOGICAL|REAL|DOUBLE\s*PRECISION|DOUBLE\s*COMPLEX|COMPLEX|"
    r"BYTE)\b")
_TYPE_DECL = re.compile(r"^(TYPE|CLASS)\s*(\(|::|,)")
_DOT_OPERATOR = re.compile(r"\.(?:EQ|NE|LT|LE|GT|GE|AND|OR|NOT|EQV|NEQV|XOR|TRUE|FALSE)\.(?:_\w+)?",
                           re.IGNORECASE)
_NUMBER = re.compile(r"(?<![A-Za-z_0-9])(?:\d+\.?\d*|\.\d+)(?:[EeDdQq][+-]?\d+)?(?:_\w+)?")
_NAME = re.compile(r"[A-Za-z_]\w*")
_IO_DEF_SPECIFIERS = {"IOSTAT", "IOMSG", "SIZE", "NUMBER", "EXIST", "OPENED", "NAMED", "NEXTREC"}


@dataclass(frozen=True)
class ReadBeforeSet:
    """One local that can be read before it is assigned."""

    name: str
    #: First physical line of the first statement that may read it unset.
    line: int
    #: First physical line of every such statement.
    lines: tuple[int, ...]
    #: real, integer, logical, complex, character or unknown.
    type: str
    rank: str
    #: Whether the generated code can start it at zero (its type is known).
    initialisable: bool
    why_not: str = ""

    def zero_statement(self, name: Optional[str] = None, literal: Optional[str] = None) -> str:
        return f"{name or self.name} = {literal or ZERO_LITERAL[self.type]}"

    def as_dict(self) -> dict:
        return {"name": self.name, "line": self.line, "lines": list(self.lines),
                "type": self.type, "rank": self.rank, "initialisable": self.initialisable,
                **({"why_not": self.why_not} if self.why_not else {})}

    def sentence(self, routine: str = "UMAT") -> str:
        where = ", ".join(str(n) for n in self.lines)
        if self.initialisable:
            return (f"{self.name} can be read before it is assigned in {routine} "
                    f"(line{'s' if len(self.lines) > 1 else ''} {where} of the source): on such a "
                    f"path the original reads an undefined value, so its result there depends on "
                    f"the compiler and its flags. The generated code starts {self.name} at "
                    f"{ZERO_LITERAL[self.type]} on entry, which is what the original computes when "
                    f"its locals start at zero (-init=zero, -finit-local-zero).")
        return (f"{self.name} can be read before it is assigned in {routine} (line"
                f"{'s' if len(self.lines) > 1 else ''} {where} of the source); it is not "
                f"initialised in the generated code because {self.why_not}.")


@dataclass
class Analysis:
    routine: str = "UMAT"
    findings: list = field(default_factory=list)
    #: Why the analysis could not decide, or "" when it did.
    undecided: str = ""
    #: Physical line before which entry statements go (the first executable
    #: statement of the routine), 0 when there is none.
    first_executable_line: int = 0

    def as_dict(self) -> dict:
        return {"routine": self.routine, "decided": not self.undecided,
                **({"undecided": self.undecided} if self.undecided else {}),
                "findings": [f.as_dict() for f in self.findings],
                "rule": ("forward data flow over the routine's executable statements: a scalar "
                         "is reported when some path reaches a read without assigning it, an "
                         "array when no path to the read assigns any element of it; a bare "
                         "actual argument of a CALL counts as assigned by the callee")}

    def warnings(self) -> list:
        return [f.sentence(self.routine) for f in self.findings]

    @property
    def initialisable(self) -> list:
        return [f for f in self.findings if f.initialisable]


# ----------------------------------------------------------------------------- text helpers

def _blank_strings(text: str) -> str:
    out, quote = [], ""
    for char in text:
        if quote:
            out.append(quote if char == quote else " ")
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            out.append(char)
        else:
            out.append(char)
    return "".join(out)


def _matching_paren(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _top_level_equals(text: str) -> int:
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "=" and depth == 0:
            before = text[index - 1] if index else ""
            after = text[index + 1] if index + 1 < len(text) else ""
            if before in "=<>/" or after in "=>":
                continue
            return index
    return -1


#: Intrinsics that ask about a variable without reading its value: SHAPE(A)
#: in ``A = RESHAPE((/.../), SHAPE(A))`` is not a read of A.
_INQUIRY = re.compile(
    r"\b(SHAPE|SIZE|LBOUND|UBOUND|KIND|LEN|ALLOCATED|PRESENT|ASSOCIATED|RANK|DIGITS|EPSILON|"
    r"HUGE|TINY|PRECISION|RANGE|RADIX|MAXEXPONENT|MINEXPONENT|BIT_SIZE|STORAGE_SIZE)"
    r"\s*\(\s*[A-Za-z_]\w*", re.IGNORECASE)


def _names(expression: str) -> list:
    """(NAME, followed_by_paren) for every identifier an expression mentions.

    Keyword arguments (``KIND=8``), derived-type components (``A%B``) and the
    variable an inquiry intrinsic asks about (``SHAPE(A)``) are not reads of a
    variable and are left out.
    """
    text = _INQUIRY.sub(lambda m: m.group(1) + "(", expression)
    text = _DOT_OPERATOR.sub(" ", text)
    text = _NUMBER.sub(" ", text)
    found = []
    for match in _NAME.finditer(text):
        start, end = match.span()
        before = text[:start].rstrip()
        if before.endswith("%"):
            continue
        rest = text[end:].lstrip()
        if rest.startswith("=") and not rest.startswith("=="):
            continue
        found.append((match.group(0).upper(), rest.startswith("(")))
    return found


def _read_names(expression: str) -> set:
    return {name for name, _ in _names(expression)}


def _lhs_parts(lhs: str) -> tuple[str, str]:
    """The variable an assignment target names, and the text of its subscripts."""
    lhs = lhs.strip()
    match = re.match(r"^([A-Za-z_]\w*)\s*(.*)$", lhs)
    if not match:
        return "", lhs
    return match.group(1).upper(), match.group(2)


# ----------------------------------------------------------------------------- statements

@dataclass
class _Stmt:
    kind: str
    line: int
    label: str = ""
    reads: set = field(default_factory=set)
    defs: set = field(default_factory=set)
    labels: tuple = ()
    name: str = ""                  # construct name, DO terminal label, EXIT/CYCLE target
    inner: Optional["_Stmt"] = None
    bare: bool = False              # DO without control, SAVE without a list
    #: A counted DO whose literal bounds make the body run at least once.
    trips_at_least_once: bool = False


def _io_lists(head: str, rest: str, *, reading: bool) -> tuple[set, set]:
    reads, defs = set(), set()
    for item in split_top_level(head):
        spec = re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*(.*)$", item)
        if spec and spec.group(1).upper() in _IO_DEF_SPECIFIERS:
            defs |= _read_names(spec.group(2))
        elif spec:
            reads |= _read_names(spec.group(2))
        else:
            reads |= _read_names(item)
    for item in split_top_level(rest):
        item = item.strip()
        if reading:
            implied = re.match(r"^\((.*),\s*([A-Za-z_]\w*)\s*=\s*(.*)\)$", item)
            if implied:
                defs.add(implied.group(2).upper())
                for inner in split_top_level(implied.group(1)):
                    name, subscripts = _lhs_parts(inner)
                    if name:
                        defs.add(name)
                        reads |= _read_names(subscripts)
                continue
            name, subscripts = _lhs_parts(item)
            if name:
                defs.add(name)
                reads |= _read_names(subscripts)
        else:
            implied = re.match(r"^\((.*),\s*([A-Za-z_]\w*)\s*=\s*(.*)\)$", item)
            if implied:
                defs.add(implied.group(2).upper())
                reads |= _read_names(implied.group(1)) | _read_names(implied.group(3))
                reads.discard(implied.group(2).upper())
            else:
                reads |= _read_names(item)
    return reads, defs


def _classify(text: str, line: int, label: str) -> _Stmt:
    """One executable statement (upper case, strings blanked)."""
    construct = re.match(r"^([A-Z_]\w*)\s*:\s*(?!:)(.*)$", text)
    name = ""
    if construct and re.match(r"^(DO|IF|SELECT|BLOCK|ASSOCIATE|WHERE|FORALL)\b", construct.group(2)):
        name, text = construct.group(1), construct.group(2)
    statement = _Stmt("other", line, label, name=name)

    if re.match(r"^IF\s*\(", text):
        close = _matching_paren(text, text.index("("))
        condition, rest = text[text.index("(") + 1:close], text[close + 1:].strip()
        if rest == "THEN":
            return _Stmt("if_then", line, label, reads=_read_names(condition), name=name)
        if re.match(r"^\d+\s*,\s*\d+(\s*,\s*\d+)?$", rest):
            return _Stmt("arith_if", line, label, reads=_read_names(condition),
                         labels=tuple(x.strip() for x in rest.split(",")))
        inner = _classify(rest, line, "")
        return _Stmt("logical_if", line, label, reads=_read_names(condition), inner=inner)
    if re.match(r"^ELSE\s*IF\s*\(", text):
        start = text.index("(")
        close = _matching_paren(text, start)
        return _Stmt("else_if", line, label, reads=_read_names(text[start + 1:close]))
    if re.match(r"^ELSE(\s+[A-Z_]\w*)?$", text):
        return _Stmt("else", line, label)
    if re.match(r"^END\s*IF\b", text):
        return _Stmt("end_if", line, label)
    if re.match(r"^SELECT\s*CASE\s*\(", text):
        start = text.index("(")
        return _Stmt("select", line, label, reads=_read_names(text[start + 1:_matching_paren(text, start)]),
                     name=name)
    if re.match(r"^CASE\s*(\(|DEFAULT\b)", text):
        return _Stmt("case", line, label, bare=bool(re.match(r"^CASE\s*DEFAULT\b", text)))
    if re.match(r"^END\s*SELECT\b", text):
        return _Stmt("end_select", line, label)
    if re.match(r"^END\s*DO\b", text):
        return _Stmt("end_do", line, label)
    do = re.match(r"^DO\b\s*(\d+)?\s*,?\s*(.*)$", text)
    if do and (not do.group(2) or re.match(r"^(WHILE\s*\(|[A-Z_]\w*\s*=)", do.group(2))):
        terminal, control = do.group(1) or "", do.group(2)
        if not control:
            return _Stmt("do", line, label, labels=(terminal,), name=name, bare=True)
        if control.startswith("WHILE"):
            start = control.index("(")
            return _Stmt("do", line, label, labels=(terminal,), name=name,
                         reads=_read_names(control[start + 1:_matching_paren(control, start)]))
        variable, bounds = control.split("=", 1)
        parts = [p.strip() for p in split_top_level(bounds)]
        literal = all(re.fullmatch(r"[+-]?\d+", p) for p in parts) and len(parts) in (2, 3)
        once = bool(literal and int(parts[2] if len(parts) == 3 else "1") != 0 and (
            (int(parts[1]) - int(parts[0])) * (1 if int(parts[2] if len(parts) == 3 else "1") > 0 else -1) >= 0))
        return _Stmt("do", line, label, labels=(terminal,), name=name,
                     reads=_read_names(bounds), defs={variable.strip().upper()},
                     trips_at_least_once=once)
    if re.match(r"^(EXIT|CYCLE)\b", text):
        kind, target = (text.split() + [""])[:2]
        return _Stmt(kind.lower(), line, label, name=target)
    goto = re.match(r"^GO\s*TO\s*(.*)$", text)
    if goto:
        target = goto.group(1).strip()
        if re.fullmatch(r"\d+", target):
            return _Stmt("goto", line, label, labels=(target,))
        computed = re.match(r"^\(([\d\s,]+)\)\s*,?\s*(.*)$", target)
        if computed:
            return _Stmt("computed_goto", line, label,
                         labels=tuple(x.strip() for x in computed.group(1).split(",") if x.strip()),
                         reads=_read_names(computed.group(2)))
        return _Stmt("undecidable", line, label, name="an assigned GO TO")
    if re.match(r"^(RETURN|STOP|ERROR\s+STOP)\b", text):
        return _Stmt("return", line, label, reads=_read_names(re.sub(r"^(RETURN|STOP|ERROR\s+STOP)", "", text)))
    if re.match(r"^ENTRY\b", text):
        return _Stmt("undecidable", line, label, name="an ENTRY statement")
    if re.match(r"^CONTINUE$", text):
        return _Stmt("pass", line, label)
    call = re.match(r"^CALL\s+([A-Z_]\w*)\s*(\((.*)\))?\s*$", text)
    if call:
        reads, defs = set(), set()
        for argument in split_top_level(call.group(3) or ""):
            argument = argument.strip()
            keyword = re.match(r"^[A-Z_]\w*\s*=(?!=)\s*(.*)$", argument)
            if keyword:
                argument = keyword.group(1).strip()
            whole = re.match(r"^([A-Z_]\w*)\s*(\(.*\))?$", argument)
            if whole and (whole.group(2) is None or _matching_paren(whole.group(2), 0) == len(whole.group(2)) - 1):
                defs.add(whole.group(1))
                reads |= _read_names(whole.group(2) or "")
            else:
                reads |= _read_names(argument)
        return _Stmt("assign", line, label, reads=reads, defs=defs)
    io = re.match(r"^(WRITE|READ)\s*\(", text)
    if io:
        start = text.index("(")
        close = _matching_paren(text, start)
        reads, defs = _io_lists(text[start + 1:close], text[close + 1:].strip(), reading=io.group(1) == "READ")
        return _Stmt("assign", line, label, reads=reads, defs=defs)
    printed = re.match(r"^(PRINT|READ)\s+([^,]+)\s*(,(.*))?$", text)
    if printed:
        reads, defs = _io_lists(printed.group(2), printed.group(4) or "", reading=printed.group(1) == "READ")
        return _Stmt("assign", line, label, reads=reads, defs=defs)
    if re.match(r"^(OPEN|CLOSE|INQUIRE|REWIND|BACKSPACE|ENDFILE|FLUSH|ALLOCATE|DEALLOCATE|NULLIFY|WAIT)\b",
                text):
        return _Stmt("assign", line, label, defs=_read_names(text) - {text.split("(")[0].strip()})
    if re.match(r"^(END\s*WHERE|ELSE\s*WHERE|END\s*FORALL|END\s*BLOCK|END\s*ASSOCIATE|BLOCK|ASSOCIATE)\b", text):
        return _Stmt("pass", line, label)
    where = re.match(r"^(WHERE|FORALL)\s*\(", text)
    if where:
        start = text.index("(")
        close = _matching_paren(text, start)
        rest = text[close + 1:].strip()
        reads = _read_names(text[start + 1:close])
        # FORALL (I=1:N, J=1:N, mask): I and J are the construct's own indices
        indices = set(re.findall(r"(?:^|,)\s*([A-Z_]\w*)\s*=(?!=)", text[start + 1:close])) \
            if where.group(1) == "FORALL" else set()
        if rest:
            inner = _classify(rest, line, "")
            return _Stmt("assign", line, label, reads=(reads | inner.reads) - indices,
                         defs=inner.defs | indices)
        return _Stmt("pass", line, label, reads=reads - indices, defs=indices)
    equals = _top_level_equals(text)
    if equals > 0:
        lhs, rhs = text[:equals], text[equals + 1:]
        if rhs.startswith(">"):
            rhs = rhs[1:]
        target, subscripts = _lhs_parts(lhs)
        if target:
            return _Stmt("assign", line, label, reads=_read_names(subscripts) | _read_names(rhs), defs={target})
    # Anything else (an unrecognised statement): counted as assigning every name
    # it mentions, so it can neither hide nor invent a finding by itself.
    return _Stmt("assign", line, label, defs=_read_names(text))


# ----------------------------------------------------------------------------- the routine

@dataclass
class _Routine:
    name: str
    args: set
    statements: list
    declared: dict           # NAME -> (kind, rank)
    excluded: set
    all_saved: bool
    uses_module: bool
    other_includes: list
    statement_functions: set
    first_executable_line: int
    undecided: str = ""


def _split_statements(line: FortranLogicalLine, raw_lines: Sequence[str], form: str) -> list:
    """(label, text) of each statement on one logical line; ``;`` separates."""
    text = line.text
    label = ""
    if form == "fixed":
        raw = raw_lines[line.line_numbers[0] - 1] if line.line_numbers else ""
        field_text = raw.replace("\t", " ")[:5].strip()
        if field_text.isdigit():
            label = str(int(field_text))
    else:
        match = re.match(r"^(\d+)\s+(.*)$", text)
        if match:
            label, text = str(int(match.group(1))), match.group(2)
    blanked = _blank_strings(text)
    pieces, start, depth = [], 0, 0
    for index, char in enumerate(blanked):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth == 0:
            pieces.append(blanked[start:index])
            start = index + 1
    pieces.append(blanked[start:])
    result = []
    for number, piece in enumerate(p.strip() for p in pieces):
        if piece:
            result.append((label if number == 0 else "", piece.upper()))
    return result


def _is_specification(text: str) -> bool:
    """A specification statement, not an assignment to a variable that happens
    to be called VALUE, DATA or TARGET."""
    if not (_SPEC_KEYWORDS.match(text) or _TYPE_DECL.match(text)):
        return False
    equals = _top_level_equals(text)
    if equals > 0 and re.fullmatch(r"\s*[A-Z_]\w*\s*(\(.*\))?\s*", text[:equals]):
        return False
    return True


#: Words an expression can carry that are not variable names.
_NOT_VARIABLES = frozenset({"THEN", "KIND", "LEN", "NPRECD"})

#: Statement keywords that are followed by a parenthesis: ``IF (C) X = 1`` has a
#: top-level ``=`` and starts with ``NAME(``, and it is not a definition.
_KEYWORDS_WITH_PARENS = frozenset({
    "IF", "ELSEIF", "WHERE", "FORALL", "CALL", "DO", "DOWHILE", "WHILE", "READ", "WRITE", "PRINT",
    "SELECT", "SELECTCASE", "CASE", "ALLOCATE", "DEALLOCATE", "NULLIFY", "OPEN", "CLOSE", "INQUIRE",
    "REWIND", "BACKSPACE", "ENDFILE", "FLUSH", "WAIT", "GO", "GOTO", "RETURN", "STOP", "ASSOCIATE",
    "BLOCK", "FORMAT", "ENTRY", "DATA"})


def _is_statement_function(statement: str, declared: dict, args: set) -> bool:
    """``F(X, Y) = expression``: the whole left side is one name and a list of dummy
    names, the name is neither a declared array nor an argument nor a keyword."""
    equals = _top_level_equals(statement)
    if equals <= 0:
        return False
    target = re.fullmatch(r"\s*([A-Z_]\w*)\s*\((.*)\)\s*", statement[:equals])
    if not target:
        return False
    name, inside = target.group(1), target.group(2)
    if name in _KEYWORDS_WITH_PARENS or name in args:
        return False
    if declared.get(name, ("", "scalar"))[1] == "array":
        return False
    if _matching_paren(statement, statement.index("(")) != statement[:equals].rstrip().rfind(")"):
        return False
    dummies = [item.strip() for item in split_top_level(inside)]
    return bool(dummies) and all(re.fullmatch(r"[A-Z_]\w*", item) for item in dummies)


def _names_in_list(text: str) -> set:
    names = set()
    for item in split_top_level(text):
        match = re.match(r"^\s*/?\s*([A-Za-z_]\w*)", item)
        if match:
            names.add(match.group(1).upper())
    return names


def _read_routine(text: str, routine: str, form: str) -> Optional[_Routine]:
    logical = logical_lines_from_text(text, form)
    found = next((r for r in parse_subroutines(logical) if r.upper_name == routine.upper()), None)
    if found is None:
        return None
    raw_lines = text.splitlines()
    args = {a.upper() for a in found.args}
    declared: dict = {}
    excluded: set = set()
    statement_functions: set = set()
    all_saved = uses_module = False
    other_includes: list = []
    statements: list = []
    in_spec = True
    interface_depth = 0
    first_executable = 0
    referenced: set = set()          # names written NAME(...) in executable statements
    contained = False
    for line in found.lines[1:]:
        if contained:
            break
        for label, statement in _split_statements(line, raw_lines, form):
            if re.match(r"^END(\s*SUBROUTINE\b.*)?$", statement):
                continue
            if re.match(r"^(ABSTRACT\s+)?INTERFACE\b", statement):
                interface_depth += 1
                continue
            if re.match(r"^END\s*INTERFACE\b", statement):
                interface_depth = max(interface_depth - 1, 0)
                continue
            if interface_depth:
                continue
            if re.match(r"^CONTAINS$", statement):
                # internal procedures are other scoping units
                contained = True
                break
            if _is_specification(statement):
                original = line.text if len(line.line_numbers) else statement
                declaration = parse_declaration_line(FortranLogicalLine(statement, line.line_numbers))
                if declaration is not None:
                    attributes = {a.strip().upper().split("(")[0] for a in declaration.attributes}
                    old_style_data = "::" not in statement and "/" in re.sub(r"\([^()]*\)", "", statement)
                    for entity in declaration.entities:
                        entity_name = re.match(r"[A-Za-z_]\w*", entity.name)
                        if not entity_name:
                            continue
                        upper = entity_name.group(0).upper()
                        rank = "array" if (entity.dimensions or "DIMENSION" in attributes) else "scalar"
                        previous = declared.get(upper, ("", "scalar"))
                        declared[upper] = (declaration.kind,
                                           "array" if "array" in (rank, previous[1]) else "scalar")
                        if (entity.initializer is not None or old_style_data
                                or attributes & {"SAVE", "PARAMETER", "ALLOCATABLE", "POINTER",
                                                 "EXTERNAL", "INTRINSIC"}):
                            excluded.add(upper)
                    continue
                keyword = re.match(r"^(\w+(?:\s*PRECISION)?)", statement).group(1)
                body = statement[len(keyword):].strip()
                if keyword == "DIMENSION":
                    for item in split_top_level(body):
                        match = re.match(r"^\s*([A-Za-z_]\w*)", item)
                        if match:
                            upper = match.group(1).upper()
                            declared[upper] = (declared.get(upper, ("", ""))[0], "array")
                elif keyword == "PARAMETER":
                    inner = body.strip()
                    if inner.startswith("("):
                        inner = inner[1:_matching_paren(inner, 0)]
                    excluded |= {item.split("=")[0].strip().upper() for item in split_top_level(inner)}
                elif keyword == "COMMON":
                    excluded |= _names_in_list(re.sub(r"/\s*\w*\s*/", ",", body))
                elif keyword == "SAVE":
                    if not body:
                        all_saved = True
                    excluded |= _names_in_list(body.replace("::", ""))
                elif keyword == "DATA":
                    for group in re.findall(r"([^/]+)/[^/]*/", body):
                        excluded |= _names_in_list(group.strip().strip(","))
                elif keyword == "EQUIVALENCE":
                    excluded |= _read_names(body)
                elif keyword in ("EXTERNAL", "INTRINSIC", "ALLOCATABLE", "POINTER", "TARGET",
                                 "NAMELIST", "VOLATILE"):
                    excluded |= _read_names(body.replace("::", " "))
                elif keyword == "USE":
                    uses_module = True
                elif keyword == "INCLUDE":
                    included = re.search(r"['\"]([^'\"]+)['\"]", original)
                    if included and included.group(1).strip().upper() != "ABA_PARAM.INC":
                        other_includes.append(included.group(1).strip())
                continue
            # An assignment to NAME(args) in the specification part, NAME not an
            # array, is a statement function definition.
            if in_spec and _is_statement_function(statement, declared, args):
                statement_functions.add(re.match(r"^([A-Z_]\w*)", statement).group(1))
                continue
            in_spec = False
            if not first_executable:
                first_executable = line.line_numbers[0] if line.line_numbers else 0
            if re.match(r"^FORMAT\s*\(", statement):
                continue
            referenced |= {name for name, call in _names(statement) if call}
            statements.append(_classify(statement, line.line_numbers[0] if line.line_numbers else 0, label))
    # A name written NAME(...) that is neither an array nor a CHARACTER variable
    # (a substring) is a function reference: not a local to start at zero.
    statement_functions |= {name for name in referenced
                            if declared.get(name, ("", "scalar"))[1] != "array"
                            and declared.get(name, ("", ""))[0] != "character"}
    return _Routine(found.name, args, statements, declared, excluded, all_saved, uses_module,
                    other_includes, statement_functions, first_executable)


# ----------------------------------------------------------------------------- control flow

class _Undecidable(Exception):
    pass


def _successors(statements: list) -> tuple[list, int]:
    """Successor lists; the index ``len(statements)`` is the routine's exit."""
    count = len(statements)
    exit_node = count
    by_label = {s.label: i for i, s in enumerate(statements) if s.label}
    clauses: dict = {}           # header index -> list of clause indexes incl. end
    owner: dict = {}             # clause index -> header index
    do_end: dict = {}            # do index -> end index (END DO or labelled terminal)
    loops_ending_at: dict = {}   # terminal index -> do indexes, outermost first
    stack: list = []
    for index, statement in enumerate(statements):
        kind = statement.kind
        if kind == "if_then":
            stack.append(("if", index))
            clauses[index] = []
        elif kind in ("else_if", "else"):
            if not stack or stack[-1][0] != "if":
                raise _Undecidable(f"line {statement.line}: ELSE without IF")
            clauses[stack[-1][1]].append(index)
            owner[index] = stack[-1][1]
        elif kind == "end_if":
            if not stack or stack[-1][0] != "if":
                raise _Undecidable(f"line {statement.line}: END IF without IF")
            header = stack.pop()[1]
            clauses[header].append(index)
            owner[index] = header
        elif kind == "select":
            stack.append(("select", index))
            clauses[index] = []
        elif kind == "case":
            if not stack or stack[-1][0] != "select":
                raise _Undecidable(f"line {statement.line}: CASE without SELECT")
            clauses[stack[-1][1]].append(index)
            owner[index] = stack[-1][1]
        elif kind == "end_select":
            if not stack or stack[-1][0] != "select":
                raise _Undecidable(f"line {statement.line}: END SELECT without SELECT")
            header = stack.pop()[1]
            clauses[header].append(index)
            owner[index] = header
        elif kind == "do":
            stack.append(("do", index))
        elif kind == "end_do":
            if not stack or stack[-1][0] != "do" or statements[stack[-1][1]].labels[0]:
                raise _Undecidable(f"line {statement.line}: END DO without a block DO")
            header = stack.pop()[1]
            do_end[header] = index
            loops_ending_at.setdefault(index, []).append(header)
        if statement.label:
            closing = []
            while stack and stack[-1][0] == "do" and statements[stack[-1][1]].labels[0] == statement.label:
                closing.append(stack.pop()[1])
            for header in closing:
                do_end[header] = index
            if closing:
                loops_ending_at[index] = list(reversed(closing))
    if stack:
        raise _Undecidable("an IF, DO or SELECT block is not closed")
    at_least_once = {index for index, statement in enumerate(statements)
                     if statement.kind == "do" and statement.trips_at_least_once}

    def header_of(index: int) -> Optional[int]:
        return owner.get(index)

    def after(index: int) -> int:
        """Where control goes when ``index`` completes and nothing loops."""
        nxt = index + 1
        if nxt >= count:
            return exit_node
        following = statements[nxt]
        if following.kind in ("else_if", "else", "case"):
            return clauses[owner[nxt]][-1]
        return nxt

    def back_edge(header: int) -> list:
        """The end of a loop body: back to its test, and, for a loop known to
        run at least once, out of the loop (its header has no zero-trip exit)."""
        return [header, loop_exit(header)] if header in at_least_once else [header]

    def cont(index: int) -> list:
        """Normal completion of ``index``: back to a loop whose body it ends."""
        if index in loops_ending_at and statements[index].kind != "end_do":
            return back_edge(loops_ending_at[index][-1])
        return [after(index)]

    def loop_exit(header: int) -> int:
        end = do_end[header]
        if statements[end].kind == "end_do":
            return after(end)
        sharing = loops_ending_at[end]
        position = sharing.index(header)
        return sharing[position - 1] if position > 0 else after(end)

    def enclosing_loop(index: int, name: str) -> int:
        candidates = [h for h, e in do_end.items() if h < index <= e]
        if name:
            candidates = [h for h in candidates if statements[h].name == name]
        if not candidates:
            raise _Undecidable(f"line {statements[index].line}: EXIT or CYCLE outside a loop")
        return max(candidates)

    def target(label: str, line: int) -> int:
        if label not in by_label:
            raise _Undecidable(f"line {line}: a jump to label {label}, which is not found")
        return by_label[label]

    def flow(statement: _Stmt, index: int) -> list:
        kind = statement.kind
        if kind == "goto":
            return [target(statement.labels[0], statement.line)]
        if kind == "computed_goto":
            return [target(lab, statement.line) for lab in statement.labels] + cont(index)
        if kind == "arith_if":
            return [target(lab, statement.line) for lab in statement.labels]
        if kind == "return":
            return [exit_node]
        if kind == "exit":
            return [loop_exit(enclosing_loop(index, statement.name))]
        if kind == "cycle":
            return [enclosing_loop(index, statement.name)]
        if kind == "undecidable":
            raise _Undecidable(f"line {statement.line}: {statement.name}")
        return cont(index)

    successors: list = [[] for _ in range(count)]
    extra: list = []                 # (statement, successors) of logical-IF bodies
    for index, statement in enumerate(statements):
        kind = statement.kind
        if kind in ("if_then", "else_if"):
            header = index if kind == "if_then" else header_of(index)
            own = clauses[header]
            later = [c for c in own if c > index]
            body = index + 1
            if body in own:
                body = own[-1]
            successors[index] = [body, later[0]]
        elif kind == "select":
            own = clauses[index]
            successors[index] = [c for c in own[:-1]] + (
                [] if any(statements[c].bare for c in own[:-1]) else [own[-1]])
        elif kind == "case":
            nxt = index + 1
            successors[index] = [clauses[owner[index]][-1] if nxt in clauses[owner[index]] else nxt]
        elif kind == "else":
            successors[index] = [index + 1]
        elif kind == "do":
            end = do_end.get(index)
            if end is None:
                raise _Undecidable(f"line {statement.line}: a DO without its end")
            body = index + 1
            successors[index] = ([body] if statement.bare or index in at_least_once
                                 else [body, loop_exit(index)])
        elif kind == "end_do":
            successors[index] = back_edge(loops_ending_at[index][-1])
        elif kind == "logical_if":
            inner_index = count + 1 + len(extra)
            extra.append((statement.inner, flow(statement.inner, index)))
            successors[index] = [inner_index, *cont(index)]
        else:
            successors[index] = flow(statement, index)
    return successors + [[]] + [s for _, s in extra], len(extra)


def analyse_text(text: str, routine: str = "UMAT", *, form: Optional[str] = None,
                 source_path: Optional[Path] = None) -> Analysis:
    """Locals of ``routine`` in ``text`` that can be read before they are assigned."""
    from umat_oti.transform.routine_typing import routine_typing

    form = form or detect_source_form(Path(source_path or "umat.f"), text)
    analysis = Analysis(routine=routine.upper())
    parsed = _read_routine(text, routine, form)
    if parsed is None:
        analysis.undecided = f"routine {routine} was not found"
        return analysis
    analysis.first_executable_line = parsed.first_executable_line
    if parsed.all_saved:
        analysis.undecided = ("a SAVE statement without a list makes every local static: a value "
                              "carried between calls is not a read before assignment")
        return analysis
    statements = parsed.statements
    try:
        successors, extras = _successors(statements)
    except _Undecidable as reason:
        analysis.undecided = str(reason)
        return analysis
    count = len(statements)
    nodes = list(statements) + [_Stmt("exit", 0)]
    for index, statement in enumerate(statements):
        if statement.kind == "logical_if":
            nodes.append(statement.inner)
    typing = routine_typing(text, routine, form=form,
                            source_dir=Path(source_path).parent if source_path else None)
    statement_functions = parsed.statement_functions
    excluded = (parsed.args | parsed.excluded | statement_functions | {parsed.name.upper()})
    # An INCLUDE other than ABA_PARAM.INC can put a name the routine declares
    # into COMMON (or SAVE it, or give it a DATA value); starting such a name at
    # zero would change state carried between calls. The names those files
    # carry that way are excluded; when a file cannot be read, nothing is
    # started at zero and the findings say why.
    carried, unreadable = _names_carried_by_includes(
        parsed.other_includes, Path(source_path).parent if source_path else None)
    excluded |= carried
    candidates = {name for name in parsed.declared if name not in excluded}
    implicit_known = not (typing.implicit_none or typing.unknown_because or parsed.uses_module
                          or parsed.other_includes)
    if implicit_known:
        # An implicitly typed name the routine assigns, and one it only reads (a
        # name nothing ever sets is read undefined on every path).
        mentioned = set().union(*(n.defs | n.reads for n in nodes)) if nodes else set()
    assigned_somewhere = set().union(*(n.defs for n in nodes)) if nodes else set()
    if implicit_known:
        candidates |= {name for name in mentioned
                       if name not in excluded and name not in parsed.declared
                       and name not in typing.declared_real and name not in typing.declared_nonreal
                       and name not in _NOT_VARIABLES}
    # Only names the compiler sees: a line the repository's fixed-form reader takes
    # for a statement but that a compiler reads as a comment ("!" after column 1)
    # must not produce a finding.
    candidates &= _names_on_code_lines(text, form)
    if not candidates or not statements:
        return analysis
    universe = frozenset(candidates)
    total = len(nodes)
    predecessors: list = [[] for _ in range(total)]
    for index, targets in enumerate(successors):
        for successor in targets:
            predecessors[successor].append(index)
    reachable = {0}
    pending = [0]
    while pending:
        index = pending.pop()
        for successor in successors[index]:
            if successor not in reachable:
                reachable.add(successor)
                pending.append(successor)
    entry_in: list = [universe] * total
    out: list = [universe] * total
    entry_in[0] = frozenset()
    changed = True
    while changed:
        changed = False
        for index in range(total):
            if index not in reachable:
                continue
            if index == 0:
                incoming = frozenset()
            else:
                incoming = universe
                for predecessor in predecessors[index]:
                    if predecessor in reachable:
                        incoming = incoming & out[predecessor]
            new_out = incoming | (nodes[index].defs & universe)
            if incoming != entry_in[index] or new_out != out[index]:
                entry_in[index], out[index] = incoming, new_out
                changed = True
    # Arrays: an element assignment inside a loop that may run zero times, or
    # in one branch, covers the elements that are read later on every path the
    # author meant -- which a data flow over whole names cannot see. An array
    # is therefore reported only when NO element of it can have been assigned
    # on any path to the read ("may" analysis); a scalar whenever SOME path
    # reaches the read without assigning it ("must" analysis).
    arrays = frozenset(name for name in universe
                       if parsed.declared.get(name, ("", "scalar"))[1] == "array")
    may_in: list = [frozenset()] * total
    may_out: list = [frozenset()] * total
    changed = True
    while changed:
        changed = False
        for index in range(total):
            if index not in reachable:
                continue
            # the entry contributes nothing; a loop back to the first statement does
            incoming = frozenset()
            for predecessor in predecessors[index]:
                if predecessor in reachable:
                    incoming = incoming | may_out[predecessor]
            new_out = incoming | (nodes[index].defs & arrays)
            if incoming != may_in[index] or new_out != may_out[index]:
                may_in[index], may_out[index] = incoming, new_out
                changed = True
    flagged: dict = {}
    for index in sorted(reachable, key=lambda i: (nodes[i].line, i)):
        unset = ((nodes[index].reads & (universe - arrays)) - entry_in[index]) | (
            (nodes[index].reads & arrays) - may_in[index])
        for name in sorted(unset):
            flagged.setdefault(name, []).append(nodes[index].line)
    for name, lines in sorted(flagged.items(), key=lambda item: (min(item[1]), item[0])):
        kind, rank = parsed.declared.get(name, ("", "scalar"))
        type_name = {"real": "real", "integer": "integer", "logical": "logical",
                     "complex": "complex", "character": "character"}.get(kind, "")
        if not type_name:
            if typing.is_known_real(name):
                type_name = "real"
            elif (implicit_known and name[:1] in "IJKLMN"
                  and set(typing.nonreal_letters) == set("IJKLMN")):
                type_name = "integer"
        lines_sorted = tuple(sorted(set(lines)))
        if type_name and name not in assigned_somewhere and name not in parsed.declared:
            analysis.findings.append(ReadBeforeSet(
                name, lines_sorted[0], lines_sorted, type_name, rank or "scalar", False,
                why_not="nothing in the routine assigns it and it is not declared: either the source "
                        "reads a variable it never sets (a misspelt name, say) or this reader took a "
                        "name for a variable; it is reported, not initialised"))
        elif type_name and unreadable:
            analysis.findings.append(ReadBeforeSet(
                name, lines_sorted[0], lines_sorted, type_name, rank or "scalar", False,
                why_not=f"the routine INCLUDEs {', '.join(unreadable)}, which could not be read, and a "
                        f"name declared there in COMMON or SAVE must not be reset on entry"))
        elif type_name:
            analysis.findings.append(ReadBeforeSet(name, lines_sorted[0], lines_sorted, type_name,
                                                   rank or "scalar", True))
        else:
            analysis.findings.append(ReadBeforeSet(
                name, lines_sorted[0], lines_sorted, "unknown", rank or "scalar", False,
                why_not="its type could not be settled from the routine's declarations and "
                        "implicit rules"))
    return analysis


def _names_carried_by_includes(includes: Sequence[str], directory: Optional[Path]) -> tuple[set, list]:
    """Names the INCLUDEd files put in COMMON, SAVE, DATA or EQUIVALENCE (and every
    name they declare when they hold a bare SAVE), and the files that could not be read."""
    carried: set = set()
    unreadable: list = []
    for name in includes:
        found = None
        if directory is not None and directory.is_dir():
            wanted = Path(name).name.lower()
            found = next((p for p in directory.iterdir() if p.is_file() and p.name.lower() == wanted), None)
        if found is None:
            unreadable.append(name)
            continue
        text = found.read_text(encoding="utf-8", errors="replace")
        statements = [line.text.upper() for line in logical_lines_from_text(text, "fixed")] + [
            line.text.upper() for line in logical_lines_from_text(text, "free")]
        for statement in statements:
            match = re.match(r"^(COMMON|SAVE|DATA|EQUIVALENCE)\b(.*)$", statement)
            if not match:
                continue
            if match.group(1) == "SAVE" and not match.group(2).strip():
                carried |= _read_names(" ".join(statements))
                continue
            carried |= _read_names(re.sub(r"/[^/]*/", " ", match.group(2)) if match.group(1) != "COMMON"
                                   else re.sub(r"/\s*\w*\s*/", " ", match.group(2)))
    return carried, unreadable


def _names_on_code_lines(text: str, form: str) -> set:
    names: set = set()
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("!"):
            continue
        if form == "fixed" and raw[:1] in ("c", "C", "*"):
            continue
        names |= {n.upper() for n in _NAME.findall(_blank_strings(strip_inline_comment(raw)))}
    return names


def analyse_file(path: Path | str, routine: str = "UMAT") -> Analysis:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return analyse_text(text, routine, form=detect_source_form(path, text), source_path=path)


# ----------------------------------------------------------------------------- emitting

def statement_line(form: str, statement: str) -> str:
    """One statement as physical line(s) of ``form``: fixed form starts in
    column 7 and continues after the ``=`` when column 72 would be passed."""
    if form != "fixed":
        return statement
    line = "      " + statement
    if len(line) <= 72 or " = " not in statement:
        return line
    target, value = statement.split(" = ", 1)
    return "      " + target + " =\n     &  " + value


def routine_span(text: str, routine: str, form: str) -> tuple[int, int]:
    """(first executable line, last line) of ``routine``; (0, 0) when absent."""
    logical = logical_lines_from_text(text, form)
    found = next((r for r in parse_subroutines(logical) if r.upper_name == routine.upper()), None)
    if found is None:
        return 0, 0
    last = max(n for line in found.lines for n in line.line_numbers)
    return first_executable_line(text, routine, form), last


def executable_text(text: str, routine: str, form: str) -> str:
    """The routine's statements from its first executable one, comments
    removed, upper case: what a generated routine still refers to."""
    first, last = routine_span(text, routine, form)
    if not first:
        return ""
    kept = []
    for raw in text.split("\n")[first - 1:last]:
        if form == "fixed" and raw[:1] in ("c", "C", "*", "!"):
            continue
        kept.append(_blank_strings(strip_inline_comment(raw)))
    return "\n".join(kept).upper()


def entry_comment(form: str) -> str:
    text = "Read before assignment in the original: started at zero here (transform report)"
    return ("C     " + text) if form == "fixed" else ("! " + text)


def first_executable_line(text: str, routine: str, form: str) -> int:
    parsed = _read_routine(text, routine, form)
    return parsed.first_executable_line if parsed else 0


def insert_at_entry(text: str, routine: str, form: str, statements: Sequence[str]) -> str:
    """``text`` with ``statements`` placed before the first executable statement
    of ``routine``. Unchanged when there is nothing to place or no such line."""
    if not statements:
        return text
    line = first_executable_line(text, routine, form)
    if not line:
        return text
    lines = text.split("\n")
    block = [entry_comment(form)] + [statement_line(form, s) for s in statements]
    lines[line - 1:line - 1] = block
    return "\n".join(lines)
