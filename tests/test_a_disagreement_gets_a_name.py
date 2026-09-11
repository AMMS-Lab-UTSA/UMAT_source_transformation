""""primal_disagreed" is a stage, not a diagnosis.

Thirty-seven entries reached it at magnitudes spanning nine orders -- 2.3e-10
to 1.9 -- and a single name over that range tells nobody which of them share
a cause or which fix would move any of them. The signature is read off the
comparison and the source, so the cluster can be worked as clusters.

Nothing here relaxes a tolerance. A signature is a hypothesis with its
evidence attached.
"""
from umat_oti.abaqus.primal_signature import (ACCUMULATING, DATA_OR_LIFETIME,
                                              FIRST_INCREMENT,
                                              ITERATIVE_SOLVER, NEAR_ZERO,
                                              NON_FINITE, ROUND_OFF,
                                              ROUND_OFF_SCALE, SIGN_FLIP,
                                              SIGN_FLIP_CLOSENESS, classify)

NEWTON = ("      SUBROUTINE UMAT(STRESS,STATEV)\n"
          "C     Newton-Raphson iteration to solve stresses\n"
          "      DO WHILE (RESID .GT. TOLER)\n      END DO\n      END\n")
PLAIN = "      SUBROUTINE UMAT(STRESS,STATEV)\n      RETURN\n      END\n"
READS = ("      SUBROUTINE UMAT(STRESS,STATEV)\n"
         "      SAVE TABLE\n      OPEN(301,FILE='t.csv')\n"
         "      READ(301,*) TABLE\n      END\n")


def test_opposite_signs_of_near_equal_size_are_two_answers_not_one():
    """Measured on huang_umat_97.for: stress 17.5883 against -20.0786 and
    state -3.38e-05 against 3.43e-05. A number computed two ways does not
    change sign; something chose a different branch."""
    signature = classify(
        {"worst_stress_relative": 1.876, "worst_state_relative": 1.986,
         "worst_stress_at": [137, 3, 17.5883, -20.0786],
         "worst_state_at": [50, 23, -3.3817e-05, 3.4295e-05]}, NEWTON, 140)
    assert signature.kind == ITERATIVE_SOLVER
    assert "opposite signs" in signature.evidence[0]
    assert "Newton iteration" in signature.evidence[-1]


def test_a_sign_flip_without_an_iteration_is_still_a_branch_divergence():
    signature = classify(
        {"worst_stress_relative": 1.8,
         "worst_stress_at": [50, 1, 10.0, -11.0]}, PLAIN, 100)
    assert signature.kind == SIGN_FLIP


def test_two_magnitudes_far_apart_are_not_a_sign_flip():
    signature = classify(
        {"worst_stress_relative": 1.0,
         "worst_stress_at": [50, 1, 10.0, -1000.0]}, PLAIN, 100)
    assert signature.kind != SIGN_FLIP
    assert 0.0 < SIGN_FLIP_CLOSENESS < 1.0


def test_a_difference_at_the_first_record_is_not_an_accumulation():
    signature = classify(
        {"worst_stress_relative": 1.0,
         "worst_stress_at": [1, 1, 5.0, 7.0]}, PLAIN, 100)
    assert signature.kind == FIRST_INCREMENT
    assert "before any history has accumulated" in signature.evidence[0]


def test_a_difference_part_way_along_grows_with_the_path():
    signature = classify(
        {"worst_stress_relative": 5.9e-05, "worst_state_relative": 1e-06,
         "worst_stress_at": [83, 1, 1372.13, 1372.05]}, PLAIN, 280)
    assert signature.kind == ACCUMULATING


def test_a_source_that_reads_and_saves_is_named_for_it():
    signature = classify(
        {"worst_stress_relative": 4.2e-08,
         "worst_stress_at": [40, 1, 1.0, 1.0000001]}, READS, 100)
    assert signature.kind == DATA_OR_LIFETIME
    assert "keeps what it read between calls" in signature.evidence[0]


def test_mostly_unresolvable_components_are_a_normalisation_artefact():
    signature = classify(
        {"worst_stress_relative": 1e-05, "worst_stress_at": [20, 1, 1.0, 1.1],
         "resolved_components": 10, "unresolved_components": 500}, PLAIN, 50)
    assert signature.kind == NEAR_ZERO
    assert "carries rounding rather than signal" in signature.evidence[0]


def test_a_round_off_scale_difference_says_so():
    signature = classify(
        {"worst_stress_relative": 2.336e-10,
         "worst_stress_at": [105, 1, -1.77e12, -1.77e12]}, PLAIN, 280)
    assert signature.kind == ROUND_OFF_SCALE
    assert signature.magnitude <= ROUND_OFF


def test_a_comparison_against_nan_establishes_nothing():
    signature = classify(
        {"worst_stress_relative": 0.0, "non_finite_components": 2520}, PLAIN, 0)
    assert signature.kind == NON_FINITE
    assert "nothing about this pair is established" in signature.evidence[0]


def test_the_signature_is_recorded_beside_the_comparison():
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    assert 'record["primal_signature"] = primal_signature.classify(' in text


def test_a_signature_never_changes_a_verdict():
    """It is a hypothesis with evidence, not a tolerance."""
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    block = text[text.index('record["primal_signature"]'):]
    block = block[:block.index('seen["primal_agrees"]')]
    assert "agrees" not in block and "tolerance" not in block
