"""CLI entry-point smoke tests (``--help`` must not error)."""

from __future__ import annotations

import importlib
import inspect

import pytest


@pytest.mark.parametrize(
    "module_name",
    ["umat_oti.cli", "umat_oti.cli_json", "umat_oti.cli_batch"],
)
def test_cli_help_exits_zero(module_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module(module_name)
    main = module.main

    # Some entry points accept an explicit argv list; others read sys.argv.
    takes_argv = len(inspect.signature(main).parameters) > 0
    monkeypatch.setattr("sys.argv", [module_name, "--help"])

    with pytest.raises(SystemExit) as excinfo:
        main(["--help"]) if takes_argv else main()

    assert excinfo.value.code == 0
