"""CLI entry-point smoke tests (``--help`` must not error)."""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

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


def test_main_cli_config_uses_canonical_dispatch(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from umat_oti import cli

    calls: list[tuple[Path, Path]] = []

    def fake_run_config_transform(config_path: Path, out_dir: Path, *, compile_generated: bool = False):
        calls.append((config_path, out_dir))
        assert compile_generated is True
        return {"transform_success": True, "schema_version": "1.1"}, 0

    monkeypatch.setattr(cli, "run_config_transform", fake_run_config_transform)

    exit_code = cli.main(["config", "request.json", "--out", "generated", "--compile"])

    assert exit_code == 0
    assert calls == [(Path("request.json"), Path("generated"))]
    assert '"transform_success": true' in capsys.readouterr().out


def test_batch_cli_uses_canonical_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from umat_oti import cli_batch

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "request.json"
    config_path.write_text("{}", encoding="utf-8")
    batch_dir = tmp_path / "batch"
    calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(cli_batch, "load_project_config_json", lambda *args, **kwargs: {})

    def fake_run_config_transform(path: Path, out_dir: Path):
        calls.append((path, out_dir))
        return {
            "source": str(tmp_path / "umat.for"),
            "ntens": 6,
            "anchor_status": "ready",
            "transform_success": True,
            "transformed_source": str(out_dir / "umat_oti.for"),
            "derivative_requests": [{"target": "DDSDDE", "order": 4}],
        }, 0

    monkeypatch.setattr(cli_batch, "run_config_transform", fake_run_config_transform)
    monkeypatch.setattr(
        "sys.argv",
        ["umat-oti-batch", "--config-dir", str(config_dir), "--batch-dir", str(batch_dir)],
    )

    assert cli_batch.main() == 0
    assert calls == [(config_path, batch_dir / "oti_transform" / "request")]
    report = json.loads((batch_dir / "completed_json_batch_report.json").read_text(encoding="utf-8"))
    assert report["results"][0]["derivative_requests"] == [{"target": "DDSDDE", "order": 4}]
