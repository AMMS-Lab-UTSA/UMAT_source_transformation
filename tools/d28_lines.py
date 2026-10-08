"""B20 separate-line rules (Vera, D-28, written 2026-10-08 BEFORE any run).

Every rule here produces an ADDITIONAL, labelled verdict that sits NEXT TO the
published verdict of a row and never replaces it. Nothing in this module
writes to a store record, the registry, or any gate. The published figure
(106 of 242) cannot move because of anything computed here; the lines are
reported as "106 of 242 as published; 106 + j of 242 under rule X (names)".
A source counts under rule X only if all OTHER D-4 gates also hold.

The rule texts are copied verbatim into the docstring of the function that
implements each (``rule_1_...`` etc.) from
corpus_campaign/batches/B19/VERA_D28_RULES.md. Constants named there are
module constants and must not be tuned.

This file is deliberately outside ``src/umat_oti`` and outside the
``HARNESS_TOOLS`` list: it reads the existing comparison code and changes none
of it, so neither the transform fingerprint nor the harness fingerprint moves.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from umat_oti.abaqus import compare as _compare            # noqa: E402
from umat_oti.abaqus import precision as _precision        # noqa: E402
from umat_oti.abaqus.replay import (HistoryBuild, parse_history_output,   # noqa: E402
                                    run_history_replay)

#: float32 machine epsilon in the same convention as compare.EPS (2**-52).
EPS32 = 2.0 ** -23
EPS64 = _compare.EPS

#: Rule 1 constants, fixed by Vera: bound = clip(4*U, 2, 64) ulpK.
R1_FACTOR = 4.0
R1_MIN_ULPS = 2.0
R1_CAP_ULPS = 64.0
#: Rule 1 canary: a relative error planted in the transformed stress.
R1_CANARY_RELATIVE = 1e-6

#: Rule 4 constants: F = 8 * eps64 * S ; canary sizes 1e-12*S (fail) / 1e-17*S (pass).
R4_FLOOR_FACTOR = 8.0
R4_CANARY_FAIL = 1e-12
R4_CANARY_PASS = 1e-17

#: Rule 3 mutation factor.
R3_MUTATION = 1.0 + 1e-3

#: Root of the campaign's working tree. Override with D28_WORK; the default is
#: ~/softwarex_work, where the pass runs, the cache and the stores live.
WORK = Path(os.environ.get("D28_WORK") or Path.home() / "softwarex_work")
PASS24 = Path(os.environ.get("D28_PASS24") or WORK / "corpus_run" / "pass24")


# ---------------------------------------------------------------------------
# shared readers
# ---------------------------------------------------------------------------

def load_records(path: Path = PASS24 / "results" / "store_verification.jsonl") -> dict:
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            out[record["key"]] = record
    return out


def work_dir(key: str, run: Path = PASS24) -> Path:
    return Path(run) / "work" / key


def read_calls(path: Path) -> list:
    return parse_history_output(Path(path))


def entries_of(key: str, run: Path = PASS24) -> list:
    history = json.loads((work_dir(key, run) / "original" / "original_history.json").read_text())
    return [r["entry"] for r in history if r.get("entry")]


@contextlib.contextmanager
def epsilon(value: float):
    """Run the UNCHANGED compare code with another unit epsilon.

    compare.py reads the module constant EPS when it forms the stiffness unit,
    the input perturbation and the noise measurement; swapping it here and
    restoring it afterwards re-uses the published code path exactly, so the
    only difference between a published verdict and this one is the epsilon.
    """
    saved = _compare.EPS
    _compare.EPS = value
    try:
        yield
    finally:
        _compare.EPS = saved


def _clip(value: float) -> float:
    return min(R1_CAP_ULPS, max(R1_MIN_ULPS, R1_FACTOR * value))


# ---------------------------------------------------------------------------
# RULE 1: float32-native primal unit
# ---------------------------------------------------------------------------

def rule_1_float32_native_primal_unit(reference_calls: Sequence[dict],
                                      transformed_calls: Sequence[dict],
                                      noise_draws: Sequence[Sequence[dict]], *,
                                      stiffness: float, tolerance: float = 1e-10,
                                      excluded: Optional[dict] = None,
                                      eps: float = EPS32) -> dict:
    """RULE (1) FLOAT32-NATIVE PRIMAL BOUND (Vera, verbatim):

    LEGITIMATE, separate line. For a row whose original declares single-precision
    REAL on the stress path (declaration scan + the original's own build), the
    ulp unit of the primal bound is the epsilon of the narrowest REAL kind
    assigned on that path. Floor U still measured on the original with 1-ulp
    input perturbations in that precision. Bound stays clip(4*U, 2, 64) ulpK with
    the same stiffness cap and Jacobian-matched control. Constants 4, 2, 64 fixed
    now; the Wrinkle ratios 1.14 to 2.68 must not enter the choice. Reference
    stays the author's single-precision program; a promoted REAL*8 variant is
    never a reference (D-28.2). Canary: a 1e-6 relative error planted in the
    transformed stress must still fail; double-precision rows must give
    byte-identical verdicts; passing rows stay passing. Evidence: measured floor
    U for each of the 5 and the passing sibling l2-12; ratio of difference to new
    bound for every single-precision row. Line: "Float32-native primal unit: j rows".

    ``noise_draws`` are replays of the ORIGINAL with every real input moved by
    one ulp of ``eps`` (see :func:`perturbed_entries_native`). Returns the
    measured floor, the bound and the verdict of the routine-level part of the
    primal gate under the native unit.
    """
    with epsilon(eps):
        floor = _compare.measured_noise_ulps(reference_calls, noise_draws, excluded=excluded)
        # measured_noise_ulps applies the published constants (4, 2, 64): the
        # same numbers Vera fixed; recomputed explicitly so the record shows them
        measured = floor.get("measured")
        ulps = _clip(measured) if measured is not None else R1_CAP_ULPS
        comparison = _compare.compare_calls(reference_calls, transformed_calls,
                                            stiffness=stiffness, tolerance=tolerance,
                                            ulps=ulps, excluded=excluded)
    return {"unit_epsilon": eps, "measured_floor_U": measured, "ulps": ulps,
            "agrees": bool(comparison.agrees),
            "worst_stress_over_bound": comparison.worst_stress_over_bound,
            "worst_stress_absolute": comparison.worst_stress_absolute,
            "stress_bound": comparison.stress_bound,
            "worst_state_relative": comparison.worst_state_relative,
            "reason": comparison.reason}


def plant_relative_error(calls: Sequence[dict], relative: float) -> list:
    """Copies of ``calls`` with every STRESS component scaled by 1+relative."""
    out = []
    for call in calls:
        c = dict(call)
        c["STRESS"] = [v * (1.0 + relative) if isinstance(v, float) else v
                       for v in call["STRESS"]]
        out.append(c)
    return out


def perturbed_entries_native(entries: Sequence[dict], seed: int, eps: float = EPS32) -> list:
    """The harness's own perturbation (random sign, fixed seeds), one ulp of eps."""
    with epsilon(eps):
        return _compare.perturb_entries(entries, seed)


def survey_single_precision(original_text: str, transformed_text: str) -> dict:
    """Declaration scan for rule 1: promoted names declared single precision."""
    finding = _precision.survey(original_text, transformed_text)
    return {"widened": list(finding.widened),
            "declarations": [d.line for d in finding.narrow],
            "reason": finding.reason}


def _routine_dirs(key: str, run: Path = PASS24) -> dict:
    base = work_dir(key, run) / "primal_gate" / "routine"
    return {"reference": base / "reference", "transformed": base / "transformed", "base": base}


def stiffness_of(key: str, run: Path = PASS24) -> float:
    history = json.loads((work_dir(key, run) / "original" / "original_history.json").read_text())
    return _compare.stiffness_scale(history)


def run_rule_1_row(key: str, scratch: Path, record: dict, run: Path = PASS24,
                   eps: float = EPS32) -> dict:
    """Rule 1 for one row, offline: the stored replays plus three float32-sized
    perturbation draws of the stored ORIGINAL replay program."""
    dirs = _routine_dirs(key, run)
    ref = read_calls(dirs["reference"] / "otis_history_out.txt")
    trn = read_calls(dirs["transformed"] / "otis_history_out.txt")
    program = dirs["reference"] / "otis_history"
    out: dict[str, Any] = {"key": key, "source": record.get("source")}
    if not ref or len(ref) != len(trn) or not program.exists():
        out["status"] = "not_run"
        out["reason"] = "no complete stored replay pair for this row"
        return out
    entries = entries_of(key, run)
    if len(entries) != len(ref):
        out["status"] = "not_run"
        out["reason"] = "recorded entries do not match the replayed calls"
        return out
    scratch = Path(scratch) / f"r1_{key[:8]}"
    scratch.mkdir(parents=True, exist_ok=True)
    local = scratch / "otis_history"
    shutil.copy2(program, local)
    build = HistoryBuild(label="original", program=local, ok=True)
    draws = []
    for seed in range(1, _compare.NOISE_DRAWS + 1):
        wd = scratch / f"n{seed}"
        wd.mkdir(exist_ok=True)
        for extra in dirs["reference"].glob("*"):      # data files the original opens
            if extra.is_file() and extra.suffix.lower() in (".csv", ".dat", ".txt") \
                    and extra.name not in ("otis_history_out.txt", "otis_history_states.txt"):
                shutil.copy2(extra, wd / extra.name)
        run_ = run_history_replay(build, perturbed_entries_native(entries, seed, eps), wd, 900)
        if run_.ok:
            draws.append(run_.calls)
    stiffness = stiffness_of(key, run)
    excluded = {k: v for k, v in (record.get("undefined_outputs_map") or {}).items()}
    native = rule_1_float32_native_primal_unit(ref, trn, draws, stiffness=stiffness,
                                               excluded=excluded, eps=eps)
    canary = rule_1_float32_native_primal_unit(
        ref, plant_relative_error(trn, R1_CANARY_RELATIVE), draws,
        stiffness=stiffness, excluded=excluded, eps=eps)
    published = (record.get("routine_primal") or {})
    out.update({
        "status": "run", "draws": len(draws), "native": native,
        "canary_1e-6_relative_fails": (not canary["agrees"]),
        "canary_worst_over_bound": canary["worst_stress_over_bound"],
        "published_routine_agrees": published.get("agrees"),
        "published_floor_ulps": (published.get("noise_floor") or {}).get("ulps"),
        "published_worst_over_bound": (published.get("comparison") or {}).get("worst_stress_over_bound"),
        "published_final_gate": (record.get("primal_gate") or {}).get("agrees"),
        "published_decided_by": (record.get("primal_gate") or {}).get("decided_by"),
    })
    return out


def _verify_tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_tool_for_d28",
                                                  ROOT / "tools" / "verify_store_in_abaqus.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_tool_for_d28"] = module
    spec.loader.exec_module(module)
    return module


def rule_1_jacobian_matched(key: str, floor_ulps: float, record: dict, run: Path = PASS24,
                            eps: float = EPS32, plant: float = 0.0) -> Optional[dict]:
    """The same native bound applied to the Jacobian-matched control comparison."""
    base = work_dir(key, run)
    jm_path = base / "jacobian_matched" / "jacobian_matched_history.json"
    tr_path = base / "transformed" / "transformed_history.json"
    if not (jm_path.exists() and tr_path.exists()):
        return None
    jm = json.loads(jm_path.read_text())
    tr = json.loads(tr_path.read_text())
    if plant:
        tr = [dict(r, STRESS=[v * (1.0 + plant) for v in r["STRESS"]]) for r in tr]
    tool = _verify_tool()
    with epsilon(eps):
        out = tool.jacobian_matched_verdict(
            jm, tr, tolerance=1e-10, reference_stiffness=stiffness_of(key, run),
            ulps=floor_ulps)
    comparison = out.get("comparison") or {}
    return {"agrees": out.get("agrees"), "reason": out.get("reason"),
            "worst_stress_over_bound": comparison.get("worst_stress_over_bound"),
            "bound_over_max_sigma": out.get("bound_over_max_sigma")}


def rule_1_row_verdict(key: str, scratch: Path, record: dict, run: Path = PASS24) -> dict:
    row = run_rule_1_row(key, scratch, record, run)
    if row.get("status") != "run":
        return row
    ulps = row["native"]["ulps"]
    jm = rule_1_jacobian_matched(key, ulps, record, run)
    jm_c = rule_1_jacobian_matched(key, ulps, record, run, plant=R1_CANARY_RELATIVE)
    row["jacobian_matched_native"] = jm
    row["jacobian_matched_canary_fails"] = None if jm_c is None else (jm_c.get("agrees") is False)
    routine_ok = row["native"]["agrees"]
    row["native_primal_gate"] = bool(routine_ok and (jm is None or jm.get("agrees")))
    row["canary_fails_as_required"] = bool(
        (not row["native"]["agrees"] or row["canary_1e-6_relative_fails"])
        and (jm_c is None or row["jacobian_matched_canary_fails"]))
    return row


def single_precision_rows(records: dict, run: Path = PASS24) -> list:
    """Rule-1 scope: every row whose original declares a promoted variable single."""
    rows = []
    for key in sorted(records):
        o = work_dir(key, run) / "original" / "original_user.f"
        t = work_dir(key, run) / "transformed" / "transformed_user.f"
        if not (o.exists() and t.exists()):
            continue
        found = survey_single_precision(o.read_text(errors="replace"),
                                        t.read_text(errors="replace"))
        if found["widened"]:
            rows.append((key, found))
    return rows


def undefined_excluded(record: dict) -> dict:
    """The excluded map exactly as the harness passes it: both keys, always."""
    un = (record.get("undefined_in_original") or {}).get("undefined") or {}
    return {name: list(un.get(name) or []) for name in ("STATEV", "STRESS")}


def ab_identity_rule_1(records: dict, run: Path = PASS24) -> dict:
    """A/B: the rule-1 code path at the DOUBLE epsilon, fed the stored floor,
    reproduces the stored routine-level comparison of every row, byte for byte
    (compared as JSON). This is what 'double-precision rows give byte-identical
    verdicts' rests on: for a row outside the rule-1 scope the rule is not
    evaluated at all, and the code it would use is the published code."""
    same, diff, skipped = [], [], []
    for key, rec in sorted(records.items()):
        stored = (rec.get("routine_primal") or {}).get("comparison")
        floor = (rec.get("routine_primal") or {}).get("noise_floor")
        dirs = _routine_dirs(key, run)
        ref_p, trn_p = dirs["reference"] / "otis_history_out.txt", dirs["transformed"] / "otis_history_out.txt"
        if not (stored and floor and ref_p.exists() and trn_p.exists()):
            skipped.append(key)
            continue
        ref, trn = read_calls(ref_p), read_calls(trn_p)
        if len(ref) != len(trn):
            skipped.append(key)
            continue
        with epsilon(EPS64):
            again = _compare.compare_calls(ref, trn, stiffness=stiffness_of(key, run),
                                           tolerance=stored.get("tolerance", 1e-10),
                                           ulps=floor["ulps"],
                                           excluded=undefined_excluded(rec)).as_dict()
        (same if json.dumps(again, sort_keys=True) == json.dumps(stored, sort_keys=True)
         else diff).append(key)
    return {"identical": len(same), "different": diff, "skipped": len(skipped),
            "verified_identical": sum(1 for k in same if records[k].get("stage") == "verified"),
            "verified_total": sum(1 for k in records if records[k].get("stage") == "verified")}


# ---------------------------------------------------------------------------
# RULE 4: absolute floor on state slots
# ---------------------------------------------------------------------------

def state_slot_floor_compare(reference: Sequence[dict], other: Sequence[dict], *,
                             tolerance: float = 1e-10,
                             excluded: Optional[Iterable[int]] = None) -> dict:
    """RULE (4) ABSOLUTE FLOOR ON STATE SLOTS (Vera, verbatim):

    (Lemaitre, NTNU): LEGITIMATE, separate line. A state slot is compared with
    max(1e-10 x own scale, F), F = 8*eps64*S, S = largest |STATEV| over all
    slots and all increments of that path. Stress and DDSDDE untouched. A floor,
    not structural-zero detection. Canary: a real slot error of 1e-12*S must
    still fail; a 1e-17*S difference must pass. Every verified row's verdict
    unchanged; name any row whose state verdict changes. Line: "State-slot
    floor: j rows".

    The published comparison holds slot k to ``tolerance * max|slot k|``
    (compare.RoutineComparison). This holds it to ``max`` of that and the
    floor. ``S`` is taken over both builds' STATEV on every call given. Only
    the state part is evaluated here; the stress part is the published one.
    """
    skip = set(excluded or ())
    nstatv = len(reference[0].get("STATEV") or ()) if reference else 0
    scale = [0.0] * nstatv
    S = 0.0
    for record in list(reference) + list(other):
        for k, v in enumerate((record.get("STATEV") or ())[:nstatv]):
            if math.isfinite(v):
                scale[k] = max(scale[k], abs(v))
                S = max(S, abs(v))
    floor = R4_FLOOR_FACTOR * EPS64 * S
    worst_published = 0.0           # |dx| / own scale  (what compare.py reports)
    worst_floor = 0.0               # |dx| / max(tol*own, F)
    worst_at = ()
    for index, (a, b) in enumerate(zip(reference, other)):
        for k, (x, y) in enumerate(zip(a.get("STATEV") or (), b.get("STATEV") or ()), start=1):
            if k in skip or not (math.isfinite(x) and math.isfinite(y)) or x == y:
                continue
            own = scale[k - 1] if k - 1 < nstatv else 0.0
            if not own:
                continue
            d = abs(x - y)
            worst_published = max(worst_published, d / own)
            ratio = d / max(tolerance * own, floor)
            if ratio > worst_floor:
                worst_floor, worst_at = ratio, (index, k, x, y)
    return {"S": S, "floor_F": floor, "tolerance": tolerance,
            "worst_state_relative_published": worst_published,
            "worst_over_bound_with_floor": worst_floor,
            "state_agrees_published": worst_published <= tolerance,
            "state_agrees_with_floor": worst_floor <= 1.0,
            "worst_at": list(worst_at)}


def rule_4_canaries(reference: Sequence[dict], other: Sequence[dict]) -> dict:
    """Plant a 1e-12*S error (must fail) and a 1e-17*S one (must pass) in the
    state slot with the SMALLEST nonzero own scale, at its largest-magnitude
    call. A 1e-12*S error can only fail on a slot whose own scale is below
    0.01*S (1e-10 x scale > 1e-12*S above that), so the canary is applicable
    only to a row that has such a slot; otherwise it is reported as not
    applicable, never as passed."""
    scale: dict = {}
    for r in list(reference) + list(other):
        for k, v in enumerate(r.get("STATEV") or ()):
            if math.isfinite(v):
                scale[k] = max(scale.get(k, 0.0), abs(v))
    S = max(scale.values(), default=0.0)
    small = [k for k, v in scale.items() if 0.0 < v < 0.01 * S]
    if not S or not small:
        return {"applicable": False, "reason": "no state slot has an own scale below 0.01*S"}
    k = min(small, key=lambda i: scale[i])
    idx = max(range(len(other)), key=lambda i: abs((other[i].get("STATEV") or [0.0] * (k + 1))[k]))
    out = {"applicable": True, "slot": k + 1, "S": S, "slot_scale": scale[k]}
    for name, size, expect in (("fail_1e-12", R4_CANARY_FAIL, False), ("pass_1e-17", R4_CANARY_PASS, True)):
        planted = [dict(r, STATEV=list(r.get("STATEV") or ())) for r in other]
        planted[idx]["STATEV"][k] += size * S
        got = state_slot_floor_compare(reference, planted)["state_agrees_with_floor"]
        out[name] = {"agrees": got, "as_required": got is expect}
    return out


# ---------------------------------------------------------------------------
# offline re-run of the D-4 tangent gate from stored artefacts
# ---------------------------------------------------------------------------

CACHE = Path(os.environ.get("D28_CACHE") or WORK / "discovery_cache")
STORE = Path(os.environ.get("D28_STORE") or WORK / "transform_store")


def _manifest_of(record: dict):
    from umat_oti.abaqus.manifest import VerificationManifest
    m = record["manifest"]
    return VerificationManifest(
        name=m.get("name") or "umat", source=Path(m.get("source") or "umat.f"),
        source_form=m.get("source_form", "fixed"), element_type=m.get("element_type", "C3D8"),
        kinematics=m.get("kinematics", "small strain"), ntens=m["ntens"], ndi=m["ndi"],
        nshr=m["nshr"], nprops=m.get("nprops", 0), nstatv=m.get("nstatv", 1),
        props=tuple(m.get("props") or ()), fd_steps=tuple(m["fd_steps"]),
        near_zero_fraction=m.get("near_zero_fraction", 1e-8))


def tangent_inputs(key: str, record: dict, run: Path = PASS24) -> dict:
    """The histories verify_one hands to verify_tangent: finite common prefix,
    then paired by time; rebuilt from the stored probe files."""
    tool = _verify_tool()
    from umat_oti.abaqus import frames
    wd = work_dir(key, run)
    oh = tool.history_of(wd / "original", "original")
    th = tool.history_of(wd / "transformed", "transformed")
    co, ct, _n, _g = tool.common_finite_prefix(list(oh), list(th),
                                               frames.points_for(record["manifest"]["element_type"]))
    co, ct, _ = _compare.align_by_time(co, ct)
    return {"original_history": co, "transformed_history": ct}


def tangent_rerun(key: str, record: dict, scratch: Path, *, original: Optional[Path] = None,
                  frozen_states: Optional[Sequence[dict]] = None, run: Path = PASS24,
                  timeout: int = 900) -> dict:
    """verify_tangent on stored histories. ``original`` defaults to the author's
    cached file; ``frozen_states`` pins the states (verify_tangent's own hook)."""
    tool = _verify_tool()
    ins = tangent_inputs(key, record, run)
    return tool.verify_tangent(
        _manifest_of(record), Path(original or (CACHE / record["source"])), ins["transformed_history"],
        Path(scratch), form=record.get("source_form", "fixed"), timeout=timeout,
        transformed=work_dir(key, run) / "transformed" / "transformed_user.f",
        original_history=ins["original_history"], frozen_states=frozen_states)


# ---------------------------------------------------------------------------
# RULE 5: revised pre-activation state selection
# ---------------------------------------------------------------------------

R5_FRACTIONS = (0.5, 0.9)


def nearest_ordinals(positions: Sequence[int], activation_ordinal: int) -> list:
    """The two pool positions whose ordinal (position+1) is nearest 0.5 and 0.9
    of the activation ordinal, in that order, distinct; ties go to the smaller
    ordinal."""
    chosen: list = []
    for fraction in R5_FRACTIONS:
        target = fraction * activation_ordinal
        best = min((p for p in positions if p not in chosen), key=lambda p: (abs((p + 1) - target), p))
        chosen.append(best)
    return chosen


def revised_gate_states(original_history: Sequence[dict],
                        transformed_history: Sequence[dict]) -> tuple[list, dict]:
    """RULE (5) (Vera, verbatim):

    Th005 PRE-ACTIVATION STATES: NOT LEGITIMATE as "3 of 4 judged is enough".
    LEGITIMATE only as a deterministic selection rule applied to all 242,
    separate line: the two pre-activation states are the increments nearest 0.5
    and 0.9 of the activation increment (Th005 activation is increment 15;
    selected were 1 and 13: a poor choice, not a missing capability). Coverage
    rule unchanged (two pre-activation states or an honest fail). Canary: a
    planted wrong tangent entry on an elastic state must fail under the new
    selection. Needs a finite-difference re-run for every row. Line: "Revised
    state selection: j rows".

    Implementation: the published chooser runs unchanged and fixes the
    integration point and the post-activation states. Only the two states
    BEFORE activation are replaced, from the same pool the published rule draws
    on (replayable, clear of the transition by one increment), by the pool
    members whose ordinal (position+1 within that point's records) is nearest
    0.5 and 0.9 of the activation ordinal; ties go to the smaller ordinal.
    Rows whose selection has no activation, or whose pool holds fewer than two
    states, keep the published selection (coverage unchanged: two states or an
    honest fail).
    """
    tool = _verify_tool()
    chosen, selection = tool.choose_gate_states(original_history, transformed_history)
    if not chosen:
        return chosen, dict(selection, revised=False, revised_reason="nothing chosen")
    point = (selection["point"]["element"], selection["point"]["point"])
    records = chosen[0][1]
    turn = tool.first_activated(records)
    if turn is None:
        return chosen, dict(selection, revised=False, revised_reason="no activation at this point")
    transformed = {(r.get("step"), r.get("increment")) + point: r for r in transformed_history
                   if r.get("DDSDDE") and r.get("entry")}
    pool = [(pos, rec) for pos, rec in enumerate(records)
            if (rec.get("step"), rec.get("increment")) + point in transformed and pos < turn - 1]
    if len(pool) < 2:
        return chosen, dict(selection, revised=False, revised_reason="fewer than two clear pre-activation states")
    activation = turn + 1
    by_position = dict(pool)
    picked = [(pos, by_position[pos]) for pos in nearest_ordinals([p[0] for p in pool], activation)]
    old_before = [c for c in chosen if c[0] < turn]
    after = [c for c in chosen if c[0] > turn]
    new_before = [(pos, records, rec, transformed.get((rec.get("step"), rec.get("increment")) + point))
                  for pos, rec in sorted(picked)]
    revised = new_before + after
    sel = dict(selection)
    sel["revised"] = True
    sel["states"] = [{"step": c[2].get("step"), "increment": c[2].get("increment"),
                      "element": point[0], "point": point[1], "position": c[0]} for c in revised]
    sel["rule"] = ("revised: pre-activation states nearest 0.5 and 0.9 of the activation "
                   "ordinal; post-activation states as published")
    sel["changed"] = [c[0] for c in old_before] != [c[0] for c in new_before]
    return revised, sel


def _tangent_with_histories(key, record, scratch, ins, frozen, original=None, run=PASS24):
    tool = _verify_tool()
    return tool.verify_tangent(
        _manifest_of(record), Path(original or (CACHE / record["source"])), ins["transformed_history"],
        Path(scratch), form=record.get("source_form", "fixed"), timeout=900,
        transformed=work_dir(key, run) / "transformed" / "transformed_user.f",
        original_history=ins["original_history"], frozen_states=frozen)


def plant_wrong_tangent_entry(transformed_history: Sequence[dict], state: dict,
                              relative: float = 1e-2) -> list:
    """Copy of the transformed history with the largest DDSDDE entry of the
    record at ``state`` (step, increment, element, point) scaled by 1+relative."""
    out = []
    for r in transformed_history:
        if (r.get("step"), r.get("increment"), r.get("element"), r.get("point")) == \
                (state.get("step"), state.get("increment"), state.get("element"), state.get("point")):
            dd = list(r["DDSDDE"])
            k = max(range(len(dd)), key=lambda i: abs(dd[i]))
            dd[k] *= (1.0 + relative)
            r = dict(r, DDSDDE=dd)
        out.append(r)
    return out


def rule_5_row(key: str, record: dict, scratch: Path, run: Path = PASS24) -> dict:
    scratch = Path(scratch)
    ins = tangent_inputs(key, record, run)
    revised, sel = revised_gate_states(ins["original_history"], ins["transformed_history"])
    out = {"key": key, "source": record["source"], "published_stage": record["stage"],
           "published_tangent_verified": record["tangent"].get("verified"),
           "published_states": [s["increment"] for s in record["tangent"]["chosen_states"]],
           "revised_states": [s["increment"] for s in sel["states"]],
           "changed": bool(sel.get("changed"))}
    if not sel.get("changed"):
        return out
    frozen = sel["states"]
    base = _tangent_with_histories(key, record, scratch / "published", ins, None, run=run)
    new = _tangent_with_histories(key, record, scratch / "revised", ins, frozen, run=run)
    out["rerun_published_verified"] = base.get("verified")
    out["revised_verified"] = new.get("verified")
    out["revised_failed"] = new.get("failed")
    out["revised_reason"] = new.get("reason")
    out["revised_states_judged"] = new.get("states_judged")
    out["coverage"] = new.get("coverage")
    # canary: a wrong entry planted at the (first) revised pre-activation state
    planted = plant_wrong_tangent_entry(ins["transformed_history"], frozen[0])
    can = _tangent_with_histories(key, record, scratch / "canary",
                                  dict(ins, transformed_history=planted), frozen, run=run)
    out["canary_wrong_entry_fails"] = bool(can.get("failed") or not can.get("verified"))
    out["canary_reason"] = can.get("reason")
    return out


# ---------------------------------------------------------------------------
# RELABEL: published-text-compiles rule (D-28.4)
# ---------------------------------------------------------------------------

REGISTRY = Path(os.environ.get("D28_REGISTRY") or WORK / "final-umat-b17" / "paper_results" / "corpus" / "corpus_registry.csv")


def relabel_rule_text() -> str:
    """RELABEL of the three non-compiling sources (umat_elastic_official,
    umat_mises_official, nsundar) as incomplete_or_corrupt_source (Vera, verbatim):

    possible as a denominator change under D-28.4. Rule: an original_job_failed
    row whose build log shows an error located in the file itself (not a missing
    external file or an environment fault), reproduced by compiling the published
    text alone with the solver's form and flags, becomes
    incomplete_or_corrupt_source. Evidence: the real Abaqus build log for each of
    the three plus the standalone compile. Apply to all 12 original_job_failed
    rows and any other row whose original does not compile; report moves in both
    directions. Lines: "106 of 242 as published; 106 of 251 revised callee rule;
    106 of 251 - k with the published-text-compiles rule (k named)". The
    source-defect cause is stated, never "fine"."""
    return relabel_rule_text.__doc__


def compile_published_text(source_id: str, form: str, scratch: Path, timeout: int = 600) -> dict:
    """Compile the PUBLISHED text alone with Abaqus's own compile line: the
    harness's own ``diagnose_original`` (companions and includes laid out as it
    does), so a missing external file is separated from an error in the file."""
    tool = _verify_tool()
    path = CACHE / source_id
    if not path.is_file():
        return {"status": "no_cached_file"}
    out = tool.diagnose_original(path, CACHE, Path(scratch), form=form, timeout=timeout,
                                 source_id=source_id)
    c = out.get("compile") or {}
    return {"status": "run", "verdict": out.get("verdict"), "compile_ok": c.get("ok"),
            "defects": c.get("defects"), "missing_dependencies": c.get("missing_dependencies"),
            "reason": (out.get("reason") or "")[:400]}


# ---------------------------------------------------------------------------
# fixed-form Fortran statement reader (enough for the static rules)
# ---------------------------------------------------------------------------

_COMMENT = re.compile(r"^[cC*!]")


def mask_strings(text: str) -> str:
    return re.sub(r"'[^']*'|\"[^\"]*\"", lambda m: "'" + "x" * (len(m.group(0)) - 2) + "'", text)


def fixed_statements(text: str) -> list:
    """[(first_line, last_line, statement)] for fixed-form text: comments and
    blank lines dropped, continuation lines joined, strings masked, upper-cased,
    trailing '!' comments removed, statement labels kept as a leading number."""
    out, cur = [], None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.expandtabs(8)
        if not line.strip() or _COMMENT.match(line) or line.lstrip().startswith("!"):
            continue
        body = line[6:] if len(line) > 6 else ""
        label = line[:5].strip()
        continuation = len(line) > 5 and line[5] not in " 0" and not label
        body = mask_strings(body)
        body = re.sub(r"!.*$", "", body)
        if continuation and cur is not None:
            cur[1] = number
            cur[2] += " " + body.strip()
        else:
            if cur is not None:
                out.append(tuple(cur))
            cur = [number, number, (label + " " if label else "") + body.strip()]
    if cur is not None:
        out.append(tuple(cur))
    return [(a, b, s.upper()) for a, b, s in out]


_UNIT_HEAD = re.compile(r"^(?:\d+\s+)?(?:(?:RECURSIVE|PURE|ELEMENTAL)\s+)*"
                        r"(SUBROUTINE|FUNCTION|(?:REAL\*?\d*|INTEGER|DOUBLE\s+PRECISION|LOGICAL)\s+FUNCTION)"
                        r"\s+(\w+)\s*(?:\(([^)]*)\))?")


def program_units(statements: Sequence[tuple]) -> list:
    """Units with name, dummy argument names, and their statements."""
    units, current = [], None
    for st in statements:
        head = _UNIT_HEAD.match(st[2])
        if head:
            current = {"name": head.group(2), "kind": head.group(1).split()[-1],
                       "dummies": [a.strip() for a in (head.group(3) or "").split(",") if a.strip()],
                       "stmts": [st]}
            units.append(current)
            continue
        if current is not None:
            current["stmts"].append(st)
            if re.match(r"^(?:\d+\s+)?END(?:\s+(?:SUBROUTINE|FUNCTION)\b.*)?$", st[2]):
                current = None
    return units


_REAL_DECL = re.compile(r"^(REAL\*?\d*|DOUBLE\s+PRECISION)\b(.*)$")
_INT_DECL = re.compile(r"^INTEGER\*?\d*\b(.*)$")
_IMPLICIT = re.compile(r"^IMPLICIT\s+(.*)$")


def _names_in_declaration(rest: str) -> set:
    names, depth, cur = set(), 0, ""
    for ch in rest + ",":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            m = re.match(r"\s*(?:::)?\s*([A-Z_]\w*)", cur)
            if m:
                names.add(m.group(1))
            cur = ""
        else:
            cur += ch
    return names


def typing_of(name: str, unit: dict, aba_param: bool = True) -> str:
    """'integer' | 'real' by explicit declaration, IMPLICIT statements, include
    of ABA_PARAM.INC (IMPLICIT REAL*8 (A-H,O-Z)), then Fortran's default."""
    name = name.upper()
    implicit = []
    for _a, _b, s in unit["stmts"]:
        s = re.sub(r"^\d+\s+", "", s)
        m = _REAL_DECL.match(s)
        if m and name in _names_in_declaration(m.group(2)):
            return "real"
        m = _INT_DECL.match(s)
        if m and name in _names_in_declaration(m.group(1)):
            return "integer"
        m = _IMPLICIT.match(s)
        if m:
            implicit.append(m.group(1))
        if aba_param and re.match(r"^INCLUDE\s+'ABA_PARAM\.INC'", s):
            implicit.append("REAL*8 (A-H,O-Z)")
    for spec in implicit:
        kind = "integer" if spec.startswith("INTEGER") else "real" if re.match(r"^(REAL|DOUBLE)", spec) else None
        if kind is None:
            continue
        for lo, hi in re.findall(r"([A-Z])\s*(?:-\s*([A-Z]))?", spec[spec.find("("):]):
            hi = hi or lo
            if lo <= name[0] <= hi:
                return kind
    return "integer" if name[0] in "IJKLMN" else "real"


_REAL_INTRINSICS = {"FLOAT", "REAL", "DBLE", "SNGL", "SQRT", "DSQRT", "EXP", "DEXP", "LOG", "DLOG",
                    "LOG10", "SIN", "COS", "TAN", "ATAN", "ATAN2", "ASIN", "ACOS", "SINH", "COSH",
                    "TANH", "DABS", "SIGN", "DSIGN", "AMAX1", "AMIN1", "DMAX1", "DMIN1", "AINT", "ANINT"}
_INT_INTRINSICS = {"INT", "NINT", "IABS", "IDINT", "IFIX", "LEN", "SIZE", "IDNINT"}
_POLY_INTRINSICS = {"MIN", "MAX", "MOD", "ABS"}
_DECLARATION_HEADS = re.compile(r"^(DIMENSION|INTEGER|REAL|DOUBLE\s+PRECISION|COMMON|PARAMETER|DATA|"
                                r"CHARACTER|LOGICAL|EXTERNAL|SAVE|IMPLICIT|INCLUDE|EQUIVALENCE)\b")
_REL = re.compile(r"\.(?:EQ|NE|LT|LE|GT|GE)\.|==|/=|<=|>=|<|>")


def _split_top(text: str, sep: str = ",") -> list:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _find_top_equals(s: str) -> int:
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "=" and depth == 0:
            if s[i + 1:i + 2] == "=" or s[i - 1:i] in "<>/=":
                continue
            return i
    return -1


def expr_is_integer(expr: str, unit: dict, functions: set) -> bool:
    """True when every operand of ``expr`` is an INTEGER by typing/literal."""
    text = expr
    # replace intrinsic calls by their result kind
    def replace(m):
        name, inner = m.group(1), m.group(2)
        if name in _REAL_INTRINSICS:
            return " 1.0 "
        if name in _INT_INTRINSICS:
            return " 1 "
        if name in _POLY_INTRINSICS:
            return " 1 " if all(expr_is_integer(a, unit, functions) for a in _split_top(inner)) else " 1.0 "
        if name in functions:
            return " 1.0 "
        # array element: typed by the implicit/explicit typing of the array name
        return " 1 " if typing_of(name, unit) == "integer" else " 1.0 "
    pattern = re.compile(r"\b([A-Z_]\w*)\s*\(([^()]*)\)")
    for _ in range(12):
        new = pattern.sub(replace, text)
        if new == text:
            break
        text = new
    text = re.sub(r"\b\d+\.\d*(?:[DE][+-]?\d+)?|\b\.\d+(?:[DE][+-]?\d+)?|\b\d+[DE][+-]?\d+", " 1.0 ", text)
    for name in re.findall(r"\b[A-Z_]\w*\b", text):
        if typing_of(name, unit) != "integer":
            return False
    return " 1.0 " not in text and "1.0" not in text


def _enclosing_args(expr: str, pos: int):
    """(owner, args, index, bare) of the innermost call/array group around pos."""
    depth, i = 0, pos - 1
    while i >= 0:
        ch = expr[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                j = i - 1
                while j >= 0 and expr[j] == " ":
                    j -= 1
                k = j
                while k >= 0 and (expr[k].isalnum() or expr[k] == "_"):
                    k -= 1
                owner = expr[k + 1:j + 1]
                d, e = 0, i
                for e in range(i, len(expr)):
                    if expr[e] == "(":
                        d += 1
                    elif expr[e] == ")":
                        d -= 1
                        if d == 0:
                            break
                args = _split_top(expr[i + 1:e])
                offset = i + 1
                for index, a in enumerate(args):
                    if offset <= pos < offset + len(a):
                        return owner, args, index, a.strip()
                    offset += len(a) + 1
                return owner, args, -1, ""
            depth -= 1
        i -= 1
    return "", [], -1, ""


def _occurrence_contexts(expr: str, name: str, unit: dict, functions: set) -> list:
    """Context of each occurrence of ``name`` in a right-hand-side expression."""
    contexts = []
    for m in re.finditer(rf"\b{re.escape(name)}\b", expr):
        # walk outward through enclosing parentheses
        depth = 0
        owners = []
        i = m.start() - 1
        while i >= 0:
            ch = expr[i]
            if ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    j = i - 1
                    while j >= 0 and expr[j] == " ":
                        j -= 1
                    k = j
                    while k >= 0 and (expr[k].isalnum() or expr[k] == "_"):
                        k -= 1
                    owners.append(expr[k + 1:j + 1])
                else:
                    depth -= 1
            i -= 1
        verdict = None
        for owner in owners:                    # innermost first
            o = owner.upper()
            if not o:
                continue
            if o in _REAL_INTRINSICS:
                verdict = "real_expression"
                break
            if o in _INT_INTRINSICS or o in _POLY_INTRINSICS:
                continue
            if o in functions:
                _own, _args, idx, bare = _enclosing_args(expr, m.start())
                verdict = f"function_argument:{o}:{idx}:{'bare' if bare == name else 'expr'}"
                break
            verdict = "subscript"
            break
        if verdict is None:
            verdict = "arithmetic"
        contexts.append(verdict)
    return contexts


def classify_uses(unit: dict, name: str, functions: set, units_by_name: dict) -> list:
    """Every reference to ``name`` in a program unit, with its context and
    whether Vera's static condition allows it. Contexts allowed: dimension,
    do_limit, subscript, integer_comparison, definition-by-integer-expression,
    integer arithmetic into another INTEGER (closure), actual argument to an
    INTEGER dummy of a unit defined in the file (checked in that unit).
    """
    uses = []
    pat = re.compile(rf"\b{re.escape(name)}\b")
    for first, last, raw in unit["stmts"]:
        s = re.sub(r"^\d+\s+", "", raw)
        if not pat.search(s):
            continue
        rec = lambda ctx, allowed, note="", **extra: uses.append(  # noqa: E731
            dict({"line": first, "context": ctx, "allowed": allowed, "text": raw[:120], "note": note}, **extra))
        if _UNIT_HEAD.match(s):
            continue
        if _DECLARATION_HEADS.match(s):
            if s.startswith("PARAMETER"):
                rec("parameter", False, "enters a PARAMETER")
            elif re.search(rf"\(\s*[^()]*\b{re.escape(name)}\b", s):
                rec("dimension", True)
            elif _REAL_DECL.match(s):
                rec("declared_real", False, "declared REAL")
            else:
                rec("declaration", True)
            continue
        mdo = re.match(r"^DO\s*\d*\s*([A-Z_]\w*)\s*=\s*(.*)$", s)
        if mdo:
            rec("do_limit", expr_is_integer(mdo.group(2), unit, functions),
                "" if expr_is_integer(mdo.group(2), unit, functions) else "non-integer DO bounds")
            continue
        action = s
        mif = re.match(r"^(?:ELSE\s*)?IF\s*\(", s)
        if mif:
            depth, end = 0, None
            for i, ch in enumerate(s):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            cond = s[s.index("(") + 1:end]
            action = s[end + 1:].strip()
            if action in ("", "THEN"):
                action = ""
            if pat.search(cond):
                for part in re.split(r"\.AND\.|\.OR\.|\.NOT\.", cond):
                    if not pat.search(part):
                        continue
                    sides = _REL.split(part)
                    contexts = _occurrence_contexts(part, name, unit, functions)
                    if contexts and all(c == "subscript" for c in contexts):
                        rec("subscript", True)
                    elif len(sides) >= 2:
                        ok = all(expr_is_integer(x, unit, functions) for x in sides)
                        rec("integer_comparison" if ok else "real_expression", ok,
                            "" if ok else "compared with a real operand")
                    else:
                        rec("other", False, "unclassified in a condition")
            if not action or not pat.search(action):
                continue
            s = action
        mcall = re.match(r"^CALL\s+([A-Z_]\w*)\s*(?:\((.*)\))?\s*$", s)
        if mcall:
            callee, args = mcall.group(1), _split_top(mcall.group(2) or "")
            for pos, arg in enumerate(args):
                if not pat.search(arg):
                    continue
                bare = arg.strip() == name
                inner = _occurrence_contexts(arg, name, unit, functions)
                if bare:
                    target = units_by_name.get(callee)
                    if target is None:
                        rec("actual_argument", False, f"callee {callee} is not defined in the file")
                    else:
                        dummy = target["dummies"][pos] if pos < len(target["dummies"]) else None
                        ok = dummy is not None and typing_of(dummy, target) == "integer"
                        rec("actual_argument", ok, f"{callee} dummy {dummy}" + ("" if ok else " is REAL"),
                            callee=callee, dummy=dummy)
                else:
                    for ctx in inner:
                        rec(ctx, ctx in ("subscript", "arithmetic")
                            and (ctx == "subscript" or expr_is_integer(arg, unit, functions)))
            continue
        if re.match(r"^(WRITE|PRINT|READ)\b", s):
            rec("io_list", False, "appears in an I/O list (console output; not in Vera's list of allowed contexts)")
            continue
        eq = _find_top_equals(s)
        if eq < 0:
            rec("other", False, "unclassified statement")
            continue
        lhs, rhs = s[:eq].strip(), s[eq + 1:].strip()
        lname = re.match(r"([A-Z_]\w*)", lhs).group(1) if re.match(r"([A-Z_]\w*)", lhs) else ""
        if pat.search(lhs):
            if lname == name:
                ok = expr_is_integer(rhs, unit, functions) or re.match(r"^NINT\s*\(", rhs) is not None
                rec("definition", ok, "" if ok else "defined from a real expression")
                subs = lhs[len(lname):]
                for ctx in _occurrence_contexts(subs, name, unit, functions) if pat.search(subs) else ():
                    rec(ctx, ctx == "subscript")
            else:
                for ctx in _occurrence_contexts(lhs, name, unit, functions):
                    rec(ctx, ctx == "subscript")
        if pat.search(rhs):
            ltype = typing_of(lname, unit) if lname else "real"
            for ctx in _occurrence_contexts(rhs, name, unit, functions):
                if ctx == "subscript":
                    rec("subscript", True)
                elif ctx == "arithmetic":
                    ok = ltype == "integer" and expr_is_integer(rhs, unit, functions) \
                        and "(" not in lhs.replace(lname, "", 1) or (
                            ltype == "integer" and expr_is_integer(rhs, unit, functions))
                    rec("integer_arithmetic" if ok else "real_expression", ok,
                        f"into {lname}" if ok else f"enters the REAL expression for {lname}")
                elif ctx.startswith("function_argument:"):
                    _f, callee, idx, kind = ctx.split(":")
                    target = units_by_name.get(callee)
                    idx = int(idx)
                    if kind != "bare" or target is None or idx < 0 or idx >= len(target["dummies"]):
                        rec("function_argument", False, f"argument {idx} of {callee} is not a bare integer")
                    else:
                        dummy = target["dummies"][idx]
                        ok = typing_of(dummy, target) == "integer"
                        rec("actual_argument", ok, f"{callee} dummy {dummy}" + ("" if ok else " is REAL"),
                            callee=callee, dummy=dummy)
                else:
                    rec(ctx, False, f"{ctx.replace('_', ' ')} in the right-hand side of {lname}")
    return uses


def static_integer_use(units: Sequence[dict], unit_name: str, name: str, *, depth: int = 4,
                       _seen: Optional[set] = None) -> dict:
    """Vera's static condition for one target ``name`` in ``unit_name``: every
    reference in the unit and, recursively, in every unit it is passed to, with
    the integer-derived variables it is assigned to followed as well.
    Returns the list of uses and the ones that are not allowed."""
    by_name = {u["name"]: u for u in units}
    functions = {u["name"] for u in units if u["kind"] == "FUNCTION"}
    seen = _seen if _seen is not None else set()
    key = (unit_name, name)
    if key in seen or depth < 0:
        return {"uses": [], "violations": []}
    seen.add(key)
    unit = by_name[unit_name]
    uses = classify_uses(unit, name, functions, by_name)
    for u in uses:
        u["unit"] = unit_name
        u["variable"] = name
    out = list(uses)
    # integer variables derived from it (X = 3*NAME): their references count too
    for u in uses:
        m = re.match(r"^(?:\d+\s+)?([A-Z_]\w*)\s*=", u["text"])
        if u["context"] == "integer_arithmetic" and m and m.group(1) != name:
            out += static_integer_use(units, unit_name, m.group(1), depth=depth - 1, _seen=seen)["uses"]
        if u["context"] == "actual_argument" and u["allowed"]:
            if u.get("callee") in by_name and u.get("dummy"):
                out += static_integer_use(units, u["callee"], u["dummy"], depth=depth - 1,
                                          _seen=seen)["uses"]
    violations = [u for u in out if not u["allowed"]]
    return {"uses": out, "violations": violations}


# ---------------------------------------------------------------------------
# RULE 2: benign NINT read-back
# ---------------------------------------------------------------------------

_NINT_PATTERN = re.compile(r"^([A-Z_]\w*)\s*(?:\(([^=]*)\))?\s*=\s*REAL\(\s*NINT\(\s*REAL\(\s*STATEV_OTI\((.*)\)\s*\)\s*\)\s*\)\s*$")


def nint_pattern_targets(truncations: Sequence[dict]) -> dict:
    """Static condition 1: every truncation of the row is EXACTLY
    v = REAL(NINT(REAL(STATEV_OTI(k)))). Returns the targets and the offenders."""
    targets, offenders = [], []
    for t in truncations:
        text = re.sub(r"\s+", "", t.get("text", "")).upper()
        m = _NINT_PATTERN.match(text)
        if m:
            targets.append(m.group(1))
        else:
            offenders.append(t)
    return {"targets": sorted(set(targets)), "offenders": offenders}


def rule_2_static(original_text: str, truncations: Sequence[dict], entry_unit: str = "UMAT") -> dict:
    """RULE (2) BENIGN NINT READ-BACK (Vera, verbatim):

    (RitioL x3, harshaa765 UMATFile): LEGITIMATE (D-28.3), separate line.
    Static (all): target exactly v = REAL(NINT(REAL(STATEV_OTI(k)))); v INTEGER
    by declaration or implicit typing; every reference to v in the program unit
    and in anything it is passed to is a DIMENSION bound, a DO limit, a
    subscript or an integer comparison; never an actual argument to a REAL
    dummy, never in a REAL expression. Dynamic: in the original v takes one
    integer value for every call of the path and is unchanged in every
    central-difference run (all steps, parameters, +/-). The tangent gate must
    pass in full. Canary: a NINT result multiplied into STRESS stays flagged;
    UVC, Tissue x3, NN_UMAT_Vahid stay derivative_truncated under this rule.
    Line: "Benign NINT read-back: j rows".

    Two static verdicts are returned. ``static_literal`` is the rule as
    written: every violation counts. ``static_admitting_output`` additionally
    admits two references that are not in Vera's list but cannot carry a value
    into any computed quantity: a console WRITE of v, and the store of the same
    integer back into STATEV (`STATEV(..)=FLOAT(v)`, the first-call initial
    state). Which of the two is the rule is Vera's to say; the line uses the
    literal one.
    """
    pat = nint_pattern_targets(truncations)
    out: dict[str, Any] = {"targets": pat["targets"], "pattern_offenders": pat["offenders"]}
    if pat["offenders"] or not pat["targets"]:
        out.update(static_literal=False, static_admitting_output=False,
                   reason="a truncation is not the exact NINT read-back pattern")
        return out
    units = program_units(fixed_statements(original_text))
    if not any(u["name"] == entry_unit for u in units):
        out.update(static_literal=False, static_admitting_output=False, reason="entry unit not found")
        return out
    by_name = {u["name"]: u for u in units}
    violations, integer_typed = [], {}
    for name in pat["targets"]:
        integer_typed[name] = typing_of(name, by_name[entry_unit]) == "integer"
        result = static_integer_use(units, entry_unit, name)
        violations += [dict(v, target=name) for v in result["violations"]]
    out["integer_typed"] = integer_typed
    out["violations"] = [{k: v[k] for k in ("target", "unit", "variable", "line", "context", "note", "text")}
                         for v in violations]
    store_back = re.compile(r"^STATEV\s*\(.*\)\s*=\s*(?:FLOAT|REAL|DBLE)\(\s*[A-Z_]\w*\s*(?:\([^()]*\))?\s*\)$")
    admitting = all(v["context"] == "io_list"
                    or (v["context"] == "real_expression" and store_back.match(re.sub(r"^\d+\s+", "", v["text"])))
                    for v in violations)
    out["static_literal"] = bool(all(integer_typed.values()) and not violations)
    out["static_admitting_output"] = bool(all(integer_typed.values()) and admitting)
    return out


D28_TRACE_SUBROUTINE = """
      SUBROUTINE D28TR(NV,IV,IA,NA)
C     B20 rule-2 trace: appends the integer value(s) the UMAT holds to the
C     file named by $D28_TRACE. Reads its arguments, assigns nothing.
      INTEGER NV,IV,NA,IA(*),IOTS
      CHARACTER*400 OTSFN
      CALL GETENV('D28_TRACE',OTSFN)
      OPEN(UNIT=97,FILE=OTSFN,POSITION='APPEND',STATUS='UNKNOWN')
      WRITE(97,'(I0,8(1X,I0))') IV,(IA(IOTS),IOTS=1,NA)
      CLOSE(97)
      RETURN
      END
"""


def instrument_after(text: str, patterns: Sequence[str], call: str) -> tuple:
    """Insert the one-line ``call`` (fixed form) after the END DO that closes
    the loop whose body statement matches a pattern, and append the trace
    subroutine. Returns (text, number of insertion points)."""
    statements = fixed_statements(text)
    lines = text.splitlines()
    inserts = []
    for index, (first, last, s) in enumerate(statements):
        flat = re.sub(r"\s+", "", re.sub(r"^\d+\s+", "", s))
        if any(re.match(p, flat) for p in patterns):
            for later in statements[index + 1:index + 4]:
                if re.match(r"^(?:\d+\s+)?END\s*DO$", later[2]) or re.match(r"^\d+\s+CONTINUE$", later[2]):
                    inserts.append(later[1])
                    break
            else:
                inserts.append(last)
    for line_no in sorted(set(inserts), reverse=True):
        lines[line_no:line_no] = [f"      {call}"]
    return "\n".join(lines) + "\n" + D28_TRACE_SUBROUTINE, len(set(inserts))


_NINT_BODY_PATTERNS = (r"^NSLIP\(I\)=NINT\(STATEV\(NSTATV-4\+I\)\)$",
                       r"^STATEV\(NSTATV-4\+I\)=FLOAT\(NSLIP\(I\)\)$")


def _trace_values(path: Path) -> list:
    if not Path(path).exists():
        return []
    return [tuple(line.split()) for line in Path(path).read_text().splitlines() if line.strip()]


def rule_2_dynamic(key: str, record: dict, scratch: Path, run: Path = PASS24) -> dict:
    """Dynamic conditions for rule 2: v takes ONE integer value over (a) every
    recorded call of the path replayed through the original, and (b) every run
    of the D-4 central-difference sweep (all steps, +/-, quad reference), and
    the tangent gate passes in full. Both use the original with a trace call
    inserted after the loops that read back / store NSLPTL and NSLIP."""
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    from umat_oti.abaqus.replay import build_history_replay
    from umat_oti.abaqus.single_call import ABAQUS_IFORT_FLAGS
    tool = _verify_tool()
    wd = work_dir(key, run)
    call = "CALL D28TR(1,NSLPTL,NSLIP,NSET)"
    out: dict[str, Any] = {"key": key}
    # (a) the recorded path
    probed = wd / "original" / "original_probed.for"
    text, n1 = instrument_after(probed.read_text(errors="replace"), _NINT_BODY_PATTERNS, call)
    (scratch / "replay").mkdir(exist_ok=True)
    src = scratch / "replay" / "original_probed_trace.for"
    src.write_text(text)
    includes = tool._include_dirs(wd / "original", wd / "transformed")
    build = build_history_replay(src, scratch / "replay", label="original_trace",
                                 flags=ABAQUS_IFORT_FLAGS, include_dirs=includes)
    out["insertion_points_replay"] = n1
    if not build.ok:
        out["replay_error"] = build.reason
        return out
    trace = scratch / "trace_replay.txt"
    trace.unlink(missing_ok=True)
    os.environ["D28_TRACE"] = str(trace)
    entries = entries_of(key, run)
    done = run_history_replay(build, entries, scratch / "replay", 900)
    values = _trace_values(trace)
    out["replay_calls"] = len(entries)
    out["replay_ok"] = done.ok
    out["replay_trace_lines"] = len(values)
    out["replay_distinct_values"] = sorted({v for v in values})
    # (b) the central-difference sweeps of the tangent gate
    cached = (CACHE / record["source"]).read_text(errors="replace")
    text2, n2 = instrument_after(cached, _NINT_BODY_PATTERNS, call)
    (scratch / "tangent").mkdir(exist_ok=True)
    inst = scratch / "tangent" / Path(record["source"]).name
    inst.write_text(text2)
    trace2 = scratch / "trace_tangent.txt"
    trace2.unlink(missing_ok=True)
    os.environ["D28_TRACE"] = str(trace2)
    gate = tangent_rerun(key, record, scratch / "tangent_run", original=inst)
    values2 = _trace_values(trace2)
    out["insertion_points_tangent"] = n2
    out["tangent_verified"] = gate.get("verified")
    out["tangent_reason"] = gate.get("reason")
    out["tangent_states_judged"] = gate.get("states_judged")
    out["tangent_trace_lines"] = len(values2)
    out["tangent_distinct_values"] = sorted({v for v in values2})
    both = {v for v in values} | {v for v in values2}
    out["single_integer_value_everywhere"] = bool(len(both) == 1 and values and values2)
    return out


# ---------------------------------------------------------------------------
# RULE 3: truncation reaching only the hand-coded DDSDDE
# ---------------------------------------------------------------------------

_KEYWORDS = {"IF", "THEN", "ELSE", "ENDIF", "DO", "END", "CALL", "WHILE", "AND", "OR", "NOT", "EQ", "NE",
             "LT", "LE", "GT", "GE", "TRUE", "FALSE", "GO", "TO", "GOTO", "CONTINUE", "RETURN", "STOP"}
_INTRINSIC_NAMES = (_REAL_INTRINSICS | _INT_INTRINSICS | _POLY_INTRINSICS
                    | {"MATMUL", "TRANSPOSE", "DOT_PRODUCT", "SUM", "MAXVAL", "MINVAL", "SIZE", "RESHAPE"})


def _ids(text: str) -> set:
    cleaned = re.sub(r"\.(?:AND|OR|NOT|EQ|NE|LT|LE|GT|GE|TRUE|FALSE|EQV|NEQV)\.", " ", text)
    cleaned = re.sub(r"\b\d+\.?\d*(?:[DE][+-]?\d+)?\b", " ", cleaned)
    return {m for m in re.findall(r"[A-Z_]\w*", cleaned) if m not in _KEYWORDS}


def rule_3_static(original_text: str, targets: Iterable[str], sinks: Iterable[str],
                  entry_unit: str = "UMAT") -> dict:
    """RULE (3) TRUNCATION REACHING ONLY THE HAND-CODED DDSDDE (Vera, verbatim):

    (UVC, Tissue x3, NN_UMAT_Vahid): LEGITIMATE only as a separate line, with
    proof of no influence; a different rule from (2) (does not contradict
    D-28.3). Static: dataflow closure of every truncated target (COMMON, SAVE,
    module variables, helper arguments) reaches neither STRESS, nor STATEV
    after that point, nor any variable the replacement DDSDDE region reads.
    Dynamic mutation proof per row: multiply each truncated RHS by 1+1e-3 in the
    original; STRESS and STATEV bitwise unchanged for every call and path while
    the hand-coded DDSDDE changes; name-slicing alone not accepted. Transformed
    DDSDDE must pass the D-4 tangent gate in full. Canary: a REAL() on a
    quantity that reaches STRESS flags; a truncated target feeding a variable
    the replacement reads flags. Line: "Hand-DDSDDE-only truncations: j rows"
    listing mutation results.

    The closure here is a conservative over-approximation: one name space for
    the whole file (so a name reused in two units is one variable), control
    dependence through IF/DO conditions, CALL actuals <-> dummies by position
    (an actual of a callee not in the file is tainted whole if any actual is),
    COMMON members by block position. It is the static half only.
    """
    statements = fixed_statements(original_text)
    units = program_units(statements)
    by_name = {u["name"]: u for u in units}
    tainted = {str(t).upper() for t in targets}
    seeds = set(tainted)
    commons: dict = {}
    for u in units:
        for _a, _b, s in u["stmts"]:
            m = re.match(r"^(?:\d+\s+)?COMMON\s*/\s*(\w+)\s*/\s*(.*)$", s)
            if m:
                commons.setdefault(m.group(1), []).append([n.strip() for n in _split_top(m.group(2)) if n.strip()])
    changed = True
    edges = []                       # (reason, lhs, deps) recorded for the report
    guard = 0
    while changed and guard < 50:
        changed, guard = False, guard + 1
        for u in units:
            control: list = []       # stack of (is_tainted)
            for first, last, raw in u["stmts"]:
                s = re.sub(r"^\d+\s+", "", raw)
                if _UNIT_HEAD.match(s):
                    continue
                m_if = re.match(r"^(?:ELSE\s*)?IF\s*\((.*)\)\s*THEN$", s)
                if m_if:
                    cond = bool(_ids(m_if.group(1)) & tainted)
                    if s.startswith("ELSE"):
                        control.pop() if control else None
                    control.append(cond)
                    continue
                if re.match(r"^ELSE$", s):
                    continue
                if re.match(r"^END\s*IF$", s) or re.match(r"^END\s*DO$", s):
                    if control:
                        control.pop()
                    continue
                m_do = re.match(r"^DO\s*\d*\s*([A-Z_]\w*)\s*=\s*(.*)$", s)
                if m_do:
                    cond = bool(_ids(m_do.group(2)) & tainted)
                    control.append(cond)
                    if cond and m_do.group(1) not in tainted:
                        tainted.add(m_do.group(1)); changed = True
                    continue
                m_dw = re.match(r"^DO\s+WHILE\s*\((.*)\)$", s)
                if m_dw:
                    control.append(bool(_ids(m_dw.group(1)) & tainted))
                    continue
                inherited = any(control)
                action = s
                m_lif = re.match(r"^IF\s*\((.*?)\)\s*(.+)$", s)
                if m_lif and "THEN" not in s.split(")")[-1]:
                    inherited = inherited or bool(_ids(m_lif.group(1)) & tainted)
                    action = m_lif.group(2)
                m_call = re.match(r"^CALL\s+([A-Z_]\w*)\s*(?:\((.*)\))?$", action)
                if m_call:
                    callee, args = m_call.group(1), _split_top(m_call.group(2) or "")
                    tgt = by_name.get(callee)
                    any_tainted = inherited or any(_ids(a) & tainted for a in args)
                    for pos, a in enumerate(args):
                        bare = re.match(r"^\s*([A-Z_]\w*)\s*(?:\(.*\))?\s*$", a)
                        base = bare.group(1) if bare else None
                        if tgt is not None and pos < len(tgt["dummies"]):
                            dummy = tgt["dummies"][pos]
                            if (_ids(a) & tainted or inherited) and dummy not in tainted:
                                tainted.add(dummy); changed = True
                            if dummy in tainted and base and base not in tainted:
                                tainted.add(base); changed = True
                        elif any_tainted and base and base not in tainted and base not in _INTRINSIC_NAMES:
                            tainted.add(base); changed = True
                    continue
                eq = _find_top_equals(action)
                if eq < 0 or _DECLARATION_HEADS.match(action):
                    continue
                lhs, rhs = action[:eq].strip(), action[eq + 1:]
                base = re.match(r"([A-Z_]\w*)", lhs)
                if not base:
                    continue
                base = base.group(1)
                deps = _ids(rhs) | (_ids(lhs[len(base):]) if "(" in lhs else set())
                # function references: actual -> dummy
                for fm in re.finditer(r"\b([A-Z_]\w*)\s*\(", rhs):
                    fn = by_name.get(fm.group(1))
                    if fn is not None and fn["kind"] == "FUNCTION":
                        _o, args, _i, _b = _enclosing_args(rhs, fm.end())
                        for pos, a in enumerate(args):
                            if pos < len(fn["dummies"]) and (_ids(a) & tainted) and fn["dummies"][pos] not in tainted:
                                tainted.add(fn["dummies"][pos]); changed = True
                        if fn["name"] in tainted:
                            deps.add(fn["name"])
                if (deps & tainted or inherited) and base not in tainted:
                    tainted.add(base); changed = True
                    edges.append({"line": first, "unit": u["name"], "lhs": base})
        for block, member_lists in commons.items():
            width = max(len(m) for m in member_lists)
            for pos in range(width):
                names = {m[pos].split("(")[0].strip().upper() for m in member_lists if pos < len(m)}
                if names & tainted and not names <= tainted:
                    tainted |= names; changed = True
    sinks = {str(x).upper() for x in sinks}
    reaches = sorted(sinks & tainted)
    return {"seeds": sorted(seeds), "reached_sinks": reaches, "closure_size": len(tainted),
            "closure_contains_ddsdde": "DDSDDE" in tainted, "reaches_none": not reaches,
            "closure_sample": sorted(tainted)[:60]}


def replacement_region_reads(transformed_text: str) -> set:
    """Names read by the transform's replacement DDSDDE region (the extraction
    block), mapped back to author names: STRESS_OTI -> STRESS; loop indices and
    the OTI helpers dropped."""
    lines = transformed_text.splitlines()
    start = next((i for i, l in enumerate(lines) if "OTIS DDSDDE extraction" in l), None)
    if start is None:
        return set()
    block, depth = [], 0
    for l in lines[start:start + 40]:
        if l.lstrip().startswith(("C", "c", "!")) and block and "OTIS" not in l:
            break
        block.append(l)
        t = l.strip().upper()
        if t.startswith("DO "):
            depth += 1
        elif t.startswith("END DO"):
            depth -= 1
            if depth == 0:
                break
    text = " ".join(re.sub(r"^\s{5}\S", " ", l)[6:] if not l[:1].strip() == "C" else "" for l in block).upper()
    names = _ids(text)
    names = {n[:-4] if n.endswith("_OTI") else n for n in names}
    return {n for n in names if not n.startswith("OTI_") and n not in ("GETIM", "REAL")}


def _physical_code(lines: Sequence[str], first: int, last: int) -> tuple:
    """(label, code) of the statement on physical lines first..last (1-based)."""
    label, parts = "", []
    for n in range(first, last + 1):
        line = lines[n - 1].expandtabs(8)
        if n == first:
            label = line[:5].strip()
        body = line[6:] if len(line) > 6 else ""
        body = re.sub(r"!(?=(?:[^']*'[^']*')*[^']*$).*$", "", body)      # inline comment outside strings
        parts.append(body.rstrip())
    return label, "".join(p.strip() if i else p.strip() for i, p in enumerate(parts))


def mutate_assignments(text: str, targets: Iterable[str], factor: str = "(1.0D0+1.0D-3)") -> tuple:
    """Multiply the right-hand side of every assignment to a ``targets`` name by
    ``factor`` (default 1 + 1e-3). Fixed-form text in, (text, count, lines) out.
    A logical IF keeps its condition; the mutated statement is re-wrapped in
    continuation lines (fixed form tolerates a break inside a token)."""
    targets = {t.upper() for t in targets}
    lines = text.splitlines()
    statements = fixed_statements(text)
    edits = []
    for first, last, s in statements:
        s2 = re.sub(r"^\d+\s+", "", s)
        if _DECLARATION_HEADS.match(s2) or _UNIT_HEAD.match(s2) or re.match(r"^(CALL|DO|WRITE|PRINT|READ)\b", s2):
            continue
        prefix = ""
        m = re.match(r"^IF\s*\(", s2)
        action = s2
        if m and not s2.endswith("THEN"):
            depth, end = 0, None
            for i, ch in enumerate(s2):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            prefix, action = s2[:end + 1], s2[end + 1:].strip()
        eq = _find_top_equals(action)
        if eq < 0:
            continue
        base = re.match(r"([A-Z_]\w*)", action[:eq].strip())
        if not base or base.group(1) not in targets:
            continue
        label, code = _physical_code(lines, first, last)
        # recover the case-preserved code of the action
        code_u = code.upper()
        idx = code_u.find(action[:eq].strip()[:12])
        full = code
        if prefix:
            depth, end = 0, None
            for i, ch in enumerate(full):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            head, act = full[:end + 1] + " ", full[end + 1:].strip()
        else:
            head, act = "", full
        e2 = _find_top_equals(act)
        new = f"{head}{act[:e2].strip()} = ({act[e2 + 1:].strip()})*{factor}"
        edits.append((first, last, label, new))
    for first, last, label, new in sorted(edits, reverse=True):
        pieces = [new[i:i + 62] for i in range(0, len(new), 62)] or [""]
        block = [f"{label:<5} " + pieces[0]] + ["     &" + p for p in pieces[1:]]
        lines[first - 1:last] = block
    return "\n".join(lines) + "\n", len(edits), [e[0] for e in sorted(edits)]


def rule_3_dynamic(key: str, record: dict, scratch: Path, run: Path = PASS24) -> dict:
    """Mutation proof: STRESS and STATEV of the ORIGINAL are bitwise unchanged
    over every recorded call when each truncated right-hand side is multiplied
    by 1+1e-3, while the hand-coded DDSDDE changes."""
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    from umat_oti.abaqus.replay import build_history_replay
    from umat_oti.abaqus.single_call import ABAQUS_IFORT_FLAGS
    tool = _verify_tool()
    wd = work_dir(key, run)
    targets = sorted({t["target"] for t in record["truncation"]["truncations"]})
    probed = wd / "original" / "original_probed.for"
    text, count, where = mutate_assignments(probed.read_text(errors="replace"), targets)
    out: dict[str, Any] = {"key": key, "targets": targets, "mutated_statements": count}
    if not count:
        out["error"] = "no assignment to a truncated target found in the original"
        return out
    (scratch / "mut").mkdir(exist_ok=True)
    src = scratch / "mut" / "original_probed_mutated.for"
    src.write_text(text)
    includes = tool._include_dirs(wd / "original", wd / "transformed")
    build = build_history_replay(src, scratch / "mut", label="original_mutated",
                                 flags=ABAQUS_IFORT_FLAGS, include_dirs=includes)
    if not build.ok:
        out["error"] = f"mutated original did not build: {build.reason}"
        return out
    entries = entries_of(key, run)
    done = run_history_replay(build, entries, scratch / "mut", 900)
    ref = read_calls(_routine_dirs(key, run)["reference"] / "otis_history_out.txt")
    out["calls"] = len(entries)
    out["mutated_replay_ok"] = done.ok
    if not done.ok or len(done.calls) != len(ref):
        out["error"] = f"mutated replay incomplete: {done.reason}"
        return out
    def bits(a, b):
        return all((x == y) or (x != x and y != y) for x, y in zip(a, b))
    stress_same = all(bits(a["STRESS"], b["STRESS"]) for a, b in zip(ref, done.calls))
    state_same = all(bits(a["STATEV"], b["STATEV"]) for a, b in zip(ref, done.calls))
    dd_changed = sum(1 for a, b in zip(ref, done.calls) if not bits(a["DDSDDE"], b["DDSDDE"]))
    out.update(stress_bitwise_unchanged=stress_same, statev_bitwise_unchanged=state_same,
               ddsdde_changed_calls=dd_changed,
               proof=bool(stress_same and state_same and dd_changed > 0))
    return out


def compile_alone(source_id: str, form: str, scratch: Path, timeout: int = 600) -> dict:
    """The rule's reproduction: the published text ALONE (no companion bundle, no
    laid-out includes), Abaqus's compile line and the stated source form."""
    from umat_oti.abaqus.support import compile_one
    path = CACHE / source_id
    if not path.is_file():
        return {"status": "no_cached_file"}
    check = compile_one(path, Path(scratch), form=form, timeout=timeout)
    mine = [d for d in check.defects if str(path.name) in d or source_id in d]
    return {"status": "run", "ok": check.ok,
            "malformed": check.source_is_malformed,
            "defects": list(check.defects)[:6],
            "defects_in_this_file": mine[:6],
            "missing_dependencies": list(check.missing_dependencies)[:4]}


def solver_form(path: Path) -> str:
    """The form Abaqus itself compiles a user subroutine file in: by suffix
    (.f/.for/.f77/.for = fixed; .f90/.F90 = free)."""
    return "free" if path.suffix.lower() in (".f90", ".f95", ".f03", ".f08") else "fixed"


def compile_alone_solver_form(source_id: str, scratch: Path, timeout: int = 600) -> dict:
    return compile_alone(source_id, solver_form(CACHE / source_id), scratch, timeout)


def manifest_full(record: dict):
    """The complete VerificationManifest of a stored record (the deck's source of
    truth), rebuilt from ``record['manifest']``."""
    import dataclasses
    from umat_oti.abaqus.manifest import LoadingSegment, VerificationManifest
    m = dict(record["manifest"])
    names = {f.name for f in dataclasses.fields(VerificationManifest)}
    seg_names = {f.name for f in dataclasses.fields(LoadingSegment)}
    def tup(x):
        return tuple(tup(i) for i in x) if isinstance(x, list) else x
    kwargs = {}
    for key, value in m.items():
        if key not in names:
            continue
        if key == "loading":
            value = tuple(LoadingSegment(**{k: tup(v) for k, v in seg.items() if k in seg_names})
                          for seg in value)
        elif key == "source":
            value = Path(value)
        elif key == "bundle":
            value = tuple(Path(v) for v in value)
        elif key == "origins":
            value = tuple((n, o["origin"], o["provenance"]) for n, o in value.items())
        else:
            value = tup(value)
        kwargs[key] = value
    return VerificationManifest(**kwargs)


def deck_matches(key: str, record: dict, run: Path = PASS24) -> bool:
    """Self-check of manifest_full: it regenerates the stored original deck."""
    from umat_oti.abaqus.deck import generate_deck
    text = generate_deck(manifest_full(record))
    stored = (work_dir(key, run) / "original" / "original.inp").read_text(errors="replace")
    return text.strip() == stored.strip()


def _support_of(key: str, run: Path = PASS24):
    from umat_oti.abaqus.support import SupportBuild
    wd = work_dir(key, run) / "transformed"
    env = (wd / "abaqus_v6.env").read_text()
    objs = re.findall(r"'([^']+\.o)'", env.split("_objects = [", 1)[1].split("]", 1)[0])
    return SupportBuild(objects=tuple(Path(o) for o in objs), include_dir=wd, ok=True,
                        compiler="ifort", transform_dir=wd)


def jacobian_matched_control(key: str, record: dict, scratch: Path, run: Path = PASS24,
                             timeout: int = 1800) -> dict:
    """Run the published primal gate part (b) -- one Abaqus job -- for a row whose
    routine-level part did not agree under the published rule, with the
    published code unchanged. Returns the raw outcome (history verdict under
    the published state comparison) plus the path of the job directory so the
    history can be re-judged under another rule."""
    tool = _verify_tool()
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    ins = tangent_inputs(key, record, run)
    wd = work_dir(key, run)
    floor = (record.get("routine_primal") or {}).get("noise_floor") or {}
    un = undefined_excluded(record)
    out = tool.jacobian_matched_primal(
        manifest_full(record), (CACHE / record["source"]).read_text(errors="replace"),
        Path(json.loads((STORE / key / "entry.json").read_text())["entry_source"]).read_text(errors="replace"),
        ins["transformed_history"], scratch / "jm", form=record.get("source_form", "fixed"),
        timeout=timeout, tolerance=1e-10, support=_support_of(key, run),
        data_roots=[CACHE / Path(record["source"]).parts[0]], undefined=un,
        reference_stiffness=stiffness_of(key, run), ulps=floor.get("ulps"))
    return out


def rule_4_history_verdict(left: Sequence[dict], right: Sequence[dict], *, tolerance: float,
                           stiffness: float, ulps: float, excluded: Optional[dict] = None) -> dict:
    """The stress/non-finite part of ``compare_calls`` unchanged plus the
    rule-4 state comparison, for two histories already paired call for call."""
    ex = excluded or {}
    c = _compare.compare_calls(left, right, stiffness=stiffness, tolerance=tolerance, ulps=ulps,
                               excluded=ex)
    s = state_slot_floor_compare(left, right, tolerance=tolerance, excluded=ex.get("STATEV"))
    stress_ok = c.worst_stress_over_bound <= 1.0 and not c.non_finite_mismatches
    return {"published_agrees": bool(c.agrees), "stress_part_ok": bool(stress_ok),
            "state_floor": s, "rule_4_agrees": bool(stress_ok and s["state_agrees_with_floor"]),
            "worst_stress_over_bound": c.worst_stress_over_bound}


def rule_4_jm_row(key: str, record: dict, scratch: Path, run: Path = PASS24) -> dict:
    tool = _verify_tool()
    out = jacobian_matched_control(key, record, scratch, run)
    row = {"key": key, "source": record["source"], "jm_completed": out.get("completed"),
           "published_jm_agrees": out.get("agrees"), "published_jm_reason": out.get("reason")}
    if not out.get("completed"):
        return row
    ins = tangent_inputs(key, record, run)
    history = tool.history_of(Path(scratch) / "jm", "jacobian_matched")
    left, right, _note = _compare.align_by_time(list(history), list(ins["transformed_history"]))
    row["records_paired"] = len(left)
    row["records_transformed"] = len(ins["transformed_history"])
    floor = (record.get("routine_primal") or {}).get("noise_floor") or {}
    row["rule_4"] = rule_4_history_verdict(left, right, tolerance=1e-10, stiffness=stiffness_of(key, run),
                                           ulps=floor.get("ulps") or _compare.STIFFNESS_ULPS,
                                           excluded=undefined_excluded(record))
    return row


# ---------------------------------------------------------------------------
# RULE 2, AMENDED VARIANT (Vera, written 2026-10-08 AFTER the first run)
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def rule_2_amended_static(original_text: str, truncations: Sequence[dict], entry_unit: str = "UMAT") -> dict:
    """RULE (2) NINT, AMENDED (Vera, verbatim, written 2026-10-08 after the first run):

    a REAL-expression use of v is admitted only as (a) a console WRITE or PRINT,
    or (b) the idempotent store `STATEV(j) = FLOAT(v)`, `REAL(v)` or `DBLE(v)`
    into the slot family v was read from; the dynamic condition is unchanged (v
    takes one value over all calls and all FD runs); any other REAL use fails.
    Canaries: the same store into a DIFFERENT slot that reaches STRESS must
    flag; NINT x STRESS must still flag; UVC, Tissue x3 and NN_UMAT_Vahid must
    stay derivative_truncated under this rule.
    Line: "Benign NINT read-back: 0 rows under the rule as first written; 4
    under the amended rule".

    A separate, labelled variant: ``rule_2_static`` (as first written) is kept.
    The slot family v was read from is the subscript text of the
    STATEV_OTI(k) inside the truncation; a store is idempotent only into the
    same subscript text.
    """
    base = rule_2_static(original_text, truncations, entry_unit)
    out = {k: base[k] for k in ("targets", "pattern_offenders", "integer_typed") if k in base}
    out["variant"] = "amended"
    if base.get("pattern_offenders") or not base.get("targets") or "violations" not in base:
        out["static_amended"] = False
        out["reason"] = base.get("reason", "not the exact NINT read-back pattern")
        return out
    read_slot = {}
    for t in truncations:
        m = _NINT_PATTERN.match(_norm(t.get("text", "")))
        if m:
            read_slot[m.group(1)] = _norm(m.group(3))
    remaining = []
    for v in base["violations"]:
        text = _norm(re.sub(r"^\d+\s+", "", v["text"]))
        if v["context"] == "io_list":
            continue
        m = re.match(r"^STATEV\((.*)\)=(?:FLOAT|REAL|DBLE)\(([A-Z_]\w*)(?:\(.*\))?\)$", text)
        if v["context"] == "real_expression" and m and read_slot.get(m.group(2)) == _norm(m.group(1)):
            continue
        remaining.append(v)
    out["violations_after_amendment"] = remaining
    out["static_amended"] = bool(all(base["integer_typed"].values()) and not remaining)
    return out
