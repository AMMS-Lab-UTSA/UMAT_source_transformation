"""A tool that does not import is a batch that fails on its eighteenth entry.

Measured: a missing import of ``analyse_truncation`` in
``verify_store_in_abaqus`` was reached only on the first entry that got as far
as the tangent, seventeen Abaqus jobs into a 253-entry run. Nothing before that
touched the name, so the run started, printed progress, and then recorded
``harness_error`` for every remaining entry.

Importing a module executes its top level and binds every name its functions
close over, which is what makes this catch that class. It does not run
anything: every tool here is argparse-driven and does its work under
``main()``.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

TOOLS = sorted(path for path in (ROOT / "tools").glob("*.py")
               if not path.name.startswith("_"))


@pytest.mark.parametrize("tool", TOOLS, ids=lambda p: p.stem)
def test_the_tool_imports(tool: Path):
    name = f"_toolimport_{tool.stem}"
    specification = importlib.util.spec_from_file_location(name, tool)
    module = importlib.util.module_from_spec(specification)
    # Registered before execution: a dataclass resolves its own annotations
    # through sys.modules[cls.__module__], and a module that is not there
    # yet raises inside dataclasses rather than in the tool.
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda p: p.stem)
def test_every_module_level_name_a_function_reads_is_bound(tool: Path):
    """A name a function body reads must exist by the time the body runs.

    Python binds it at call time, so a missing import is invisible until that
    line executes -- which for a batch means part-way through a run that has
    already spent hours.

    Checked PER FUNCTION. This used to pool every function's parameters into
    one set, so a name that was a parameter of one function counted as bound
    inside every other, and a genuinely free variable was masked by an
    unrelated signature elsewhere in the file. That is not a hypothetical:

        wanted = min(amplitude * factor, ceiling)

    went into a real Abaqus run and came back NameError: name 'ceiling' is
    not defined, with this guard passing, because some other function in the
    same file took a parameter of that name.
    """
    import ast
    import builtins

    tree = ast.parse(tool.read_text(encoding="utf-8"), filename=str(tool))

    #: Names a module always has without binding them itself.
    always = set(dir(builtins)) | {
        "__file__", "__name__", "__doc__", "__package__", "__spec__",
        "__loader__", "__builtins__", "__debug__", "__annotations__"}

    def bound_by(node) -> set:
        """Names this scope binds, not descending into nested scopes."""
        names: set = set()
        for argument in getattr(getattr(node, "args", None), "posonlyargs", []) or []:
            names.add(argument.arg)
        for argument in getattr(getattr(node, "args", None), "args", []) or []:
            names.add(argument.arg)
        for argument in getattr(getattr(node, "args", None), "kwonlyargs", []) or []:
            names.add(argument.arg)
        for extra in ("vararg", "kwarg"):
            argument = getattr(getattr(node, "args", None), extra, None)
            if argument is not None:
                names.add(argument.arg)
        stack = list(ast.iter_child_nodes(node))
        while stack:
            child = stack.pop()
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                names.add(child.name)
                continue           # its own scope; its locals are not ours
            if isinstance(child, ast.Lambda):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                names.update(child.names)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                names.add(child.name)
            stack.extend(ast.iter_child_nodes(child))
        return names

    def read_by(node) -> set:
        """Names this scope reads, not descending into nested scopes."""
        names: set = set()
        stack = list(ast.iter_child_nodes(node))
        while stack:
            child = stack.pop()
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                names.add(child.id)
            stack.extend(ast.iter_child_nodes(child))
        return names

    module_level = set(always)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module_level.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            module_level.add(node.name)
        else:
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    module_level.add(child.id)
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        module_level.add(alias.asname or alias.name.split(".")[0])

    # Nested scopes can read their enclosing function's names, so a scope is
    # checked against everything its ancestors bind as well.
    problems: list = []

    def visit(node, enclosing: set) -> None:
        here = enclosing | bound_by(node) | {
            child.name for child in ast.iter_child_nodes(node)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef))}
        for name in sorted(read_by(node) - here):
            problems.append(f"{getattr(node, 'name', '<module>')}: {name}")
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, here)
            elif isinstance(child, ast.ClassDef):
                visit(child, enclosing)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(node, module_level)
        elif isinstance(node, ast.ClassDef):
            visit(node, module_level)

    assert not problems, (
        f"{tool.name} reads names nothing binds where they are read: "
        + ", ".join(problems[:12]))


def test_the_guard_sees_a_name_another_function_only_happens_to_take():
    """The blind spot that let a NameError into a real Abaqus run.

    Pooling every function's parameters into one set made `ceiling` look
    bound inside a function that never took it, because a different function
    in the same file did.
    """
    import ast
    import builtins

    sample = ast.parse("def a(ceiling=1.0):\n    return ceiling\n\n"
                       "def b(x):\n    return min(x, ceiling)\n")
    pooled: set = set(dir(builtins))
    for node in ast.walk(sample):
        if isinstance(node, ast.arg):
            pooled.add(node.arg)
        elif isinstance(node, ast.FunctionDef):
            pooled.add(node.name)
    missed = {n.id for n in ast.walk(sample)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
              and n.id not in pooled}
    assert missed == set(), "the pooled check is the one that misses it"

    # And per scope, b's read of `ceiling` is free.
    functions = {node.name: node for node in ast.iter_child_nodes(sample)
                 if isinstance(node, ast.FunctionDef)}
    taken = {argument.arg for argument in functions["b"].args.args}
    read = {n.id for n in ast.walk(functions["b"])
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert "ceiling" in read - taken - set(dir(builtins))
