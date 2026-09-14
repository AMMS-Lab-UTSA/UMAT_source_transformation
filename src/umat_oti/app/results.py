"""What the material did, and whether its derivatives are right.

Two screens' worth of view model. Both obey the same rule the rest of this
interface does: a quantity nobody measured is reported as not measured, with
the recorded reason it was not, and never as a blank and never as a zero.

That rule is load-bearing here more than anywhere. The probe this pipeline runs
records material-point output, and dissipated energy is not material-point
output -- it is model-level history. The run says so, in its own words, in
``activation_on_the_frozen_run.not_measured``. An energy panel that drew a
curve from what the probe does have would be drawing a quantity the pipeline
never measured, and it would look exactly like one it had.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from umat_oti.app.corpus_view import (NOT_ESTABLISHED, componentwise_errors,
                                      fd_plateau, field_anywhere, finding,
                                      histories, three_state)

__all__ = ["stress_strain", "state_histories", "markers", "rate_response",
           "energy", "implausibility_warnings", "mechanical_view",
           "evaluation_states", "one_sided", "plateau", "criteria",
           "derivative_view", "COMPARISONS"]


# ---------------------------------------------------------------------------
# mechanical results
# ---------------------------------------------------------------------------
def stress_strain(work_dir: Path, key: str) -> dict:
    """Stress against strain for both builds, as series a plot can draw.

    Both builds or neither claim. A record whose converted history is missing
    gets an ``original`` series and an explicit note that the other side is
    absent -- a single curve on a chart captioned "original versus converted"
    is a picture of an agreement nobody checked.
    """
    series = histories(Path(work_dir), key)
    drawn: dict = {"series": {}, "missing": [], "components": 0}
    for name in ("original", "transformed", "control"):
        block = series.get(name)
        if not block:
            if name != "control":
                drawn["missing"].append(name)
            continue
        stress = block.get("stress") or []
        strain = block.get("strain") or []
        drawn["components"] = max(drawn["components"],
                                  max((len(s) for s in stress), default=0))
        drawn["series"][name] = {
            "increment": block.get("increment") or [],
            "time": block.get("time") or [],
            "stress": stress,
            "strain": strain,
        }
    if drawn["missing"]:
        drawn["note"] = (
            "only " + ", ".join(sorted(set(drawn["series"]))) + " is here; "
            + " and ".join(drawn["missing"]) + " left no history, so these "
            "curves are not a comparison of the two builds")
    drawn["comparable"] = ("original" in drawn["series"]
                           and "transformed" in drawn["series"])
    return drawn


def state_histories(work_dir: Path, key: str) -> dict:
    """Every internal state variable over the run, both builds."""
    series = histories(Path(work_dir), key)
    out: dict = {"series": {}, "count": 0}
    for name in ("original", "transformed"):
        block = series.get(name)
        if not block:
            continue
        states = block.get("state") or []
        out["count"] = max(out["count"], max((len(s) for s in states),
                                             default=0))
        out["series"][name] = {"increment": block.get("increment") or [],
                               "state": states}
    if not out["series"]:
        out["note"] = ("no state history was recorded for this entry, so "
                       "whether any internal variable moved is "
                       + NOT_ESTABLISHED)
    return out


#: What each activation indicator is, in the words of somebody reading a
#: stress-strain curve rather than somebody who wrote the detector.
MARKER_PLAIN = {
    "state_change": "an internal variable started moving -- the material "
                    "began to remember something",
    "departure_from_linearity": "the response stopped being a straight line "
                                "-- yielding, damage or another change of "
                                "behaviour",
    "tangent_change": "the stiffness changed",
    "residual_after_reversal": "stress remained after the loading was taken "
                               "back off -- the material kept something",
}


def markers(row: dict) -> dict:
    """Where the material changed behaviour, and what was NOT looked for.

    The second half is not decoration. The run records three quantities it
    could not measure from probe output at all, and a panel of markers that
    listed only what fired would read as "nothing else happened".
    """
    block = field_anywhere(row, "activation_on_the_frozen_run")
    block = block if isinstance(block, dict) else {}
    fired = []
    for indicator in block.get("indicators") or ():
        if not isinstance(indicator, dict):
            continue
        name = str(indicator.get("name") or "")
        fired.append({
            "marker": MARKER_PLAIN.get(name, name.replace("_", " ")),
            "happened": three_state(indicator.get("fired")),
            "how much": indicator.get("magnitude"),
            "where": str(indicator.get("detail") or ""),
            "internal name": name,
        })
    return {
        "the material did something": three_state(block.get("activated")),
        "over how many increments": block.get("increments"),
        "markers": fired,
        "in one sentence": str(block.get("summary") or ""),
        # Carried verbatim. These are the run's own words about what it could
        # not see, and rewriting them would be this interface making a claim
        # about the probe's reach that the run did not make.
        "what this run could not measure": list(block.get("not_measured")
                                                or ()),
    }


def rate_response(row: dict) -> dict:
    """Whether the material cares how fast it is loaded, as a finding."""
    time_block = ((row.get("discovery") or {}).get("time")
                  if isinstance(row.get("discovery"), dict) else None)
    time_block = time_block if isinstance(time_block, dict) else {}
    if not time_block:
        return finding("the material's response depends on how fast it is "
                       "loaded", None,
                       "no rate probe was run for this entry",
                       about="whether time appears in the material's law")
    row_out = finding(
        "the material's response depends on how fast it is loaded",
        time_block.get("rate_dependent"),
        str(time_block.get("reason") or ""),
        magnitude=time_block.get("rate_difference"),
        about="whether time appears in the material's law")
    row_out["stress relaxed while the strain was held"] = three_state(
        time_block.get("relaxed"))
    row_out["how much it relaxed"] = time_block.get("relaxation")
    row_out["the probe ran"] = three_state(time_block.get("ran"))
    return row_out


def energy(row: dict) -> dict:
    """Energy, and why there is no number here.

    There is deliberately no calculation in this function. Dissipated energy
    is model-level history and this pipeline drives a single material point,
    so the probe does not produce it. The run records that, and this returns
    the run's own sentence rather than integrating a stress-strain curve and
    presenting the result as a measurement -- which would be a number this
    project never measured, rendered identically to ones it did.
    """
    block = field_anywhere(row, "activation_on_the_frozen_run")
    block = block if isinstance(block, dict) else {}
    reasons = [str(r) for r in (block.get("not_measured") or ())
               if "energ" in str(r).lower()]
    return {
        "measured": False,
        "state": NOT_ESTABLISHED,
        "why": (reasons[0] if reasons else
                "this run recorded no energy measurement, and this interface "
                "does not compute one from the stress history: an integral of "
                "a probe output is not the solver's energy and would be shown "
                "beside quantities that are"),
        "what would be needed": "model-level history output from a full "
                                "model, which this single-point probe does "
                                "not produce",
    }


def implausibility_warnings(row: dict) -> list:
    """Checks whose answer means the numbers should not be trusted at face value.

    Every check is returned, passing ones included, because a panel headed
    "warnings" that is empty is ambiguous between "everything was checked and
    was fine" and "nothing was checked".
    """
    block = row.get("response_plausibility")
    block = block if isinstance(block, dict) else {}
    checks = block.get("checks") or ()
    out = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        plausible = check.get("plausible")
        out.append({
            "check": str(check.get("name") or ""),
            "result": three_state(plausible),
            "warn": plausible is False,
            "what was measured": check.get("measured"),
            "what it was measured against": check.get("against"),
            "why": str(check.get("detail") or ""),
        })
    if not out:
        out.append({
            "check": "the response fits the scales this problem supplies",
            "result": NOT_ESTABLISHED, "warn": False,
            "what was measured": None, "what it was measured against": None,
            "why": "no plausibility check was recorded for this entry, so "
                   "whether the stresses and deformations are believable is "
                   + NOT_ESTABLISHED,
        })
    return out


def mechanical_view(row: dict, work_dir: Optional[Path] = None,
                    key: str = "") -> dict:
    """Everything the mechanical results screen shows, in one shape."""
    key = key or str(row.get("key") or "")
    view: dict = {
        "markers": markers(row),
        "rate": rate_response(row),
        "energy": energy(row),
        "plausibility": implausibility_warnings(row),
        "evaluation states": evaluation_states(row),
    }
    if work_dir is not None and key:
        view["stress and strain"] = stress_strain(Path(work_dir), key)
        view["state variables"] = state_histories(Path(work_dir), key)
    else:
        view["stress and strain"] = {
            "series": {}, "comparable": False,
            "note": "no run directory was given, so no history was read"}
        view["state variables"] = {"series": {}, "count": 0}
    view["any warning"] = any(c["warn"] for c in view["plausibility"])
    return view


# ---------------------------------------------------------------------------
# derivative results
# ---------------------------------------------------------------------------
#: The three things the converted build's derivatives can be measured against,
#: and what each one settles. All three are shown, because the third is what
#: tells the first two apart from a numerical accident: if the reference's own
#: difference cannot reproduce itself to better than the disagreement, the
#: disagreement is the method's, not the conversion's.
COMPARISONS = (
    ("comparison",
     "the converted build's derivatives against a numerical difference of "
     "the ORIGINAL -- this is the one the verdict rests on"),
    ("against_the_authors_tangent",
     "the author's own stiffness against the same numerical difference -- "
     "what the published source itself achieves"),
    ("the_references_own_error",
     "the numerical difference against itself -- how well the method can do "
     "at all here, which is the floor under the other two"),
)


def evaluation_states(row: dict) -> list:
    """Which points on the path the derivatives were checked at, and why those.

    A derivative verified at one point is a derivative verified at one point.
    The run chooses several and records what kind of point each is -- smooth,
    or on a transition where two different derivatives meet -- and that
    distinction decides what a disagreement means.
    """
    tangent = row.get("tangent")
    tangent = tangent if isinstance(tangent, dict) else {}
    out = []
    for index, state in enumerate(tangent.get("states") or ()):
        if not isinstance(state, dict):
            continue
        regime = state.get("regime") if isinstance(state.get("regime"),
                                                   dict) else {}
        kind = str(regime.get("regime") or "")
        out.append({
            "index": index,
            "increment": state.get("increment"),
            "kind of point": ("a transition, where the material changes "
                              "behaviour" if "transition" in kind
                              or "kink" in kind
                              else "smooth" if kind else NOT_ESTABLISHED),
            "internal name for it": kind,
            "the material had activated here": three_state(
                regime.get("activated_here")),
            "unloading": three_state(regime.get("unloading")),
            "a derivative can be checked here": three_state(
                regime.get("verifiable")),
            "derivatives matched here": three_state(state.get("verified")),
            "why": str(state.get("reason") or regime.get("reason") or ""),
            "step this point used": regime.get("selected_step"),
            "driven through": str(state.get("driven_through") or ""),
        })
    if not out:
        return [{"index": None, "increment": None,
                 "kind of point": NOT_ESTABLISHED, "internal name for it": "",
                 "the material had activated here": NOT_ESTABLISHED,
                 "unloading": NOT_ESTABLISHED,
                 "a derivative can be checked here": NOT_ESTABLISHED,
                 "derivatives matched here": NOT_ESTABLISHED,
                 "why": "no derivative check was recorded for this entry",
                 "step this point used": None, "driven through": ""}]
    return out


def one_sided(row: dict, state: int = 0) -> dict:
    """The centred difference with the two one-sided ones beside it.

    A centred difference averages the two sides, so at a point where the
    material changes behaviour it averages two different derivatives and
    returns something that is neither. The forward and backward differences
    are what expose that: where they agree, the centred one means what it
    says; where they do not, the point is a transition and the gap between
    them is the size of the change.
    """
    tangent = row.get("tangent")
    tangent = tangent if isinstance(tangent, dict) else {}
    states = tangent.get("states") or []
    if not 0 <= state < len(states):
        return {"available": False,
                "why": f"this entry has no derivative check at state {state}"}
    block = states[state] if isinstance(states[state], dict) else {}
    branch = block.get("branch") if isinstance(block.get("branch"),
                                               dict) else {}
    centred = block.get("comparison") if isinstance(block.get("comparison"),
                                                    dict) else {}
    sides = {}
    for name in ("forward", "backward"):
        side = branch.get(name)
        side = (side.get("comparison") if isinstance(side, dict)
                and isinstance(side.get("comparison"), dict) else side)
        if isinstance(side, dict):
            sides[name] = {"best step": side.get("best_step"),
                           "best relative": side.get("best_relative"),
                           "resolved relative": side.get("resolved_relative"),
                           "stable range": list(side.get("stable_range")
                                                or ())}
    if not branch:
        return {
            "available": False,
            "centred": {"best step": centred.get("best_step"),
                        "best relative": centred.get("best_relative")},
            "why": ("only the centred difference was recorded at this point; "
                    "the one-sided differences are taken where the run needs "
                    "to tell a smooth point from a transition, and this point "
                    "did not need it"),
        }
    return {"available": True,
            "centred": {"best step": centred.get("best_step"),
                        "best relative": centred.get("best_relative"),
                        "resolved relative": centred.get("resolved_relative")},
            "one sided": sides,
            "why it matters": one_sided.__doc__.strip().splitlines()[0]}


def plateau(entry: Any, state: int = 0, *,
            against: str = "comparison") -> dict:
    """The step-size sweep at one point, with the accepted range marked.

    Returned as the sweep plus the range rather than as a single number,
    because one step size cannot separate a truncation error from a
    cancellation one: both shrink the error and then grow it, and a number
    taken anywhere on that curve looks the same as a number taken where two
    different derivatives happen to cross.
    """
    rows = fd_plateau(entry, state, against=against)
    tangent = getattr(entry, "tangent", None) or {}
    states = tangent.get("states") or []
    block = states[state] if 0 <= state < len(states) else {}
    comparison = (block.get(against) or {}) if isinstance(block, dict) else {}
    inside = [r for r in rows if r["on the plateau"]]
    return {
        "sweep": rows,
        "accepted range": list(comparison.get("stable_range") or ()),
        "best step": comparison.get("best_step"),
        "steps on the plateau": len(inside),
        "what the sweep is against": dict(COMPARISONS).get(against, against),
        "settled": bool(inside),
        "why": ("the error stops moving over "
                f"{len(inside)} step sizes, which is what makes it the "
                "derivative rather than a crossing point"
                if inside else
                "no run of step sizes was found over which the error stops "
                "moving, so this sweep does not pin the derivative down"),
    }


def criteria(row: dict) -> list:
    """The pass/fail rules the derivative verdict is made of, each measured."""
    tangent = row.get("tangent")
    tangent = tangent if isinstance(tangent, dict) else {}
    evidence = row.get("evidence") or {}
    checked = tangent.get("states_checked")
    agreeing = tangent.get("states_agreeing")
    measured = tangent.get("states_measured")
    return [
        finding("the derivatives matched at every point that could be checked",
                tangent.get("verified") if "verified" in tangent
                else evidence.get("derivatives_verified"),
                str(tangent.get("reason") or ""),
                magnitude=(f"{agreeing} of {checked}"
                           if checked is not None else None),
                about="the verdict this screen reports"),
        finding("there was at least one point where a derivative can be "
                "checked at all",
                None if measured is None else bool(measured),
                f"{measured} of {checked} chosen points could be measured"
                if measured is not None else
                "how many points could be measured was not recorded",
                about="a material that is activated from its first increment "
                      "has no elastic branch to check against"),
        finding("the agreement holds over a range of step sizes rather than "
                "at one",
                None if not tangent.get("states") else
                any(bool((s or {}).get(name, {}).get("stable_range"))
                    for s in tangent.get("states") or ()
                    for name in ("comparison",)),
                "a single step size cannot tell a converged difference from "
                "two tangents crossing",
                about="why a plateau is required"),
        finding("smooth points and transition points were told apart",
                None if not tangent.get("states") else
                any(isinstance((s or {}).get("regime"), dict)
                    for s in tangent.get("states") or ()),
                f"{tangent.get('states_smooth')} smooth and "
                f"{tangent.get('states_transitional')} transitional"
                if tangent.get("states_smooth") is not None else
                "the run recorded no split between smooth and transition "
                "points",
                about="a centred difference at a transition averages two "
                      "different derivatives and returns neither"),
    ]


def derivative_view(entry: Any, state: int = 0) -> dict:
    """Everything the derivative results screen shows, in one shape."""
    row = getattr(entry, "raw", None)
    if not isinstance(row, dict):
        row = {"tangent": getattr(entry, "tangent", None) or {},
               "evidence": {}}
    return {
        "evaluation states": evaluation_states(row),
        "one sided": one_sided(row, state),
        "criteria": criteria(row),
        "plateaus": {name: plateau(entry, state, against=name)
                     for name, _what in COMPARISONS},
        "componentwise": componentwise_errors(entry, state),
        "what each comparison settles": dict(COMPARISONS),
    }
