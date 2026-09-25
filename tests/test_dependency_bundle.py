from pathlib import Path
import json
import shutil
import subprocess

import pytest

from umat_oti.transform.dependency_bundle import bundle_sources


@pytest.mark.parametrize("discover", [False, True])
@pytest.mark.parametrize("form", ["free", "fixed"])
def test_transformation_bundle_builds_after_inputs_removed(tmp_path, discover, form):
    from umat_oti.services.jacobian_request import run_jacobian_transform
    from umat_oti.transform.source_transform import _wrap_fixed_form_source

    if not shutil.which("gfortran"):
        pytest.skip("gfortran required")
    inputs = tmp_path / "inputs"
    (inputs / "nested").mkdir(parents=True)
    source = inputs / ("umat.f90" if form == "free" else "umat.for")
    source.write_text("""subroutine umat(stress,dstran,ddsdde,ntens)
implicit none
integer :: ntens, idx
include 'nested/declarations.inc'
real(8) :: stress(ntens),dstran(ntens),ddsdde(ntens,ntens)
do idx=1,ntens
stress(idx)=stress(idx)+2.0d0*dstran(idx)
end do
ddsdde=0.0d0
end subroutine umat
""")
    (inputs / "nested/declarations.inc").write_text("include 'integer.inc'\n")
    (inputs / "nested/integer.inc").write_text("integer :: unused_local\n")
    if form == "fixed":
        for path in (source, inputs / "nested/declarations.inc", inputs / "nested/integer.inc"):
            path.write_text(_wrap_fixed_form_source("\n".join("      " + line for line in path.read_text().splitlines()) + "\n"))
    output = tmp_path / "out"
    run = run_jacobian_transform(source, output, ntens=6, discover_dependencies=discover)
    assert run.succeeded, run.report
    relocated = tmp_path / "relocated output"
    shutil.copytree(output, relocated)
    shutil.rmtree(inputs)
    shutil.rmtree(output)
    built = subprocess.run([str(relocated / "compile_hint.sh")], cwd=tmp_path, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    assert (relocated / "transformed_umat.o").is_file()
    report = json.loads((relocated / "dependency_bundle.json").read_text())
    assert len(report['files']) == 3
    assert not report['missing_includes']
    assert all(Path(item['bundled']).parent == Path('dependencies') for item in report['files'])
    assert all(path.is_file() for path in (relocated / 'dependencies').iterdir())


def test_recursive_includes_compile_after_relocation(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran required")
    inputs = tmp_path / "input"
    (inputs / "nested").mkdir(parents=True)
    source = inputs / "main.f90"
    source.write_text("program main\ninclude 'nested/constants.inc'\nprint *, factor\nend\n")
    (inputs / "nested/constants.inc").write_text("include 'value.inc'\n")
    (inputs / "nested/value.inc").write_text("real(8), parameter :: factor=3.0d0\n")
    output = tmp_path / "out"
    paths, manifest = bundle_sources([source], output)
    relative = paths[source].relative_to(output)
    assert relative == Path("dependencies/main.f90")
    assert (output / "dependencies/constants.inc").is_file()
    assert (output / "dependencies/value.inc").is_file()
    assert len(json.loads(manifest.read_text())["files"]) == 3
    relocated = tmp_path / "relocated"
    shutil.copytree(output, relocated)
    shutil.rmtree(inputs)
    shutil.rmtree(output)
    built = subprocess.run(["gfortran", "-I.", str(relative), "-o", "check"], cwd=relocated,
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(relocated / "check")], capture_output=True, text=True)
    assert float(run.stdout) == 3.0


def test_declared_module_is_bundled_and_compiled_before_helpers(tmp_path):
    from umat_oti.services.transformation import run_transformation, TransformationOptions

    if not shutil.which("gfortran"):
        pytest.skip("gfortran required")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "umat.f90"
    source.write_text("""subroutine umat(stress,dstran,ddsdde,ntens)
implicit none
integer :: ntens
real(8) :: stress(ntens),dstran(ntens),ddsdde(ntens,ntens)
call update(stress,dstran,ntens)
stress=stress+dstran
ddsdde=0.0d0
end subroutine umat
subroutine update(stress,dstran,ntens)
use input_flags, only: enabled
implicit none
integer :: ntens
real(8) :: stress(ntens),dstran(ntens)
if (enabled) stress=stress+2.d0*dstran
end subroutine update
""")
    (inputs / "input_flags.f90").write_text(
        "module input_flags\nlogical :: enabled=.true.\nend module input_flags\n")
    contract = inputs / "contract.json"
    contract.write_text(json.dumps({"schema_version": "1.1", "name": "module_build",
                                    "source": "umat.f90", "ntens": 6, "order": 1,
                                    "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN",
                                                     "response": "STRESS", "order": 1}],
                                    "dependency_roots": ["."],
                                    "module_sources": ["input_flags.f90"]}))
    output = tmp_path / "out"
    summary, code = run_transformation(contract, output, TransformationOptions(compile_generated=True))
    assert code == 0, summary
    assert summary["compilation"]["status"] == "compiled"
    assert (output / "compile_order.txt").read_text().splitlines()[0] == "dependencies/input_flags.f90"
    combined = Path(summary["combined_source"]).read_text()
    assert combined.index("module input_flags") < combined.index("subroutine update_oti")
    relocated = tmp_path / "relocated"
    shutil.copytree(output, relocated, ignore=shutil.ignore_patterns("*.o", "*.mod"))
    shutil.rmtree(inputs)
    shutil.rmtree(output)
    built = subprocess.run([str(relocated / "compile_hint.sh")], cwd=tmp_path,
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr


def test_same_include_name_from_different_helpers_is_preserved(tmp_path):
    sources = []
    for label, value in (("first", 1), ("second", 2)):
        folder = tmp_path / label
        folder.mkdir()
        source = folder / "helper.f90"
        source.write_text(f"subroutine {label}()\ninclude 'constants.inc'\nend\n")
        (folder / "constants.inc").write_text(f"integer, parameter :: value={value}\n")
        sources.append(source)
    paths, manifest = bundle_sources(sources, tmp_path / "out")
    assert paths[sources[0]].read_text() != paths[sources[1]].read_text()
    assert len(json.loads(manifest.read_text())["files"]) == 4
    assert len(set(paths.values())) == 4
    assert all(path.parent == tmp_path / "out/dependencies" for path in paths.values())
    for source in sources:
        include = source.parent / "constants.inc"
        assert f"INCLUDE 'dependencies/{paths[include].name}'" in paths[source].read_text()
    repeated, _ = bundle_sources(reversed(sources), tmp_path / "repeat")
    assert {source: path.name for source, path in paths.items()} == {
        source: path.name for source, path in repeated.items()}


def test_missing_and_runtime_includes_are_reported(tmp_path):
    source = tmp_path / "main.f90"
    source.write_text("subroutine main()\ninclude 'ABA_PARAM.INC'\ninclude 'absent.inc'\nend\n")
    _, manifest = bundle_sources([source], tmp_path / "out")
    report = json.loads(manifest.read_text())
    assert [item['include'] for item in report['missing_includes']] == ['absent.inc']
    assert [item['include'] for item in report['runtime_includes']] == ['ABA_PARAM.INC']


def test_ambiguous_include_in_search_roots_is_refused(tmp_path):
    source = tmp_path / "umat.f90"
    source.write_text("subroutine umat()\ninclude 'constants.inc'\nend\n")
    roots = [tmp_path / "first", tmp_path / "second"]
    for index, root in enumerate(roots):
        root.mkdir()
        (root / "constants.inc").write_text(f"integer, parameter :: count={index}\n")
    with pytest.raises(ValueError, match="Ambiguous include"):
        bundle_sources([source], tmp_path / "out", roots=roots)
    assert not (tmp_path / "out").exists()


def test_bundle_survives_transform_blocker(tmp_path):
    from umat_oti.services.jacobian_request import run_jacobian_transform

    source = tmp_path / "umat.f90"
    source.write_text("""subroutine umat(stress,dstran,ddsdde,ntens)
implicit none
integer :: ntens
real(8) :: stress(ntens),dstran(ntens),ddsdde(ntens,ntens)
include 'local.inc'
call unavailable(stress,dstran,ntens)
ddsdde=0.0d0
end subroutine umat
""")
    (tmp_path / "local.inc").write_text("integer :: local_count\n")
    output = tmp_path / "out"
    run = run_jacobian_transform(source, output, ntens=6)
    assert not run.succeeded
    report = json.loads((output / "dependency_bundle.json").read_text())
    assert len(report['files']) == 2
    assert all((output / item['bundled']).is_file() for item in report['files'])