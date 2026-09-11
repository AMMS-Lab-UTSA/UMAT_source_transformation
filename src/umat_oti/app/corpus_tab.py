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

from umat_oti.app.corpus_view import (MODES, componentwise_errors, deck_text,
                                      evidence_paths, fd_plateau, histories,
                                      job_log, load_run, run_command,
                                      start_run)

#: A one-line gloss for every terminal state, so a table of them is readable
#: without the reader having to hold the vocabulary in their head.
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
}


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
    st.write({"terminal state": entry.terminal_state, "kind": entry.kind,
              "stage the batch reached": entry.stage})
    st.info(entry.reason or "no reason recorded")

    # The six gates first, because every other panel on this page is one of
    # them in detail and a reader who stops here should still know which
    # measurements the verdict rests on and which of them nobody made.
    st.markdown("**What was measured, gate by gate**")
    st.table(entry.evidence)

    st.markdown("**Manifest and where every number came from**")
    st.write(entry.manifest)
    if entry.run_manifest:
        st.markdown("**The manifest that was actually run**")
        st.write({k: v for k, v in entry.run_manifest.items() if k != "loading"})
    if entry.loading:
        st.markdown("**The loading history it walked, segment by segment**")
        st.table(entry.loading)
    if entry.material_search:
        with st.expander("what was read while looking for material constants"):
            st.write(entry.material_search)
    if entry.formulation:
        st.markdown("**Formulation**")
        st.write(entry.formulation)

    st.markdown("**What is missing**")
    st.table([r.as_dict() for r in entry.requirements])

    _experiment_panel(entry, st)
    _history_panel(entry, st)

    if entry.jobs:
        st.markdown("**Abaqus**")
        st.write(entry.jobs)
        for job in ("original", "transformed", "control"):
            if job in (entry.artifacts or {}):
                with st.expander(f"{job} log"):
                    st.write(job_log(work_dir, entry.key, job))

    if entry.primal:
        st.markdown("**Original against converted, over the whole history**")
        st.write(entry.primal)
        if entry.primal_signature:
            st.markdown("**What kind of disagreement this is**")
            st.write(entry.primal_signature)
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
