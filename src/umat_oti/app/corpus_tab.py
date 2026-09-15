"""The corpus, as a page: what was acquired, what happened, and where to look.

Thin on purpose. Every number here comes from
:mod:`umat_oti.app.corpus_view`, which reads the artefacts the batch wrote;
nothing on this page computes a verdict, a count or a tolerance, so what a
reader sees is what the evidence says and a screenshot of it remains evidence.

Import-safe without Streamlit, so the service and its tests do not drag a UI
dependency into a headless run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from umat_oti.app.corpus_view import (DID_NOT_HOLD, MODES, NOT_ESTABLISHED,
                                      componentwise_errors, deck_text,
                                      evidence_paths, fd_plateau, histories,
                                      job_log, load_run, run_command,
                                      start_run)

#: A one-line gloss for every terminal state, so a table of them is readable
#: without the reader having to hold the vocabulary in their head.
#:
#: The page's own wording wins where it has some; anything it does not gloss
#: falls back to :data:`umat_oti.abaqus.terminal_states.MEANING`, which is
#: where the meaning of a state now lives -- beside the state itself, so that
from umat_oti.abaqus import terminal_states

#: adding a rung without giving it words is no longer possible.
GLOSS = {
    "fully_verified": "both builds ran, agreed over the whole history, and "
                      "the tangent matched a converged difference",
    "missing_material_data": "nobody published what this material is made of",
    "not_a_umat": "the file's Abaqus entry point is something else",
    "incomplete_or_corrupt_source": "the file does not compile as published",
    "external_dependency_unavailable": "a module or include it needs was "
                                       "never published beside it",
    "waits_for_input": "the source waits on terminal input, so a solver hangs "
                       "rather than fails",
    "transform_refused": "the transform could not convert it -- our work",
    "unsupported_formulation": "no element here drives that formulation -- ours",
    "experiment_not_generated": "this harness builds no experiment this "
                                "source will run -- ours",
    "experiment_not_informative": "both builds agreed, over an experiment in "
                                  "which the material did not do what it is "
                                  "for -- ours",
    "informativeness_not_established": "nobody measured whether the "
                                       "experiment exercised anything -- ours",
    "support_build_failed": "the transform's own modules did not compile -- ours",
    "original_job_failed": "the original did not run -- ours until proven "
                           "otherwise",
    "transformed_job_failed": "the converted build did not run -- ours",
    "primal_disagreed": "the two builds compute different stress -- ours",
    "derivative_truncated": "the converted source drops a derivative on the "
                            "way to the stress -- ours",
    "tangent_not_verified": "the difference could not pin the tangent down "
                            "-- ours",
    "not_attempted": "this run did not reach it",
    "harness_error": "the run broke, not the model",
    #: A file with the 37-argument UMAT header that assigns neither STRESS nor
    #: DDSDDE and makes no CALL: the author published the interface and no
    #: constitutive content. External, and its own state rather than a
    #: borrowed one -- "does not compile" is what
    #: incomplete_or_corrupt_source is glossed, and a template compiles
    #: perfectly well.
    "published_stub_no_constitutive_content":
        "the author published a template with no material in it",
    #: The two builds were handed different arguments, computed by the solver
    #: from each build's own earlier outputs on our deck. Ours to locate.
    "arguments_diverged_before_the_routine":
        "the two builds were handed different arguments part way through, "
        "computed from their own earlier answers; where they parted is not "
        "yet located",
    #: The histories differ and no recorded call accounts for it: the
    #: difference is real and the explanation is missing. Ours, because what
    #: is missing is our instrumentation rather than their file.
    "disagreement_not_in_any_recorded_call":
        "the builds differ and no call this harness recorded accounts for it "
        "-- ours",
}

# Anything the page does not word itself takes the state's own meaning.
GLOSS = {**terminal_states.MEANING, **GLOSS}


def render(results_dir: Path, work_dir: Path, *, st=None) -> None:
    """Draw the corpus page. ``st`` is Streamlit, injected so tests can pass a
    recorder and check what would be drawn without a browser."""
    if st is None:                                # pragma: no cover - runtime
        import streamlit as st                    # noqa: PLC0415

    view = load_run(results_dir, work_dir)
    st.subheader("Corpus verification")
    st.caption(f"{view.attempted} entries settled"
               + (f" of {view.expected}" if view.expected else "")
               + ("; run finished" if view.finished else "; run in progress"))

    counts = view.by_kind
    columns = st.columns(3)
    columns[0].metric("verified", counts.get("verified", 0))
    columns[1].metric("blocked outside this repository", counts.get("external", 0))
    columns[2].metric("work remaining here", counts.get("internal", 0))

    st.markdown("**Where every entry stands**")
    st.table([{"terminal state": state, "entries": number,
               "what it means": GLOSS.get(state, "")}
              for state, number in view.by_terminal_state.items()])

    st.markdown("**Start a run**")
    for mode, description in MODES.items():
        st.caption(f"`{mode}`: {description}")
    chosen = st.selectbox("mode", list(MODES))
    only = st.text_input("only (a substring of the source's path)", "")
    st.code(" ".join(run_command(chosen, results_dir, work_dir, only=only)))
    if st.button(f"start {chosen}"):
        handle = start_run(chosen, results_dir, work_dir, only=only)
        st.write(handle.as_dict())

    names = [entry.source_id for entry in view.entries]
    if not names:
        return
    picked = st.selectbox("entry", names)
    entry = next(e for e in view.entries if e.source_id == picked)
    _entry_panel(entry, work_dir, st)


def _entry_panel(entry, work_dir: Path, st) -> None:
    st.markdown(f"### {entry.source_id}")
    _verdict_panel(entry, st)
    st.write({"terminal state": entry.terminal_state, "kind": entry.kind,
              "stage the batch reached": entry.stage})
    st.info(entry.reason or "no reason recorded")

    # The six gates first, because every other panel on this page is one of
    # them in detail and a reader who stops here should still know which
    # measurements the verdict rests on and which of them nobody made.
    st.markdown("**What was measured, gate by gate**")
    st.table(entry.evidence)
    _gate_tally_panel(entry, st)

    st.markdown("**Manifest and where every number came from**")
    st.write(entry.manifest)
    if entry.run_manifest:
        st.markdown("**The manifest that was actually run**")
        st.write({k: v for k, v in entry.run_manifest.items() if k != "loading"})
    if entry.loading:
        st.markdown("**The loading history it walked, segment by segment**")
        st.table(entry.loading)
    if entry.material_search_finding:
        st.markdown("**Where the material constants were looked for**")
        st.table([entry.material_search_finding])
        if entry.material_search:
            with st.expander("the pairing scan's own record"):
                st.write(entry.material_search)
    if entry.formulation:
        st.markdown("**Formulation**")
        st.write(entry.formulation)

    st.markdown("**What is missing**")
    st.table([r.as_dict() for r in entry.requirements])

    _planned_experiment_panel(entry, st)
    _coverage_panel(entry, st)
    _objectivity_panel(entry, st)
    _experiment_panel(entry, st)
    _informativeness_panel(entry, st)
    _history_panel(entry, st)

    if entry.jobs:
        st.markdown("**Abaqus**")
        st.write(entry.jobs)
        for job in ("original", "transformed", "control"):
            if job in (entry.artifacts or {}):
                with st.expander(f"{job} log"):
                    st.write(job_log(work_dir, entry.key, job))

    # Drawn whenever a signature was recorded, and NOT only where a primal
    # block sits beside it: a panel hidden behind another field's presence is
    # a blank, and a blank reads as "nobody classified this".
    if entry.primal_signature:
        _signature_panel(entry, st)

    if entry.primal:
        st.markdown("**Original against converted, over the whole history**")
        st.write(entry.primal)
        series = histories(work_dir, entry.key)
        if series:
            st.line_chart({name: [row[0] if row else None
                                  for row in payload["stress"]]
                           for name, payload in series.items()})

    if entry.precision_control:
        st.markdown("**Precision control: the author's own declared precision, "
                    "widened and re-run**")
        st.write(entry.precision_control)
    if entry.association_control:
        st.markdown("**Association control: the model against itself, with the "
                    "same mathematics computed in a different order**")
        st.write(entry.association_control)
    if entry.truncation:
        st.markdown("**Where the derivative was dropped**")
        st.write(entry.truncation)

    if entry.tangent:
        _tangent_panel(entry, work_dir, st)

    st.markdown("**Where the files are**")
    st.write(entry.artifacts)
    st.markdown("**The path to every piece of evidence on this page**")
    st.table(evidence_paths(entry))
    text = deck_text(work_dir, entry.key)
    if text:
        with st.expander("the generated deck"):
            st.code(text)


def _verdict_panel(entry, st) -> None:
    """What this entry may honestly be called, before anything else on it.

    The batch's own terminal state is carried unedited. What is added is the
    qualification the six gates make necessary, in the channel that matches
    it: a complete six is a success, a gate that did not hold is an error, and
    a gate nobody established is a WARNING -- a third channel, because a
    measurement that was never made is neither a pass nor a failure and a
    reader must not have to read the text to tell which of the three it is.

    Measured on pass10: 3 of the 10 entries the batch settled at ``verified``
    carry no informativeness measurement at all. The word "verified" does not
    appear over any of them here.
    """
    verdict = entry.verdict or {}
    st.markdown(f"**{verdict.get('qualified state', entry.terminal_state)}**")
    claim = verdict.get("what may be claimed") or ""
    if verdict.get("may be called verified"):
        st.success(claim)
    elif verdict.get("nothing was measured"):
        # Its own channel. An entry that never reached a run is not a warning
        # about this pipeline's evidence -- nobody published what the material
        # is made of, or the file is not a UMAT -- and drawing it beside the
        # entries whose gates nobody got round to measuring would pool two
        # answers the record keeps apart.
        st.info(claim)
    elif verdict.get("gates never established"):
        st.warning(claim)
    else:
        st.error(claim)


def _gate_tally_panel(entry, st) -> None:
    """The six split three ways, so the split cannot be read as a two-way one.

    A page that lists "5 of 6 passed" has already merged "did not hold" with
    "nobody measured it", and those are the two findings a reader most needs
    apart: one is a result about the source and the other is a hole in this
    pipeline's evidence.
    """
    verdict = entry.verdict or {}
    st.write({
        "gates that hold": verdict.get("gates that hold") or [],
        "gates that did not hold": verdict.get("gates that did not hold") or [],
        f"gates {NOT_ESTABLISHED} -- neither a pass nor a failure":
            verdict.get("gates never established") or [],
    })
    after = verdict.get(
        "what the batch recorded after a gate that did not hold") or {}
    for gate, said in after.items():
        st.caption(f"{gate.replace('_', ' ')}: {said}")
    # Findings the six gates do not cover, on the page beside them rather
    # than under them: a source can pass every gate this pipeline measures
    # and still be a source whose own response is not frame indifferent.
    outside = verdict.get("findings outside the six gates") or []
    if outside:
        st.markdown("**What the record says that the six gates do not cover**")
        for said in outside:
            st.warning(said)


def _planned_experiment_panel(entry, st) -> None:
    """Why this source was driven the way it was, quoted from the source.

    The loading path says what was driven. This says why: which family of
    behaviour the source was read as, what criterion an experiment for that
    family has to meet, and which lines of the source settled it. A reader who
    cannot see the quoted lines cannot disagree with the reading, and a
    reading nobody can disagree with is not evidence.
    """
    plan = entry.planned_experiment or {}
    st.markdown("**Why this source was driven this way**")
    if not plan.get("recorded"):
        st.warning("this run records no planned experiment, so why this "
                   "source was driven the way it was is " + NOT_ESTABLISHED)
    st.write({k: v for k, v in plan.items()
              if k not in ("recorded", "the source lines that settled it",
                           "notes this family carries", "warnings")})
    lines = plan.get("the source lines that settled it") or []
    if lines:
        st.caption("the source lines that settled the family:")
        for line in lines:
            st.code(str(line))
    for note in plan.get("notes this family carries") or ():
        st.caption(f"note: {note}")
    for warning in plan.get("warnings") or ():
        st.warning(str(warning))


def _coverage_panel(entry, st) -> None:
    """The family's own criteria, each with three possible answers.

    ``met=null`` is NOT MEASURED and is shown as ``not established``: on
    pass10 one criterion reads "no increment in this run applied a direct
    strain with no shear, so the coupling has nothing to show up in", and a
    page that rendered that as met would be claiming a coupling was exercised
    by an experiment that never presented it.
    """
    if not entry.coverage:
        return
    st.markdown("**The criteria this family of behaviour has to meet**")
    st.table(entry.coverage)
    unestablished = [row["finding"] for row in entry.coverage
                     if not row["established"]]
    if unestablished:
        st.warning("not measured on this run, so neither met nor unmet: "
                   + "; ".join(unestablished))


def _objectivity_panel(entry, st) -> None:
    """Two facts, two rows, never one tick.

    "agreed" is about THE TRANSFORM -- the converted build and the original
    computed the same thing on a rotated path. "objective" is about THE MODEL
    -- the author's own response to a rotated path is the unrotated response
    rotated. On pass10 the NeoHookean entry has agreed=true and
    objective=false, its own response missing Q sigma Q^T by 9.02 relative, so
    merging them would report this pipeline's success as the published
    source's correctness.
    """
    rows = entry.objectivity or []
    if not any(row["established"] for row in rows) and not entry.objectivity_detail:
        return
    st.markdown("**Objectivity: two different claims, kept apart**")
    st.table(rows)
    for row in rows:
        if row["holds"] == DID_NOT_HOLD:
            st.error(f"{row['finding']}: {DID_NOT_HOLD}. {row['why']}")
        elif not row["established"]:
            st.warning(f"{row['finding']}: {NOT_ESTABLISHED}. {row['why']}")
    with st.expander("the rotation and what was compared in it"):
        st.write(entry.objectivity_detail)


def _informativeness_panel(entry, st) -> None:
    """Whether there is any behaviour under the agreement, and at what scale.

    Agreement about a material sitting still is agreement about the part every
    build gets right. This is the gate that says whether there was anything
    else, the clock the experiment ran against, and whether the response it
    produced fits the scales the problem supplies.
    """
    st.markdown("**Did the material do anything, and does the response fit "
                "the problem**")
    st.table([entry.informativeness])
    if not entry.informativeness.get("established"):
        st.warning("whether the material did anything over the run that was "
                   "verified is " + NOT_ESTABLISHED + ": "
                   + str(entry.informativeness.get("why") or ""))
    elif entry.informativeness.get("holds") == DID_NOT_HOLD:
        st.error(str(entry.informativeness.get("why") or ""))

    st.markdown("**Against the source's own clock**")
    st.table([entry.time_scale])

    if entry.plausibility or entry.plausibility_overall.get("established"):
        st.markdown("**Whether the response fits the scales this problem "
                    "supplies**")
        st.table([entry.plausibility_overall] + list(entry.plausibility))


def _signature_panel(entry, st) -> None:
    """Hypotheses about a disagreement, each with its own confirmation status.

    A stage is not a diagnosis. Every hypothesis carries whether it was
    confirmed, refuted or still needs evidence, and ``confirmed_root_cause``
    is shown as ``not established`` wherever the record holds null -- which is
    every hypothesis that is not settled. A list without the statuses reads as
    a set of conclusions.
    """
    st.markdown("**What kind of disagreement this is -- hypotheses, not a "
                "diagnosis**")
    rows = entry.signature or []
    if rows:
        st.table(rows)
        confirmed = [row for row in rows
                     if row["confirmed root cause"] != NOT_ESTABLISHED]
        if not confirmed:
            st.warning("no root cause is confirmed: every hypothesis below "
                       "is " + NOT_ESTABLISHED)
    with st.expander("the signature block as the batch wrote it"):
        st.write(entry.primal_signature)


def _experiment_panel(entry, st) -> None:
    """The experiment this verdict rests on, and what it cost to get one.

    A repair that made a history finite by removing the behaviour under test
    has not produced a verification OF that behaviour, so what was dropped is
    on the page beside what was verified rather than in a log.
    """
    settlement = entry.experiment or {}
    st.markdown("**The experiment this pipeline generated**")
    st.write({"an analysis finite from end to end":
              settlement.get("complete_finite_verification_run"),
              "how far the search's own run got":
              settlement.get("discovery_usable_prefix"),
              "why it stopped": settlement.get("failure_mechanism"),
              "what was rebuilt inside the part it proved safe":
              settlement.get("safe_loading_reconstructed"),
              "which segment was shortened or dropped":
              settlement.get("segment_repair"),
              "what the experiment therefore stopped exercising":
              settlement.get("coverage_given_up")})
    st.markdown("**Did the material do anything, and for long enough**")
    st.write({"mechanically informative":
              settlement.get("mechanically_informative"),
              "measured on the run that was verified":
              settlement.get("activation_on_the_frozen_run"),
              "against the time scale the source declares":
              settlement.get("time_scale_coverage")})
    if entry.discovery:
        st.write({k: v for k, v in entry.discovery.items()
                  if k not in ("attempts", "failure_mechanism",
                               "segment_repair", "coverage_given_up",
                               "safe_loading_reconstructed",
                               "discovery_usable_prefix")})
        for attempt in (entry.discovery.get("attempts") or [])[:12]:
            summary = ((attempt.get("activation") or {}).get("summary") or "")
            st.caption(f"amplitude {attempt.get('amplitude')}: "
                       f"{'activated' if attempt.get('activated') else 'linear'}"
                       f" -- {summary[:160]}")


def _history_panel(entry, st) -> None:
    """How each history grouped, side by side.

    Abaqus printing THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a statement
    about the solver, not about the routine it called: a job completes while
    its UMAT returns values that are not numbers. The increment and the
    material point where that first happened are named here.
    """
    if not entry.history:
        return
    st.markdown("**What the routine wrote, increment by increment**")
    st.table(entry.history)


def _tangent_panel(entry, work_dir: Path, st) -> None:
    st.markdown("**The tangent, state by state**")
    st.write({k: v for k, v in entry.tangent.items() if k != "states"})
    for index, state in enumerate(entry.tangent.get("states") or ()):
        with st.expander(f"increment {state.get('increment')} -- "
                         f"{(state.get('regime') or {}).get('regime', '')}"):
            st.write({"verified": state.get("verified"),
                      "reason": state.get("reason"),
                      "regime": state.get("regime"),
                      "one-sided gap per step": state.get("smoothness")})
            st.caption("the finite-difference plateau: one step size cannot "
                       "separate truncation error from cancellation, so what "
                       "settles it is the run of steps the error stops "
                       "moving over")
            st.table(fd_plateau(entry, index))
            for against, title in (
                    ("against_the_authors_tangent",
                     "the author's own DDSDDE against the same difference"),
                    ("the_references_own_error",
                     "what the reference difference costs itself")):
                rows = fd_plateau(entry, index, against=against)
                if rows:
                    st.caption(title)
                    st.table(rows)
            rows = componentwise_errors(entry, index, work_dir=work_dir)
            if rows:
                st.caption("entry by entry: the DDSDDE the author's own "
                           "routine returned against the derivative the "
                           "converted build extracted. The verdict rests on "
                           "the plateau above, not on this -- a difference "
                           "here is a statement about the author's tangent")
                st.table(rows[:24])
