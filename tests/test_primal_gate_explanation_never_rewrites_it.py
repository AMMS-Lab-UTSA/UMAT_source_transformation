"""B2c replacement for the invariants pinned by
test_a_gate_that_reads_false_beside_a_verdict_says_why.py and
test_an_unmeasured_zero_is_not_a_measurement.py, which name the pre-B2c code
(the FE comparison as the gate, the association control as an explanation).

The invariant itself is unchanged: an explanation is never agreement. Since
B2c the gate is decided by the routine-level comparison and the Jacobian-
matched control; the declared-precision control may route a row to
primal_mismatch_explained, and only after BOTH of its halves agreed."""
import pathlib

SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "tools" /
          "verify_store_in_abaqus.py").read_text()


def test_nothing_ever_sets_the_gate_true_by_hand():
    assert 'seen["primal_agrees"] = True' not in SOURCE
    assert '"primal_agreed"] = True' not in SOURCE


def test_the_gate_is_written_only_from_the_two_comparisons_that_see_the_routine():
    assert SOURCE.count('seen["primal_agrees"] = gate') == 1
    assert SOURCE.count('record["evidence"]["primal_agreed"] = gate') == 1
    block = SOURCE[SOURCE.index("    gate = bool("):]
    block = block[:block.index("decided_by")]
    assert 'init_check.get("established")' in block
    assert 'routine.get("agrees")' in block
    assert 'jacobian.get("agrees")' in block


def test_an_explanation_needs_both_halves_of_the_precision_control():
    assert SOURCE.count('seen["primal_explained"] = True') == 1
    before = SOURCE[:SOURCE.index('seen["primal_explained"] = True')]
    tail = before[before.rindex('if control.get("agrees"):'):]
    assert 'control["jacobian_matched"].get("agrees")' in tail


def test_the_explanation_flag_starts_unmeasured_and_is_set_false_when_refuted():
    assert '"primal_difference_explained_by_a_measured_control": None,' in SOURCE
    assert ('record["evidence"]["primal_difference_explained_by_a_measured_control"] = False'
            in SOURCE)


def test_the_fe_comparison_is_kept_and_labelled_informational():
    assert 'record["primal"]["informational_only"] = True' in SOURCE
