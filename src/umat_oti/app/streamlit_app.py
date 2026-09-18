"""UMAT-OTI Streamlit GUI.

A guided workflow that drives the same service the CLI and the batch driver
use (:func:`umat_oti.services.transformation.run_transformation`), so nothing
on these screens is a second implementation of the transformation:

  0. Start here         - what the tool does, and a demo that runs end to end
  1. Load Config        - pick a JSON contract from the repository or upload one
  2. Transform          - rewrite the UMAT so DDSDDE comes from OTI arithmetic
  3. Validate           - build the workspace, run both Abaqus jobs, extract ODB
  4. Constitutive Jac.  - per-contract Original vs OTIS tables + line plots
  5. Report             - status panel, downloadable artifacts, raw JSON browse
  6. Corpus             - every acquired UMAT and how far it got

Steps 0-2 need only ``gfortran``. Step 3 onwards needs Abaqus. The interface
says which of those it can find rather than failing halfway through a run.

Start it with::

    streamlit run scripts/app.py
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import streamlit as st

from umat_oti.app.derivative_editor import (
    DERIVATIVE_KINDS,
    build_unified_config,
    mapping_editor_rows,
    request_editor_rows,
)
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.core.config_loader import load_project_config_json
from umat_oti.core.derivative_request import DerivativeRequestError
from umat_oti.validation.abaqus_runner import (
    extract_results,
    run_both_jobs,
)
from umat_oti.validation.compare_results import compare_validation_results
from umat_oti.validation.job_builder import (
    DEFAULT_ABAQUS_MODULES,
    DEFAULT_ABAQUS_RUN_PREFIX,
    build_validation_workspace,
)


# ----------------------------------------------------------------------------
# Path discovery
# ----------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


WORKSPACE_ROOT = _repo_root() / "umat_oti_workspace"

#: Where contracts live, in the order a newcomer should meet them. Each entry
#: is (directory, what it is). The old single ``json_files_completed/``
#: directory is kept last so an existing checkout that still has one keeps
#: working, but it is not what ships.
CONFIG_SOURCES: list[tuple[Path, str]] = [
    (_repo_root() / "examples", "curated examples - start here"),
    (_repo_root() / "json_files", "benchmark contracts used in the paper"),
    (_repo_root() / "user_jsons", "your own contracts"),
    (_repo_root() / "json_files_completed", "legacy completed configs"),
]

#: Kept because the sidebar used to print it; it now points at the first
#: directory that actually exists, so the caption cannot name an empty path.
COMPLETED_JSON_DIR = next(
    (path for path, _ in CONFIG_SOURCES if path.is_dir()), CONFIG_SOURCES[0][0])

#: The contract the "Start here" demo drives. Its source is the smallest
#: of the shipped examples (94 lines, linear elastic, NTENS 4, order 1)
#: and it ships with the checkout, so the demo needs no setup.
DEMO_CONFIG = _repo_root() / "examples" / "elastic_minimal.json"

#: The same contract as the picker on tab 1 labels it, so a config loaded by a
#: shortcut and one loaded from the dropdown are the same entry, not two.
DEMO_LABEL = f"{DEMO_CONFIG.parent.name}/{DEMO_CONFIG.name}"

_CHOOSE = "(choose...)"

#: Files in a config directory that are not contracts.
_NOT_CONFIGS = {"completion_report.json"}


# ----------------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "config": None,
    "config_path": "",
    "config_label": "",
    "transform_dir": "",
    "transformed_umat": "",
    "transform_report": None,
    "transform_summary": None,
    "validation_dir": "",
    "build_result": None,
    "run_result": None,
    "extract_result": None,
    "compare_result": None,
    "material_test_mode": "single element plastic tension",
    "abaqus_command": "abaqus",
    "abaqus_modules": DEFAULT_ABAQUS_MODULES,
    "abaqus_run_prefix": DEFAULT_ABAQUS_RUN_PREFIX,
    "compare_outputs": ["STRESS", "STATEV", "DDSDDE", "CONSTITUTIVE_JACOBIANS", "CONVERGENCE"],
    "presentation_label": "",
    "demo_exit": None,
}


def _init_state() -> None:
    for key, value in _DEFAULTS.items():
        st.session_state.setdefault(key, value)


def _clear_downstream() -> None:
    """Loading a new config invalidates everything computed from the old one."""
    for key in ("transformed_umat", "transform_dir", "validation_dir"):
        st.session_state[key] = ""
    for key in ("transform_report", "transform_summary", "build_result",
                "run_result", "extract_result", "compare_result"):
        st.session_state[key] = None


# ----------------------------------------------------------------------------
# External software
# ----------------------------------------------------------------------------

def _tool(name: str) -> str | None:
    """Where an external program is, or None. Never a guess."""
    return shutil.which(name)


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

@dataclass
class _ConfigSummary:
    name: str
    selected_umat_file: str
    selected_umat: str
    ntens: int
    order: int
    contracts: list[dict[str, Any]]
    helper_surfaces: list[dict[str, Any]]


def _summarize_config(cfg: dict[str, Any]) -> _ConfigSummary:
    project = cfg.get("project") or {}
    source = cfg.get("source") or {}
    ts = cfg.get("transformation_settings") or {}
    contracts = cfg.get("extra_jacobian_contracts") or []
    return _ConfigSummary(
        name=str(project.get("name") or "unnamed"),
        selected_umat_file=str(source.get("selected_umat_file") or ""),
        selected_umat=str(source.get("selected_umat_name") or source.get("detected_umat_name") or "UMAT"),
        ntens=int(ts.get("ntens") or 0),
        order=int(ts.get("order") or 1),
        contracts=list(contracts),
        helper_surfaces=list(cfg.get("helper_output_surfaces") or []),
    )


def _find_existing_transformed(umat_name: str) -> Path | None:
    """Return the most recent transformed UMAT already present in the workspace.

    The generator names the file after the routine and keeps the source file's
    own extension, which is ``.f`` for the fixed-form sources that ship here
    and ``.for`` for others - so both have to be looked for.
    """
    if not umat_name:
        return None
    matches = [p for pattern in (f"*/oti_transform/{umat_name}/{umat_name}_oti.f",
                                 f"*/oti_transform/{umat_name}/{umat_name}_oti.for")
               for p in WORKSPACE_ROOT.glob(pattern)]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _transformed_from_summary(summary: dict[str, Any], out_dir: Path) -> str:
    """The transformed subroutine the service just wrote.

    The service reports the path itself; globbing for it is a guess that was
    wrong for every ``.f`` source in this repository. The glob is kept only as
    a fallback for a summary that predates the field.
    """
    reported = str(summary.get("transformed_source") or "")
    if reported and Path(reported).is_file():
        return reported
    produced = sorted(out_dir.glob("*_oti.f")) + sorted(out_dir.glob("*_oti.for"))
    return str(produced[0]) if produced else ""


def _list_configs() -> list[tuple[str, Path]]:
    """Every contract on disk, labelled by the directory it came from."""
    found: list[tuple[str, Path]] = []
    for directory, _ in CONFIG_SOURCES:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            if path.name in _NOT_CONFIGS:
                continue
            found.append((f"{directory.name}/{path.name}", path))
    return found


def _load_config(path: Path) -> tuple[dict[str, Any] | None, str]:
    """Load a contract, returning the error text instead of raising it.

    ``templates/`` skeletons and half-finished user contracts legitimately
    fail to load. That is an answer, and it belongs on the screen rather than
    in a traceback that replaces the whole app.
    """
    try:
        return load_project_config_json(path.read_bytes(), origin_path=path), ""
    except Exception as exc:  # noqa: BLE001 - shown to the user, never raised
        return None, f"{type(exc).__name__}: {exc}"


def _read_json(path: Any) -> dict[str, Any] | None:
    if not isinstance(path, (str, Path)) or not str(path):
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _tail(text: str, n: int = 30) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _status_badge(status: str | None) -> str:
    if not status:
        return ":grey[unknown]"
    s = status.lower()
    if s in {"completed", "passed", "ok", "compiled"}:
        return f":green[{status}]"
    if s in {"failed", "timeout", "error"}:
        return f":red[{status}]"
    if s in {"not_run", "configured", "not_requested"}:
        return f":grey[{status}]"
    return f":orange[{status}]"


def _download(path: Any, label: str, key: str) -> None:
    """Offer a produced artefact, only once it exists.

    Takes whatever the summary held: a path, a dict that carries one under
    ``source``/``path``, or nothing. A missing artefact is silence, not an
    error - the button simply is not drawn.
    """
    if isinstance(path, dict):
        path = path.get("source") or path.get("path") or ""
    if not isinstance(path, (str, Path)) or not str(path):
        return
    p = Path(path)
    if not p.is_file():
        return
    st.download_button(f"{label}  ({p.stat().st_size:,} bytes)",
                       data=p.read_bytes(), file_name=p.name, key=f"dl_{key}")


def _semantic_summary(checks: dict[str, Any] | None) -> tuple[int, int, list[str]]:
    """(passed, total, names that failed) for the generator's own checks."""
    if not isinstance(checks, dict) or not checks:
        return 0, 0, []
    failed = [name for name, ok in checks.items() if not ok]
    return len(checks) - len(failed), len(checks), failed


#: What each ``status_category`` from services/transformation.py means, and
#: what to do next. A category with no entry here is shown verbatim rather
#: than paraphrased into something the service did not say.
_OUTCOME_ADVICE: dict[str, str] = {
    "source_not_found": (
        "The contract names a UMAT source that is not on this machine. Fix "
        "`source.selected_umat_file` in the JSON, or put the file where it "
        "points."),
    "needs_json_completion": (
        "The contract is missing information the transform needs - it stopped "
        "before writing anything rather than guessing. Complete the JSON and "
        "load it again."),
    "invalid_derivative_request": (
        "One of the derivative requests is not well formed. Open **Advanced: "
        "edit the derivative requests** on tab 1 and check the kind, order and "
        "variable of each row."),
    "invalid_parameter_sensitivity_contract": (
        "A parameter-sensitivity request does not line up with the PROPS map. "
        "Check the parameter index -> name table on tab 1."),
    "transform_blocked": (
        "The generator refused this source: it could not do the rewrite "
        "soundly. The blockers below say which construct stopped it."),
    "transform_failed": (
        "The transform ran and did not produce a usable result. The report "
        "below is the whole record of what it tried."),
    "succeeded_semantic_check_warnings": (
        "Code was generated, but one of the generator's own structural checks "
        "on that code did not pass. Treat the output as unverified until you "
        "know why."),
    "succeeded_with_warnings": (
        "Code was generated, with warnings - typically a helper routine passed "
        "through instead of being OTI-lifted, which means derivatives that "
        "flow through it may be approximate. Read the warnings before using "
        "the result."),
}


def _explain_outcome(summary: dict[str, Any], code: int) -> None:
    """Say what the exit code was about, in the service's own terms."""
    category = str(summary.get("status_category") or "")
    if code == 0 and category in ("", "succeeded"):
        return
    advice = _OUTCOME_ADVICE.get(category)
    head = f"`{category}`" if category else f"exit code {code}"
    body = f"**{head}** - {advice}" if advice else f"**{head}**"
    (st.warning if code == 0 else st.error)(body)
    for field in ("error", "errors"):
        value = summary.get(field)
        if isinstance(value, str) and value:
            st.code(value, language="text")
        elif isinstance(value, list) and value:
            for item in value:
                st.markdown(f"- {item}")


def _run_transform(cfg: dict[str, Any], out_dir: Path,
                   compile_it: bool) -> tuple[dict[str, Any], int]:
    """One transformation, through the one service every front end uses."""
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / "gui_unified_config.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return run_transformation(
        config_path, out_dir,
        TransformationOptions(compile_generated=compile_it))


def _store_transform(summary: dict[str, Any], out_dir: Path) -> None:
    st.session_state.transform_dir = str(out_dir)
    st.session_state.transform_summary = summary
    st.session_state.transform_report = _read_json(summary.get("report_path", "")) or summary
    st.session_state.transformed_umat = _transformed_from_summary(summary, out_dir)


# ----------------------------------------------------------------------------
# Progress
# ----------------------------------------------------------------------------

def _progress() -> list[tuple[bool, str]]:
    """Which steps have really happened, read off the artefacts themselves."""
    report = st.session_state.transform_report or {}
    compilation = (st.session_state.transform_summary or {}).get("compilation") or {}
    runres = st.session_state.run_result or {}
    comp = st.session_state.compare_result or {}
    return [
        (bool(st.session_state.config), "Load a contract"),
        (bool(report.get("success")), "Transform the UMAT"),
        (compilation.get("status") == "compiled", "Compile it (gfortran)"),
        (bool(st.session_state.validation_dir), "Build the Abaqus workspace"),
        (runres.get("original", {}).get("status") == "completed"
         and runres.get("transformed", {}).get("status") == "completed",
         "Run both Abaqus jobs"),
        (bool(comp.get("pass")), "Compare original vs OTI"),
    ]


def _need_config(key: str, what: str) -> bool:
    """Guard a panel that needs a contract - and offer to supply one."""
    if st.session_state.config:
        return True
    st.warning(f"**Locked.** {what} needs a loaded contract.")
    left, right = st.columns([1, 2])
    with left:
        if st.button("Load the demo contract", key=f"unlock_{key}",
                     type="primary", disabled=not DEMO_CONFIG.is_file()):
            cfg, error = _load_config(DEMO_CONFIG)
            if cfg is None:
                st.error(error)
            else:
                st.session_state.config = cfg
                st.session_state.config_path = str(DEMO_CONFIG)
                st.session_state.config_label = DEMO_LABEL
                _clear_downstream()
                st.rerun()
    with right:
        st.caption(
            f"Loads `examples/{DEMO_CONFIG.name}` - the smallest of the shipped "
            "examples (94 lines, linear elastic, NTENS 4, order 1). Tab "
            "**1. Load Config** has the other 25 contracts and upload.")
    return False


# ----------------------------------------------------------------------------
# Tab 0 - Start here
# ----------------------------------------------------------------------------

def _tab_start() -> None:
    st.header("Start here")
    st.markdown(
        "**UMAT-OTI rewrites an Abaqus UMAT so that its consistent tangent is "
        "computed, not written.** In a hand-written UMAT, `DDSDDE` is an "
        "algebraic expression somebody derived and typed - the part that is "
        "wrong when a material model is wrong. This tool lifts the stress "
        "update into *order-truncated imaginary* (OTI) arithmetic, seeds the "
        "strain increment with imaginary directions, and reads the exact "
        "derivative straight back out of the result."
    )

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("**What you give it**")
        st.caption(
            "Your UMAT source, plus a small JSON *contract* that names the "
            "routine, NTENS, the derivative order, and which variables are "
            "seeded. 26 contracts already ship with this checkout.")
    with col_b:
        st.markdown("**What you get back**")
        st.caption(
            "A drop-in Abaqus user subroutine whose `DDSDDE` is the exact "
            "tangent, the OTI modules it needs, a compile script, and a report "
            "listing every structural check the generator ran on its own "
            "output.")
    with col_c:
        st.markdown("**What it refuses to do**")
        st.caption(
            "Transform a source whose tangent it cannot locate, or claim a "
            "check passed that it did not run. A blocked source is reported "
            "with the reason, before anything is written.")

    st.markdown("---")
    st.subheader("What is on this machine")
    gfortran, abaqus = _tool("gfortran"), _tool(st.session_state.abaqus_command)
    env_a, env_b = st.columns(2)
    with env_a:
        if gfortran:
            st.success(f"gfortran found: `{gfortran}`")
        else:
            st.error("gfortran not on PATH")
        st.caption("Needed to compile the generated Fortran. Tabs 0-2 need "
                   "nothing else.")
    with env_b:
        if abaqus:
            st.success(f"`{st.session_state.abaqus_command}` found: `{abaqus}`")
        else:
            st.warning(f"`{st.session_state.abaqus_command}` not on PATH")
        st.caption("Needed only from tab 3 on: running the two jobs and "
                   "extracting the ODB. A licence is a separate question.")

    st.markdown("---")
    st.subheader("Transform one UMAT, right now")
    if not DEMO_CONFIG.is_file():
        st.error(f"The demo contract is missing: {DEMO_CONFIG}")
        return
    st.markdown(
        f"This runs the real service on `examples/{DEMO_CONFIG.name}` - a "
        "linear elastic UMAT that ships with the repository - and, if "
        "`gfortran` is present, compiles what it generated. It takes a few "
        "seconds and needs no Abaqus."
    )
    compile_it = st.checkbox("Also compile the generated Fortran", value=bool(gfortran),
                             disabled=not gfortran, key="demo_compile",
                             help=None if gfortran else "gfortran is not on PATH.")
    if st.button("Run the demo transformation", type="primary", key="btn_demo"):
        cfg, error = _load_config(DEMO_CONFIG)
        if cfg is None:
            st.error(error)
        else:
            st.session_state.config = cfg
            st.session_state.config_path = str(DEMO_CONFIG)
            st.session_state.config_label = DEMO_LABEL
            # Safe here and only here: tab bodies run in order, so the picker
            # on tab 1 has not been instantiated yet this run.
            st.session_state["config_pick"] = DEMO_LABEL
            st.session_state["applied_pick"] = DEMO_LABEL
            _clear_downstream()
            out_dir = WORKSPACE_ROOT / "demo" / "oti_transform" / _summarize_config(cfg).name
            with st.spinner("transforming, and compiling what it wrote ..."):
                summary, code = _run_transform(cfg, out_dir, compile_it)
            _store_transform(summary, out_dir)
            st.session_state.demo_exit = int(code)

    summary = st.session_state.transform_summary
    if summary and st.session_state.demo_exit is not None:
        st.markdown("---")
        report = st.session_state.transform_report or {}
        passed, total, failed = _semantic_summary(summary.get("semantic_checks"))
        compilation = summary.get("compilation") or {}

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Exit code", st.session_state.demo_exit)
        m2.metric("Structural checks", f"{passed}/{total}" if total else "n/a")
        m3.metric("Blockers", len(report.get("blockers") or []))
        m4.metric("Compilation", compilation.get("status", "not_requested"))

        _explain_outcome(summary, int(st.session_state.demo_exit))

        if failed:
            st.error("Checks that did not pass: " + ", ".join(f"`{f}`" for f in failed))
        elif total:
            st.success(
                f"All {total} structural checks passed. These are the "
                "generator checking its own output - that no OTI value reaches "
                "an untransformed call, that the seed is set before the stress "
                "update reads it, that the old hand-written tangent really was "
                "disabled, and so on.")

        artifact = ((summary.get("artifacts") or {}).get("abaqus_umat") or {})
        drop_in = artifact.get("source") or ""
        if drop_in and Path(drop_in).is_file():
            st.markdown("**The thing you actually take away**")
            st.caption(
                f"`{Path(drop_in).name}` - the transformed subroutine and every "
                "OTI module it needs, in one file, with a standard real-valued "
                "UMAT interface. Point Abaqus at it exactly as you would at "
                "your original.")
            _download(drop_in, "Download the drop-in UMAT", "demo_dropin")
            with st.expander("First 60 lines of what was generated"):
                head = Path(drop_in).read_text(encoding="utf-8",
                                               errors="replace").splitlines()[:60]
                st.code("\n".join(head), language="fortran")

        st.info(
            "The contract is now loaded, so tab **2. Transform** will run the "
            "same thing with the options exposed, and tab **3. Validate** is "
            "the Abaqus half: build a single-element job for the original and "
            "the transformed UMAT, run both, and compare them increment by "
            "increment.")

    st.markdown("---")
    with st.expander("What the generated code actually looks like"):
        st.markdown(
            "The generator emits an OTI module named for the problem size - "
            "`otim<directions>n<order>`, so four seed directions at order one "
            "is `otim4n1` - and the lifted variables take its type "
            "(`ONUMM4N1`). The strain increment is seeded with one imaginary "
            "direction per tensor component (`OTI_E1` ... `OTI_E4`), the "
            "original stress update runs unchanged in that arithmetic, and "
            "each derivative is read back out of the result with a `GETIM` "
            "extraction - `dsigma(I, K) = GETIM(STRESS(I), K)`. Nothing about "
            "the constitutive logic is rewritten; only the number type it runs "
            "in changes.")


# ----------------------------------------------------------------------------
# Tab 1 - Load Config
# ----------------------------------------------------------------------------

def _tab_load_config() -> None:
    st.subheader("1. Load Project Configuration")
    st.caption(
        "A *contract* is the JSON that tells the transformation which routine "
        "to lift, how big the stress tensor is, what order to go to, and what "
        "to seed. The selected contract drives every step after this one."
    )

    configs = _list_configs()
    lookup = dict(configs)

    def _on_pick() -> None:
        """Load on user change only.

        Comparing the widget against ``config_label`` instead would re-load a
        stale dropdown value over a config that a shortcut elsewhere just
        loaded, silently throwing away the newer one.
        """
        choice = st.session_state.get("config_pick")
        if not choice or choice == _CHOOSE:
            return
        path = lookup.get(choice)
        if path is None:
            return
        cfg, error = _load_config(path)
        st.session_state["applied_pick"] = choice
        if cfg is None:
            st.session_state["config_error"] = f"`{choice}` could not be loaded - {error}"
            return
        st.session_state["config_error"] = ""
        st.session_state.config = cfg
        st.session_state.config_path = str(path)
        st.session_state.config_label = choice
        _clear_downstream()

    st.session_state.setdefault("config_pick", _CHOOSE)
    st.session_state.setdefault("config_error", "")

    left, right = st.columns([2, 1])
    with left:
        st.selectbox(
            "Contracts in this checkout",
            [_CHOOSE] + [label for label, _ in configs],
            key="config_pick",
            on_change=_on_pick,
            help="Choosing one loads it immediately. "
                 + "  ".join(f"{path.name}/ = {what};"
                             for path, what in CONFIG_SOURCES if path.is_dir()))
        if st.session_state["config_error"]:
            st.error(st.session_state["config_error"])

    with right:
        upload = st.file_uploader("Upload JSON", type=["json"], accept_multiple_files=False)
        if upload is not None and st.button("Use uploaded"):
            payload = upload.read()
            try:
                cfg = load_project_config_json(payload, origin_path=upload.name)
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                st.error(f"{type(exc).__name__}: {exc}")
            else:
                st.session_state.config = cfg
                st.session_state.config_path = upload.name
                st.session_state.config_label = Path(upload.name).stem
                _clear_downstream()
                st.success(f"Loaded {upload.name}")

    if not configs:
        st.error(
            "No contracts found. Expected JSON files in "
            + ", ".join(f"`{path.name}/`" for path, _ in CONFIG_SOURCES[:3])
            + f" under {_repo_root()}.")

    cfg = st.session_state.config
    if not cfg:
        st.info("No contract loaded yet - pick one above to unlock the rest of "
                "the app.")
        return

    summary = _summarize_config(cfg)
    st.markdown("---")
    st.markdown(f"### {summary.name}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("NTENS", summary.ntens)
    m2.metric("Derivative order", summary.order)
    m3.metric("Extra contracts", len(summary.contracts))
    m4.metric("Helper surfaces", len(summary.helper_surfaces))
    st.markdown(
        f"- **UMAT file:** `{summary.selected_umat_file}`"
        f"\n- **Selected routine:** `{summary.selected_umat}`"
    )

    src_path = Path(summary.selected_umat_file)
    if src_path.is_file():
        st.success("The UMAT source this contract names is on disk, so the "
                   "transform on tab 2 can run.")
    else:
        st.error(
            f"UMAT source file `{src_path}` was not found on disk. Transform "
            "and Validate will refuse to run until the contract's "
            "`selected_umat_file` points at a file that exists here.")

    if summary.contracts:
        st.markdown("**Contracts**")
        rows = []
        for c in summary.contracts:
            seed = c.get("seed") or {}
            out = c.get("output") or {}
            internal = c.get("internal_use") or {}
            rows.append(
                {
                    "id": c.get("id"),
                    "seed_variable": seed.get("variable"),
                    "seed_shape": seed.get("shape"),
                    "output_variable": out.get("variable"),
                    "output_shape": out.get("shape"),
                    "replaces": internal.get("replace_variable"),
                    "additional_extractions": len(c.get("additional_extractions") or []),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("Advanced: edit the derivative requests before transforming"):
        st.caption(
            "Each row is one derivative you want the transformed UMAT to "
            "produce. The default row is the standard consistent tangent; add "
            "rows for parameter or state sensitivities. Nothing here is "
            "applied until you press **Apply derivative requests**.")
        derivative_rows = st.data_editor(
            request_editor_rows(cfg),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "kind": st.column_config.SelectboxColumn("kind", options=list(DERIVATIVE_KINDS), required=True),
                "order": st.column_config.NumberColumn("order", min_value=1, max_value=4, step=1, required=True),
            },
            key=f"derivative_requests_{st.session_state.config_label}",
        )
        map_left, map_right = st.columns(2)
        with map_left:
            st.caption("Parameters: PROPS index -> name")
            parameter_rows = st.data_editor(
                mapping_editor_rows(cfg, "parameters"),
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"parameter_map_{st.session_state.config_label}",
            )
        with map_right:
            st.caption("State variables: STATEV index -> name")
            state_rows = st.data_editor(
                mapping_editor_rows(cfg, "state_variables"),
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"state_map_{st.session_state.config_label}",
            )
        try:
            authored_config = build_unified_config(cfg, derivative_rows, parameter_rows, state_rows)
        except DerivativeRequestError as exc:
            authored_config = None
            st.error(str(exc))
        apply_col, download_col = st.columns(2)
        with apply_col:
            if st.button("Apply derivative requests", type="primary", disabled=authored_config is None):
                st.session_state.config = authored_config
                st.success("Derivative requests applied.")
        with download_col:
            if authored_config is not None:
                st.download_button(
                    "Download unified config",
                    data=json.dumps(authored_config, indent=2),
                    file_name=f"{st.session_state.config_label or 'umat'}_unified.json",
                    mime="application/json",
                )

    with st.expander("Raw JSON"):
        st.json(cfg, expanded=False)


# ----------------------------------------------------------------------------
# Tab 2 - Transform
# ----------------------------------------------------------------------------

def _tab_transform() -> None:
    st.subheader("2. Transform UMAT to OTI")
    st.caption(
        "Rewrites the stress update in OTI arithmetic and replaces the "
        "hand-written `DDSDDE` with values extracted from it. The constitutive "
        "logic is not re-derived; only the number type it runs in changes."
    )
    if not _need_config("transform", "Transforming a UMAT"):
        return
    cfg = st.session_state.config

    summary = _summarize_config(cfg)
    src_path = Path(summary.selected_umat_file)
    gfortran = _tool("gfortran")

    existing = _find_existing_transformed(summary.name)
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Generate new transform**")
        default_out = WORKSPACE_ROOT / f"gui_{summary.name}" / "oti_transform" / summary.name
        out_dir_str = st.text_input(
            "Output directory",
            value=str(default_out),
            help="OTI-lifted UMAT and module files will be written here.",
        )
        compile_it = st.checkbox(
            "Also compile the generated Fortran (gfortran)",
            value=bool(gfortran), disabled=not gfortran, key="transform_compile",
            help=None if gfortran else "gfortran is not on PATH.")
        st.caption(
            "Compiling here is the cheapest real check there is: generated "
            "Fortran that does not compile is not a tangent, and you find out "
            "in seconds instead of inside an Abaqus job.")
        if st.button("Run transformation", type="primary", disabled=not src_path.is_file(),
                     help=None if src_path.is_file()
                     else f"The contract's UMAT source is missing: {src_path}"):
            with st.spinner("Transforming..."):
                out_dir = Path(out_dir_str).resolve()
                transform_summary, exit_code = _run_transform(cfg, out_dir, compile_it)
            _store_transform(transform_summary, out_dir)
            if exit_code == 0:
                st.success("Transformation succeeded.")
            # The category below says *what* went wrong; a generic "reported
            # blockers" line would assert blockers even for the outcomes that
            # have none, such as a missing source file.
            _explain_outcome(transform_summary, exit_code)

    with col_b:
        st.markdown("**Reuse existing transform**")
        if existing is not None:
            st.markdown(f"Most recent on disk: `{existing}`")
            if st.button("Use existing transform"):
                st.session_state.transformed_umat = str(existing)
                st.session_state.transform_dir = str(existing.parent)
                st.session_state.transform_report = _read_json(
                    existing.parent / "transform_report.json")
                st.session_state.transform_summary = None
                st.success(f"Using {existing.name}")
        else:
            st.caption("No previously transformed UMAT found in "
                       "`umat_oti_workspace/`.")

    if st.session_state.transformed_umat:
        st.markdown("---")
        st.markdown(f"**Active transformed UMAT:** `{st.session_state.transformed_umat}`")
        st.markdown(f"**Generated dir:** `{st.session_state.transform_dir}`")

    service = st.session_state.transform_summary or {}
    if service:
        passed, total, failed = _semantic_summary(service.get("semantic_checks"))
        compilation = service.get("compilation") or {}
        c1, c2, c3 = st.columns(3)
        c1.metric("Structural checks", f"{passed}/{total}" if total else "n/a")
        c2.markdown(f"**Compilation:** {_status_badge(compilation.get('status'))}")
        c3.markdown(f"**Anchor:** `{service.get('anchor_status', 'n/a')}`")
        if failed:
            st.error("Checks that did not pass: " + ", ".join(f"`{f}`" for f in failed))
        if compilation.get("status") not in (None, "not_requested", "compiled"):
            with st.expander("Compiler output"):
                st.code(_tail(compilation.get("stderr") or compilation.get("stdout")
                              or "(nothing)", 40), language="text")

        drop_in = ((service.get("artifacts") or {}).get("abaqus_umat") or {}).get("source")
        st.markdown("**Take-away artefacts**")
        d1, d2, d3 = st.columns(3)
        with d1:
            if drop_in:
                _download(drop_in, "Drop-in UMAT (combined)", "tr_dropin")
            st.caption("One file: the transformed subroutine plus every OTI "
                       "module it needs, with a standard real UMAT interface.")
        with d2:
            _download(service.get("manifest", ""), "Derivative manifest", "tr_manifest")
            st.caption("Which derivative each extracted value is, in order.")
        with d3:
            _download(service.get("report_path", ""), "Transform report", "tr_report")
            st.caption("Every check, anchor and generated file.")

        if drop_in and Path(drop_in).is_file():
            with st.expander("First 80 lines of the generated source"):
                head = Path(drop_in).read_text(encoding="utf-8",
                                               errors="replace").splitlines()[:80]
                st.code("\n".join(head), language="fortran")

    report = st.session_state.transform_report
    if report:
        st.markdown("---")
        st.markdown("### Transform report")
        c1, c2, c3 = st.columns(3)
        c1.metric("Success", "yes" if report.get("success") else "no")
        c2.metric("Blockers", len(report.get("blockers", [])))
        c3.metric("Warnings", len(report.get("warnings", [])))
        if report.get("blockers"):
            st.error("Blockers:")
            for b in report["blockers"]:
                st.markdown(f"- {b}")
        if report.get("warnings"):
            with st.expander(f"Warnings ({len(report['warnings'])})"):
                for w in report["warnings"]:
                    st.markdown(f"- {w}")
        if report.get("generated_files"):
            with st.expander("Generated files"):
                for f in report["generated_files"]:
                    st.markdown(f"- `{f}`")
        with st.expander("Raw transform report"):
            st.json(report, expanded=False)

        if report.get("success") and st.session_state.transformed_umat:
            st.info(
                "Next: tab **3. Validate** builds a single-element Abaqus job "
                "for the original UMAT and for this one, runs both, and "
                "compares them increment by increment. That step needs Abaqus; "
                "everything up to here did not.")


# ----------------------------------------------------------------------------
# Tab 3 - Validate
# ----------------------------------------------------------------------------

def _tab_validate() -> None:
    st.subheader("3. Validate (build, run, extract, compare)")
    st.caption(
        "The honest test: run the original UMAT and the transformed one "
        "through the same single-element job and compare what they produced. "
        "The original is the reference; agreement on stress plus a correct "
        "tangent is the claim being checked."
    )
    if not _need_config("validate", "Validating a transform"):
        return
    cfg = st.session_state.config
    if not st.session_state.transformed_umat:
        st.warning("**Locked.** There is no transformed UMAT yet. Run the "
                   "transform on tab **2. Transform** (or the demo on tab "
                   "**Start here**) first.")
        return

    abaqus = _tool(st.session_state.abaqus_command)
    if not abaqus:
        st.warning(
            f"`{st.session_state.abaqus_command}` is not on PATH, so the run "
            "and extract steps below will fail. You can still build the "
            "workspace and inspect the decks it writes, then run them "
            "wherever Abaqus lives.")

    summary = _summarize_config(cfg)
    src_path = Path(summary.selected_umat_file)
    transformed = Path(st.session_state.transformed_umat)
    transform_dir = Path(st.session_state.transform_dir or transformed.parent)

    st.markdown("**Workspace**")
    label_default = st.session_state.presentation_label or f"gui_{summary.name}"
    label = st.text_input("Workspace label", value=label_default, key="presentation_label")
    default_val = WORKSPACE_ROOT / label / "validation" / summary.name
    val_dir_str = st.text_input("Validation directory", value=str(default_val))

    st.markdown("**Run options**")
    cc1, cc2 = st.columns(2)
    with cc1:
        material_modes = [
            "single element plastic tension",
            "single element tension",
            "single element plastic shear",
            "single element finite tension",
            "single element plastic finite tension",
        ]
        try:
            mode_idx = material_modes.index(st.session_state.material_test_mode)
        except ValueError:
            mode_idx = 0
        st.session_state.material_test_mode = st.selectbox(
            "Material test mode", material_modes, index=mode_idx,
            help="The strain path the single-element deck follows. Pick one "
                 "the material actually exercises: an elastic-only path will "
                 "not test a plasticity branch."
        )
        st.session_state.compare_outputs = st.multiselect(
            "Compare outputs",
            ["STRESS", "STATEV", "DDSDDE", "CONSTITUTIVE_JACOBIANS", "CONVERGENCE"],
            default=st.session_state.compare_outputs,
            help="CONSTITUTIVE_JACOBIANS is what tab 4 plots; leave it on.",
        )
    with cc2:
        st.session_state.abaqus_command = st.text_input(
            "Abaqus command", value=st.session_state.abaqus_command
        )
        st.session_state.abaqus_modules = st.text_input(
            "Abaqus modules", value=st.session_state.abaqus_modules,
            help="Environment modules to load first, on a cluster that uses them."
        )
        st.session_state.abaqus_run_prefix = st.text_input(
            "Run prefix (srun/...)", value=st.session_state.abaqus_run_prefix
        )

    st.markdown("---")
    st.markdown("**Pipeline** — each step needs the one before it.")
    b1, b2, b3, b4 = st.columns(4)

    if b1.button("1. Build workspace", type="primary"):
        with st.spinner("Building workspace..."):
            val_dir = Path(val_dir_str).resolve()
            res = build_validation_workspace(
                validation_dir=val_dir,
                original_umat=src_path,
                transformed_umat=transformed,
                generated_dir=transform_dir,
                project_config=cfg,
                ntens=summary.ntens,
                abaqus_command=st.session_state.abaqus_command,
                abaqus_modules=st.session_state.abaqus_modules,
                run_prefix=st.session_state.abaqus_run_prefix,
                material_test_mode=st.session_state.material_test_mode,
                compare_outputs=list(st.session_state.compare_outputs),
                run_compile_smoke=False,
            )
        st.session_state.validation_dir = str(val_dir)
        st.session_state.build_result = {
            "warnings": res.warnings,
            "report": res.report,
            "files": res.files,
        }
        st.success(f"Workspace built at `{val_dir}`")

    val_dir = Path(st.session_state.validation_dir) if st.session_state.validation_dir else None
    locked = "Build the workspace first." if val_dir is None else None

    if b2.button("2. Run Abaqus jobs", disabled=val_dir is None, help=locked):
        with st.spinner("Running both UMAT jobs (this may take a few minutes)..."):
            res = run_both_jobs(
                val_dir.resolve(),
                abaqus_command=st.session_state.abaqus_command,
                abaqus_modules=st.session_state.abaqus_modules,
                run_prefix=st.session_state.abaqus_run_prefix,
            )
        st.session_state.run_result = res
        ok_o = res.get("original", {}).get("status") == "completed"
        ok_t = res.get("transformed", {}).get("status") == "completed"
        if ok_o and ok_t:
            st.success("Both jobs completed.")
        else:
            st.error("At least one job did not complete - see logs below.")

    if b3.button("3. Extract ODB", disabled=val_dir is None, help=locked):
        with st.spinner("Running abaqus python extraction..."):
            res = extract_results(
                val_dir.resolve(),
                abaqus_command=st.session_state.abaqus_command,
                abaqus_modules=st.session_state.abaqus_modules,
                run_prefix=st.session_state.abaqus_run_prefix,
            )
        st.session_state.extract_result = res.to_json()
        if res.status == "completed":
            st.success("Extraction completed.")
        else:
            st.error(f"Extraction status: {res.status}")

    if b4.button("4. Compare results", disabled=val_dir is None, help=locked):
        res = compare_validation_results(val_dir.resolve())
        st.session_state.compare_result = res.to_json()
        if res.passed:
            st.success(f"PASS  (max abs = {res.max_abs_difference})")
        else:
            st.warning(f"Status: {res.status}  (max abs = {res.max_abs_difference})")

    if val_dir is not None:
        st.caption(
            f"Workspace: `{val_dir}` — it holds both decks, both UMAT sources, "
            "and the run scripts, so the same comparison can be re-run by hand "
            "or on a cluster.")

    # ---- Status panel ----------------------------------------------------
    st.markdown("---")
    st.markdown("### Status")
    grid = st.columns(4)
    build = st.session_state.build_result
    runres = st.session_state.run_result
    ext = st.session_state.extract_result
    comp = st.session_state.compare_result
    grid[0].markdown(f"**Build:** {_status_badge('configured' if build else None)}")
    if runres:
        orig_st = runres.get("original", {}).get("status")
        oti_st = runres.get("transformed", {}).get("status")
        grid[1].markdown(f"**Original:** {_status_badge(orig_st)}<br>**OTIS:** {_status_badge(oti_st)}", unsafe_allow_html=True)
    else:
        grid[1].markdown(f"**Jobs:** {_status_badge(None)}")
    grid[2].markdown(f"**Extract:** {_status_badge((ext or {}).get('status'))}")
    if comp is not None:
        comp_status = "passed" if comp.get("pass") else (comp.get("status") or "unknown")
        grid[3].markdown(f"**Compare:** {_status_badge(comp_status)}")
    else:
        grid[3].markdown(f"**Compare:** {_status_badge(None)}")

    if runres:
        with st.expander("Run job logs"):
            for which in ("original", "transformed"):
                entry = runres.get(which, {})
                st.markdown(f"**{which}** - status: `{entry.get('status')}` - rc: `{entry.get('returncode')}`")
                st.code(_tail(entry.get("stdout_excerpt") or "", 20) or "(no stdout excerpt)", language="text")
                if entry.get("stderr_excerpt"):
                    st.caption("stderr tail")
                    st.code(_tail(entry.get("stderr_excerpt"), 15), language="text")
    if ext and ext.get("stderr_excerpt"):
        with st.expander("Extraction stderr tail"):
            st.code(_tail(ext["stderr_excerpt"], 25), language="text")

    if comp:
        st.markdown("### Comparison summary")
        st.json(comp, expanded=False)
        # show DDSDDE & stress diff highlights if comparison_report.json exists
        rep = _read_json(comp.get("report_json_path"))
        if rep:
            with st.expander("Top-level comparison report"):
                st.json(rep, expanded=False)


# ----------------------------------------------------------------------------
# Tab 4 - Constitutive Jacobians
# ----------------------------------------------------------------------------

def _tab_constitutive() -> None:
    st.subheader("4. Constitutive Jacobians (Original vs OTIS)")
    st.caption(
        "Component by component, increment by increment: what the original "
        "UMAT reported and what the OTI-transformed one did. Agreement here is "
        "the result the whole pipeline exists to produce."
    )
    val_dir = Path(st.session_state.validation_dir) if st.session_state.validation_dir else None
    if val_dir is None or not val_dir.is_dir():
        st.warning("**Locked.** Build and run a validation workspace on tab "
                   "**3. Validate** first — this tab only reads what those "
                   "Abaqus runs wrote.")
        return

    orig = _read_json(val_dir / "original_results.json")
    otis = _read_json(val_dir / "otis_results.json")
    if not orig or not otis:
        st.warning(
            "The workspace exists but has no extracted results yet. On tab 3, "
            "run steps **2. Run Abaqus jobs** and **3. Extract ODB**; this tab "
            f"reads `original_results.json` and `otis_results.json` from "
            f"`{val_dir}`.")
        return

    incs_o = orig.get("increments") or []
    incs_t = otis.get("increments") or []
    if not incs_o or not incs_t:
        st.warning("No increments found in extracted results.")
        return

    art_ids = sorted({k for inc in incs_o for k in (inc.get("constitutive_outputs") or {})})

    # DDSDDE is present for every transform; the extra artifacts are not, so
    # the context plot is shown before deciding whether there is more to show.
    st.markdown("### DDSDDE evolution (context)")
    _ddsdde_overview(incs_o, incs_t)

    if not art_ids:
        st.info(
            "No `constitutive_outputs` artifacts in the extracted results, so "
            "the DDSDDE comparison above is all there is for this run. Extra "
            "artifacts appear when the contract defines "
            "`extra_jacobian_contracts` and the workspace was built with "
            "`CONSTITUTIVE_JACOBIANS` in *Compare outputs*.")
        return

    st.markdown("---")
    selected = st.multiselect(
        "Artifacts to display",
        art_ids,
        default=art_ids,
    )
    for art_id in selected:
        _render_artifact(art_id, incs_o, incs_t)


def _ddsdde_overview(incs_o: list[dict], incs_t: list[dict]) -> None:
    # show DDSDDE(1,1) and DDSDDE(4,4) per increment
    try:
        time = [float(inc.get("frame_value") or inc.get("increment_number")) for inc in incs_o]
        d11_o = [float(inc["ddsdde"][0][0]) for inc in incs_o]
        d11_t = [float(inc["ddsdde"][0][0]) for inc in incs_t]
        d44_o = [float(inc["ddsdde"][3][3]) for inc in incs_o] if len(incs_o[0]["ddsdde"]) > 3 else None
        d44_t = [float(inc["ddsdde"][3][3]) for inc in incs_t] if len(incs_t[0]["ddsdde"]) > 3 else None
    except Exception:  # noqa: BLE001
        st.warning("DDSDDE not available in extracted results.")
        return

    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**DDSDDE(1,1)**")
        st.line_chart({"step": time, "original": d11_o, "otis": d11_t}, x="step")
    if d44_o is not None:
        with cc2:
            st.markdown("**DDSDDE(4,4)**")
            st.line_chart({"step": time, "original": d44_o, "otis": d44_t}, x="step")
    st.caption("Two curves that lie on top of each other is the intended "
               "result: the transformed UMAT computing what the hand-written "
               "one wrote out.")


def _render_artifact(art_id: str, incs_o: list[dict], incs_t: list[dict]) -> None:
    sample = None
    for inc in incs_o:
        if art_id in (inc.get("constitutive_outputs") or {}):
            sample = inc["constitutive_outputs"][art_id]
            break
    if not sample:
        return

    labels = sample.get("component_labels") or [f"c{i}" for i in range(int(sample.get("component_count") or 0))]
    target = sample.get("target_variable") or art_id
    source = sample.get("source_variable") or "?"
    kind = sample.get("source_kind") or "?"

    st.markdown(f"#### `{art_id}`   -   `{source} -> {target}`   ({kind})")

    # build per-component arrays
    time = [float(inc.get("frame_value") or inc.get("increment_number")) for inc in incs_o]
    arr_o = np.array(
        [list((inc.get("constitutive_outputs") or {}).get(art_id, {}).get("values") or [np.nan] * len(labels)) for inc in incs_o],
        dtype=float,
    )
    arr_t = np.array(
        [list((inc.get("constitutive_outputs") or {}).get(art_id, {}).get("values") or [np.nan] * len(labels)) for inc in incs_t],
        dtype=float,
    )

    # alignment guard
    if arr_o.shape != arr_t.shape:
        st.warning(f"Component shape mismatch: original {arr_o.shape} vs otis {arr_t.shape}.")
        return

    # summary table
    abs_err = np.abs(arr_o - arr_t)
    denom = np.maximum(np.abs(arr_o), 1e-30)
    rel_err = abs_err / denom
    rows: list[dict[str, Any]] = []
    for j, lbl in enumerate(labels):
        rows.append(
            {
                "component": lbl,
                "max |original|": float(np.max(np.abs(arr_o[:, j]))),
                "max |otis|": float(np.max(np.abs(arr_t[:, j]))),
                "max abs err": float(np.max(abs_err[:, j])),
                "max rel err": float(np.max(rel_err[:, j])),
                "RMSE": float(np.sqrt(np.mean((arr_o[:, j] - arr_t[:, j]) ** 2))),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    # per-component plots in a grid
    n = len(labels)
    cols_per_row = 2 if n > 1 else 1
    for row_start in range(0, n, cols_per_row):
        cols = st.columns(cols_per_row)
        for k in range(cols_per_row):
            j = row_start + k
            if j >= n:
                break
            with cols[k]:
                st.markdown(f"**{labels[j]}**")
                st.line_chart(
                    {
                        "step": time,
                        "original": arr_o[:, j].tolist(),
                        "otis": arr_t[:, j].tolist(),
                    },
                    x="step",
                )

    # per-increment data table
    with st.expander("Per-increment values"):
        per_rows: list[dict[str, Any]] = []
        for i, t in enumerate(time):
            for j, lbl in enumerate(labels):
                per_rows.append(
                    {
                        "step": t,
                        "component": lbl,
                        "original": float(arr_o[i, j]),
                        "otis": float(arr_t[i, j]),
                        "abs_err": float(abs_err[i, j]),
                    }
                )
        st.dataframe(per_rows, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------
# Tab 5 - Report / artifacts
# ----------------------------------------------------------------------------

_ARTIFACT_PRIORITY = [
    "validation_report.json",
    "validation_report.md",
    "comparison_report.json",
    "comparison_report.md",
    "original_results.json",
    "otis_results.json",
    "original_umat_validation.inp",
    "otis_umat_validation.inp",
    "original_abaqus_stdout.log",
    "original_abaqus_stderr.log",
    "otis_abaqus_stdout.log",
    "otis_abaqus_stderr.log",
    "extract_results_stdout.log",
    "extract_results_stderr.log",
]


def _tab_report() -> None:
    st.subheader("5. Report and Artifacts")
    st.caption(
        "Everything the validation workspace wrote, in one place: the reports "
        "to read and the files to keep."
    )
    val_dir = Path(st.session_state.validation_dir) if st.session_state.validation_dir else None
    if val_dir is None or not val_dir.is_dir():
        st.warning("**Locked.** Build a validation workspace on tab "
                   "**3. Validate** first.")
        if st.session_state.transform_summary:
            st.caption(
                "The transform's own artefacts — the drop-in UMAT, the "
                "derivative manifest and the transform report — are on tab "
                "**2. Transform**, and do not need Abaqus.")
        return

    st.markdown(f"**Validation dir:** `{val_dir}`")

    md = val_dir / "comparison_report.md"
    if md.is_file():
        with st.expander("Comparison report (markdown)", expanded=True):
            st.markdown(md.read_text(encoding="utf-8"))

    vmd = val_dir / "validation_report.md"
    if vmd.is_file():
        with st.expander("Validation report (markdown)"):
            st.markdown(vmd.read_text(encoding="utf-8"))

    st.markdown("### Downloads")
    present = []
    for name in _ARTIFACT_PRIORITY:
        p = val_dir / name
        if p.is_file():
            present.append(p)
    # add anything else not in priority list
    for p in sorted(val_dir.iterdir()):
        if p.is_file() and p not in present:
            present.append(p)

    if not present:
        st.info("The workspace exists but is empty — run the pipeline on tab 3.")
        return

    cols = st.columns(2)
    for idx, p in enumerate(present):
        col = cols[idx % 2]
        with col:
            try:
                data = p.read_bytes()
            except Exception:  # noqa: BLE001
                continue
            col.download_button(
                p.name,
                data=data,
                file_name=p.name,
                key=f"dl_{p.name}",
            )


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

#: Where a corpus round writes its results and its scratch. Both are outside
#: the repository: the results carry machine paths until they are scrubbed and
#: the scratch is tens of gigabytes of Abaqus output.
CORPUS_RESULTS = Path(
    os.environ.get("UMAT_OTI_CORPUS_RESULTS")
    or _repo_root().parent / "corpus_run" / "results")
CORPUS_WORK = Path(
    os.environ.get("UMAT_OTI_CORPUS_WORK")
    or _repo_root().parent / "corpus_run" / "work")


def _tab_corpus() -> None:
    """Every acquired UMAT, how far it got, and where to look.

    The whole panel is drawn by umat_oti.app.corpus_tab from the artefacts a
    batch wrote. Nothing is decided here: a verdict rendered differently in the
    interface than in the evidence is a second opinion nobody can cite.
    """
    from umat_oti.app.corpus_tab import render

    if not CORPUS_RESULTS.is_dir():
        st.info(
            f"No corpus round has written to {CORPUS_RESULTS}. Run "
            f"`make batch-abaqus` , or set UMAT_OTI_CORPUS_RESULTS and "
            f"UMAT_OTI_CORPUS_WORK to where one did.")
        return
    render(CORPUS_RESULTS, CORPUS_WORK, st=st)


def _sidebar(summary: _ConfigSummary | None) -> None:
    with st.sidebar:
        st.title("UMAT-OTI")
        st.caption("OTI source transformation, validation, and constitutive Jacobians")

        st.markdown("---")
        st.markdown("**Where you are**")
        steps = _progress()
        for done, label in steps:
            st.markdown(f"{'✅' if done else '⬜'} {label}")
        st.progress(sum(1 for done, _ in steps if done) / len(steps))
        st.caption("A step ticks only when its own artefact says so.")

        st.markdown("---")
        if summary:
            st.markdown(f"**Config:** `{st.session_state.config_label or summary.name}`")
            st.markdown(f"NTENS = `{summary.ntens}`  -  order = `{summary.order}`  -  "
                        f"contracts = `{len(summary.contracts)}`")
            if st.button("Clear config", key="btn_clear_config"):
                st.session_state.config = None
                st.session_state.config_path = ""
                st.session_state.config_label = ""
                # Safe: the sidebar is drawn before the tab that owns this
                # widget, so the key is not yet instantiated this run.
                st.session_state["config_pick"] = _CHOOSE
                st.session_state["applied_pick"] = _CHOOSE
                st.session_state["config_error"] = ""
                _clear_downstream()
                st.rerun()
        else:
            st.markdown(":grey[No config loaded]")
        if st.session_state.transformed_umat:
            st.markdown(f"**OTI UMAT:** `{Path(st.session_state.transformed_umat).name}`")
        if st.session_state.validation_dir:
            st.markdown(f"**Validation dir:** `{Path(st.session_state.validation_dir).name}`")

        st.markdown("---")
        gfortran, abaqus = _tool("gfortran"), _tool(st.session_state.abaqus_command)
        st.markdown(f"{'✅' if gfortran else '❌'} gfortran &nbsp; "
                    f"{'✅' if abaqus else '❌'} abaqus", unsafe_allow_html=True)
        with st.expander("What needs what"):
            st.caption(
                "Tabs **Start here**, **1** and **2** need only gfortran, and "
                "only if you ask for the compile check. Tabs **3**, **4** and "
                "**5** need Abaqus: they run two real jobs and read their ODBs. "
                "Tab **6** reads a corpus round that was run elsewhere.")

        with st.expander("Other interfaces in this repository"):
            st.caption(
                "This page is the full console. Two narrower front ends over "
                "the same services also ship:")
            st.code("streamlit run src/umat_oti/app/workbench_app.py\n"
                    "streamlit run src/umat_oti/app/unified_app.py",
                    language="bash")
            st.caption(
                "`workbench_app` is a four-step guided wizard for one "
                "transformation; `unified_app` is the plain-language view that "
                "avoids Abaqus vocabulary. Neither computes anything this one "
                "does not.")

        st.markdown("---")
        st.caption(f"Repo root: {_repo_root()}")
        st.caption(f"Contracts: {', '.join(p.name for p, _ in CONFIG_SOURCES if p.is_dir())}")


def main() -> None:
    st.set_page_config(page_title="UMAT-OTI", layout="wide", page_icon="∂")
    _init_state()

    cfg = st.session_state.config
    summary = _summarize_config(cfg) if cfg else None
    _sidebar(summary)

    tabs = st.tabs(
        ["Start here", "1. Load Config", "2. Transform", "3. Validate",
         "4. Constitutive Jacobians", "5. Report", "6. Corpus"]
    )
    with tabs[0]:
        _tab_start()
    with tabs[1]:
        _tab_load_config()
    with tabs[2]:
        _tab_transform()
    with tabs[3]:
        _tab_validate()
    with tabs[4]:
        _tab_constitutive()
    with tabs[5]:
        _tab_report()
    with tabs[6]:
        _tab_corpus()


if __name__ == "__main__":
    main()
