"""A bundled file's INCLUDE points at the output directory, not at itself.

``umat_oti.transform.dependency_bundle`` stages the entry source, its helpers
and their literal includes under ``OUT/dependencies/`` and rewrites every
reference it resolved to ``dependencies/<name>`` -- a path relative to ``OUT``,
because ``OUT`` is where the emitted source is compiled from. A staged file
itself sits one level down, so resolving its own rewritten reference against
its own directory looks for ``dependencies/dependencies/<name>``.

The helper lifter did exactly that and refused two sources that had
transformed the pass before:

    HelperLiftingError: Missing helper INCLUDE
        'dependencies/aba_param__83d13fed26c5.inc'
        relative to <work>/out/dependencies/enhanced_curing.for

Two separate things are wrong in that one message. The path does not resolve,
and the file it names is Abaqus's parameter header under the name the bundler
gave it after a collision -- which the lifter must skip, as it skips
``aba_param.inc``, because the solver supplies it and its implicit rules must
not be inlined into a body that writes its own.
"""
from pathlib import Path
import shutil

import pytest

from umat_oti.transform.helper_lifting import (
    HelperLiftingError, _expand_helper_includes, _helper_include_target,
    _is_runtime_header)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.mark.parametrize("name, runtime", [
    ("ABA_PARAM.INC", True),
    ("aba_param.inc", True),
    ("dependencies/aba_param__83d13fed26c5.inc", True),
    ("aba_param__83d13fed26c5_1.inc", True),
    ("my_aba_param.inc", False),
    ("dependencies/local_decls.inc", False),
    ("aba_param_extra.inc", False),
])
def test_the_runtime_header_is_recognised_under_the_name_the_bundler_gave_it(
        name, runtime):
    """A collision renames it; skipping only the literal name let it through."""
    assert _is_runtime_header(name) is runtime


def test_a_staged_file_resolves_its_include_against_the_output_directory(tmp_path):
    output = tmp_path / "out"
    (output / "dependencies").mkdir(parents=True)
    staged = output / "dependencies" / "helper.for"
    staged.write_text("      END\n", encoding="utf-8")
    include = output / "dependencies" / "decls.inc"
    include.write_text("      PARAMETER (FACTOR=2.0D0)\n", encoding="utf-8")

    assert _helper_include_target("dependencies/decls.inc", staged) == include


def test_an_ordinary_source_still_resolves_against_its_own_directory(tmp_path):
    source = tmp_path / "helper.for"
    source.write_text("      END\n", encoding="utf-8")
    include = tmp_path / "decls.inc"
    include.write_text("      PARAMETER (FACTOR=2.0D0)\n", encoding="utf-8")

    assert _helper_include_target("decls.inc", source) == include


def test_an_include_that_is_nowhere_still_names_what_was_asked_for(tmp_path):
    output = tmp_path / "out"
    (output / "dependencies").mkdir(parents=True)
    staged = output / "dependencies" / "helper.for"
    staged.write_text("      INCLUDE 'dependencies/absent.inc'\n", encoding="utf-8")

    with pytest.raises(HelperLiftingError, match="dependencies/absent.inc"):
        _expand_helper_includes(staged.read_text().splitlines(), "fixed", staged)


def test_a_staged_include_is_expanded_and_the_renamed_header_is_skipped(tmp_path):
    output = tmp_path / "out"
    (output / "dependencies").mkdir(parents=True)
    staged = output / "dependencies" / "helper.for"
    staged.write_text(
        "      INCLUDE 'dependencies/aba_param__83d13fed26c5.inc'\n"
        "      INCLUDE 'dependencies/decls.inc'\n"
        "      END\n", encoding="utf-8")
    (output / "dependencies" / "aba_param__83d13fed26c5.inc").write_text(
        "      IMPLICIT REAL*8(A-H,O-Z)\n", encoding="utf-8")
    (output / "dependencies" / "decls.inc").write_text(
        "      PARAMETER (FACTOR=2.0D0)\n", encoding="utf-8")

    expanded = _expand_helper_includes(
        staged.read_text().splitlines(), "fixed", staged)

    assert "      PARAMETER (FACTOR=2.0D0)" in expanded
    assert not any("IMPLICIT" in line for line in expanded), (
        "the solver supplies the header; inlining it fights the lifted "
        "body's own implicit rules")


UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'aba_param.inc'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      EMOD=PROPS(1)
      CALL SCALE_STRESS(STRESS,DSTRAN,EMOD,NTENS)
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=0.D0
        END DO
        DDSDDE(K1,K1)=EMOD
      END DO
      RETURN
      END
      SUBROUTINE SCALE_STRESS(SIG,DEPS,EMOD,N)
      INCLUDE 'ABA_PARAM.INC'
      INCLUDE 'local_decls.inc'
      DIMENSION SIG(N),DEPS(N)
      DO K1=1,N
        SIG(K1)=SIG(K1)+EMOD*FACTOR*DEPS(K1)
      END DO
      RETURN
      END
"""


@pytest.mark.integration
def test_a_source_whose_header_copy_collides_still_transforms(tmp_path):
    """The Worlthen shape: two spellings of the header, plus a real include.

    Two casings of ``aba_param`` in one closure are distinct files on a
    case-sensitive filesystem. While the bundler staged the header it renamed
    the second copy, and the lifter then had to recognise the rename AND
    resolve the rewritten path. The bundler now never stages the solver's
    header at all (it is the solver's, reached on its include path), so the
    collision cannot arise; what is pinned here is the outcome -- the source
    transforms, its own include is staged, and no copy of the header is.
    """
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.jacobian_request import run_jacobian_transform

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "umat.for").write_text(UMAT, encoding="utf-8")
    (inputs / "local_decls.inc").write_text(
        "      PARAMETER (FACTOR=2.0D0)\n", encoding="utf-8")
    _write_aba_param_stub(inputs)

    output = tmp_path / "out"
    run = run_jacobian_transform(inputs / "umat.for", output, ntens=6)

    assert run.succeeded, run.report
    staged = sorted(path.name for path in (output / "dependencies").iterdir())
    assert not any(name.lower().startswith("aba_param") for name in staged), (
        "the solver's header is never staged into the artefact")
    assert "local_decls.inc" in staged


def test_the_bundled_entry_source_is_where_the_lifter_reads_from(tmp_path):
    """Guards the assumption the resolution rests on: the staged file's parent."""
    shutil.rmtree(tmp_path / "nothing", ignore_errors=True)
    staged = tmp_path / "out" / "dependencies" / "u.for"
    staged.parent.mkdir(parents=True)
    staged.write_text("      END\n", encoding="utf-8")

    assert staged.parent.name == "dependencies"
    assert _helper_include_target("dependencies/absent.inc", staged) == (
        staged.parent / "dependencies" / "absent.inc")
