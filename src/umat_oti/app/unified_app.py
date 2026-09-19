"""The one interface: eight areas, one vocabulary, nothing decided here.

Thin on purpose, in the same way :mod:`umat_oti.app.corpus_tab` is thin. Every
number, verdict and status on these screens comes from a view module that a
test can call without a browser --- :mod:`umat_oti.app.home`,
:mod:`umat_oti.app.library`, :mod:`umat_oti.app.results`,
:mod:`umat_oti.app.residual_bridge`, :mod:`umat_oti.app.jobs` and
:mod:`umat_oti.app.plain_language`. Nothing in this file computes a verdict,
formats a status word, assembles a command line or decides whether something
may be called verified.

Two structural rules it exists to hold.

**Plain by default, expert on request.** Everything outside an "Advanced" or
"Evidence" expander is written for somebody who has never seen an Abaqus
keyword. The pipeline's own vocabulary lives inside those expanders.
:func:`default_text` returns exactly the text the default screens show, so a
test can assert the absence of that vocabulary rather than a reviewer having
to notice it.

**Import-safe without Streamlit.** The module imports and every view function
runs headless, so the suite that checks these screens does not drag a UI
dependency into a run that has no display.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from umat_oti.app import home as home_module
from umat_oti.app import jobs as jobs_module
from umat_oti.app import library as library_module
from umat_oti.app import plain_language, residual_bridge, results
from umat_oti.app.corpus_view import NOT_ESTABLISHED, load_run
from umat_oti.app.plain_language import (EXPERT_TERMS, failure_for,
                                         may_say_verified, plain_sentence,
                                         plain_status, verified_summary)

__all__ = ["AREAS", "area_view", "default_text", "render", "main"]


#: The eight areas, in the order a first-time user meets them. ``key`` is what
#: the navigation stores; ``leads_to`` is the area a completed step hands on
#: to, which is what makes this a workflow rather than eight tabs.
AREAS: tuple[dict, ...] = (
    {"key": "home", "label": "Home",
     "what it is for": "what is here, what works on this machine, and what to "
                       "do next",
     "leads_to": "library"},
    {"key": "library", "label": "Materials",
     "what it is for": "everything that has been brought in, and what state "
                       "each one is in",
     "leads_to": "analyze"},
    {"key": "analyze", "label": "Check and prepare",
     "what it is for": "what this program worked out about a material, and "
                       "the few things only you can answer",
     "leads_to": "verify"},
    {"key": "verify", "label": "Transform and verify",
     "what it is for": "one button, and what it is doing while it runs",
     "leads_to": "mechanical"},
    {"key": "mechanical", "label": "What the material does",
     "what it is for": "stresses, strains, internal variables and where the "
                       "behaviour changed",
     "leads_to": "derivative"},
    {"key": "derivative", "label": "Derivatives",
     "what it is for": "whether the converted material's derivatives are "
                       "right, and how that was established",
     "leads_to": "residual"},
    {"key": "residual", "label": "Use it in a problem",
     "what it is for": "put a verified material into a residual problem and "
                       "check the result",
     "leads_to": "reports"},
    {"key": "reports", "label": "Reports and regression",
     "what it is for": "export what was found, and re-run it later to check "
                       "nothing moved",
     "leads_to": ""},
)

_AREA_KEYS = tuple(a["key"] for a in AREAS)


# ---------------------------------------------------------------------------
# the view behind each area, headless
# ---------------------------------------------------------------------------
def area_view(key: str, *, results_dir: Optional[Path] = None,
              work_dir: Optional[Path] = None,
              selected: str = "", run=None,
              probe: Optional[Callable[..., dict]] = None,
              include_abaqus: bool = True,
              manager: Optional[jobs_module.JobManager] = None,
              tracked: Optional[jobs_module.TrackedJobs] = None) -> dict:
    """Everything one area needs, as data. No widgets, no side effects.

    This is what the tests drive. A screen that cannot be produced without a
    browser is a screen nobody checks, and every rule this interface is held
    to is a rule about what appears on one.
    """
    if key not in _AREA_KEYS:
        raise ValueError(f"{key!r} is not an area; known: "
                         + ", ".join(_AREA_KEYS))
    if run is None and results_dir is not None:
        run = load_run(Path(results_dir),
                       Path(work_dir) if work_dir else None)
    entries = list(getattr(run, "entries", ()) or ())
    entry = None
    if selected:
        entry = next((e for e in entries if e.source_id == selected), None)

    if key == "home":
        return {"area": key,
                "home": home_module.home_view(results_dir, work_dir,
                                              probe=probe,
                                              include_abaqus=include_abaqus,
                                              run=run)}

    if key == "library":
        rows = library_module.rows(entries)
        return {"area": key, "rows": rows,
                "filters": library_module.FILTERS,
                "counts": library_module.counts_by_filter(rows)}

    if key == "analyze":
        return {"area": key, "entry": entry,
                "prepare": _prepare(entry)}

    if key == "verify":
        return {"area": key, "entry": entry,
                "button": _verify_button(entry, results_dir, work_dir,
                                         probe=probe,
                                         include_abaqus=include_abaqus,
                                         run=run),
                "jobs": (tracked.recover(manager)
                         if tracked is not None and manager is not None
                         else [])}

    if key == "mechanical":
        if entry is None:
            return {"area": key, "entry": None,
                    "note": "pick a material first"}
        return {"area": key, "entry": entry,
                "mechanical": results.mechanical_view(
                    entry.raw, Path(work_dir) if work_dir else None,
                    entry.key)}

    if key == "derivative":
        if entry is None:
            return {"area": key, "entry": None,
                    "note": "pick a material first"}
        return {"area": key, "entry": entry,
                "derivative": results.derivative_view(entry)}

    if key == "residual":
        return {"area": key, "offer": residual_bridge.offer(entries),
                "residual assembler":
                    home_module.residual_assembler_status()}

    # reports
    verified = [e for e in entries if may_say_verified(e)]
    return {"area": key,
            "verified": verified,
            "counts": {"materials here": len(entries),
                       "verified": len(verified),
                       "reached the last stage":
                           sum(1 for e in entries if e.stage == "verified")},
            "regression": _regression(entries)}


def _prepare(entry) -> dict:
    """What was worked out, where from, and the few questions left for a user.

    "Targeted questions only" is the requirement, and it is met by asking
    about requirements the run recorded as unmet -- never by presenting the
    inferred settings as a form. A user who is shown twenty correct fields in
    order to fix one has been asked twenty questions.
    """
    if entry is None:
        return {"questions": [], "found": [], "note": "pick a material first"}
    found, questions, ours = [], [], []
    for requirement in getattr(entry, "requirements", ()) or ():
        record = (requirement.as_dict()
                  if hasattr(requirement, "as_dict") else dict(requirement))
        name = str(record.get("name") or "")
        # The pipeline's own sentence is kept verbatim under "as recorded" and
        # never shown on the default screen. It is the citable evidence and it
        # is written in the pipeline's vocabulary; putting it in front of a
        # first-time user as the question is what this split exists to stop.
        record["as recorded"] = record.get("detail", "")
        if record.get("satisfied"):
            record["detail"] = plain_sentence(record.get("detail", ""))
            found.append(record)
            continue
        question = plain_language.question_for(name)
        if question is None:
            # Unmet, and not the user's to answer. Shown, under its own
            # heading, so the screen does not imply everything outstanding is
            # waiting on them.
            ours.append({"what": name,
                         "as recorded": record["as recorded"]})
            continue
        record["ask"] = question["ask"]
        record["what to supply"] = question.get("supply", "")
        record["undecided"] = bool(question.get("undecided"))
        record["detail"] = question["ask"]
        questions.append(record)

    manifest = getattr(entry, "manifest", None) or {}
    where_from = []
    for label, key in (("the material constants", "material_provenance"),
                       ("whether deformations are large or small",
                        "kinematics_provenance"),
                       ("the kind of element this is for", "formulation")):
        value = manifest.get(key) or (entry.raw or {}).get(key)
        if isinstance(value, dict):
            value = value.get("provenance") or value.get("agreement")
        if value:
            where_from.append({"what": label,
                               "where it came from": str(value)})
    status = plain_status(entry)
    return {
        "questions": questions,
        "waiting on this program": ours,
        "found": found,
        "where each thing came from": where_from,
        "status": status.as_dict(),
        "nothing to ask": not questions,
    }


def _verify_button(entry, results_dir, work_dir, *, probe, include_abaqus,
                   run) -> dict:
    """The single button, and whether it can be pressed.

    Never disabled without a sentence saying why, and never enabled on an
    assumption: a capability this program could not establish is not a
    capability it will start a run on.
    """
    capabilities = home_module.availability(probe=probe,
                                            include_abaqus=include_abaqus)
    blocked, unknown = [], []
    for name in ("Abaqus", "Fortran compiler"):
        capability = capabilities.get(name)
        if capability is None or capability.usable is None:
            unknown.append(name)
        elif not capability.usable:
            blocked.append(f"{name} is not available"
                           + (f" ({capability.detail})" if capability.detail
                              else ""))
    if entry is None:
        return {"label": "Transform and verify", "enabled": False,
                "why not": "Pick a material first."}
    if blocked:
        return {"label": "Transform and verify", "enabled": False,
                "why not": "This needs something that is not ready on this "
                           "machine: " + "; ".join(blocked)}
    if unknown:
        return {"label": "Transform and verify", "enabled": False,
                "why not": "This program could not establish whether "
                           + " and ".join(unknown) + " is usable here, and it "
                           "will not start a run on an assumption."}
    unmet = [(r.as_dict() if hasattr(r, "as_dict") else dict(r))
             for r in (getattr(entry, "requirements", ()) or ())]
    unmet = [r for r in unmet if not r["satisfied"]]
    asked = [plain_language.question_for(str(r.get("name") or ""))
             for r in unmet]
    asked = [q for q in asked if q]
    if asked:
        return {"label": "Transform and verify", "enabled": False,
                "why not": "This still needs something from you: "
                           + asked[0]["ask"]}
    if unmet:
        return {"label": "Transform and verify", "enabled": False,
                "why not": "This material is not ready to run, and what is "
                           "outstanding is this program's work rather than "
                           "anything you can supply. What it is, and what was "
                           "recorded about it, is under Check and prepare."}
    return {"label": "Transform and verify", "enabled": True, "why not": ""}


def _regression(entries) -> dict:
    """What a regression run would cover, and what it could not.

    A regression suite over a corpus is only meaningful against the entries
    that were verified: re-running one that never passed proves nothing moved
    in a thing that was never still. The count of what is EXCLUDED is carried
    beside it, because "the regression suite passed" over four materials
    sounds the same as over forty.
    """
    verified = [e for e in entries if may_say_verified(e)]
    excluded = [e for e in entries if not may_say_verified(e)]
    return {
        "would re-run": len(verified),
        "would not re-run": len(excluded),
        "why some are excluded":
            "a regression compares a run against an earlier verified result. "
            "A material that was never verified has no earlier result to "
            "compare against, so re-running it would not be a regression "
            "check",
        "fixtures": [{"source": e.source_id, "key": e.key}
                     for e in verified],
    }


# ---------------------------------------------------------------------------
# what the default screens actually say
# ---------------------------------------------------------------------------
def default_text(view: dict) -> list:
    """Every string a default (non-Advanced) screen shows, for checking.

    The Advanced and Evidence panels are excluded by construction: this walks
    the keys the default screens render and nothing else, so a term appearing
    in the returned list is a term a first-time user is shown.
    """
    area = view.get("area")
    text: list = []

    if area == "home":
        page = view["home"]
        for name, capability in page.capabilities.items():
            text += [name, capability.word]
        for action in page.actions:
            text += [action.label, action.what_it_does, action.reason]
        text += [str(k) for k in page.counts]
    elif area == "library":
        for spec in view["filters"]:
            text += [spec["label"], spec["explains"]]
        for row in view["rows"]:
            text += [row.status, row.means, row.whose_move]
    elif area == "analyze":
        prepare = view["prepare"]
        for question in prepare["questions"]:
            text += [str(question.get("ask", "")),
                     str(question.get("what to supply", ""))]
        for origin in prepare.get("where each thing came from", ()):
            text.append(origin["what"])
        status = prepare.get("status") or {}
        text += [str(status.get("headline", "")), str(status.get("means", ""))]
    elif area == "verify":
        button = view["button"]
        text += [button["label"], button["why not"]]
        for job in view["jobs"]:
            text.append(job.headline)
            text += [s["step"] for s in job.steps]
            text += [s["what it is doing"] for s in job.steps]
    elif area == "mechanical":
        block = view.get("mechanical") or {}
        for marker in (block.get("markers") or {}).get("markers", ()):
            text.append(marker["marker"])
        text.append((block.get("energy") or {}).get("state", ""))
        for check in block.get("plausibility") or ():
            text.append(check["check"])
    elif area == "derivative":
        block = view.get("derivative") or {}
        for state in block.get("evaluation states") or ():
            text.append(str(state["kind of point"]))
        for criterion in block.get("criteria") or ():
            text.append(str(criterion["finding"]))
    elif area == "residual":
        offer = view["offer"]
        text.append(offer["warning for experimental"])
        for fixture in offer["verified"]:
            text.append(fixture.label)
    elif area == "reports":
        text += [str(k) for k in view["counts"]]
        text.append(view["regression"]["why some are excluded"])

    return [t for t in text if t]


def jargon_in(strings) -> list:
    """Expert vocabulary found in text a default screen shows."""
    found = []
    for text in strings:
        for term in EXPERT_TERMS:
            if term in str(text):
                found.append((term, str(text)))
    return found


# ---------------------------------------------------------------------------
# the Streamlit shell
# ---------------------------------------------------------------------------
def render(results_dir: Path, work_dir: Path, *, st=None) -> None:
    """Draw the interface. Import-safe: ``st`` is injected or imported here."""
    if st is None:                                 # pragma: no cover
        import streamlit as st                     # noqa: PLC0415

    st.set_page_config(page_title="UMAT verification", layout="wide")
    state = st.session_state
    state.setdefault("area", "home")
    state.setdefault("selected", "")

    labels = [a["label"] for a in AREAS]
    chosen = st.sidebar.radio(
        "Where you are", labels,
        index=_AREA_KEYS.index(state["area"]) if state["area"] in _AREA_KEYS
        else 0)
    state["area"] = _AREA_KEYS[labels.index(chosen)]
    spec = AREAS[labels.index(chosen)]
    st.sidebar.caption(spec["what it is for"])

    view = area_view(state["area"], results_dir=results_dir,
                     work_dir=work_dir, selected=state.get("selected", ""))
    st.title(spec["label"])

    drawer = {
        "home": _draw_home, "library": _draw_library, "analyze": _draw_analyze,
        "verify": _draw_verify, "mechanical": _draw_mechanical,
        "derivative": _draw_derivative, "residual": _draw_residual,
        "reports": _draw_reports,
    }[state["area"]]
    drawer(view, st, state)


def _draw_home(view, st, state) -> None:
    page = view["home"]
    columns = st.columns(4)
    for column, (label, value) in zip(columns, list(page.counts.items())[:4]):
        column.metric(label, value)
    if page.counts.get("reached the last stage but not every check passed"):
        st.warning(
            f"{page.counts['reached the last stage but not every check passed']}"
            " materials ran all the way to the end without passing every "
            "check. They are results and they are not verifications; they are "
            "under 'Ran to the end, did not pass everything' in Materials.")
    if page.untranslated_stages:
        st.error("This run contains states this interface has no name for: "
                 + ", ".join(page.untranslated_stages)
                 + ". They are shown under their internal names rather than "
                   "guessed at.")
    st.subheader("This machine")
    for name, capability in page.capabilities.items():
        st.write(f"**{name}** -- {capability.word}"
                 + (f": {capability.detail}" if capability.detail else ""))
        if capability.probe:
            with st.expander(f"Evidence: how {name} was checked"):
                st.code(capability.probe)
                st.json(capability.evidence)
    st.subheader("What would you like to do?")
    for action in page.actions:
        st.button(action.label, disabled=not action.enabled,
                  help=action.what_it_does, key=f"home:{action.key}")
        if not action.enabled and action.reason:
            st.caption(action.reason)


def _draw_library(view, st, state) -> None:
    labels = [f["label"] for f in view["filters"]]
    counts = view["counts"]
    chosen = st.radio("Show", labels, horizontal=True)
    spec = view["filters"][labels.index(chosen)]
    st.caption(f'{spec["explains"]} -- {counts[spec["key"]]} of '
               f'{counts["all"]}')
    text = st.text_input("Search", placeholder="name, repository, material")
    shown = library_module.search(view["rows"], text=text,
                                  filter_key=spec["key"])
    for row in shown[:200]:
        with st.container():
            st.write(f"**{row.source_id}**")
            st.write(f"{row.status} -- {row.means}")
            if row.qualifier:
                st.caption(row.qualifier)
            if st.button("Open", key=f"open:{row.key or row.source_id}"):
                state["selected"] = row.source_id
                state["area"] = "analyze"
            with st.expander("Evidence and advanced"):
                st.json(row.as_dict())


def _draw_analyze(view, st, state) -> None:
    prepare = view["prepare"]
    if view["entry"] is None:
        st.info("Pick a material in Materials first.")
        return
    status = prepare["status"]
    st.write(f"**{status['headline']}** -- {status['means']}")
    if prepare["nothing to ask"]:
        st.success("Everything this program needs, it found. Nothing is "
                   "waiting on you.")
    else:
        st.subheader("These are the only things this program needs from you")
        for question in prepare["questions"]:
            st.write(f"- {question.get('name')}: {question.get('detail')}")
    st.subheader("What was found, and where it came from")
    for origin in prepare.get("where each thing came from", ()):
        st.write(f"- **{origin['what']}** -- {origin['where it came from']}")
    with st.expander("Evidence and advanced"):
        st.json(view["entry"].as_dict())


def _draw_verify(view, st, state) -> None:
    button = view["button"]
    st.button(button["label"], disabled=not button["enabled"],
              key="verify:run")
    if button["why not"]:
        st.caption(button["why not"])
    for job in view["jobs"]:
        st.subheader(job.headline)
        for step in job.steps:
            st.write(f"- {step['step']}: **{step['state']}** "
                     f"-- {step['what it is doing']}")
        if job.failure:
            _draw_failure(job.failure, st)


def _draw_failure(failure: dict, st) -> None:
    """A failure, in the five parts this project requires of every one."""
    st.error(failure["what failed"])
    st.write(failure["why this program believes that"])
    if failure["the evidence for it"]:
        st.write("**What this is based on**")
        for item in failure["the evidence for it"]:
            st.write(f"- {item['finding']}: {item['result']}")
    if failure["what you must provide"]:
        st.info("What you can do: " + failure["what you must provide"])
    else:
        st.caption("Whose move: " + failure["whose move"])
    st.caption("Can this be retried automatically: "
               + ("yes" if failure["can this be retried automatically"]
                  else "no"))
    if failure["full log"]:
        with st.expander("Full log"):
            st.code(failure["full log"])


def _draw_mechanical(view, st, state) -> None:
    if view["entry"] is None:
        st.info(view.get("note", "Pick a material first."))
        return
    block = view["mechanical"]
    curves = block["stress and strain"]
    if not curves.get("comparable") and curves.get("note"):
        st.warning(curves["note"])
    st.subheader("Where the behaviour changed")
    for marker in block["markers"]["markers"]:
        st.write(f"- {marker['marker']}: **{marker['happened']}** "
                 f"{marker['where']}")
    if block["markers"]["what this run could not measure"]:
        st.caption("This run could not measure: "
                   + "; ".join(block["markers"]
                               ["what this run could not measure"]))
    st.subheader("Speed of loading")
    st.write(f"{block['rate']['finding']}: **{block['rate']['holds']}**")
    st.caption(block["rate"]["why"])
    st.subheader("Energy")
    st.write(f"**{block['energy']['state']}** -- {block['energy']['why']}")
    st.subheader("Are these numbers believable?")
    for check in block["plausibility"]:
        (st.warning if check["warn"] else st.write)(
            f"{check['check']}: **{check['result']}** -- {check['why']}")
    with st.expander("Evidence and advanced"):
        st.json({k: v for k, v in block.items()
                 if k not in ("stress and strain", "state variables")})


def _draw_derivative(view, st, state) -> None:
    if view["entry"] is None:
        st.info(view.get("note", "Pick a material first."))
        return
    block = view["derivative"]
    st.subheader("What had to be true")
    for criterion in block["criteria"]:
        st.write(f"- {criterion['finding']}: **{criterion['holds']}** "
                 f"-- {criterion['why']}")
    st.subheader("Where the derivatives were checked")
    for point in block["evaluation states"]:
        st.write(f"- increment {point['increment']}: {point['kind of point']}"
                 f" -- derivatives matched: **{point['derivatives matched here']}**")
    st.subheader("The step sizes the answer holds over")
    for name, sweep in block["plateaus"].items():
        st.write(f"**{sweep['what the sweep is against']}** -- "
                 f"{sweep['why']}")
    with st.expander("Evidence and advanced"):
        st.json({"one sided": block["one sided"],
                 "componentwise": block["componentwise"][:50]})


def _draw_residual(view, st, state) -> None:
    offer = view["offer"]
    status = view["residual assembler"]
    if not status.usable:
        st.error(status.detail)
        return
    st.write(f"{offer['counts']['verified']} verified materials are ready to "
             f"use.")
    for fixture in offer["verified"]:
        st.write(f"- {fixture.label}")
    if offer["experimental"]:
        with st.expander(f"{offer['counts']['not verified']} materials that "
                         f"are NOT verified"):
            st.error(offer["warning for experimental"])
            for fixture in offer["experimental"]:
                st.write(f"- {fixture.label} -- {fixture.why_not}")


def _draw_reports(view, st, state) -> None:
    for label, value in view["counts"].items():
        st.write(f"- {label}: **{value}**")
    regression = view["regression"]
    st.write(f"A regression run would re-run "
             f"{regression['would re-run']} materials and would not re-run "
             f"{regression['would not re-run']}.")
    st.caption(regression["why some are excluded"])


def corpus_directories() -> tuple[Path, Path]:
    """Where the corpus round this view reads was written: results, then work.

    The same place the main interface's Corpus tab reads, so the two show the
    same round without being told: ``UMAT_OTI_CORPUS_RESULTS`` and
    ``UMAT_OTI_CORPUS_WORK`` when set, otherwise ``corpus_run/`` beside the
    checkout.
    """
    import os                                      # noqa: PLC0415

    from umat_oti.app.resources import repository_root  # noqa: PLC0415

    beside = (repository_root() or Path.cwd()).parent / "corpus_run"
    return (Path(os.environ.get("UMAT_OTI_CORPUS_RESULTS") or beside / "results"),
            Path(os.environ.get("UMAT_OTI_CORPUS_WORK") or beside / "work"))


def main(argv: Optional[list[str]] = None) -> None:
    """``streamlit run src/umat_oti/app/unified_app.py [-- --results-dir D --work-dir D]``.

    Both directories default to :func:`corpus_directories`. Before they did,
    both were required and nothing called this function, so the command the
    GUI guide gives opened an empty page.
    """
    import argparse                                # noqa: PLC0415
    results_dir, work_dir = corpus_directories()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results-dir", type=Path, default=results_dir,
                        help=f"a corpus round's results (default: {results_dir})")
    parser.add_argument("--work-dir", type=Path, default=work_dir,
                        help=f"that round's work directory (default: {work_dir})")
    args = parser.parse_args(argv)
    render(args.results_dir, args.work_dir)


if __name__ == "__main__":                         # `streamlit run <this file>`
    main()
