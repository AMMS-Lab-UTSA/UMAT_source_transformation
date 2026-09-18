"""The two developer screens of the IMQCAM presentation (slides 16-17, 40-41).

``Constitutive Jacobian``
    Load the UMAT and set NTENS; differentiate STRESS with respect to DSTRAN
    and write into DDSDDE; the tangent block is found for you; Transform.
    Calls :mod:`umat_oti.services.jacobian_request` -- the same function as
    ``umat-oti jacobian`` -- which calls the transformation service.

``Parameter Sensitivities``
    Take the UMAT from the first screen, list the parameters with their PROPS
    index and value, tick the stress and state derivatives, Build. Calls
    :func:`umat_oti.provider.collaborator.package`, which runs
    ``umat-oti-provider build`` and the provider's independent verification as
    subprocesses and writes REAL_UMAT.obj, OTI_UMAT.obj, Mapping.json and
    transform_report.txt.

Neither screen computes a derivative, a contract field the service would
compute, or a verdict of its own: every number shown is read from what those
commands wrote.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from umat_oti.provider import collaborator
from umat_oti.services import jacobian_request as jr

SOURCE_TYPES = ["for", "f", "f90", "f77", "ftn"]

#: Repository models whose input contracts ship with the checkout. Every
#: source starts from an empty table; one that is byte-identical to a shipped
#: model is offered a button that fills the table from that model's contract.
MODELS_DIR = Path(__file__).resolve().parents[3] / "parameter_sensitivity" / "models"


def workspace_root() -> Path:
    """Where the screens write. ``UMAT_OTI_GUI_WORKSPACE`` overrides the default."""
    configured = os.environ.get("UMAT_OTI_GUI_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "umat_oti_workspace" / "presentation"


def _fresh_dir(kind: str, stem: str) -> Path:
    base = workspace_root() / kind
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{collaborator.model_name(stem)}-", dir=base))


def _store_upload(upload) -> Path:
    """Keep an uploaded source under its own name, addressed by its content."""
    payload = upload.getvalue()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    target = workspace_root() / "sources" / digest / Path(upload.name).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_bytes() != payload:
        target.write_bytes(payload)
    return target


def _source_input(prefix: str, label: str) -> Path | None:
    """An uploaded file, or a path on this machine. Returns the file or None."""
    upload = st.file_uploader(label, type=SOURCE_TYPES, key=f"{prefix}_upload")
    typed = st.text_input("or its path on this machine", key=f"{prefix}_path",
                          placeholder="/path/to/umat.for")
    if upload is not None:
        return _store_upload(upload)
    if typed.strip():
        path = Path(typed.strip()).expanduser()
        if path.is_file():
            return path.resolve()
        st.error(f"No file at `{path}`.")
    return None


def _download(path: Path | None, label: str, key: str, file_name: str | None = None) -> None:
    if path is None or not Path(path).is_file():
        return
    data = Path(path).read_bytes()
    st.download_button(f"{label}  ({len(data):,} bytes)", data=data,
                       file_name=file_name or Path(path).name, key=key)


# ---------------------------------------------------------------------------
# Constitutive Jacobian (slides 16 and 40)
# ---------------------------------------------------------------------------

def render_jacobian_screen() -> None:
    st.header("umat-oti — Constitutive Jacobian")
    st.caption("Return the consistent material tangent DDSDDE = ∂σ/∂ε from a "
               "stress-update routine")
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("1. Material source")
        source = _source_input("pj", "Fortran source file (.for)")
        if source is not None and st.session_state.get("pj_loaded") != str(source):
            # A new source resets NTENS to what the source itself suggests.
            # Safe here: the number input below is not instantiated yet.
            from umat_oti.app.engine import suggest_ntens

            suggested, why = suggest_ntens(source.read_text(errors="replace"))
            st.session_state["pj_loaded"] = str(source)
            st.session_state["pj_ntens"] = suggested if suggested in jr.NTENS_CHOICES else 6
            st.session_state["pj_ntens_why"] = why
            st.session_state.pop("pj_run", None)
        st.session_state.setdefault("pj_ntens", 6)
        ntens = int(st.number_input("Number of stress components (NTENS)", min_value=3,
                                    max_value=6, step=1, key="pj_ntens"))
        if source is not None and st.session_state.get("pj_ntens_why"):
            st.caption(f"Suggested from the source: {st.session_state['pj_ntens_why']}. "
                       "Set it to what your analysis passes.")

        st.subheader("2. Derivative to extract")
        c1, c2, c3 = st.columns(3)
        seed = c1.selectbox("differentiate with respect to", jr.SEED_CHOICES, key="pj_seed")
        response = c2.selectbox("of the output", jr.RESPONSE_CHOICES, key="pj_response")
        target = c3.selectbox("write into", jr.TARGET_CHOICES, key="pj_target")
        st.caption(f"i.e. {target}(i,j) = ∂ {response}(i) / ∂ {seed}(j)")

        st.subheader("3. Tangent block (detected automatically)")
        problem = None if ntens in jr.NTENS_CHOICES else \
            f"NTENS must be one of {', '.join(map(str, jr.NTENS_CHOICES))}"
        preview: dict[str, Any] = {}
        if source is not None and problem is None:
            try:
                preview = jr.preview_tangent_block(source, ntens=ntens, seed=seed,
                                                   response=response, target=target)
            except Exception as error:  # noqa: BLE001 - shown, never raised
                problem = f"{type(error).__name__}: {error}"
        st.text_input("variables carried through the derivative", disabled=True,
                      value=", ".join(preview.get("carried_variables") or []),
                      key=f"pj_carried_{hash(str(preview))}")
        st.text_input("line(s) that assign the tangent", disabled=True,
                      value=jr.describe_tangent_block(preview) if preview else "",
                      key=f"pj_lines_{hash(str(preview))}")
        if problem:
            st.error(problem)
        clicked = st.button("Transform →", type="primary", key="pj_transform",
                            disabled=source is None or problem is not None)
        if clicked and source is not None:
            out_dir = _fresh_dir("jacobian", source.stem)
            with st.spinner("transforming ..."):
                run = jr.run_jacobian_transform(source, out_dir, ntens=ntens, seed=seed,
                                                response=response, target=target)
            st.session_state["pj_run"] = {
                "source": str(source), "ntens": ntens, "seed": seed, "response": response,
                "target": target, "out_dir": str(out_dir), "exit_code": run.exit_code,
                "succeeded": run.succeeded, "summary": run.summary,
                "tangent_lines": run.tangent_lines(), "carried": run.carried_variables(),
                "tangent_block": jr.describe_tangent_block(preview),
                "contract": str(run.contract_path),
                "transformed": str(run.transformed_source or ""),
                "drop_in": str(run.drop_in_source or ""),
                "report_txt": str(run.text_report or ""),
            }
            st.session_state["pp_source_from_jacobian"] = str(source)
    with right:
        _render_jacobian_result(st.session_state.get("pj_run"))


def _render_jacobian_result(run: dict[str, Any] | None) -> None:
    st.subheader("Result")
    if not run:
        st.info("Load a UMAT on the left and press **Transform**.")
        return
    summary = run["summary"]
    report_path = Path(str(summary.get("report_path") or ""))
    report = json.loads(report_path.read_text()) if report_path.is_file() else {}
    if run["succeeded"]:
        st.success("Transform succeeded")
    else:
        st.error(f"Transform did not succeed (exit code {run['exit_code']}, "
                 f"`{summary.get('status_category') or 'no category'}`)")
        for field in ("error", "errors", "blockers", "completion_issues"):
            if summary.get(field):
                st.code(json.dumps(summary[field], indent=2, default=str), language="json")
    m1, m2, m3 = st.columns(3)
    m1.metric("blockers", len(summary.get("blockers") or report.get("blockers") or []))
    m2.metric("warnings", len(summary.get("warnings") or report.get("warnings") or []))
    m3.metric("exit code", run["exit_code"])
    if run["succeeded"]:
        checks = summary.get("semantic_checks") or {}
        passed = sum(1 for ok in checks.values() if ok)
        transformed = Path(run["transformed"]) if run["transformed"] else None
        st.markdown(
            f"- the routine now fills **{run['target']} = ∂{run['response']}/∂{run['seed']}** "
            "exactly, from OTI arithmetic (no step size)\n"
            f"- generated `{transformed.name if transformed else '?'}`\n"
            f"- lines that assign the tangent: {run.get('tangent_block')}\n"
            f"- carried through the derivative: {', '.join(run['carried'])}\n"
            f"- the generator's own structural checks: {passed}/{len(checks)} passed")
        d1, d2 = st.columns(2)
        with d1:
            _download(transformed, "Transformed UMAT", "pj_dl_transformed")
            _download(Path(run["report_txt"]) if run["report_txt"] else None,
                      "Transform report", "pj_dl_report")
        with d2:
            _download(Path(run["drop_in"]) if run["drop_in"] else None,
                      "Drop-in UMAT with OTI modules", "pj_dl_dropin")
            _download(Path(run["contract"]), "Contract (four fields)", "pj_dl_contract")
    st.caption("The same request from a terminal:")
    st.code(" ".join(["umat-oti", "jacobian", shlex.quote(run["source"]), "--ntens",
                      str(run["ntens"]), "--seed", run["seed"], "--response", run["response"],
                      "--target", run["target"], "--out", shlex.quote(run["out_dir"])]),
            language="bash")


# ---------------------------------------------------------------------------
# Parameter Sensitivities (slides 17 and 41)
# ---------------------------------------------------------------------------

PARAMETER_COLUMNS = ("parameter", "PROPS index", "value")


def repository_model(source: Path) -> tuple[str, dict[str, Any]] | None:
    """The shipped model whose source is byte-identical to ``source``, if any."""
    if not MODELS_DIR.is_dir():
        return None
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for contract_path in sorted(MODELS_DIR.glob("*/contract_v2.json")):
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        main = contract_path.parent / (contract.get("source") or {}).get("main_file", "")
        if main.is_file() and hashlib.sha256(main.read_bytes()).hexdigest() == digest:
            return contract_path.parent.name, contract
    return None


def default_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    values = (contract.get("validation") or {}).get("props_values") or []
    rows = [{"parameter": p["name"], "PROPS index": int(p["props_index"]),
             "value": float(values[p["props_index"] - 1]) if p["props_index"] <= len(values) else None}
            for p in contract.get("parameters") or []]
    return sorted(rows, key=lambda row: row["PROPS index"])


def _table_frame(rows: list[dict[str, Any]]):
    """The editor's data: typed columns, so an empty table still has them."""
    import pandas as pd

    frame = pd.DataFrame(rows, columns=list(PARAMETER_COLUMNS))
    return frame.astype({"parameter": "object", "PROPS index": "Int64", "value": "float64"})


def _rows_from_editor(table: Any) -> list[dict[str, Any]]:
    if hasattr(table, "to_dict"):
        return table.to_dict("records")
    return list(table or [])


def render_provider_screen() -> None:
    st.header("umat-oti — Parameter Sensitivities")
    st.caption("Return exact parameter derivatives DSIGMA_DP = ∂σ/∂p and "
               "DSTATEV_DP = ∂(state)/∂p from a stress-update routine")
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("1. Material source")
        from_jacobian = st.session_state.get("pp_source_from_jacobian")
        use_previous = False
        if from_jacobian:
            use_previous = st.checkbox(
                f"use the UMAT from the Constitutive Jacobian screen (`{Path(from_jacobian).name}`)",
                value=True, key="pp_use_previous")
        source = Path(from_jacobian) if use_previous else _source_input("pp", "Fortran source file (.for)")
        known = repository_model(source) if source is not None else None
        if source is not None and st.session_state.get("pp_loaded") != str(source):
            # A new source starts an empty table. Safe: no widget below exists
            # yet in this run.
            st.session_state["pp_loaded"] = str(source)
            st.session_state["pp_rows"] = []
            st.session_state["pp_model"] = known[0] if known else collaborator.model_name(source.stem)
            st.session_state["pp_table_version"] = st.session_state.get("pp_table_version", 0) + 1
            st.session_state.pop("pp_result", None)
        if known and st.button(f"Fill the table from parameter_sensitivity/models/{known[0]}/"
                               "contract_v2.json", key="pp_fill",
                               help="This source is byte-identical to a model that ships with "
                                    "the repository; its contract lists the parameters."):
            st.session_state["pp_rows"] = default_rows(known[1])
            st.session_state["pp_nstatv"] = int(known[1]["dimensions"]["nstatev"])
            st.session_state["pp_table_version"] = st.session_state.get("pp_table_version", 0) + 1
        st.session_state.setdefault("pp_nstatv", 0)
        nstatv = int(st.number_input("Number of state variables (NSTATV)", min_value=0,
                                     step=1, key="pp_nstatv"))

        st.subheader("2. Parameters to differentiate")
        st.caption("one row per parameter: its **PROPS index** in the routine and the "
                   "**value** to evaluate at")
        rows = st.session_state.get("pp_rows") or []
        table = st.data_editor(
            _table_frame(rows),
            num_rows="dynamic", hide_index=True, width="stretch",
            height=38 + 35 * (max(len(rows), 4) + 1),
            column_order=PARAMETER_COLUMNS,
            column_config={
                "parameter": st.column_config.TextColumn("parameter"),
                "PROPS index": st.column_config.NumberColumn("PROPS index", min_value=1, step=1, format="%d"),
                "value": st.column_config.NumberColumn("value", format="%g"),
            },
            key=f"pp_table_{st.session_state.get('pp_table_version', 0)}")

        st.subheader("3. Derivatives")
        c1, c2 = st.columns(2)
        stress = c1.checkbox("stress (DSIGMA_DP)", value=True, key="pp_stress")
        state = c2.checkbox("state (DSTATEV_DP, auto)", value=True, key="pp_state")
        with st.expander("Options"):
            st.session_state.setdefault("pp_model", "model")
            model = st.text_input("model name (names the canonical umat_<name>_oti.obj)",
                                  key="pp_model")
            verify = st.checkbox("verify against finite differences of the original routine",
                                 value=True, key="pp_verify")
            j2 = st.checkbox("require the check path to cross elastic, plastic and unloading "
                             "increments (J2-type materials)", value=False, key="pp_j2")

        problem = None
        contract: dict[str, Any] | None = None
        if source is None:
            problem = "Load a UMAT first."
        else:
            try:
                parameters = collaborator.parse_parameters(_rows_from_editor(table))
                contract = collaborator.provider_contract(
                    source.name, name=model, nstatev=nstatv, parameters=parameters,
                    stress=stress, state=state)
            except ValueError as error:
                problem = str(error)
        if problem and source is not None:
            st.warning(problem)
        clicked = st.button("Build OTI object →", type="primary", key="pp_build",
                            disabled=contract is None)
        if clicked and contract is not None and source is not None:
            work = _fresh_dir("provider", model)
            contract_path = collaborator.stage_model(source, work / collaborator.model_name(model), contract)
            with st.spinner("building the provider, then checking it against finite "
                            "differences of the original routine ..."):
                summary = collaborator.package(contract_path, work / "out", verify=verify,
                                               require_j2_branches=j2)
            st.session_state["pp_result"] = summary
    with right:
        _render_provider_result(st.session_state.get("pp_result"))


def _render_provider_result(summary: dict[str, Any] | None) -> None:
    st.subheader("Result")
    if not summary:
        st.info("List the parameters on the left and press **Build OTI object**.")
        return
    build = summary.get("build") or {}
    verification = summary.get("verification")
    if build.get("exit_code") != 0:
        st.error(f"Build failed (exit code {build.get('exit_code')})")
        st.code(build.get("diagnostic") or "", language="text")
        return
    if summary.get("exit_code") == 0:
        st.success("Build succeeded" + (" and verified" if verification else ""))
    else:
        st.warning("Build succeeded; verification did not pass")
    canonical = Path(summary["canonical"]["object"]).name
    count = len(summary.get("parameters") or [])
    st.markdown(
        f"- generated `{canonical}` — the original routine plus a differentiated one\n"
        f"- the differentiated routine returns **DSIGMA_DP = ∂σ/∂p** and "
        f"**DSTATEV_DP = ∂(state)/∂p** for all {count} parameters")
    m1, m2 = st.columns(2)
    m1.metric("build exit code", build.get("exit_code"))
    if verification is not None:
        m2.metric("verification exit code", verification.get("exit_code"))
        result = verification.get("result") or {}
        if verification.get("passed"):
            errors = collaborator.headline_errors(result)
            e1, e2, e3 = st.columns(3)
            for column, (label, value) in zip((e1, e2, e3), errors.items()):
                column.metric(label, f"{value:.2e}" if isinstance(value, float) and math.isfinite(value) else "n/a")
            st.caption(
                f"Scaled max errors at the finest step (tolerance "
                f"{result.get('scaled_max_error_tolerance')}), against centred finite "
                "differences of the separately compiled original routine over "
                f"{result.get('increments')} increments. Primal parity: stress "
                f"{result.get('primal_stress_max_abs'):.1e}, state "
                f"{result.get('primal_state_max_abs'):.1e}.")
            tie = summary.get("tie") or {}
            if tie.get("identical_outputs"):
                st.caption("The shipped OTI_UMAT.obj returns bit-identical arrays to the "
                           "verified build on the check path.")
            else:
                st.error(f"The shipped object is not tied to the verified build: {tie}")
        else:
            st.error("Verification failed — the verifier's diagnostic:")
            st.code(str(result.get("error") or verification.get("log")), language="text")
            if "nonfinite" in str(result.get("error")):
                st.caption(
                    "The provider's check path is the fixed seven-increment path of "
                    "docs/PROVIDER.md (strain increments up to 3.2e-3 per unit time). A "
                    "routine that cannot integrate it returns non-finite values. The "
                    "objects are built but not verified.")
    else:
        m2.metric("verification", "not run")
    st.markdown("**Shared with the collaborator** — the source never leaves your machine; "
                "only the compiled objects, the mapping and the report are shared.")
    shared = summary.get("shared") or {}
    d1, d2 = st.columns(2)
    for index, name in enumerate(collaborator.SHARED_FILES):
        with (d1 if index % 2 == 0 else d2):
            _download(Path(shared[name]["path"]) if name in shared else None, name,
                      f"pp_dl_{name}")
    with st.expander("Canonical provider outputs and the machine-readable record"):
        _download(Path(summary["canonical"]["object"]), "canonical object", "pp_dl_canonical_obj")
        _download(Path(summary["canonical"]["contract"]), "canonical contract", "pp_dl_canonical_json")
        st.caption("The same build from a terminal:")
        st.code(" ".join(shlex.quote(part) for part in build.get("command") or []), language="bash")
        st.json({key: summary.get(key) for key in ("exit_code", "build", "tie")}, expanded=False)
