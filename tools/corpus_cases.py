#!/usr/bin/env python3
"""Regression cases: freeze a routine-level-verified UMAT, and check it later.

A case (``umat/cases/<id>/``) freezes ONE verified (source, loading paths)
pair: the source identity and licence, the driver inputs of every frozen
loading path, the ORIGINAL routine's history, the FD-of-the-original
reference value and tolerance of every DDSDDE entry at every judged state,
the error the transformed build had when frozen, and the fingerprints of the
transform and of the harness that produced the evidence. See
``docs/REGRESSION_CASES.md`` and ``corpus_campaign/design/REGRESSION_ARCHITECTURE.md``.

    PYTHONHASHSEED=0 python tools/corpus_cases.py freeze --key c7bf17b21519e33da0b7bbb1 --tier offline
    PYTHONHASHSEED=0 python tools/corpus_cases.py freeze --model parameter_sensitivity/models/m3_j2 --tier ci
    PYTHONHASHSEED=0 python tools/corpus_cases.py check --tier ci            # R and P
    PYTHONHASHSEED=0 python tools/corpus_cases.py check --tier offline --replay --only <id>
    python tools/corpus_cases.py fetch <id>          # source of a non-redistributable case
    python tools/corpus_cases.py verify-assets       # re-hash every CAS object a case lists

Checks (numbers only; generated Fortran is never text-diffed):

* R (``--regenerate``): transform the ORIGINAL source with the CURRENT code
  (``tools/transform_all.transform_one``: same recipe, job-layout gfortran
  compile), build it with the harness's real driver, rerun every frozen path.
* P (``--replay``): build the preserved transformed units (in the case when
  the source is redistributable, otherwise from ``corpus_assets``) and rerun.

Both are compared against the frozen ORIGINAL history (primal), the frozen FD
reference entries (tangent) and themselves (hidden state: the unperturbed call
replayed with restored state must be bit-identical). A check FAILS on a
tolerance breach, a coverage shrink (a frozen judged state that is no longer
judged), drift (error > 10x the frozen error), a changed tolerance rule, or a
mutant canary that is NOT rejected.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

CASES = REPO / "umat" / "cases"
CANARY_DIR = CASES / "_canaries"
WORKSPACE = Path(os.environ.get("UMAT_OTI_WORKSPACE", str(Path.home() / "softwarex_work")))
ASSETS = Path(os.environ.get("UMAT_CASE_ASSETS", str(WORKSPACE / "corpus_assets")))
DISCOVERY_CACHE = WORKSPACE / "discovery_cache"
MANIFEST = REPO / "paper_results/corpus/manifest/corpus_manifest.json"
SCHEMA = "umat-oti/regression-case/1"
FEATURES = ("primal_stress_state", "ddsdde")

# ---------------------------------------------------------------------------
# the one global rule (Vera B1 amendment 2: tolerances are never per case)
# ---------------------------------------------------------------------------

RULE = {
    "primal": {"comparator": "umat_oti.corpus_features.fd.judge_primal (row-scaled)",
               "rtol": 1e-10, "atol": 1e-14,
               "outputs": "STRESS and STATEV of the build under test vs the frozen ORIGINAL "
                          "history, every increment of every frozen path"},
    "tangent": {"comparator": "|DDSDDE_e - D_e| <= tau_e (pass entries), |DDSDDE_e| <= tau_e "
                              "(structural-zero entries); D_e, tau_e frozen from the harness",
                "entry_rule": "harness.TOLERANCE_RULE (FD-only plateau >= 3 steps, rtol 1e-6, "
                              "resolution 1e-3) evaluated ONCE at freeze on the ORIGINAL"},
    "hidden_state": "the unperturbed call replayed with restored incoming state (driver 'L' "
                    "h=0 and 'R' records) is bit-identical to the history call",
    "coverage": "every frozen judged state is judged again: output present and finite, primal "
                "agrees at it and at every earlier increment, no hidden-state difference up to "
                "it, and (when the ORIGINAL is rebuilt) the ORIGINAL reproduces its frozen history",
    "drift": {"factor": 10.0, "floor_error_over_tolerance": 1e-3,
              "rule": "fail when error/tolerance > factor x max(frozen error/tolerance, floor)"},
    "canaries": {"tangent_column_scale": 1e-4, "tangent_dropped_small_entry": True,
                 "primal_scale": 1e-6, "hidden_state_toy": "umat/cases/_canaries/hidden_state_toy.f"},
}


def rule_id() -> str:
    from umat_oti.corpus_features import fd
    from umat_oti.corpus_features.harness import TOLERANCE_RULE
    material = json.dumps({"rule": RULE, "harness_rule": TOLERANCE_RULE,
                           "fd": [fd.DEFAULT_RTOL, fd.MIN_PLATEAU, fd.RESOLUTION,
                                  list(fd.DEFAULT_LADDER)]}, sort_keys=True)
    return "case-rule/1-" + hashlib.sha256(material.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def write_gz_json(path: Path, payload) -> None:
    """Deterministic gzip (mtime 0): the same reference gives the same bytes."""
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())


def scrub(value):
    """No machine paths in committed case files: roots become <umat>/<workspace>/<home>."""
    if isinstance(value, str):
        for root, name in ((str(REPO), "<umat>"), (str(WORKSPACE), "<workspace>"),
                           (str(Path.home()), "<home>"), (tempfile.gettempdir(), "<tmp>")):
            value = value.replace(root, name)
        return value
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def read_gz_json(path: Path):
    return json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))


def material_id(source_id: str) -> str:
    """Same rule as tools/promote_verified_umats.material_id (kept identical)."""
    path = Path(source_id)
    owner_repo = (path.parts[0] if path.parts else "unknown").replace("__", "-")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()
    return f"{owner_repo.lower()}--{stem}--{hashlib.sha256(source_id.encode()).hexdigest()[:8]}"


def toolchain() -> dict:
    def first_line(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()[0]
        except Exception:                                            # noqa: BLE001
            return None
    return {"python": platform.python_version(), "numpy": np.__version__,
            "gfortran": first_line(["gfortran", "--version"]), "platform": platform.platform()}


def fingerprints() -> dict:
    from umat_oti.store.transform_store import harness_fingerprint, transform_fingerprint
    return {"transform_fingerprint": transform_fingerprint(),
            "harness_fingerprint": harness_fingerprint()}


# ---------------------------------------------------------------------------
# content-addressed asset store (corpus_assets)
# ---------------------------------------------------------------------------

def cas_object(sha: str, root: Path = None) -> Path:
    root = ASSETS if root is None else root
    return root / "objects" / "sha256" / sha[:2] / sha[2:4] / sha


def cas_put(path: Path, root: Path = None) -> str:
    data = Path(path).read_bytes()
    sha = sha256_bytes(data)
    target = cas_object(sha, root)
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{os.getpid()}.partial")   # parallel freezes
        tmp.write_bytes(data)
        os.replace(tmp, target)
        target.chmod(0o444)
    return sha


def cas_tree(case_id: str, fingerprint: str, files: list, root: Path = None) -> str:
    """files: [{"path", "sha256", "bytes", "role"}] -> tree sha (over canonical JSON)."""
    root = ASSETS if root is None else root
    tree = {"case_id": case_id, "evidence_fingerprint": fingerprint,
            "files": sorted(files, key=lambda f: f["path"])}
    blob = json.dumps(tree, sort_keys=True, separators=(",", ":")).encode()
    sha = sha256_bytes(blob)
    (root / "trees").mkdir(parents=True, exist_ok=True)
    (root / "trees" / f"{sha}.json").write_bytes(blob)
    with (root / "log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"date": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "case_id": case_id, "tree": sha, "command": " ".join(sys.argv),
                                 "who": os.environ.get("USER", "")}) + "\n")
    return sha


def verify_assets(root: Path = None) -> list:
    root = ASSETS if root is None else root
    problems = []
    for case_json in sorted(CASES.glob("*/case.json")):
        case = json.loads(case_json.read_text())
        tree_sha = (case.get("assets") or {}).get("tree_sha256")
        if not tree_sha:
            continue
        tree_path = root / "trees" / f"{tree_sha}.json"
        if not tree_path.is_file():
            problems.append(f"{case['case_id']}: tree {tree_sha} missing")
            continue
        if sha256_file(tree_path) != tree_sha:
            problems.append(f"{case['case_id']}: tree {tree_sha} corrupted")
            continue
        for item in json.loads(tree_path.read_text())["files"]:
            obj = cas_object(item["sha256"], root)
            if not obj.is_file():
                problems.append(f"{case['case_id']}: {item['path']} missing ({item['sha256']})")
            elif sha256_file(obj) != item["sha256"]:
                problems.append(f"{case['case_id']}: {item['path']} corrupted")
    return problems


# ---------------------------------------------------------------------------
# licence (D-2) and source identity
# ---------------------------------------------------------------------------

#: in-repo models: THIRD_PARTY_NOTICES.md 2a (MIT adaptations of jgomezc1/ABAQUS-US) and 2c
CURATED_MIT = {"sweep_real_ECL_TEMP", "sweep_real_PCO", "sweep_eco"}


def curated_licence(name: str) -> dict:
    if name in CURATED_MIT:
        return {"spdx": "MIT", "scope": "file (adaptation)",
                "basis": "THIRD_PARTY_NOTICES.md section 2a: adaptation of jgomezc1/ABAQUS-US "
                         "(MIT, LICENSE.md upstream), notice kept in this repository",
                "redistribution": "permitted",
                "redistribution_basis": "MIT is GPL-3.0-only-compatible (D-2); the file is already "
                                        "distributed in this repository with its notice"}
    return {"spdx": "GPL-3.0-only", "scope": "file",
            "basis": "THIRD_PARTY_NOTICES.md section 2c: the UMAT-OTI authors' own implementation",
            "redistribution": "permitted",
            "redistribution_basis": "project-owned source, distributed under this repository's licence"}


def corpus_licence(source_id: str) -> dict:
    """The corpus manifest's licence determination (scout), applied under D-2."""
    if MANIFEST.is_file():
        for row in json.loads(MANIFEST.read_text())["rows"]:
            if row.get("source_id") == source_id:
                lic = row.get("license") or {}
                status = lic.get("redistribution") or "unknown"
                if status == "permitted" and not lic.get("licence_file"):
                    status = "unknown"           # D-2: a licence FILE is required
                return {"spdx": lic.get("spdx"), "scope": lic.get("scope"),
                        "licence_file": lic.get("licence_file"),
                        "basis": lic.get("spdx_metadata_source") or "",
                        "redistribution": status,
                        "redistribution_basis": lic.get("redistribution_basis") or ""}
    return {"spdx": None, "redistribution": "unknown",
            "redistribution_basis": "no corpus manifest row for this source"}


# ---------------------------------------------------------------------------
# harness capture (freeze only): the per-entry FD reference the harness used
# ---------------------------------------------------------------------------

def _install_capture():
    """Wrap FeatureTally.add/as_dict and fd.judge_column so that every ddsdde
    record carries ``_case_capture``: per state and input column, the output
    names, the FD reference D_e, tolerance tau_e, entry codes and the value
    under test exactly as the harness judged them. Nothing else changes."""
    from umat_oti.corpus_features import fd
    from umat_oti.corpus_features import harness as H
    if getattr(H.FeatureTally, "_case_capture_installed", False):
        return
    orig_add, orig_as_dict, orig_judge = H.FeatureTally.add, H.FeatureTally.as_dict, fd.judge_column
    stack: list = []

    def judge(*args, **kwargs):
        verdict = orig_judge(*args, **kwargs)
        if stack:
            stack[-1].append(verdict)
        return verdict

    def add(self, inc, wrt, column, oti, output_names, magnitude, undefined=None,
            probe=False, **keywords):
        # every other keyword goes through unchanged, whatever FeatureTally.add
        # takes now (G4/G10 added kinematic_input, block_derivative, double_zero)
        call = lambda: orig_add(self, inc, wrt, column, oti, output_names, magnitude,  # noqa: E731
                                undefined=undefined, probe=probe, **keywords)
        if self.feature != "ddsdde" or probe:
            return call()
        names, values = list(output_names), np.asarray(oti, float)
        if undefined is not None and np.any(undefined):
            keep = ~np.asarray(undefined, bool)
            names, values = [n for n, k in zip(names, keep) if k], values[keep]
        stack.append([])
        try:
            result = call()
        finally:
            got = stack.pop()
        cap = self.__dict__.setdefault("_cap", {})
        if got:
            v = got[-1]
            cap.setdefault(int(inc), {})[wrt] = {
                "names": names, "D": [float(x) for x in v.reference],
                "tau": [float(x) for x in v.tolerance], "codes": list(v.codes),
                "oti": values.tolist()}
        else:
            cap.setdefault(int(inc), {})[wrt] = {"nonsmooth": True}
        return result

    def as_dict(self):
        payload = orig_as_dict(self)
        if self.feature == "ddsdde":
            judged = sorted(int(k) for k, c in self.states.items()
                            if c["columns"] and not c["nonsmooth"] and not c["unresolved"])
            payload["_case_capture"] = {"judged": judged,
                                        "states": {str(k): v for k, v in
                                                   getattr(self, "_cap", {}).items()}}
        return payload

    H.FeatureTally.add, H.FeatureTally.as_dict = add, as_dict
    fd.judge_column = judge
    H.FeatureTally._case_capture_installed = True


_NAME = re.compile(r"DDSDDE\((\d+),(\d+)\)")


def frozen_states_from_capture(capture: dict) -> list:
    """[{"inc", "entries": [[i, j, D, tau, code], ...]}] over the judged states."""
    states = []
    for inc in capture["judged"]:
        entries = []
        for wrt, col in sorted(capture["states"][str(inc)].items()):
            if col.get("nonsmooth"):
                raise ValueError(f"judged state {inc} has a nonsmooth column {wrt}")
            for name, d, tau, code in zip(col["names"], col["D"], col["tau"], col["codes"]):
                if code not in ("pass", "zero_pass"):
                    raise ValueError(f"judged state {inc}: entry {name} has code {code}")
                i, j = map(int, _NAME.match(name).groups())
                entries.append([i, j, d, tau, code])
        states.append({"inc": int(inc), "entries": entries})
    return states


# ---------------------------------------------------------------------------
# comparators (pure: observation + frozen reference -> verdict). The canaries
# call exactly these on mutated observations.
# ---------------------------------------------------------------------------

def _rows(base: dict, n: int, name: str, width: int) -> np.ndarray:
    out = np.full((n, width), np.nan)
    for inc in range(1, n + 1):
        if inc in base:
            out[inc - 1] = np.asarray(base[inc][name], float).reshape(-1)[:width]
    return out


def statev_rows(base: dict, path_ref: dict) -> np.ndarray:
    """STATEV rows of the DEFINED slots only (D-12: undefined_in_original slots are never compared)."""
    n, nx = path_ref["n_inc"], path_ref["nstatv"]
    if not nx:
        return np.zeros((n, 0))
    rows = _rows(base, n, "statev", nx)
    keep = path_ref.get("statev_defined")
    return rows if keep is None else rows[:, [l - 1 for l in keep]]


def compare_primal(stress: np.ndarray, statev: np.ndarray, ref: dict) -> dict:
    """Row-scaled primal rule (fd.judge_primal) plus the per-increment agreement
    that coverage needs (same scale formula)."""
    from umat_oti.corpus_features import fd
    rtol, atol = RULE["primal"]["rtol"], RULE["primal"]["atol"]
    ok_rows = np.ones(stress.shape[0], bool)
    ratio, verdicts = 0.0, {}
    for name, a, b in (("stress", stress, np.asarray(ref["stress"], float)),
                       ("statev", statev, np.asarray(ref["statev"], float))):
        if b.size == 0 or b.shape[1] == 0:
            continue
        v = fd.judge_primal(a, b, rtol=rtol, atol=atol)
        verdicts[name] = {k: v.get(k) for k in ("agrees", "max_abs", "max_rel",
                                                "max_error_over_tolerance", "reason")}
        if not np.all(np.isfinite(a) | ~np.isfinite(b)) or a.shape != b.shape:
            ok_rows[:] = False
            ratio = float("inf")
            continue
        mag = np.abs(np.nan_to_num(b))
        scale = np.maximum(mag.max(axis=1, keepdims=True), 1e-3 * float(mag.max(initial=0.0)))
        err = np.abs(np.nan_to_num(a, nan=np.inf) - np.nan_to_num(b))
        err = np.where(~np.isfinite(a) & ~np.isfinite(b), 0.0, err)
        tol = atol + rtol * scale
        ok_rows &= np.all(err <= tol, axis=1)
        ratio = max(ratio, float((err / tol).max(initial=0.0)))
    return {"agrees": bool(ok_rows.all()), "ok_rows": ok_rows, "error_over_tolerance": ratio,
            "detail": verdicts}


def compare_tangent(ddsdde: dict, states: list) -> dict:
    """ddsdde: inc -> (ntens, ntens) array. states: frozen judged states."""
    breaches, ratio, judged, nonfinite = [], 0.0, [], []
    for state in states:
        inc = state["inc"]
        if inc not in ddsdde:
            nonfinite.append(inc)
            continue
        matrix = np.asarray(ddsdde[inc], float)
        finite = True
        for i, j, d, tau, code in state["entries"]:
            value = float(matrix[i - 1, j - 1])
            if not np.isfinite(value):
                finite = False
                breaches.append({"inc": inc, "entry": f"DDSDDE({i},{j})", "value": None,
                                 "reference": d, "tolerance": tau, "why": "non-finite"})
                continue
            if code == "zero_pass":
                # a structural zero: the value under test must be within tau of zero AND the
                # stored FD reference must itself still be a zero within tau -- a frozen D_e
                # moved off zero is a reference breach, never silently ignored
                err = max(abs(value), abs(d))
            else:
                err = abs(value - d)
            r = err / tau if tau > 0 else (0.0 if err == 0 else float("inf"))
            ratio = max(ratio, r)
            if err > tau:
                breaches.append({"inc": inc, "entry": f"DDSDDE({i},{j})", "value": value,
                                 "reference": d, "tolerance": tau, "error": err})
        (judged if finite else nonfinite).append(inc)
    return {"agrees": not breaches, "breaches": breaches[:20], "n_breaches": len(breaches),
            "error_over_tolerance": ratio, "judged_incs": judged, "nonfinite_incs": nonfinite}


def compare_hidden(run, statev_defined=None) -> dict:
    """Incs where a restored-state replay of the unperturbed call differs
    (STRESS, DDSDDE and the DEFINED STATEV slots, bit for bit)."""
    def sv(x):
        x = np.asarray(x, float)
        return x if statev_defined is None else x[[l - 1 for l in statev_defined]]
    bad = set()
    for (inc, _ip, _sign), (stress, statev, _p) in run.local.items():
        b = run.base.get(inc)
        if b is None or not (np.array_equal(stress, b["stress"], equal_nan=True)
                             and np.array_equal(sv(statev), sv(b["statev"]), equal_nan=True)):
            bad.add(inc)
    for inc, r in run.replay.items():
        b = run.base.get(inc)
        if b is None or any(not np.array_equal(np.asarray(r[k]), np.asarray(b[k]), equal_nan=True)
                            for k in ("stress", "ddsdde")) \
                or not np.array_equal(sv(r["statev"]), sv(b["statev"]), equal_nan=True):
            bad.add(inc)
    probed = sorted(set(k[0] for k in run.local) | set(run.replay))
    return {"agrees": not bad and bool(probed), "differs_at": sorted(bad), "probed": len(probed)}


def judge_path(path_ref: dict, run, original_run=None) -> dict:
    """Every comparator on one path; returns verdict incl. coverage."""
    n, nt, nx = path_ref["n_inc"], path_ref["ntens"], path_ref["nstatv"]
    primal = compare_primal(_rows(run.base, n, "stress", nt), statev_rows(run.base, path_ref),
                            path_ref["original"])
    tangent = compare_tangent({k: v["ddsdde"] for k, v in run.base.items()}, path_ref["judged"])
    hidden = compare_hidden(run, path_ref.get("statev_defined"))
    reproduced = None
    if original_run is not None:
        reproduced = compare_primal(_rows(original_run.base, n, "stress", nt),
                                    statev_rows(original_run.base, path_ref), path_ref["original"])
    # coverage: a frozen judged state is judged now only if everything up to it holds
    lost = {}
    hidden_first = min(hidden["differs_at"]) if hidden["differs_at"] else None
    for state in path_ref["judged"]:
        inc, why = state["inc"], []
        if inc not in tangent["judged_incs"]:
            why.append("output missing or non-finite")
        if not primal["ok_rows"][:inc].all():
            why.append("primal disagrees at or before this increment")
        if hidden_first is not None and hidden_first <= inc:
            why.append("hidden-state replay differs at or before this increment")
        if reproduced is not None and not reproduced["ok_rows"][:inc].all():
            why.append("the ORIGINAL no longer reproduces its frozen history")
        if why:
            lost[inc] = why
    return {"primal": {k: v for k, v in primal.items() if k != "ok_rows"},
            "tangent": tangent, "hidden_state": hidden,
            "original_reproduced": None if reproduced is None
            else {k: v for k, v in reproduced.items() if k != "ok_rows"},
            "coverage": {"frozen": len(path_ref["judged"]),
                         "judged": len(path_ref["judged"]) - len(lost),
                         "lost": {str(k): v for k, v in lost.items()}}}


def failures_of(verdicts: dict, frozen_errors: dict) -> list:
    """verdicts: path -> judge_path result. frozen_errors: path -> {primal, tangent}."""
    out = []
    factor, floor = RULE["drift"]["factor"], RULE["drift"]["floor_error_over_tolerance"]
    for name, v in verdicts.items():
        if not v["primal"]["agrees"]:
            out.append({"kind": "tolerance", "path": name, "comparator": "primal",
                        "detail": v["primal"]["detail"]})
        if not v["tangent"]["agrees"]:
            out.append({"kind": "tolerance", "path": name, "comparator": "tangent",
                        "detail": v["tangent"]["breaches"][:5]})
        if not v["hidden_state"]["agrees"]:
            out.append({"kind": "hidden_state", "path": name, "detail": v["hidden_state"]})
        if v["coverage"]["lost"]:
            out.append({"kind": "coverage_shrank", "path": name,
                        "detail": f"{v['coverage']['judged']}/{v['coverage']['frozen']} frozen "
                                  f"states judged; lost: {dict(list(v['coverage']['lost'].items())[:3])}"})
        frozen = frozen_errors.get(name) or {}
        for comp in ("primal", "tangent"):
            now = v[comp]["error_over_tolerance"]
            limit = factor * max(float(frozen.get(comp, 0.0)), floor)
            if now > limit:
                out.append({"kind": "drift", "path": name, "comparator": comp,
                            "detail": f"error/tolerance {now:.3e} > {factor:g} x "
                                      f"max(frozen {float(frozen.get(comp, 0.0)):.3e}, {floor:g})"})
    return out


# ---------------------------------------------------------------------------
# mutant canaries
# ---------------------------------------------------------------------------

class _Run:
    """A RealOutput-like view whose arrays can be mutated without touching the original."""

    def __init__(self, run):
        self.base = {k: {f: np.array(v[f], float, copy=True) if isinstance(v[f], np.ndarray)
                         else v[f] for f in v} for k, v in run.base.items()}
        self.local = dict(run.local)
        self.replay = dict(run.replay)


def data_canaries(ref: dict, runs: dict) -> list:
    """Mutants of the observed build, judged by the same comparators. Each must be REJECTED."""
    results = []
    paths = [p for p in ref["paths"] if p["name"] in runs]
    if not paths:
        return [{"canary": "none", "rejected": False, "why": "no path ran"}]
    # 1. a DDSDDE column scaled by (1 + 1e-4): the column with the largest |D|
    eps = RULE["canaries"]["tangent_column_scale"]
    rejected = []
    for p in paths:
        best = max(((abs(e[2]), e[1]) for s in p["judged"] for e in s["entries"]), default=None)
        if best is None:
            continue
        j = best[1]
        mutant = _Run(runs[p["name"]])
        for v in mutant.base.values():
            v["ddsdde"][:, j - 1] *= (1.0 + eps)
        rejected.append(not compare_tangent({k: v["ddsdde"] for k, v in mutant.base.items()},
                                            p["judged"])["agrees"])
    results.append({"canary": f"tangent: DDSDDE column x (1+{eps:g})", "comparator": "tangent",
                    "rejected": bool(rejected) and all(rejected),
                    "per_path_rejected": rejected})
    # 2. the smallest nonzero-reference ('pass') entry dropped (set to 0)
    rejected = []
    for p in paths:
        small = min(((abs(e[2]), e[0], e[1]) for s in p["judged"] for e in s["entries"]
                     if e[4] == "pass" and e[2] != 0.0), default=None)
        if small is None:
            continue
        _, i, j = small
        mutant = _Run(runs[p["name"]])
        for v in mutant.base.values():
            v["ddsdde"][i - 1, j - 1] = 0.0
        rejected.append(not compare_tangent({k: v["ddsdde"] for k, v in mutant.base.items()},
                                            p["judged"])["agrees"])
    results.append({"canary": "tangent: smallest resolved nonzero entry dropped",
                    "comparator": "tangent", "rejected": bool(rejected) and all(rejected),
                    "per_path_rejected": rejected})
    # 3. primal: STRESS scaled by (1 + 1e-6)
    eps = RULE["canaries"]["primal_scale"]
    rejected = []
    for p in paths:
        mutant = _Run(runs[p["name"]])
        changed = False
        for v in mutant.base.values():
            scaled = v["stress"] * (1.0 + eps)
            changed |= not np.array_equal(scaled, v["stress"])
            v["stress"] = scaled
        if not changed:          # STRESS identically zero on this path: not a mutant here
            continue
        rejected.append(not compare_primal(_rows(mutant.base, p["n_inc"], "stress", p["ntens"]),
                                           statev_rows(mutant.base, p), p["original"])["agrees"])
    results.append({"canary": f"primal: STRESS x (1+{eps:g})", "comparator": "primal",
                    "rejected": bool(rejected) and all(rejected), "per_path_rejected": rejected})
    return results


def hidden_state_canary(work: Path) -> dict:
    """The SAVE-counter toy must be rejected by compare_hidden; the same toy
    with the counter switched off (control) must be accepted -- otherwise the
    comparator rejects everything and proves nothing."""
    from umat_oti.corpus_features import drivers as dv
    source = CANARY_DIR / "hidden_state_toy.f"
    text = source.read_text()
    build = dv.build_real(work / "toy_build", [source], text, sdvini=False,
                          unit_flags=[["-ffixed-form"]])
    if not build.ok:
        return {"canary": "hidden-state toy", "comparator": "hidden_state", "rejected": False,
                "why": f"toy did not build: {build.reason}"}
    out = {}
    for label, flag in (("toy", 1.0), ("control", 0.0)):
        incs = [((1e-4 * (k + 1), 0, 0, 0, 0, 0), np.eye(3), np.eye(3), np.eye(3), 0.1, 0.0, 0.0)
                for k in range(3)]
        config = dv.RunConfig(ntens=6, nstatv=1, nprops=2, ndi=3, nshr=3, props=[1000.0, flag],
                              statev0=[0.0], cmname="TOY", increments=incs)
        run = _run_driver(build, work / label, config=config, ntens=6, nstatv=1)
        out[label] = compare_hidden(run)["agrees"] if run is not None else None
    return {"canary": "hidden-state toy (SAVE counter)", "comparator": "hidden_state",
            "rejected": out.get("toy") is False and out.get("control") is True,
            "toy_accepted": out.get("toy"), "control_accepted": out.get("control")}


# ---------------------------------------------------------------------------
# building and running
# ---------------------------------------------------------------------------

def _run_driver(build, work: Path, config_text: Optional[str] = None, *, config=None,
                ntens: int, nstatv: int):
    """Run the harness's real driver once: the history plus one h=0 local
    perturbation (the restored-state replay used by the hidden-state comparator)."""
    from umat_oti.corpus_features import drivers as dv
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    if config is not None:
        config.write(work)
    else:
        (work / dv.CONFIG_FILE).write_text(config_text, encoding="utf-8")
    dv.write_perturbations(work, [dv.Perturbation("local", "none", 0, 0.0)])
    ok, message = dv.run_program(build, work, timeout=900)
    if not ok:
        return None
    return dv.parse_real_output(work / dv.REAL_OUT, ntens, nstatv)


def build_transformed(units_dir: Path, work: Path):
    """Exactly the harness's store build (harness.build_all): compile_order units in place."""
    from umat_oti.corpus_features import drivers as dv
    order = [l.strip() for l in (units_dir / "compile_order.txt").read_text().splitlines() if l.strip()]
    units = [units_dir / name for name in order]
    flags = [["-ffree-form", "-ffree-line-length-none"] if u.suffix == ".f90"
             else ["-ffixed-form", "-ffixed-line-length-none"] for u in units]
    return dv.build_real(work, units, units[-1].read_text(errors="replace"), sdvini=False,
                         unit_flags=flags)


def build_original(source: Path, work: Path):
    """The harness's REFERENCE build of the ORIGINAL (zero-init compile, D-12)."""
    from umat_oti.abaqus.replay import FINIT_ZERO, defines_sdvini
    from umat_oti.corpus_features import drivers as dv
    work.mkdir(parents=True, exist_ok=True)
    prepared, text, flags = dv.prepare_original_source(source, work)
    return dv.build_real(work, [prepared], text, sdvini=defines_sdvini(text), unit_flags=[flags],
                         extra_flags=FINIT_ZERO)


def regenerate(source: Path, source_id: str, sha: str, ntens: int, work: Path) -> tuple:
    """Transform with the CURRENT code, the pipeline's recipe (transform_all.transform_one,
    which also compiles in the job layout). Returns (out_dir or None, metadata/reason)."""
    import transform_all
    item = transform_all.WorkItem(source_id=source_id, path=Path(source), sha256=sha, ntens=ntens)
    result = transform_all.transform_one(item, work)
    if not result.ok:
        return None, {"reason": result.reason, **(result.metadata or {})}
    if result.metadata.get("compiled") is not True:
        return None, {"reason": "job-layout compile failed: "
                                + str(result.metadata.get("compile_error"))[:400], **result.metadata}
    return result.out_dir, result.metadata


def transformed_files(out_dir: Path, *, everything: bool = False) -> list:
    """The files a rebuild needs (compile_order.txt, its units, the dependencies
    tree, include headers); ``everything``: every non-binary output (for CAS)."""
    out_dir = Path(out_dir)
    order = [l.strip() for l in (out_dir / "compile_order.txt").read_text().splitlines() if l.strip()]
    keep = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(out_dir).as_posix()
        if rel.endswith((".o", ".mod", ".so", ".obj")):
            continue
        needed = (rel == "compile_order.txt" or rel in order or rel.startswith("dependencies/")
                  or rel.lower().endswith(".inc"))
        if needed or everything:
            keep.append(rel)
    return keep


# ---------------------------------------------------------------------------
# cases on disk
# ---------------------------------------------------------------------------

def load_cases(tier: Optional[str] = None, only: tuple = ()) -> list:
    out = []
    for case_json in sorted(CASES.glob("*/case.json")):
        case = json.loads(case_json.read_text())
        if only and case["case_id"] not in only:
            continue
        if tier == "ci" and not case["tiers"].get("ci"):
            continue
        out.append((case_json.parent, case))
    return out


def case_digest(case_dir: Path) -> dict:
    """The anchor of a case OUTSIDE its directory (index.json): the sha256 of
    case.json and of the reference file as committed. case.json in turn pins the
    configs, the preserved transformed files and the source by sha256, so a
    change to anything a check relies on shows up as a diff of index.json."""
    case_json = case_dir / "case.json"
    try:
        ref_file = json.loads(case_json.read_text())["reference"]["file"]
    except (OSError, ValueError, KeyError):
        ref_file = "reference.json.gz"
    ref = case_dir / ref_file
    return {"case_json_sha256": sha256_file(case_json),
            "reference_sha256": sha256_file(ref) if ref.is_file() else None}


def index_row(case_dir: Path) -> Optional[dict]:
    """The case's row of the index.json beside it (None when not indexed)."""
    try:
        rows = json.loads((case_dir.parent / "index.json").read_text())["cases"]
    except (OSError, ValueError, KeyError):
        return None
    return next((r for r in rows if r.get("case_id") == case_dir.name), None)


def consistency_failures(case_dir: Path, case: dict, ref: dict, row) -> list:
    """Cross-checks that do not trust any single file: the reference against
    case.json's experiment (paths, judged-state counts and increments), and
    both against the index row (digests, path and judged-state totals)."""
    out = []
    exp = {p["name"]: p for p in case["experiment"]["paths"]}
    refp = {p.get("name"): p for p in ref.get("paths", [])}
    for name in sorted(set(exp) - set(refp)):
        out.append({"kind": "reference_incomplete", "path": name,
                    "detail": "path frozen in case.json is missing from the reference"})
    for name in sorted(set(refp) - set(exp)):
        out.append({"kind": "reference_incomplete", "path": name,
                    "detail": "reference path not declared in case.json experiment.paths"})
    for name in sorted(set(exp) & set(refp)):
        incs = [s["inc"] for s in refp[name].get("judged", [])]
        want = exp[name].get("judged_increments")
        if len(incs) != exp[name]["judged_states"] or (want is not None and incs != want):
            out.append({"kind": "coverage_shrank", "path": name,
                        "detail": f"reference holds {len(incs)} judged states, case.json declares "
                                  f"{exp[name]['judged_states']} (increments differ: "
                                  f"{sorted(set(want or []) ^ set(incs))[:10]})"})
        if not all(s.get("entries") for s in refp[name].get("judged", [])):
            out.append({"kind": "coverage_shrank", "path": name,
                        "detail": "a judged state holds no entries"})
    if row is None:
        out.append({"kind": "not_indexed",
                    "detail": f"{case_dir.name} has no row in {case_dir.parent / 'index.json'}"})
        return out
    digest = case_digest(case_dir)
    for key, now in digest.items():
        if (row.get("digest") or {}).get(key) != now:
            out.append({"kind": "case_corrupted",
                        "detail": f"{key} {str(now)[:12]} differs from index.json "
                                  f"{str((row.get('digest') or {}).get(key))[:12]}"})
    n_paths, n_judged = len(refp), sum(len(p.get("judged", [])) for p in refp.values())
    if row.get("paths") != n_paths or row.get("judged_states") != n_judged:
        out.append({"kind": "coverage_shrank",
                    "detail": f"index.json lists {row.get('paths')} paths / {row.get('judged_states')} "
                              f"judged states; the reference holds {n_paths} / {n_judged}"})
    return out


def write_index() -> None:
    rows = []
    for case_json in sorted(CASES.glob("*/case.json")):
        try:                      # a parallel freeze may be rewriting a case right now
            c = json.loads(case_json.read_text())
        except (OSError, ValueError):
            continue
        rows.append({"case_id": c["case_id"], "tiers": c["tiers"],
                     "redistribution": c["source"]["licence"]["redistribution"],
                     "kind": c["source"]["kind"],
                     "transform_fingerprint": c["fingerprints"]["transform_fingerprint"],
                     "harness_fingerprint": c["fingerprints"]["harness_fingerprint"],
                     "rule_id": c["tolerance_rule_id"],
                     "paths": len(c["experiment"]["paths"]),
                     "judged_states": sum(p["judged_states"] for p in c["experiment"]["paths"]),
                     "digest": case_digest(case_json.parent)})
    tmp = CASES / f".index.json.{os.getpid()}"
    write_json(tmp, {"schema": SCHEMA + "/index", "cases": rows})
    os.replace(tmp, CASES / "index.json")


def obtain_source(case_dir: Path, case: dict, work: Path) -> tuple:
    """(path to the original source, where it came from) -- verified by sha256."""
    src = case["source"]
    candidates = []
    if src.get("in_case"):
        candidates.append((case_dir / src["in_case"], "case"))
    if src.get("cache_path"):
        candidates.append((DISCOVERY_CACHE / src["cache_path"], "discovery_cache"))
    candidates.append((cas_object(src["sha256"]), "corpus_assets"))
    for path, where in candidates:
        if path.is_file() and sha256_file(path) == src["sha256"]:
            if where == "corpus_assets":       # restore the file name the transform keys on
                target = work / "fetched" / Path(src["path"]).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                return target, where
            return path, where
    return None, ("source not available here; " + case["reproduce"]["fetch"])


def preserved_units(case_dir: Path, case: dict, work: Path) -> tuple:
    """Rebuild the preserved transform output dir (case/transformed or CAS)."""
    target = work / "preserved"
    if target.exists():
        shutil.rmtree(target)
    for item in case["transform"]["files"]:
        dest = target / item["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        in_case = case_dir / "transformed" / item["path"]
        obj = cas_object(item["sha256"])
        src = in_case if in_case.is_file() else obj
        if not src.is_file() or sha256_file(src) != item["sha256"]:
            return None, f"preserved file {item['path']} unavailable or corrupted"
        shutil.copyfile(src, dest)
    return target, "case" if (case_dir / "transformed").is_dir() else "corpus_assets"


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

_FROM_INDEX = object()


def check_case(case_dir: Path, case: dict, modes: tuple, work: Path, *,
               current_rule: str, with_original: bool = True, row=_FROM_INDEX) -> dict:
    started = time.time()
    result = {"case_id": case["case_id"], "modes": {}, "failures": [], "canaries": []}
    if case["tolerance_rule_id"] != current_rule:
        result["failures"].append({"kind": "rule_changed",
                                   "detail": f"case frozen under {case['tolerance_rule_id']}, "
                                             f"current rule {current_rule}: re-baseline decision needed"})
    if sha256_file(case_dir / case["reference"]["file"]) != case["reference"]["sha256"]:
        result["failures"].append({"kind": "case_corrupted",
                                   "detail": "reference sha256 differs from case.json"})
    ref = read_gz_json(case_dir / case["reference"]["file"])
    result["failures"] += consistency_failures(
        case_dir, case, ref, index_row(case_dir) if row is _FROM_INDEX else row)
    frozen_errors = {p["name"]: p["frozen_error"] for p in ref["paths"]}
    configs = {p["name"]: (case_dir / p["config"]).read_text() for p in case["experiment"]["paths"]}
    for p in case["experiment"]["paths"]:
        if sha256_bytes(configs[p["name"]].encode()) != p["config_sha256"]:
            result["failures"].append({"kind": "case_corrupted", "path": p["name"],
                                       "detail": "driver config sha256 mismatch"})
    work.mkdir(parents=True, exist_ok=True)
    source, where = obtain_source(case_dir, case, work)
    original_runs = None
    if source is not None and with_original:
        ob = build_original(source, work / "original_build")
        if ob.ok:
            original_runs = {name: _run_driver(ob, work / "original_run" / name, text,
                                               ntens=case["experiment"]["ntens"],
                                               nstatv=case["experiment"]["nstatv"])
                             for name, text in configs.items()}
        else:
            result["failures"].append({"kind": "build", "detail": f"ORIGINAL did not build: {ob.reason}"})
    observed = {}
    for mode in modes:
        m = {"seconds": None}
        t0 = time.time()
        if mode == "regenerate":
            if source is None:
                result["failures"].append({"kind": "source_unavailable", "mode": mode, "detail": where})
                continue
            out_dir, meta = regenerate(source, case["source"]["source_id"], case["source"]["sha256"],
                                       case["experiment"]["ntens"], work / "regen")
            m["source_from"] = where
            if out_dir is None:
                result["failures"].append({"kind": "transform", "mode": mode,
                                           "detail": str(meta.get("reason"))[:500]})
                result["modes"][mode] = m
                continue
            m["compiled_in_job_layout"] = meta.get("compiled")
            units_dir = out_dir
        else:
            units_dir, m["units_from"] = preserved_units(case_dir, case, work)
            if units_dir is None:
                result["failures"].append({"kind": "assets", "mode": mode, "detail": m["units_from"]})
                result["modes"][mode] = m
                continue
        build = build_transformed(units_dir, work / f"{mode}_build")
        if not build.ok:
            result["failures"].append({"kind": "build", "mode": mode,
                                       "detail": f"{build.reason}: {build.log[-600:]}"})
            result["modes"][mode] = m
            continue
        runs, verdicts = {}, {}
        for name, text in configs.items():
            run = _run_driver(build, work / f"{mode}_run" / name, text,
                              ntens=case["experiment"]["ntens"], nstatv=case["experiment"]["nstatv"])
            path_ref = next((p for p in ref["paths"] if p["name"] == name), None)
            if path_ref is None:        # named by consistency_failures (reference_incomplete)
                continue
            if run is None:
                result["failures"].append({"kind": "run", "mode": mode, "path": name,
                                           "detail": "driver did not run"})
                continue
            runs[name] = run
            verdicts[name] = judge_path(path_ref, run, (original_runs or {}).get(name))
        for f in failures_of(verdicts, frozen_errors):
            result["failures"].append(dict(f, mode=mode))
        m["paths"] = {k: {"primal_error_over_tolerance": v["primal"]["error_over_tolerance"],
                          "tangent_error_over_tolerance": v["tangent"]["error_over_tolerance"],
                          "coverage": f"{v['coverage']['judged']}/{v['coverage']['frozen']}",
                          "hidden_state_ok": v["hidden_state"]["agrees"],
                          "original_reproduced": None if v["original_reproduced"] is None
                          else v["original_reproduced"]["agrees"]}
                      for k, v in verdicts.items()}
        m["seconds"] = round(time.time() - t0, 1)
        result["modes"][mode] = m
        observed.setdefault("runs", runs)
    if "runs" in observed:
        result["canaries"] = data_canaries(ref, observed["runs"])
    else:
        result["canaries"] = [{"canary": "data mutants", "rejected": False,
                               "why": "no mode produced observations"}]
    for c in result["canaries"]:
        if not c["rejected"]:
            result["failures"].append({"kind": "canary_passed", "detail": c})
    result["ok"] = not result["failures"]
    result["seconds"] = round(time.time() - started, 1)
    return result


def _check_one(args_tuple):
    case_dir, case, modes, work, rule, with_original = args_tuple
    try:
        return check_case(Path(case_dir), case, modes, Path(work), current_rule=rule,
                          with_original=with_original)
    except Exception as error:                                      # noqa: BLE001
        import traceback
        return {"case_id": case["case_id"], "ok": False,
                "failures": [{"kind": "crash", "detail": f"{type(error).__name__}: {error}",
                              "traceback": traceback.format_exc()[-1500:]}], "canaries": []}


def cmd_check(args) -> int:
    started = time.time()
    if shutil.which("gfortran") is None:
        print("gfortran is not on PATH: the case check cannot run (this is a failure, not a skip)")
        return 2
    modes = tuple(m for m, on in (("regenerate", args.regenerate), ("replay", args.replay)) if on) \
        or ("regenerate", "replay")
    cases = load_cases(args.tier, tuple(args.only))
    if args.tier == "ci":
        bad = [c["case_id"] for _, c in cases if c["source"]["licence"]["redistribution"] != "permitted"]
        if bad:
            print(f"CI tier holds non-redistributable cases: {bad}")
            return 2
    if not cases:
        print("no cases selected")
        return 2
    rule = rule_id()
    root = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="corpus_cases_"))
    jobs = [(str(d), c, modes, str(root / c["case_id"]), rule, not args.no_original)
            for d, c in cases]
    if args.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(_check_one, jobs))
    else:
        results = [_check_one(j) for j in jobs]
    tier_canaries = [hidden_state_canary(root / "_canary")]
    failed = [r for r in results if not r["ok"]]
    tier_failures = [c for c in tier_canaries if not c["rejected"]]
    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        modes_txt = ", ".join(f"{m}: {v.get('seconds')}s" for m, v in (r.get("modes") or {}).items())
        print(f"{status} {r['case_id']} ({r.get('seconds')}s; {modes_txt})")
        for f in r["failures"][:8]:
            print(f"     {f['kind']}: {f.get('mode', '')} {f.get('path', '')} "
                  f"{json.dumps(f.get('detail'), default=str)[:300]}")
        for c in r.get("canaries", []):
            print(f"     canary {'rejected' if c['rejected'] else 'NOT REJECTED'}: {c['canary']}")
    for c in tier_canaries:
        print(f"tier canary {'rejected' if c['rejected'] else 'NOT REJECTED'}: {c['canary']} {c}")
    report = {"schema": SCHEMA + "/check-report", "tier": args.tier, "modes": list(modes),
              "rule_id": rule, "fingerprints": fingerprints(), "toolchain": toolchain(),
              "date": datetime.datetime.now().isoformat(timespec="seconds"),
              "seconds": round(time.time() - started, 1), "results": results,
              "tier_canaries": tier_canaries,
              "ok": not failed and not tier_failures}
    if args.report:
        write_json(Path(args.report), json.loads(json.dumps(report, default=str)))
        print(f"report -> {args.report}")
    if not args.keep and not args.work:
        shutil.rmtree(root, ignore_errors=True)
    line, ok = tier_summary(results, tier_canaries, report["seconds"])
    print(line)
    return 0 if (report["ok"] and ok) else 1


def tier_summary(results: list, tier_canaries: list, seconds) -> tuple:
    """(the closing line, ok). Every canary -- per case and per tier -- that was
    NOT rejected is named and fails the tier; "all rejected" is printed only
    when that is true."""
    failed = [r for r in results if not r.get("ok")]
    slipped = [f"{r['case_id']}: {c['canary']}" for r in results
               for c in r.get("canaries", []) if not c.get("rejected")]
    slipped += [f"tier: {c['canary']}" for c in tier_canaries if not c.get("rejected")]
    head = f"{len(results) - len(failed)}/{len(results)} cases pass; "
    if slipped:
        return (head + f"{len(slipped)} canaries NOT REJECTED (tier FAILS): "
                + "; ".join(slipped[:20]) + f"; {seconds}s", False)
    return head + f"canaries all rejected; {seconds}s", not failed


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------

def curated_entry(model_dir: Path, family: str, activation: Optional[float]):
    from umat_oti.corpus_features.harness import CorpusEntry
    contract = json.loads((model_dir / "contract_v2.json").read_text())
    dims = contract["dimensions"]
    source = model_dir / contract["source"]["main_file"]
    rel = source.resolve().relative_to(REPO).as_posix()
    kin = "finite" if str(contract.get("kinematics", "")).startswith("finite") else "small"
    props = [float(p) for p in contract["validation"]["props_values"]]
    time_dependent = family.startswith("viscoelastic")
    entry = CorpusEntry(
        key="curated-" + model_dir.name, source_id=f"umat-oti/{rel}", original_source=source,
        ntens=int(dims["ntens"]), nstatv=int(dims.get("nstatev") or 0), props=props,
        kinematics=kin, family=family,
        path_hints={"time_dependent": time_dependent, "activation_amplitude": activation,
                    "source_text": source.read_text(errors="replace")},
        provenance={"curated_model": rel, "props": "contract_v2.json validation.props_values",
                    "family": "set at freeze (--family)", "activation_amplitude":
                    "set at freeze (--activation); not an Abaqus amplitude search"})
    return entry, rel


def cmd_freeze(args) -> int:
    from umat_oti.corpus_features import harness as H
    from umat_oti.corpus_features.cells import fold
    from umat_oti.store import TransformStore
    _install_capture()
    fp = fingerprints()
    rule = rule_id()
    run_id = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    pointed = {}
    if getattr(args, "verification_records", None) is not None:
        H.PASS16 = Path(args.verification_records).resolve()
        pointed["verification_records"] = str(H.PASS16)
    if getattr(args, "registry", None) is not None:
        H.REGISTRY = Path(args.registry).resolve()
        pointed["registry"] = str(H.REGISTRY)
    if args.key:
        entry = H.resolve_entry(args.key)
        registry = {r["key"]: r for r in json.loads(H.REGISTRY.read_text())["records"]}[args.key]
        source_id, source_path = entry.source_id, entry.original_source
        kind = "corpus"
        licence = corpus_licence(source_id)
        identity = {"kind": kind, "registry_key": args.key, "source_id": source_id,
                    "repository": registry.get("repository"), "commit": registry.get("commit"),
                    "path": "/".join(registry["cache_path"].split("/")[1:]),
                    "cache_path": registry["cache_path"],
                    "url": registry.get("acquisition_url"),
                    "raw_url": (f"https://raw.githubusercontent.com/{registry.get('repository')}/"
                                f"{registry.get('commit')}/"
                                + "/".join(registry["cache_path"].split("/")[1:]))
                    if registry.get("repository") and registry.get("commit") else None,
                    "resolved_with": pointed or None}
        case_id = args.id or material_id(source_id)
    else:
        model = Path(args.model).resolve()
        entry, rel = curated_entry(model, args.family, args.activation)
        source_id, source_path, kind = entry.source_id, entry.original_source, "curated"
        licence = curated_licence(model.name)
        identity = {"kind": kind, "source_id": source_id, "repository": "this repository",
                    "path": rel, "commit": None, "url": None, "raw_url": None}
        case_id = args.id or "umat-oti-curated--" + model.name.replace("_", "-").lower()
    sha = sha256_file(source_path)
    if args.tier == "ci" and licence["redistribution"] != "permitted":
        print(f"refused: the CI tier needs a redistributable source; {source_id} is "
              f"{licence['redistribution']} ({licence.get('redistribution_basis', '')[:200]})")
        return 3
    work_root = ASSETS / "work" / "freeze" / case_id / run_id
    work_root.mkdir(parents=True, exist_ok=True)

    # the transform under test: the store's CURRENT entry (read only), else regenerated privately
    store = TransformStore()
    stored = store.get(source_id, sha) if kind == "corpus" else None
    stored_ntens = (stored.metadata or {}).get("ntens") if stored is not None else None
    if stored is not None and stored_ntens is not None and int(stored_ntens) != entry.ntens:
        print(f"note: the store's current entry was transformed for NTENS={stored_ntens}, the "
              f"experiment drives NTENS={entry.ntens}: regenerating privately for NTENS={entry.ntens}")
        stored, ntens_note = None, (f"store entry NTENS={stored_ntens} differs from the "
                                    f"experiment's NTENS={entry.ntens}; regenerated")
    else:
        ntens_note = ""
    if stored is not None and stored.fingerprint == fp["transform_fingerprint"]:
        units_dir, transform_from = Path(stored.directory), f"transform_store:{stored.key}"
    else:
        out_dir, meta = regenerate(source_path, source_id, sha, entry.ntens, work_root / "transform")
        if out_dir is None:
            print(f"refused: the current transform failed: {str(meta.get('reason'))[:400]}")
            return 3
        write_json(out_dir / "entry.json", {"fingerprint": fp["transform_fingerprint"],
                                            "source_sha256": sha, "source_id": source_id,
                                            "note": "private regeneration by tools/corpus_cases.py"})
        units_dir, transform_from = out_dir, ("regenerated (tools/transform_all.transform_one)"
                                              + (f"; {ntens_note}" if ntens_note else ""))
    entry.store_dir = units_dir

    # the routine-level harness run (umat_oti.corpus_features, as run_corpus_features.py runs it)
    t0 = time.time()
    records = H.run_entry(entry, work_root / "harness", features=FEATURES)
    harness_seconds = round(time.time() - t0, 1)
    with (work_root / "corpus_features.jsonl").open("w") as handle:
        for r in records:
            handle.write(json.dumps({k: v for k, v in r.items() if k != "_case_capture"},
                                    default=float) + "\n")
    cells = {c["feature"]: c for c in fold(records, evidence=f"corpus_assets:{case_id}")}
    status = {f: (cells.get(f) or {}).get("status") for f in FEATURES}
    print(f"{case_id}: harness {harness_seconds}s; cells {status}")
    by_path: dict = {}
    for r in records:
        by_path.setdefault(r["path"], {})[r["feature"]] = r
    problems = []
    if any(s != "verified" for s in status.values()):
        problems.append(f"cells not verified: {status}")
    undefined = sorted({o for r in records for o in (r.get("undefined_outputs") or [])})
    if not all(r.get("stress_and_ddsdde_fully_defined") is True for r in records):
        problems.append("STRESS or DDSDDE undefined in the ORIGINAL (D-12.3): not frozen")
    undefined_statev = {int(m.group(1)) for o in undefined for m in [re.match(r"STATEV\((\d+)\)$", o)] if m}
    if any(not re.match(r"(STATEV\(\d+\)|SSE|SPD|SCD)$", o) for o in undefined):
        problems.append(f"undefined outputs not handled by the case comparators: {undefined}")
    frozen_paths = [name for name, f in by_path.items()
                    if all((f.get(x) or {}).get("status") == "verified" for x in FEATURES)]
    if not frozen_paths:
        problems.append("no path with both primal and ddsdde verified")
    if problems:
        print("refused: " + "; ".join(problems))
        return 3

    case_dir = CASES / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "inputs").mkdir(parents=True)
    ref_paths, exp_paths, cas_files = [], [], []
    harness_dir = work_root / "harness" / entry.key
    for name in frozen_paths:
        rec = by_path[name]
        safe = H._safe(name)
        cfg_src = harness_dir / safe / "store" / "cf_config.txt"
        history = json.loads((harness_dir / safe / "history.json").read_text())
        cfg_text = cfg_src.read_text()
        (case_dir / "inputs" / f"{safe}.cfg").write_text(cfg_text)
        capture = rec["ddsdde"]["_case_capture"]
        judged = frozen_states_from_capture(capture)
        n_inc = len(history["original"])
        keep = [l for l in range(1, entry.nstatv + 1) if l not in undefined_statev]
        original = {"stress": [h["stress"] for h in history["original"]],
                    "statev": [[h["statev"][l - 1] for l in keep] for h in history["original"]]}
        path_ref = {"name": name, "ntens": entry.ntens, "nstatv": entry.nstatv, "n_inc": n_inc,
                    "statev_defined": keep if undefined_statev else None,
                    "undefined_in_original": sorted(undefined),
                    "original": original,
                    "original_ddsdde": [h["ddsdde"] for h in history["original"]],
                    "judged": judged}
        # frozen error of the build under test, by the SAME comparators the check uses
        store_hist = {h["increment"]: {k: np.asarray(h[k], float) for k in ("stress", "statev", "ddsdde")}
                      for h in history["store_oti"]}
        nx = entry.nstatv
        pv = compare_primal(_rows(store_hist, n_inc, "stress", entry.ntens),
                            statev_rows(store_hist, path_ref),
                            original)
        tv = compare_tangent({k: v["ddsdde"] for k, v in store_hist.items()}, judged)
        if not (pv["agrees"] and tv["agrees"]):
            print(f"refused: frozen comparators disagree with the harness on {name}: "
                  f"primal {pv['agrees']}, tangent {tv['breaches'][:2]}")
            shutil.rmtree(case_dir)
            return 3
        path_ref["frozen_error"] = {"primal": pv["error_over_tolerance"],
                                    "tangent": tv["error_over_tolerance"]}
        ref_paths.append(path_ref)
        exp_paths.append({"name": name, "regime": rec["ddsdde"].get("path_regime"),
                          "kinematics": rec["ddsdde"].get("path_kinematics"),
                          "provenance": rec["ddsdde"].get("path_provenance"),
                          "config": f"inputs/{safe}.cfg",
                          "config_sha256": sha256_bytes(cfg_text.encode()),
                          "n_increments": n_inc, "judged_states": len(judged),
                          "judged_increments": [s["inc"] for s in judged],
                          "harness_status": {f: rec[f]["status"] for f in FEATURES},
                          "harness_reason": rec["ddsdde"].get("reason"),
                          "reference_precision": rec["ddsdde"].get("reference_precision")})
        for fname, src in ((f"paths/{safe}/history.json", harness_dir / safe / "history.json"),
                           (f"paths/{safe}/cf_config.txt", cfg_src)):
            cas_files.append({"path": fname, "sha256": cas_put(src), "bytes": src.stat().st_size,
                              "role": "evidence"})
    write_gz_json(case_dir / "reference.json.gz", {"schema": SCHEMA + "/reference",
                                                   "paths": ref_paths})
    # transformed units (derivative work: same redistribution status as the source)
    tfiles = []
    needed = set(transformed_files(units_dir))
    for rel in transformed_files(units_dir, everything=True):
        src = units_dir / rel
        sha_t = cas_put(src)
        cas_files.append({"path": f"transformed/{rel}", "sha256": sha_t,
                          "bytes": src.stat().st_size,
                          "role": "transformed (rebuild set)" if rel in needed
                          else "transform output (evidence)"})
        if rel not in needed:
            continue
        tfiles.append({"path": rel, "sha256": sha_t, "bytes": src.stat().st_size})
        if licence["redistribution"] == "permitted":
            dest = case_dir / "transformed" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
    src_sha = cas_put(source_path)
    cas_files.append({"path": f"source/{Path(source_path).name}", "sha256": src_sha,
                      "bytes": Path(source_path).stat().st_size,
                      "role": "source" + ("" if licence["redistribution"] == "permitted"
                                          else " (restricted: local machine only)")})
    in_case = None
    if licence["redistribution"] == "permitted":
        in_case = f"source/{Path(source_path).name}"
        (case_dir / "source").mkdir()
        shutil.copyfile(source_path, case_dir / in_case)
    for extra in ("corpus_features.jsonl",):
        cas_files.append({"path": f"harness/{extra}", "sha256": cas_put(work_root / extra),
                          "bytes": (work_root / extra).stat().st_size, "role": "harness records"})
    cas_files.append({"path": "harness/builds.json", "sha256": cas_put(harness_dir / "builds.json"),
                      "bytes": (harness_dir / "builds.json").stat().st_size, "role": "harness builds"})
    tree = cas_tree(case_id, fp["transform_fingerprint"], cas_files)
    first = by_path[frozen_paths[0]]["ddsdde"]
    case = {
        "schema": SCHEMA, "case_id": case_id, "status": "verified",
        "status_basis": "routine-level (driver) verification: primal_stress_state and ddsdde cells "
                        "verified by umat_oti.corpus_features at the fingerprints below; NOT the "
                        "Abaqus six-gate verification",
        "source": dict(identity, sha256=sha, bytes=Path(source_path).stat().st_size,
                       licence=licence, in_case=in_case,
                       fetch=None if in_case else
                       f"python tools/corpus_cases.py fetch {case_id}  (discovery_cache by sha256, "
                       f"else corpus_assets, else --allow-network: raw_url at the pinned commit)"),
        "fingerprints": dict(fp, contract_transform_generation=json.loads(
            (REPO / "src/umat_oti/contract/schemas/transform_generation.json").read_text()
        )["transform_fingerprint"]),
        "transform": {"settings": {"recipe": "tools/transform_all.transform_one (seed auto, "
                                             "STRESS/DDSDDE, job-layout gfortran compile)",
                                   "ntens": entry.ntens, "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED")},
                      "from": transform_from, "files": tfiles,
                      "compiled_source_sha256": first.get("compiled_source_sha256")},
        "experiment": {"ntens": entry.ntens, "ndi": entry.ndi, "nshr": entry.nshr,
                       "nstatv": entry.nstatv, "props": list(entry.props),
                       "initial_statev": "first data rows of each config (after SDVINI if any)",
                       "family": entry.family, "kinematics": entry.kinematics,
                       "material_provenance": entry.provenance,
                       "paths": exp_paths,
                       "paths_not_frozen": {n: {f: (r.get(f) or {}).get("status") for f in FEATURES}
                                            for n, r in by_path.items() if n not in frozen_paths}},
        "references": [
            {"id": "primal_original", "kind": "primal",
             "producer": "ORIGINAL routine, harness real driver, gfortran zero-init build",
             "independent_of_oti": True, "compact": "reference.json.gz#paths[].original"},
            {"id": "tangent_fd_original", "kind": "derivative",
             "quantity": first.get("quantity"), "wrt": first.get("wrt"),
             "held_fixed": first.get("held_fixed"), "scope": "local: one increment from the "
             "recorded incoming state", "reference": first.get("reference"),
             "independent_of_oti": True, "compact": "reference.json.gz#paths[].judged"}],
        "reference": {"file": "reference.json.gz", "sha256": sha256_file(case_dir / "reference.json.gz")},
        "tolerance_rule_id": rule,
        "error_summary": {p["name"]: p["frozen_error"] for p in ref_paths},
        "toolchain": toolchain(),
        "harness": {"run_id": run_id, "seconds": harness_seconds, "features": list(FEATURES),
                    "cells": status, "records": "corpus_assets tree: harness/corpus_features.jsonl"},
        "assets": {"tree_sha256": tree, "location": "corpus_assets", "files": len(cas_files),
                   "bytes": sum(f["bytes"] for f in cas_files)},
        "tiers": {"ci": args.tier == "ci", "offline": True},
        "reproduce": {
            "check": f"PYTHONHASHSEED=0 python tools/corpus_cases.py check --only {case_id}",
            "fetch": f"python tools/corpus_cases.py fetch {case_id}",
            "freeze": " ".join(["PYTHONHASHSEED=0 python tools/corpus_cases.py freeze"]
                               + ([f"--key {args.key}"]
                                  + [f"--{k.replace('_', '-')} {v}" for k, v in pointed.items()]
                                  if args.key else
                                  [f"--model {Path(args.model).as_posix()} --family '{args.family}'"
                                   + (f" --activation {args.activation}" if args.activation else "")])
                               + [f"--tier {args.tier}"])},
        "undefined_in_original": undefined,
        "limitations": ["routine-level evidence (driver), not Abaqus",
                        "loading paths are this pipeline's probes, not the author's example"]
                       + ([f"undefined_in_original (D-12, a SOURCE defect): {undefined}; those "
                           "slots are never compared"] if undefined else [])
                       + ([] if in_case else ["source not redistributable (D-2): CI cannot run R or "
                                              "P for this case; offline tier only"]),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    write_json(case_dir / "case.json", scrub(case))
    # self-check: the case must pass its own check, R and P, now
    result = check_case(case_dir, case, ("regenerate", "replay"), work_root / "self_check",
                        current_rule=rule,
                        row={"digest": case_digest(case_dir), "paths": len(ref_paths),
                             "judged_states": sum(len(p["judged"]) for p in ref_paths)})
    case["freeze_check"] = {"ok": result["ok"], "modes": result.get("modes"),
                            "canaries": [{"canary": c["canary"], "rejected": c["rejected"]}
                                         for c in result["canaries"]],
                            "failures": result["failures"][:5]}
    write_json(case_dir / "case.json", scrub(case))
    if not result["ok"]:
        print(f"refused: the frozen case does not pass its own check: "
              f"{json.dumps(result['failures'][:3], default=str)[:800]}")
        shutil.move(str(case_dir), str(work_root / "refused_case"))   # evidence, not the repo
        print(f"refused case kept at {work_root / 'refused_case'}")
        write_index()
        return 3
    write_index()
    print(f"frozen {case_id}: {len(ref_paths)} path(s), "
          f"{sum(len(p['judged']) for p in ref_paths)} judged states, tree {tree[:12]}")
    return 0


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def cmd_fetch(args) -> int:
    rc = 0
    for case_dir, case in load_cases(None, tuple(args.case_id)):
        target = case_dir / ".materialized" / Path(case["source"]["path"]).name
        path, where = obtain_source(case_dir, case, case_dir / ".materialized")
        if path is None and args.allow_network and case["source"].get("raw_url"):
            import urllib.request
            data = urllib.request.urlopen(case["source"]["raw_url"], timeout=60).read()
            if sha256_bytes(data) != case["source"]["sha256"]:
                print(f"{case['case_id']}: digest mismatch from {case['source']['raw_url']}")
                rc = 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            path, where = target, "network (pinned commit)"
        print(f"{case['case_id']}: {path or 'NOT AVAILABLE'} ({where})")
        rc |= path is None
    return rc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze", help="freeze one verified case")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--key", help="corpus registry / store key")
    g.add_argument("--model", help="in-repo model dir (contract_v2.json + umat.for)")
    f.add_argument("--family", default="other / unclassified", help="(--model) reviewed family")
    f.add_argument("--activation", type=float, default=None,
                   help="(--model) inelastic activation amplitude for the loading paths")
    f.add_argument("--tier", choices=("ci", "offline"), default="offline")
    f.add_argument("--id", default="")
    f.add_argument("--verification-records", type=Path, default=None,
                   help="(--key) store_verification.jsonl whose rows supply the key's experiment "
                        "(as tools/run_corpus_features.py --verification-records)")
    f.add_argument("--registry", type=Path, default=None,
                   help="(--key) corpus registry that maps keys to sources (default: the committed "
                        "paper_results/corpus/corpus_registry.json)")
    c = sub.add_parser("check", help="R (regenerate) and/or P (replay) every case of a tier")
    c.add_argument("--tier", choices=("ci", "offline"), default="ci")
    c.add_argument("--regenerate", action="store_true")
    c.add_argument("--replay", action="store_true")
    c.add_argument("--only", action="append", default=[])
    c.add_argument("--jobs", type=int, default=1)
    c.add_argument("--work", default="")
    c.add_argument("--keep", action="store_true")
    c.add_argument("--no-original", action="store_true",
                   help="do not rebuild the ORIGINAL (skips the reference-reproduction check)")
    c.add_argument("--report", default="")
    fe = sub.add_parser("fetch", help="materialise the source of a case")
    fe.add_argument("case_id", nargs="+")
    fe.add_argument("--allow-network", action="store_true")
    sub.add_parser("verify-assets", help="re-hash every CAS object the cases list")
    sub.add_parser("index", help="rebuild umat/cases/index.json")
    args = parser.parse_args(argv)
    if args.command == "freeze":
        return cmd_freeze(args)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "fetch":
        return cmd_fetch(args)
    if args.command == "verify-assets":
        problems = verify_assets()
        print("\n".join(problems) or "every listed asset present and intact")
        return 1 if problems else 0
    write_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
