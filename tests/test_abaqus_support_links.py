"""Building the OTI support the way Abaqus will link it.

The rule these hold down is that the two command lines Abaqus reports are
extended and never replaced. An object compiled with different floating-point
or calling-convention flags still links; it just computes something else, which
is the failure this is built to avoid.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.support import (
    SupportBuild, _compile_command, build_support, compile_order,
    install_support, link_environment)


def test_the_order_comes_from_the_transform(tmp_path):
    """Module dependencies make it load-bearing, and the transform knows it."""
    for name in ("a.f90", "b.f90", "c.f90"):
        (tmp_path / name).write_text("end\n")
    (tmp_path / "compile_order.txt").write_text("b.f90\n# a comment\n\na.f90\nc.f90\n")
    assert [p.name for p in compile_order(tmp_path)] == ["b.f90", "a.f90", "c.f90"]


def test_a_named_unit_that_is_not_there_is_dropped_not_guessed(tmp_path):
    (tmp_path / "a.f90").write_text("end\n")
    (tmp_path / "compile_order.txt").write_text("a.f90\nmissing.f90\n")
    assert [p.name for p in compile_order(tmp_path)] == ["a.f90"]


def test_no_order_file_means_no_units(tmp_path):
    assert compile_order(tmp_path) == ()


def test_the_placeholders_are_substituted_in_place(tmp_path):
    """%I and %P sit where Abaqus put them; appending them would move them."""
    # Abaqus writes the include joined to its flag, which is the case a
    # whole-token substitution silently gets wrong.
    template = "ifort -c -fpp -I%I -I/opt/simulia %P"
    command = _compile_command(template, tmp_path / "u.f90", tmp_path / "inc")
    assert command[:3] == ["ifort", "-c", "-fpp"]
    assert command[3] == "-I" + str(tmp_path / "inc")
    assert command[4] == "-I/opt/simulia"        # Abaqus's own, untouched
    assert command[5] == str(tmp_path / "u.f90")
    assert not any("%I" in part or "%P" in part for part in command)
    # the module output has to land where the next unit looks for it
    assert command[command.index("-module") + 1] == str(tmp_path / "inc")
    assert command[-1] == str(tmp_path / "inc" / "u.o")


def test_the_environment_extends_both_lines_and_replaces_neither(tmp_path):
    build = SupportBuild(objects=(tmp_path / "m.o", tmp_path / "n.o"),
                         include_dir=tmp_path, ok=True)
    text = link_environment(build)
    assert "compile_fortran = compile_fortran[:1] +" in text
    assert "link_sl = list(link_sl)" in text
    # never an assignment from a literal list
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("compile_fortran =", "link_sl =")):
            assert "compile_fortran" in stripped or "link_sl" in stripped.split("=")[1] \
                or stripped.startswith("link_sl = list(link_sl)")
    assert repr(str(tmp_path / "m.o")) in text
    assert repr(str(tmp_path / "n.o")) in text


def test_the_objects_go_after_the_user_object(tmp_path):
    """A module's object must follow the code that uses it, not precede it."""
    text = link_environment(SupportBuild(objects=(tmp_path / "m.o",), ok=True))
    assert "link_sl.index('%F') + 1" in text


def test_the_environment_infers_no_path_at_all(tmp_path):
    """Abaqus executes this file with no __file__, and from a cwd of its own.

    Both were tried. The file cannot locate itself, and locating it through the
    working directory makes the link depend on where the solver chose to run.
    Every path is known when the file is written, so every path is written out.
    """
    build = SupportBuild(objects=(tmp_path / "m.o",), include_dir=tmp_path, ok=True)
    text = link_environment(build)
    assert "__file__" not in text and "getcwd" not in text
    assert f"-I{tmp_path}" in text
    assert str(tmp_path / "m.o") in text


def test_nothing_is_installed_for_a_build_that_failed(tmp_path):
    assert install_support(SupportBuild(reason="did not compile"), tmp_path) is None
    assert not (tmp_path / "abaqus_v6.env").exists()


def test_an_installed_environment_is_named_what_abaqus_reads(tmp_path):
    path = install_support(SupportBuild(objects=(tmp_path / "m.o",), ok=True), tmp_path)
    assert path.name == "abaqus_v6.env"


def test_no_units_is_stated_not_treated_as_success(tmp_path):
    build = build_support((), tmp_path)
    assert not build.ok and "no support units" in build.reason


def test_a_missing_abaqus_is_a_stated_reason(tmp_path):
    build = build_support((tmp_path / "a.f90",), tmp_path,
                          abaqus="abaqus-that-is-not-installed")
    assert not build.ok and "not on PATH" in build.reason
