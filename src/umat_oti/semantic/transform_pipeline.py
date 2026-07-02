"""End-to-end OTI-DDSDDE transform orchestrator.

One entry point that runs the whole flow on a UMAT and hands the LLM advisor its
tools — *see compiler errors, propose a fix, get it re-checked* — all behind the
deterministic verification gate (compile, and downstream the OTI-vs-FD check):

    parse (auto-discover deps)  -> derive config (from the UMAT's own driver)
    -> deterministic emit (LLM tie-breaks fuzzy type decisions)
    -> compile  -> LLM repair loop (gated by recompile)  -> [verify]

The exact transform stays deterministic; the LLM only proposes at the decision /
repair boundary, and nothing it proposes is accepted unless it compiles (and, with
a verify driver, matches finite differences). Works with no LLM (deterministic).
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .fortran_model import FortranProject
from .emit_lift import emit_oti_lift, derive_config
from .llm_advisor import repair_loop
from .seed_detect import detect_seed

_SUPPORT = ("master_parameters.f90", "real_utils.f90", "precision_.f90",
            "otim6n1.f90", "oti_intrinsics.f90", "oti_lapack.f90")


def transform_umat(*, entry_proc: str, entry_file: str, search_dirs: list[str],
                   seed: str | None = None, work_dir: str, lib_dir: str, oti_type: str = "ONUMM6N1",
                   driver_file: str | None = None, mode: str | None = None,
                   config: dict | None = None, advisor=None,
                   collect_name: str = "controls_collect_properties",
                   max_repair: int = 4, log=print) -> dict:
    os.makedirs(work_dir, exist_ok=True)

    # 1. parse + auto-discover dependency files via the USE graph
    proj = FortranProject().add_with_deps(entry_file, search_dirs=search_dirs)
    log(f"[parse]  {len(proj.files)} files, {len(proj.procedures)} procedures, "
        f"{len(proj.failed)} parse failures")

    # 1b. seed — auto-detect the strain seed when the caller did not state one.
    # Backward compatible: an explicit seed is used verbatim, never overridden.
    if seed is None:
        seed, conf, reason = detect_seed(proj, entry_proc)
        log(f"[seed]   auto-detected seed='{seed}' (confidence={conf}): {reason}")
        if seed is None:
            raise ValueError(
                f"could not auto-detect strain seed for entry '{entry_proc}'; "
                f"pass seed= explicitly. ({reason})")

    # 2. config — derive from the UMAT's own driver when available
    cfg = dict(config or {})
    if driver_file and not config:
        cfg = derive_config(proj, collect_name, driver_file, mode=mode)
        log(f"[config] auto-derived from driver: {cfg}")

    # 3. deterministic emit (advisor tie-breaks fuzzy type decisions, gated)
    libs = [os.path.join(lib_dir, "otim6n1.f90"), os.path.join(lib_dir, "oti_intrinsics.f90")]
    r = emit_oti_lift(proj, entry_proc, oti_type=oti_type, seed=seed, config=cfg,
                      library_files=libs, advisor=advisor)
    src = os.path.join(work_dir, "umat_oti_auto.f90")
    open(src, "w").write(r["source"])
    log(f"[emit]   {len(r['lift'])} procs lifted, {len(r['stubs'])} stubs, "
        f"oti_types={r['oti_types']}, config_needed={list(r['config_needed'])}")

    # 4. stage + compile the OTI support library (the gate's dependencies)
    for s in _SUPPORT:
        srcf = os.path.join(lib_dir, s)
        if os.path.exists(srcf):
            shutil.copy(srcf, work_dir)
    subprocess.run(["gfortran", "-O2", "-ffree-line-length-none", "-I.", "-c", *_SUPPORT],
                   cwd=work_dir, capture_output=True, text=True)

    # 5. compile the emitted transform; on failure run the LLM repair loop (gated)
    cmd = ["gfortran", "-O2", "-ffree-line-length-none", "-I.", "-c", os.path.basename(src)]
    pre = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
    n_err = sum("Error:" in ln for ln in (pre.stderr or "").splitlines())
    log(f"[compile] {n_err} errors on first deterministic emit")
    compiled = (n_err == 0)
    if not compiled and advisor is not None:
        compiled = repair_loop(src, cmd, advisor, max_rounds=max_repair, logger=log, cwd=work_dir)

    return {"source": src, "work_dir": work_dir, "compiled": compiled,
            "first_errors": n_err, **r}
