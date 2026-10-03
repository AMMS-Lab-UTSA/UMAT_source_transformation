"""Routine-level feature verification for corpus UMATs (no Abaqus).

For one corpus entry and one loading path this module

1. builds the ORIGINAL routine with :data:`drivers.REAL_DRIVER` and runs the
   base history plus every finite-difference perturbation in one process,
   restoring the incoming state before each perturbed call;
2. builds the store's OTI build (standard real interface, DSTRAN-seeded,
   returns DDSDDE) with the same driver -> features ``primal_stress_state``
   and ``ddsdde``;
3. lifts the original routine with the generic PROPS-seeding transformer
   (:mod:`umat_oti.transform.parameter_sensitivity_transform`) and drives it
   with :data:`drivers.OTI_DRIVER` in local and total mode -> the parameter-
   and state-sensitivity features;
4. judges every derivative column against the FD ladder of the ORIGINAL
   routine (:mod:`.fd`, decision D-4) and writes one record per
   (UMAT, feature, path).

Definitions (see ``corpus_campaign/batches/B1/gauss/DESIGN.md``):

* local  d(.)_{n+1}/dp at fixed incoming (STRESS_n, STATEV_n, STRAN_n, DSTRAN,
  DFGRD0/1, TIME, energies): one increment.
* total  d(.)_n/dp along the prescribed-strain history: STRAN/DSTRAN/DFGRD
  held at their prescribed values, STRESS/STATEV propagated.

B2 changes (Vera's B1 review): entrywise resolution-aware tolerance
(:func:`fd.judge_column`); a hidden-state gate that makes the whole SOURCE
``not_attempted`` (:func:`hidden_state_pregate`, :func:`hidden_state_gate`);
branch signatures restricted to the STATEV slots that can affect the judged
block, and state coverage in every verdict (:class:`FeatureTally`); the build
under test (store / lifted), its transformer fingerprint and compiled-source
sha256 on every record (:func:`build_identity`); the finite-strain FD
direction built from the kinematics and checked against the seed map
(:func:`canonical_strain_direction`); evidence locators ``<root>:<relative>``
(:data:`ROOTS`, :func:`locator`).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np

from umat_oti.corpus_features import drivers as dv
from umat_oti.corpus_features import fd
from umat_oti.corpus_features.paths import kinematics_for, paths_for

#: Curie's label for a path that leaves the author's documented domain (D-12.1).
OUTSIDE_MODEL_DOMAIN = "outside_model_domain"

#: The directory the checkout sits in (beside discovery_cache/, transform_store/,
#: corpus_run/ ...), or $UMAT_OTI_WORKSPACE when the checkout lives elsewhere.
WORKSPACE = Path(os.environ.get("UMAT_OTI_WORKSPACE")
                 or Path(__file__).resolve().parents[3].parent)
REGISTRY = Path(__file__).resolve().parents[3] / "paper_results/corpus/corpus_registry.json"
FAMILIES = WORKSPACE / "corpus_run/material_families_checked_E.json"
PASS16 = WORKSPACE / "corpus_run/pass16/results/store_verification.jsonl"
#: Council plans (D-19a rev 2 G8/G9): ``<dir>/<registry key>/council_plan.json``
#: (``experiment.CouncilPlan.as_dict``). Read when the verification record of
#: a key carries no manifest.
COUNCIL_PLANS = WORKSPACE / "corpus_campaign/council_plans"
COUNCIL_DRIVER_POINT = ("council plan: a single generated element at the origin; there is "
                        "no author mesh, so COORDS = 0 and NOEL = NPT = 1 are the experiment's "
                        "own (no position-dependent source is planned by the council)")
STORE = WORKSPACE / "transform_store"
#: Work directories of the Abaqus pass whose records are PASS16 (one
#: ``<key>/original/`` per source); None = ``PASS16``'s ``../../work``.
EXPERIMENT_WORK: Optional[Path] = None
CACHE = WORKSPACE / "discovery_cache"

SCHEMA = "umat-oti/corpus-feature/2"
REPO = Path(__file__).resolve().parents[3]

#: Evidence locators are ``<root>:<path relative to the root>``; the longest
#: matching root wins. Written beside every result set (``roots.json``) so a
#: locator never depends on where the workspace sits on one machine. The names
#: are the corpus manifest's (``manifest.DEFAULT_ROOTS``: ``umat`` is this
#: checkout, ``ra`` the Residual Assembler); a path under none of them is
#: written ``abs:<path>`` and is NOT accepted as manifest evidence.
ROOTS = {
    "campaign": WORKSPACE / "corpus_campaign",
    "umat": REPO,
    "ra": WORKSPACE / "final-ra",
    "transform_store": STORE,
    "discovery_cache": CACHE,
    "corpus_run": WORKSPACE / "corpus_run",
}


def locator(path) -> str:
    """``<root>:<relative path>`` for ``path`` (``abs:<path>`` outside every root)."""
    path = Path(str(path)).resolve() if str(path) else Path(".")
    best = None
    for name, root in ROOTS.items():
        root = Path(root).resolve()
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if best is None or len(root.parts) > best[2]:
            best = (name, rel, len(root.parts))
    return f"{best[0]}:{best[1]}" if best else f"abs:{path}"


def roots_map() -> dict:
    return {name: str(root) for name, root in ROOTS.items()}


#: A verdict needs at least this fraction of its states judged (every column
#: smooth and every entry resolved at that state), per path and over all
#: paths of a cell; a cell needs this many verified paths when that many
#: exist. Justification: below half, the "verified" states are a minority
#: chosen by the very exclusions (branch changes, FD resolution) that could
#: hide a wrong derivative; two paths because one path can be a degenerate
#: or regime-specific history (e.g. only elastic).
MIN_STATE_COVERAGE = 0.5
MIN_VERIFIED_PATHS = 2

#: Compiler flags of the uninitialised-variable check (D-12). ONE definition,
#: shared with the Abaqus-side init check (umat_oti.abaqus.replay): the zero
#: build is the reference; an output differing between ANY two builds is
#: undefined_in_original.
from umat_oti.abaqus.replay import (  # noqa: E402
    FINIT_BUILDS,
    FINIT_HUGE,
    FINIT_SNAN,
    FINIT_ZERO,
)

BOUNDS = ("-fcheck=bounds",)

#: FD step scale of an input whose value is 0 (PROPS) or 0 over the whole
#: history (STATEV): its unit (see evaluate_path).
ZERO_INPUT_SCALE = 1.0

FEATURES = ("primal_stress_state", "ddsdde", "internal_jacobian",
            "stress_param_sens_local", "state_param_sens_local",
            "stress_param_sens_total", "state_param_sens_total",
            "stress_state_sens_local", "state_state_sens_local")

DEFINITIONS = {
    "primal_stress_state": dict(
        quantity="STRESS_{n+1}, STATEV_{n+1} returned by the store OTI build (real parts)",
        wrt="-", derivative_kind="primal",
        held_fixed="identical inputs for both builds at every increment; incoming state "
                   "propagated by each build itself along the prescribed history",
        reference="original routine, same driver, same inputs"),
    "ddsdde": dict(
        quantity="DDSDDE returned by the store OTI build",
        wrt="DSTRAN_j (engineering shear) or, for a gradient-driven source, the strain "
            "direction j pushed forward as dF = eps_j . F (Kirchhoff term added)",
        derivative_kind="local",
        held_fixed="incoming STRESS_n, STATEV_n, STRAN_n, PROPS, TIME, DFGRD0 (and DFGRD1 "
                   "for a DSTRAN-driven source)",
        reference="central FD of the ORIGINAL routine's STRESS_{n+1}, restored state"),
    "stress_param_sens_local": dict(
        quantity="dSTRESS_{n+1}/dPROPS_i", wrt="PROPS(i), each differentiable i",
        derivative_kind="local",
        held_fixed="incoming STRESS_n, STATEV_n, STRAN_n, DSTRAN, DFGRD0/1, TIME",
        reference="central FD of the ORIGINAL routine, restored state"),
    "state_param_sens_local": dict(
        quantity="dSTATEV_{n+1}/dPROPS_i", wrt="PROPS(i)", derivative_kind="local",
        held_fixed="incoming STRESS_n, STATEV_n, STRAN_n, DSTRAN, DFGRD0/1, TIME",
        reference="central FD of the ORIGINAL routine, restored state"),
    "stress_param_sens_total": dict(
        quantity="dSTRESS_n/dPROPS_i along the history", wrt="PROPS(i)",
        derivative_kind="total",
        held_fixed="prescribed DSTRAN/STRAN/DFGRD history and time (strain control); "
                   "STRESS and STATEV propagated (dSTATEV/dp carried as OTI through STATEV)",
        reference="central FD of the ORIGINAL routine: whole history re-run with p +/- h"),
    "state_param_sens_total": dict(
        quantity="dSTATEV_n/dPROPS_i along the history", wrt="PROPS(i)",
        derivative_kind="total",
        held_fixed="prescribed DSTRAN/STRAN/DFGRD history and time (strain control)",
        reference="central FD of the ORIGINAL routine: whole history re-run with p +/- h"),
    "stress_state_sens_local": dict(
        quantity="dSTRESS_{n+1}/dSTATEV_n(l)", wrt="incoming STATEV(l)",
        derivative_kind="local",
        held_fixed="incoming STRESS_n, other STATEV_n, STRAN_n, DSTRAN, DFGRD0/1, PROPS, TIME",
        reference="central FD of the ORIGINAL routine, restored state"),
    "state_state_sens_local": dict(
        quantity="dSTATEV_{n+1}/dSTATEV_n(l)", wrt="incoming STATEV(l)",
        derivative_kind="local",
        held_fixed="incoming STRESS_n, other STATEV_n, STRAN_n, DSTRAN, DFGRD0/1, PROPS, TIME",
        reference="central FD of the ORIGINAL routine, restored state"),
    "internal_jacobian": dict(
        quantity="Jacobian of a local Newton solve inside the routine", wrt="its iterate",
        derivative_kind="local", held_fixed="-", reference="-"),
}


# ---------------------------------------------------------------------------
# entry resolution
# ---------------------------------------------------------------------------

@dataclass
class CorpusEntry:
    key: str
    source_id: str
    original_source: Path
    ntens: int
    nstatv: int
    props: list
    kinematics: str = "small"            # small|finite
    ndi: int = 3
    nshr: int = 3
    cmname: str = "MATERIAL"
    store_dir: Optional[Path] = None
    family: str = ""
    initial_statev: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    path_hints: dict = field(default_factory=dict)
    driver_point: dict = field(default_factory=lambda: dict(_ZERO_POINT))

    @property
    def nprops(self) -> int:
        return len(self.props)

    def as_mapping(self) -> dict:
        return {"key": self.key, "source_id": self.source_id, "ntens": self.ntens,
                "nstatv": self.nstatv, "nprops": self.nprops, "ndi": self.ndi,
                "nshr": self.nshr, "kinematics": self.kinematics, "family": self.family,
                "props": list(self.props), "initial_statev": list(self.initial_statev),
                **self.path_hints}


_ZERO_POINT = {"noel": 1, "npt": 1, "coords": [0.0, 0.0, 0.0],
               "provenance": "default: no recorded Abaqus call of this source was found; "
                             "COORDS = 0, NOEL = NPT = 1 (driver artefact for a "
                             "position-dependent routine)"}


def _probe_first_entry(probe: Path) -> Optional[dict]:
    """The first ``ENTRY`` block of an OTIS probe file: what Abaqus handed the
    routine at its first call (element, point, COORDS, CELENT)."""
    lines = probe.read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        parts = line.split()
        if parts[:1] != ["ENTRY"]:
            continue
        noel, npt, kstep, kinc = (int(x) for x in parts[2:6])
        for j in range(i + 1, len(lines)):
            head = lines[j].split()
            if head[:1] == ["ENTRY"]:
                break
            if head[:1] == ["COORDS"]:
                n = int(head[1])
                vals: list = []
                k = j + 1
                while len(vals) < n and k < len(lines):
                    vals += [float(v) for v in lines[k].split()]
                    k += 1
                return {"noel": noel, "npt": npt, "kstep": kstep, "kinc": kinc,
                        "coords": vals[:3], "celent": vals[3] if n > 3 else None,
                        "line": i + 1}
        return None
    return None


def experiment_driver_point(key: str, work_root: Optional[Path] = None) -> dict:
    """One real integration point of the source's own Abaqus experiment.

    Position-dependent routines (growth laws of r = |COORDS|, THICKCOORD rows
    indexed by NOEL/NPT) are undefined at COORDS = 0. The driver therefore
    runs at the point of the FIRST call recorded by the probe of the
    generated original deck (``<work>/<key>/original/original_probe.txt``):
    its NOEL, NPT and COORDS(1:3), held fixed over the driven history.
    NOEL/NPT are an element/point of that deck, so they stay inside the
    author's mesh. Fallback: the first row of ``original_history.json``
    (converged-call COORDS). COORDS = 0 only when neither exists.
    """
    root = Path(work_root) if work_root is not None else (
        EXPERIMENT_WORK if EXPERIMENT_WORK is not None else PASS16.parent.parent / "work")
    original = root / key / "original"
    probe = original / "original_probe.txt"
    if probe.is_file():
        first = _probe_first_entry(probe)
        if first and len(first["coords"]) == 3 and all(np.isfinite(first["coords"])):
            return {"noel": first["noel"], "npt": first["npt"],
                    "coords": [float(c) for c in first["coords"]],
                    "provenance": (f"{locator(probe)} line {first['line']}: first recorded call "
                                   f"of the original deck (element {first['noel']}, point "
                                   f"{first['npt']}, step {first['kstep']}, increment "
                                   f"{first['kinc']}); COORDS held fixed over the driven "
                                   f"history; deck CELENT {first['celent']} not used "
                                   f"(driver CELENT = 1)")}
    history = original / "original_history.json"
    if history.is_file():
        try:
            rows = json.loads(history.read_text())
            row = next(r for r in rows if isinstance(r, dict) and r.get("entry"))
            coords = [float(c) for c in row["entry"]["COORDS"][:3]]
            return {"noel": int(row["element"]), "npt": int(row["point"]), "coords": coords,
                    "provenance": (f"{locator(history)}: first recorded row (element "
                                   f"{row['element']}, point {row['point']}, converged-call "
                                   f"COORDS); no probe file")}
        except (ValueError, KeyError, StopIteration, TypeError):
            pass
    return dict(_ZERO_POINT, provenance=_ZERO_POINT["provenance"] + f" (looked in {original})")


def _pass16_record(key: str) -> Optional[dict]:
    if not PASS16.is_file():
        return None
    with PASS16.open() as handle:
        for line in handle:
            if key in line:
                record = json.loads(line)
                if record.get("key") == key:
                    return record
    return None


def _council_manifest(key: str, set_id: str) -> tuple[dict, dict]:
    """``(manifest dict, council plan dict)`` of one set of a council plan."""
    path = Path(COUNCIL_PLANS) / key / "council_plan.json"
    if not path.is_file():
        return {}, {}
    council = json.loads(path.read_text())
    for entry in council.get("sets") or ():
        if not set_id or str(entry.get("set_id")) == set_id:
            return ((entry.get("plan") or {}).get("experiment") or {}).get("manifest") or {}, council
    return {}, council


def resolve_entry(key: str) -> CorpusEntry:
    """A registry key -> everything the harness needs, with provenance.

    ``key`` may carry a council parameter set, ``<registry key>#<set id>``
    (D-21: each set is its own experiment). Without an Abaqus manifest for
    the key, the council plan (:data:`COUNCIL_PLANS`) supplies it, and the
    entry carries both origins (material data, experiment)."""
    key, _hash, set_id = str(key).partition("#")
    registry = json.loads(REGISTRY.read_text())
    record = next((r for r in registry["records"] if r["key"] == key), None)
    if record is None:
        raise KeyError(f"{key} is not in {REGISTRY}")
    families = {}
    if FAMILIES.is_file():
        families = {row["source_id"]: row for row in json.loads(FAMILIES.read_text())["rows"]}
    verification = _pass16_record(key) or {}
    # The TOP-LEVEL manifest is the one pass16's generated deck (original.inp)
    # was written from -- checked on 4705e258: CPS4, MATERIAL-1, DEPVAR 23 in
    # original.inp match it, while experiment.manifest names a different
    # element/material. experiment.manifest is the fallback only.
    manifest = (verification.get("manifest")
                or (verification.get("experiment") or {}).get("manifest") or {})
    council: dict = {}
    if set_id or not manifest:
        council_manifest, council = _council_manifest(key, set_id)
        if council_manifest:
            manifest = council_manifest
    origins = {}
    if council:
        origins = {"material_data_origin": council.get("material_data_origin", ""),
                   "experiment_origin": council.get("experiment_origin", "council_deck"),
                   "council_plan": str(Path(COUNCIL_PLANS) / key / "council_plan.json"),
                   "council_set": set_id or str((council.get("sets") or [{}])[0].get("set_id"))}
    elif verification.get("material_data_origin"):
        origins = {"material_data_origin": verification["material_data_origin"],
                   "experiment_origin": verification.get("experiment_origin", "author")}
    if not manifest:
        raise LookupError(f"{key}: no pass16 verification manifest; PROPS/NSTATV unknown")
    kin = str(manifest.get("kinematics") or record.get("kinematics") or "small")
    return CorpusEntry(
        key=key + (f"#{set_id}" if set_id else ""), source_id=record["source_id"],
        original_source=CACHE / record["cache_path"],
        ntens=int(manifest["ntens"]), nstatv=int(manifest["nstatv"]),
        props=[float(p) for p in manifest.get("props") or []],
        kinematics="finite" if kin.startswith("finite") else "small",
        ndi=int(manifest.get("ndi") or 3), nshr=int(manifest.get("nshr") or 3),
        cmname=str(manifest.get("name") or "MATERIAL"),
        store_dir=(STORE / key) if (STORE / key).is_dir() else None,
        family=(families.get(record["source_id"]) or {}).get("family", ""),
        initial_statev=[float(v) for v in manifest.get("initial_statev") or []],
        path_hints={"time_dependent": record.get("time_dependent"),
                    "total_time": (verification.get("time_scale_coverage") or {}).get("total_time"),
                    # The periods of the GENERATED experiment (the probe's
                    # segments), not the author's *STEP times; those are
                    # carried separately when the pass recorded them (G0).
                    "experiment_periods": [float(seg.get("period") or 0.0)
                                           for seg in manifest.get("loading") or []],
                    "author_deck_periods": (
                        [float(v) for v in verification["author_deck_periods"]]
                        if verification.get("author_deck_periods") is not None
                        else None),
                    "activation_amplitude": record.get("activation_amplitude"),
                    **({"documented_domain": council["documented_domain"]}
                       if council.get("documented_domain") else {}),
                    "source_text": (CACHE / record["cache_path"]).read_text(errors="replace")
                    if (CACHE / record["cache_path"]).is_file() else ""},
        provenance={"registry": str(REGISTRY), "manifest": f"{PASS16} key={key}",
                    "material_provenance": manifest.get("material_provenance", "")[:300],
                    "initial_state_from_user_subroutine":
                        bool(manifest.get("initial_state_from_user_subroutine")),
                    "terminal_state": record.get("terminal_state"), **origins},
        driver_point=(dict(_ZERO_POINT, provenance=COUNCIL_DRIVER_POINT) if council
                      else experiment_driver_point(key)))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ladder_steps(scale: float, ladder: Sequence[float]) -> list:
    return [h * scale for h in ladder]


def differentiable_props(source_text: str, nprops: int) -> tuple:
    """Split PROPS indices into (differentiable, {index: reason})."""
    from umat_oti.transform.parameter_sensitivity_transform import (
        NonDifferentiableParameterPathError,
        validate_parameter_paths,
    )
    ok, refused = [], {}
    for i in range(1, nprops + 1):
        try:
            validate_parameter_paths(source_text, ((f"P{i}", i),))
            ok.append(i)
        except NonDifferentiableParameterPathError as error:
            refused[i] = str(error)
    return ok, refused


@dataclass
class Builds:
    original: dv.Build = field(default_factory=dv.Build)
    store: dv.Build = field(default_factory=dv.Build)
    lifted: dv.Build = field(default_factory=dv.Build)
    lifted_ndir: int = 0
    lifted_reason: str = ""
    source_text: str = ""
    sdvini: bool = False
    gradient_driven: bool = False
    gradient_terms: dict = field(default_factory=dict)
    diff_props: list = field(default_factory=list)
    refused_props: dict = field(default_factory=dict)
    workarounds: list = field(default_factory=list)
    #: hidden-state gate variants of the ORIGINAL
    original_snan: dv.Build = field(default_factory=dv.Build)
    original_zero: dv.Build = field(default_factory=dv.Build)
    original_inf: dv.Build = field(default_factory=dv.Build)
    original_bounds: dv.Build = field(default_factory=dv.Build)
    #: the default-flag compile, kept for the record; the REFERENCE (``original``)
    #: is the zero-init build once it exists (D-12: deterministic where the
    #: source reads an uninitialised variable; identical elsewhere)
    original_default: dv.Build = field(default_factory=dv.Build)
    #: quad-precision reference build of the ORIGINAL (drivers.quadify), used
    #: only where the double ladder leaves entries unresolved
    original_quad: dv.Build = field(default_factory=dv.Build)
    uninitialised_hints: list = field(default_factory=list)
    identity: dict = field(default_factory=dict)       # build -> identity dict


def build_all(entry: CorpusEntry, work: Path, *, want_store: bool = True,
              want_lifted: bool = True, supply_utilities: bool = False) -> Builds:
    from umat_oti.abaqus.replay import defines_sdvini
    builds = Builds()
    work = Path(work)
    (work / "original").mkdir(parents=True, exist_ok=True)
    prepared, text, flags = dv.prepare_original_source(entry.original_source, work / "original")
    builds.source_text = text
    builds.sdvini = defines_sdvini(text)
    builds.original = dv.build_real(work / "original", [prepared], text, sdvini=builds.sdvini,
                                    unit_flags=[flags])
    for name, extra in (("original_snan", FINIT_SNAN), ("original_zero", FINIT_ZERO),
                        ("original_inf", FINIT_HUGE), ("original_bounds", BOUNDS)):
        setattr(builds, name, dv.build_real(work / name, [prepared], text, sdvini=builds.sdvini,
                                            unit_flags=[flags], extra_flags=extra))
    builds.uninitialised_hints = uninitialised_hints(prepared, flags)
    (work / "original_quad").mkdir(parents=True, exist_ok=True)
    qtext = dv.quadify(text)
    qfile = work / "original_quad" / ("original_quad_umat" + Path(prepared).suffix)
    qfile.write_text(qtext, encoding="utf-8")
    builds.original_quad = dv.build_real(work / "original_quad", [qfile], qtext, sdvini=builds.sdvini,
                                         unit_flags=[list(flags) + ["-fno-range-check", "-w"]],
                                         extra_flags=FINIT_ZERO, quad=True)
    builds.identity["original_quad"] = {
        "build": "original_quad", "role": "quad-precision FD reference (where double is unresolved)",
        "compiled_source": locator(qfile), "compiled_source_sha256": _sha256_file(qfile),
        "promotion": "REAL*8/DOUBLE PRECISION/REAL(8)/IMPLICIT REAL*8 -> REAL*16; default REAL "
                     "and every literal unchanged (drivers.quadify)"}
    builds.identity["original"] = {
        "build": "original", "role": "reference (finite differences, primal)",
        "source": locator(entry.original_source),
        "source_sha256": _sha256_file(entry.original_source),
        "compiled_source": locator(prepared), "compiled_source_sha256": _sha256_file(prepared),
        "preparation": "console writes silenced, author's PROGRAM removed (corpus replay helpers)"}
    builds.diff_props, builds.refused_props = differentiable_props(text, entry.nprops)

    if want_store and entry.store_dir is not None:
        store = Path(entry.store_dir)
        order = [line.strip() for line in (store / "compile_order.txt").read_text().splitlines()
                 if line.strip()]
        units = [store / name for name in order]
        unit_flags = [["-ffree-form", "-ffree-line-length-none"] if u.suffix == ".f90"
                      else ["-ffixed-form", "-ffixed-line-length-none"] for u in units]
        store_text = units[-1].read_text(errors="replace")
        builds.store = dv.build_real(work / "store", units, store_text, sdvini=False,
                                     unit_flags=unit_flags)
        store_entry = {}
        if (store / "entry.json").is_file():
            store_entry = json.loads((store / "entry.json").read_text())
        builds.identity["store"] = {
            "build": "store", "role": "value under test (primal, DDSDDE)",
            "transformer": "umat_oti.transform.source_transform (transform store entry)",
            "transformer_fingerprint": store_entry.get("fingerprint"),
            "store_entry": locator(store),
            "original_source_sha256_recorded_by_store": store_entry.get("source_sha256"),
            "compiled_units": {u.name: _sha256_file(u) for u in units},
            "compiled_source_sha256": _sha256_concat(units)}
        try:
            from umat_oti.transform.source_transform import seeded_kinematics
            drive = seeded_kinematics(store_text)
            builds.gradient_driven = drive.drives_deformation_gradient
            builds.gradient_terms = dict(drive.dfgrd1)
        except Exception as error:                                   # noqa: BLE001
            builds.store.reason += f"; seeded_kinematics failed: {error}"
    elif want_store:
        builds.store = dv.Build(reason="no transform-store entry for this key")

    if want_lifted:
        builds.lifted, builds.lifted_ndir, builds.lifted_reason = _build_lifted(
            entry, work / "lifted", builds, supply_utilities=supply_utilities)
    return builds


def _build_lifted(entry: CorpusEntry, work: Path, builds: Builds, *,
                  supply_utilities: bool = False) -> tuple:
    from umat_oti.transform.parameter_sensitivity_transform import (
        GenericPSContract,
        transform_umat_for_parameter_sensitivity,
    )
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    params = builds.diff_props or [1]
    ndir = max(len(params), entry.nstatv, entry.ntens, 1)
    lift_input = Path(work.parent / "original" / _prepared_name(work.parent / "original"))
    if supply_utilities:
        # OPT-IN workaround, recorded on every record: append the definitions
        # the transformer itself would supply (abaqus_utility_definitions) so
        # its _required_utility_stubs check, which reads the unsupplied text,
        # no longer refuses them. The ORIGINAL reference build is untouched.
        import re as _re

        from umat_oti.transform.abaqus_utility_definitions import (
            available_definitions,
            definition_text,
        )
        text = lift_input.read_text(errors="replace")
        called = {m.upper() for m in _re.findall(r"(?im)^[^cC*!].*?\bcall\s+(\w+)", text)}
        defined = {m.upper() for m in _re.findall(r"(?im)^\s*subroutine\s+(\w+)", text)}
        supplied = available_definitions(called - defined)
        if supplied:
            lift_input = work.parent / ("lift_input" + lift_input.suffix)
            lift_input.write_text(text + "\n" + definition_text(supplied), encoding="utf-8")
            builds.workarounds.append(f"supplied {', '.join(supplied)} from "
                                      "abaqus_utility_definitions before lifting")
    contract = GenericPSContract(
        name="corpus_features", umat_source_path=lift_input,
        parameters=tuple((f"P{i}", i) for i in params),
        parameter_values=tuple(entry.props[i - 1] if i <= entry.nprops else 0.0 for i in params),
        state_variables=tuple((f"S{l}", l) for l in range(1, entry.nstatv + 1)),
        ntens=entry.ntens, nstatv=max(entry.nstatv, 1), ndi=entry.ndi, nshr=entry.nshr,
        dstran_per_increment=(0.0,) * entry.ntens, n_increments=1,
        static_props=tuple(entry.props))
    try:
        layout = transform_umat_for_parameter_sensitivity(
            contract=contract, output_dir=work, extra_directions=ndir - len(params))
    except Exception as error:                                       # noqa: BLE001
        return dv.Build(reason=f"lift: {type(error).__name__}: {error}"[:1500]), ndir, "transform"
    # Only the lifted objects: the transformer's own ps_driver assumes the
    # standard scalar KSTEP and does not link for a source that declares
    # JSTEP(4) -- a defect of that driver, not of the lifted routine.
    objects = ["master_parameters.o", "real_utils.o", f"{layout.module_name}.o",
               "oti_intrinsics.o", "umat_oti_lifted.o", "abaqus_stubs.o"]
    done = subprocess.run(["make", f"FC={shutil.which('gfortran') or 'gfortran'}", *objects],
                          cwd=work, capture_output=True, text=True)
    if done.returncode != 0:
        return (dv.Build(reason=f"lifted compile failed: {(done.stdout + done.stderr)[-1500:]}"),
                ndir, "compile")
    build = dv.build_oti(work, work, layout.module_name, layout.type_name, ndir,
                         kstep_rank=dv.kstep_rank(layout.lifted_umat.read_text(errors="replace")))
    builds.identity["lifted"] = _lifted_identity(lift_input, Path(layout.lifted_umat))
    return build, ndir, "" if build.ok else "driver"


_FINGERPRINT: dict = {}


def _lifted_identity(lift_input: Path, lifted_source: Path) -> dict:
    if "live" not in _FINGERPRINT:
        try:
            from umat_oti.store.transform_store import transform_fingerprint
            _FINGERPRINT["live"] = transform_fingerprint()
        except Exception as error:                                   # noqa: BLE001
            _FINGERPRINT["live"] = f"unavailable: {error}"
    return {"build": "lifted", "role": "value under test (parameter / state sensitivities)",
            "transformer": "umat_oti.transform.parameter_sensitivity_transform."
                           "transform_umat_for_parameter_sensitivity (generic PROPS lifter)",
            "transformer_fingerprint": _FINGERPRINT["live"],
            "transformer_fingerprint_note": "transform_fingerprint() of the working tree this "
                                            "run imported (uncommitted edits included)",
            "lift_input": locator(lift_input), "lift_input_sha256": _sha256_file(lift_input),
            "compiled_source": locator(lifted_source),
            "compiled_source_sha256": _sha256_file(lifted_source)}


def _sha256_file(path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _sha256_concat(paths) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).name.encode() + b"\0")
        try:
            digest.update(Path(path).read_bytes())
        except OSError:
            pass
    return digest.hexdigest()


def uninitialised_hints(source: Path, form_flags) -> list:
    """Variables gfortran's data-flow analysis flags as (maybe) used uninitialised.

    Hints only, for the reason of a hidden-state trip: the gate itself is the
    snan/zero history comparison, which needs no analysis to be right.
    """
    import tempfile
    if shutil.which("gfortran") is None:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        done = subprocess.run(["gfortran", "-O1", "-std=legacy", *form_flags, "-Wuninitialized",
                               "-Wmaybe-uninitialized", f"-I{Path(source).parent}", "-c",
                               str(source), "-o", str(Path(tmp) / "lint.o"), f"-J{tmp}"],
                              capture_output=True, text=True)
    names = re.findall(r"[\u2018'](\w+)[\u2019'] (?:is|may be) used uninitialized",
                       done.stderr)
    return sorted(set(n.lower() for n in names))


def _prepared_name(directory: Path) -> str:
    return next(p.name for p in Path(directory).glob("original_umat.*"))


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------

def _config(entry: CorpusEntry, increments: list, statev0, call_sdvini: bool,
            props: Optional[Sequence[float]] = None) -> dv.RunConfig:
    return dv.RunConfig(ntens=entry.ntens, nstatv=entry.nstatv, nprops=entry.nprops,
                        ndi=entry.ndi, nshr=entry.nshr,
                        props=list(entry.props if props is None else props),
                        statev0=list(statev0), cmname=entry.cmname, increments=increments,
                        call_sdvini=call_sdvini,
                        coords=tuple(float(c) for c in entry.driver_point["coords"]),
                        noel=int(entry.driver_point["noel"]),
                        npt=int(entry.driver_point["npt"]))


def _run_real(build: dv.Build, work: Path, config: dv.RunConfig,
              perturbations: Sequence[dv.Perturbation], entry: CorpusEntry, *,
              fresh: bool = False):
    """Run the real driver in ``work``; ``fresh`` empties the directory first,
    so a routine that reads/writes files sees the same environment in every
    run that is compared against another (D-12: only then can a zero/snan
    difference be attributed to uninitialised memory)."""
    work = Path(work)
    if fresh and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    config.write(work)
    pert = work / dv.PERT_FILE
    if perturbations:
        dv.write_perturbations(work, perturbations)
    elif pert.exists():
        pert.unlink()
    ok, message = dv.run_program(build, work)
    if not ok:
        return None, message
    return dv.parse_real_output(work / dv.REAL_OUT, entry.ntens, entry.nstatv), ""


def _run_oti(build: dv.Build, work: Path, config: dv.RunConfig, mode: str,
             seeds: Sequence[dv.Seed], entry: CorpusEntry, ndir: int):
    config.write(work)
    dv.write_seeds(work, mode, seeds)
    ok, message = dv.run_program(build, work)
    if not ok:
        return None, message
    return dv.parse_oti_output(work / dv.OTI_OUT, entry.ntens, entry.nstatv, ndir), ""


def _base_arrays(base: dict, n: int, name: str) -> np.ndarray:
    """Per-increment array; an increment the run never reached (the routine
    stopped the program) is NaN, so it can never agree with anything."""
    width = next((np.asarray(row[name], float).shape for row in base.values()), None)
    if width is None:
        raise KeyError(f"no increment of the run returned {name}")
    return np.array([np.asarray(base[i][name], float) if i in base else np.full(width, np.nan)
                     for i in range(1, n + 1)])


def _increments(entry: CorpusEntry, path) -> list:
    kin = kinematics_for(path, entry.ndi, entry.nshr)
    return [(d, f0, f1, r, inc.dtime, inc.temp, inc.dtemp)
            for (d, f0, f1, r), inc in zip(kin, path.increments)]


# ---------------------------------------------------------------------------
# hidden-state gate (Vera B1/A)
# ---------------------------------------------------------------------------

_FIELDS = ("stress", "statev", "ddsdde", "sse", "spd", "scd", "pnewdt")


def _same(a, b) -> bool:
    return bool(np.array_equal(np.asarray(a, float), np.asarray(b, float), equal_nan=True))


def _name(field_name: str, flat_index: int, ntens: int) -> str:
    if field_name == "stress":
        return f"STRESS({flat_index + 1})"
    if field_name == "statev":
        return f"STATEV({flat_index + 1})"
    if field_name == "ddsdde":
        return f"DDSDDE({flat_index // ntens + 1},{flat_index % ntens + 1})"
    return field_name.upper()


def first_difference(reference: Mapping, other: Mapping, ntens: int,
                     fields: Sequence[str] = _FIELDS,
                     mask: Optional[Mapping] = None) -> Optional[str]:
    """The first DEFINED output that is not bit-identical, named, or None.

    ``mask[field]`` (flat bool, True = undefined_in_original) removes outputs
    that differ between the zero-init and snan-init builds (D-12): those are
    expected to move and are never compared.
    """
    for inc in sorted(reference):
        if inc not in other:
            return f"increment {inc} missing"
        for name in fields:
            if name not in reference[inc] or name not in other[inc]:
                continue
            a = np.asarray(reference[inc][name], float).reshape(-1)
            b = np.asarray(other[inc][name], float).reshape(-1)
            if a.shape != b.shape:
                return f"{name} shape {a.shape} vs {b.shape} at increment {inc}"
            differ = ~((a == b) | (np.isnan(a) & np.isnan(b)))
            if mask is not None and name in mask:
                m = np.asarray(mask[name], bool).reshape(-1)
                if m.shape == differ.shape:
                    differ &= ~m
            if differ.any():
                k = int(np.flatnonzero(differ)[0])
                return f"{_name(name, k, ntens)} at increment {inc}: {float(a[k])!r} vs {float(b[k])!r}"
    return None


@dataclass
class Undefined:
    """Outputs of the ORIGINAL that are undefined behaviour on one path (D-12).

    An output is ``undefined_in_original`` when the zero-init and the
    snan-init compiles of the original give different values for it anywhere
    on the path -- in the base history or in any perturbed call. It is never
    compared and never verified, on any state of that path; every other
    output was bit-identical across both builds over the whole history, which
    is the evidence that it does not depend on the uninitialised value.
    """
    ntens: int
    nstatv: int
    stress: np.ndarray = None
    statev: np.ndarray = None
    ddsdde: np.ndarray = None
    scalars: dict = field(default_factory=dict)
    details: list = field(default_factory=list)

    def __post_init__(self):
        nt, nx = self.ntens, self.nstatv
        self.stress = np.zeros(nt, bool) if self.stress is None else self.stress
        self.statev = np.zeros(nx, bool) if self.statev is None else self.statev
        self.ddsdde = np.zeros((nt, nt), bool) if self.ddsdde is None else self.ddsdde
        for s in ("sse", "spd", "scd", "pnewdt"):
            self.scalars.setdefault(s, False)

    def mask(self) -> dict:
        return {"stress": self.stress, "statev": self.statev, "ddsdde": self.ddsdde.reshape(-1),
                **{k: np.array([v]) for k, v in self.scalars.items()}}

    def output_vector(self) -> np.ndarray:
        """True where a (STRESS, STATEV) output is undefined."""
        return np.concatenate([self.stress, self.statev])

    @property
    def any(self) -> bool:
        return bool(self.stress.any() or self.statev.any() or self.ddsdde.any()
                    or any(self.scalars.values()))

    @property
    def stress_or_ddsdde(self) -> bool:
        return bool(self.stress.any() or self.ddsdde.any())

    def _mark(self, name: str, k: int, inc, zero, snan, where: str, path: str):
        if name == "stress":
            target, flag = self.stress, k
        elif name == "statev":
            target, flag = self.statev, k
        elif name == "ddsdde":
            target, flag = self.ddsdde.reshape(-1), k
        else:
            if self.scalars.get(name):
                return
            self.scalars[name] = True
            target = None
        if target is not None:
            if target[flag]:
                return
            target[flag] = True
            if name == "ddsdde":
                self.ddsdde = target.reshape(self.ntens, self.ntens)
        self.details.append({"output": _name(name, k, self.ntens), "path": path,
                             "first_increment": inc, "where": where,
                             "zero_init": _num_or_str(zero), "snan_init": _num_or_str(snan)})

    def collect(self, zero: Mapping, snan: Mapping, where: str, path: str,
                fields: Sequence[str] = _FIELDS):
        """Mark every output that differs between two tables of records."""
        for key in sorted(zero):
            if key not in snan:
                continue
            a_rec, b_rec = zero[key], snan[key]
            if not isinstance(a_rec, Mapping):           # L/T tuples
                a_rec = dict(zip(("stress", "statev", "pnewdt"), a_rec))
                b_rec = dict(zip(("stress", "statev", "pnewdt"), b_rec))
            inc = key if isinstance(key, int) else key
            for name in fields:
                if name not in a_rec or name not in b_rec:
                    continue
                a = np.asarray(a_rec[name], float).reshape(-1)
                b = np.asarray(b_rec[name], float).reshape(-1)
                if a.shape != b.shape:
                    continue
                differ = ~((a == b) | (np.isnan(a) & np.isnan(b)))
                for k in np.flatnonzero(differ):
                    self._mark(name, int(k), inc, a[k], b[k], where, path)


def _num_or_str(x):
    x = float(x)
    return x if math.isfinite(x) else str(x)


def hidden_state_pregate(entry: CorpusEntry, builds: Builds, path, work: Path) -> tuple:
    """Unperturbed-history gates. Returns (pristine, trips, message, undefined).

    * ``pristine`` is the history of the REFERENCE build (``builds.original``,
      the zero-init compile when it built);
    * the snan-init compile runs the same history; every output that differs
      is ``undefined_in_original`` on this path (D-12: a SOURCE defect,
      reported with the gfortran-flagged variables, never compared) -- it is
      NOT a trip any more;
    * the ``-fcheck=bounds`` compile must run the history (a stop is a trip);
      a failed variant build or run is a trip (the gate cannot be applied).
    """
    increments = _increments(entry, path)
    statev0 = entry.initial_statev or [0.0] * entry.nstatv
    call_sdv = builds.sdvini and not any(statev0)
    config = _config(entry, increments, statev0, call_sdv)
    undefined = Undefined(entry.ntens, entry.nstatv)
    pristine, message = (_run_real(builds.original, work / "original", config, [], entry, fresh=True)
                         if builds.original.ok else (None, builds.original.reason))
    trips = []
    if pristine is None:
        return None, trips, message, undefined
    # determinism: the reference twice from scratch, bit-identical on EVERY
    # output (no mask) -- a clock, random number or environment read is
    # hidden state, never "undefined"
    repeat, message = _run_real(builds.original, work / "original_repeat", config, [], entry,
                                fresh=True)
    if repeat is None:
        trips.append(f"repeat of the reference run failed on path {path.name}: {message[-300:]}")
    else:
        diff = first_difference(pristine.base, repeat.base, entry.ntens)
        if diff:
            trips.append(f"nondeterministic: two identical runs of the reference differ on path "
                         f"{path.name}: {diff}")
    for name in ("original_snan", "original_inf", "original_bounds"):
        build = getattr(builds, name)
        if not build.ok:
            trips.append(f"{name} build failed ({build.reason}); the gate cannot be applied")
            continue
        out, message = _run_real(build, work / name, config, [], entry, fresh=True)
        if out is None:
            what = ("-fcheck=bounds run stopped" if name == "original_bounds"
                    else f"{name} run failed")
            trips.append(f"{what} on path {path.name}: {message.strip()[-400:]}")
            continue
        if name in ("original_snan", "original_inf"):
            if builds.original is not builds.original_zero:
                trips.append("zero-init build unavailable: undefined outputs cannot be separated")
            undefined.collect(pristine.base, out.base, f"base history ({name})", path.name)
            zero0 = np.asarray(pristine.initial_statev, float)
            snan0 = np.asarray(out.initial_statev, float)
            if zero0.shape == snan0.shape:
                for k in np.flatnonzero(~((zero0 == snan0) | (np.isnan(zero0) & np.isnan(snan0)))):
                    if k < entry.nstatv:
                        undefined._mark("statev", int(k), 0, zero0[k], snan0[k],
                                        "initial STATEV (SDVINI)", path.name)
    return pristine, trips, "", undefined


TERMINATED = "original terminated under perturbation (STOP/XIT)"


def first_missing_record(run, perts: Sequence[dv.Perturbation], n_inc: int) -> Optional[dict]:
    """The first record, in the real driver's write order, that a perturbation
    run of the ORIGINAL did not write; None when the run is complete.

    The driver runs every perturbation in ONE process, so a routine that
    STOPs (or CALLs XIT) under a perturbed input ends the program there with
    exit status 0: every later record -- the rest of that local block, every
    later increment, every total re-run, the replays -- is simply absent.
    The missing record names the call that did not return (the base call of
    increment k, local perturbation ip with sign sg at increment k, total
    perturbation ip with sign sg at increment k, or a replay).
    """
    local = [ip for ip, p in enumerate(perts, 1) if p.mode == "local"]
    total = [ip for ip, p in enumerate(perts, 1) if p.mode == "total"]

    def what(ip, sg):
        p = perts[ip - 1]
        return f"{p.mode} {p.kind}({p.index}) {'+' if sg > 0 else '-'}h, h={p.step:g}"

    for inc in range(1, n_inc + 1):
        if inc not in run.base:
            return {"increment": inc, "call": f"unperturbed base call (increment {inc})"}
        for ip in local:
            for sg in (1, -1):
                if (inc, ip, sg) not in run.local:
                    return {"increment": inc, "call": what(ip, sg), "ip": ip, "sign": sg}
        if local and inc not in run.replay:
            return {"increment": inc, "call": f"replay of the unperturbed call (increment {inc})"}
    for ip in total:
        for sg in (1, -1):
            for m in range(1, n_inc + 1):
                if (ip, sg, m) not in run.total:
                    return {"increment": m, "call": what(ip, sg), "ip": ip, "sign": sg}
        if ip not in run.total_replay:
            return {"increment": 1, "call": f"increment-1 replay after total block {ip}"}
    if total:
        for m in range(1, n_inc + 1):
            if m not in run.zero_total:
                return {"increment": m, "call": f"h=0 total re-run (increment {m})"}
    return None


def termination_reason(stop: Mapping, build: str = "original") -> str:
    return (f"{TERMINATED} at increment {stop['increment']} ({build} build; first call that "
            f"did not return: {stop['call']}; the records after it were never written)")


def is_derivative_feature(feature: str) -> bool:
    return feature == "ddsdde" or feature.endswith(("_sens_local", "_sens_total"))


def apply_gate_notes(records: list) -> list:
    """Explicit rule (Vera B5 r2, item G): a hidden-state gate check that was
    NOT APPLIED on a path (``gates.hidden_state_gate_notes``, e.g. an isolation
    probe whose in-process record the original never wrote) leaves that path
    without the evidence that restored-state FD is a valid reference. Its
    derivative records (ddsdde, sensitivities) are then not verified: a
    ``verified`` one becomes ``not_attempted`` with the note as the reason.
    (Before, only the constants m=(n+1)//2 and MIN_STATE_COVERAGE=0.5 made
    such a path fall short of coverage.) A ``failed`` record stands. Idempotent."""
    for record in records:
        notes = (record.get("gates") or {}).get("hidden_state_gate_notes") or []
        if notes and record.get("status") == "verified" and is_derivative_feature(
                record.get("feature", "")):
            record["status_before_gate_notes"] = record["status"]
            record["reason_before_gate_notes"] = record.get("reason")
            record["status"] = "not_attempted"
            record["reason"] = ("hidden-state gate not applied on this path: " + notes[0]
                                + (f" (+{len(notes) - 1} more)" if len(notes) > 1 else ""))
    return records


def hidden_state_gate(entry: CorpusEntry, builds: Builds, path, work: Path, pristine,
                      perturbed, config: dv.RunConfig, perts: Sequence[dv.Perturbation],
                      index: Mapping, *, tangent_kind: str = "", ladder=fd.DEFAULT_LADDER,
                      undefined: Optional[Undefined] = None,
                      notes: Optional[list] = None) -> list:
    """Gates on the perturbation run. Every check is bit-exact on every DEFINED
    output (``undefined`` masks the outputs that are undefined_in_original).

    1. base trajectory inside the perturbation run == pristine run;
    2. the unperturbed call replayed after every local block (``R``) == base;
    3. the increment-1 call replayed after every total block (``Q``) == base;
    4. an h=0 total re-run after all total blocks (``Z``) == base;
    5. process isolation: a FRESH process started with the perturbed input
       reproduces the in-process perturbed call (PROPS: whole history vs the
       in-process total run; DSTRAN: increment m vs the in-process local call;
       incoming STATEV at increment 1 vs the in-process local call). This is
       what catches SAVEd data initialised from PROPS on the first call (Vera's
       toy a1), which leaves every in-process base call unchanged.
    """
    nt = entry.ntens
    trips = []
    notes = [] if notes is None else notes
    mask = undefined.mask() if undefined is not None else None
    n_inc = len(config.increments)
    stop = first_missing_record(perturbed, perts, n_inc)
    # A run the ORIGINAL ended (STOP/XIT under a perturbed input) is compared
    # on the records it wrote; what it never wrote is a termination (columns
    # needing it are not judged), not a hidden-state difference.
    reached = (lambda table: table) if stop is None else (
        lambda table: {i: v for i, v in table.items() if i in perturbed.base})
    diff = first_difference(reached(pristine.base), perturbed.base, nt, mask=mask)
    if diff:
        trips.append(f"base trajectory inside the perturbation run differs from the pristine run: {diff}")
    if perturbed.replay:
        diff = first_difference({i: pristine.base[i] for i in perturbed.replay}, perturbed.replay, nt, mask=mask)
        if diff:
            trips.append(f"unperturbed call replayed after the local perturbation block differs: {diff}")
    for ip, rec in sorted(perturbed.total_replay.items()):
        diff = first_difference({1: pristine.base[1]}, {1: rec}, nt, mask=mask)
        if diff:
            p = perts[ip - 1]
            trips.append(f"increment-1 call replayed after the total block {p.kind}({p.index}) "
                         f"h={p.step:g} differs: {diff}")
            break
    if perturbed.zero_total:
        diff = first_difference({i: pristine.base[i] for i in perturbed.zero_total}
                                if stop is not None else pristine.base,
                                perturbed.zero_total, nt, mask=mask)
        if diff:
            trips.append(f"h=0 total re-run after the total perturbation blocks differs: {diff}")
    # 5. process isolation
    probe_root = Path(work) / "isolation"
    short = ("stress", "statev", "pnewdt")

    def fresh(name, cfg):
        out, message = _run_real(builds.original, probe_root / name, cfg, [], entry, fresh=True)
        if out is None:
            trips.append(f"isolation probe {name} did not run: {message[-300:]}")
        return out

    for i in builds.diff_props[:8]:
        key = ("total", "props", i, 0)
        if key not in index:
            continue
        ip = index[key]
        props = list(config.props)
        props[i - 1] = props[i - 1] + perts[ip - 1].step
        out = fresh(f"props{i}", dv.RunConfig(**{**config.__dict__, "props": props}))
        if out is None:
            continue
        # Only the increments the in-process run produced: an original that
        # STOPs part-way through a path ends its history there (that path is
        # reported not_attempted with the reason); comparing increments it
        # never reached raised KeyError and lost the whole source.
        inproc = {m: dict(zip(short, perturbed.total[(ip, 1, m)]))
                  for m in range(1, n_inc + 1) if (ip, 1, m) in perturbed.total}
        if not inproc:
            notes.append(f"isolation probe PROPS({i}) not applied: {termination_reason(stop)}"
                         if stop else f"isolation probe PROPS({i}) not applied: no total record")
            continue
        base = {m: v for m, v in out.base.items() if m in inproc}
        diff = first_difference(inproc, base, nt, short, mask=mask)
        if diff:
            trips.append(f"fresh process with PROPS({i})+h differs from the in-process total "
                         f"perturbation (SAVE/COMMON state carried between calls): {diff}")
    if tangent_kind == "dstran" and ("local", "dstran", 1, 0) in index and n_inc:
        m = (n_inc + 1) // 2
        ip = index[("local", "dstran", 1, 0)]
        incs = [list(x) for x in config.increments]
        d = list(incs[m - 1][0])
        d[0] = d[0] + perts[ip - 1].step
        incs[m - 1][0] = d
        out = fresh("dstran1", dv.RunConfig(**{**config.__dict__,
                                               "increments": [tuple(x) for x in incs]}))
        # A path whose original stopped before increment m has no such call
        # (in-process); a fresh run that stopped earlier is a difference.
        if out is not None and (m, ip, 1) not in perturbed.local:
            notes.append(f"isolation probe DSTRAN(1) not applied: {termination_reason(stop)}"
                         if stop else "isolation probe DSTRAN(1) not applied")
        elif out is not None:
            diff = first_difference({m: dict(zip(short, perturbed.local[(m, ip, 1)]))},
                                    {m: out.base[m]} if m in out.base else {}, nt, short, mask=mask)
            if diff:
                trips.append("fresh process with DSTRAN(1)+h at increment "
                             f"{m} differs from the in-process restored-state call: {diff}")
    for l in range(1, min(entry.nstatv, 3) + 1):
        key = ("local", "statev", l, 0)
        if key not in index or (undefined is not None and undefined.statev[l - 1]):
            continue
        ip = index[key]
        statev0 = list(config.statev0)
        statev0[l - 1] = statev0[l - 1] + perts[ip - 1].step
        out = fresh(f"statev{l}", dv.RunConfig(**{**config.__dict__, "statev0": statev0}))
        if out is not None and (1, ip, 1) not in perturbed.local:
            notes.append(f"isolation probe STATEV({l}) not applied: {termination_reason(stop)}"
                         if stop else f"isolation probe STATEV({l}) not applied")
        elif out is not None:
            diff = first_difference({1: dict(zip(short, perturbed.local[(1, ip, 1)]))},
                                    {1: out.base[1]} if 1 in out.base else {}, nt, short, mask=mask)
            if diff:
                trips.append(f"fresh process with incoming STATEV({l})+h differs from the "
                             f"in-process restored-state call at increment 1: {diff}")
    return trips


# ---------------------------------------------------------------------------
# branch signatures
# ---------------------------------------------------------------------------

def _signature(x_in: np.ndarray, x_out: np.ndarray, pnewdt: float,
               ignore: frozenset = frozenset()) -> tuple:
    """The discrete state of one call: which STATEV moved, and a cutback flag.

    Slots in ``ignore`` (STATEV shown not to affect the judged block) are left
    out of the signature.
    """
    # Bit-exact: a STATEV the routine leaves alone comes back identical, and a
    # relative threshold hid a plastic multiplier of 2e-14 switching on from a
    # degenerate yield surface (Lemaitre, xn = 200: Sf ~ 0) -- measured.
    x_in, x_out = np.asarray(x_in, float), np.asarray(x_out, float)
    moved = tuple(bool(v) for l, v in enumerate(x_out != x_in) if l not in ignore)
    return moved + (bool(pnewdt < 1.0),)


def _consistent(x_in_p, x_out_p, p_p, x_in_m, x_out_m, p_m, x_in_b, x_out_b, p_b,
                ignore: frozenset = frozenset()) -> bool:
    """Did the +h and -h calls stay on the unperturbed call's branch?

    The discrete state of a call is which STATEV moved and whether it asked
    for a cutback. Both perturbed calls must agree with each other, and with
    the unperturbed call -- except for a STATEV that did not move at the base
    but moves ANTISYMMETRICALLY under +/-h (a stored smooth function of the
    perturbed input), which is smooth dependence and not a branch change.
    """
    keep = [l for l in range(len(np.atleast_1d(x_out_b))) if l not in ignore]
    sp = _signature(x_in_p, x_out_p, p_p, ignore)
    sm = _signature(x_in_m, x_out_m, p_m, ignore)
    sb = _signature(x_in_b, x_out_b, p_b, ignore)
    if sp != sm:
        return False
    if sp == sb:
        return True
    if sp[-1] != sb[-1]:
        return False
    xb = np.asarray(x_out_b, float)
    dp = np.asarray(x_out_p, float) - xb
    dm = np.asarray(x_out_m, float) - xb
    for pos, (a, b) in enumerate(zip(sp[:-1], sb[:-1])):
        if a == b:
            continue
        l = keep[pos]
        if b:          # moved at the base, frozen under both perturbations
            return False
        if abs(dp[l] + dm[l]) > 0.5 * max(abs(dp[l]), abs(dm[l])):
            return False
    return True


def stress_irrelevant_slots(perturbed, index: Mapping, base_stress: np.ndarray, nstatv: int,
                            n_inc: int, ladder, stress_undefined=None) -> frozenset:
    """STATEV slots shown not to affect STRESS across +/-h on this path.

    Slot l qualifies when perturbing the INCOMING STATEV(l) by every ladder
    step, in both directions, at every increment, returns the base STRESS
    bit-for-bit. Such a slot can still move with a branch of its own (a
    diagnostic flag, an uninitialised scratch value) without that branch
    reaching the stress, so it is left out of the signature of STRESS columns.
    """
    out = set()
    for l in range(1, nstatv + 1):
        keys = [index.get(("local", "statev", l, k)) for k in range(len(ladder))]
        if any(k is None for k in keys):
            continue
        same = True
        for inc in range(1, n_inc + 1):
            for ip in keys:
                for sg in (1, -1):
                    if (inc, ip, sg) not in perturbed.local:
                        # not reached (the original stopped): irrelevance is not shown
                        same = False
                        break
                    a = np.asarray(perturbed.local[(inc, ip, sg)][0], float)
                    b = np.asarray(base_stress[inc - 1], float)
                    if stress_undefined is not None:
                        a, b = a[~stress_undefined], b[~stress_undefined]
                    if not np.array_equal(a, b):
                        same = False
                        break
                if not same:
                    break
            if not same:
                break
        if same:
            out.add(l - 1)
    return frozenset(out)


def canonical_strain_direction(j: int, ndi: int, nshr: int) -> np.ndarray:
    """Abaqus strain direction of Voigt column ``j`` (1-based), from the kinematics alone.

    Direct components: ``eps_aa = 1``. Shear components are ENGINEERING shear
    (DDSDDE columns are per unit gamma), so ``eps_ab = eps_ba = 1/2``. Built
    without reading the store's seed map; :func:`build_all` callers compare
    the two (Vera B1/A: the FD direction must not come from the code path
    under test).
    """
    from umat_oti.corpus_features.paths import VOIGT_3D, voigt_components
    a, b = VOIGT_3D[voigt_components(ndi, nshr)[j - 1]]
    eps = np.zeros((3, 3))
    if a == b:
        eps[a, a] = 1.0
    else:
        eps[a, b] = eps[b, a] = 0.5
    return eps


# ---------------------------------------------------------------------------
# feature accounting
# ---------------------------------------------------------------------------

TOLERANCE_RULE = (
    "entrywise: D_e, u_e from the entry's own FD-only plateau (>=3 consecutive ladder steps "
    "agreeing within max(rtol|D|, round-off); the 3-step window of smallest spread; u_e = "
    "spread); atol_e = 8 eps F_e / h_(3) (F_e = max(the output's own magnitude at the state: "
    "incoming, base, perturbed; max|D| of the column x |input|); h_(3) third-largest step); "
    "|D_e| <= atol_e: structural zero, pass iff |oti| <= atol_e + 2u_e (needs u_e <= atol_e); "
    "else u_e or atol_e > 1e-3|D_e| -> unresolved; else pass iff |oti - D_e| <= atol_e + rtol|D_e| + 2u_e")


class PerturbationTerminated(Exception):
    """A column needs records that a perturbed run of the original never
    wrote (the routine ended the program under a perturbed input)."""


@dataclass
class FeatureTally:
    feature: str
    ladder: Sequence[float]
    rtol: float
    states: dict = field(default_factory=dict)        # inc -> Counter
    eps: float = fd.EPS                               # unit round-off of the reference
    column_status: Counter = field(default_factory=Counter)
    entries: Counter = field(default_factory=Counter)
    max_abs: float = 0.0
    max_rel: float = 0.0
    max_ratio: float = 0.0
    max_rel_tolerance: float = 0.0
    worst: dict = field(default_factory=dict)
    min_plateau: Optional[int] = None
    orders: list = field(default_factory=list)
    nonsmooth: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    unresolved_examples: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    signature_ignored_statev: list = field(default_factory=list)
    #: wrt -> [states where this input's column was judged, states seen]
    per_input: dict = field(default_factory=dict)
    #: column-max Euler round-off term (fd.judge_column): True on the STRESS
    #: block; "bracket" on a STATEV block (mixed units: an entry whose verdict
    #: depends on the term is unresolved)
    euler: object = True
    #: columns not judged because a perturbed run of the ORIGINAL ended
    #: (STOP/XIT) before writing the records they need: {reason: count}
    terminations: Counter = field(default_factory=Counter)

    def terminated(self, inc: int, wrt: str, reason: str):
        """A column at this state is not judged: a perturbed run of the
        original (any build) terminated before writing a record it needs.
        The state then is not judged (coverage rule); nothing is compared."""
        state = self.states.setdefault(inc, Counter())
        state["columns"] += 1
        state["terminated"] += 1
        self.per_input.setdefault(wrt, [0, 0])[1] += 1
        self.terminations[reason] += 1

    def add(self, inc: int, wrt: str, column: fd.ColumnFD, oti: np.ndarray,
            output_names: Sequence[str], magnitude: np.ndarray, undefined=None,
            value_magnitude=None, derivative_scale: float = 0.0, probe: bool = False,
            kinematic_input: float = 0.0, block_derivative: float = 0.0, double_zero=None):
        """Judge one column at one state (entries of the judged block only).

        ``derivative_scale``: the column's derivative scale over the PATH (the
        largest |FD reference| of this input's column at any state); it caps
        the value-under-test round-off term and decides structural zeros
        (fd.judge_column). ``probe=True`` records nothing and returns the
        largest |FD reference| of the column at this state (0 if not judged).

        ``undefined`` (bool per entry): outputs that are undefined_in_original
        (D-12) -- excluded from the comparison, counted as such, and neither
        resolved nor unresolved.
        """
        state = Counter() if probe else self.states.setdefault(inc, Counter())
        state["columns"] += 1
        oti = np.asarray(oti, float)
        if undefined is not None and np.any(undefined):
            undefined = np.asarray(undefined, bool)
            if not probe:
                self.entries["undefined_in_original"] += int(undefined.sum())
            keep = ~undefined
            if not keep.any():
                state["all_undefined"] += 1
                return 0.0
            import copy
            column = copy.copy(column)
            column.estimates = [np.asarray(e)[keep] for e in column.estimates]
            column.forward = [np.asarray(e)[keep] for e in column.forward]
            column.backward = [np.asarray(e)[keep] for e in column.backward]
            oti = oti[keep]
            magnitude = np.asarray(magnitude)[keep]
            if double_zero is not None:
                double_zero = np.asarray(double_zero, bool)[keep]
            if value_magnitude is not None:
                value_magnitude = np.asarray(value_magnitude)[keep]
            output_names = [n for n, k in zip(output_names, keep) if k]
        if probe:
            if not column.smooth:
                return 0.0
            ref = fd.judge_column(oti, column.estimates, column.usable, self.ladder,
                                  steps=column.steps, magnitude=magnitude, rtol=self.rtol,
                                  eps=self.eps, euler=self.euler,
                                  kinematic_input=kinematic_input,
                                  block_derivative=block_derivative).reference
            ref = np.abs(ref[np.isfinite(ref)])
            # entries without a plateau still have a size: the central
            # difference at the largest usable step (least round-off; a scale,
            # not a reference)
            first = [np.abs(np.asarray(column.estimates[k], float)) for k in column.usable[:1]]
            first = first[0][np.isfinite(first[0])] if first else np.zeros(0)
            return float(max(ref.max() if ref.size else 0.0, first.max() if first.size else 0.0))
        seen = self.per_input.setdefault(wrt, [0, 0])
        seen[1] += 1
        if not column.smooth:
            state["nonsmooth"] += 1
            if len(self.nonsmooth) < 12:
                k = column.finite[-1] if column.finite else None
                near = None
                if k is not None:
                    fwd, bwd = np.asarray(column.forward[k]), np.asarray(column.backward[k])
                    scale = max(float(np.max(np.abs(fwd), initial=0.0)),
                                float(np.max(np.abs(bwd), initial=0.0)), 1e-300)
                    near = {"oti_vs_forward": float(np.max(np.abs(oti - fwd), initial=0.0)) / scale,
                            "oti_vs_backward": float(np.max(np.abs(oti - bwd), initial=0.0)) / scale,
                            "at_relative_step": self.ladder[k]}
                self.nonsmooth.append({"increment": inc, "wrt": wrt, "reason": column.reason,
                                       "one_sided": near})
            return
        verdict = fd.judge_column(oti, column.estimates, column.usable, self.ladder,
                                  steps=column.steps, magnitude=magnitude, rtol=self.rtol,
                                  eps=self.eps, value_magnitude=value_magnitude,
                                  euler=self.euler, derivative_scale=derivative_scale,
                                  kinematic_input=kinematic_input,
                                  block_derivative=block_derivative, double_zero=double_zero)
        self.column_status[verdict.status] += 1
        for code in verdict.codes:
            self.entries[code] += 1
        state["unresolved"] += verdict.unresolved
        state["failed"] += verdict.failed
        seen[0] += int(verdict.unresolved == 0)
        state["passed"] += verdict.passed
        state["zero_passed"] += verdict.zero_passed
        for e, o, r, tol, plateau in verdict.failed_entries:
            if len(self.failures) < 20:
                self.failures.append({"increment": inc, "wrt": wrt, "output": output_names[e],
                                      "oti": o, "fd": r, "tolerance": tol,
                                      "plateau_relative_steps": list(plateau)})
        if verdict.unresolved and len(self.unresolved_examples) < 12:
            e = next(i for i, c in enumerate(verdict.codes) if c.startswith("unresolved"))
            self.unresolved_examples.append({
                "increment": inc, "wrt": wrt, "output": output_names[e], "code": verdict.codes[e],
                "oti": float(oti[e]), "fd_plateau_value": _num(verdict.reference[e]),
                "u": _num(verdict.uncertainty[e]), "atol": float(verdict.atol[e]),
                "ladder": [_num(np.asarray(x)[e]) for x in column.estimates]})
        if column.order is not None:
            self.orders.append(column.order)
        if verdict.min_plateau and (self.min_plateau is None or verdict.min_plateau < self.min_plateau):
            self.min_plateau = verdict.min_plateau
        self.max_abs = max(self.max_abs, verdict.max_abs)
        self.max_ratio = max(self.max_ratio, verdict.max_ratio)
        self.max_rel_tolerance = max(self.max_rel_tolerance, verdict.max_rel_tolerance)
        if verdict.worst_entry >= 0 and (not self.worst or verdict.max_rel >= self.max_rel):
            e = verdict.worst_entry
            self.worst = {"increment": inc, "wrt": wrt, "output": output_names[e],
                          "oti": float(oti[e]), "fd": float(verdict.reference[e]),
                          "u": float(verdict.uncertainty[e]),
                          "abs": float(abs(oti[e] - verdict.reference[e])),
                          "rel": verdict.max_rel, "tolerance": verdict.tolerance_at_worst,
                          "plateau_relative_steps": list(verdict.plateau_steps)}
            self.max_rel = max(self.max_rel, verdict.max_rel)

    def coverage(self) -> dict:
        n = len(self.states)
        judged = sum(1 for c in self.states.values()
                     if c["columns"] and not c["nonsmooth"] and not c["unresolved"]
                     and not c["terminated"])
        return {"n_states": n, "n_states_judged": judged,
                "n_states_terminated_under_perturbation": sum(1 for c in self.states.values()
                                                              if c["terminated"]),
                "n_states_with_nonsmooth_columns": sum(1 for c in self.states.values() if c["nonsmooth"]),
                "n_states_with_unresolved_entries": sum(1 for c in self.states.values()
                                                        if c["unresolved"] and not c["nonsmooth"]),
                "fraction": (judged / n) if n else 0.0, "minimum": MIN_STATE_COVERAGE,
                "rule": "a state is judged when EVERY input column at it is smooth and every "
                        "entry of every column is resolved (pass, structural-zero pass or fail); "
                        "a column whose perturbed run of the original terminated (STOP/XIT) "
                        "before writing its records is not judged",
                "per_input_informational": {k: f"{v[0]}/{v[1]}" for k, v in self.per_input.items()}}

    def status(self) -> tuple:
        cov = self.coverage()
        failed = sum(c["failed"] for c in self.states.values())
        if failed:
            return "failed", (f"{failed} resolved entr{'y' if failed == 1 else 'ies'} outside "
                              f"tolerance at {sum(1 for c in self.states.values() if c['failed'])} state(s)")
        if not cov["n_states"]:
            return "not_attempted", "no state was evaluated"
        n_term = cov["n_states_terminated_under_perturbation"]
        if cov["fraction"] < MIN_STATE_COVERAGE:
            why = (f"insufficient coverage: {cov['n_states_judged']}/{cov['n_states']} states judged "
                   f"({cov['n_states_with_nonsmooth_columns']} with nonsmooth columns, "
                   f"{cov['n_states_with_unresolved_entries']} with FD-unresolved entries, "
                   f"{n_term} with columns whose perturbed run terminated; "
                   f"entries {dict(self.entries)})")
            if n_term:
                first = min(self.terminations, key=_increment_of)
                why = (f"{first}: {n_term}/{cov['n_states']} states not judged; " + why)
            return "not_attempted", why
        judged_pass = sum(c["passed"] for c in self.states.values()
                          if c["columns"] and not c["nonsmooth"] and not c["unresolved"])
        compared = sum(c["passed"] + c["zero_passed"] + c["failed"] + c["unresolved"]
                       for c in self.states.values())
        if not compared and self.entries.get("undefined_in_original"):
            return "not_attempted", ("undefined_in_original: every compared output is undefined "
                                     "behaviour of the original on this path")
        if not judged_pass:
            return "not_attempted", ("every judged entry is a structural zero: the derivative was "
                                     "not exercised on this path")
        note = ""
        if n_term:
            note = (f"; {n_term} state(s) not judged: "
                     f"{min(self.terminations, key=_increment_of)}")
        return "verified", (f"{cov['n_states_judged']}/{cov['n_states']} states judged, every "
                            f"resolved entry within its tolerance (largest tau/|D| = "
                            f"{self.max_rel_tolerance:.2e}){note}")

    def as_dict(self) -> dict:
        status, reason = self.status()
        return {"status": status, "reason": reason,
                "max_abs": self.max_abs, "max_rel": self.max_rel,
                "max_error_over_tolerance": self.max_ratio,
                "max_relative_tolerance": self.max_rel_tolerance, "worst": self.worst,
                "tolerance": {"rtol": self.rtol, "atol": "8 eps F_e / h_(3) (round-off scale)",
                              "resolution": fd.RESOLUTION, "rule": TOLERANCE_RULE},
                "ladder_relative": list(self.ladder), "min_plateau_required": fd.MIN_PLATEAU,
                "min_plateau_observed": self.min_plateau,
                "observed_order_median": (statistics.median(self.orders) if self.orders else None),
                "coverage": self.coverage(),
                "n_states": len(self.states), "n_states_judged": self.coverage()["n_states_judged"],
                "columns": dict(self.column_status),
                "n_columns_nonsmooth": sum(c["nonsmooth"] for c in self.states.values()),
                "entries": dict(self.entries),
                "signature_ignored_statev": self.signature_ignored_statev,
                "nonsmooth_examples": self.nonsmooth, "failed_examples": self.failures,
                "unresolved_examples": self.unresolved_examples, "notes": self.notes,
                "terminated_under_perturbation": [
                    {"reason": r, "columns": n} for r, n in
                    sorted(self.terminations.items(), key=lambda kv: _increment_of(kv[0]))[:12]]}


def _increment_of(reason: str) -> int:
    m = re.search(r"at increment (\d+)", reason)
    return int(m.group(1)) if m else 0


def _num(x) -> Optional[float]:
    x = float(x)
    return x if math.isfinite(x) else None


# ---------------------------------------------------------------------------
# main per-path evaluation
# ---------------------------------------------------------------------------

#: The build each feature's value under test comes from.
FEATURE_BUILD = {"primal_stress_state": "store", "ddsdde": "store", "internal_jacobian": "store"}


def feature_build(feature: str) -> str:
    return FEATURE_BUILD.get(feature, "lifted")


def _record(entry: CorpusEntry, feature: str, path, payload: dict, extra: dict) -> dict:
    record = {"schema": SCHEMA, "key": entry.key, "source_id": entry.source_id,
              "family": entry.family, "feature": feature, "build": feature_build(feature),
              "path": path.name, "path_regime": path.regime, "path_kinematics": path.kinematics,
              "path_provenance": getattr(path, "provenance", ""),
              "n_increments": len(path.increments)}
    record.update(DEFINITIONS.get(feature, {}))
    record.update(payload)
    record.update(extra)
    # the three tiers (D-19/D-21): set only off the author-deck tier, so the
    # author-deck records read as before
    for name in ("material_data_origin", "experiment_origin", "council_set"):
        if entry.provenance.get(name):
            record[name] = entry.provenance[name]
    return record


def _simple(status: str, reason: str) -> dict:
    return {"status": status, "reason": reason}


#: A comparison with no defined output to compare (D-12): agrees vacuously;
#: the "informative" test then makes the primal inconclusive.
_NOTHING = {"agrees": True, "max_abs": 0.0, "max_rel": 0.0, "max_error_over_tolerance": 0.0,
            "note": "no defined output to compare"}


def primal_equivalence(a: np.ndarray, b: np.ndarray, *, rtol: float = 1e-10) -> dict:
    """bit-equal / within (primal tolerance, max_rel stated) / differs."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.shape == b.shape and _same(a, b):
        return {"status": "bit-equal", "max_abs": 0.0, "max_rel": 0.0}
    judged = fd.judge_primal(a, b, rtol=rtol)
    return {"status": "within" if judged.get("agrees") else "differs",
            "max_abs": judged.get("max_abs"), "max_rel": judged.get("max_rel"),
            "rule": judged.get("scale_rule"), "rtol": rtol}


def evaluate_path(entry: CorpusEntry, builds: Builds, path, work: Path, *,
                  ladder: Sequence[float] = fd.DEFAULT_LADDER,
                  rtol: float = fd.DEFAULT_RTOL,
                  features: Sequence[str] = FEATURES, pristine=None,
                  call_sdv: bool = False, undefined: Optional[Undefined] = None) -> tuple:
    """Returns (records, history, trips) for one loading path.

    ``undefined`` (from :func:`hidden_state_pregate`) is extended here with the
    outputs that differ between the zero-init and snan-init PERTURBATION runs
    and masks every comparison (D-12).
    """
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    nt, nx = entry.ntens, entry.nstatv
    stress_names = [f"S{i}" for i in range(1, nt + 1)]
    statev_names = [f"SDV{l}" for l in range(1, nx + 1)]
    increments = _increments(entry, path)
    n_inc = len(increments)
    records: list = []
    common = {"evidence_dir": locator(work)}
    if undefined is None:
        undefined = Undefined(nt, nx)

    # --- original: pristine run (also produces the initial STATEV) -----------
    if pristine is None:
        statev0 = entry.initial_statev or [0.0] * nx
        call_sdv = builds.sdvini and not any(statev0)
        pristine, message = _run_real(builds.original, work / "original",
                                      _config(entry, increments, statev0, call_sdv), [], entry,
                                      fresh=True) \
            if builds.original.ok else (None, builds.original.reason)
        if pristine is None:
            reason = f"original routine did not run: {message}"
            status = "blocked" if "not on PATH" in reason else "not_attempted"
            return [_record(entry, f, path, _simple(status, reason), common) for f in features], None, []
    statev0 = list(pristine.initial_statev[:nx]) if nx else []
    config = _config(entry, increments, statev0, False)
    done = sum(1 for i in range(1, n_inc + 1) if i in pristine.base)
    if done < n_inc:
        # The ORIGINAL terminated the program (STOP / CALL XIT) inside this
        # history: nothing to compare against past that point.
        reason = (f"the original routine terminated the run after {done} of {n_inc} "
                  f"increments on this path (STOP/XIT inside the routine)")
        return [_record(entry, f, path, _simple("not_attempted", reason), common)
                for f in features], None, []
    base_stress = _base_arrays(pristine.base, n_inc, "stress")
    base_statev = _base_arrays(pristine.base, n_inc, "statev") if nx else np.zeros((n_inc, 0))
    finite_base = bool(np.all(np.isfinite(base_stress)) and np.all(np.isfinite(base_statev)))

    # --- perturbation plan ---------------------------------------------------
    perts: list = []
    index: dict = {}

    def add(mode, kind, idx, scale, direction=((0, 0, 0),) * 3, key_idx=None):
        for k, h in enumerate(_ladder_steps(scale, ladder)):
            perts.append(dv.Perturbation(mode, kind, idx, h, direction))
            index[(mode, kind, idx if key_idx is None else key_idx, k)] = len(perts)

    # Step scale of an input whose value is 0 (Vera B2/C): the 1e-6 floor
    # put the plateau's 3rd step at 1e-10 and the round-off atol at
    # 8 eps F / 1e-10 = 1.8e-5 F, so a true derivative below that passed as a
    # "structural zero". A zero-valued PROPS (and a STATEV slot that is 0 over
    # the whole history) is instead stepped on its UNIT scale, ZERO_INPUT_SCALE
    # = 1 in the parameter's own units: the ladder spans 1e-2..1e-7 absolute,
    # the smallest resolvable sensitivity is ~1.8e-11 F / (1e-4) ~ 1.8e-9 F per
    # unit input (1e6x finer), and a step that changes the branch (a flag-like
    # input) is excluded by the branch signature as for every other input.
    # fd.judge_column additionally refuses a structural-zero pass unless the
    # FD differences are exactly zero or atol < 1e-3 of the column's scale.
    def _input_scale(value, typical):
        if float(value) == 0.0 and float(typical) == 0.0:
            return ZERO_INPUT_SCALE
        return fd.step_scale(value, typical, floor=1e-6)

    prop_scale = {i: _input_scale(entry.props[i - 1], 0.0) for i in range(1, entry.nprops + 1)}
    statev_scale = {}
    for l in range(1, nx + 1):
        history = np.concatenate([[statev0[l - 1]], base_statev[:, l - 1]])
        statev_scale[l] = _input_scale(0.0, float(np.nanmax(np.abs(history))) if history.size else 0.0)
    dstran_hist = np.array([d for d, *_ in increments], float)
    strain_scale = fd.step_scale(0.0, float(np.max(np.abs(dstran_hist))) if dstran_hist.size else 0.0,
                                 floor=1e-6)
    want_tangent = "ddsdde" in features and builds.store.ok
    want_param = any(f.startswith(("stress_param", "state_param")) for f in features)
    for i in builds.diff_props if want_param else []:
        add("local", "props", i, prop_scale[i])
        add("total", "props", i, prop_scale[i])
    # Incoming-STATEV perturbations always run: they decide which STATEV slots
    # cannot reach the stress (column-relevant branch signature) and feed the
    # isolation probe, besides the state-sensitivity features.
    for l in range(1, nx + 1):
        add("local", "statev", l, statev_scale[l])
    direction_check = {}
    tangent_kind = ""
    if want_tangent:
        tangent_kind = "dfgrd1" if builds.gradient_driven else "dstran"
        for j in range(1, nt + 1):
            if builds.gradient_driven:
                from umat_oti.validation.finite_strain_tangent import strain_direction
                independent = canonical_strain_direction(j, entry.ndi, entry.nshr)
                terms = builds.gradient_terms.get(j, ())
                seeded = np.asarray(strain_direction(terms, 1.0), float) if terms else None
                same = seeded is not None and bool(np.array_equal(seeded, independent))
                direction_check[j] = {"independent": independent.tolist(),
                                      "seed_map": None if seeded is None else seeded.tolist(),
                                      "match": same}
                add("local", "dfgrd1", 0, strain_scale, tuple(map(tuple, independent)), key_idx=j)
            else:
                add("local", "dstran", j, strain_scale)
    perturbed, message = _run_real(builds.original, work / "original_perturbed", config, perts,
                                   entry, fresh=True)
    if perturbed is None:
        return [_record(entry, f, path, _simple("not_attempted",
                                                 f"perturbed original run failed: {message}"), common)
                for f in features], None, []

    # D-12: the snan-init build runs the SAME perturbations; every output
    # that differs anywhere (base, local, total, replays) is undefined.
    trips = []
    # A routine that STOPs / CALLs XIT under a perturbed input ends the
    # perturbation process there (exit 0): the records after that call are
    # absent. Every column that needs one is not judged (FeatureTally.terminated).
    stops = {"original": first_missing_record(perturbed, perts, n_inc)}
    checked_runs = [("original", perturbed)]
    path_block = ""
    for variant in ("original_snan", "original_inf"):
        vbuild = getattr(builds, variant)
        if not (vbuild.ok and builds.original is builds.original_zero):
            continue
        v_run, message = _run_real(vbuild, work / f"{variant}_perturbed",
                                   config, perts, entry, fresh=True)
        if v_run is None:
            trips.append(f"{variant} perturbation run failed on path {path.name}: {message[-300:]}")
            continue
        stops[variant] = first_missing_record(v_run, perts, n_inc)
        checked_runs.append((variant, v_run))
        if stops[variant] != stops["original"] and not path_block:
            # the init value decides WHERE the routine stops: the outputs over
            # the reached history cannot be shown bit-identical (D-12)
            stop = stops[variant] or stops["original"]
            name = variant if stops[variant] else "original"
            path_block = (termination_reason(stop, name) + "; the other init build "
                          f"{'did not stop there' if name == variant else 'stopped elsewhere or not at all'}"
                          ": definedness (D-12) cannot be established on this path")
        for name in ("base", "replay", "total_replay", "zero_total", "local", "total"):
            undefined.collect(getattr(perturbed, name), getattr(v_run, name),
                              (f"base history ({variant})" if name == "base"
                               else f"perturbed run ({name}, {variant})"), path.name)
    gate_notes: list = []
    trips += hidden_state_gate(entry, builds, path, work, pristine, perturbed, config, perts, index,
                               tangent_kind=tangent_kind, ladder=ladder, undefined=undefined,
                               notes=gate_notes)
    undef_vec = undefined.output_vector()
    undef_statev = frozenset(int(l) for l in np.flatnonzero(undefined.statev))
    ignore_for_stress = stress_irrelevant_slots(perturbed, index, base_stress, nx, n_inc, ladder,
                                                undefined.stress) | undef_statev
    S_def, X_def = ~undefined.stress, ~undefined.statev
    finite_base = bool(np.all(np.isfinite(base_stress[:, S_def]))
                       and np.all(np.isfinite(base_statev[:, X_def])))
    gates = {"original_history_finite": finite_base,
             "hidden_state_trips": trips,
             "props_refused_for_integer_use": {str(k): v[:200] for k, v in builds.refused_props.items()},
             "pnewdt_cutback_increments": [i for i in range(1, n_inc + 1)
                                           if pristine.base[i]["pnewdt"] < 1.0],
             "statev_ignored_in_stress_signature": sorted(l + 1 for l in ignore_for_stress),
             "undefined_in_original_on_path": [d["output"] for d in undefined.details],
             "terminated_under_perturbation": {k: v for k, v in stops.items() if v},
             "hidden_state_gate_notes": gate_notes}
    common["gates"] = gates
    gate_reason = ""
    if not finite_base:
        gate_reason = "the original routine's history is not finite on this path"

    history_scale = float(max(np.nanmax(np.abs(base_stress), initial=0.0),
                              np.nanmax(np.abs(base_statev), initial=0.0)))

    def magnitude_of(column: fd.ColumnFD, inc: int, block: slice) -> np.ndarray:
        """Round-off scale per output at this state: incoming, base, perturbed."""
        incoming = np.concatenate([base_stress[inc - 2] if inc > 1 else np.zeros(nt),
                                   np.asarray(statev0 if inc == 1 else base_statev[inc - 2], float)])
        mag = np.maximum(np.asarray(column.magnitude, float), np.abs(np.nan_to_num(incoming)))
        # Each output's OWN magnitude. A block maximum (B1, and the first B2
        # sweep) overstated the round-off of a 2e6 shear entry next to a 3.7e9
        # pressure 1000-fold (Jeff97): u_e and atol_e both blew up. If the own
        # magnitude understates cancellation inside the routine, the extra
        # noise shows up as FD steps that do not agree -> unresolved, never a
        # verdict.
        return mag[block]

    def _defined(vector, inc, delta=False):
        """Undefined outputs replaced by the base value (by 0 for a delta):
        they cannot feed the nonsmooth classification and are excluded from
        judgement anyway."""
        vector = np.asarray(vector, float).copy()
        if undef_vec.any():
            if delta:
                vector[undef_vec] = 0.0
            else:
                base = np.concatenate([REF["base_stress"][inc - 1], REF["base_statev"][inc - 1]])
                vector[undef_vec] = base[undef_vec]
        return vector

    #: the FD reference in use: the double run, or (second pass) the quad run
    REF = {"quad": False, "run": perturbed, "eps": fd.EPS, "base_stress": base_stress,
           "base_statev": base_statev, "stop": stops["original"], "name": "original"}

    def _why_missing(ips, inc, total=False) -> str:
        """'' when every record the column needs was written by every run it
        depends on (the FD reference run and the init-variant runs that prove
        definedness); else the termination reason."""
        if path_block:
            return path_block
        runs = [(REF["name"], REF["run"], REF["stop"], REF["quad"])]
        runs += [(n, r, stops[n], False) for n, r in checked_runs if REF["quad"] or n != "original"]
        for name, r, stop, quad in runs:
            if stop is None:
                continue
            for ip in ips:
                if total:
                    need = [(ip, sg, m) for sg in (1, -1) for m in range(1, inc + 1)]
                    ok = all(k in r.total for k in need) and ip in r.total_replay and (
                        not quad or all(k in r.total_delta for k in need))
                else:
                    need = [(inc, ip, 1), (inc, ip, -1)]
                    # the whole local block of the increment, replay included
                    ok = all(k in r.local for k in need) and inc in r.replay and (
                        not quad or all(k in r.local_delta for k in need))
                if not ok:
                    return termination_reason(stop, name)
        return ""

    def _column(plus_abs, minus_abs, plus_d, minus_d, inc, same, step):
        base = np.concatenate([REF["base_stress"][inc - 1], REF["base_statev"][inc - 1]])
        if not REF["quad"]:
            return fd.classify_and_reference(plus_abs, minus_abs, base, step, same_branch=same,
                                             output_scale=history_scale)
        magnitude = np.abs(base)
        for arr in plus_abs + minus_abs:
            magnitude = np.maximum(magnitude, np.abs(np.nan_to_num(np.asarray(arr, float))))
        return fd.classify_and_reference(plus_d, minus_d, np.zeros_like(base), step,
                                         same_branch=same, output_scale=history_scale,
                                         magnitude=magnitude, eps=fd.EPS_QUAD)

    def local_column(kind, idx, inc, ignore=frozenset()):
        run, bx = REF["run"], REF["base_statev"]
        plus, minus, plus_d, minus_d, same = [], [], [], [], []
        x_in = np.asarray(statev0 if inc == 1 else bx[inc - 2], float)
        why = _why_missing([index[("local", kind, idx, k)] for k in range(len(ladder))], inc)
        if why:
            raise PerturbationTerminated(why)
        for k in range(len(ladder)):
            ip = index[("local", kind, idx, k)]
            sp, xp, pp = run.local[(inc, ip, 1)]
            sm, xm, pm = run.local[(inc, ip, -1)]
            plus.append(_defined(np.concatenate([sp, xp]), inc))
            minus.append(_defined(np.concatenate([sm, xm]), inc))
            if REF["quad"]:
                plus_d.append(_defined(np.concatenate(run.local_delta[(inc, ip, 1)]), inc, True))
                minus_d.append(_defined(np.concatenate(run.local_delta[(inc, ip, -1)]), inc, True))
            dx = np.zeros(nx)
            if kind == "statev":
                dx[idx - 1] = perts[ip - 1].step
            same.append(_consistent(x_in + dx, xp, pp, x_in - dx, xm, pm,
                                    x_in, bx[inc - 1], run.base[inc]["pnewdt"],
                                    frozenset(ignore) | undef_statev))
        step = [perts[index[("local", kind, idx, k)] - 1].step for k in range(len(ladder))]
        return _column(plus, minus, plus_d, minus_d, inc, same, step)

    def total_column(idx, inc, ignore=frozenset()):
        run, bx = REF["run"], REF["base_statev"]
        plus, minus, plus_d, minus_d, same = [], [], [], [], []
        why = _why_missing([index[("total", "props", idx, k)] for k in range(len(ladder))], inc,
                           total=True)
        if why:
            raise PerturbationTerminated(why)
        for k in range(len(ladder)):
            ip = index[("total", "props", idx, k)]
            ok = True
            xp_prev = xm_prev = xb_prev = np.asarray(statev0, float)
            for m in range(1, inc + 1):
                _s, xp_m, pp_m = run.total[(ip, 1, m)]
                _s, xm_m, pm_m = run.total[(ip, -1, m)]
                xb_m = bx[m - 1]
                ok = ok and _consistent(xp_prev, xp_m, pp_m, xm_prev, xm_m, pm_m,
                                        xb_prev, xb_m, run.base[m]["pnewdt"],
                                        frozenset(ignore) | undef_statev)
                xp_prev, xm_prev, xb_prev = xp_m, xm_m, xb_m
            sp, xp, _ = run.total[(ip, 1, inc)]
            sm, xm, _ = run.total[(ip, -1, inc)]
            plus.append(_defined(np.concatenate([sp, xp]), inc))
            minus.append(_defined(np.concatenate([sm, xm]), inc))
            if REF["quad"]:
                plus_d.append(_defined(np.concatenate(run.total_delta[(ip, 1, inc)]), inc, True))
                minus_d.append(_defined(np.concatenate(run.total_delta[(ip, -1, inc)]), inc, True))
            same.append(ok)
        step = [perts[index[("total", "props", idx, k)] - 1].step for k in range(len(ladder))]
        return _column(plus, minus, plus_d, minus_d, inc, same, step)

    history = {"original": [dict(increment=i, stress=pristine.base[i]["stress"].tolist(),
                                 statev=pristine.base[i]["statev"].tolist(),
                                 ddsdde=pristine.base[i]["ddsdde"].tolist(),
                                 sse=float(pristine.base[i]["sse"]), spd=float(pristine.base[i]["spd"]),
                                 scd=float(pristine.base[i]["scd"]),
                                 pnewdt=float(pristine.base[i]["pnewdt"]))
                            for i in range(1, n_inc + 1)],
               "initial_statev": list(statev0)}

    rejudge: dict = {}           # feature -> payload() under the current REF

    # --- store OTI build: primal + DDSDDE -------------------------------------
    store_out = None
    if "primal_stress_state" in features or "ddsdde" in features or want_param:
        if builds.store.ok:
            store_out, message = _run_real(builds.store, work / "store", config, [], entry)
            if store_out is None:
                builds.store.reason = f"store build did not run: {message}"
        if store_out is not None:
            history["store_oti"] = [dict(increment=i, stress=store_out.base[i]["stress"].tolist(),
                                         statev=store_out.base[i]["statev"].tolist(),
                                         ddsdde=store_out.base[i]["ddsdde"].tolist())
                                    for i in range(1, n_inc + 1)]
    primal = None
    if store_out is not None:
        # compared against the ORIGINAL's DEFINED outputs only (D-12)
        s = fd.judge_primal(_base_arrays(store_out.base, n_inc, "stress")[:, S_def],
                            base_stress[:, S_def]) if S_def.any() else dict(_NOTHING)
        x = fd.judge_primal(_base_arrays(store_out.base, n_inc, "statev")[:, X_def],
                            base_statev[:, X_def]) if nx and X_def.any() \
            else dict(_NOTHING)
        informative = finite_base and (float(np.max(np.abs(base_stress[:, S_def]), initial=0.0)) > 0.0
                                       or (nx and float(np.max(np.abs(base_statev[:, X_def] - np.asarray(statev0)[None, X_def]),
                                                               initial=0.0)) > 0.0))
        primal = {"s": s, "x": x, "agrees": bool(s["agrees"] and x["agrees"]),
                  "informative": bool(informative)}
    primal_ok = bool(primal and primal["agrees"] and primal["informative"])
    if "primal_stress_state" in features:
        if store_out is None:
            records.append(_record(entry, "primal_stress_state", path, _simple(
                "not_attempted", f"store OTI build unavailable: {builds.store.reason}"), common))
        else:
            s, x = primal["s"], primal["x"]
            if not finite_base:
                status, reason, inconclusive = ("inconclusive", gate_reason, True)
            elif not primal["informative"]:
                status, reason, inconclusive = (
                    "inconclusive", "the original's history is identically zero (no stress, no "
                    "state change): agreement would carry no information", True)
            elif primal["agrees"]:
                status, reason, inconclusive = ("verified", "stress and state agree at every increment",
                                                False)
            else:
                status, reason, inconclusive = (
                    "failed", f"store OTI build values disagree with the original (stress max_rel "
                    f"{s.get('max_rel')}, statev max_rel {x.get('max_rel')})", False)
            records.append(_record(entry, "primal_stress_state", path, {
                "status": status, "reason": reason, "inconclusive": inconclusive,
                "values_disagree": status == "failed",
                "max_abs": max(s["max_abs"], x["max_abs"]),
                "max_rel": max(s["max_rel"], x["max_rel"]),
                "max_error_over_tolerance": max(s.get("max_error_over_tolerance", 0.0),
                                                x.get("max_error_over_tolerance", 0.0)),
                "stress": s, "statev": x, "n_states": n_inc,
                "tolerance": {"rtol": s.get("rtol"), "atol": s.get("atol"),
                              "rule": s.get("scale_rule")}}, common))

    if "ddsdde" in features:
        mismatched = sorted(j for j, c in direction_check.items() if not c["match"])
        if not builds.store.ok or store_out is None:
            records.append(_record(entry, "ddsdde", path, _simple(
                "not_attempted", f"store OTI build unavailable: {builds.store.reason}"), common))
        elif gate_reason:
            records.append(_record(entry, "ddsdde", path, _simple("not_attempted", gate_reason), common))
        elif mismatched:
            records.append(_record(entry, "ddsdde", path, {
                "status": "failed",
                "reason": (f"store seed map direction differs from the Abaqus strain direction built "
                           f"from the kinematics for column(s) {mismatched}: the store's DDSDDE "
                           f"columns are derivatives in other directions"),
                "direction_check": direction_check}, common))
        elif not primal_ok:
            records.append(_record(entry, "ddsdde", path, _simple(
                "not_attempted", "store build primal does not agree with the original (or is "
                "non-informative): its DDSDDE is evaluated at different incoming states than the "
                "FD reference"), common))
        else:
          #: per (increment, column): which entries the DOUBLE ladder found
          #: exactly zero at every usable step (Vera B7 A3, read by the quad pass)
          double_zero_of: dict = {}

          def ddsdde_payload():
              tally = FeatureTally("ddsdde", ladder, rtol, eps=REF["eps"])
              tally.signature_ignored_statev = sorted(l + 1 for l in ignore_for_stress)
              if builds.gradient_driven:
                  tally.notes.append("gradient-driven source: reference = d sigma/d eps with "
                                     "dF = eps_j . F (eps_j built from the kinematics, engineering "
                                     "shear, checked equal to the store seed map), plus sigma_ij "
                                     "delta_kl (Abaqus nlgeom Jacobian)")
              S = slice(0, nt)
              for inc in range(1, n_inc + 1):
                  oti_matrix = store_out.base[inc]["ddsdde"]
                  columns = {}
                  for j in range(1, nt + 1):
                      try:
                          column = local_column("dfgrd1" if builds.gradient_driven else "dstran",
                                                j, inc, ignore_for_stress)
                      except PerturbationTerminated as stop:
                          columns[j] = stop
                          continue
                      if builds.gradient_driven:
                          shift = np.zeros(nt + nx)
                          if j <= entry.ndi:
                              shift[:nt] = REF["base_stress"][inc - 1]
                          column.estimates = [e + shift for e in column.estimates]
                          column.forward = [e + shift for e in column.forward]
                          column.backward = [e + shift for e in column.backward]
                      columns[j] = column
                  # Round-off model (Vera B7 A1): the largest derivative term
                  # across the BLOCK at this state times the TOTAL kinematic
                  # input, not the increment.
                  block_derivative = _block_derivative(
                      [c for c in columns.values() if not isinstance(c, Exception)], S)
                  kinematic_input = _kinematic_input(increments, inc,
                                                     builds.gradient_driven)
                  for j in range(1, nt + 1):
                      column = columns[j]
                      if isinstance(column, PerturbationTerminated):
                          tally.terminated(inc, f"strain_{j}", str(column))
                          continue
                      sub = _restrict(column, S)
                      exact = _exact_zero(sub)
                      if not REF["quad"]:
                          double_zero_of[(inc, j)] = exact
                      # an entry is compared only when both the ORIGINAL's STRESS(i)
                      # and its own DDSDDE(i,j) are defined (D-12)
                      tally.add(inc, f"strain_{j}", sub, oti_matrix[:, j - 1],
                                [f"DDSDDE({i},{j})" for i in range(1, nt + 1)],
                                magnitude_of(column, inc, S),
                                undefined=undefined.stress | undefined.ddsdde[:, j - 1],
                                kinematic_input=kinematic_input,
                                block_derivative=block_derivative,
                                double_zero=double_zero_of.get((inc, j))
                                if REF["quad"] else None)
              payload = tally.as_dict()
              if direction_check:
                  payload["direction_check"] = {"all_match": True, "columns": len(direction_check)}
              return payload
          rejudge["ddsdde"] = ddsdde_payload
          records.append(_record(entry, "ddsdde", path, ddsdde_payload(), common))

    # --- internal Jacobian ----------------------------------------------------
    if "internal_jacobian" in features:
        from umat_oti.transform.internal_jacobian import discover_local_solves
        solves = discover_local_solves(builds.source_text)
        if not solves:
            records.append(_record(entry, "internal_jacobian", path, _simple(
                "not_attempted", "discover_local_solves found no scalar Newton update; the "
                "detector is pattern-based and misses loops it does not recognise (e.g. the "
                "Lemaitre 'kewton' loop, deqpl=deqpl+rhs/(...)), so absence is NOT established "
                "and not_applicable is not claimed"), common))
        else:
            records.append(_record(entry, "internal_jacobian", path, _simple(
                "not_attempted", f"{len(solves)} local Newton solve(s) found "
                f"({', '.join(s.iterate for s in solves[:4])}); extraction is not part of "
                "the routine-level harness"), common))

    # --- lifted OTI build: parameter and state sensitivities -------------------
    sens = [f for f in features if f.endswith(("_sens_local", "_sens_total"))]
    if not sens or not builds.lifted.ok or gate_reason:
        _quad_pass(records, rejudge, REF, builds, work, config, perts, entry, pristine,
                   undefined, n_inc, common)
    if not sens:
        return records, history, trips
    if not builds.lifted.ok:
        for f in sens:
            records.append(_record(entry, f, path, _simple(
                "unsupported", f"lifted OTI build unavailable ({builds.lifted_reason}): "
                               f"{builds.lifted.reason}"), common))
        return records, history, trips
    if gate_reason:
        for f in sens:
            records.append(_record(entry, f, path, _simple("not_attempted", gate_reason), common))
        return records, history, trips
    lifted_dir = Path(builds.lifted.program).parent
    ndir = builds.lifted_ndir
    dirs = {i: d for d, i in enumerate(builds.diff_props, start=1)}
    want_state = any(f in features for f in ("stress_state_sens_local", "state_state_sens_local"))

    runs = {}
    if want_param and builds.diff_props:
        seeds = [dv.Seed("props", i, d) for i, d in dirs.items()]
        runs["param_local"] = _run_oti(builds.lifted, lifted_dir, config, "local", seeds, entry, ndir)
        runs["param_total"] = _run_oti(builds.lifted, lifted_dir, config, "total", seeds, entry, ndir)
    if want_state and nx:
        seeds = [dv.Seed("statev", l, l) for l in range(1, nx + 1)]
        runs["state_local"] = _run_oti(builds.lifted, lifted_dir, config, "local", seeds, entry, ndir)
    lifted_primal = None
    lifted_vs_store = None
    for name, (out, message) in runs.items():
        if out is None:
            lifted_primal = {"agrees": False, "reason": f"{name} run failed: {message}"}
            break
        s = fd.judge_primal(_base_arrays(out.base, n_inc, "stress")[:, S_def],
                            base_stress[:, S_def]) if S_def.any() else dict(_NOTHING)
        x = fd.judge_primal(_base_arrays(out.base, n_inc, "statev")[:, X_def],
                            base_statev[:, X_def]) if nx and X_def.any() else s
        both = dict(s, agrees=bool(s["agrees"] and x["agrees"]),
                    statev_max_rel=x.get("max_rel"))
        if lifted_primal is None or not both["agrees"]:
            lifted_primal = both
        if lifted_vs_store is None and store_out is not None:
            lifted_vs_store = {
                "stress": primal_equivalence(_base_arrays(out.base, n_inc, "stress"),
                                             _base_arrays(store_out.base, n_inc, "stress")),
                "statev": primal_equivalence(_base_arrays(out.base, n_inc, "statev"),
                                             _base_arrays(store_out.base, n_inc, "statev"))
                if nx else {"status": "bit-equal"}}
            order = ("bit-equal", "within", "differs")
            lifted_vs_store["status"] = max((lifted_vs_store["stress"]["status"],
                                             lifted_vs_store["statev"]["status"]), key=order.index)
    common = dict(common)
    common["gates"] = dict(gates, lifted_primal=lifted_primal)
    common["primal_equivalence_lifted_vs_store"] = lifted_vs_store or {
        "status": "unknown", "reason": "store build unavailable on this path"}

    def _sens_tally(feature, column_fn, wrt_items, block, names, oti_of, out, ignore):
        tally = FeatureTally(feature, ladder, rtol, eps=REF["eps"],
                             euler=True if (block.start == 0 and block.stop == nt) else "bracket")
        tally.signature_ignored_statev = sorted(l + 1 for l in ignore)
        # each input's derivative scale over the path (FD references only),
        # so a state where the response cancelled to ~0 is judged against the
        # derivative's size along the path, not against its own noise
        path_scale: dict = {}
        cached: dict = {}
        for inc in range(1, n_inc + 1):
            for label, idx, d in wrt_items:
                try:
                    column = cached[(inc, idx)] = column_fn(idx, inc, ignore)
                except PerturbationTerminated as stop:
                    cached[(inc, idx)] = stop
                    continue
                block_undefined = undef_vec[block].copy()
                if label.startswith("STATEV_n(") and undefined.statev[idx - 1]:
                    block_undefined[:] = True
                path_scale[label] = max(path_scale.get(label, 0.0), tally.add(
                    inc, label, _restrict(column, block), oti_of(out, inc, d), names,
                    magnitude_of(column, inc, block), undefined=block_undefined, probe=True))
        for label, _idx, _d in wrt_items:
            path_scale.setdefault(label, 0.0)
        for inc in range(1, n_inc + 1):
            for label, idx, d in wrt_items:
                column = cached[(inc, idx)]
                if isinstance(column, PerturbationTerminated):
                    tally.terminated(inc, label, str(column))
                    continue
                block_undefined = undef_vec[block].copy()
                if label.startswith("STATEV_n(") and undefined.statev[idx - 1]:
                    block_undefined[:] = True      # the INPUT itself is undefined
                value_mag = None
                if feature.endswith("_total"):
                    # value under test carried through inc increments
                    hist = np.concatenate([np.abs(REF["base_stress"][:inc]),
                                           np.abs(REF["base_statev"][:inc])], axis=1)
                    value_mag = inc * np.nanmax(np.nan_to_num(hist), axis=0)[block]
                tally.add(inc, label, _restrict(column, block), oti_of(out, inc, d),
                          names, magnitude_of(column, inc, block), undefined=block_undefined,
                          value_magnitude=value_mag, derivative_scale=path_scale[label])
        return tally.as_dict()

    def emit(feature, run_name, column_fn, wrt_items, block, names, oti_of, stress_block):
        if feature not in features:
            return
        out, message = runs.get(run_name, (None, "not run"))
        if not wrt_items:
            if feature.startswith(("stress_param", "state_param")) and entry.nprops \
                    and not builds.diff_props:
                status, why = "unsupported", ("every PROPS index flows into an INTEGER context "
                                              "(non_differentiable_integer_parameter_path)")
            else:
                status, why = "not_applicable", ("no input of this kind (NPROPS=0 or NSTATV=0)"
                                                 if not entry.nprops or not nx else
                                                 "no input of this kind")
            records.append(_record(entry, feature, path, _simple(status, why), common))
            return
        if out is None:
            records.append(_record(entry, feature, path, _simple("failed",
                                                                 f"lifted run failed: {message}"), common))
            return
        ignore = ignore_for_stress if stress_block else frozenset()

        def payload():
            return _sens_tally(feature, column_fn, wrt_items, block, names, oti_of, out, ignore)

        if lifted_primal and lifted_primal.get("agrees"):
            rejudge[feature] = payload
        judged = payload()
        if not lifted_primal or not lifted_primal.get("agrees"):
            records.append(_record(entry, feature, path, {
                "status": "failed",
                "reason": ("the lifted build's primal history disagrees with the original "
                           f"(stress max_rel {lifted_primal and lifted_primal.get('max_rel')}, "
                           f"statev max_rel {lifted_primal and lifted_primal.get('statev_max_rel')}): "
                           "the lifted build computes a different function"),
                "derivative_check_despite_primal_mismatch": {
                    k: judged[k] for k in ("status", "reason", "entries", "coverage")},
                "derivative_check_note": "informational only: in local mode the lifted build's "
                                         "incoming states are its own, not the original's"},
                common))
            return
        records.append(_record(entry, feature, path, judged, common))

    p_items = [(f"PROPS({i})", i, d) for i, d in dirs.items()]
    x_items = [(f"STATEV_n({l})", l, l) for l in range(1, nx + 1)]
    S, X = slice(0, nt), slice(nt, nt + nx)
    emit("stress_param_sens_local", "param_local", lambda i, n, g: local_column("props", i, n, g),
         p_items, S, stress_names, lambda o, n, d: o.dstress[n][:, d - 1], True)
    emit("state_param_sens_local", "param_local", lambda i, n, g: local_column("props", i, n, g),
         p_items if nx else [], X, statev_names, lambda o, n, d: o.dstatev[n][:, d - 1], False)
    emit("stress_param_sens_total", "param_total", total_column,
         p_items, S, stress_names, lambda o, n, d: o.dstress[n][:, d - 1], True)
    emit("state_param_sens_total", "param_total", total_column,
         p_items if nx else [], X, statev_names, lambda o, n, d: o.dstatev[n][:, d - 1], False)
    emit("stress_state_sens_local", "state_local", lambda l, n, g: local_column("statev", l, n, g),
         x_items, S, stress_names, lambda o, n, d: o.dstress[n][:, d - 1], True)
    emit("state_state_sens_local", "state_local", lambda l, n, g: local_column("statev", l, n, g),
         x_items, X, statev_names, lambda o, n, d: o.dstatev[n][:, d - 1], False)
    _quad_pass(records, rejudge, REF, builds, work, config, perts, entry, pristine,
               undefined, n_inc, common)
    for name, (out, _m) in runs.items():
        if out is not None:
            history[f"lifted_{name}_real"] = [dict(increment=i, stress=out.base[i]["stress"].tolist(),
                                                   statev=out.base[i]["statev"].tolist())
                                              for i in range(1, n_inc + 1)]
    return records, history, trips


def _quad_pass(records, rejudge, REF, builds, work, config, perts, entry, pristine,
               undefined, n_inc, common):
    """Re-judge, against the QUAD-precision reference build of the ORIGINAL,
    every feature on this path whose double ladder left entries unresolved.

    The quad run must reproduce the double primal on the defined outputs
    (primal rule, rtol 1e-10); otherwise the quad reference is refused (a
    source whose real kind is a named constant is not promoted). The record
    then carries ``reference_precision: quad`` with the double verdict kept in
    ``double_reference``. Same entrywise rule, with eps = 2^-112.
    """
    need = [r for r in records if r["feature"] in rejudge
            and any(k.startswith("unresolved") and v for k, v in (r.get("entries") or {}).items())]
    if not need:
        return
    note = {"status": "unavailable", "reason": builds.original_quad.reason or "not built"}
    run = None
    qstop = None
    if builds.original_quad.ok:
        run, message = _run_real(builds.original_quad, Path(work) / "original_quad_perturbed", config,
                                 perts, entry, fresh=True)
        if run is None:
            note = {"status": "unavailable", "reason": f"quad run failed: {message[-300:]}"}
        else:
            qstop = first_missing_record(run, perts, n_inc)
            S, X = ~undefined.stress, ~undefined.statev
            qs = _base_arrays(run.base, n_inc, "stress")
            qx = _base_arrays(run.base, n_inc, "statev") if entry.nstatv else np.zeros((n_inc, 0))
            ds = _base_arrays(pristine.base, n_inc, "stress")
            dx = _base_arrays(pristine.base, n_inc, "statev") if entry.nstatv else np.zeros((n_inc, 0))
            # a quad run the original ended under a perturbation: its primal
            # is compared on the increments it reached
            reached = np.array([i in run.base for i in range(1, n_inc + 1)])
            qs, qx, ds, dx = qs[reached], qx[reached], ds[reached], dx[reached]
            s = fd.judge_primal(qs[:, S], ds[:, S]) if S.any() else dict(_NOTHING)
            x = fd.judge_primal(qx[:, X], dx[:, X]) if X.any() else dict(_NOTHING)
            note = {"status": "used" if s["agrees"] and x["agrees"] else "refused",
                    "primal_quad_vs_double": {"stress_max_rel": s.get("max_rel"),
                                              "statev_max_rel": x.get("max_rel"),
                                              "rule": "primal_row_scaled rtol 1e-10"},
                    "build": builds.identity.get("original_quad")}
            if note["status"] == "refused":
                note["reason"] = ("the quad build does not reproduce the double primal: the "
                                  "promotion changed the function (e.g. a kind from a named constant)")
            elif qstop != REF.get("stop"):
                # it would leave a DIFFERENT set of columns unjudged: the
                # verdicts are then not comparable record for record
                note = {"status": "refused", "reason": (
                    (termination_reason(qstop, "quad") if qstop else "the quad run completed")
                    + "; the double reference run "
                    + ("stopped elsewhere" if REF.get("stop") else "completed")
                    + ": the two references do not cover the same columns"),
                    "build": builds.identity.get("original_quad")}
    for record in need:
        record["quad_reference"] = note
    if note["status"] != "used":
        return
    saved = dict(REF)
    REF.update(quad=True, run=run, eps=fd.EPS_QUAD, stop=qstop, name="original_quad",
               base_stress=_base_arrays(run.base, n_inc, "stress"),
               base_statev=_base_arrays(run.base, n_inc, "statev") if entry.nstatv
               else np.zeros((n_inc, 0)))
    try:
        keys = ("status", "reason", "entries", "coverage", "max_error_over_tolerance",
                "min_plateau_observed")

        def unresolved(entries):
            return sum(v for k, v in (entries or {}).items() if k.startswith("unresolved"))

        for record in need:
            double = {k: record.get(k) for k in keys}
            payload = rejudge[record["feature"]]()
            quad_summary = {k: payload.get(k) for k in keys}
            # The quad verdict replaces the double one when it resolves MORE
            # entries; a failure under EITHER reference stands. (Quad can
            # resolve less when the source computes in binary32: its noise
            # exceeds the quad round-off model -> unresolved, never a verdict.)
            use_quad = (payload.get("status") == "failed" and double["status"] != "failed") or (
                double["status"] != "failed"
                and unresolved(payload.get("entries")) < unresolved(double["entries"]))
            if use_quad:
                record.update(payload)
                record["reference_precision"] = "quad"
                record["double_reference"] = double
                record["reference"] = ("central FD of the ORIGINAL compiled in quad precision "
                                       "(REAL*8 -> REAL*16, binary32 and literals unchanged), "
                                       "restored state")
            else:
                record["quad_reference_summary"] = quad_summary
                record["quad_reference"] = dict(note, status="used, not adopted",
                                                why="it resolved no more entries than the double "
                                                    "reference" if double["status"] != "failed"
                                                else "the double reference already failed")
    finally:
        REF.clear()
        REF.update(saved)


def _block_derivative(columns, block: slice) -> float:
    """The largest |central difference| over the block's columns at the
    largest usable step of each (a scale, not a reference)."""
    out = 0.0
    for column in columns:
        for k in column.usable[:1]:
            values = np.abs(np.asarray(column.estimates[k], float)[block])
            values = values[np.isfinite(values)]
            if values.size:
                out = max(out, float(values.max()))
    return out


def _kinematic_input(increments, inc: int, gradient_driven: bool) -> float:
    """The TOTAL kinematic input at increment ``inc``: max |DFGRD1| for a
    gradient-driven source, else max |STRAN + DSTRAN| (the driver starts STRAN
    at 0 and adds each DSTRAN)."""
    if gradient_driven:
        return float(np.max(np.abs(np.asarray(increments[inc - 1][2], float))))
    total = np.sum([np.asarray(d, float) for d, *_ in increments[:inc]], axis=0)
    return float(np.max(np.abs(total))) if np.size(total) else 0.0


def _exact_zero(column: fd.ColumnFD) -> np.ndarray:
    """Per entry: the central difference is exactly zero at every usable step."""
    if not column.usable:
        return np.zeros(np.asarray(column.estimates[0]).size, bool)
    stack = np.stack([np.asarray(column.estimates[k], float).reshape(-1)
                      for k in column.usable])
    return np.all(stack == 0.0, axis=0)


#: What the zero-started STATEV slots hold in the second run of the
#: initial-state proof (D-19a rev 2, R5). Finite, so a routine that reads it
#: computes with it, and not a value a routine plausibly starts at.
INITIAL_STATE_SENTINEL = 7.3205080756887719e3


def initial_state_proof(entry: CorpusEntry, build: dv.Build, work: Path,
                        increments: list, statev0: Optional[Sequence[float]] = None) -> dict:
    """Is starting the zero-started STATEV slots at 0 harmless? (R5)

    The ORIGINAL is driven twice over ``increments``: with ``statev0`` (zeros
    by default) and with :data:`INITIAL_STATE_SENTINEL` in every slot that
    starts at zero. Bit-identical STRESS and DDSDDE at every increment, and
    bit-identical STATEV in every slot the routine writes (a slot that holds
    its starting value throughout in both runs is untouched and not
    compared), prove the zero start harmless: the routine initialises what it
    reads (``IF (KINC.EQ.1) STATEV(1) = ...``). Anything else is
    ``needs_initial_state`` -- the source needs SDVINI or a documented
    initial_statev -- and the first difference is named.
    """
    nx = int(entry.nstatv)
    if nx == 0:
        return {"status": "not_applicable", "reason": "NSTATV = 0"}
    start = np.zeros(nx) if statev0 is None else np.asarray(statev0, float).copy()
    zero = np.flatnonzero(start == 0.0)
    if not zero.size:
        return {"status": "not_applicable",
                "reason": "every STATEV slot starts at a stated value"}
    sentinel = start.copy()
    sentinel[zero] = INITIAL_STATE_SENTINEL
    runs = {}
    for name, x0 in (("zero", start), ("sentinel", sentinel)):
        out, message = _run_real(build, Path(work) / f"initial_state_{name}",
                                 _config(entry, increments, x0, False), [], entry, fresh=True)
        if out is None:
            return {"status": "not_attempted", "reason": f"{name} run failed: {message[-300:]}"}
        runs[name] = out.base
    a, b = runs["zero"], runs["sentinel"]
    record = {"slots_started_at_zero": [int(i) + 1 for i in zero],
              "sentinel": INITIAL_STATE_SENTINEL, "increments": len(increments)}
    if sorted(a) != sorted(b):
        return dict(record, status="needs_initial_state",
                    reason=f"the runs reached different increments ({len(a)} vs {len(b)})")
    xa = np.array([np.asarray(a[i]["statev"], float) for i in sorted(a)])
    xb = np.array([np.asarray(b[i]["statev"], float) for i in sorted(b)])
    untouched = np.all(xa == start, axis=0) & np.all(xb == sentinel, axis=0)
    for inc in sorted(a):
        for field_name in ("stress", "ddsdde"):
            if not _same(a[inc][field_name], b[inc][field_name]):
                return dict(record, status="needs_initial_state", reason=(
                    f"{field_name.upper()} at increment {inc} depends on what the zero-started "
                    f"slots hold: the routine reads state it does not initialise"))
        written = ~untouched
        if not _same(np.asarray(a[inc]["statev"], float)[written],
                     np.asarray(b[inc]["statev"], float)[written]):
            slot = int(np.flatnonzero(written & (np.asarray(a[inc]["statev"], float)
                                                 != np.asarray(b[inc]["statev"], float)))[0]) + 1
            return dict(record, status="needs_initial_state", reason=(
                f"STATEV({slot}) at increment {inc} carries the starting value forward"))
    return dict(record, status="proven", untouched_slots=[int(i) + 1 for i in
                                                          np.flatnonzero(untouched)],
                reason=("STRESS, DDSDDE and every written STATEV are bit-identical with the "
                        "zero-started slots at 0 and at the sentinel"))


def _restrict(column: fd.ColumnFD, block: slice) -> fd.ColumnFD:
    """The column's FD ladder restricted to one output block (same usable steps)."""
    import copy
    sub = copy.copy(column)
    sub.estimates = [np.asarray(e)[block] for e in column.estimates]
    sub.forward = [np.asarray(e)[block] for e in column.forward]
    sub.backward = [np.asarray(e)[block] for e in column.backward]
    return sub


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(name))[:80]


def run_entry(entry: CorpusEntry, work_root: Path, *, paths=None,
              features: Sequence[str] = FEATURES, ladder=fd.DEFAULT_LADDER,
              rtol=fd.DEFAULT_RTOL, supply_utilities: bool = False,
              evaluate_despite_trips: bool = False) -> list:
    """All records of one corpus entry over its loading paths.

    ``evaluate_despite_trips`` (diagnostic, default off): when the hidden-state
    pre-gate trips, still evaluate every path so that each record carries
    ``status_before_hidden_state_gate`` -- what the derivative rules alone
    would have said. The record's ``status`` is ``not_attempted`` either way.
    """
    started = time.time()
    work = Path(work_root) / entry.key
    paths = list(paths or paths_for(entry.as_mapping()))
    builds = build_all(entry, work,
                       want_store=any(f in features for f in ("primal_stress_state", "ddsdde"))
                       or any(f.startswith(("stress_param", "state_param")) for f in features),
                       want_lifted=any(f.endswith(("_local", "_total")) for f in features),
                       supply_utilities=supply_utilities)
    if not builds.original.ok:
        reason = f"original routine did not build: {builds.original.reason}"
        (work / "original_build.log").write_text(builds.original.log)
        records = [_record(entry, f, p, _simple("not_attempted", reason),
                           {"evidence_dir": locator(work)}) for p in paths for f in features]
        return _stamp(records, entry, builds, work, started)
    # D-12: the REFERENCE is the zero-init compile (deterministic where the
    # source reads an uninitialised variable, identical to the default compile
    # everywhere else); the snan-init compile is the check build.
    builds.original_default = builds.original
    if builds.original_zero.ok:
        builds.original = builds.original_zero
        builds.identity["original"] = dict(builds.identity.get("original") or {},
                                           compile_flags=" ".join(FINIT_ZERO),
                                           check_build_flags=" ".join(FINIT_SNAN) + " | "
                                           + " ".join(FINIT_HUGE))

    # D-12.1 (Curie's loading_paths): a path whose clock leaves the author's
    # documented domain gives no verdict and is not run through the gate --
    # undefined behaviour outside the model's domain is not a source defect.
    outside = [p for p in paths if getattr(p, "purpose", "") == OUTSIDE_MODEL_DOMAIN]
    paths = [p for p in paths if getattr(p, "purpose", "") != OUTSIDE_MODEL_DOMAIN]
    records = []
    for path in outside:
        prov = getattr(path, "provenance", {}) or {}
        why = prov.get("outside_model_domain") if isinstance(prov, Mapping) else str(prov)
        records += [_record(entry, f, path, _simple("not_attempted", f"outside_model_domain: {why}"),
                            {"evidence_dir": locator(work), "outside_model_domain": True})
                    for f in features]

    # hidden-state pre-gate on every path before any perturbation is spent
    pre = {}
    source_trips = []
    undefined_by_path = {}
    for path in paths:
        pristine, trips, message, undefined = hidden_state_pregate(entry, builds, path,
                                                                   work / _safe(path.name))
        pre[path.name] = (pristine, message)
        undefined_by_path[path.name] = undefined
        source_trips += trips
    runs_for_checks = {}
    if not source_trips or evaluate_despite_trips:
        for path in paths:
            pristine, message = pre[path.name]
            if pristine is None:
                status = "blocked" if "not on PATH" in message else "not_attempted"
                records += [_record(entry, f, path, _simple(status, f"original routine did not run: "
                                                                    f"{message}"),
                                    {"evidence_dir": locator(work / _safe(path.name))})
                            for f in features]
                continue
            recs, history, trips = evaluate_path(entry, builds, path, work / _safe(path.name),
                                                 ladder=ladder, rtol=rtol, features=features,
                                                 pristine=pristine,
                                                 undefined=undefined_by_path[path.name])
            apply_gate_notes(recs)
            source_trips += [f"[{path.name}] {t}" for t in trips]
            if history is not None:
                (work / _safe(path.name) / "history.json").write_text(json.dumps(history))
                runs_for_checks[path.name] = (path, {"increments": history["original"],
                                                     "statev0": history["initial_statev"]})
            records.extend(recs)
    if source_trips:
        # A trip anywhere makes the whole SOURCE not_attempted (Vera B1/A):
        # restored-state FD of a routine with hidden state is not a reference.
        reason = "hidden state: " + " | ".join(source_trips[:4])
        if len(source_trips) > 4:
            reason += f" | (+{len(source_trips) - 4} more)"
        if any(not r.get("outside_model_domain") for r in records):
            for record in records:
                record["status_before_hidden_state_gate"] = record["status"]
                record["reason_before_hidden_state_gate"] = record.get("reason")
                record["status"] = "not_attempted"
                record["reason"] = reason
        else:
            records = [_record(entry, f, p, _simple("not_attempted", reason),
                               {"evidence_dir": locator(work / _safe(p.name))})
                       for p in paths for f in features] + records
        for record in records:
            record["hidden_state_trips"] = source_trips[:20]
    # D-12.2/3: undefined outputs are a SOURCE defect, disclosed on every record
    details = [d for u in undefined_by_path.values() for d in u.details]
    names = sorted({d["output"] for d in details})
    fully_defined = not any(u.stress_or_ddsdde for u in undefined_by_path.values())
    for record in records:
        record["undefined_outputs"] = names
        record["undefined_outputs_detail"] = details[:60]
        record["undefined_variables_flagged"] = builds.uninitialised_hints if names else []
        record["stress_and_ddsdde_fully_defined"] = fully_defined
    # Curie's admissibility checks on the ORIGINAL routine's histories.
    try:
        from umat_oti.corpus_features import mechanics_checks
        checks = mechanics_checks.run_all(entry.as_mapping(), runs_for_checks)
        (work / "mechanics_checks.json").write_text(json.dumps(
            [c.as_dict() for c in checks], indent=1, default=str))
    except Exception as error:                                       # noqa: BLE001
        (work / "mechanics_checks.json").write_text(json.dumps(
            {"error": f"{type(error).__name__}: {error}"}))
    return _stamp(records, entry, builds, work, started)


def _stamp(records: list, entry: CorpusEntry, builds: Builds, work: Path, started: float) -> list:
    build_info = {"original": builds.original.as_dict(), "store": builds.store.as_dict(),
                  "lifted": builds.lifted.as_dict(), "lifted_ndir": builds.lifted_ndir,
                  "gate_variants": {n: getattr(builds, n).as_dict()
                                    for n in ("original_snan", "original_zero", "original_inf",
                                              "original_bounds")},
                  "uninitialised_hints": builds.uninitialised_hints,
                  "differentiable_props": builds.diff_props,
                  "gradient_driven": builds.gradient_driven, "sdvini": builds.sdvini,
                  "identity": builds.identity,
                  "seconds": round(time.time() - started, 2),
                  "entry": {k: v for k, v in entry.as_mapping().items() if k != "source_text"},
                  "provenance": entry.provenance}
    work.mkdir(parents=True, exist_ok=True)
    (work / "builds.json").write_text(json.dumps(build_info, indent=1, default=str))
    for record in records:
        if record.get("feature") not in ("primal_stress_state", "internal_jacobian", "*"):
            record.setdefault("reference_precision", "double")
        which = record.get("build") or feature_build(record.get("feature", ""))
        identity = dict(builds.identity.get(which) or {"build": which,
                                                        "reason": "build not produced"})
        record["build_identity"] = identity
        record["driver_point"] = dict(entry.driver_point)
        record["transformer_fingerprint"] = identity.get("transformer_fingerprint")
        record["compiled_source_sha256"] = identity.get("compiled_source_sha256")
        record["reference_identity"] = builds.identity.get("original")
        record["build_info"] = {"compiler": "gfortran", "store_ok": builds.store.ok,
                                "workarounds": list(builds.workarounds),
                                "ntens": entry.ntens, "ndi": entry.ndi, "nshr": entry.nshr,
                                "ntens_override": entry.provenance.get("ntens_override"),
                                "lifted_ok": builds.lifted.ok,
                                "driver_point": {"NOEL": entry.driver_point["noel"],
                                                 "NPT": entry.driver_point["npt"],
                                                 "LAYER": 1, "KSPT": 1,
                                                 "COORDS": list(entry.driver_point["coords"])},
                                "builds_json": locator(work / "builds.json")}
    return records
