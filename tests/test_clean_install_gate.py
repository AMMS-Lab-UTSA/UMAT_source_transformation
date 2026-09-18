"""The joint gate must be reachable without importing development packages."""

from pathlib import Path
import subprocess
import sys


def test_joint_gate_requires_explicit_companion_repository():
    script = Path(__file__).resolve().parents[1] / "scripts/clean_install_gate.py"
    result = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "--ra-repo" in result.stderr


def test_joint_gate_reports_missing_companion_script(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/clean_install_gate.py"
    result = subprocess.run([sys.executable, "-I", str(script), "--ra-repo", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "joint gate not found" in result.stderr