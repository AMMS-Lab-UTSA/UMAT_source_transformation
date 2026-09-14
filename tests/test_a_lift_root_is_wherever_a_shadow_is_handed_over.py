"""A callee that receives a shadow must be lifted, wherever the call sits.

``_liftable_helper_roots`` read one list: ``stress_path_helpers``, the calls
inside the DETECTED stress-update interval. The emitter does not rewrite
arguments by interval -- it rewrites a promoted name wherever it appears in the
selected routine -- so a call below the interval was handed a shadow and its
callee was never offered to the lifter.

abuganza/BayesianCalibrationSkinGrowth/GOH_Example.f is the clean case, and it
takes three hops to see:

    call move6to33(fginv, fginvmat)     <- MOVE6TO33 is rooted from the interval
    ...
    call doubledot(fginvmat, dFgdtheg, const1)   <- twenty lines below it
    call doubledot42(ddsedde, tmp3, const2)
    call move6to33(const2, const2mat)

MOVE6TO33 is lifted, so its second dummy is typed ONUMM6N1 and FGINVMAT comes
back a shadow -- although the role classifier calls it neither seed nor
promoted. DOUBLEDOT then receives a shadow; DOUBLEDOT42's output CONST2 reaches
MOVE6TO33, which is lifted at every call site, so CONST2 is a shadow too.
Fortran's implicit interface let every one of those calls compile while the
callee read the first of seven doubles as the whole number.

So the roots are found the same way the shadows spread: to a fixed point, and
restricted to callees THIS FILE DEFINES, because a root with no body is not a
root and an external callee's leak is a true external blocker that the leak
check already states in full.

Widening can add reach and must not take any away: when the widened closure
reaches something nothing can lift -- KUMATCHECKS calls Abaqus's own
STDB_ABQERR in victorlefevre/UMAT_KLP_RK5_hybrid.f -- the narrow root set is
tried instead, so a source that transformed before still transforms.

Measured over all 391 triage rows: 5 sources moved from refused to
transformed, all 5 compile, none moved the other way, and one output changed
bytes (a shadow declared for a name a newly-lifted helper now types OTI).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _liftable_helper_roots, _names_defined_in_this_file,
    _selected_routine_span_from_analysis)

pytestmark = pytest.mark.unit


def _config(calls, defined, span=(1, 500), helpers=()):
    return {
        "analysis": {
            "calls": list(calls),
            "stress_path_helpers": list(helpers),
            "detected_subroutines": (
                [{"name": "UMAT", "line_numbers": [span[0], span[1]], "arguments": []}]
                + [{"name": name, "line_numbers": [span[1] + 10, span[1] + 20],
                    "arguments": []} for name in defined]
            ),
            "detected_functions": [],
        },
        "variable_roles": {},
    }


ROLES = {"seed": {"DSTRAN"}, "promote": {"FGINV"}, "constant": set(), "keep_real": set()}
STRESS = [{"start_line": 100, "end_line": 120}]


def test_a_call_below_the_stress_interval_is_still_a_root():
    calls = [
        {"callee": "MOVE6TO33", "arguments": ["fginv", "fginvmat"], "line_numbers": [110]},
        {"callee": "DOUBLEDOT", "arguments": ["fginvmat", "dfgdtheg", "const1"],
         "line_numbers": [300]},
    ]
    roots = _liftable_helper_roots(
        _config(calls, ["MOVE6TO33", "DOUBLEDOT"]), ROLES, STRESS, "UMAT")
    assert "MOVE6TO33" in roots and "DOUBLEDOT" in roots


def test_the_walk_reaches_a_callee_three_hops_out():
    calls = [
        {"callee": "MOVE6TO33", "arguments": ["fginv", "fginvmat"], "line_numbers": [110]},
        {"callee": "DOUBLEDOT", "arguments": ["fginvmat", "dfgdtheg", "const1"],
         "line_numbers": [300]},
        {"callee": "DOUBLEDOT42", "arguments": ["ddsedde", "tmp3", "const2"],
         "line_numbers": [301]},
        {"callee": "MOVE6TO33", "arguments": ["const2", "const2mat"], "line_numbers": [302]},
    ]
    roots = _liftable_helper_roots(
        _config(calls, ["MOVE6TO33", "DOUBLEDOT", "DOUBLEDOT42"]), ROLES, STRESS, "UMAT")
    assert "DOUBLEDOT42" in roots, roots


def test_an_external_callee_is_never_made_a_root():
    """Its leak is a true external blocker, and the warning says so in full."""
    calls = [{"callee": "STDB_ABQERR", "arguments": ["fginv", "msg"], "line_numbers": [111]}]
    roots = _liftable_helper_roots(_config(calls, []), ROLES, STRESS, "UMAT")
    assert "STDB_ABQERR" not in roots


def test_a_call_outside_the_selected_routine_is_not_a_root():
    calls = [{"callee": "HELPER", "arguments": ["fginv"], "line_numbers": [900]}]
    roots = _liftable_helper_roots(
        _config(calls, ["HELPER"], span=(1, 500)), ROLES, STRESS, "UMAT")
    assert roots == ()


def test_the_narrow_rule_is_recoverable():
    """``widen=False`` reproduces the old root set exactly, for the fallback."""
    calls = [{"callee": "DOUBLEDOT", "arguments": ["fginv", "x", "y"], "line_numbers": [300]}]
    config = _config(calls, ["DOUBLEDOT"])
    assert _liftable_helper_roots(config, ROLES, STRESS, "UMAT", None, widen=False) == ()
    assert _liftable_helper_roots(config, ROLES, STRESS, "UMAT") == ("DOUBLEDOT",)


def test_the_span_and_definition_helpers_read_the_analysis():
    config = _config([], ["HELPER"], span=(7, 99))
    analysis = config["analysis"]
    assert _selected_routine_span_from_analysis(analysis, "UMAT") == (7, 99)
    assert {"UMAT", "HELPER"} <= _names_defined_in_this_file(analysis)
