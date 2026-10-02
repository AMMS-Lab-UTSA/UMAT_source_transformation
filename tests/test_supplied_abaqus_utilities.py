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


def test_an_eigenproblem_is_supplied_only_on_the_body_that_handles_coincidence():
    """SPRIND and SPRINC return principal values and directions.

    They were refused while the only body available differentiated correctly
    only for distinct eigenvalues -- silently wrongly where they coincide,
    which is where an isotropic model spends much of its time. They are
    supplied now because they are built on the DSPEVD body, which treats a
    repeated cluster deliberately (the cluster mean, whose derivative exists).
    The behaviour is pinned numerically in
    tests/test_transform_supplied_abaqus_utilities_differentiate.py
    (test_a_repeated_pair_keeps_the_sum_of_its_derivatives); this test pins
    that the supply rests on that body and on nothing else.
    """
    for name in ("SPRIND", "SPRINC"):
        assert name in UTILITY_DEFINITIONS
        assert name in available_definitions([name])
    assert "DSPEVD" in UTILITY_DEFINITIONS["SPRIND"].upper()


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
    from umat_oti.transform.abaqus_utility_definitions import \
        supply_reachable_definitions

    # Since 5dacb13 the transform supplies only what is reachable from the
    # lifted roots, through supply_reachable_definitions, rather than calling
    # available_definitions itself. What matters is that a UMAT calling ROTSIG
    # comes out of that step with the body the lifter will look for.
    assert source_transform.supply_reachable_definitions is \
        supply_reachable_definitions
    umat = (
        "      SUBROUTINE UMAT(STRESS, DROT, NDI, NSHR)\n"
        "      DIMENSION STRESS(NDI+NSHR), DROT(3,3)\n"
        "      CALL ROTSIG(STRESS, DROT, STRESS, 1, NDI, NSHR)\n"
        "      RETURN\n"
        "      END\n")
    parsed = source_transform._parse_source(umat, "umat.f")
    supplied_parse, supplied = supply_reachable_definitions(parsed, ["UMAT"])
    assert supplied == ("ROTSIG",)
    assert "ROTSIG" in {routine.upper_name for routine in supplied_parse.subroutines}
