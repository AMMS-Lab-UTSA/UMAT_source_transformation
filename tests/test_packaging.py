"""The installed package must carry everything it reads at run time.

An editable install hides this class of defect completely: the source tree is
still on disk, so files that were never declared as package data resolve
anyway. Only a built wheel shows the truth.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Read by umat_oti.oti.module_generator at run time.
REQUIRED_PACKAGE_DATA = (
    "umat_oti/app/demo_inputs/examples/elastic_minimal.json",
    "umat_oti/app/demo_inputs/UMATs/UMATs/ICP/elasticity/elastic.f",
    "umat_oti/oti/support/fmod_writer.py",
    "umat_oti/oti/support/master_parameters.f90",
    "umat_oti/oti/support/real_utils.f90",
    "umat_oti/oti/support/pyoti_templates/core_functions.f90",
    "umat_oti/oti/support/pyoti_templates/base_derivs_fortran.f90",
    "umat_oti/oti/support/pyoti_templates/LICENSE",
)


def test_pyoti_templates_resolve_inside_the_package():
    """Regression: absent templates produced an uncompilable module, not an error.

    The generator fell back to empty placeholder templates and only warned. The
    module it emitted declared generic interfaces over procedures that were
    never written, so gfortran rejected it with dozens of "is neither function
    nor subroutine" errors that pointed nowhere near the real cause.
    """
    from umat_oti.oti.module_generator import _find_template_dir
    import umat_oti

    templates = _find_template_dir()
    assert templates is not None, "the packaged pyoti templates were not found"
    package_root = Path(umat_oti.__file__).resolve().parent
    assert templates.is_relative_to(package_root)
    for name in ("core_functions.f90", "base_derivs_fortran.f90"):
        assert (templates / name).is_file(), name


def test_missing_templates_raise_rather_than_emit_a_broken_module(monkeypatch, tmp_path):
    """An unavailable input must not become an artefact that looks generated."""
    from umat_oti.oti import module_generator

    monkeypatch.setattr(module_generator, "_find_template_dir", lambda: None)
    with pytest.raises(module_generator.OtilibGenerationError) as excinfo:
        module_generator.generate_otilib_module(
            output_dir=tmp_path, ntens=4, order=1)
    assert "templates" in str(excinfo.value)


def test_support_files_resolve_inside_the_package():
    """Resolution must not depend on the repository layout around the package."""
    from umat_oti.oti.module_generator import _find_support_dir
    import umat_oti

    support = _find_support_dir(None)
    package_root = Path(umat_oti.__file__).resolve().parent
    assert support.is_relative_to(package_root), (
        f"support files resolved to {support}, outside the package at "
        f"{package_root}; a wheel install would not find them")
    for name in ("fmod_writer.py", "master_parameters.f90", "real_utils.f90"):
        assert (support / name).is_file(), name


@pytest.mark.slow
def test_built_wheel_contains_the_runtime_support_files(tmp_path):
    """Regression: a pip-installed package could not generate an OTI module.

    The support sources lived at the repository root and were located by walking
    up from the module file. From a wheel that walk lands in site-packages, the
    files are absent, and generate_otilib_module raised "OTILIB module
    generation unavailable: missing fmod_writer.py, master_parameters.f90,
    real_utils.f90" on first use. Every editable install masked it; the
    cross-repository CI of the companion product is what exposed it.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps",
         "-w", str(tmp_path), str(REPO_ROOT)],
        capture_output=True, text=True)
    assert proc.returncode == 0, (
        "wheel build failed; packaging verification did not pass:\n"
        + proc.stdout + proc.stderr)
    wheels = list(tmp_path.glob("umat_oti-*.whl")) + list(tmp_path.glob("umat-oti-*.whl"))
    assert wheels, f"no wheel was produced: {proc.stdout[-400:]}"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        for relative in ("examples/elastic_minimal.json", "UMATs/UMATs/ICP/elasticity/elastic.f"):
            assert archive.read("umat_oti/app/demo_inputs/" + relative) == (REPO_ROOT / relative).read_bytes()
    missing = [name for name in REQUIRED_PACKAGE_DATA if name not in names]
    assert not missing, f"the wheel omits runtime data files: {missing}"


def test_demo_resources_preserve_relative_source_and_compile(tmp_path, monkeypatch):
    from umat_oti.app import resources
    from umat_oti.services.transformation import TransformationOptions, run_transformation

    monkeypatch.setattr(resources, "repository_root", lambda: None)
    monkeypatch.setattr(resources.resources, "files", lambda package: tmp_path / "package")
    for relative in resources.DEMO_INPUTS:
        target = tmp_path / "package/demo_inputs" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / relative).read_bytes())
    monkeypatch.chdir(tmp_path)
    contract = resources.demo_contract(tmp_path / "workspace")
    assert contract.read_bytes() == (REPO_ROOT / resources.DEMO_INPUTS[0]).read_bytes()
    summary, code = run_transformation(contract, tmp_path / "generated", TransformationOptions(compile_generated=True))
    assert code == 0, summary
    assert summary["transform_success"] is True
    assert summary["compilation"]["status"] == "compiled"
