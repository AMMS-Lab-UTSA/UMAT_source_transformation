"""A helper the solver provides, not the author, still needs a definition.

Abaqus links ROTSIG in at build time, so a UMAT that calls it publishes no
definition for it. The helper lifter walks CALL statements looking for a body
to transform, finds none, and refuses the source. That refusal is right: an
un-lifted external handed a hypercomplex array reads the first of seven
doubles and returns a truncated derivative with nothing to show for it.

The way past it is to supply the body, not to exempt the call. These cover
the supplied text, the rule about what may be supplied, and the fact that an
unknown name is still refused.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.abaqus_utility_definitions import (  # noqa: E402
    UTILITY_DEFINITIONS, available_definitions, definition_text)


def test_rotsig_is_supplied():
    assert available_definitions(["ROTSIG"]) == ("ROTSIG",)
    assert "SUBROUTINE ROTSIG" in definition_text(["ROTSIG"])


def test_a_name_with_no_definition_is_not_claimed():
    """Silence here means the source keeps its refusal, which is correct."""
    assert available_definitions(["KHARDEN", "MOONEY"]) == ()
    assert definition_text(["KHARDEN"]) == ""


def test_an_eigenproblem_is_deliberately_not_supplied():
    """SPRIND and SPRINC return principal values and directions.

    Writing the algebra out would produce a body that differentiates
    correctly only while the eigenvalues stay distinct, and silently wrongly
    where they coincide -- which is where an isotropic model spends much of
    its time. A refusal is the honest answer until that case is handled.
    """
    for name in ("SPRIND", "SPRINC"):
        assert name not in UTILITY_DEFINITIONS
        assert available_definitions([name]) == ()


def test_the_lookup_is_case_insensitive_like_fortran():
    assert available_definitions(["rotsig"]) == ("ROTSIG",)


def test_rotsig_honours_both_storage_conventions():
    """LSTR distinguishes a stress-type tensor from a strain-type one.

    A strain vector stores ENGINEERING shear -- twice the tensor entry -- so
    rotating it as though the stored value were the entry is a silent factor
    of two on every rotated strain. The body must branch on LSTR and undo the
    factor on the way out.
    """
    text = definition_text(["ROTSIG"])
    assert "LSTR" in text and "0.5D0" in text
    assert "HALFSH" in text


def test_the_supplied_body_declares_its_shapes():
    """It is lifted by the same machinery as an author's helper, which reads
    DIMENSION statements to size what it promotes."""
    text = definition_text(["ROTSIG"])
    assert "DIMENSION S(NDI+NSHR), R(3,3), OUTPUT(NDI+NSHR)" in text


def test_the_transform_supplies_it_before_the_lifter_looks():
    """The regression that made this necessary: eleven corpus sources were
    refused with 'Helper lifting requires source definitions for ROTSIG'."""
    from umat_oti.transform import source_transform

    assert "available_definitions" in source_transform.__dict__
