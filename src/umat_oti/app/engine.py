"""Tapenade-style single-page engine for the UMAT -> UMAT-OTI transform.

Mirrors Tapenade's flow: paste the source, name the head routine, choose the
variable to differentiate against, press one button, read the transformed source.
Two backends sit behind the one button and are chosen automatically:

  * single-file UMAT  -> the original config pipeline. The contract (seed, the
                         DDSDDE lines to replace, ntens) is AUTO-SCAFFOLDED from a
                         source scan, so the user never hand-writes it.
  * multi-file UMAT   -> the semantic pipeline, which discovers the dependency
                         files via the USE graph and auto-detects the seed.
"""
from __future__ import annotations

import json
import tempfile
import traceback
from pathlib import Path

import streamlit as st

ORANGE = "#F15A22"
LIB_DIR = "/tmp/oti_emit"          # where the OTI Fortran library lives (otim6n1.f90, ...)


# --------------------------------------------------------------------------- #
# source analysis helpers (single-file contract scaffolding)
# --------------------------------------------------------------------------- #
def _analyze(path: Path) -> dict:
    from umat_oti.fortran.scanner import analyze_fortran_source
    return analyze_fortran_source(path)


def _ddsdde_ranges(analysis: dict) -> list[str]:
    """Cluster the DDSDDE assignment line numbers into 'lo-hi' ranges."""
    lines = sorted({n for e in analysis.get("assignments_to_ddsdde", []) for n in e.get("line_numbers", [])})
    if not lines:
        return []
    ranges, start, prev = [], lines[0], lines[0]
    for n in lines[1:]:
        if n - prev > 25:                       # gap -> new cluster (elastic vs plastic block)
            ranges.append(f"{start}-{prev}"); start = n
        prev = n
    ranges.append(f"{start}-{prev}")
    return ranges


def _is_finite(analysis: dict) -> bool:
    fs = analysis.get("finite_strain", {})
    if isinstance(fs, dict):
        return bool(fs.get("dfgrd_driven_stress_update") or fs.get("executable_dfgrd_use"))
    return bool(fs)


def _is_fixed_form(text: str) -> bool:
    """Fixed-form (legacy F77 .f/.for) vs free-form (.f90). Fixed form has column-1
    C/* comments and statements indented to column 7; free form uses :: and trailing &."""
    import re
    fixed = len(re.findall(r"(?im)^[c*]\S|^ {6}[a-z0-9]", text))
    free = len(re.findall(r"(?m)::|&\s*$|^\s*subroutine", text))
    return fixed >= free


def suggest_ntens(text: str) -> tuple[int, str]:
    """Best-effort ntens (number of stress/strain components) from source clues, with a
    reason. ntens is fundamentally a runtime value Abaqus passes in, so this is a SUGGESTION
    the user can override; it defaults to 6 (3D) when the source carries no fixed size."""
    import re
    # 1. explicit PARAMETER NTENS=n  -> definitive
    m = re.search(r"(?i)parameter\s*\([^)]*\bntens\s*=\s*(\d+)", text)
    if m:
        return int(m.group(1)), f"PARAMETER NTENS={m.group(1)}"
    # 2. hard-coded DDSDDE(i,j) literal indices -> the largest index used
    idx = [int(x) for a, b in re.findall(r"(?i)\bDDSDDE\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", text)
           for x in (a, b)]
    if idx and max(idx) in (3, 4, 6):
        return max(idx), f"hard-coded DDSDDE indices up to {max(idx)}"
    # 3. a stress/strain array dimensioned to a literal in its declaration
    for name in ("STRESS", "DSTRAN", "STRAN", "DDSDDE"):
        m = re.search(rf"(?i)\b{name}\s*\(\s*(\d+)\s*[,)]", text)
        if m and int(m.group(1)) in (3, 4, 6):
            return int(m.group(1)), f"{name} dimensioned ({m.group(1)})"
    # 4. handles 3 shear components -> 3D
    if re.search(r"(?i)NSHR\s*\.EQ\.\s*3|NSHR\s*==\s*3", text):
        return 6, "handles NSHR=3 (3D)"
    return 6, "no fixed size in source; defaulting to 6 (3D)"


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #
def _head_and_called(source_text: str, head: str) -> str:
    """Keep the head UMAT and the subroutines it calls (transitively), with the head
    FIRST. A file with two routines (e.g. UHYPER then UMAT) otherwise places the DDSDDE
    extraction in the wrong routine; unrelated routines are dropped, used helpers kept."""
    import re
    lines = source_text.splitlines()
    blocks: dict[str, tuple[int, int]] = {}
    cur_name, cur = None, 0
    for i, l in enumerate(lines):
        m = re.match(r"(?i)\s*subroutine\s+(\w+)", l)
        if m:
            if cur_name is not None:
                blocks[cur_name] = (cur, i)
            cur_name, cur = m.group(1).lower(), i
    if cur_name is not None:
        blocks[cur_name] = (cur, len(lines))
    head = head.lower()
    if len(blocks) <= 1 or head not in blocks:
        return source_text
    keep, queue = {head}, [head]
    while queue:
        s, e = blocks[queue.pop()]
        for cm in re.finditer(r"(?i)\bcall\s+(\w+)", "\n".join(lines[s:e])):
            c = cm.group(1).lower()
            if c in blocks and c not in keep:
                keep.add(c); queue.append(c)
    order = [head] + [n for n in blocks if n in keep and n != head]
    return "\n".join(l for n in order for l in lines[blocks[n][0]:blocks[n][1]]) + "\n"


def _build_contract(name: str, seed: str, output: str, target: str, ntens: int, order: int,
                    src_path: Path) -> tuple[dict, bool]:
    """Auto-scaffold the contract from a source scan (src_path must already hold the
    cleaned source): full variable role classification + finite-strain correction."""
    from umat_oti.core.roles import suggest_variable_roles, role_summary
    analysis = _analyze(src_path)
    finite = _is_finite(analysis) if seed == "auto" else (seed == "DFGRD1")
    # The source text goes in so the classifier can apply Fortran's implicit
    # typing rule: an undeclared name in the integer range carries no
    # derivative, and promoting one turns index and parity arithmetic into
    # unsupported operations on a derived type.
    summ = role_summary(suggest_variable_roles(
        analysis, src_path.read_text(errors="replace")))
    promote = list(dict.fromkeys(summ["promoted_variables"] + [output] + (["DFGRD1"] if finite else [])))
    cfg = {
        "case_name": name,
        "jacobian": {"dependent": output, "independent": "DSTRAN", "target": target},
        "otis": {"ntens": int(ntens), "order": int(order)},
        "replace": {"ddsdde_block": _ddsdde_ranges(analysis)},
        "source": {"file": str(src_path)},
        "variables": {"seed": ["DSTRAN"], "promote": promote,
                      "constant": summ["constant_variables"], "real": summ["keep_real_variables"]},
    }
    if finite:                                       # the Abaqus finite-strain correction
        cfg["transformation_settings"] = {"seed_dfgrd1": True}
    return cfg, finite


def transform_single(source_text: str, name: str, seed: str, output: str, target: str,
                     ntens: int, order: int) -> dict:
    """Original config pipeline, with an auto-scaffolded contract."""
    from umat_oti.services.transformation import run_transformation
    cleaned = _head_and_called(source_text, name)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"{name}.f"
        src.write_text(cleaned)
        cfg, finite = _build_contract(name, seed, output, target, ntens, order, src)
        cfgpath = Path(td) / "contract.json"
        cfgpath.write_text(json.dumps(cfg, indent=2))
        report, _ = run_transformation(cfgpath, Path(td) / "out")
        ok = bool(report.get("transform_success"))
        transformed = ""
        ts = report.get("transformed_source")
        if ok and ts and Path(ts).exists():
            transformed = Path(ts).read_text(errors="replace")
        seed_disp = "DSTRAN + DFGRD1 finite-strain correction" if finite else "DSTRAN"
        return {"ok": ok, "pipeline": "single-file", "seed": seed_disp, "code": transformed,
                "report": report, "contract": cfg}


def validate_in_abaqus(source_text: str, name: str, seed: str, output: str, target: str,
                       ntens: int, order: int, abaqus_cmd: str, test_mode: str,
                       work_root: str, material_props=None) -> dict:
    """Transform to a persistent dir, then build the Abaqus validation workspace, run
    the ORIGINAL and OTI jobs, extract and compare DDSDDE. Returns the comparison."""
    from umat_oti.services.transformation import run_transformation
    from umat_oti.core.config_loader import load_project_config_json
    from umat_oti.validation.abaqus_runner import run_both_jobs, extract_results, abaqus_available
    from umat_oti.validation.compare_results import compare_validation_results
    from umat_oti.validation.job_builder import build_validation_workspace
    import shutil
    work = Path(work_root)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    src = work / f"{name}.f"
    src.write_text(_head_and_called(source_text, name))
    cfg, finite = _build_contract(name, seed, output, target, ntens, order, src)
    cfgpath = work / "contract.json"
    cfgpath.write_text(json.dumps(cfg, indent=2))
    summary, _ = run_transformation(cfgpath, work / "out")
    code = ""
    ts = summary.get("transformed_source")
    if ts and Path(ts).exists():
        code = Path(ts).read_text(errors="replace")
    if not summary.get("transform_success"):
        return {"stage": "transform_failed", "ok": False, "code": code, "report": summary}
    if not abaqus_available(abaqus_cmd):
        return {"stage": "abaqus_missing", "ok": False, "code": code,
                "message": f"Abaqus not found at '{abaqus_cmd}'. Set the correct path."}
    config = load_project_config_json(cfgpath.read_bytes(), origin_path=cfgpath)
    transform_dir = Path(str(summary.get("out_dir", ""))).resolve()
    transformed = Path(str(summary.get("transformed_source", ""))).resolve()
    vdir = transform_dir / "validation"
    build_validation_workspace(validation_dir=vdir, original_umat=src, transformed_umat=transformed,
                               generated_dir=transform_dir, project_config=config, ntens=int(ntens),
                               abaqus_command=abaqus_cmd, abaqus_modules="", run_prefix="",
                               material_test_mode=test_mode, run_compile_smoke=True,
                               material_props=material_props)
    run_both_jobs(vdir, abaqus_cmd, "", "", timeout_seconds=1800)
    extract_results(vdir, abaqus_cmd, "", "", timeout_seconds=600)
    compare_validation_results(vdir)                  # writes the full report files
    # Compare DDSDDE DIRECTLY from the extracted results. This is robust to the Abaqus
    # 2021/glibc teardown abort (signal 6 "buffer overflow" AFTER the analysis completes
    # and results are written) that otherwise masks a correct run as failed_execution.
    def _ddsdde(p: Path):
        if not p.exists():
            return None
        return json.loads(p.read_text(errors="replace")).get("final_ddsdde")
    orig = _ddsdde(vdir / "original_results.json")
    otis = _ddsdde(vdir / "otis_results.json")
    if not orig or not otis:
        return {"stage": "no_results", "ok": False, "code": code, "vdir": str(vdir),
                "message": "Abaqus ran but DDSDDE could not be extracted from one of the jobs."}
    cells = [(i, j) for i in range(len(orig)) for j in range(len(orig[i]))]
    mx = max(abs(orig[i][j] - otis[i][j]) for i, j in cells)
    denom = max((abs(orig[i][j]) for i, j in cells), default=0.0) or 1.0
    rel = mx / denom
    # Abaqus stores SDV field output in single precision, and DDSDDE is read back through
    # SDVs, so the comparison floor is float32 (~1e-6 relative). A genuine transform error
    # makes the tangent wrong by O(1) relative, so 1e-4 cleanly separates the two.
    return {"stage": "compared", "ok": True, "code": code, "vdir": str(vdir),
            "ddsdde_original": orig, "ddsdde_oti": otis,
            "max_abs_diff": mx, "max_rel_diff": rel, "match": rel < 1e-4}


def transform_multi(source_text: str, extra_files: list[tuple[str, str]], name: str,
                    seed: str, ntens: int, order: int) -> dict:
    """Semantic pipeline: discovers deps + auto-detects the seed."""
    from umat_oti.semantic.transform_pipeline import transform_umat
    with tempfile.TemporaryDirectory() as td:
        srcdir = Path(td) / "src"
        srcdir.mkdir()
        ext = ".f" if _is_fixed_form(source_text) else ".f90"   # preserve the source form
        entry = srcdir / f"{name}{ext}"
        entry.write_text(source_text)
        for fn, content in extra_files:
            (srcdir / Path(fn).name).write_text(content)
        out = Path(td) / "out"
        log: list[str] = []
        res = transform_umat(entry_proc=name, entry_file=str(entry), search_dirs=[str(srcdir)],
                             seed=(None if seed == "auto" else seed.lower()),
                             work_dir=str(out), lib_dir=LIB_DIR, advisor=None,
                             log=lambda m: log.append(str(m)))
        code = ""
        f = out / "umat_oti_auto.f90"
        if f.exists():
            code = f.read_text(errors="replace")
        ok = res.get("first_errors", 1) == 0
        seed_used = seed
        for line in log:                                # surface the auto-detected seed
            m = __import__("re").search(r"seed='([^']+)'", line)
            if m:
                seed_used = m.group(1)
        return {"ok": ok, "pipeline": "multi-file", "seed": seed_used,
                "code": code, "report": {"compile_errors": res.get("first_errors"), "log": log}}


# --------------------------------------------------------------------------- #
# render helpers
# --------------------------------------------------------------------------- #
def _render_transform(res: dict, head: str) -> None:
    badge = "✅" if res["ok"] else "⚠️"
    verb = "transformed" if res["ok"] else "did not fully transform"
    st.markdown(f"### {badge} {res['pipeline']} pipeline &mdash; {verb}  "
                f"<span style='color:#666'>(seed = <code>{res['seed']}</code>)</span>",
                unsafe_allow_html=True)
    if res.get("note"):
        st.caption("ℹ️ " + res["note"])
    if res["code"]:
        st.download_button("Download transformed UMAT", res["code"], file_name=f"{head}_oti.f")
        st.code(res["code"], language="fortran")
    else:
        st.warning("No transformed source was produced.")
    with st.expander("Report / log", expanded=not res["ok"]):
        st.json(res["report"])


def _render_verify(v: dict) -> None:
    stage = v.get("stage")
    if stage == "abaqus_missing":
        st.error(v.get("message", "Abaqus not found."))
    elif stage == "transform_failed":
        st.error("The transform for validation failed.")
        st.json(v.get("report", {}))
    elif stage == "no_results":
        st.warning(v.get("message", "Abaqus ran but no DDSDDE could be extracted."))
    elif stage == "compared":
        if v.get("match"):
            st.success(f"DDSDDE MATCHES the original analytical tangent in Abaqus  "
                       f"(max abs diff = {v['max_abs_diff']:.2e}, "
                       f"max rel diff = {v['max_rel_diff']:.2e}).")
        else:
            st.error(f"DDSDDE DIFFERS  (max abs diff = {v['max_abs_diff']:.2e}, "
                     f"max rel diff = {v['max_rel_diff']:.2e}).")
        st.caption("Original (analytical) DDSDDE")
        st.dataframe(v["ddsdde_original"])
        st.caption("OTI DDSDDE")
        st.dataframe(v["ddsdde_oti"])
        st.caption("Agreement is to single precision because Abaqus stores state-variable (SDV) field "
                   "output in float32, and DDSDDE is read back through SDVs; the OTI computation itself "
                   "is double precision. Abaqus 2021 here also emits a harmless 'buffer overflow' abort "
                   "at process exit AFTER results are written, which does not affect this comparison.")
    else:
        st.warning("Abaqus verification did not complete.")
        st.json(v or {})


# --------------------------------------------------------------------------- #
# page
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(page_title="UMAT-OTI Engine", layout="wide")
    st.markdown(
        f"<h1 style='color:{ORANGE};margin-bottom:0'>UMAT &rarr; UMAT-OTI</h1>"
        "<div style='font-size:1.1rem;color:#444;margin-top:0'>Automatic consistent-tangent engine "
        "&mdash; transform an Abaqus UMAT so it computes <b>DDSDDE</b> exactly by OTI / HYPAD "
        "automatic differentiation.</div><hr>", unsafe_allow_html=True)

    col_in, col_out = st.columns([1, 1])

    with col_in:
        st.subheader("Input")
        up = st.file_uploader("UMAT source file (optional)", type=["f", "for", "f90", "ftn", "txt"])
        default_src = up.read().decode(errors="replace") if up is not None else ""
        source_text = st.text_area("UMAT source", value=default_src, height=320,
                                   placeholder="Paste your UMAT (SUBROUTINE UMAT ...) here, or upload a file above.")
        extra = st.file_uploader("Dependency files (multi-file UMATs only)",
                                 type=["f", "for", "f90", "ftn"], accept_multiple_files=True)

        st.markdown("**Differentiation**")
        head = st.text_input("Head routine", value="umat", help="The UMAT subroutine to transform.")
        seed_label = st.selectbox("Differentiate STRESS with respect to",
                                  ["Auto-detect", "DSTRAN  (small strain)", "DFGRD1  (finite strain)"])
        seed = {"Auto-detect": "auto", "DSTRAN  (small strain)": "DSTRAN",
                "DFGRD1  (finite strain)": "DFGRD1"}[seed_label]
        output = st.text_input("Output (dependent)", value="STRESS")
        target = st.text_input("Jacobian target", value="DDSDDE")

        # auto-suggest ntens from the source; reset to the suggestion when the source changes,
        # but let a manual override stick (the widget owns session_state["ntens_val"] after).
        sug_n, sug_why = suggest_ntens(source_text) if source_text.strip() else (6, "")
        src_key = str(hash(source_text))
        if st.session_state.get("_ntens_src") != src_key:
            st.session_state["_ntens_src"] = src_key
            st.session_state["ntens_val"] = sug_n
        ntens = st.number_input("ntens (directions)", min_value=1, max_value=9, step=1, key="ntens_val")
        if source_text.strip():
            st.caption(f"Auto-detected ntens = {sug_n} ({sug_why}). Override above if your analysis differs.")
        order = st.number_input("order", min_value=1, max_value=4, value=1, step=1)

        pipe = st.radio("Pipeline", ["Auto", "Single-file", "Multi-file"],
                        help="Auto: multi-file if dependency files are given, otherwise single-file.")

        go = st.button("Transform")

        st.markdown("**Verify in Abaqus** (optional, after transforming)")
        abaqus_cmd = st.text_input("Abaqus command / path", value="abaqus",
                                   help="Per machine: 'abaqus', 'abq2023', or a full path to the launcher.")
        test_mode = st.selectbox("Material test", ["single element tension", "single element shear"])
        verify = st.button("Verify in Abaqus")

    with col_out:
        st.subheader("Output")
        extra_files = [(f.name, f.read().decode(errors="replace")) for f in (extra or [])]
        use_multi = (pipe == "Multi-file") or (pipe == "Auto" and len(extra_files) > 0)

        # ---- Transform button: run, store result, clear any stale verification ---- #
        if go:
            st.session_state.pop("verify", None)
            if not source_text.strip():
                st.session_state.pop("res", None)
                st.error("No source provided.")
            else:
                res = None
                with st.spinner("Transforming ..."):
                    try:
                        if use_multi:
                            res = transform_multi(source_text, extra_files, head, seed, ntens, order)
                        else:
                            res = transform_single(source_text, head, seed, output, target, ntens, order)
                            # Fallback: the single-file pipeline only seeds DSTRAN, so a pure
                            # finite-strain UMAT blocked there is retried via the semantic pipeline.
                            if not res["ok"] and pipe != "Single-file":
                                alt = transform_multi(source_text, extra_files, head, seed, ntens, order)
                                if alt["ok"]:
                                    alt["note"] = ("single-file pipeline was blocked (DSTRAN-only); "
                                                   "transformed via the multi-file / semantic pipeline instead.")
                                    res = alt
                    except Exception:                  # never crash the page
                        st.error("The transform raised an error:")
                        st.code(traceback.format_exc())
                        res = None
                if res is not None:
                    st.session_state["res"] = res
                    st.session_state["tx"] = {"source_text": source_text, "head": head, "seed": seed,
                                              "output": output, "target": target, "ntens": int(ntens),
                                              "order": int(order), "use_multi": use_multi}

        # ---- Verify button: run Abaqus on the LAST transform, store the comparison -- #
        if verify:
            res = st.session_state.get("res")
            tx = st.session_state.get("tx")
            if not res or not res.get("ok") or not tx:
                st.warning("Press **Transform** first &mdash; a successful transform is required "
                           "before verifying.")
            elif tx["use_multi"]:
                st.info("Abaqus DDSDDE verification currently supports single-file UMATs.")
            else:
                v = None
                with st.spinner("Compiling and running both UMATs in Abaqus (a few minutes) ..."):
                    try:
                        v = validate_in_abaqus(tx["source_text"], tx["head"], tx["seed"], tx["output"],
                                               tx["target"], tx["ntens"], tx["order"], abaqus_cmd,
                                               test_mode, "/tmp/oti_engine_abq")
                    except Exception:
                        st.error("Abaqus verification raised an error:")
                        st.code(traceback.format_exc()); v = None
                if v is not None:
                    st.session_state["verify"] = v

        # ---- Render the stored transform, then the stored verification ---- #
        res = st.session_state.get("res")
        if not res:
            st.info("Fill the form on the left and press **Transform**. Then press "
                    "**Verify in Abaqus** to run both UMATs in Abaqus and compare DDSDDE.")
            return
        _render_transform(res, st.session_state.get("tx", {}).get("head", "umat"))
        v = st.session_state.get("verify")
        if v is not None:
            st.markdown("---")
            st.markdown(f"#### <span style='color:{ORANGE}'>Abaqus verification</span>",
                        unsafe_allow_html=True)
            _render_verify(v)


if __name__ == "__main__":
    main()
