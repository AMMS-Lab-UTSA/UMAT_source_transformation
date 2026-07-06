"""Basic import and metadata sanity checks."""

from __future__ import annotations


def test_package_imports_and_has_version() -> None:
    import umat_oti

    assert isinstance(umat_oti.__version__, str)
    assert umat_oti.__version__.count(".") >= 1


def test_public_cli_modules_import() -> None:
    # The console-script entry points declared in pyproject.toml must import.
    from umat_oti import cli, cli_batch, cli_json

    assert hasattr(cli, "main")
    assert hasattr(cli_json, "main")
    assert hasattr(cli_batch, "main")
