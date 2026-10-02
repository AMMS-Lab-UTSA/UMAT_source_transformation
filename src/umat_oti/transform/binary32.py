"""Keep the source's binary32 arithmetic binary32 in a transformed statement.

The OTI type is built over double precision, and its operators take REAL(8)
operands only. Two things the source computes in single precision therefore
change when a statement is rewritten over it (Curie-G, B2 growth diagnosis,
clusters B-L and B-W; Gauss B1 F3):

**Literal-only subexpressions (B-L).** ``X**(-5.0/3.0)``: the compiler folds
``-5.0/3.0`` in binary32 (-1.66666662693...), then converts. Writing each
literal as the double it denotes is exact for the literals, but the quotient
is then formed in double (-1.666...667) -- a different exponent, and the
primal moves by up to 1e-6 relative. :func:`fold_binary32_constants` folds every
maximal literal-only subexpression of default-REAL kind the way the compiler
does -- correctly rounded binary32 arithmetic, intrinsics included -- and
writes the binary32 result as the exact double literal. A lone literal is left
to the caller's per-literal conversion, which is already exact.

**Variables declared binary32 (B-W).** ``REAL Lambda1`` stores a binary32
value; its OTI shadow is double. :func:`round_binary32_stores` appends, after
every assignment to such a shadow, a statement that rounds its REAL PART to
binary32 (``X_OTI%R = REAL(REAL(X_OTI%R, 4), 8)``) and leaves the derivative
parts double. Where the source evaluates the right-hand side in double -- the
usual case, because one REAL*8 operand promotes the whole expression -- this
reproduces the source's stored value exactly. Where every operand is binary32
the source also rounds each intermediate operation; that residual is at most
an ulp of binary32 per operation and is not modelled.

Hazard respected: no default-REAL literal is ever widened to the double of its
decimal text. ``(TIME(2)+DTIME) .LE. 2.2`` compares against the binary32 value
of 2.2 in the source, and the literal conversions here keep exactly that value.
"""
from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

import numpy as np

_TOKEN = re.compile(
    r"""(?P<str>'(?:[^']|'')*'|"(?:[^"]|"")*")
      |(?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eEdD][+-]?\d+)?(?:_\w+)?)
      |(?P<dotop>\.(?:EQ|NE|LT|LE|GT|GE|AND|OR|NOT|EQV|NEQV|TRUE|FALSE)\.)
      |(?P<name>[A-Za-z_]\w*)
      |(?P<op>\*\*|//|==|/=|<=|>=|=>|[-+*/<>=(),:%])
      |(?P<ws>\s+)
      |(?P<other>.)""",
    re.VERBOSE | re.IGNORECASE)

_REL = {".EQ.", ".NE.", ".LT.", ".LE.", ".GT.", ".GE.", "==", "/=", "<", "<=", ">", ">="}
_PREC = {"**": 6, "*": 5, "/": 5, "+": 4, "-": 4, "//": 3}
_LOGICAL_PREC = {".AND.": 1, ".OR.": 0.5, ".EQV.": 0.2, ".NEQV.": 0.2}

_FUNCTIONS_KEEP_KIND = {"SQRT", "EXP", "LOG", "LOG10", "SIN", "COS", "TAN", "ASIN", "ACOS",
                        "ATAN", "SINH", "COSH", "TANH", "ABS", "ATAN2", "MAX", "MIN", "SIGN"}
_FUNCTIONS_REAL4 = {"REAL", "FLOAT", "SNGL", "AMAX1", "AMIN1"}


@dataclass
class _Tok:
    kind: str
    text: str
    start: int
    end: int


@dataclass
class _Node:
    start: int
    end: int
    value: object = None      # python int, np.float32 or np.float64 when constant
    kind: str = "unknown"     # int | real4 | real8 | unknown
    has_op: bool = False
    paren_inner: Optional[tuple[int, int]] = None
    b32: str = ""            # "real4" when the source holds this value in binary32, "int" for integers
    oti: bool = False        # the value is an OTI shadow (or computed from one)


def _tokens(text: str) -> list[_Tok]:
    out = []
    for match in _TOKEN.finditer(text):
        kind = match.lastgroup
        if kind == "ws":
            continue
        out.append(_Tok(kind, match.group(0), match.start(), match.end()))
    return out


def _literal(tok: _Tok) -> _Node:
    text = tok.text.upper()
    node = _Node(tok.start, tok.end)
    if "_" in text:
        body, suffix = text.split("_", 1)
        if suffix not in ("4", "8"):
            return node
        text = body
        forced = "real4" if suffix == "4" else "real8"
    else:
        forced = ""
    if re.fullmatch(r"\d+", text) and not forced:
        node.value, node.kind = int(text), "int"
        return node
    if "D" in text or forced == "real8":
        node.value, node.kind = np.float64(float(text.replace("D", "E"))), "real8"
        return node
    node.value, node.kind = np.float32(float(text)), "real4"
    return node


def _as_kind(value, kind: str):
    if kind == "real4":
        return np.float32(value)
    if kind == "real8":
        return np.float64(value)
    return value


def _mp_round(function, args, kind: str):
    """``function`` of ``args`` correctly rounded to ``kind`` (binary32 or binary64)."""
    import mpmath

    bits = 24 if kind == "real4" else 53
    with mpmath.workprec(bits):
        result = function(*[mpmath.mpf(float(a)) for a in args])
    return _as_kind(float(result), kind)


def _combine(op: str, left: _Node, right: _Node) -> _Node:
    node = _Node(left.start, right.end, has_op=True)
    if left.kind == "unknown" or right.kind == "unknown":
        return node
    if left.kind == right.kind == "int":
        a, b = int(left.value), int(right.value)
        try:
            if op == "+":
                node.value = a + b
            elif op == "-":
                node.value = a - b
            elif op == "*":
                node.value = a * b
            elif op == "/":
                if b == 0:
                    return node
                quotient = abs(a) // abs(b)
                node.value = quotient if (a >= 0) == (b >= 0) else -quotient
            elif op == "**":
                if b < 0:
                    node.value = 1 if a == 1 else (-1 if a == -1 and b % 2 else (1 if a == -1 else 0))
                else:
                    node.value = a ** b
            else:
                return node
        except (OverflowError, ZeroDivisionError):
            return node
        node.kind = "int"
        return node
    kind = "real8" if "real8" in (left.kind, right.kind) else "real4"
    if op == "**" and right.kind == "int":
        exponent = int(right.value)
        node.value = _mp_round(lambda x: x ** exponent, [left.value], kind)
        node.kind = kind
        return node
    a, b = _as_kind(left.value, kind), _as_kind(right.value, kind)
    with np.errstate(all="ignore"):
        if op == "+":
            value = a + b
        elif op == "-":
            value = a - b
        elif op == "*":
            value = a * b
        elif op == "/":
            if b == 0:
                return node
            value = a / b
        elif op == "**":
            if a < 0:
                return node
            value = _mp_round(lambda x, y: x ** y, [a, b], kind)
        else:
            return node
    if not np.isfinite(value):
        return node
    node.value, node.kind = _as_kind(value, kind), kind
    return node


def _call(name: str, args: list[_Node], start: int, end: int) -> _Node:
    import mpmath

    node = _Node(start, end, has_op=True)
    upper = name.upper()
    if not args or any(a.kind == "unknown" for a in args):
        return node
    if upper in _FUNCTIONS_REAL4:
        if upper in ("AMAX1", "AMIN1"):
            values = [np.float32(a.value) for a in args]
            node.value = max(values) if upper == "AMAX1" else min(values)
        elif len(args) == 1:
            node.value = np.float32(args[0].value)
        else:
            return node
        node.kind = "real4"
        return node
    if upper == "DBLE" and len(args) == 1:
        node.value, node.kind = np.float64(args[0].value), "real8"
        return node
    if upper not in _FUNCTIONS_KEEP_KIND:
        return node
    kinds = {a.kind for a in args}
    if "int" in kinds and upper not in ("ABS", "MAX", "MIN", "SIGN"):
        return node
    kind = "real8" if "real8" in kinds else ("real4" if "real4" in kinds else "int")
    if kind == "int":
        values = [int(a.value) for a in args]
        if upper == "ABS" and len(values) == 1:
            node.value = abs(values[0])
        elif upper in ("MAX", "MIN"):
            node.value = max(values) if upper == "MAX" else min(values)
        else:
            return node
        node.kind = "int"
        return node
    values = [_as_kind(a.value, kind) for a in args]
    if upper in ("ABS", "MAX", "MIN", "SIGN"):
        if upper == "ABS" and len(values) == 1:
            node.value = abs(values[0])
        elif upper == "MAX":
            node.value = max(values)
        elif upper == "MIN":
            node.value = min(values)
        elif upper == "SIGN" and len(values) == 2:
            node.value = abs(values[0]) if values[1] >= 0 else -abs(values[0])
        else:
            return node
        node.kind = kind
        return node
    functions = {"SQRT": mpmath.sqrt, "EXP": mpmath.exp, "LOG": mpmath.log,
                 "LOG10": mpmath.log10, "SIN": mpmath.sin, "COS": mpmath.cos,
                 "TAN": mpmath.tan, "ASIN": mpmath.asin, "ACOS": mpmath.acos,
                 "ATAN": mpmath.atan, "SINH": mpmath.sinh, "COSH": mpmath.cosh,
                 "TANH": mpmath.tanh, "ATAN2": mpmath.atan2}
    function = functions.get(upper)
    if function is None or (upper != "ATAN2" and len(values) != 1):
        return node
    if upper in ("SQRT", "LOG", "LOG10") and values[0] < 0 or upper in ("LOG", "LOG10") and values[0] == 0:
        return node
    try:
        value = _mp_round(function, values, kind)
    except (ValueError, ZeroDivisionError):
        return node
    if not np.isfinite(value):
        return node
    node.value, node.kind = value, kind
    return node


class _Parser:
    def __init__(self, tokens: list[_Tok], single_names: frozenset = frozenset(),
                 suffix: str = "_OTI", oti_names: frozenset = frozenset()):
        self.tokens = tokens
        self.index = 0
        self.candidates: list[_Node] = []
        self.single_names = single_names
        self.suffix = suffix.upper()
        self.oti_names = oti_names
        self.wraps: list[tuple[int, int]] = []
        # Wraps of a binary32 variable against a literal, kept only when the
        # statement is rewritten over OTI (see _b32_operation).
        self.literal_wraps: list[tuple[int, int]] = []
        self.saw_oti = False

    def _b32_operation(self, combined: _Node, left: _Node, right: _Node) -> None:
        """Mark (and record for rounding) a binary32 operation on an OTI value."""
        kinds = {left.b32, right.b32}
        if "" in kinds or kinds == {"int"}:
            return
        combined.b32 = "real4"
        combined.oti = left.oti or right.oti
        if combined.oti:
            self.wraps.append((combined.start, combined.end))
        elif (left.value is None) != (right.value is None):
            # A binary32 variable against a literal (or literal-only
            # subexpression). In a statement the transform rewrites over OTI
            # the literal is written as the double it denotes, which turns
            # the compiler's binary32 operation into a double one:
            # SweetMelon's ``9.0/40.0*Pi*(-2.0+STATEV(5))`` (Pi REAL) formed
            # 0.225*Pi in double and lost the binary32 rounding of that
            # product (ulpK 6e8). OTI_R4 restores it, and on a REAL(4)
            # operand -- a statement whose literals stay as written -- it is
            # the identity, kind included.
            self.literal_wraps.append((combined.start, combined.end))

    def peek(self) -> Optional[_Tok]:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self) -> _Tok:
        tok = self.tokens[self.index]
        self.index += 1
        return tok

    def _flush(self, node: _Node) -> None:
        """A constant node that will not grow any further."""
        if node.kind == "real4" and node.has_op and node.value is not None:
            self.candidates.append(node)

    def expression(self, minimum: float = 0.0) -> Optional[_Node]:
        tok = self.peek()
        if tok is None:
            return None
        if tok.kind == "op" and tok.text in "+-" and len(tok.text) == 1:
            self.take()
            operand = self.expression(_PREC["+"] + 0.01)
            if operand is None:
                return None
            node = _Node(tok.start, operand.end, has_op=operand.has_op,
                         paren_inner=None)
            if operand.value is not None:
                node.value = -operand.value if tok.text == "-" else operand.value
                node.kind = operand.kind
            else:
                self._flush(operand)
            node.b32, node.oti = operand.b32, operand.oti
            left = node
        elif tok.kind == "dotop" and tok.text.upper() == ".NOT.":
            self.take()
            operand = self.expression(0.9)
            if operand is None:
                return None
            self._flush(operand)
            left = _Node(tok.start, operand.end)
        else:
            left = self.primary()
            if left is None:
                return None
        while True:
            tok = self.peek()
            if tok is None:
                break
            text = tok.text.upper()
            if tok.kind == "op" and text in _PREC:
                prec = _PREC[text]
            elif text in _REL:
                prec = 2
            elif tok.kind == "dotop" and text in _LOGICAL_PREC:
                prec = _LOGICAL_PREC[text]
            else:
                break
            if prec < minimum:
                break
            self.take()
            right_minimum = prec if text == "**" else prec + 0.01
            right = self.expression(right_minimum)
            if right is None:
                self._flush(left)
                return None
            if prec >= 3:
                combined = _combine(text, left, right)
                if text != "//":
                    self._b32_operation(combined, left, right)
            else:
                combined = _Node(left.start, right.end)
            if combined.value is None:
                self._flush(left)
                self._flush(right)
            left = combined
        return left

    def primary(self) -> Optional[_Node]:
        tok = self.peek()
        if tok is None:
            return None
        if tok.kind == "num":
            self.take()
            node = _literal(tok)
            node.b32 = {"real4": "real4", "int": "int"}.get(node.kind, "")
            return node
        if tok.kind == "str" or (tok.kind == "dotop" and tok.text.upper() in (".TRUE.", ".FALSE.")):
            self.take()
            return _Node(tok.start, tok.end)
        if tok.kind == "op" and tok.text == "(":
            self.take()
            inner = self.expression()
            items = [inner]
            while self.peek() is not None and self.peek().text == ",":
                self.take()
                items.append(self.expression())
            close = self.peek()
            end = close.end if close is not None and close.text == ")" else (items[-1].end if items[-1] else tok.end)
            if close is not None and close.text == ")":
                self.take()
            if len(items) == 1 and inner is not None:
                node = _Node(tok.start, end, inner.value, inner.kind, inner.has_op,
                             paren_inner=(inner.start, inner.end), b32=inner.b32, oti=inner.oti)
                return node
            return _Node(tok.start, end)
        if tok.kind == "name":
            self.take()
            nxt = self.peek()
            if nxt is not None and nxt.text == "(":
                self.take()
                args = []
                while True:
                    if self.peek() is not None and self.peek().text == ")":
                        break
                    argument = self.expression()
                    if argument is None:
                        break
                    args.append(argument)
                    if self.peek() is not None and self.peek().text in (",", ":"):
                        self.take()
                        continue
                    break
                close = self.peek()
                end = close.end if close is not None and close.text == ")" else tok.end
                if close is not None and close.text == ")":
                    self.take()
                node = _call(tok.text, args, tok.start, end)
                kind, is_oti = self._name_kind(tok.text)
                upper_name = tok.text.upper()
                if kind:
                    node.b32, node.oti = kind, is_oti           # element of a binary32 array
                elif (upper_name == "REAL" and len(args) == 1
                      and args[0].b32 == "real4" and args[0].oti):
                    # The real part of a binary32 variable's shadow: a double
                    # holding a binary32 value, operated on in double.
                    node.b32, node.oti = "real4", True
                elif (upper_name in ("MAX", "MIN") and len(args) == 2
                      and args[0].b32 == "real4" and args[0].oti
                      and args[1].kind == "real8" and args[1].value is not None
                      and float(args[1].value) == 1e-30):
                    # The transform's own SQRT guard,
                    # (MAX(REAL(e), 1.0D-30) - REAL(e)) + (e): it is e where
                    # e is positive, so it keeps e's binary32 kind and the
                    # SQRT around it is still a binary32 SQRT (Cereus).
                    node.b32, node.oti = "real4", True
                elif (tok.text.upper() in _FUNCTIONS_KEEP_KIND and args
                      and all(a.b32 in ("real4", "int") for a in args)
                      and any(a.b32 == "real4" for a in args)):
                    node.b32, node.oti = "real4", any(a.oti for a in args)
                    if node.oti:
                        self.wraps.append((node.start, node.end))
                if node.value is None and tok.text.upper() in _FUNCTIONS_KEEP_KIND:
                    # An intrinsic is generic over the kind of its argument.
                    # A user function, a CALL or an array subscript is not:
                    # folding there would change the type of the actual, so
                    # a constant argument keeps the kind the source gave it.
                    for argument in args:
                        self._flush(argument)
                node = self._postfix(node)
                return node
            node = self._postfix(_Node(tok.start, tok.end))
            node.b32, node.oti = self._name_kind(tok.text)
            return node
        return None

    def _name_kind(self, text: str) -> tuple[str, bool]:
        upper = text.upper()
        if (self.suffix and upper.endswith(self.suffix)) or upper in self.oti_names:
            self.saw_oti = True
        if self.suffix and upper.endswith(self.suffix) and upper[:-len(self.suffix)] in self.single_names:
            return "real4", True
        if upper in self.single_names:
            return "real4", upper in self.oti_names
        return "", False

    def _postfix(self, node: _Node) -> _Node:
        while self.peek() is not None and self.peek().text == "%":
            self.take()
            component = self.peek()
            if component is None or component.kind != "name":
                break
            self.take()
            node = _Node(node.start, component.end)
        return node


def _binary32_literal(value) -> str:
    from umat_oti.transform.source_transform import _as_written_in_double

    text = repr(float(np.float32(value)))
    return _as_written_in_double(text)


def fold_binary32_constants(statement: str, *, at_line_end_is_open: bool = True) -> str:
    """``statement`` with every maximal binary32 literal-only subexpression folded.

    ``at_line_end_is_open``: the statement may continue on the next physical
    line, so a constant reaching the end of the text is left alone -- a
    continuation starting ``**2`` would bind tighter than what is visible.
    """
    code, _, comment = _split_comment(statement)
    tokens = _tokens(code)
    if not tokens:
        return statement
    parser = _Parser(tokens)
    while parser.index < len(tokens):
        before = parser.index
        node = parser.expression()
        if node is not None:
            parser._flush(node)
        if parser.index == before:
            parser.index += 1
    replacements = []
    stripped_end = len(code.rstrip())
    for node in parser.candidates:
        start, end = node.paren_inner or (node.start, node.end)
        if at_line_end_is_open and end >= stripped_end:
            continue
        replacements.append((start, end, _binary32_literal(node.value)))
    if not replacements:
        return statement
    replacements.sort()
    kept = []
    for item in replacements:
        if kept and item[0] < kept[-1][1]:
            continue
        kept.append(item)
    out = code
    for start, end, text in reversed(kept):
        replacement = f"({text})" if text.startswith("-") and start > 0 and out[:start].rstrip()[-1:] in "*/+-" else text
        out = out[:start] + replacement + out[end:]
    return out + comment


def _split_comment(statement: str) -> tuple[str, str, str]:
    quote = ""
    for index, char in enumerate(statement):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char == "!":
            return statement[:index], "!", statement[index:]
    return statement, "", ""


_ASSIGNMENT_TARGET = re.compile(r"^\s*(?:\d+\s+)?(?:IF\s*\(.*\)\s*)?([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=(?!=)",
                                re.IGNORECASE)


def round_binary32_stores(text: str, form: str, span: tuple[int, int], names: set[str],
                          *, suffix: str = "_OTI") -> str:
    """After each assignment to ``<name><suffix>`` in ``span``, round its real part to binary32."""
    if not names:
        return text
    targets = {f"{name.upper()}{suffix.upper()}" for name in names}
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    index = 0
    first, last = span
    while index < len(lines):
        line = lines[index]
        number = index + 1
        out.append(line)
        index += 1
        if not (first <= number <= last) or _is_comment(line, form):
            continue
        statement_lines = [line]
        # Gather continuations so the rounding goes after the whole statement.
        while index < len(lines) and _continues(lines[index], statement_lines[-1], form):
            out.append(lines[index])
            statement_lines.append(lines[index])
            index += 1
        head = _statement_text(statement_lines[0], form)
        match = _ASSIGNMENT_TARGET.match(head)
        if not match or match.group(1).upper() not in targets:
            continue
        name = match.group(1)
        indent = "      " if form == "fixed" else re.match(r"^\s*", _strip_label(statement_lines[0])).group(0)
        newline = "\n" if line.endswith("\n") else ""
        out.append(f"{indent}{name}%R = REAL(REAL({name}%R, 4), 8){newline or chr(10)}")
    return "".join(out)


def _strip_label(line: str) -> str:
    return re.sub(r"^\s*\d+\s+", lambda m: " " * len(m.group(0)), line)


def _is_comment(line: str, form: str) -> bool:
    if form == "fixed":
        return line[:1] in "Cc*!" or not line.strip()
    return line.lstrip().startswith("!") or not line.strip()


def _statement_text(line: str, form: str) -> str:
    if form == "fixed":
        return line[6:72] if len(line) > 6 else ""
    return line.split("!", 1)[0]


def _continues(next_line: str, previous: str, form: str) -> bool:
    if form == "fixed":
        return len(next_line) > 5 and next_line[:1] not in "Cc*!" and next_line[5] not in " 0\n"
    return previous.split("!", 1)[0].rstrip().endswith("&")


def round_binary32_operations(statement: str, single_names, *, suffix: str = "_OTI",
                              oti_names=frozenset()) -> str:
    """Wrap every binary32 operation on an OTI value in ``OTI_R4(...)``.

    An operation the source performs in binary32 -- both operands binary32:
    a binary32 variable (or its shadow ``X_OTI``), a default-REAL literal, an
    integer -- rounds its result to binary32. ``(Lambda1-1.0)`` in
    Growth-frac.for loses six digits that way, and the double the OTI
    arithmetic forms keeps them. ``OTI_R4`` rounds the real part to binary32
    and leaves the derivative parts alone; for + - * / and SQRT on binary32
    operands, rounding the double result is exactly the binary32 operation.
    Operations with no OTI operand are untouched: they are still REAL and the
    compiler does them in binary32 itself.
    """
    single = frozenset(str(n).upper() for n in single_names)
    if not single:
        return statement
    code, _, comment = _split_comment(statement)
    tokens = _tokens(code)
    if not tokens:
        return statement
    parser = _Parser(tokens, single, suffix, frozenset(str(n).upper() for n in oti_names))
    while parser.index < len(tokens):
        before = parser.index
        parser.expression()
        if parser.index == before:
            parser.index += 1
    wraps = parser.wraps + (parser.literal_wraps if parser.saw_oti else [])
    if not wraps:
        return statement
    inserts: dict[int, list[str]] = {}
    for start, end in set(wraps):
        inserts.setdefault(start, []).append("OTI_R4(")
        inserts.setdefault(end, []).append(")")
    out = code
    for position in sorted(inserts, reverse=True):
        opens = [t for t in inserts[position] if t != ")"]
        closes = [t for t in inserts[position] if t == ")"]
        out = out[:position] + "".join(closes) + "".join(opens) + out[position:]
    return out + comment


#: (binary32 names, shadow suffix, OTI-typed bare names) of the routine being
#: emitted. Set by the emitters around their statement loop so the per-line
#: literal normaliser can round binary32 operations before literals lose
#: their kind; empty everywhere else.
BINARY32_CONTEXT: ContextVar[tuple[frozenset, str, frozenset]] = ContextVar(
    "binary32_context", default=(frozenset(), "_OTI", frozenset()))


def round_binary32_operations_in_context(statement: str) -> str:
    names, suffix, oti_names = BINARY32_CONTEXT.get()
    if not names:
        return statement
    return round_binary32_operations(statement, names, suffix=suffix, oti_names=oti_names)
