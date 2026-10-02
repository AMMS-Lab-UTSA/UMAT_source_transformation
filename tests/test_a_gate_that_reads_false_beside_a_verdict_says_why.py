"""``primal_agreed: false`` next to ``stage: verified`` is not a contradiction.

Thirteen entries in pass11 are in exactly that shape, and the record carried
the explanation only inside a prose reason string:

    the two builds differ by 3.127e-08, and this model differs from ITSELF by
    5.805e-03 when the same source is compiled so that the same mathematics is
    computed differently (reassociation)

That is a measured control and not a loosened tolerance -- the raw comparison
flag never moves, and ``run_association_control`` is a real pair of Abaqus runs
whose result is written into the record. But a reader looking at the six gates
saw a false one beside a verdict and had no flag saying which of those two
readings was right.

So the chain is a flag of its own. ``primal_agreed`` stays false, because the
two builds did not agree to tolerance; ``primal_difference_explained_by_a_
measured_control`` says whether anything was measured about it and what came
back. None means no control was needed, which is every entry whose builds
agreed in the first place.
"""
import importlib.util
import pathlib
import sys

FLAG = "primal_difference_explained_by_a_measured_control"


def _verifier():
    where = pathlib.Path(__file__).resolve().parents[1] / "tools" / "verify_store_in_abaqus.py"
    spec = importlib.util.spec_from_file_location("_vs_gate", where)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_vs_gate"] = module
    spec.loader.exec_module(module)
    return module

# Retired 2026-10-01 (corpus campaign B2c): test_the_flag_is_written_beside_the_six_and_starts_unmeasured, test_it_is_set_true_only_where_a_control_actually_explained_it, test_a_control_that_ran_and_did_not_explain_it_says_false_not_nothing, test_the_raw_comparison_flag_is_never_rewritten, test_an_explanation_never_rewrites_the_primal_gate asserted on the source TEXT
# of the pre-B2c primal gate (the FE comparison as the gate, and the
# association control, which no longer runs). The invariants they protected are
# now tested behaviourally in tests/test_primal_gate_explanation_never_rewrites_it.py
# and tests/test_primal_gate_routine_level.py.
