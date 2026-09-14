"""28 of 62 rows in the largest failure cluster said more than their evidence.

``primal_disagreed`` is glossed "the two builds do not compute the same
stress". That is a claim about the ROUTINE, and the recorded calls are what can
support it. Agent D ran ``isolate_first_divergence`` over every one of the 62
disagreements in pass10, against each entry's own probe records:

    34   same_inputs_different_outputs      a genuine claim about the routine
    16   inputs_already_diverged            the ARGUMENTS had already parted
    12   no_divergence_in_paired_calls      every paired call bit-identical

The middle sixteen -- all at call 8, all in one family -- were handed different
arguments before the call whose outputs differ, so what the routine returned
there is not attributable to it. The last twelve returned bit-identical outputs
at every call the probe recorded, and the history comparison reported a
difference anyway; whatever those twelve are, they are not evidence that a
converted routine computes a different stress.

``compare_primal`` scores two converged histories and never asks whether the
two builds were still being handed the same arguments. The code that can tell
these apart was already in the package and the corpus stage was not calling it.
"""
import importlib.util
import pathlib
import sys

import pytest

from umat_oti.abaqus import call_isolation


def _verifier():
    where = pathlib.Path(__file__).resolve().parents[1] / "tools" / "verify_store_in_abaqus.py"
    spec = importlib.util.spec_from_file_location("_vs_history", where)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_vs_history"] = module
    spec.loader.exec_module(module)
    return module


def _reached(**seen):
    vs = _verifier()
    base = dict(material_found=True, original_completed=True,
                transformed_completed=True, primal_agrees=False)
    base.update(seen)
    return vs.classify_stage(vs.StageEvidence(**base))


def test_a_difference_the_routine_really_made_is_still_primal_disagreed():
    assert _reached(
        call_isolation=call_isolation.SAME_INPUTS_DIFFERENT_OUTPUTS
    ) == "primal_disagreed"


def test_arguments_that_parted_first_are_not_the_routines_doing():
    vs = _verifier()
    assert _reached(
        call_isolation=call_isolation.INPUTS_ALREADY_DIVERGED
    ) == vs.ARGUMENTS_DIVERGED


def test_bit_identical_calls_do_not_support_a_disagreement():
    vs = _verifier()
    assert _reached(
        call_isolation=call_isolation.NO_DIVERGENCE
    ) == vs.DISAGREEMENT_NOT_IN_ANY_CALL


def test_no_probe_records_leaves_the_claim_where_it_was():
    """Not established is not the same as refuted. An entry whose probe files
    could not be read keeps the pessimistic reading rather than being promoted
    out of the cluster on the strength of a missing measurement."""
    assert _reached(call_isolation="") == "primal_disagreed"
    assert _reached(call_isolation=call_isolation.NOT_PAIRABLE) == "primal_disagreed"


def test_the_split_only_applies_where_the_histories_actually_disagreed():
    """An entry whose primal comparison AGREED must not be routed anywhere by
    the isolation verdict; it carries on up the ladder."""
    vs = _verifier()
    for verdict in (call_isolation.NO_DIVERGENCE,
                    call_isolation.INPUTS_ALREADY_DIVERGED):
        reached = vs.classify_stage(vs.StageEvidence(
            material_found=True, original_completed=True,
            transformed_completed=True, primal_agrees=True,
            mechanically_informative=True, call_isolation=verdict))
        assert reached not in (vs.ARGUMENTS_DIVERGED,
                               vs.DISAGREEMENT_NOT_IN_ANY_CALL)


def test_both_new_states_are_on_the_ladder_and_neither_is_verified():
    vs = _verifier()
    assert vs.ARGUMENTS_DIVERGED in vs.STAGES
    assert vs.DISAGREEMENT_NOT_IN_ANY_CALL in vs.STAGES
    assert vs.VERIFIED not in (vs.ARGUMENTS_DIVERGED,
                               vs.DISAGREEMENT_NOT_IN_ANY_CALL)


def test_the_two_states_say_whose_problem_they_are():
    """One is about the experiment, one is about this harness, and the
    difference has to be readable or the split is just two more names."""
    vs = _verifier()
    source = pathlib.Path(vs.__file__).read_text()
    block = source[source.index("ARGUMENTS_DIVERGED = "):]
    assert "EXTERNAL" in source[:source.index("ARGUMENTS_DIVERGED = ")][-900:]
    assert "INTERNAL" in block[:block.index("DISAGREEMENT_NOT_IN_ANY_CALL = ") + 400]
