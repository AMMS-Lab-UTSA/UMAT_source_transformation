"""The support units the transform emits are compiled with their console
writes silenced, like the author's own source (pass22 thealanjason
VISC_OGDEN_2EL / 3EL): the lifted helper kept the author's
``PRINT *, "DSYEVJ3: No convergence."``, Abaqus aborts on a console write, and
the original job -- silenced -- did not.
"""
import json
import os
import stat
import sys

import pytest

from umat_oti.abaqus import support

pytestmark = pytest.mark.unit

HELPER = """\
subroutine dsyevj3_oti(a)
    double precision :: a
    a = a + 1.0d0
    PRINT *, "DSYEVJ3: No convergence."
    include 'dependencies/extra.inc'
end subroutine dsyevj3_oti
"""

QUIET = "subroutine quiet(a)\n    double precision :: a\n    a = a + 1.0d0\nend subroutine quiet\n"


def test_a_console_write_is_commented_out_and_reported(tmp_path):
    unit = tmp_path / "umat_oti_helpers.f90"
    unit.write_text(HELPER)
    copy, removed = support.silenced_copy(unit, tmp_path / "work")
    assert removed == ['PRINT *, "DSYEVJ3: No convergence."']
    text = copy.read_text()
    assert '!     OTIS-SILENCED: PRINT *, "DSYEVJ3: No convergence."' in text
    assert "a = a + 1.0d0" in text and "include 'dependencies/extra.inc'" in text
    assert (copy.parent / "umat_oti_helpers.f90.removed.txt").read_text().strip() == removed[0]
    assert unit.read_text() == HELPER                          # the store is untouched


def test_a_unit_with_nothing_to_silence_is_compiled_as_it_is(tmp_path):
    unit = tmp_path / "quiet.f90"
    unit.write_text(QUIET)
    copy, removed = support.silenced_copy(unit, tmp_path / "work")
    assert copy == unit and removed == []
    assert not (tmp_path / "work" / "_silenced").exists()


def _fake_abaqus(tmp_path):
    """An 'abaqus' that reports a compile line, and a compiler that records it."""
    log = tmp_path / "compiles.jsonl"
    cc = tmp_path / "fakecc"
    cc.write_text(f"#!{sys.executable}\n"
                  "import json, sys\n"
                  "a = sys.argv[1:]\n"
                  f"open({str(log)!r}, 'a').write(json.dumps(a) + '\\n')\n"
                  "open(a[a.index('-o') + 1], 'w').write('o')\n")
    cc.chmod(cc.stat().st_mode | stat.S_IEXEC)
    ab = tmp_path / "bin" / "abaqus"
    ab.parent.mkdir()
    ab.write_text(f"#!{sys.executable}\n"
                  f"print(\"compile_fortran='{cc} -c %P'\")\n"
                  "print(\"link_sl='x'\")\n")
    ab.chmod(ab.stat().st_mode | stat.S_IEXEC)
    return ab, log


def test_build_support_compiles_the_silenced_copy_and_records_what_it_removed(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    (store / "umat_oti_helpers.f90").write_text(HELPER)
    (store / "quiet.f90").write_text(QUIET)
    ab, log = _fake_abaqus(tmp_path)
    monkeypatch.setenv("PATH", str(ab.parent) + os.pathsep + os.environ["PATH"])
    build = support.build_support([store / "umat_oti_helpers.f90", store / "quiet.f90"],
                                  tmp_path / "work", abaqus="abaqus")
    assert build.ok, build.reason
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    sources = [next(t for t in call if t.endswith(".f90")) for call in calls]
    assert sources[0].endswith("_silenced/umat_oti_helpers.f90")
    assert sources[1] == str(store / "quiet.f90")
    assert f"-I{store}" in calls[0] and f"-I{store}" not in calls[1]   # relative INCLUDEs still resolve
    assert build.silenced == {"umat_oti_helpers.f90": ['PRINT *, "DSYEVJ3: No convergence."']}
    assert build.as_dict()["console_writes_silenced"] == {
        "umat_oti_helpers.f90": ['PRINT *, "DSYEVJ3: No convergence."']}
