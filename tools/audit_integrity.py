#!/usr/bin/env python
"""Audit how a repository changed since its baseline commit.

Three checks, each comparing the commit being audited (``--rev``, default
``HEAD``) with the repository's baseline commit, the commit the completion
work started from:

``t12``  what changed in the tests and the verification code: deleted or
         renamed tests; new skips, xfails, importorskips and deselections
         (including CI and script filters, and deselecting markers added to
         existing tests); changed numeric tolerances; removed assertions and
         tolerance checks; new warning filters; new broad exception handlers;
         deleted examples; changed support metadata; new mocks and
         monkeypatches in tests; new ``warnings.warn`` calls; and changed
         reference data. Every finding must be reviewed in
         ``docs/evidence/integrity_review.json``, either with a reason a reader
         can check (quoted evidence is looked up where the entry says it is)
         or as a violation; a finding with no review entry, or an entry that
         matches no finding, fails the check.
``t11``  every bug fixed since the baseline has a regression test. The fix
         commits are selected by the rule in
         ``docs/evidence/bug_fix_regression_map.json``; each is either mapped
         to test node ids that must exist, excluded with a reason, or listed
         as a fix without a test (reported open).
``ci3``  every step of the clean-clone run corresponds to a documented
         instruction. The run's steps and the documentation passages they
         rest on are data in ``docs/evidence/clean_clone_commands.json``; the
         check confirms each quoted passage is still in the named document
         and, where the scripts are present, that the list is what the run
         script (Residual_Assembler ``scripts/reproduce_from_clean_clones.sh``),
         the clean-install gate and the examples phase really run. A step
         the run needs only as a harness (recording commits, checking the
         clones were left unmodified) is marked ``harness`` with its reason,
         and may only run read-only queries.

The script is identical in UMAT_source_transformation and Residual_Assembler
and works out which of the two it runs in. It needs the full git history (a
shallow clone does not contain the baseline commit and fails loudly).

Exit status: 0 when every finding is explained and no violation is open,
1 when a finding is unexplained or a review entry is stale, 2 when every
finding is explained but a recorded violation (or undocumented step, or fix
without a test) is still open.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The commit each repository's completion work started from.
BASELINES = {
    "umat-oti": "3f340b72ec4d9d1f474fdb2e0f6bda1c41bfaa76",
    "residual-assembler": "0789984c6c2750091d0f43b9ba42b84b3d890556",
}
REPOSITORY_LABELS = {"umat-oti": "UMAT", "residual-assembler": "RA"}

REVIEW_FILE = "docs/evidence/integrity_review.json"
FIX_MAP_FILE = "docs/evidence/bug_fix_regression_map.json"
COMMANDS_FILE = "docs/evidence/clean_clone_commands.json"

T12_CATEGORIES = (
    "deleted_test", "skip", "tolerance", "removed_check", "warning_filter", "broad_except",
    "deleted_example", "metadata", "mock", "warn_call", "reference_data",
)


# --------------------------------------------------------------------------
# git access

class GitError(RuntimeError):
    pass


def git(*arguments: str, root: Optional[Path] = None) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root or REPO_ROOT, capture_output=True, text=True)
    if completed.returncode:
        raise GitError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return completed.stdout


class Revision:
    """Read files of one commit through a single ``git cat-file --batch``."""

    def __init__(self, rev: str, root: Optional[Path] = None):
        self.root = root = root or REPO_ROOT
        self.commit = git("rev-parse", "--verify", rev + "^{commit}", root=root).strip()
        listing = git("ls-tree", "-r", "-z", "--name-only", self.commit, root=root)
        self.files = sorted(name for name in listing.split("\0") if name)
        self._fileset = set(self.files)
        self._cache: Dict[str, Optional[str]] = {}
        self._batch = None

    def __contains__(self, path: str) -> bool:
        return path in self._fileset

    def text(self, path: str) -> Optional[str]:
        if path not in self._fileset:
            return None
        if path in self._cache:
            return self._cache[path]
        if self._batch is None:
            self._batch = subprocess.Popen(["git", "cat-file", "--batch"], cwd=self.root,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._batch.stdin.write(f"{self.commit}:{path}\n".encode())
        self._batch.stdin.flush()
        header = self._batch.stdout.readline().decode().split()
        if len(header) < 3 or header[1] != "blob":
            self._cache[path] = None
            return None
        data = self._batch.stdout.read(int(header[2]) + 1)[:-1]
        text = data.decode("utf-8", errors="replace") if b"\0" not in data[:8000] else None
        self._cache[path] = text
        return text

    def close(self):
        if self._batch is not None:
            self._batch.stdin.close()
            self._batch.wait()
            self._batch = None


def repository_name(root: Optional[Path] = None) -> str:
    text = ((root or REPO_ROOT) / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^name\s*=\s*"([^"]+)"', text)
    if not match or match.group(1) not in BASELINES:
        raise SystemExit(f"not one of the audited repositories: {match.group(1) if match else '?'}")
    return match.group(1)


def baseline_commit(name: str, root: Optional[Path] = None) -> str:
    wanted = BASELINES[name]
    try:
        commit = git("rev-parse", "--verify", wanted + "^{commit}", root=root).strip()
    except GitError:
        raise SystemExit(
            f"baseline commit {wanted} is not in this clone. The audit compares with the "
            "commit the work started from and needs full history: clone without --depth, "
            "or check out with fetch-depth: 0.")
    return commit


def rename_map(base: str, head: str, root: Optional[Path] = None) -> Dict[str, str]:
    """Baseline path -> path at ``head`` for files git sees as renamed."""
    out = git("diff", "-M", "--name-status", "-z", base, head, root=root)
    fields = out.split("\0")
    renames = {}
    index = 0
    while index < len(fields) - 1:
        status = fields[index]
        if not status:
            index += 1
            continue
        if status.startswith(("R", "C")):
            renames[fields[index + 1]] = fields[index + 2]
            index += 3
        else:
            index += 2
    return renames


def name_status(base: str, head: str, root: Optional[Path] = None) -> List[Tuple[str, str, Optional[str]]]:
    out = git("diff", "-M", "--name-status", "-z", base, head, root=root)
    fields = out.split("\0")
    entries = []
    index = 0
    while index < len(fields) - 1:
        status = fields[index]
        if not status:
            index += 1
            continue
        if status.startswith(("R", "C")):
            entries.append((status[0], fields[index + 1], fields[index + 2]))
            index += 3
        else:
            entries.append((status[0], fields[index + 1], None))
            index += 2
    return entries


def pickaxe(base: str, head: str, needle: str, paths: Iterable[str], root: Optional[Path] = None) -> List[str]:
    """Commits in base..head whose diff changes the number of ``needle`` in ``paths``."""
    needle = needle.strip()
    if not needle:
        return []
    out = git("log", "--format=%h", "-S" + needle, f"{base}..{head}", "--", *sorted(set(paths)), root=root)
    return out.split()


# --------------------------------------------------------------------------
# Python source scanning

TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
TOL_NAME = re.compile(
    r"(?i)(?:^|_)(?:r|a|abs|rel)?tol(?:erance)?s?(?:_|$)"
    r"|(?:^|_)(?:rtol|atol)(?:_|$)"
    r"|(?:^|_)(?:limit|bound|threshold)s?$")
APPROX_KWARGS = {"rel", "abs"}
PRECISION_KWARGS = {"decimal", "places"}   # larger is tighter
SKIP_CALLS = {"skip", "importorskip", "xfail", "skipTest", "skipIf", "skipUnless", "expectedFailure"}
MARK_SKIPS = {"skip", "skipif", "xfail"}
MOCK_CALLS = {"patch", "MagicMock", "Mock", "NonCallableMock", "AsyncMock", "create_autospec", "PropertyMock"}
MONKEYPATCH_CALLS = {"setattr", "setitem", "delattr"}
VERIFICATION_WORDS = ("verif", "valid", "check", "gate", "compare", "diagnos", "audit",
                      "reference", "census", "regression", "reproduce", "homogen", "benchmark")


def is_test_file(path: str) -> bool:
    return path.startswith("tests/") and bool(TEST_FILE.search(path))


def is_test_code(path: str) -> bool:
    return path.startswith("tests/") or bool(TEST_FILE.search(path)) or path.endswith("conftest.py")


def is_verification_code(path: str) -> bool:
    if path.startswith(("tests/", "verification/", "scripts/", "tools/", "examples/", "benchmarks/")):
        return True
    lowered = path.lower()
    return any(word in lowered for word in VERIFICATION_WORDS)


def is_integration_test(path: str, source: str) -> bool:
    return "integration" in path or "mark.integration" in source


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def numeric(node: ast.AST) -> Optional[float]:
    """The value of a numeric literal expression, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = numeric(node.operand)
        if value is None:
            return None
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        left, right = numeric(node.left), numeric(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right if right else None
        if abs(right) > 64:
            return None
        return left ** right
    return None


NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|(?<![\w.])\.\d+(?:[eE][-+]?\d+)?")
FLIP = {"Lt": "Gt", "LtE": "GtE", "Gt": "Lt", "GtE": "LtE"}
OPERATOR_TEXT = {"Lt": "<", "LtE": "<=", "Gt": ">", "GtE": ">="}


class Scan(ast.NodeVisitor):
    """Everything the T-12 categories look for in one Python file."""

    def __init__(self, path: str, source: str):
        self.path = path
        self.source = source
        self._lines: Optional[List[bytes]] = None
        self.stack: List[str] = []
        self.functions = set()
        self.tests: List[Tuple[str, int]] = []
        self.skips: List[dict] = []
        self.tolerances: List[dict] = []
        self.filters: List[dict] = []
        self.handlers: List[dict] = []
        self.mocks: List[dict] = []
        self.warns: List[dict] = []
        self.checks: List[dict] = []
        self.test_marks: Dict[str, set] = {}
        self.class_marks: List[set] = [set()]
        self.in_assert = 0
        self.in_if = 0
        self.test_file = is_test_file(path)
        self.test_code = is_test_code(path)
        self.verification = is_verification_code(path)
        self.integration = is_integration_test(path, source)

    # helpers ----------------------------------------------------------------
    @property
    def qualname(self) -> str:
        return ".".join(self.stack) or "<module>"

    def segment(self, node: ast.AST) -> str:
        """The node's source text, whitespace collapsed (linear, unlike
        ``ast.get_source_segment``, which splits the file on every call)."""
        if self._lines is None:
            self._lines = [line.encode("utf-8") for line in
                           re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$", self.source)]
        try:
            first, last = node.lineno - 1, node.end_lineno - 1
            start, end = node.col_offset, node.end_col_offset
        except AttributeError:
            return collapse(ast.unparse(node))
        if first == last:
            data = self._lines[first][start:end]
        else:
            data = b"".join([self._lines[first][start:]] + self._lines[first + 1:last]
                            + [self._lines[last][:end]])
        return collapse(data.decode("utf-8", errors="replace"))

    def raw_line(self, lineno: int, end: Optional[int] = None) -> str:
        """The physical source lines, as ``git log -S`` sees them (at most ten)."""
        if self._lines is None:
            self.segment(ast.parse("0").body[0])
        end = min(end or lineno, lineno + 9, len(self._lines))
        return "\n".join(self._lines[number - 1].decode("utf-8", errors="replace").strip()
                         for number in range(max(lineno, 1), end + 1))

    def record(self, bucket: List[dict], kind: str, node: ast.AST, text: str, **extra):
        end = getattr(node, "end_lineno", None) or node.lineno
        bucket.append(dict(kind=kind, qualname=self.qualname, line=node.lineno, end=end,
                           text=text, raw=self.raw_line(node.lineno, end), **extra))

    # structure --------------------------------------------------------------
    @staticmethod
    def mark_names(node: Optional[ast.AST]) -> set:
        """Marker names applied by decorators or a ``pytestmark`` value."""
        names = set()
        if node is None:
            return names
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Attribute) \
                    and child.value.attr == "mark":
                names.add(child.attr)
        return names

    def _pytestmark(self, body: List[ast.AST]) -> set:
        names = set()
        for statement in body:
            if isinstance(statement, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "pytestmark" for target in statement.targets):
                names |= self.mark_names(statement.value)
        return names

    def visit_Module(self, node):
        self.class_marks = [self._pytestmark(node.body)]
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.class_marks.append(set().union(*[self.mark_names(d) for d in node.decorator_list])
                                | self._pytestmark(node.body))
        self.stack.append(node.name)
        self.functions.add(self.qualname)
        for child in node.body:
            self.visit(child)
        self.stack.pop()
        self.class_marks.pop()

    def _function(self, node):
        for decorator in node.decorator_list:
            self.visit(decorator)
        if self.test_file and node.name.startswith("test") and (
                not self.stack or (len(self.stack) == 1 and self.stack[0].startswith("Test"))):
            self.tests.append(("::".join(self.stack + [node.name]), node.lineno))
            self.test_marks["::".join(self.stack + [node.name])] = set().union(
                *self.class_marks, *[self.mark_names(d) for d in node.decorator_list])
        self.stack.append(node.name)
        self.functions.add(self.qualname)
        arguments = node.args
        positional = arguments.posonlyargs + arguments.args
        for arg, default in zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults):
            self._named_tolerance("default", arg.arg, default, default)
        for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            if default is not None:
                self._named_tolerance("default", arg.arg, default, default)
        for default in list(arguments.defaults) + [d for d in arguments.kw_defaults if d is not None]:
            self.visit(default)
        for child in node.body:
            self.visit(child)
        self.stack.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    # tolerances -------------------------------------------------------------
    def _named_tolerance(self, kind: str, name: str, value_node: ast.AST, node: ast.AST):
        value = numeric(value_node)
        if value is None:
            return
        self.tolerances.append(dict(kind=kind, qualname=self.qualname, line=node.lineno, key=name,
                                    value=value, larger_is_looser=True,
                                    text=(name + " = " + self.segment(value_node))[:160],
                                    raw=self.raw_line(node.lineno)))

    def visit_Assign(self, node):
        for target in node.targets:
            name = self._target_name(target)
            if name and TOL_NAME.search(name.split(".")[-1]):
                self._named_tolerance("name", name, node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        name = self._target_name(node.target)
        if name and node.value is not None and TOL_NAME.search(name.split(".")[-1]):
            self._named_tolerance("name", name, node.value, node)
        self.generic_visit(node)

    @staticmethod
    def _target_name(target: ast.AST) -> Optional[str]:
        if isinstance(target, ast.Name):
            return target.id
        if isinstance(target, ast.Attribute):
            return ast.unparse(target)
        return None

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and TOL_NAME.search(key.value):
                value_number = numeric(value)
                if value_number is not None:
                    self.tolerances.append(dict(kind="dict", qualname=self.qualname, line=key.lineno,
                                                key=key.value, value=value_number, larger_is_looser=True,
                                                text=(repr(key.value) + ": " + self.segment(value))[:160],
                                                raw=self.raw_line(key.lineno)))
        self.generic_visit(node)

    def visit_Assert(self, node):
        if self.test_code or self.verification:
            self.record(self.checks, "assert", node, self.segment(node.test)[:240])
        self.in_assert += 1
        self.generic_visit(node)
        self.in_assert -= 1

    def visit_If(self, node):
        self.in_if += 1
        self.visit(node.test)
        self.in_if -= 1
        for child in node.body + node.orelse:
            self.visit(child)

    def _is_tolerance_operand(self, node: ast.AST) -> bool:
        value = numeric(node)
        if value is not None:
            return value != int(value) and abs(value) < 1
        text = ast.unparse(node) if isinstance(node, (ast.Name, ast.Attribute)) else ""
        return bool(text) and bool(TOL_NAME.search(text.split(".")[-1]))

    def visit_Compare(self, node):
        if self.in_if and not self.in_assert and self.verification and \
                any(type(op).__name__ in OPERATOR_TEXT for op in node.ops) and \
                any(self._is_tolerance_operand(operand) for operand in [node.left] + list(node.comparators)):
            self.record(self.checks, "if-compare", node, self.segment(node)[:240])
        if self.in_assert or (self.in_if and self.verification):
            operands = [node.left] + list(node.comparators)
            for index, operator in enumerate(node.ops):
                name = type(operator).__name__
                if name not in OPERATOR_TEXT:
                    continue
                left, right = operands[index], operands[index + 1]
                lvalue, rvalue = numeric(left), numeric(right)
                if (lvalue is None) == (rvalue is None):
                    continue
                if rvalue is None:              # literal on the left: normalise
                    left, right, name, rvalue = right, left, FLIP[name], lvalue
                if self.in_if and not self.in_assert:
                    # an if-test is a tolerance only when it compares with a
                    # small non-integer literal; loop bounds and counts are not
                    if rvalue == int(rvalue) or abs(rvalue) >= 1:
                        continue
                # in an assert the bound is what passes (x < N: larger N is
                # looser); an if-test may guard the failure or the success
                # branch, so its direction is left to the reviewer
                self.tolerances.append(dict(
                    kind="assert" if self.in_assert else "if", qualname=self.qualname, line=node.lineno,
                    key=self.segment(left)[:120] + " " + OPERATOR_TEXT[name], value=rvalue,
                    larger_is_looser=(name in ("Lt", "LtE")) if self.in_assert else None,
                    text=self.segment(node)[:160], raw=self.raw_line(node.lineno)))
        self.generic_visit(node)

    # calls: tolerances, skips, filters, mocks, warns ---------------------------
    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        callee = ast.unparse(func)
        for keyword in node.keywords:
            if keyword.arg is None:
                continue
            if TOL_NAME.search(keyword.arg) or (keyword.arg in APPROX_KWARGS and name == "approx") \
                    or keyword.arg in PRECISION_KWARGS:
                value = numeric(keyword.value)
                if value is not None:
                    self.tolerances.append(dict(
                        kind="kwarg", qualname=self.qualname, line=node.lineno,
                        key=callee[:80] + ":" + keyword.arg, value=value,
                        larger_is_looser=keyword.arg not in PRECISION_KWARGS,
                        text=self.segment(node)[:160], raw=self.raw_line(keyword.value.lineno)))
        if self.test_code and (name.startswith("assert") or
                               (name in ("raises", "warns") and callee.startswith("pytest."))):
            self.record(self.checks, "call:" + name, node, self.segment(node)[:240])
        interesting = (name in SKIP_CALLS or name in ("filterwarnings", "simplefilter", "warn")
                       or (self.test_code and (name in MOCK_CALLS or name in MONKEYPATCH_CALLS
                                               or callee.startswith(("mock.", "unittest.mock.", "patch.")))))
        text = self.segment(node) if interesting else ""
        if name in SKIP_CALLS and (callee.startswith(("pytest.", "unittest.", "self.")) or isinstance(func, ast.Name)):
            if not self._is_mark(func):
                self.record(self.skips, "call:" + name, node, text[:300])
        if name == "pytest_deselected":
            self.record(self.skips, "hook:pytest_deselected", node, self.segment(node)[:300])
        if name in ("filterwarnings", "simplefilter") and not self._is_mark(func):
            self.record(self.filters, "call:" + name, node, text[:300])
        if name == "warn" and callee in ("warnings.warn", "warn"):
            self.record(self.warns, "warnings.warn", node, text[:300])
        if self.test_code:
            if name in MOCK_CALLS or callee.startswith(("mock.", "unittest.mock.")) or \
                    (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                     and func.value.id == "patch"):
                self.record(self.mocks, "mock:" + name, node, text[:300], integration=self.integration)
            elif isinstance(func, ast.Attribute) and name in MONKEYPATCH_CALLS and \
                    "monkeypatch" in ast.unparse(func.value):
                self.record(self.mocks, "monkeypatch." + name, node, text[:300], integration=self.integration)
        self.generic_visit(node)

    @staticmethod
    def _is_mark(func: ast.AST) -> bool:
        return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute) \
            and func.value.attr == "mark"

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Attribute) and node.value.attr == "mark":
            if node.attr in MARK_SKIPS:
                self.record(self.skips, "mark." + node.attr, node, self._marker_text(node))
            elif node.attr == "filterwarnings":
                self.record(self.filters, "mark.filterwarnings", node, self._marker_text(node))
        self.generic_visit(node)

    def _marker_text(self, node: ast.Attribute) -> str:
        # the whole marker call when there is one, so a changed reason shows
        call = getattr(node, "_call_parent", None)
        return (self.segment(call) if call is not None else self.segment(node))[:300]

    def visit_Raise(self, node):
        if node.exc is not None:
            exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if ast.unparse(exc).endswith(("SkipTest", "skip.Exception")):
                self.record(self.skips, "raise:SkipTest", node, self.segment(node)[:300])
        self.generic_visit(node)

    # imports of mock libraries -----------------------------------------------
    def visit_Import(self, node):
        if self.test_code:
            for alias in node.names:
                if alias.name in ("mock", "unittest.mock"):
                    self.record(self.mocks, "import", node, self.segment(node), integration=self.integration)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if self.test_code and (node.module in ("unittest.mock", "mock") or
                               (node.module == "unittest" and any(a.name == "mock" for a in node.names))):
            self.record(self.mocks, "import", node, self.segment(node), integration=self.integration)
        self.generic_visit(node)

    # exception handlers -------------------------------------------------------
    def visit_ExceptHandler(self, node):
        broad = self._broad(node.type)
        if broad:
            body = node.body
            reraises = any(isinstance(child, ast.Raise) for statement in body for child in ast.walk(statement))
            first = self.segment(body[0]) if body else ""
            self.record(self.handlers, broad, node, collapse(first)[:160], reraises=reraises)
        self.generic_visit(node)

    @staticmethod
    def _broad(node: Optional[ast.AST]) -> Optional[str]:
        if node is None:
            return "bare except"
        names = node.elts if isinstance(node, ast.Tuple) else [node]
        for item in names:
            text = ast.unparse(item)
            if text.split(".")[-1] in ("Exception", "BaseException"):
                return "except " + ast.unparse(node)
        return None


def attach_marker_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            node.func._call_parent = node


REGEX_FALLBACK = (
    ("broad_except", re.compile(r"^\s*except\s*(?::|\(?\s*(?:[\w.]*\.)?(?:Base)?Exception\b)")),
    ("skip", re.compile(r"pytest\.(?:skip|importorskip|xfail)\(|mark\.(?:skip|skipif|xfail)\b")),
    ("warning_filter", re.compile(r"\b(?:filterwarnings|simplefilter)\(")),
)


def scan_python(path: str, source: str) -> Tuple[Optional[Scan], List[dict]]:
    """Scan one file; if it does not parse as Python 3, fall back to line patterns."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        found = []
        for number, line in enumerate(source.splitlines(), 1):
            for category, pattern in REGEX_FALLBACK:
                if pattern.search(line):
                    found.append(dict(category=category, line=number, text=collapse(line)[:200]))
        return None, found
    attach_marker_calls(tree)
    scan = Scan(path, source)
    scan.visit(tree)
    return scan, []


# --------------------------------------------------------------------------
# T-12

def finding_id(category: str, *parts: str) -> str:
    return ":".join([category] + [str(part) for part in parts])


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:8]


def multiset_added(old: List[dict], new: List[dict], key) -> List[dict]:
    """Entries of ``new`` beyond what ``old`` already had, per key."""
    counts: Dict[str, int] = {}
    for item in old:
        counts[key(item)] = counts.get(key(item), 0) + 1
    added = []
    for item in new:
        k = key(item)
        if counts.get(k, 0):
            counts[k] -= 1
        else:
            added.append(item)
    return added


class T12:
    def __init__(self, base: Revision, head: Revision):
        self.base, self.head = base, head
        self.root = base.root
        self.renames = rename_map(base.commit, head.commit, self.root)
        self.findings: List[dict] = []
        self.base_scans: Dict[str, Scan] = {}
        self.head_scans: Dict[str, Scan] = {}
        self.fallback: Dict[Tuple[str, str], List[dict]] = {}
        self.unparsed: Dict[str, List[str]] = {"base": [], "head": []}
        for label, revision, scans in (("base", base, self.base_scans), ("head", head, self.head_scans)):
            for path in revision.files:
                if not path.endswith(".py"):
                    continue
                source = revision.text(path)
                if source is None:
                    continue
                scan, fallback = scan_python(path, source)
                if scan is None:
                    self.unparsed[label].append(path)
                    self.fallback[(label, path)] = fallback
                else:
                    scans[path] = scan

    def mapped(self, base_path: str) -> str:
        return self.renames.get(base_path, base_path)

    def add(self, category: str, fid: str, path: str, summary: str, **detail):
        self.findings.append(dict(id=fid, category=category, path=path, summary=summary, **detail))

    def introduced_by(self, needle: str, paths: Iterable[str], lines: Optional[Tuple[str, int, int]] = None
                      ) -> List[str]:
        """The commits since the baseline that added or removed ``needle``.

        Each physical line of the needle is tried with ``git log -S`` until one
        changes count; failing that, ``git log -L`` over the lines at the
        audited commit (``lines`` = path, first, last)."""
        paths = list(paths)
        for line in (needle or "").splitlines():
            line = line.strip()
            if len(line) < 4 or line in ("pytest.skip(", "assert (", "warnings.warn("):
                continue
            found = pickaxe(self.base.commit, self.head.commit, line[:200], paths, self.root)
            if found:
                return found
        if lines is not None:
            path, first, last = lines
            out = git("log", "--format=%h", "-s", f"-L{first},{last}:{path}",
                      f"{self.base.commit}..{self.head.commit}", root=self.root)
            return [commit for commit in out.split() if commit]
        return []

    # 1. deleted or renamed tests ---------------------------------------------------
    def deleted_tests(self):
        head_ids = {}
        for path, scan in self.head_scans.items():
            for node, line in scan.tests:
                head_ids[f"{path}::{node}"] = line
        by_name: Dict[str, List[str]] = {}
        for node_id in head_ids:
            by_name.setdefault(node_id.rsplit("::", 1)[1], []).append(node_id)
        base_files = sorted(set(p for p in self.base.files if is_test_file(p)))
        for path in base_files:
            scan = self.base_scans.get(path)
            target = self.mapped(path)
            if path not in self.head and target == path:
                self.add("deleted_test", finding_id("deleted_test", path), path,
                         "test file deleted",
                         tests=[node for node, _ in scan.tests] if scan else [],
                         commits=self._deleting_commits(path))
            elif target != path:
                self.add("deleted_test", finding_id("deleted_test", path), path,
                         f"test file renamed to {target}", moved_to=target,
                         commits=self._deleting_commits(path))
            if scan is None:
                continue
            for node, _line in scan.tests:
                if f"{target}::{node}" in head_ids:
                    continue
                name = node.rsplit("::", 1)[-1]
                candidates = sorted(by_name.get(name, []))
                self.add("deleted_test", finding_id("deleted_test", f"{path}::{node}"), path,
                         "test function no longer exists" + (" here" if candidates else ""),
                         candidates=candidates,
                         commits=pickaxe(self.base.commit, self.head.commit, f"def {name}(", [path, target], self.root))
        for label in ("base", "head"):
            for path in self.unparsed[label]:
                if is_test_file(path):
                    self.add("deleted_test", finding_id("deleted_test", "unparsed", label, path), path,
                             f"test file does not parse as Python 3 at {label}; its tests were not compared")

    def _deleting_commits(self, path: str) -> List[str]:
        out = git("log", "--format=%h", "--diff-filter=DR", f"{self.base.commit}..{self.head.commit}", "--", path,
                  root=self.root)
        return out.split()

    # generic multiset comparisons ----------------------------------------------------
    def _compare(self, category: str, attribute: str, key, summary, needle, only=None):
        for path, scan in sorted(self.head_scans.items()):
            if only and not only(path, scan):
                continue
            base_path = next((old for old, new in self.renames.items() if new == path), path)
            base_scan = self.base_scans.get(base_path)
            old = getattr(base_scan, attribute) if base_scan else []
            new = getattr(scan, attribute)
            for item in multiset_added(old, new, key):
                fid = finding_id(category, path, item["qualname"], item["kind"], short_hash(key(item)))
                self.add(category, fid, path, summary(item), line=item["line"], qualname=item["qualname"],
                         text=item["text"], **{k: v for k, v in item.items()
                                               if k not in ("kind", "qualname", "line", "text")},
                         commits=self.introduced_by(item.get("raw") or needle(item), [path, base_path],
                                                    lines=(path, item["line"], item.get("end", item["line"]))))
        for path in self.unparsed["head"]:
            base_path = next((old for old, new in self.renames.items() if new == path), path)
            old = self.fallback.get(("base", base_path), [])
            new = self.fallback.get(("head", path), [])
            for item in multiset_added([o for o in old if o["category"] == category],
                                       [n for n in new if n["category"] == category],
                                       key=lambda item: item["text"]):
                fid = finding_id(category, path, "<unparsed>", short_hash(item["text"]))
                self.add(category, fid, path, "pattern added in a file that is not Python 3 (line match)",
                         line=item["line"], text=item["text"],
                         commits=self.introduced_by(item["text"], [path, base_path]))

    #: markers the offline suites deselect (CI: -m "not abaqus and not arc and
    #: not network"; conftest hooks deselect gui and corpus_pass by default)
    DESELECTING_MARKERS = {"abaqus", "arc", "network", "gui", "corpus_pass", "browser", "skip", "skipif", "xfail"}
    CI_FILE = re.compile(r"(^\.github/workflows/.*\.ya?ml$|(^|/)Makefile$|\.sh$|\.ps1$|(^|/)tox\.ini$|(^|/)noxfile\.py$)")
    CI_PATTERN = re.compile(
        r"""(-m\s+["'][^"']*\bnot\b|--deselect|\s-k\s|continue-on-error|\|\|\s*(true|:)\b|set\s+\+e"""
        r"""|--ignore|allow_failure|\bskip|xfail|declared\s*=|-p\s*no:)""", re.IGNORECASE)

    def skips(self):
        self._compare("skip", "skips", key=lambda i: f"{i['qualname']}|{i['kind']}|{i['text']}",
                      summary=lambda i: f"{i['kind']} added", needle=lambda i: i["text"])
        # a marker that deselects an existing test in the offline run
        for base_path, scan in sorted(self.base_scans.items()):
            path = self.mapped(base_path)
            head_scan = self.head_scans.get(path)
            if head_scan is None:
                continue
            for node, marks in sorted(scan.test_marks.items()):
                if node not in head_scan.test_marks:
                    continue
                for mark in sorted((head_scan.test_marks[node] - marks) & self.DESELECTING_MARKERS):
                    self.add("skip", finding_id("skip", path, node, "marker", mark), path,
                             f"existing test now marked {mark}", qualname=node, text=f"pytest.mark.{mark}",
                             commits=self.introduced_by(f"mark.{mark}", [base_path, path]))
        # deselection in CI workflows, Makefiles and shell scripts
        for path in sorted(set(self.head.files)):
            if not self.CI_FILE.search(path):
                continue
            base_path = next((old for old, new in self.renames.items() if new == path), path)
            before = [line.strip() for line in (self.base.text(base_path) or "").splitlines()]
            after = [line.strip() for line in (self.head.text(path) or "").splitlines()]
            for line in multiset_added(before, after, key=lambda x: x):
                if line and self.CI_PATTERN.search(line):
                    self.add("skip", finding_id("skip", path, "ci-line", short_hash(line)), path,
                             "CI or script line that selects, ignores or tolerates results", text=line[:300],
                             commits=self.introduced_by(line, [base_path, path]))

    def warning_filters(self):
        self._compare("warning_filter", "filters", key=lambda i: f"{i['qualname']}|{i['kind']}|{i['text']}",
                      summary=lambda i: f"{i['kind']} added", needle=lambda i: i["text"])
        # configuration files
        for path in ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"):
            old = {entry for entry, _ in self._config_filters(self.base.text(path))}
            for entry, needle in self._config_filters(self.head.text(path)):
                if entry not in old:
                    self.add("warning_filter", finding_id("warning_filter", path, short_hash(entry)), path,
                             "warning filter or option added to pytest configuration", text=entry,
                             commits=self.introduced_by(needle, [path]))

    @staticmethod
    def _config_filters(text: Optional[str]) -> List[Tuple[str, str]]:
        """(entry, the text as written) for each warning filter and warning option."""
        if not text:
            return []
        entries = []
        block = re.search(r"(?ms)^filterwarnings\s*=\s*(\[.*?\]|.*?)(?=^\S|\Z)", text)
        if block:
            items = re.findall(r"[\"']([^\"']+)[\"']", block.group(1)) or \
                [line.strip() for line in block.group(1).splitlines() if line.strip()]
            entries += [("filterwarnings " + collapse(item), item) for item in items]
        for addopts in re.findall(r"(?m)^addopts\s*=\s*(.*)$", text):
            for option in re.findall(r"(-W\s*\S+|-p\s*no:warnings|--disable-warnings)", addopts):
                entries.append(("addopts " + collapse(option), option))
        return entries

    def broad_handlers(self):
        self._compare("broad_except", "handlers", key=lambda i: f"{i['qualname']}|{i['kind']}",
                      summary=lambda i: f"{i['kind']} added" + (" (re-raises)" if i.get("reraises") else ""),
                      needle=lambda i: i["kind"].replace("bare except", "except:"))

    def mocks(self):
        self._compare("mock", "mocks", key=lambda i: f"{i['qualname']}|{i['kind']}|{i['text']}",
                      summary=lambda i: f"{i['kind']} added" + (" in an integration test" if i.get("integration") else ""),
                      needle=lambda i: i["text"])

    def warn_calls(self):
        self._compare("warn_call", "warns", key=lambda i: f"{i['qualname']}|{i['text']}",
                      summary=lambda i: "warnings.warn added", needle=lambda i: i["text"])

    # 3. tolerances ------------------------------------------------------------------
    def tolerances(self):
        def table(scans: Dict[str, Scan], mapping) -> Dict[tuple, List[dict]]:
            result: Dict[tuple, List[dict]] = {}
            for path, scan in scans.items():
                target = mapping(path)
                for item in scan.tolerances:
                    if item["kind"] == "if" and not is_verification_code(target):
                        continue
                    result.setdefault((target, item["qualname"], item["kind"], item["key"]), []).append(item)
            return result

        old = table(self.base_scans, self.mapped)
        new = table(self.head_scans, lambda path: path)
        head_functions = {(path, name) for path, scan in self.head_scans.items() for name in scan.functions}
        head_by_key: Dict[tuple, List[float]] = {}
        for (path, qualname, kind, key), items in new.items():
            head_by_key.setdefault((kind, key), []).extend(i["value"] for i in items)
        for full_key in sorted(set(old) | set(new)):
            path, qualname, kind, key = full_key
            before = old.get(full_key, [])
            after = new.get(full_key, [])
            if not before:
                continue                      # a new check, not a changed one
            old_values = [i["value"] for i in before]
            new_values = [i["value"] for i in after]
            if sorted(old_values) == sorted(new_values):
                continue
            larger_is_looser = before[0]["larger_is_looser"]
            fid = finding_id("tolerance", path, qualname, kind, key)
            if not after:
                if kind in ("assert", "if") and (is_test_code(path) or is_verification_code(path)):
                    continue                  # the whole check went: reported as removed_check
                function_exists = qualname == "<module>" or (path, qualname) in head_functions
                moved = all(v in head_by_key.get((kind, key), []) for v in old_values)
                if not function_exists and moved:
                    continue                  # the same tolerance, same value, now in another function
                change = "removed"
            elif len(old_values) == len(new_values):
                pairs = [(o, n) for o, n in zip(old_values, new_values) if n != o]
                if larger_is_looser is None:
                    change = "changed"        # direction depends on the branch the test guards
                else:
                    looser = any((n > o) if larger_is_looser else (n < o) for o, n in pairs)
                    tighter = any((n < o) if larger_is_looser else (n > o) for o, n in pairs)
                    change = "loosened" if looser and not tighter else \
                        "tightened" if tighter and not looser else "mixed"
            else:
                remaining = list(new_values)
                missing = []
                for value in old_values:
                    if value in remaining:
                        remaining.remove(value)
                    else:
                        missing.append(value)
                if not missing:
                    continue                  # only new occurrences were added
                change = "removed" if not remaining else "changed"
            commits = self.introduced_by(before[0]["raw"], [path])
            if after:
                commits += [c for c in self.introduced_by(after[0]["raw"], [path]) if c not in commits]
            self.add("tolerance", fid, path,
                     f"{kind} {key}: {change} {old_values} -> {new_values}",
                     qualname=qualname, change=change, old=old_values, new=new_values,
                     line=(after or before)[0]["line"], text=(after or before)[0]["text"],
                     old_text=before[0]["text"], commits=commits)

    # removed assertions and tolerance checks ----------------------------------------------
    def removed_checks(self):
        head_checks: Dict[Tuple[str, str], List[dict]] = {}
        anywhere = set()
        for path, scan in self.head_scans.items():
            for item in scan.checks:
                head_checks.setdefault((path, item["qualname"]), []).append(item)
                anywhere.add(item["text"])
        head_functions = {(path, name) for path, scan in self.head_scans.items() for name in scan.functions}
        for base_path, scan in sorted(self.base_scans.items()):
            path = self.mapped(base_path)
            groups: Dict[str, List[dict]] = {}
            for item in scan.checks:
                groups.setdefault(item["qualname"], []).append(item)
            for qualname, items in sorted(groups.items()):
                after = head_checks.get((path, qualname), [])
                removed = multiset_added(after, items, key=lambda item: item["text"])
                if not removed:
                    continue
                exists = qualname == "<module>" or (path, qualname) in head_functions
                if not exists:
                    test_node = is_test_file(base_path) and qualname.split(".")[-1].startswith("test")
                    if test_node:
                        continue              # the test itself went: reported as deleted_test
                    removed = [item for item in removed if item["text"] not in anywhere]
                added = [item["text"] for item in multiset_added(items, after, key=lambda item: item["text"])]
                # an assertion whose only change is a tolerance it carries is
                # reported once, as that tolerance's change
                tolerance_lines = {t["line"] for t in scan.tolerances if t["kind"] in ("assert", "if", "kwarg")}
                numbers_blind = {NUMBER.sub("#", text) for text in added}
                removed = [item for item in removed
                           if not (item["line"] in tolerance_lines and NUMBER.sub("#", item["text"]) in numbers_blind)]
                for item in removed:
                    fid = finding_id("removed_check", path, qualname, short_hash(item["text"]))
                    self.add("removed_check", fid, path,
                             f"{item['kind']} removed" + ("" if exists else " (its function no longer exists)"),
                             qualname=qualname, line=item["line"], text=item["text"],
                             added_in_same_function=added,
                             commits=self.introduced_by(item["raw"], [base_path, path]))

    # 6. deleted examples -------------------------------------------------------------
    def deleted_examples(self):
        for status, path, target in name_status(self.base.commit, self.head.commit, self.root):
            if status not in ("D", "R"):
                continue
            lowered = path.lower()
            if not any(word in lowered for word in ("example", "demo", "walkthrough", "tutorial", "templates/")):
                continue
            summary = "example file deleted" if status == "D" else f"example file renamed to {target}"
            commits = git("log", "--format=%h", "--diff-filter=DR", f"{self.base.commit}..{self.head.commit}",
                          "--", path, root=self.root).split()
            # a renamed file is named by where it went: the review file then
            # never has to repeat a name the repository has given up
            fid = finding_id("deleted_example", path) if status == "D" else \
                finding_id("deleted_example", "renamed-to", target)
            self.add("deleted_example", fid, path, summary, moved_to=target, commits=commits)

    # 7. metadata -----------------------------------------------------------------------
    def metadata(self):
        for path in ("pyproject.toml", "setup.py", "setup.cfg"):
            old, new = self.base.text(path), self.head.text(path)
            for field, extract in (("classifier", self._classifiers), ("requires-python", self._requires)):
                before, after = extract(old), extract(new)
                for value in sorted(set(before) ^ set(after)):
                    sign = "+" if value in after else "-"
                    self.add("metadata", finding_id("metadata", path, field, sign + value), path,
                             f"{field} {'added' if sign == '+' else 'removed'}: {value}", text=value,
                             commits=self.introduced_by(value, [path]))
        for path in ("codemeta.json", ".zenodo.json"):
            before, after = self._flatten_json(self.base.text(path)), self._flatten_json(self.head.text(path))
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key):
                    self.add("metadata", finding_id("metadata", path, key), path,
                             f"{key}: {before.get(key)!r} -> {after.get(key)!r}",
                             old=before.get(key), new=after.get(key),
                             commits=self.introduced_by(str(after.get(key) or before.get(key)), [path]))
        for path in ("CITATION.cff",):
            before = self._lines(self.base.text(path))
            after = self._lines(self.head.text(path))
            for line in multiset_added(before, after, key=lambda x: x):
                self.add("metadata", finding_id("metadata", path, "+" + line), path, f"line added: {line}",
                         text=line, commits=self.introduced_by(line, [path]))
            for line in multiset_added(after, before, key=lambda x: x):
                self.add("metadata", finding_id("metadata", path, "-" + line), path, f"line removed: {line}",
                         text=line, commits=self.introduced_by(line, [path]))

    @staticmethod
    def _classifiers(text: Optional[str]) -> List[str]:
        if not text:
            return []
        block = re.search(r"(?s)classifiers\s*=\s*\[(.*?)\]", text)
        return re.findall(r"[\"']([^\"']+)[\"']", block.group(1)) if block else []

    @staticmethod
    def _requires(text: Optional[str]) -> List[str]:
        if not text:
            return []
        return [collapse(m) for m in re.findall(r"(?m)^\s*(?:requires-python|python_requires)\s*=\s*(.+?)\s*,?$", text)]

    @staticmethod
    def _flatten_json(text: Optional[str]) -> Dict[str, str]:
        if not text:
            return {}
        flat: Dict[str, str] = {}

        def walk(value, prefix):
            if isinstance(value, dict):
                for key in value:
                    walk(value[key], f"{prefix}.{key}" if prefix else key)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{prefix}[{index}]")
            else:
                flat[prefix] = json.dumps(value, ensure_ascii=False)
        walk(json.loads(text), "")
        return flat

    @staticmethod
    def _lines(text: Optional[str]) -> List[str]:
        return [line.rstrip() for line in (text or "").splitlines() if line.strip()]

    # 9. reference data --------------------------------------------------------------------
    REFERENCE_PARTS = ("fixtures", "expected", "golden", "reference", "references", "baseline",
                       "baselines", "snapshots", "paper_results")

    def reference_data(self):
        for status, path, target in name_status(self.base.commit, self.head.commit, self.root):
            if status not in ("M", "D", "R"):
                continue
            parts = path.lower().split("/")
            if not (any(part in self.REFERENCE_PARTS for part in parts[:-1]) or
                    any(word in parts[-1] for word in ("expected", "golden", "reference", "baseline"))):
                continue
            if path.endswith((".py", ".md")):
                continue
            commits = git("log", "--format=%h", f"{self.base.commit}..{self.head.commit}", "--", path,
                          root=self.root).split()
            summary = {"M": "reference data modified", "D": "reference data deleted",
                       "R": f"reference data renamed to {target}"}[status]
            self.add("reference_data", finding_id("reference_data", path), path, summary, commits=commits)

    def run(self) -> List[dict]:
        self.deleted_tests()
        self.skips()
        self.tolerances()
        self.removed_checks()
        self.warning_filters()
        self.broad_handlers()
        self.deleted_examples()
        self.metadata()
        self.mocks()
        self.warn_calls()
        self.reference_data()
        seen = {}
        for finding in self.findings:
            if finding["id"] in seen:           # identical key twice: number them
                seen[finding["id"]] += 1
                finding["id"] += f"#{seen[finding['id']]}"
            else:
                seen[finding["id"]] = 1
        return sorted(self.findings, key=lambda f: (T12_CATEGORIES.index(f["category"]), f["id"]))


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"missing data file: {path.relative_to(REPO_ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def text_at(where: str, base: Revision, head: Revision) -> Optional[str]:
    """What a review entry points at: a commit's message (a hash), a file of
    the baseline commit (``BASE:path``) or a file of the audited commit."""
    if re.fullmatch(r"[0-9a-f]{7,40}", where):
        try:
            return git("log", "-1", "--format=%B", where)
        except GitError:
            return None
    if where.startswith("BASE:"):
        return base.text(where[5:])
    return head.text(where)


def check_evidence(entry: dict, base: Revision, head: Revision) -> List[str]:
    """Every quoted passage must really be where the entry says it is."""
    problems = []
    items = list(entry.get("evidence", []))
    if entry.get("quote"):
        items.append({"in": entry.get("quote_source", ""), "text": entry["quote"]})
    for item in items:
        text = text_at(item.get("in", ""), base, head)
        if text is None:
            problems.append(f"{item.get('in')!r} does not exist")
        elif collapse(item["text"]) not in collapse(text):
            problems.append(f"text not found in {item['in']}: {item['text'][:60]!r}")
    return problems


def check_moved_to(entry: dict, head: Revision, head_tests: Dict[str, set]) -> Optional[str]:
    target = entry.get("moved_to")
    if not target:
        return None
    if "::" in target:
        path, node = target.split("::", 1)
        return None if node in head_tests.get(path, set()) else f"moved_to {target} does not exist"
    return None if target in head else f"moved_to {target} does not exist"


def check_json_only_changed(entry: dict, finding: dict, base: Revision, head: Revision) -> Optional[str]:
    """For reference data said to differ only in some fields, prove it."""
    allowed = entry.get("json_only_changed")
    if allowed is None:
        return None
    before = T12._flatten_json(base.text(finding["path"]))
    after = T12._flatten_json(head.text(finding["path"]))
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    outside = [key for key in changed if not any(key == a or key.startswith(a + ".") or key.startswith(a + "[")
                                                 for a in allowed)]
    return f"fields outside {allowed} changed: {outside[:5]}" if outside else None


#: A justified entry for these changes must quote the reasoning that allows it.
NEEDS_QUOTE = {("tolerance", "loosened"), ("tolerance", "mixed"), ("tolerance", "changed"),
               ("tolerance", "removed"), ("removed_check", "if-compare removed")}


def audit_pre_work_failures(review: dict, head_tests: Dict[str, set]) -> List[str]:
    """Tests that failed in the recorded pre-work run must still exist."""
    problems = []
    for node, entry in sorted(review.get("pre_work_failures", {}).items()):
        path, _, name = node.partition("::")
        present = name in head_tests.get(path, set()) if name else path in head_tests
        if entry.get("status") == "present":
            if not present:
                problems.append(f"pre-work failure {node} no longer exists")
        elif entry.get("status") == "renamed":
            now_path, _, now_name = entry.get("now", "").partition("::")
            if present or now_name not in head_tests.get(now_path, set()):
                problems.append(f"pre-work failure {node}: rename to {entry.get('now')} does not hold")
            if not entry.get("reason", "").strip():
                problems.append(f"pre-work failure {node}: renamed without a reason")
        else:
            problems.append(f"pre-work failure {node}: status must be present or renamed")
    return problems


def audit_t12(base: Revision, head: Revision) -> dict:
    scanner = T12(base, head)
    findings = scanner.run()
    review = load_json(REPO_ROOT / REVIEW_FILE)
    if review.get("baseline") != base.commit:
        raise SystemExit(f"{REVIEW_FILE} reviews baseline {review.get('baseline')}, not {base.commit}")
    entries = review.get("findings", {})
    head_tests = {path: {node for node, _ in scan.tests} for path, scan in scanner.head_scans.items()}
    unexplained, violations, problems = [], [], []
    for finding in findings:
        entry = entries.get(finding["id"])
        if entry is None:
            unexplained.append(finding["id"])
            continue
        finding["review"] = entry
        verdict = entry.get("verdict")
        if verdict not in ("justified", "violation"):
            problems.append(f"{finding['id']}: verdict must be justified or violation")
        if not entry.get("reason", "").strip():
            problems.append(f"{finding['id']}: no reason")
        change = finding.get("change") or finding["summary"].split(" (")[0]
        if (finding["category"], change) in NEEDS_QUOTE and verdict == "justified" and not entry.get("quote"):
            problems.append(f"{finding['id']}: a justified '{change}' needs the quoted reasoning")
        problems += [f"{finding['id']}: {problem}" for problem in check_evidence(entry, base, head)]
        for check in (check_moved_to(entry, head, head_tests),
                      check_json_only_changed(entry, finding, base, head)):
            if check:
                problems.append(f"{finding['id']}: {check}")
        if verdict == "violation":
            violations.append(finding["id"])
    problems += audit_pre_work_failures(review, head_tests)
    found_ids = {finding["id"] for finding in findings}
    stale = sorted(set(entries) - found_ids)
    counts = {category: sum(f["category"] == category for f in findings) for category in T12_CATEGORIES}
    return dict(check="t12", baseline=base.commit, head=head.commit, counts=counts,
                unparsed_python=scanner.unparsed, findings=findings,
                unexplained=unexplained, stale=stale, problems=problems, violations=violations)


# --------------------------------------------------------------------------
# T-11

def commits_since(base: str, head: str) -> List[dict]:
    out = git("log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{base}..{head}")
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        full, subject, body = (record.split("\x1f") + ["", "", ""])[:3]
        # trailers name who wrote the commit or where it was picked from; they
        # say nothing about what it fixed
        body = "\n".join(line for line in body.splitlines()
                         if not re.match(r"\s*(Co-Authored-By:|\(cherry picked from)", line))
        commits.append(dict(commit=full, subject=subject, body=body.strip()))
    return commits


def changelog_fixed_entries(text: str) -> List[str]:
    """Bullets under every ``### Fixed`` heading of a keep-a-changelog file."""
    entries: List[str] = []
    current: Optional[str] = None
    inside = False
    for line in text.splitlines():
        if line.startswith("#"):
            if current:
                entries.append(current)
                current = None
            inside = line.strip().lstrip("#").strip().lower() == "fixed"
            continue
        if not inside:
            continue
        if re.match(r"^[-*] ", line):
            if current:
                entries.append(current)
            current = line[2:].strip()
        elif line.strip() and current is not None:
            current += " " + line.strip()
        elif not line.strip() and current:
            entries.append(current)
            current = None
    if current:
        entries.append(current)
    return [collapse(entry) for entry in entries]


def changelog_fixed_added(base: Revision, head: Revision) -> List[str]:
    before = set(changelog_fixed_entries(base.text("CHANGELOG.md") or ""))
    return [entry for entry in changelog_fixed_entries(head.text("CHANGELOG.md") or "") if entry not in before]


def node_exists(node: str, head: Revision, cache: Dict[str, Optional[set]]) -> bool:
    path, _, rest = node.partition("::")
    if path not in cache:
        source = head.text(path)
        scan = scan_python(path, source)[0] if source is not None else None
        cache[path] = {name for name, _ in scan.tests} if scan else (set() if source is not None else None)
    if cache[path] is None:
        return False
    return not rest or rest.split("[")[0] in cache[path]


def audit_t11(base: Revision, head: Revision) -> dict:
    """Every fix commit since the baseline is mapped to existing regression tests."""
    data = load_json(REPO_ROOT / FIX_MAP_FILE)
    if data.get("baseline") != base.commit:
        raise SystemExit(f"{FIX_MAP_FILE} maps baseline {data.get('baseline')}, not {base.commit}")
    rule = data["rule"]
    pattern = re.compile(rule["message_pattern"], re.IGNORECASE)
    commits = commits_since(base.commit, head.commit)

    def resolve(prefix: str) -> Optional[dict]:
        matches = [c for c in commits if c["commit"].startswith(prefix)]
        return matches[0] if len(matches) == 1 else None

    fixed = changelog_fixed_added(base, head)
    entry_commits = {}
    for entry in fixed:
        out = git("log", "--format=%H", "-S" + entry[:60], f"{base.commit}..{head.commit}", "--", "CHANGELOG.md")
        entry_commits[entry] = out.split()
    by_changelog = {commit for found in entry_commits.values() for commit in found}
    selected = {}
    for commit in commits:
        reasons = []
        words = sorted({match.group(0).lower() for match in pattern.finditer(commit["subject"] + "\n" + commit["body"])})
        if words:
            reasons.append("message: " + ", ".join(words))
        if commit["commit"] in by_changelog:
            reasons.append("adds a CHANGELOG Fixed entry")
        if reasons:
            selected[commit["commit"]] = reasons

    problems, unexplained, stale, without_tests, rows = [], [], [], [], []
    fixes, excluded = {}, {}
    for kind, table in (("fixes", fixes), ("excluded", excluded)):
        for entry in data.get(kind, []):
            commit = resolve(entry["commit"])
            if commit is None:
                stale.append(f"{kind}:{entry['commit']} (not exactly one commit since the baseline)")
                continue
            if commit["commit"] in fixes or commit["commit"] in excluded:
                problems.append(f"{entry['commit']}: listed twice")
            table[commit["commit"]] = entry
    cache: Dict[str, Optional[set]] = {}
    for commit in commits:
        full = commit["commit"]
        reasons = selected.get(full)
        if full in excluded:
            entry = excluded[full]
            if reasons is None:
                stale.append(f"excluded:{entry['commit']} (the rule does not select it)")
            if not entry.get("reason", "").strip():
                problems.append(f"{entry['commit']}: exclusion without a reason")
            rows.append(dict(commit=full[:7], subject=commit["subject"], selected_by=reasons,
                             status="excluded", reason=entry.get("reason", "")))
            continue
        if full in fixes:
            entry = fixes[full]
            if reasons is None and entry.get("selected_by") != "manual":
                problems.append(f"{entry['commit']}: the rule does not select it; mark it selected_by manual")
            if not entry.get("bug", "").strip():
                problems.append(f"{entry['commit']}: no bug description")
            missing = [node for node in entry.get("tests", []) if not node_exists(node, head, cache)]
            if missing:
                problems.append(f"{entry['commit']}: test node ids do not exist: {missing}")
            status = "fix with regression tests"
            if not entry.get("tests"):
                status = "fix without a regression test"
                without_tests.append(f"{entry['commit']}: {entry.get('bug', '')[:120]}")
                if not entry.get("no_test_reason", "").strip():
                    problems.append(f"{entry['commit']}: a fix without tests must say so in no_test_reason")
            rows.append(dict(commit=full[:7], subject=commit["subject"],
                             selected_by=reasons or ["manual"], status=status, bug=entry.get("bug", ""),
                             tests=entry.get("tests", []), untested_parts=entry.get("untested_parts", "")))
            continue
        if reasons is not None:
            unexplained.append(f"{full[:7]} {commit['subject']} ({'; '.join(reasons)})")
    # every new CHANGELOG Fixed entry must name a mapped fix
    mapping = data.get("changelog_fixed", {})
    for entry in fixed:
        key = entry[:80]
        record = mapping.get(key)
        if record is None:
            unexplained.append(f"changelog Fixed entry not mapped: {key}")
            continue
        commit = resolve(record.get("commit", ""))
        if commit is None or commit["commit"] not in fixes:
            problems.append(f"changelog Fixed entry {key!r} names no mapped fix commit")
    stale += [f"changelog_fixed:{key}" for key in sorted(set(mapping) - {entry[:80] for entry in fixed})]
    return dict(check="t11", baseline=base.commit, head=head.commit, rule=rule,
                commits_since_baseline=len(commits), selected=len(selected),
                fixes=sum(row["status"].startswith("fix") for row in rows),
                excluded=sum(row["status"] == "excluded" for row in rows), rows=rows,
                changelog_fixed_added=fixed,
                changelog_entry_commits={key[:80]: [c[:7] for c in value] for key, value in entry_commits.items()},
                unexplained=unexplained, stale=stale, problems=problems, violations=without_tests)


# --------------------------------------------------------------------------
# CI-3

GATE_SCRIPT = "scripts/clean_install_gate.py"
EXAMPLES_SCRIPT = "scripts/audit_recovery_usage.py"
RUN_SCRIPT = "scripts/reproduce_from_clean_clones.sh"
STATUSES = ("documented", "partial", "undocumented", "harness")


def gate_calls(source: str) -> List[str]:
    """Each command the clean-install gate runs, as its argv list is written.

    The argv of every ``gate.run([...])`` call, and the ``command = [...]``
    that ``check_servers`` starts with ``subprocess.Popen``.
    """
    tree = ast.parse(source)
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run" \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "gate" \
                    and node.args and isinstance(node.args[0], ast.List):
                found.append(collapse(ast.get_source_segment(source, node.args[0]) or "")[:160])
            elif function.name == "check_servers" and isinstance(node, ast.Assign) \
                    and any(isinstance(t, ast.Name) and t.id == "command" for t in node.targets) \
                    and isinstance(node.value, ast.List):
                found.append(collapse(ast.get_source_segment(source, node.value) or "")[:160])
    return found


def example_calls(source: str) -> List[str]:
    """The named ``run(repo, name, argv)`` calls the examples phase makes.

    The two calls every phase makes first, and those under
    ``args.phase == "examples"``; each is ``name <- argv`` as written.
    """
    tree = ast.parse(source)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    scopes = []
    for statement in main.body:
        if isinstance(statement, ast.If):
            test = collapse(ast.get_source_segment(source, statement.test) or "")
            if test == 'args.phase == "help"':
                # the examples branch is an elif of this chain
                branch = statement
                while branch is not None:
                    if collapse(ast.get_source_segment(source, branch.test) or "") == 'args.phase == "examples"':
                        scopes.extend(branch.body)
                        break
                    branch = branch.orelse[0] if len(branch.orelse) == 1 and isinstance(branch.orelse[0], ast.If) \
                        else None
                break
            continue
        scopes.append(statement)
    found = []
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run" \
                    and len(node.args) >= 3:
                name = collapse(ast.get_source_segment(source, node.args[1]) or "")
                argv = collapse(ast.get_source_segment(source, node.args[2]) or "")
                found.append((name + " <- " + argv)[:160])
    return found


def run_script_steps(text: str) -> dict:
    """What the run script does, by kind.

    ``steps``: the ``step NAME CWD COMMAND...`` lines (the user steps);
    ``variables``: the names it exports, ``-u NAME`` for what it unsets,
    ``NAME`` for an assignment written into a step's command, and
    ``activate`` for sourcing a virtual environment's ``bin/activate``;
    ``harness``: the harness-only lines, ``record FILE`` (a query whose output
    is saved) and ``exec env`` (starting the script again in a changed
    environment), each mapped to its command.
    """
    steps, variables, harness = [], [], {}
    for line in text.replace("\\\n", " ").splitlines():
        code = line.strip()
        if code.startswith("#"):
            continue
        match = re.match(r"step (\S+) (.*)", code)
        if match:
            steps.append(match.group(1))
            variables += re.findall(r"(?:^|\s)([A-Z][A-Z0-9_]*)=", match.group(2))
            continue
        if re.match(r"export\s", code):
            variables += [word.split("=", 1)[0] for word in code.split()[1:]
                          if re.match(r"[A-Z][A-Z0-9_]*(=|$)", word)]
        elif re.match(r"unset\s", code):
            variables += ["-u " + word for word in code.split()[1:]]
        elif re.match(r"\.\s+\S*bin/activate", code):
            variables.append("activate")
        elif code.startswith("record "):
            words = shlex.split(re.split(r"\s(?:\|\||&&)\s", code)[0])
            harness["record " + words[1]] = words[2:]
        elif re.match(r"exec env\b", code):
            harness["exec env"] = [code]
    return dict(steps=steps, variables=variables, harness=harness)


def read_only_query(item: str, command: List[str]) -> bool:
    """A harness line may only read: git rev-parse or status of a checkout, grep a file,
    or start this same script again in a changed environment."""
    if item == "exec env":
        return command[0].endswith('bash "$0" "$@"')
    if command[:2] == ["git", "-C"] and len(command) >= 4:
        return command[3:] in (["rev-parse", "HEAD"], ["status", "--porcelain"],
                               ["status", "--porcelain", "--untracked-files=all"])
    return command[:1] == ["grep"]


def check_run_script(steps: List[dict], parsed: dict) -> List[str]:
    """Harness steps run only read-only queries, and no user step is filed as harness."""
    problems = []
    harness = parsed["harness"]
    for item, command in harness.items():
        if not read_only_query(item, command):
            problems.append(f"the run script's harness line {item!r} runs {' '.join(command)!r}, "
                            "which is not a read-only query")
    for step in steps:
        listed = step.get("run_steps", [])
        if step["status"] == "harness":
            users = [name for name in listed if name not in harness]
            if users:
                problems.append(f"{step['id']}: a harness step lists {users}, which the run script "
                                "runs as user steps or variables")
        else:
            filed = [name for name in listed if name in harness]
            if filed:
                problems.append(f"{step['id']}: lists the harness-only {filed} as a user step")
    return problems


def audit_ci3(label: str, companion: Optional[Path], run_script: Optional[Path] = None) -> dict:
    """Every step of the clean-clone run rests on a quoted instruction of the documents."""
    data = load_json(REPO_ROOT / COMMANDS_FILE)
    roots = {label: REPO_ROOT}
    if companion is not None:
        roots["RA" if label == "UMAT" else "UMAT"] = companion.resolve()
    allowed_docs = list(data["documents"])
    problems, stale, open_steps, rows, harness_steps = [], [], [], [], []
    for step in data["steps"]:
        row = dict(id=step["id"], source=step["source"], command=step["command"], status=step["status"],
                   fix_in=step.get("fix_in"), checked={})
        for repo in step["repos"]:
            if repo not in roots:
                row["checked"][repo] = "not checked here: pass --companion to check the other repository"
                continue
            root = roots[repo]
            evidence = [e for e in step.get("evidence", []) + step.get("elsewhere", []) if e["repo"] == repo]
            results = []
            for item in evidence:
                in_scope = item["doc"] in allowed_docs
                if item in step.get("evidence", []) and not in_scope:
                    problems.append(f"{step['id']}: {item['doc']} is not one of the instruction documents")
                    continue
                path = root / item["doc"]
                lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
                found = any(item["quote"] in line for line in lines)
                results.append(found)
                if not found:
                    stale.append(f"{step['id']}: {repo} {item['doc']} no longer has {item['quote']!r}")
            for probe in step.get("would_document", []):
                if probe["repo"] != repo:
                    continue
                for doc in (allowed_docs if probe["doc"] == "*" else [probe["doc"]]):
                    path = root / doc
                    text = path.read_text(encoding="utf-8") if path.is_file() else ""
                    if re.search(probe["pattern"], text):
                        stale.append(f"{step['id']}: {repo} {doc} now matches {probe['pattern']!r}; the step "
                                     "looks documented: update its status and evidence")
            if step["status"] == "documented" and not any(
                    e["repo"] == repo for e in step.get("evidence", [])):
                problems.append(f"{step['id']}: documented for {repo} without a quote from its documents")
            row["checked"][repo] = "quotes found" if results and all(results) else \
                "no quote" if not results else "a quote is missing"
        if step["status"] not in STATUSES:
            problems.append(f"{step['id']}: status must be one of {', '.join(STATUSES)}")
        if step["status"] == "harness":
            if step.get("source") != "run" or not step.get("run_steps") or not step.get("reason", "").strip():
                problems.append(f"{step['id']}: a harness step is a step of the run script (source run, "
                                "run_steps) with the reason a user does not need it")
            harness_steps.append(f"{step['id']}: {step.get('reason', '')}")
        if step["status"] in ("undocumented", "partial"):
            if step.get("fix_in") not in ("docs", "run"):
                problems.append(f"{step['id']}: fix_in must be docs or run")
            if not step.get("gap", "").strip() or not step.get("missing", "").strip():
                problems.append(f"{step['id']}: say what differs (gap) and what would fix it (missing)")
            open_steps.append(f"{step['id']} ({step['status']}, fix in {step.get('fix_in')}): {step.get('gap', '')}")
        rows.append(row)

    # the data must list what the run's scripts really execute
    def compare(kind: str, actual: List[str], listed_key: str):
        listed = [(step["id"], call) for step in data["steps"] for call in step.get(listed_key, [])]
        names = [call for _, call in listed]
        for call in actual:
            if names.count(call) != 1:
                problems.append(f"{kind} runs {call!r}, which {'no step' if not names.count(call) else 'several steps'} lists")
        for step_id, call in listed:
            if call not in actual:
                stale.append(f"{step_id}: {kind} no longer runs {call!r}")

    coverage = {}
    for kind, root_label, script, extract, key in (
            ("the clean-install gate", "RA", GATE_SCRIPT, gate_calls, "gate_calls"),
            ("the examples phase", "RA", EXAMPLES_SCRIPT, example_calls, "example_calls")):
        root = roots.get(root_label)
        if root is None or not (root / script).is_file():
            coverage[key] = "not checked here: the script is in Residual_Assembler"
            continue
        actual = extract((root / script).read_text(encoding="utf-8"))
        compare(kind, actual, key)
        coverage[key] = f"{len(actual)} calls compared with {script}"
    if run_script is None:
        for root in roots.values():
            if (root / RUN_SCRIPT).is_file():
                run_script = root / RUN_SCRIPT
                break
    if run_script is not None:
        parsed = run_script_steps(run_script.read_text(encoding="utf-8"))
        problems.extend(check_run_script(data["steps"], parsed))
        compare("the run script", parsed["steps"] + parsed["variables"] + list(parsed["harness"]), "run_steps")
        shown = RUN_SCRIPT if run_script.resolve().as_posix().endswith(RUN_SCRIPT) else run_script.name
        coverage["run_steps"] = (f"{len(parsed['steps'])} steps, {len(parsed['variables'])} variables and "
                                 f"{len(parsed['harness'])} harness lines compared with {shown}")
    else:
        coverage["run_steps"] = f"not checked here: {RUN_SCRIPT} is in Residual_Assembler (pass --companion)"
    return dict(check="ci3", repository=label, documents=allowed_docs, coverage=coverage, steps=rows,
                unexplained=[], stale=stale, problems=problems, violations=open_steps, harness=harness_steps)


# --------------------------------------------------------------------------

def summarise(report: dict) -> str:
    lines = [f"{report['check']}: {len(report['unexplained'])} unexplained, {len(report['stale'])} stale, "
             f"{len(report['problems'])} problems, {len(report['violations'])} open"]
    if "counts" in report:
        lines.append("  findings per category: " + ", ".join(f"{k}={v}" for k, v in report["counts"].items()))
    for field in ("unexplained", "stale", "problems", "violations", "harness"):
        for item in report.get(field, [])[:50]:
            lines.append(f"  {field}: {item}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", choices=("t11", "t12", "ci3", "all"), default="all")
    parser.add_argument("--rev", default="HEAD", help="commit to audit (default HEAD)")
    parser.add_argument("--report", type=Path, default=None,
                        help="report path (default build/audit_integrity/<check>.json)")
    parser.add_argument("--companion", type=Path, default=None,
                        help="the other repository's checkout, to check its documents too (ci3)")
    parser.add_argument("--run-script", type=Path, default=None,
                        help=f"the clean-clone run script to check the step list against (ci3; default "
                             f"{RUN_SCRIPT} of Residual_Assembler, here or in --companion)")
    args = parser.parse_args(argv)

    name = repository_name()
    label = REPOSITORY_LABELS[name]
    checks = ("t11", "t12", "ci3") if args.check == "all" else (args.check,)
    base = head = None
    reports = {}
    try:
        if any(check in ("t11", "t12") for check in checks):
            base = Revision(baseline_commit(name))
            head = Revision(args.rev)
        for check in checks:
            if check == "t12":
                reports[check] = audit_t12(base, head)
            elif check == "t11":
                reports[check] = audit_t11(base, head)
            else:
                reports[check] = audit_ci3(label, args.companion, args.run_script)
    finally:
        for revision in (base, head):
            if revision is not None:
                revision.close()
    status = 0
    for check, report in reports.items():
        report["repository"] = label
        destination = args.report if (args.report and len(reports) == 1) else \
            (args.report.parent / f"{check}.json" if args.report else
             REPO_ROOT / "build" / "audit_integrity" / f"{check}.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(summarise(report))
        print(f"  report: {destination}")
        if report["unexplained"] or report["stale"] or report["problems"]:
            status = 1
        elif report["violations"] and status == 0:
            status = 2
    return status


if __name__ == "__main__":
    raise SystemExit(main())
