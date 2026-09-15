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


def test_the_flag_is_written_beside_the_six_and_starts_unmeasured():
    """It is built as None, so an entry that never needed a control does not
    claim one ran."""
    vs = _verifier()
    source = pathlib.Path(vs.__file__).read_text()
    block = source[source.index('"primal_agreed": bool(primal.agrees),'):]
    block = block[:block.index("}")]
    assert f'"{FLAG}": None,' in block


def test_it_is_set_true_only_where_a_control_actually_explained_it():
    """Both explanations -- a declared single-precision variable, and the
    model's own sensitivity to reordering -- and nothing else."""
    vs = _verifier()
    source = pathlib.Path(vs.__file__).read_text()
    setters = source.count(f'"{FLAG}"] = True')
    assert setters == 2, setters
    for neighbour in ('record["primal"]["explained_by_declared_precision"] = True',
                      'record["primal"]["explained_by_operation_order"] = True'):
        after = source[source.index(neighbour):]
        assert FLAG in after[:400], neighbour


def test_a_control_that_ran_and_did_not_explain_it_says_false_not_nothing():
    """Not-measured and measured-and-refuted are different answers, and
    leaving the second as None would report a control that ran as one that
    never happened."""
    vs = _verifier()
    source = pathlib.Path(vs.__file__).read_text()
    after = source[source.index('record["association_control"] = association'):]
    assert f'"{FLAG}"] = False' in after[:400]


def test_the_raw_comparison_flag_is_never_rewritten():
    """The gate that says whether the two builds agreed must keep saying it.
    An explanation is a second fact, never an edit to the first."""
    vs = _verifier()
    source = pathlib.Path(vs.__file__).read_text()
    assert source.count('"primal_agreed": bool(primal.agrees),') == 1
    assert '"primal_agreed"] = True' not in source
    assert 'evidence"]["primal_agreed"]' not in source


def test_an_explanation_never_rewrites_the_primal_gate():
    """A measured explanation for a disagreement is not agreement.

    The harness used to set ``seen["primal_agrees"] = True`` once a control had
    measured why the two builds differ, and thirteen entries carrying a false
    primal gate were counted verified, frozen into the baseline and offered to
    the Residual Assembler. The explanation is still recorded -- it says where
    to look -- but it routes to the internal rung primal_mismatch_explained and
    never touches the gate.
    """
    vs = _verifier()
    source = pathlib.Path(vs.__file__).read_text()
    assert 'seen["primal_agrees"] = True' not in source
    assert source.count('seen["primal_explained"] = True') == 2
    guard = source[source.index("own = association.get("):]
    guard = guard[:guard.index('seen["primal_explained"] = True')]
    assert 'association.get("ran")' in guard
    assert 'association.get("measured")' in guard
    assert "mine <= own" in guard
    assert "tolerance" not in guard
    evidence = vs.StageEvidence(
        material_found=True, original_completed=True, transformed_completed=True,
        primal_agrees=False, primal_explained=True,
        mechanically_informative=True, tangent_verified=True)
    assert vs.classify_stage(evidence) == vs.PRIMAL_MISMATCH_EXPLAINED
    assert vs.classify_stage(evidence) != vs.VERIFIED

