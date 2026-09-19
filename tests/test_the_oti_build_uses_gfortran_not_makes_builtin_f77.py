"""The OTI builds compile with gfortran, not with make's built-in f77.

GNU make predefines ``FC = f77``. A Makefile line ``FC ?= gfortran`` therefore
never applies, and a plain ``make`` compiles with f77, which is not installed
everywhere gfortran is. The parameter-sensitivity sweep ran plain ``make``, so
its OTI driver build failed on such machines (09d661b). Two things now keep
the build on gfortran, and each is tested here:

* every generated Makefile replaces make's built-in FC with gfortran and keeps
  an FC the caller names (``make -n`` prints the compile lines without
  running them);
* the sweep names the compiler on make's command line, so its OTI driver is
  built with gfortran whatever FC make would otherwise use.

On many machines f77 is gfortran under another name, which hides the defect.
The sweep test puts an f77 on PATH ahead of every other that refuses to
compile, so a build that reaches f77 fails on any machine.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from umat_oti.fortran_emit.higher_order_strain import HigherOrderModel, generate_higher_order_build
from umat_oti.fortran_emit.parameter_sensitivity_j2 import generate_j2_oti_build
from umat_oti.services.transformation import TransformationOptions, run_transformation

pytestmark = [pytest.mark.regression, pytest.mark.fortran]

REPO_ROOT = Path(__file__).resolve().parents[1]
SWEEP = REPO_ROOT / "tools" / "run_parameter_sensitivity_sweep.py"
MODEL = "m1_elastic"
CONTRACT = REPO_ROOT / "parameter_sensitivity" / "contracts" / f"{MODEL}.json"

#: Variables through which a caller, or a make that started this test, hands
#: make an FC or options. None of them may reach the builds below.
_MAKE_VARIABLES = ("FC", "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKELEVEL", "MAKEFILES")


def _environment(**extra: str) -> dict:
    environment = {key: value for key, value in os.environ.items() if key not in _MAKE_VARIABLES}
    environment.update(extra)
    return environment


def _compilers(directory: Path, *arguments: str, environment: dict) -> set:
    """The first word of every command ``make -n`` would run in ``directory``."""
    completed = subprocess.run(["make", "-n", *arguments], cwd=directory, env=environment,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    lines = [line.split()[0] for line in completed.stdout.splitlines() if line.strip()]
    assert lines, f"make -n printed no command in {directory}"
    return set(lines)


def _generated_builds(root: Path) -> dict:
    """The three generated build directories, each written by its own generator."""
    transformed = root / "transform"
    summary, _ = run_transformation(CONTRACT, transformed, TransformationOptions(compile_generated=False))
    assert summary.get("transform_success"), summary
    j2 = generate_j2_oti_build(root / "j2").root
    higher = generate_higher_order_build(root / "higher_order",
                                         HigherOrderModel.softwarex_bivariate_quintic()).root
    return {"parameter-sensitivity transform": transformed / "parameter_sensitivity",
            "J2 parameter sensitivity": j2, "higher-order strain": higher}


def test_every_generated_makefile_replaces_makes_builtin_f77_with_gfortran(tmp_path):
    environment = _environment()
    # the default this is about: without it the test would prove nothing
    builtin = subprocess.run(["make", "-p", "-f", os.devnull], env=environment,
                             capture_output=True, text=True).stdout
    assert "FC = f77" in builtin.splitlines()

    for name, directory in _generated_builds(tmp_path).items():
        assert _compilers(directory, environment=environment) == {"gfortran"}, name
        # a compiler the caller names is kept, on the command line or in the environment
        assert _compilers(directory, "FC=caller-fortran", environment=environment) == {"caller-fortran"}, name
        assert _compilers(directory, environment=_environment(FC="caller-fortran")) == {"caller-fortran"}, name


def _refusing_f77(directory: Path) -> Path:
    directory.mkdir()
    f77 = directory / "f77"
    f77.write_text("#!/bin/sh\necho 'f77 was asked to compile' >&2\nexit 1\n")
    f77.chmod(f77.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


def test_the_sweep_builds_its_oti_driver_with_gfortran_whatever_fc_make_would_use(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("run_parameter_sensitivity_sweep", SWEEP)
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)

    bin_dir = _refusing_f77(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    for name in _MAKE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FC", "f77")

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    out = tmp_path / MODEL
    summary, _ = run_transformation(CONTRACT, out, TransformationOptions(compile_generated=False))
    assert summary.get("transform_success"), summary
    ps_dir = out / "parameter_sensitivity"
    # a plain make here reaches the refusing f77: the Makefile keeps the FC it is given
    assert _compilers(ps_dir, environment=dict(os.environ)) == {"f77"}
    plain = subprocess.run(["make"], cwd=ps_dir, capture_output=True, text=True)
    assert plain.returncode != 0 and "f77 was asked to compile" in plain.stderr
    subprocess.run(["make", "clean"], cwd=ps_dir, capture_output=True, text=True, check=True)

    record = {"model": MODEL, "stages": {}}
    sweep._execute_and_verify(MODEL, contract, out, record)

    assert record["stages"]["executed_oti"] == {"status": "succeeded"}, record["stages"]["executed_oti"]
    # the driver it built is the one the verification then reads
    assert record["stages"]["derivatives_verified"]["status"] == "succeeded", record["stages"]
