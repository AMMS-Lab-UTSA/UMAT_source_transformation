"""A file with no UMAT in it should say which of the three reasons applies.

"Compact configuration source file does not contain a detectable UMAT routine"
names no construct and no line, so it cannot be read as anything but a verdict
on the file. Three quite different situations reached it and were reported
identically:

* ``sas229__geomat/tests/umat_integration.f90`` is a ``program main`` that
  declares UMAT in an INTERFACE block and CALLs it. There is no UMAT here
  because there was never meant to be one -- it is compiled from another file
  -- and the right thing for a reader to do is point the transform elsewhere.
* a file that defines other routines but no UMAT, where naming one in the
  configuration is the answer.
* a file the Fortran reader could not parse at all, usually because a
  free-form source is named ``.f`` or ``.for`` and is being read by column.

Until the INTERFACE fix, the first of these did not even reach this message:
the interface body was parsed as a definition, so the driver looked like a
UMAT and refused four anchors down instead.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.core.config_loader import _no_detectable_umat_message  # noqa: E402
from umat_oti.core.transformation_anchors import (  # noqa: E402
    ABAQUS_UMAT_ARGUMENT_COUNT, _not_an_abaqus_umat_issue)
from umat_oti.fortran.scanner import analyze_fortran_source  # noqa: E402

pytestmark = pytest.mark.unit

DRIVER = """program main
    implicit none
    interface
      subroutine umat(stress, statev, ddsdde, ntens)
        real(8) :: stress(ntens), statev(1), ddsdde(ntens,ntens)
        integer :: ntens
      end subroutine umat
    end interface
    real(8) :: stress(6), statev(1), ddsdde(6,6)
    call umat(stress, statev, ddsdde, 6)
end program main
"""

HELPERS_ONLY = """      subroutine kinver(a, b)
      real*8 a(3,3), b(3,3)
      b = a
      end
      subroutine ktrace(a, t)
      real*8 a(3,3), t
      t = a(1,1) + a(2,2) + a(3,3)
      end
"""


def _message(text, name, tmp_path):
    path = tmp_path / name
    path.write_text(text)
    return _no_detectable_umat_message(analyze_fortran_source(path))


def test_an_interface_only_driver_names_the_interface_and_its_lines(tmp_path):
    message = _message(DRIVER, "umat_integration.f90", tmp_path)
    assert "INTERFACE" in message
    assert "lines 4-7" in message or "line 4" in message, message
    assert "defined" not in message.split(".")[0]
    assert "compiled from another file" in message


def test_a_file_of_helpers_lists_what_it_does_define(tmp_path):
    message = _message(HELPERS_ONLY, "helpers.f", tmp_path)
    assert "KINVER" in message and "KTRACE" in message
    assert "source.umat" in message


def test_an_unparseable_file_points_at_the_source_form(tmp_path):
    message = _message("this is not fortran at all\n", "notes.f", tmp_path)
    assert "source form" in message
    assert "free-form file named .f or .for" in message


# --------------------------------------------------------------------------
# A UMAT under the author's own argument names is not "not a UMAT"


def _issue(arguments):
    analysis = {"detected_subroutines": [{"name": "UMAT", "arguments": list(arguments),
                                          "line_numbers": [1, 400]}]}
    return _not_an_abaqus_umat_issue(analysis, {}, "UMAT")


def test_a_renamed_interface_is_reported_as_a_mapping_gap_not_a_wrong_file():
    """sahmotaman's TMM-FE sources declare the Abaqus interface under other names.

    ``subroutine umat(sigma, sv, C, sse, delta_w_p, ...)`` takes the 37
    arguments Abaqus passes a UMAT and spells none of them STRESS or DDSDDE.
    Reporting that as "not an Abaqus UMAT" says the source is wrong when the
    configuration is incomplete, and sends the reader to look for a UMAT that
    is already in front of them.
    """
    arguments = ["SIGMA", "SV", "C"] + [f"A{index}" for index in range(4, 38)]
    assert len(arguments) == ABAQUS_UMAT_ARGUMENT_COUNT
    issue = _issue(arguments)
    assert issue["kind"] == "umat_interface_uses_the_authors_own_argument_names"
    assert issue["required_json_field"] == "mapping.stress"
    assert "37 arguments" in issue["message"] and "SIGMA" in issue["message"]


def test_a_four_argument_demonstration_routine_is_still_not_a_umat():
    """The case the original check was written for keeps its own verdict."""
    issue = _issue(["A", "B", "C", "D"])
    assert issue["kind"] == "selected_routine_is_not_an_abaqus_umat"
    assert "4 arguments" in issue["message"]
    assert str(ABAQUS_UMAT_ARGUMENT_COUNT) in issue["message"]


def test_the_real_interface_is_never_reported_at_all():
    assert _issue(["STRESS", "STATEV", "DDSDDE"]) is None
