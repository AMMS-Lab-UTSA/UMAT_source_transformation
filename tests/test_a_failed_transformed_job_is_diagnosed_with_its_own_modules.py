"""diagnose_transformed (pass22: all three transformed_job_failed rows).

The converted source ``use``s the support modules. Compiled alone it fails
with "error in opening the compiled module file" -- about what is missing
beside the file -- and the reason still read "the transform emitted Fortran the
compiler will not accept". With the job's module directory the compile finds
them; when something is still missing the answer is "not established"; and
the solver's own crash report names the routine it died in.
"""
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.abaqus.job_status import exception_summary

pytestmark = pytest.mark.unit

TOOL = Path(__file__).resolve().parents[1] / "tools" / "verify_store_in_abaqus.py"

EXCEPTION = """\
<Description>
      ABAQUS/standard rank 00 pid 1208995 received signal 6 (Aborted)

</Description>

<Context>
   ELEMENT LOOP
</Context>

<Callstack>
   1) libc.so.6                  0x0004300b ! gsignal          ??:?
   2) libc.so.6                  0x00022859 ! abort            ??:?
   3) libifcoremt.so.5           0x000f2245 ! for__compute_filename ??:?
   4) libstandardU.so            0x0015306e ! dsyevj3_oti      ??:?
   5) libstandardU.so            0x000121dd ! umat             ??:?
</Callstack>
"""


def _tool():
    spec = importlib.util.spec_from_file_location("verify_tool_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_tool_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_the_crash_report_is_read_into_signal_context_and_frames(tmp_path):
    (tmp_path / "transformed.00.1208995.exception").write_text(EXCEPTION)
    summary = exception_summary(tmp_path)
    assert summary["signal"] == "6 (Aborted)" and summary["context"] == "ELEMENT LOOP"
    assert [f["symbol"] for f in summary["top_frames"]] == [
        "gsignal", "abort", "for__compute_filename", "dsyevj3_oti", "umat"]
    assert exception_summary(tmp_path / "nowhere") == {}


def _fake_abaqus(tmp_path):
    """A compiler that finds module `otim6n1` only if its .mod is on -I."""
    cc = tmp_path / "fakecc"
    cc.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "a = sys.argv[1:]\n"
        "dirs = [t[2:] for t in a if t.startswith('-I')]\n"
        "if not any(os.path.isfile(os.path.join(d, 'otim6n1.mod')) for d in dirs):\n"
        "    sys.stderr.write('x.for(3): error #7002: Error in opening the compiled module file.  "
        "Check INCLUDE paths.   [OTIM6N1]\\n')\n"
        "    sys.exit(1)\n"
        "open(a[a.index('-o') + 1], 'w').write('o')\n")
    cc.chmod(cc.stat().st_mode | stat.S_IEXEC)
    ab = tmp_path / "bin" / "abaqus"
    ab.parent.mkdir()
    ab.write_text(f"#!{sys.executable}\n"
                  f"print(\"compile_fortran='{cc} -c %P'\")\nprint(\"link_sl='x'\")\n")
    ab.chmod(ab.stat().st_mode | stat.S_IEXEC)
    return ab


@pytest.fixture
def stored(tmp_path, monkeypatch):
    ab = _fake_abaqus(tmp_path)
    monkeypatch.setenv("PATH", str(ab.parent) + os.pathsep + os.environ["PATH"])
    directory = tmp_path / "store"
    directory.mkdir()
    entry = directory / "u_oti.for"
    entry.write_text("      SUBROUTINE UMAT\n      USE otim6n1\n      END\n")
    return SimpleNamespace(directory=directory, entry_source=entry)


def test_without_the_modules_the_answer_is_not_established_not_a_defect_of_the_transform(
        stored, tmp_path):
    out = _tool().diagnose_transformed(stored, tmp_path / "diag")
    assert out["reason"].startswith("not established whether the converted source compiles")
    assert "the transform emitted Fortran" not in out["reason"]
    assert out["compile"]["missing_dependencies"]


def test_with_the_job_module_directory_the_converted_source_compiles(stored, tmp_path):
    jobdir = tmp_path / "job"
    jobdir.mkdir()
    (jobdir / "otim6n1.mod").write_text("m")
    out = _tool().diagnose_transformed(stored, tmp_path / "diag", module_dirs=[jobdir])
    assert out["compile"]["ok"] is True
    assert out["reason"].startswith("the converted source compiles with Abaqus's own")


def test_a_real_defect_is_still_the_transforms_to_answer_for(stored, tmp_path, monkeypatch):
    stored.entry_source.write_text("      SUBROUTINE UMAT\n      END\n")
    cc = tmp_path / "fakecc"
    cc.write_text(f"#!{sys.executable}\nimport sys\n"
                  "sys.stderr.write('u_oti.for(2): error #6410: This name has not been "
                  "declared as an array or a function.\\n')\nsys.exit(1)\n")
    out = _tool().diagnose_transformed(stored, tmp_path / "diag2")
    assert out["reason"].startswith("the transform emitted Fortran the compiler will not accept")
