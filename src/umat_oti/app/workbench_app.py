"""Streamlit front end for the UMAT-OTI workbench.

This module renders. It builds a :class:`WorkbenchRequest` from the widgets,
hands it to :func:`run_workbench`, and displays what comes back. There is no
numerical logic here and no tolerance: the interface a user drives and the
pipeline the paper cites are the same code, which is what makes a screenshot of
this page evidence rather than decoration.

Two display rules are load-bearing:

* primal parity is shown *before* any derivative status, because a derivative
  computed by two builds that disagree on stress is not a comparable quantity;
* ``compiled`` is rendered as its own outcome and never as success. A product
  that transformed and built has had nothing checked numerically.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from umat_oti.services.workbench import (
    OUTCOMES, PRODUCTS, LoadingHistory, WorkbenchRequest, analyse_source,
    run_workbench,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "parameter_sensitivity" / "models"

#: How each outcome is presented. Colour is never the only signal: every badge
#: carries its word, so the meaning survives a greyscale print and a colourblind
#: reader.
OUTCOME_BADGES: dict[str, tuple[str, str]] = {
    "verified": ("PASS", "Checked numerically against an independent reference"),
    "compiled": ("BUILT", "Transformed and compiled. Nothing verified yet"),
    "failed": ("FAIL", "Disagreed with a reference that could resolve it"),
    "unresolved": ("UNRESOLVED", "The reference could not adjudicate this"),
    "blocked": ("BLOCKED", "An earlier gate stopped this product"),
    "unsupported": ("UNSUPPORTED", "Not applicable to this source or request"),
    "not_requested": ("NOT REQUESTED", "This product was not asked for"),
}

LOADING_PRESETS: dict[str, dict[str, Any]] = {
    "Uniaxial strain, 20 x 1e-4 (small strain)": {
        "dstran": (1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        "increments": 20, "gradient": (),
        "provenance": "parameter_sensitivity/loading_paths.json default",
    },
    "Uniaxial strain, 10 x 1e-4 (small strain)": {
        "dstran": (1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        "increments": 10, "gradient": (),
        "provenance": "declared in the interface",
    },
    "Uniaxial stretch, 10 x 1e-3 (finite strain)": {
        "dstran": (0.0,) * 6, "increments": 10,
        "gradient": (1.0e-3, 0, 0, 0, 0, 0, 0, 0, 0),
        "provenance": "declared in the interface; drives DFGRD directly",
    },
}


def _example_sources() -> dict[str, Path]:
    if not EXAMPLES.is_dir():
        return {}
    return {d.name: d / "umat.for" for d in sorted(EXAMPLES.iterdir())
            if (d / "umat.for").is_file()}


def _state(key: str, default: Any) -> Any:
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def render_source_selection() -> tuple[Optional[Path], tuple[Path, ...]]:
    """Entry source and dependency roots."""
    st.subheader("1. Source and dependencies")
    examples = _example_sources()
    choices = ["(upload a file)"] + list(examples)
    picked = st.selectbox("UMAT entry source", choices, key="source_choice")

    source: Optional[Path] = None
    if picked != "(upload a file)":
        source = examples[picked]
        st.caption(f"Example project: `parameter_sensitivity/models/{picked}/umat.for`")
    else:
        uploaded = st.file_uploader("Upload a UMAT source",
                                    type=["f", "for", "f90", "f77"],
                                    key="source_upload")
        if uploaded is not None:
            scratch = Path(tempfile.mkdtemp(prefix="umat_oti_gui_"))
            source = scratch / uploaded.name
            source.write_bytes(uploaded.getvalue())

    roots_text = st.text_input(
        "Dependency / include roots (one per line, blank for none)",
        value=st.session_state.get("roots_text", ""), key="roots_text",
        help="Directories searched for helper routines the entry source calls "
             "but does not define.")
    roots = tuple(Path(line.strip()) for line in roots_text.splitlines()
                  if line.strip())
    if source is not None and not roots:
        roots = (source.parent,)
    return source, roots


def render_analysis(source: Path, roots: tuple[Path, ...]) -> dict:
    """Show what the source is before anything is transformed."""
    st.subheader("2. Detected source information")
    analysis = analyse_source(source, roots)
    st.session_state["analysis"] = analysis

    left, middle, right = st.columns(3)
    left.metric("Source form", analysis.get("source_form", "?"))
    middle.metric("Routines in closure", analysis.get("closure_size", 0))
    right.metric("Local Newton solves", len(analysis.get("local_solves") or []))

    if analysis.get("dependency_error"):
        st.error(f"Dependency resolution failed: {analysis['dependency_error']}")
        return analysis

    helpers = analysis.get("helper_routines") or []
    st.write(f"**Helper routines detected:** "
             f"{', '.join(helpers) if helpers else 'none; the source is self-contained'}")
    if analysis.get("external_files"):
        st.write("**Resolved from sibling files:** "
                 + ", ".join(analysis["external_files"]))
    if analysis.get("missing_symbols"):
        st.error("Unresolved symbols: "
                 + ", ".join(m["symbol"] for m in analysis["missing_symbols"]))
    if analysis.get("ambiguous_symbols"):
        st.warning("Helpers with differing definitions and no local copy: "
                   + ", ".join(analysis["ambiguous_symbols"]))
    if analysis.get("external_library_calls"):
        st.info("External library calls: "
                + ", ".join(f"{k} ({v})"
                            for k, v in analysis["external_library_calls"].items()))
    if analysis.get("abaqus_runtime_calls"):
        st.info("Abaqus runtime routines: "
                + ", ".join(analysis["abaqus_runtime_calls"]))

    dimensions = analysis.get("dimensions") or {}
    if dimensions.get("minimum_ntens"):
        st.caption(f"This source writes tensor index "
                   f"{dimensions['minimum_ntens']}, so NTENS must be at least that.")
    return analysis


def render_dimensions_and_mapping(analysis: dict) -> dict:
    """Tensor and state dimensions, PROPS mapping, state names."""
    st.subheader("3. Dimensions, properties and state")
    columns = st.columns(4)
    ntens = columns[0].number_input("NTENS", 1, 12, _state("ntens", 6), key="ntens")
    ndi = columns[1].number_input("NDI", 1, 6, _state("ndi", 3), key="ndi")
    nshr = columns[2].number_input("NSHR", 0, 6, _state("nshr", 3), key="nshr")
    nstatv = columns[3].number_input("NSTATV", 0, 400, _state("nstatv", 1),
                                     key="nstatv")

    props_text = st.text_area(
        "Material properties, one per line, in PROPS order",
        value=st.session_state.get("props_text", "200000\n0.3\n250\n2000"),
        key="props_text", height=150)
    props: list[float] = []
    bad: list[str] = []
    for line in props_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            props.append(float(line))
        except ValueError:
            bad.append(line)
    if bad:
        st.error("These property values are not numbers: " + ", ".join(bad))

    mapping_text = st.text_area(
        "Differentiated parameters, one per line as name=PROPS index",
        value=st.session_state.get("mapping_text", "E=1\nnu=2\nsy0=3\nH=4"),
        key="mapping_text", height=150,
        help="Each named parameter becomes an OTI direction.")
    parameters: list[tuple[str, int]] = []
    for line in mapping_text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        name, _, index = line.partition("=")
        try:
            parameters.append((name.strip(), int(index.strip())))
        except ValueError:
            st.error(f"Cannot read a PROPS index from {line!r}")

    state_text = st.text_area(
        "State variable names, one per line, in STATEV order",
        value=st.session_state.get("state_text", "EQPLAS"),
        key="state_text", height=110)
    state_names = tuple(line.strip() for line in state_text.splitlines()
                        if line.strip())
    return {"ntens": int(ntens), "ndi": int(ndi), "nshr": int(nshr),
            "nstatv": int(nstatv), "props": tuple(props),
            "parameters": tuple(parameters), "state_names": state_names}


def render_products_and_loading() -> tuple[tuple[str, ...], LoadingHistory]:
    st.subheader("4. Derivative products and loading history")
    left, right = st.columns(2)
    with left:
        st.markdown("**Requested products**")
        chosen = [product for product in PRODUCTS
                  if st.checkbox(product, value=(product in ("DSIGMA_DP",)),
                                 key=f"product_{product}")]
        order = st.slider("Highest stress-derivative order", 1, 4,
                          _state("higher_order_max", 4), key="higher_order_max")
    with right:
        st.markdown("**Loading history**")
        label = st.selectbox("Supplied loading history", list(LOADING_PRESETS),
                             key="loading_choice")
        preset = LOADING_PRESETS[label]
        st.caption(f"Provenance: {preset['provenance']}")
        st.caption(f"{preset['increments']} increments"
                   + (", deformation-gradient driven" if preset["gradient"] else ""))
    loading = LoadingHistory(
        dstran_per_increment=preset["dstran"],
        n_increments=preset["increments"],
        deformation_gradient_increment=preset["gradient"],
        label=label, provenance=preset["provenance"])
    return tuple(chosen), loading


def render_outcome_badge(outcome) -> None:
    word, meaning = OUTCOME_BADGES.get(outcome.status, (outcome.status.upper(), ""))
    st.markdown(f"**{outcome.product}** — `{word}`  \n{meaning}")
    if outcome.reason:
        st.caption(outcome.reason)


def render_results(result) -> None:
    """Primal parity first, then derivatives, then artifacts."""
    st.subheader("6. Results")
    if result.errors:
        for problem in result.errors:
            st.error(problem)
        return

    st.markdown("### Pipeline stages")
    for name, stage in result.stages.items():
        status = stage.get("status", "?")
        st.write(f"- `{name}`: **{status}**"
                 + (f" — {stage['reason']}" if stage.get("reason") else ""))

    st.markdown("### Primal parity")
    parity = result.primal_parity or {}
    if parity.get("status") == "succeeded":
        st.success(
            "Stress and state agree between the independently compiled original "
            "and transformed builds (worst relative difference "
            f"{parity.get('worst_relative_difference'):.3e}). Derivative "
            "comparisons below are therefore between comparable quantities.")
    elif parity:
        st.error(f"Primal parity {parity.get('status')}: {parity.get('reason')}")
    else:
        st.warning("The run did not reach the primal-parity check, so no "
                   "derivative below has been verified.")

    st.markdown("### Derivative products")
    for _name, outcome in sorted(result.products.items()):
        render_outcome_badge(outcome)

    if result.comparison:
        st.markdown("### Comparison summary")
        st.json(result.comparison)

    st.markdown("### Artifacts")
    if not result.artifacts:
        st.caption("No artifacts were produced.")
    for name, path in sorted(result.artifacts.items()):
        candidate = Path(path)
        if not candidate.is_file():
            continue
        st.download_button(f"Download {name} ({candidate.name})",
                           data=candidate.read_bytes(), file_name=candidate.name,
                           key=f"download_{name}")


def main() -> None:
    st.set_page_config(page_title="UMAT-OTI workbench", layout="wide")
    st.title("UMAT-OTI workbench")
    st.caption(
        "Transform an Abaqus UMAT, build both implementations independently, "
        "run them over the same loading history, and check the derivatives "
        "against a reference. This page runs the same backend as the command "
        "line and the batch pipeline.")

    source, roots = render_source_selection()
    if source is None:
        st.info("Select an example project or upload a UMAT source to begin.")
        return

    analysis = render_analysis(source, roots)
    dimensions = render_dimensions_and_mapping(analysis)
    products, loading = render_products_and_loading()

    st.subheader("5. Run")
    if not st.button("Analyze, transform, build and verify", key="run_button"):
        st.caption("Nothing has been run yet. No result on this page is a claim "
                   "until this button has completed.")
        return

    request = WorkbenchRequest(
        name=source.stem or "request", source_path=source,
        dependency_roots=roots, products=products, loading=loading,
        higher_order_max=int(st.session_state.get("higher_order_max", 4)),
        **dimensions)
    problems = request.validate()
    if problems:
        for problem in problems:
            st.error(problem)
        return

    work = Path(tempfile.mkdtemp(prefix="umat_oti_run_"))
    with st.spinner("Running the pipeline..."):
        result = run_workbench(request, work)
    st.session_state["result"] = result.as_dict()
    render_results(result)


if __name__ == "__main__":
    main()
