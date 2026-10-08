"""B20: Vera's five D-28 separate-line rules and the published-text-compiles rule.

Each rule yields an ADDITIONAL verdict beside the published one. These tests pin
the rule text's constants, the planted canaries Vera specified, and the fact
that the published comparison code is untouched (the rule-1 code path at the
double epsilon reproduces compare_calls exactly).
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TOOL = Path(__file__).resolve().parents[1] / "tools" / "d28_lines.py"


def _lines():
    spec = importlib.util.spec_from_file_location("d28_lines_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d28_lines_under_test"] = module
    spec.loader.exec_module(module)
    return module


D = _lines()


def _calls(n, stress, k, state=None):
    return [{"STRESS": [stress * (1 + 0.1 * i)], "STATEV": list(state or [1.0]),
             "DDSDDE": [k]} for i in range(n)]


# ---- constants fixed by Vera ------------------------------------------------

def test_the_constants_vera_fixed_are_the_ones_in_the_code():
    assert (D.R1_FACTOR, D.R1_MIN_ULPS, D.R1_CAP_ULPS) == (4.0, 2.0, 64.0)
    assert D.EPS32 == 2.0 ** -23
    assert D.R4_FLOOR_FACTOR == 8.0
    assert (D.R4_CANARY_FAIL, D.R4_CANARY_PASS) == (1e-12, 1e-17)
    assert D.R3_MUTATION == pytest.approx(1.001)
    assert D.R5_FRACTIONS == (0.5, 0.9)


# ---- rule 1 -------------------------------------------------------------------

def test_the_double_epsilon_reproduces_the_published_comparison_exactly():
    ref, trn = _calls(6, 10.0, 1e3), _calls(6, 10.0, 1e3)
    trn[2]["STRESS"][0] += 3e-12
    published = D._compare.compare_calls(ref, trn, stiffness=1e3, tolerance=1e-10, ulps=7.0).as_dict()
    with D.epsilon(D.EPS64):
        again = D._compare.compare_calls(ref, trn, stiffness=1e3, tolerance=1e-10, ulps=7.0).as_dict()
    assert json.dumps(published, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_the_epsilon_swap_is_undone_even_when_the_body_raises():
    before = D._compare.EPS
    with pytest.raises(RuntimeError):
        with D.epsilon(D.EPS32):
            assert D._compare.EPS == D.EPS32
            raise RuntimeError
    assert D._compare.EPS == before


def test_the_native_unit_is_2_to_the_29_wider_and_the_bound_follows():
    ref, trn = _calls(4, 10.0, 1.0), _calls(4, 10.0, 1.0)
    quiet = [_calls(4, 10.0, 1.0)]                 # a draw that does not move: floor 0 -> clip to 2
    native = D.rule_1_float32_native_primal_unit(ref, trn, quiet, stiffness=1.0)
    with D.epsilon(D.EPS64):
        double = D._compare.compare_calls(ref, trn, stiffness=1.0, tolerance=1e-10, ulps=2.0)
    assert native["ulps"] == 2.0
    scale = 10.0 * (1 + 0.1 * 3)                       # max |STRESS| over the calls
    ulp_part_native = native["stress_bound"] - 1e-10 * scale
    ulp_part_double = double.stress_bound - 1e-10 * scale
    assert ulp_part_native / ulp_part_double == pytest.approx(2.0 ** 29, rel=1e-6)


def test_canary_a_1e6_relative_error_fails_when_the_stiffness_is_modest():
    ref, trn = _calls(4, 10.0, 1.0), _calls(4, 10.0, 1.0)
    draws = [_calls(4, 10.0, 1.0)]
    planted = D.plant_relative_error(trn, D.R1_CANARY_RELATIVE)
    verdict = D.rule_1_float32_native_primal_unit(ref, planted, draws, stiffness=1.0)
    assert verdict["agrees"] is False


def test_canary_is_swallowed_when_the_stiffness_dwarfs_the_stress_which_is_the_wrinkle_regime():
    """K = 1.5e8 against a stress of 27 (the Wrinkle rows): eps32*K = 18 > the stress.
    The planted 1e-6 error does NOT fail. The rule as written cannot be admitted on
    such a row, and the report says so rather than counting it."""
    ref, trn = _calls(4, 27.0, 1.5e8), _calls(4, 27.0, 1.5e8)
    draws = [_calls(4, 27.0, 1.5e8)]
    planted = D.plant_relative_error(trn, D.R1_CANARY_RELATIVE)
    verdict = D.rule_1_float32_native_primal_unit(ref, planted, draws, stiffness=1.5e8)
    assert verdict["agrees"] is True
    assert verdict["stress_bound"] > 27.0


def test_a_passing_row_stays_passing_under_the_wider_unit():
    ref, trn = _calls(5, 3.0, 50.0), _calls(5, 3.0, 50.0)
    with D.epsilon(D.EPS64):
        published = D._compare.compare_calls(ref, trn, stiffness=50.0, tolerance=1e-10, ulps=2.0)
    native = D.rule_1_float32_native_primal_unit(ref, trn, [_calls(5, 3.0, 50.0)], stiffness=50.0)
    assert published.agrees and native["agrees"]


def test_the_single_precision_scan_names_a_promoted_real_declaration():
    original = "      REAL  G11,G12\n      EMOD=1.0D0\n"
    transformed = "      TYPE(ONUMM6N1) :: G11_OTI, G12_OTI, OTHER_OTI\n"
    found = D.survey_single_precision(original, transformed)
    assert found["widened"] == ["G11", "G12"]
    assert D.survey_single_precision("      REAL*8 G11\n", transformed)["widened"] == []


# ---- rule 4 -------------------------------------------------------------------

def _state_calls(slot_values, big=1.0):
    return [{"STATEV": [big, v], "STRESS": [0.0], "DDSDDE": [1.0]} for v in slot_values]


def test_rule_4_a_dust_slot_that_the_published_rule_fails_passes_with_the_floor():
    ref = _state_calls([0.0, -2.2e-19, 4.4e-19])
    trn = _state_calls([-4.3e-50, 0.0, 2.2e-19])
    out = D.state_slot_floor_compare(ref, trn)
    assert out["state_agrees_published"] is False
    assert out["state_agrees_with_floor"] is True
    assert out["floor_F"] == pytest.approx(8 * D.EPS64 * 1.0)


def test_rule_4_canaries_a_real_error_of_1e12_S_fails_and_1e17_S_passes():
    ref = _state_calls([0.5, 0.25, 0.125], big=7000.0)
    trn = _state_calls([0.5, 0.25, 0.125], big=7000.0)
    out = D.rule_4_canaries(ref, trn)
    assert out["applicable"] and out["slot"] == 2
    assert out["fail_1e-12"]["as_required"] is True and out["fail_1e-12"]["agrees"] is False
    assert out["pass_1e-17"]["as_required"] is True and out["pass_1e-17"]["agrees"] is True


def test_rule_4_canary_is_not_applicable_when_every_slot_is_as_large_as_S():
    ref = _state_calls([5.0, 6.0], big=7.0)
    assert D.rule_4_canaries(ref, ref)["applicable"] is False


def test_rule_4_never_makes_a_passing_state_fail_and_never_touches_stress():
    ref = _state_calls([0.3, 0.2])
    out = D.state_slot_floor_compare(ref, ref)
    assert out["state_agrees_published"] and out["state_agrees_with_floor"]
    c = D.rule_4_history_verdict(
        [{"STRESS": [1.0], "STATEV": [1.0], "DDSDDE": [10.0]}],
        [{"STRESS": [1.0 + 1e-3], "STATEV": [1.0], "DDSDDE": [10.0]}],
        tolerance=1e-10, stiffness=10.0, ulps=2.0)
    assert c["stress_part_ok"] is False and c["rule_4_agrees"] is False


def test_rule_4_an_excluded_slot_is_not_compared():
    ref = _state_calls([1.0, 2.0])
    trn = _state_calls([9.0, 2.0])
    assert D.state_slot_floor_compare(ref, trn)["state_agrees_with_floor"] is False
    assert D.state_slot_floor_compare(ref, trn, excluded=[2])["state_agrees_with_floor"] is True


# ---- rule 5 -------------------------------------------------------------------

def test_rule_5_th005_pre_activation_states_are_nearest_half_and_nine_tenths():
    # activation ordinal 15; the pool the published rule draws on is positions 0..12
    picked = D.nearest_ordinals(list(range(13)), 15)
    assert [p + 1 for p in picked] == [7, 13]       # not 1 and 13


def test_rule_5_a_tie_goes_to_the_smaller_ordinal_and_the_two_are_distinct():
    assert D.nearest_ordinals([2, 3], 7) == [2, 3]
    assert len(set(D.nearest_ordinals([0, 1], 3))) == 2


def test_rule_5_canary_plants_a_wrong_entry_at_the_chosen_state():
    history = [{"step": 1, "increment": i, "element": 1, "point": 1, "DDSDDE": [1.0, 5.0, 2.0]}
               for i in range(1, 4)]
    planted = D.plant_wrong_tangent_entry(history, {"step": 1, "increment": 2, "element": 1, "point": 1})
    assert planted[1]["DDSDDE"] == [1.0, 5.0 * 1.01, 2.0]
    assert planted[0]["DDSDDE"] == history[0]["DDSDDE"] and planted[2]["DDSDDE"] == history[2]["DDSDDE"]


# ---- rule 2 -------------------------------------------------------------------

BENIGN = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NSTATV)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS)
      DIMENSION A(NSLPTL)
      NSLPTL=NINT(STATEV(NSTATV))
      IF (NSLPTL .GT. 3) STRESS(1)=0.D0
      DO 10 J=1,NSLPTL
         STRESS(1)=STRESS(1)+STATEV(2*NSLPTL+J)
   10 CONTINUE
      RETURN
      END
"""
TRUNC = [{"text": "NSLPTL=REAL(NINT(REAL(STATEV_OTI(NSTATV))))", "target": "NSLPTL", "line": 9}]


def test_rule_2_a_nint_used_only_as_bound_limit_subscript_and_integer_comparison_is_benign():
    out = D.rule_2_static(BENIGN, TRUNC)
    assert out["targets"] == ["NSLPTL"]
    assert out["integer_typed"] == {"NSLPTL": True}
    assert out["static_literal"] is True, out["violations"]


def test_rule_2_canary_a_nint_result_multiplied_into_stress_stays_flagged():
    bad = BENIGN.replace("      RETURN", "      STRESS(1)=STRESS(1)*NSLPTL\n      RETURN")
    out = D.rule_2_static(bad, TRUNC)
    assert out["static_literal"] is False
    assert out["static_admitting_output"] is False
    assert any(v["context"] in ("arithmetic", "real_expression") for v in out["violations"])


def test_rule_2_the_store_back_of_the_integer_is_a_literal_violation_but_admitted_separately():
    stored = BENIGN.replace("      RETURN", "      STATEV(NSTATV)=FLOAT(NSLPTL)\n      RETURN")
    out = D.rule_2_static(stored, TRUNC)
    assert out["static_literal"] is False
    assert out["static_admitting_output"] is True


def test_rule_2_a_real_valued_target_is_not_the_exact_pattern():
    other = [{"text": "I1BAR=REAL(BISO_OTI(1)+BISO_OTI(2))", "target": "I1BAR", "line": 3}]
    out = D.rule_2_static(BENIGN, other)
    assert out["static_literal"] is False and out["pattern_offenders"]


def test_rule_2_passing_the_integer_to_a_real_dummy_is_flagged():
    text = BENIGN.replace("      RETURN", "      CALL SUB1(NSLPTL)\n      RETURN") + """      SUBROUTINE SUB1(X)
      INCLUDE 'ABA_PARAM.INC'
      Z=X*2.D0
      RETURN
      END
"""
    out = D.rule_2_static(text, TRUNC)
    assert out["static_literal"] is False
    assert any(v["context"] == "actual_argument" for v in out["violations"])


def test_rule_2_an_implicit_real_name_is_not_an_integer():
    text = BENIGN.replace("NSLPTL", "ALPHA")
    out = D.rule_2_static(text, [{"text": "ALPHA=REAL(NINT(REAL(STATEV_OTI(NSTATV))))", "target": "ALPHA", "line": 1}])
    assert out["integer_typed"] == {"ALPHA": False}
    assert out["static_literal"] is False


def test_rule_2_amended_admits_console_write_and_the_idempotent_store_but_the_first_variant_does_not():
    src = BENIGN.replace("      RETURN", "      WRITE(6,*) NSLPTL\n      STATEV(NSTATV)=FLOAT(NSLPTL)\n      RETURN")
    assert D.rule_2_static(src, TRUNC)["static_literal"] is False
    assert D.rule_2_amended_static(src, TRUNC)["static_amended"] is True


def test_rule_2_amended_canary_the_same_store_into_a_different_slot_flags():
    src = BENIGN.replace("      RETURN", "      STATEV(NSTATV-1)=FLOAT(NSLPTL)\n      RETURN")
    assert D.rule_2_amended_static(src, TRUNC)["static_amended"] is False


def test_rule_2_amended_canary_nint_times_stress_still_flags():
    src = BENIGN.replace("      RETURN", "      STRESS(1)=STRESS(1)*NSLPTL\n      RETURN")
    assert D.rule_2_amended_static(src, TRUNC)["static_amended"] is False


def test_rule_2_amended_a_non_nint_truncation_is_never_admitted():
    other = [{"text": "I1BAR=REAL(BISO_OTI(1))", "target": "I1BAR", "line": 3}]
    assert D.rule_2_amended_static(BENIGN, other)["static_amended"] is False


# ---- rule 3 -------------------------------------------------------------------

HAND = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NDI)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(*),DDSDDE(NTENS,NTENS),XN(6)
      DIMENSION YN(6)
      DO I=1,NTENS
        XN(I)=STRESS(I)*2.D0
        YN(I)=XN(I)*XN(I)
      END DO
      DO I=1,NTENS
        DDSDDE(I,I)=YN(I)
      END DO
      RETURN
      END
"""


def test_rule_3_a_target_reaching_only_the_hand_ddsdde_reaches_no_sink():
    out = D.rule_3_static(HAND, ["XN"], ["STRESS", "STATEV", "NDI", "NTENS"])
    assert out["reached_sinks"] == [] and out["closure_contains_ddsdde"] is True


def test_rule_3_canary_a_cast_on_a_quantity_that_reaches_stress_flags():
    bad = HAND.replace("      RETURN", "      STRESS(1)=STRESS(1)+YN(1)\n      RETURN")
    out = D.rule_3_static(bad, ["XN"], ["STRESS", "STATEV", "NDI", "NTENS"])
    assert "STRESS" in out["reached_sinks"]


def test_rule_3_canary_a_target_feeding_a_variable_the_replacement_reads_flags():
    bad = HAND.replace("      RETURN", "      NDI=INT(YN(1))\n      RETURN")
    out = D.rule_3_static(bad, ["XN"], ["STRESS", "STATEV", "NDI", "NTENS"])
    assert "NDI" in out["reached_sinks"]


def test_rule_3_flow_through_a_helper_argument_and_a_common_block_is_followed():
    text = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(*),DDSDDE(NTENS,NTENS)
      COMMON /BLK/ W
      CALL HELP(XN,V)
      STATEV(1)=W
      RETURN
      END
      SUBROUTINE HELP(A,B)
      INCLUDE 'ABA_PARAM.INC'
      COMMON /BLK/ C
      C=A
      B=A
      RETURN
      END
"""
    out = D.rule_3_static(text, ["XN"], ["STRESS", "STATEV"])
    assert "STATEV" in out["reached_sinks"]


def test_rule_3_the_control_dependence_of_an_if_is_followed():
    text = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(*),DDSDDE(NTENS,NTENS)
      IF (XN .GT. 1.D0) THEN
         STRESS(1)=0.D0
      END IF
      RETURN
      END
"""
    assert "STRESS" in D.rule_3_static(text, ["XN"], ["STRESS"])["reached_sinks"]


def test_rule_3_mutation_multiplies_only_the_named_assignments_and_wraps_long_lines():
    text, count, where = D.mutate_assignments(HAND, ["XN"])
    assert count == 1
    assert "XN(I) = (STRESS(I)*2.D0)*(1.0D0+1.0D-3)" in text
    assert "YN(I)=XN(I)*XN(I)" in text
    long_rhs = "+".join(["STRESS(1)"] * 30)
    src = f"      SUBROUTINE UMAT(STRESS)\n      XN(1)={long_rhs}\n      END\n"
    wrapped, n, _ = D.mutate_assignments(src, ["XN"])
    assert n == 1 and all(len(line) <= 72 for line in wrapped.splitlines())


def test_rule_3_the_replacement_region_reads_are_the_stress_shadow_and_dimensions():
    transformed = """C     OTIS DDSDDE extraction: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)
      DO OTI_I = 1, NTENS
         DO OTI_J = 1, NTENS
            DDSDDE(OTI_I,OTI_J) =
     1      GETIM(STRESS_OTI(OTI_I),OTI_J)
            IF (OTI_J .LE. NDI) DDSDDE(OTI_I,OTI_J) =
     1      DDSDDE(OTI_I,OTI_J) + REAL(STRESS_OTI(OTI_I))
         END DO
      END DO
"""
    reads = D.replacement_region_reads(transformed)
    assert {"STRESS", "NTENS", "NDI"} <= reads


# ---- relabel rule -------------------------------------------------------------

def test_the_solver_compiles_by_suffix_not_by_content():
    assert D.solver_form(Path("a/b/umat.f")) == "fixed"
    assert D.solver_form(Path("umat.for")) == "fixed"
    assert D.solver_form(Path("umat.f90")) == "free"
    assert D.solver_form(Path("UMAT.F90")) == "free"


def test_the_relabel_rule_text_is_carried_in_the_code():
    text = " ".join(D.relabel_rule_text().split())
    assert "reproduced by compiling the published text alone" in text
    assert "never \"fine\"" in text


# ---- A/B on the stored pass24 evidence ----------------------------------------

PASS24 = D.PASS24 / "results" / "store_verification.jsonl"


@pytest.mark.skipif(not PASS24.exists(), reason="pass24 evidence is machine-local")
def test_ab_the_112_verified_rows_are_byte_identical_under_the_rule_1_code_path():
    records = D.load_records(PASS24)
    out = D.ab_identity_rule_1(records)
    assert out["different"] == []
    assert out["verified_identical"] == out["verified_total"] == 112
