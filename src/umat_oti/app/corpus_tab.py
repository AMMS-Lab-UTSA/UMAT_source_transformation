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
                                      histories, job_log, load_run,
                                      run_command, start_run)

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

    st.markdown("**Manifest and where every number came from**")
    st.write(entry.manifest)
    if entry.formulation:
        st.markdown("**Formulation**")
        st.write(entry.formulation)

    st.markdown("**What is missing**")
    st.table([r.as_dict() for r in entry.requirements])

    if entry.discovery:
        st.markdown("**The experiment this pipeline generated**")
        st.write({k: v for k, v in entry.discovery.items() if k != "attempts"})
        for attempt in (entry.discovery.get("attempts") or [])[:12]:
            st.caption(f"amplitude {attempt.get('amplitude')}: "
                       f"{'activated' if attempt.get('activated') else 'linear'}"
                       f" -- {((attempt.get('activation') or {}).get('summary') or '')[:160]}")

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
        series = histories(work_dir, entry.key)
        if series:
            st.line_chart({name: [row[0] if row else None
                                  for row in payload["stress"]]
                           for name, payload in series.items()})

    if entry.precision_control:
        st.markdown("**Precision control**")
        st.write(entry.precision_control)
    if entry.truncation:
        st.markdown("**Where the derivative was dropped**")
        st.write(entry.truncation)

    if entry.tangent:
        st.markdown("**The tangent, state by state**")
        st.write({k: v for k, v in entry.tangent.items() if k != "states"})
        for index, state in enumerate(entry.tangent.get("states") or ()):
            with st.expander(f"increment {state.get('increment')} -- "
                             f"{(state.get('regime') or {}).get('regime', '')}"):
                st.write({"verified": state.get("verified"),
                          "reason": state.get("reason"),
                          "regime": state.get("regime"),
                          "one-sided gap per step": state.get("smoothness")})
                st.table(componentwise_errors(entry, index))

    st.markdown("**Where the files are**")
    st.write(entry.artifacts)
    text = deck_text(work_dir, entry.key)
    if text:
        with st.expander("the generated deck"):
            st.code(text)
