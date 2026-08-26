"""A guided four-step interface over the same backend the CLI uses.

The interface constructs a WorkbenchRequest and calls run_workbench. There is
no second numerical implementation here, and no result on this page comes from
anywhere but that call.

The design rule is progressive disclosure: a first-time user meets one
conceptual task per screen, with expert controls folded away, and is told what
is missing rather than being allowed to press Run and find out. The step
numbers are generated from wizard.STEPS, so they cannot skip.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "src") not in sys.path:  # running via `streamlit run`
    sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.app import examples as example_projects  # noqa: E402
from umat_oti.app.wizard import (  # noqa: E402
    PRODUCT_HELP, PRODUCT_LABELS, PRODUCT_TABS, STEPS, WizardState, step_titles,
)
from umat_oti.publication.layout import GUI_MIN_TEXT_PX  # noqa: E402
from umat_oti.publication.status import STATUS_MEANINGS, status_word  # noqa: E402
from umat_oti.services.workbench import (  # noqa: E402
    LoadingHistory, PRODUCTS, WorkbenchRequest, analyse_source, run_workbench,
)

#: Body text large enough to read, and to survive being placed in a figure.
#: Streamlit's own label and caption tier is 14 CSS px, which prints below the
#: 9 pt floor at any viewport wide enough to be usable; every tier is raised to
#: this instead of only the base, because raising the base alone leaves the
#: rem-scaled tiers behind.
BASE_FONT_PX = GUI_MIN_TEXT_PX

LOADING_PRESETS: dict[str, dict[str, Any]] = {
    "Uniaxial strain, 20 steps of 1e-4 (small strain)": {
        "dstran": (1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        "increments": 20, "gradient": (),
        "provenance": "parameter_sensitivity/loading_paths.json default",
        "explains": "Stretches along one axis in 20 equal steps. For a "
                    "steel-like model this crosses the yield point part way "
                    "through, so both the elastic and the inelastic response "
                    "are exercised.",
    },
    "Uniaxial strain, 10 steps of 1e-4 (small strain)": {
        "dstran": (1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        "increments": 10, "gradient": (),
        "provenance": "declared in the interface",
        "explains": "The same path, half as long. Quicker, and may stay "
                    "elastic throughout for a stiffer material.",
    },
    "Uniaxial stretch, 10 steps of 1e-3 (finite strain)": {
        "dstran": (0.0,) * 6, "increments": 10,
        "gradient": (1.0e-3, 0, 0, 0, 0, 0, 0, 0, 0),
        "provenance": "declared in the interface; drives DFGRD directly",
        "explains": "Drives the deformation gradient instead of the strain "
                    "increment. Required by a source that reads DFGRD1.",
    },
}

STYLE = f"""
<style>
  html, body, [class*="css"] {{ font-size: {BASE_FONT_PX}px; }}
  .stApp h1 {{ font-size: 1.9rem; }}
  .stApp h2 {{ font-size: 1.45rem; }}
  .stApp h3 {{ font-size: 1.15rem; }}
  div[data-testid="stMetricValue"] {{ font-size: 1.5rem; }}
  /* Every tier Streamlit sets below 1rem, raised to 1rem. These are the ones
     that printed at 8.8 pt in the manuscript while the headings passed. */
  label, label p, .stCheckbox label, .stRadio label,
  div[data-testid="stWidgetLabel"] p,
  div[data-testid="stCaptionContainer"], div[data-testid="stCaptionContainer"] p,
  div[data-testid="stMetricLabel"] p,
  .stSelectbox div[data-baseweb="select"], .stMultiSelect div[data-baseweb="select"],
  input, textarea, button, .stDownloadButton button,
  div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{
      font-size: 1rem !important; line-height: 1.45; }}
  code, .stCode, pre {{ font-size: .95rem !important; }}
  .oti-steps {{ display: flex; gap: .5rem; flex-wrap: wrap;
                margin: .1rem 0 .9rem 0; }}
  .oti-step {{ border: 1px solid #c9ced6; border-radius: 6px;
               padding: .28rem .7rem; font-size: .92rem; color: #4a5261;
               background: #f4f6f9; white-space: nowrap; }}
  .oti-step.done {{ border-color: #2f7d55; color: #2f7d55; background: #eef7f1; }}
  .oti-step.current {{ border-color: #1c3f94; color: #fff; background: #1c3f94;
                       font-weight: 600; }}
  .oti-badge {{ display: inline-block; border-radius: 4px; padding: .06rem .5rem;
                font-size: .84rem; font-weight: 700; letter-spacing: .02em;
                border: 1px solid; }}
  .oti-pass {{ color: #1d6b40; border-color: #1d6b40; background: #eef7f1; }}
  .oti-warn {{ color: #8a5300; border-color: #8a5300; background: #fdf5e8; }}
  .oti-stop {{ color: #9b1c1c; border-color: #9b1c1c; background: #fdeeee; }}
  .oti-mute {{ color: #4a5261; border-color: #9aa1ad; background: #f1f3f6; }}
  .oti-origin {{ font-size: .82rem; color: #5b6270; }}
</style>
"""

#: Which visual class a status word gets. The word is always shown, so this
#: only reinforces meaning; it never carries it.
BADGE_CLASS = {"PASS": "oti-pass", "PARTIAL": "oti-warn", "WITHHELD": "oti-warn",
               "FAILED": "oti-stop", "BLOCKED": "oti-stop",
               "UNSUPPORTED": "oti-mute", "NOT REQUESTED": "oti-mute"}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _state() -> WizardState:
    if "wizard" not in st.session_state:
        st.session_state["wizard"] = WizardState()
    return st.session_state["wizard"]


def badge(word: str) -> str:
    return (f'<span class="oti-badge {BADGE_CLASS.get(word, "oti-mute")}">'
            f'{word}</span>')


def origin_note(origin: str, detail: str = "") -> None:
    words = {example_projects.INFERRED: "read from the example's contract",
             example_projects.USER: "entered by you",
             example_projects.UNAVAILABLE: "not available; nothing was assumed"}
    st.markdown(f'<span class="oti-origin">{words.get(origin, origin)}'
                f'{(" — " + detail) if detail else ""}</span>',
                unsafe_allow_html=True)


def progress_bar(current: int, furthest: int) -> None:
    chips = []
    for index, title in enumerate(step_titles()):
        css = "current" if index == current else ("done" if index <= furthest
                                                  else "")
        chips.append(f'<span class="oti-step {css}">{title}</span>')
    st.markdown(f'<div class="oti-steps">{"".join(chips)}</div>',
                unsafe_allow_html=True)


def context_strip(state: WizardState) -> None:
    """What has been settled so far, on every step after the first.

    Each step shows one task, which means a screenshot of one step would
    otherwise not say which source it is about. This keeps the answer on screen
    without bringing the earlier controls back with it.
    """
    if state.source_key is None:
        return
    pieces = [f"**{state.source_key}**"]
    if state.analysis:
        pieces.append(f"{state.analysis.get('source_form', '?')} form")
        pieces.append(f"{state.analysis.get('closure_size', 0)} routine"
                      + ("s" if state.analysis.get("closure_size", 0) != 1 else ""))
        solves = len(state.analysis.get("local_solves") or [])
        pieces.append(f"{solves} local Newton solve"
                      + ("s" if solves != 1 else ""))
    if state.props:
        pieces.append(f"NTENS {state.ntens}")
        pieces.append(f"NSTATV {state.nstatv}")
        pieces.append(f"{len(state.props)} constants")
    st.caption(" · ".join(pieces))


def blockers(problems: list[str], heading: str) -> None:
    if not problems:
        return
    st.warning(f"**{heading}**\n\n"
               + "\n".join(f"- {problem}" for problem in problems))


def navigate(current: int, forward_ok: bool, forward_label: str = "Next") -> None:
    """Back and Next, with Next explaining itself when it cannot be used."""
    left, right = st.columns([1, 1])
    if current > 0 and left.button("← Back", key=f"back_{current}",
                                   width="stretch"):
        st.session_state["step"] = current - 1
        st.rerun()
    if current < len(STEPS) - 1:
        if right.button(f"{forward_label} →", key=f"next_{current}",
                        type="primary", disabled=not forward_ok,
                        width="stretch"):
            st.session_state["step"] = current + 1
            st.rerun()


# --------------------------------------------------------------------------- #
# Step 1 -- Source
# --------------------------------------------------------------------------- #
def step_source(state: WizardState) -> None:
    st.subheader(step_titles()[0])
    st.caption(STEPS[0][1])

    found = example_projects.discover()
    labels = {f"{key} — {example_projects.describe(value)}": key
              for key, value in found.items()}
    choices = ["Upload my own UMAT file"] + list(labels)
    picked = st.selectbox(
        "Which UMAT do you want to differentiate?", choices, key="source_choice",
        help="A UMAT is the Fortran subroutine Abaqus calls to update stress "
             "for one material point. The examples ship with this repository, "
             "each with a committed contract the interface can fill in from.")

    if picked == "Upload my own UMAT file":
        uploaded = st.file_uploader("UMAT source file",
                                    type=["f", "for", "f90", "f77"],
                                    key="source_upload")
        if uploaded is not None:
            scratch = Path(tempfile.mkdtemp(prefix="umat_oti_gui_"))
            state.source_path = scratch / uploaded.name
            state.source_path.write_bytes(uploaded.getvalue())
            state.source_key = uploaded.name
            state.field_origins = {}
        st.caption("Nothing is prefilled for an uploaded file: its dimensions "
                   "and material constants are yours to give on the next step.")
    else:
        key = labels[picked]
        example = found[key]
        if state.source_key != key:
            _adopt_example(state, example)
        st.caption(f"`{example.source.relative_to(REPO_ROOT)}` — "
                   f"{example.provenance()}")

    with st.expander("Advanced settings — dependency and include roots"):
        roots_text = st.text_area(
            "Directories to search for helper routines, one per line",
            value=st.session_state.get("roots_text", ""), key="roots_text",
            height=90,
            help="Left blank, the folder holding the source is searched. A "
                 "helper routine is a subroutine the entry source calls but "
                 "does not itself define.")
        state.dependency_roots = tuple(
            Path(line.strip()) for line in roots_text.splitlines() if line.strip())
        if state.source_path is not None and not state.dependency_roots:
            state.dependency_roots = (Path(state.source_path).parent,)

    if state.source_path is None:
        st.info("Choose an example or upload a file to continue.")
        navigate(0, forward_ok=False)
        return

    if st.button("Analyse this source", type="primary", key="analyse"):
        with st.spinner("Reading the source and resolving its dependencies…"):
            state.analysis = analyse_source(Path(state.source_path),
                                            state.dependency_roots)
        st.rerun()

    if state.analysis:
        _show_analysis(state.analysis)
    blockers(state.source_problems(), "This source cannot be used yet")
    navigate(0, forward_ok=state.source_complete())


def _adopt_example(state: WizardState, example) -> None:
    """Fill the material step from a committed contract, and record that."""
    state.source_key = example.key
    state.source_path = example.source
    state.analysis = {}
    origins: dict[str, str] = {}
    inferred = example_projects.INFERRED
    missing = example_projects.UNAVAILABLE

    for field, value in (("ntens", example.ntens), ("ndi", example.ndi),
                         ("nshr", example.nshr), ("nstatv", example.nstatv)):
        if value is None:
            origins[field] = missing
        else:
            setattr(state, field, int(value))
            origins[field] = inferred
    state.props = example.props
    origins["props"] = inferred if example.props else missing
    state.parameters = tuple((p.name, p.props_index) for p in example.parameters
                             if p.differentiate)
    origins["parameters"] = inferred if example.parameters else missing
    state.state_names = tuple(example.state_names)
    origins["state_names"] = inferred if example.state_names else missing
    state.field_origins = origins
    for key in ("props_editor", "parameter_editor", "state_editor"):
        st.session_state.pop(key, None)


def _show_analysis(analysis: dict) -> None:
    st.markdown("**What the source turned out to be**")
    left, middle, right = st.columns(3)
    left.metric("Source form", analysis.get("source_form", "unknown"),
                help="Fixed form is the older column-sensitive Fortran layout; "
                     "free form is the modern one. It is detected, not declared.")
    middle.metric("Routines resolved", analysis.get("closure_size", 0),
                  help="The entry routine plus every helper it needs.")
    right.metric("Local Newton solves", len(analysis.get("local_solves") or []),
                 help="Iterative solves inside the stress update. A model with "
                      "none has no internal Jacobian to extract.")

    helpers = analysis.get("helper_routines") or []
    st.caption("Helper routines: "
               + (", ".join(helpers) if helpers
                  else "none; the source is self-contained"))

    with st.expander("Details of the dependency closure"):
        for label, value in (
                ("Resolved from sibling files", analysis.get("external_files")),
                ("External library calls", analysis.get("external_library_calls")),
                ("Abaqus runtime routines", analysis.get("abaqus_runtime_calls"))):
            if not value:
                continue
            if isinstance(value, dict):
                value = [f"{k} ({v})" for k, v in value.items()]
            st.write(f"**{label}:** " + ", ".join(map(str, value)))
        dimensions = analysis.get("dimensions") or {}
        if dimensions.get("minimum_ntens"):
            st.write(f"**Smallest usable NTENS:** {dimensions['minimum_ntens']} "
                     "— the source writes that tensor index.")
        st.json(analysis, expanded=False)


# --------------------------------------------------------------------------- #
# Step 2 -- Material model
# --------------------------------------------------------------------------- #
def step_material(state: WizardState) -> None:
    st.subheader(step_titles()[1])
    st.caption(STEPS[1][1])

    origins = state.field_origins
    st.markdown("**Material constants**")
    st.caption("PROPS is the vector of constants the subroutine reads. Tick the "
               "ones you want derivatives with respect to; each ticked constant "
               "becomes one differentiation direction.")

    rows = _property_rows(state)
    edited = st.data_editor(
        rows, key="props_editor", width="stretch", hide_index=True,
        num_rows="dynamic", height=(len(rows) + 2) * 36,
        column_config={
            "PROPS index": st.column_config.NumberColumn(
                min_value=1, step=1, width="small",
                help="Position in the PROPS array the subroutine reads."),
            "Name": st.column_config.TextColumn(
                width="medium", help="Your label for this constant."),
            "Value": st.column_config.NumberColumn(format="%.6g"),
            "Differentiate": st.column_config.CheckboxColumn(
                width="small",
                help="Include this constant in the parameter sensitivities."),
        })
    state.props, state.parameters = _read_property_rows(edited)
    origin_note(origins.get("props", example_projects.USER),
                f"{len(state.props)} constants, "
                f"{len(state.parameters)} marked for differentiation")

    st.markdown("**State variables**")
    st.caption("STATEV holds whatever the model carries from one increment to "
               "the next, such as accumulated plastic strain.")
    state_rows = [{"STATEV index": index, "Name": name}
                  for index, name in enumerate(state.state_names, start=1)]
    edited_state = st.data_editor(
        state_rows or [{"STATEV index": 1, "Name": ""}], key="state_editor",
        width="stretch", hide_index=True, num_rows="dynamic",
        height=(max(len(state_rows), 1) + 2) * 36,
        column_config={
            "STATEV index": st.column_config.NumberColumn(min_value=1, step=1,
                                                          width="small"),
            "Name": st.column_config.TextColumn(width="medium")})
    state.state_names = tuple(
        str(row["Name"]).strip() for row in edited_state
        if str(row.get("Name") or "").strip())
    origin_note(origins.get("state_names", example_projects.USER))

    with st.expander("Advanced settings — tensor dimensions"):
        st.caption("These are read from the example's contract. Change them "
                   "only if you are driving the source differently.")
        columns = st.columns(4)
        state.ntens = int(columns[0].number_input(
            "NTENS", 1, 12, state.ntens, key="ntens",
            help="Number of stress components the subroutine works with."))
        state.ndi = int(columns[1].number_input(
            "NDI", 0, 6, state.ndi, key="ndi",
            help="How many of those are direct (normal) components."))
        state.nshr = int(columns[2].number_input(
            "NSHR", 0, 6, state.nshr, key="nshr",
            help="How many are shear components. NDI + NSHR must equal NTENS."))
        state.nstatv = int(columns[3].number_input(
            "NSTATV", 0, 400, state.nstatv, key="nstatv",
            help="Length of the state array the subroutine is given."))
        for field in ("ntens", "ndi", "nshr", "nstatv"):
            if origins.get(field) == example_projects.UNAVAILABLE:
                st.caption(f"`{field.upper()}` was not in the contract; the "
                           "value shown is a default, not a measurement.")

    blockers(state.material_problems(), "The material description is incomplete")
    navigate(1, forward_ok=state.material_complete())


def _property_rows(state: WizardState) -> list[dict]:
    differentiated = {index for _, index in state.parameters}
    names = {index: name for name, index in state.parameters}
    if not state.props:
        return [{"PROPS index": 1, "Name": "", "Value": 0.0,
                 "Differentiate": False}]
    return [{"PROPS index": index,
             "Name": names.get(index, f"P{index}"),
             "Value": float(value),
             "Differentiate": index in differentiated}
            for index, value in enumerate(state.props, start=1)]


def _read_property_rows(rows) -> tuple[tuple[float, ...], tuple[tuple[str, int], ...]]:
    """Turn the editor's table back into a PROPS vector and a name mapping.

    A row with no index is dropped rather than guessed at, and the vector is
    sized by the largest index present so a gap reads as a zero the user can
    see rather than shifting every later constant.
    """
    entries: list[tuple[int, str, float, bool]] = []
    for row in rows:
        try:
            index = int(row["PROPS index"])
        except (TypeError, ValueError, KeyError):
            continue
        if index < 1:
            continue
        try:
            value = float(row.get("Value") or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        entries.append((index, str(row.get("Name") or f"P{index}").strip(),
                        value, bool(row.get("Differentiate"))))
    if not entries:
        return (), ()
    size = max(index for index, _, _, _ in entries)
    props = [0.0] * size
    parameters: list[tuple[str, int]] = []
    for index, name, value, differentiate in sorted(entries):
        props[index - 1] = value
        if differentiate and name:
            parameters.append((name, index))
    return tuple(props), tuple(parameters)


# --------------------------------------------------------------------------- #
# Step 3 -- Derivatives and loading
# --------------------------------------------------------------------------- #
def step_request(state: WizardState) -> None:
    st.subheader(step_titles()[2])
    st.caption(STEPS[2][1])

    st.markdown("**What should be computed?**")
    chosen: list[str] = []
    for product in PRODUCTS:
        label, api = PRODUCT_LABELS[product]
        default = product in (state.products or ("DSIGMA_DP",))
        if st.checkbox(f"{label}  ·  `{api}`", value=default,
                       key=f"product_{product}", help=PRODUCT_HELP[product]):
            chosen.append(product)
    state.products = tuple(chosen)

    if "HIGHER_ORDER_STRESS" in state.products:
        state.higher_order_max = int(st.slider(
            "Highest stress-derivative order", 2, 4, state.higher_order_max,
            key="higher_order_max",
            help="Order 1 is the tangent itself; 2 and above are curvature."))

    st.markdown("**How should the material be loaded?**")
    label = st.selectbox(
        "Loading history", list(LOADING_PRESETS), key="loading_choice",
        help="The strain path the material point is driven along. Derivatives "
             "are reported at every increment of it.")
    state.loading_label = label
    preset = LOADING_PRESETS[label]
    st.caption(preset["explains"])
    st.caption(f"{preset['increments']} increments · provenance: "
               f"{preset['provenance']}")

    requirements = state.requirements()
    if requirements:
        st.markdown("**Before you run**")
        for requirement in requirements:
            st.markdown(
                f"{badge(requirement.word)} &nbsp; **"
                f"{PRODUCT_LABELS[requirement.product][0]}** — "
                f"{requirement.reason}", unsafe_allow_html=True)
        remaining = state.supported_products()
        if remaining:
            st.caption("The rest of the request can still run: "
                       + ", ".join(PRODUCT_LABELS[p][0] for p in remaining))
        else:
            st.caption("Nothing in this request can be produced. Choose another "
                       "product, or another source.")

    blockers(state.request_problems(), "This request cannot run yet")
    navigate(2, forward_ok=state.request_complete(), forward_label="Review and run")


# --------------------------------------------------------------------------- #
# Step 4 -- Run and results
# --------------------------------------------------------------------------- #
def step_run(state: WizardState) -> None:
    st.subheader(step_titles()[3])
    st.caption(STEPS[3][1])

    request = _build_request(state)
    problems = state.blocking_problems() + (request.validate() if request else
                                            ["The request could not be built."])

    _run_summary(state, request)

    if problems:
        st.error("**Run is unavailable until these are fixed**\n\n"
                 + "\n".join(f"- {problem}" for problem in problems))
    ready = not problems
    already = st.session_state.get("result") is not None
    label = "Run again" if already else "Run the pipeline"
    if st.button(label, type="secondary" if already else "primary",
                 disabled=not ready, key="run_button"):
        work = Path(tempfile.mkdtemp(prefix="umat_oti_run_"))
        with st.spinner("Transforming, compiling both builds, executing and "
                        "comparing…"):
            st.session_state["result"] = run_workbench(request, work)
        st.rerun()

    result = st.session_state.get("result")
    if result is None:
        st.info("Nothing has been run yet. No status on this page is a claim "
                "until the pipeline has completed.")
        navigate(3, forward_ok=False)
        return

    render_results(result, state)
    navigate(3, forward_ok=False)


def _build_request(state: WizardState) -> Optional[WorkbenchRequest]:
    if state.source_path is None:
        return None
    preset = LOADING_PRESETS.get(state.loading_label)
    if preset is None:
        return None
    loading = LoadingHistory(
        dstran_per_increment=preset["dstran"], n_increments=preset["increments"],
        deformation_gradient_increment=preset["gradient"],
        label=state.loading_label, provenance=preset["provenance"])
    return WorkbenchRequest(
        name=state.source_key or Path(state.source_path).stem,
        source_path=Path(state.source_path),
        dependency_roots=tuple(state.dependency_roots),
        ntens=state.ntens, nstatv=state.nstatv, ndi=state.ndi, nshr=state.nshr,
        props=tuple(state.props), parameters=tuple(state.parameters),
        state_names=tuple(state.state_names), loading=loading,
        products=tuple(state.products),
        higher_order_max=state.higher_order_max)


def _run_summary(state: WizardState, request) -> None:
    st.markdown("**Run summary**")
    left, right = st.columns(2)
    with left:
        st.write(f"**Source** · `{state.source_key or 'uploaded file'}`")
        st.write("**Products** · " + (", ".join(
            PRODUCT_LABELS[p][0] for p in state.products) or "none selected"))
    with right:
        st.write(f"**Loading** · {state.loading_label or 'none selected'}")
        st.write("**Execution** · offline material point, both builds compiled "
                 "here")
    result = st.session_state.get("result")
    if result is not None:
        word, detail = _overall_outcome(result)
        st.markdown(f"**Overall** · {badge(word)} &nbsp; {detail}",
                    unsafe_allow_html=True)


def _overall_outcome(result) -> tuple[str, str]:
    """One word for the whole run, and what it rests on.

    A run is only PASS when every requested product was verified. One product
    that could not be adjudicated makes the run PARTIAL rather than passing on
    the strength of the others.
    """
    requested = [o for o in result.products.values()
                 if o.status != "not_requested"]
    if not requested:
        return "NOT REQUESTED", "no product was asked for"
    words = [status_word(o.status) for o in requested]
    verified = sum(1 for w in words if w == "PASS")
    if any(w == "FAILED" for w in words):
        return "FAILED", "at least one product disagreed with its reference"
    if verified == len(requested):
        return "PASS", f"all {verified} requested products verified"
    if verified:
        return "PARTIAL", (f"{verified} of {len(requested)} requested products "
                           "verified; the rest are reported with their reason")
    return "BLOCKED", "no requested product reached a numerical comparison"


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
#: Reader-facing name for each pipeline stage, so the table does not require a
#: reader to know the internal identifiers.
STAGE_LABELS: dict[str, str] = {
    "discovered": "Source located",
    "license_classified": "Licence classified",
    "entry_detected": "Entry routine detected",
    "dependencies_resolved": "Dependencies resolved",
    "contract_constructed": "Request checked against the source",
    "original_compiled": "Original build compiled",
    "transformed": "Source transformed",
    "generated_compiled": "Transformed build compiled",
    "original_executed": "Original build executed",
    "transformed_executed": "Transformed build executed",
    "primal_parity": "Stress and state agree between builds",
    "reference_resolved": "Independent reference resolved",
    "derivatives_verified": "Derivatives compared",
}


def render_results(result, state: Optional[WizardState] = None) -> None:
    """The evidence, ordered so the conclusion comes before the detail.

    The two blocks carry keys because they are the two regions a publication
    figure photographs. Naming them here means a screenshot is a region of the
    interface rather than a rectangle chosen with a ruler.
    """
    st.divider()
    with st.container(key="results_summary"):
        st.markdown("### Results")
        _pipeline_table(result)
        _primal_parity(result)
    with st.container(key="results_products"):
        _product_tabs(result)
    _downloads_and_provenance(result, state)
    _diagnostics(result)


def _pipeline_table(result) -> None:
    st.markdown("**Pipeline stages**")
    stages = result.stages or {}
    if not stages:
        st.caption("No stage was recorded.")
        return
    rows = []
    for name, entry in stages.items():
        detail = entry if isinstance(entry, dict) else {}
        status = detail.get("status", "unknown")
        rows.append({
            "Stage": STAGE_LABELS.get(name, name.replace("_", " ")),
            "Outcome": "succeeded" if status == "succeeded" else status,
            "Seconds": detail.get("seconds"),
            "Note": (detail.get("reason") or "")[:110],
            "Identifier": name,
        })
    # A column of empty strings costs the width that pushed the identifier off
    # the right edge. It appears when there is something to say.
    if not any(row["Note"] for row in rows):
        rows = [{k: v for k, v in row.items() if k != "Note"} for row in rows]
    # Tall enough for every stage. Left to itself the table scrolls inside
    # itself, and a screenshot of it then shows a run that stopped halfway.
    st.dataframe(rows, width="stretch", hide_index=True,
                 height=(len(rows) + 1) * 36 + 12,
                 column_config={
                     "Seconds": st.column_config.NumberColumn(
                         format="%.2f", width="small",
                         help="Wall clock spent in this stage."),
                     "Stage": st.column_config.TextColumn(width="medium"),
                     "Identifier": st.column_config.TextColumn(
                         width="medium",
                         help="The name this stage carries in the evidence "
                              "files, for cross-reference.")})
    reached = result.furthest_stage
    if reached:
        st.caption(f"Furthest stage reached: {STAGE_LABELS.get(reached, reached)}")


def _primal_parity(result) -> None:
    st.markdown("**Do the two builds agree before any derivative is compared?**")
    parity = result.primal_parity or {}
    if parity.get("status") == "succeeded":
        # The funnel records this as worst_relative_difference. Reading a
        # shorter name meant the number never printed and the sentence claimed
        # agreement without saying how close.
        worst = parity.get("worst_relative_difference",
                           parity.get("worst_relative"))
        detail = (f" Worst relative difference {worst:.3e}."
                  if isinstance(worst, (int, float)) else "")
        st.markdown(
            f"{badge('PASS')} &nbsp; Stress and state agree between the "
            f"independently compiled original and transformed builds.{detail} "
            "The derivative comparisons below are therefore between comparable "
            "quantities.", unsafe_allow_html=True)
    elif parity:
        st.markdown(
            f"{badge('FAILED')} &nbsp; The two builds disagree on stress or "
            f"state, so no derivative comparison below can be trusted. "
            f"{parity.get('reason', '')}", unsafe_allow_html=True)
    else:
        st.markdown(f"{badge('BLOCKED')} &nbsp; The run stopped before parity "
                    "could be checked.", unsafe_allow_html=True)


#: Which outcome has most to show a reader, most first.
_INFORMATIVENESS = {"verified": 0, "partial": 1, "failed": 2, "unresolved": 3,
                    "unsupported": 4, "blocked": 5, "compiled": 5,
                    "not_requested": 6}


def _product_tabs(result) -> None:
    st.markdown("**Derivative products**")
    # Ordered by how much each card has to say, so the section opens on a
    # result rather than on a product nobody asked for. Schema order opened it
    # on "not requested", which is the least informative card there is.
    present = [p for p in PRODUCTS if p in result.products]
    products = sorted(present, key=lambda name: (
        _INFORMATIVENESS.get(result.products[name].status, 99),
        PRODUCTS.index(name)))
    if not products:
        st.caption("No product was evaluated.")
        return
    # Short names: five full ones do not fit a narrow window, and a tab strip
    # that overflows takes the whole page sideways with it.
    tabs = st.tabs([PRODUCT_TABS[p] for p in products])
    for tab, product in zip(tabs, products):
        with tab:
            _product_card(result.products[product])


def _product_card(outcome) -> None:
    word = status_word(outcome.status)
    label, api = PRODUCT_LABELS.get(outcome.product,
                                    (outcome.product, outcome.product))
    st.markdown(f"{badge(word)} &nbsp; **{label}** · `{api}`",
                unsafe_allow_html=True)
    meaning = STATUS_MEANINGS.get(word, "")
    st.write(meaning)
    # Only when it adds something. A reason that restates the meaning printed
    # the same sentence twice, once in prose and once in a coloured box.
    reason = (outcome.reason or "").strip()
    if reason and reason.rstrip(".").lower() not in meaning.rstrip(".").lower():
        st.info(reason)

    detail = outcome.detail or {}
    if not detail:
        return
    numbers = [(k, v) for k, v in detail.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if numbers:
        columns = st.columns(min(4, len(numbers)))
        for column, (key, value) in zip(columns, numbers[:4]):
            column.metric(key.replace("_", " "),
                          f"{value:.3e}" if isinstance(value, float)
                          and abs(value) and abs(value) < 1e-3 else f"{value}")
    method = detail.get("reference_method")
    if method:
        st.caption(f"Validation method: {method}")
    with st.expander("All reported numbers for this product"):
        st.json(detail, expanded=False)


def _downloads_and_provenance(result, state) -> None:
    artifacts = result.artifacts or {}
    with st.expander(f"Downloads and provenance ({len(artifacts)} artefacts)"):
        _downloads(result, state, artifacts)


def _downloads(result, state, artifacts) -> None:
    """The artefacts, then where they came from."""
    if artifacts:
        names = sorted(artifacts)
        columns = st.columns(min(2, len(names)))
        for index, name in enumerate(names):
            path = Path(artifacts[name])
            if not path.is_file():
                continue
            with columns[index % len(columns)]:
                st.download_button(
                    f"{name.replace('_', ' ')}", path.read_bytes(),
                    file_name=path.name, key=f"download_{name}",
                    width="stretch")
    else:
        st.caption("This run produced no downloadable artefact.")

    st.divider()
    st.write("Every number above was produced by "
             "`umat_oti.services.workbench.run_workbench`, the same entry "
             "point the command line and the published rounds use.")
    if state is not None:
        st.write(f"**Source** · `{state.source_key}`")
        st.write(f"**Loading history** · {state.loading_label}")
    st.json({"comparison": result.comparison,
             "furthest_stage": result.furthest_stage}, expanded=False)


def _diagnostics(result) -> None:
    with st.expander("Diagnostics (developer detail)"):
        st.caption("Stage records and raw result manifest. Nothing here is a "
                   "scientific claim; it is what the run did.")
        st.json(result.as_dict() if hasattr(result, "as_dict") else {},
                expanded=False)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(page_title="UMAT-OTI workbench", layout="centered")
    st.markdown(STYLE, unsafe_allow_html=True)
    st.title("UMAT-OTI workbench")
    st.caption("Generate and verify derivatives of an Abaqus UMAT, without "
               "editing the subroutine.")

    state = _state()
    furthest = state.furthest_ready_step()
    current = min(int(st.session_state.get("step", 0)), furthest)
    st.session_state["step"] = current
    progress_bar(current, furthest)
    if current > 0:
        context_strip(state)

    (step_source, step_material, step_request, step_run)[current](state)


if __name__ == "__main__":
    main()
