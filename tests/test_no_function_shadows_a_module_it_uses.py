"""A name bound anywhere in a function is local to all of it. ``frames = [...]``
inside one branch of verify_one made ``frames.points_for(...)`` 40 lines later --
the imported MODULE -- an UnboundLocalError on every row that reached it
(beae90e; pass23-prep, results1..5 all harness_error). No tool or module may
bind, inside a function, a name it also uses as a module-level import. The
offline tests did not see it: the one end-to-end verify_one test skips where
its recordings are absent.
"""
import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "tools").glob("*.py")) + sorted((ROOT / "src" / "umat_oti").rglob("*.py"))


def _module_bindings(tree):
    names = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                names[(a.asname or a.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names[a.asname or a.name] = node.lineno
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names[node.name] = node.lineno
    return names


class _Scope(ast.NodeVisitor):
    """Names bound and names loaded in ONE function, not its nested scopes."""

    def __init__(self):
        self.bound, self.loaded, self.declared = {}, [], set()

    def bind(self, name, line):
        self.bound.setdefault(name, line)

    def visit_FunctionDef(self, node):            # a nested def binds its name only
        self.bind(node.name, node.lineno)
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.bind(node.name, node.lineno)

    def visit_Lambda(self, node):
        pass

    def _comprehension(self, node):                # its targets are its own
        for generator in node.generators:
            self.visit(generator.iter)
    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _comprehension

    def visit_Global(self, node):
        self.declared.update(node.names)
    visit_Nonlocal = visit_Global

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(node.id, node.lineno)
        else:
            self.loaded.append((node.id, node.lineno))

    def visit_Import(self, node):
        for a in node.names:
            self.bind((a.asname or a.name).split(".")[0], node.lineno)

    def visit_ImportFrom(self, node):
        for a in node.names:
            self.bind(a.asname or a.name, node.lineno)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bind(node.name, node.lineno)
        self.generic_visit(node)


def _shadows(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_level = _module_bindings(tree)
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        scope = _Scope()
        for argument in (function.args.args + function.args.kwonlyargs
                         + function.args.posonlyargs
                         + [a for a in (function.args.vararg, function.args.kwarg) if a]):
            scope.bind(argument.arg, function.lineno)
        for statement in function.body:
            scope.visit(statement)
        for name, line in scope.bound.items():
            if name in scope.declared or name not in module_level:
                continue
            # bound here AND loaded here as the module-level thing: either
            # before its first binding (certain), or as a module is used --
            # name.attribute -- while the local binding is not an import
            first_load = min((l for n, l in scope.loaded if n == name), default=None)
            if first_load is not None and first_load < line:
                found.append((str(path.relative_to(ROOT)), function.name, name, line, first_load))
    return found


def _module_imports(tree):
    """Module-level names that are MODULES: ``import x``, and ``from pkg import
    submodule`` -- found by importing, because only a module is used as
    ``name.attribute`` for what it contains (a function or class rebound locally
    is a different matter)."""
    import importlib
    import types
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                try:
                    package = importlib.import_module(node.module)
                    thing = getattr(package, a.name, None)
                    if thing is None:
                        thing = importlib.import_module(f"{node.module}.{a.name}")
                except Exception:                     # not importable here: not judged
                    continue
                if isinstance(thing, types.ModuleType):
                    names.add(a.asname or a.name)
    return names


def _attribute_uses(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = _module_imports(tree)
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        scope = _Scope()
        for statement in function.body:
            scope.visit(statement)
        argument_names = {a.arg for a in function.args.args + function.args.kwonlyargs}
        used_as_module = {n.value.id for n in ast.walk(function)
                          if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                          and isinstance(n.ctx, ast.Load)}
        for name in used_as_module & imports & set(scope.bound) - scope.declared - argument_names:
            # a local import of the same name is the same module, not a shadow
            local_imports = {a.asname or a.name for n in ast.walk(function)
                             if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            if name in local_imports:
                continue
            found.append((str(path.relative_to(ROOT)), function.name, name, scope.bound[name]))
    return found


def test_no_function_loads_a_module_level_name_before_binding_it_locally():
    problems = [p for f in FILES for p in _shadows(f)]
    assert not problems, problems


def test_no_function_rebinds_a_module_it_calls_into():
    problems = [p for f in FILES for p in _attribute_uses(f)]
    assert not problems, problems


def test_the_check_sees_the_pass23_prep_defect(tmp_path, monkeypatch):
    (tmp_path / "tools").mkdir()
    tool = tmp_path / "tools" / "t.py"
    tool.write_text(
        "from umat_oti.abaqus import frames\n\n"
        "def verify(crash):\n"
        "    if crash:\n"
        "        frames = [f for f in crash]\n"
        "    return frames.points_for(1)\n\n"
        "def fine(crash):\n"
        "    names = [f for f in crash]\n"
        "    return frames.points_for(1), names\n")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    assert _attribute_uses(tool) == [("tools/t.py", "verify", "frames", 5)]
