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
    already spent hours. This checks only names that are NOT bound anywhere in
    the module and are NOT builtins and are NOT parameters or locals of the
    function that reads them: a genuinely free variable with nothing to
    resolve to.
    """
    import ast
    import builtins

    tree = ast.parse(tool.read_text(encoding="utf-8"), filename=str(tool))

    # The names a module always has without binding them itself.
    module_level: set = set(dir(builtins)) | {
        "__file__", "__name__", "__doc__", "__package__", "__spec__",
        "__loader__", "__builtins__", "__debug__", "__annotations__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module_level.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            module_level.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            module_level.add(node.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            module_level.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            module_level.add(node.name)
        elif isinstance(node, ast.arg):
            module_level.add(node.arg)
        elif isinstance(node, ast.alias):
            module_level.add((node.asname or node.name).split(".")[0])

    unbound = sorted({
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        and node.id not in module_level})
    assert not unbound, (f"{tool.name} reads names nothing in it binds: "
                         + ", ".join(unbound))
