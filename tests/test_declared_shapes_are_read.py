"""A promoted variable "has no confirmed shape" for several different reasons.

Thirty-three of the discovered sources were refused with one sentence --
"Promoted variable X is indexed in a stress region but has no confirmed
shape" -- and the sentence was true about the transformer's own state of
knowledge and said nothing about the source. Opened, they split into causes
that need opposite answers:

* the shape is written on the declaration rather than after the name,
  ``DOUBLE PRECISION, DIMENSION(3,3) :: BeOLD``, and the reader only looked
  after the name;
* the declaration is not read at all, because the attribute list contains a
  colon (``DIMENSION(:, :), ALLOCATABLE``) or because the type keyword is
  ``DOUBLE COMPLEX``;
* ``NAME(...)`` is not indexing: the source defines a FUNCTION of that name,
  or a derived type of that name, or the occurrence is inside a comment, or
  the name is a component of something else, ``shvars%calc_dsigma(...)``;
* the name is declared in a module in this same file, so no routine declares
  it and shared storage cannot be shadowed anyway.

Two of these have no shape to find and must stay refused -- a deferred shape
and a complex declaration -- but the refusal has to say which, because
"no confirmed shape" sends the reader to look for a DIMENSION statement that
either exists in plain sight or was never going to be there.
"""
from __future__ import annotations

import json

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.core.roles import (
    call_names_that_are_not_variables, derived_type_names,
    module_variable_names, subscripted_assignment_names, suggest_variable_roles,
)
from umat_oti.fortran.parser import parse_declaration_line
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.transform.helper_lifting import _flattened_attributed_declaration
from umat_oti.transform.source_transform import (
    _dimension_bounds, _dimension_loop_range, _has_deferred_extent,
    _has_undeclarable_extent, _shape_blockers,
)


# --------------------------------------------------------------------------
# The declaration statement itself
# --------------------------------------------------------------------------

class TestTheDimensionAttributeIsAShape:
    def test_it_reaches_every_entity_that_declares_none_of_its_own(self):
        declaration = parse_declaration_line(
            "DOUBLE PRECISION, DIMENSION(3, 3) :: BeOLD, BeTR_")
        assert [(e.name, e.dimensions) for e in declaration.entities] == [
            ("BeOLD", ("3", "3")), ("BeTR_", ("3", "3"))]

    def test_an_entity_that_states_its_own_shape_keeps_it(self):
        """Fortran gives the entity's array-spec precedence over the attribute."""
        declaration = parse_declaration_line("REAL, DIMENSION(6) :: A, B(3)")
        assert [(e.name, e.dimensions) for e in declaration.entities] == [
            ("A", ("6",)), ("B", ("3",))]

    def test_the_attribute_list_is_split_outside_its_own_parentheses(self):
        declaration = parse_declaration_line(
            "REAL(8), DIMENSION(NTENS, NTENS), INTENT(IN) :: DDSDDE")
        assert declaration.attributes == ("DIMENSION(NTENS, NTENS)", "INTENT(IN)")

    def test_the_old_form_is_unchanged(self):
        declaration = parse_declaration_line("REAL*8 X(3), Y")
        assert declaration.raw_type == "real*8"
        assert [(e.name, e.dimensions) for e in declaration.entities] == [
            ("X", ("3",)), ("Y", ())]

    def test_a_parameter_attribute_is_still_recognised(self):
        declaration = parse_declaration_line("REAL(8), PARAMETER :: TOL = 1.0D-10")
        assert declaration.has_parameter_attribute


class TestADeclarationWhoseAttributesContainAColon:
    def test_a_deferred_shape_is_a_declaration(self):
        """It was not matched at all, so the name had no type and no shape."""
        declaration = parse_declaration_line(
            "REAL(8), DIMENSION(:, :), ALLOCATABLE :: alpha_k")
        assert declaration is not None
        assert declaration.kind == "real"
        assert declaration.entities[0].dimensions == (":", ":")

    def test_a_double_colon_inside_a_string_is_not_the_separator(self):
        declaration = parse_declaration_line(
            "CHARACTER(LEN=*), PARAMETER :: S = 'a::b'")
        assert [e.name for e in declaration.entities] == ["S"]

    def test_an_assignment_is_still_not_a_declaration(self):
        assert parse_declaration_line("REALX = 3.0") is None
        assert parse_declaration_line("INTEGERS = 1") is None


class TestComplexIsAType:
    @pytest.mark.parametrize("text,shape", [
        ("DOUBLE COMPLEX :: dstrain_z(3,3)", ("3", "3")),
        ("COMPLEX*16 Z(6)", ("6",)),
        ("COMPLEX(KIND=8) :: W(3)", ("3",)),
    ])
    def test_the_declaration_is_read(self, text, shape):
        declaration = parse_declaration_line(text)
        assert declaration.kind == "complex"
        assert declaration.entities[0].dimensions == shape

    def test_double_precision_is_still_real(self):
        assert parse_declaration_line("DOUBLE PRECISION X").kind == "real"


# --------------------------------------------------------------------------
# An extent that cannot be written down
# --------------------------------------------------------------------------

class TestADimensionIsNotAlwaysABareExtent:
    @pytest.mark.parametrize("dimension,bounds", [
        ("NTENS", ("1", "NTENS")),
        ("1:NTENS", ("1", "NTENS")),
        ("0:N-1", ("0", "N-1")),
        ("MAX(1,N):M", ("MAX(1,N)", "M")),
    ])
    def test_the_bounds_are_read(self, dimension, bounds):
        assert _dimension_bounds(dimension) == bounds

    def test_a_loop_counts_between_them(self):
        """DO OTI_HI = 1, 1:NTENS is not a loop."""
        assert _dimension_loop_range("1:NTENS") == "1, NTENS"
        assert _dimension_loop_range("NTENS") == "1, NTENS"

    def test_a_deferred_dimension_has_no_upper_bound(self):
        assert _has_deferred_extent(":, :") is True
        assert _has_deferred_extent("1:NTENS, 3") is False

    def test_assumed_size_and_deferred_shape_are_both_undeclarable(self):
        assert _has_undeclarable_extent("*") is True
        assert _has_undeclarable_extent(":") is True
        assert _has_undeclarable_extent("NTENS, NTENS") is False


# --------------------------------------------------------------------------
# NAME(...) that is not indexing
# --------------------------------------------------------------------------

_FUNCTION_AND_VARIABLE = """\
      SUBROUTINE UMAT(STRESS,DSTRAN,PROPS)
      STRESS(1) = F(DSTRAN(1),PROPS)
      END
      SUBROUTINE HSELF(PROP,TERM2)
      F = (PROP(1)-PROP(4))*TERM2**2+PROP(4)
      END
      REAL*8 FUNCTION F(X,PROP)
      F = X*PROP(1)
      RETURN
      END
"""


def test_a_scalar_assignment_is_not_evidence_of_an_array():
    """F = ... says F is a variable in that scope, not that F(X,PROP) is an index."""
    assert "F" in subscripted_assignment_names("      F(1) = 2.D0\n")
    assert "F" not in subscripted_assignment_names("      F = 2.D0\n")


def test_a_function_result_assignment_does_not_make_the_name_a_variable():
    """Assigning the name is how a Fortran function returns its value."""
    only_its_own_body = (
        "      SUBROUTINE UMAT(STRESS,DSTRAN,PROPS)\n"
        "      STRESS(1) = F(DSTRAN(1),PROPS)\n"
        "      END\n"
        "      REAL*8 FUNCTION F(X,PROP)\n"
        "      F = X*PROP(1)\n"
        "      END\n")
    assert "F" in call_names_that_are_not_variables(only_its_own_body)


def test_an_assignment_outside_the_function_body_still_says_variable():
    """In HSELF, F is an ordinary scalar; the classifier must not demote it."""
    assert "F" not in call_names_that_are_not_variables(_FUNCTION_AND_VARIABLE)


def test_the_call_is_still_not_an_index_where_the_name_is_also_a_scalar():
    """F(X,PROP) is a call on the stress path whatever HSELF does with F."""
    source = ("      SUBROUTINE UMAT(STRESS,DSTRAN,PROPS)\n"
              "      STRESS(1) = F(DSTRAN(1),PROPS)\n"
              "      END\n"
              "      SUBROUTINE HSELF(PROP,TERM2)\n"
              "      F = PROP(1)*TERM2\n"
              "      END\n"
              "      REAL*8 FUNCTION F(X,PROP)\n"
              "      F = X*PROP(1)\n"
              "      END\n")
    assert _blockers(source, ["F"], {}, start=1, end=3) == []


def test_a_function_in_a_free_form_source_is_found_too():
    """The header was only ever read under fixed-form column rules."""
    free = ("module m\ncontains\n"
            "  function yf(sigma) result(y)\n"
            "    real :: y\n    y = sigma\n"
            "  end function yf\nend module m\n")
    assert "YF" in call_names_that_are_not_variables(free)


def test_a_derived_type_is_not_an_array():
    source = ("module m\n  type, public :: Share_var\n"
              "    real :: a\n  endtype Share_var\nend module m\n")
    assert derived_type_names(source) == frozenset({"SHARE_VAR"})


def test_a_module_variable_is_shared_storage():
    source = ("      module kvisual\n"
              "      implicit none\n"
              "      real*8 UserVar(70000,16,8)\n"
              "      integer nelem\n"
              "      save\n"
              "      end module\n")
    assert module_variable_names(source) == frozenset({"USERVAR", "NELEM"})


def test_a_module_variable_is_kept_real_rather_than_shadowed():
    source = ("      module kvisual\n"
              "      real*8 UserVar(70000,16,8)\n"
              "      end module\n"
              "      SUBROUTINE UMAT(STRESS,STATEV)\n"
              "      use kvisual\n"
              "      STATEV(1) = UserVar(1,1,1)\n"
              "      END\n")
    analysis = {
        "detected_variables": [{"variable_name": "USERVAR",
                                "detected_type": "real*8",
                                "detected_usage": ["read"]}],
        "region_summary": {"stress_path_variables": ["USERVAR"]},
    }
    row = suggest_variable_roles(analysis, source)[0]
    assert row["suggested OTIS role"] == "Keep real"
    assert "module" in str(row["notes"])


# --------------------------------------------------------------------------
# The blocker, and what it now says
# --------------------------------------------------------------------------

def _blockers(source_text, promoted, shapes, *, start=1, end=None):
    end = end or source_text.count("\n") + 1
    return _shape_blockers(
        source_text,
        {"seed": set(), "promote": set(promoted)},
        {"stress": [{"start_line": start, "end_line": end}]},
        {"dstran": "DSTRAN", "stress": "STRESS", "statev": "STATEV"},
        shapes,
    )


def test_a_deferred_shape_is_refused_by_name_and_not_as_a_missing_shape():
    source = ("      SUBROUTINE UMAT(STRESS)\n"
              "      ALPHA = ALPHA + ALPHA_K(I, 1)\n"
              "      END\n")
    blockers = _blockers(source, ["ALPHA_K"], {"ALPHA_K": ":, :"})
    assert len(blockers) == 1
    assert "deferred shape" in blockers[0] and "ALLOCATE" in blockers[0]
    assert "no confirmed shape" not in blockers[0]


def test_a_whole_array_reference_to_an_allocatable_is_refused_too():
    source = ("      SUBROUTINE UMAT(STRESS)\n"
              "      ALPHA = ALPHA + ALPHA_K\n"
              "      END\n")
    assert _blockers(source, ["ALPHA_K"], {"ALPHA_K": ":, :"})


def test_a_name_that_only_appears_in_a_comment_is_not_indexed():
    """! calculate the geq(g1) was the only place its file wrote geq(."""
    source = ("      SUBROUTINE UMAT(STRESS,DSTRAN)\n"
              "      ! calculate the geq(g1)\n"
              "      GEQ = DSTRAN(1)\n"
              "      END\n")
    assert _blockers(source, ["GEQ"], {}) == []


def test_a_component_reference_is_not_an_index_into_the_component_name():
    source = ("      SUBROUTINE UMAT(STRESS)\n"
              "      DSIGMA = SHVARS%CALC_DSIGMA(DEPSLN)\n"
              "      END\n")
    assert _blockers(source, ["CALC_DSIGMA"], {}) == []


def test_a_genuinely_undeclared_indexed_name_is_still_refused():
    """The guard has to keep firing; a shadow needs an extent."""
    source = ("      SUBROUTINE UMAT(STRESS)\n"
              "      STRESS(1) = WORK(1)\n"
              "      END\n")
    blockers = _blockers(source, ["WORK"], {})
    assert len(blockers) == 1 and "no confirmed shape" in blockers[0]


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

_ATTRIBUTED_SHAPE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,JSTEP,KINC)
      implicit real(8) (a-h,o-z)
      CHARACTER*80 CMNAME
      DOUBLE PRECISION, DIMENSION(1:NTENS) :: STRANNP1
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),
     2 DDSDDT(NTENS),DRPLDE(NTENS),
     3 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     4 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3),
     5 JSTEP(4)
      DO K1=1,NTENS
        STRANNP1(K1) = STRAN(K1) + DSTRAN(K1)
      END DO
      DO K1=1,NTENS
        DDSDDE(K1,K1) = PROPS(1)
      END DO
      STRESS = MATMUL(DDSDDE, STRANNP1)
      RETURN
      END
"""

_COMPLEX_STEP = _ATTRIBUTED_SHAPE.replace(
    "      DOUBLE PRECISION, DIMENSION(1:NTENS) :: STRANNP1\n",
    "      DOUBLE COMPLEX, DIMENSION(1:NTENS) :: STRANNP1\n")


def _transform(tmp_path, text, stem="src"):
    src = tmp_path / f"{stem}.f"
    src.write_text(text, encoding="utf-8")
    config, _finite = _build_contract(stem, "auto", "STRESS", "DDSDDE", 6, 1, src)
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary, _code = run_transformation(config_path, tmp_path / "out",
                                        TransformationOptions(compile_generated=False))
    return summary


def test_a_shape_written_on_the_declaration_is_enough_to_transform(tmp_path):
    summary = _transform(tmp_path, _ATTRIBUTED_SHAPE, "attributed")
    assert summary.get("transform_success") is True, summary.get("blockers")
    emitted = (tmp_path / "out" / "attributed_oti.f").read_text()
    # Declared with the extent the source states, and counted between its bounds.
    assert "TYPE(ONUMM6N1) :: STRANNP1_OTI(1:NTENS)" in emitted
    assert "DO OTI_HI = 1, NTENS" in emitted
    assert "1, 1:NTENS" not in emitted
    # The seed is still consumed on the stress path and the tangent extracted.
    assert "STRANNP1_OTI(K1) = STRAN(K1) + DSTRAN_OTI(K1)" in emitted
    assert "GETIM(STRESS_OTI(OTI_I),OTI_J)" in emitted


def test_a_complex_variable_on_the_stress_path_is_refused_by_name(tmp_path):
    summary = _transform(tmp_path, _COMPLEX_STEP, "cstep")
    assert summary.get("transform_success") is not True
    blockers = summary.get("blockers") or []
    assert any("COMPLEX" in text and "no complex shadow" in text
               for text in blockers), blockers
    assert not any("no confirmed shape" in text for text in blockers), blockers


# --------------------------------------------------------------------------
# The lifted helper's declarations
# --------------------------------------------------------------------------

class TestTheLifterReadsAnAttributedDeclaration:
    def test_the_attributes_do_not_survive_into_the_emitted_declaration(self):
        """It emitted "type(ONUMM6N1) :: , DIMENSION(3,3), INTENT(IN)  :: A"."""
        assert _flattened_attributed_declaration(
            "DOUBLE PRECISION, DIMENSION(3,3), INTENT(IN)  :: A"
        ) == "double precision A(3, 3)"

    def test_a_typed_parameter_becomes_the_parameter_statement(self):
        assert _flattened_attributed_declaration(
            "DOUBLE PRECISION, PARAMETER :: EPS = 1.0D-16"
        ) == "PARAMETER(EPS = 1.0D-16)"

    def test_an_attribute_it_cannot_express_is_left_exactly_as_written(self):
        """Dropping SAVE silently would change what the routine does."""
        text = "REAL(8), SAVE :: X"
        assert _flattened_attributed_declaration(text) == text

    def test_an_unattributed_declaration_is_untouched(self):
        assert _flattened_attributed_declaration("REAL*8 A(3,3)") == "REAL*8 A(3,3)"
