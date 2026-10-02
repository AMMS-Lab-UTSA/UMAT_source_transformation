"""Fold per-path feature records into manifest feature cells.

The harness writes one record per (UMAT, feature, loading path). The corpus
manifest (``corpus_features/manifest.py``, ``merge_feature_results``) takes one
cell per (source_id, feature). The fold (B2) is strict and reports coverage:

* ``failed``   if any path failed;
* a derivative cell is ``verified`` only when
  - no path failed,
  - at least ``min(MIN_VERIFIED_PATHS, paths evaluated)`` paths are verified
    (a path is evaluated when it reached judgement, i.e. has states), and
  - the judged states over ALL evaluated paths are at least
    ``MIN_STATE_COVERAGE`` of their states;
  otherwise it is ``not_attempted`` with ``insufficient coverage: x/y ...``;
* a primal cell is ``verified`` when no path failed and at least one path
  verified; ``inconclusive`` paths (non-informative history) are counted in
  the reason;
* otherwise the most informative non-verified status of the paths.

Every cell carries ``undefined_outputs`` (outputs of the ORIGINAL that are
undefined behaviour, D-12: never compared), the gfortran-flagged variables and
``stress_and_ddsdde_fully_defined`` (False if any STRESS or DDSDDE entry is
undefined on any evaluated path; D-8 counting requires True). Paths labelled
``outside_model_domain`` give no verdict and are listed.

Every cell names the BUILD whose values were judged (``store`` / ``lifted``),
its transformer fingerprint and the sha256 of the source that was compiled;
lifted-build cells also carry the primal equivalence lifted-vs-store.

``max_error`` is the largest |value - reference| / (entry tolerance) over every
judged entry of every path, so ``tolerance`` is 1.0 and the rule that produced
the entry tolerances is carried in ``tolerance_rule``.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Iterable, Mapping

from umat_oti.corpus_features.harness import (MIN_STATE_COVERAGE, MIN_VERIFIED_PATHS,
                                              apply_gate_notes)

#: Features the manifest knows. Records for other features (the state
#: sensitivities wrt incoming STATEV) stay in the per-path JSONL only.
MANIFEST_FEATURES = ("primal_stress_state", "ddsdde", "internal_jacobian",
                     "stress_param_sens_local", "stress_param_sens_total",
                     "state_param_sens_local", "state_param_sens_total")

_ORDER = ("inconclusive", "unsupported", "blocked", "not_applicable", "not_attempted")


def _coverage(record: Mapping) -> tuple:
    cov = record.get("coverage") or {}
    judged = int(cov.get("n_states_judged") or 0)
    if record.get("status_before_gate_notes"):
        judged = 0        # the path's hidden-state gate was not applied: nothing judged counts
    return int(cov.get("n_states") or 0), judged


def fold(records: Iterable[Mapping], *, evidence: str, producer: str = "gauss/B2") -> list:
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    # a "not applied" hidden-state gate note never folds into a verified cell
    records = apply_gate_notes([dict(r) for r in records])
    for record in records:
        if record.get("feature") in MANIFEST_FEATURES:
            groups.setdefault((record["source_id"], record["feature"]), []).append(record)
    cells = []
    for (source_id, feature), recs in groups.items():
        statuses = [r["status"] for r in recs]
        by = lambda s: [r["path"] for r in recs if r["status"] == s]   # noqa: E731
        first = recs[0]
        cell = {"source_id": source_id, "feature": feature, "producer": producer,
                "evidence": f"{evidence}#key={first.get('key')}&feature={feature}",
                "paths": {r["path"]: r["status"] for r in recs},
                "quantity": first.get("quantity"), "wrt": first.get("wrt"),
                "held_fixed": first.get("held_fixed"),
                "scope": first.get("derivative_kind") if first.get("derivative_kind")
                in ("local", "total") else None,
                "build": {"kind": first.get("build"),
                          "fingerprint": first.get("transformer_fingerprint") or "",
                          "sha256": first.get("compiled_source_sha256"),
                          "transformer": (first.get("build_identity") or {}).get("transformer")}}
        # D-12: undefined behaviour of the ORIGINAL, disclosed on every cell
        cell["undefined_outputs"] = list(first.get("undefined_outputs") or [])
        cell["undefined_variables_flagged"] = list(first.get("undefined_variables_flagged") or [])
        cell["stress_and_ddsdde_fully_defined"] = bool(first.get("stress_and_ddsdde_fully_defined", True))
        if first.get("driver_point"):
            cell["driver_point"] = first["driver_point"]
        outside = [r["path"] for r in recs if r.get("outside_model_domain")]
        if outside:
            cell["paths_outside_model_domain"] = outside
        if first.get("build") == "lifted":
            cell["primal_equivalence_lifted_vs_store"] = sorted(
                {(r.get("primal_equivalence_lifted_vs_store") or {}).get("status", "unknown")
                 for r in recs})
        trips = next((r.get("hidden_state_trips") for r in recs if r.get("hidden_state_trips")), None)
        if trips:
            # the whole SOURCE is not_attempted (hidden-state gate)
            cell["hidden_state_trips"] = trips[:5]
            cell["status"] = "not_attempted"
            cell["reason"] = first.get("reason") or "hidden state"
            cell["reference"] = "original" if feature == "primal_stress_state" else "fd"
            cells.append(cell)
            continue
        if feature == "primal_stress_state":
            cell["reference"] = "original"
            ratios = [r.get("max_error_over_tolerance") or 0.0 for r in recs
                      if r["status"] in ("verified", "failed")]
            cell["max_error"] = max(ratios) if ratios else None
            cell["tolerance"] = 1.0
            cell["tolerance_rule"] = ("|oti - original| / (atol + rtol*scale), scale per increment "
                                      "= max(row max, 1e-3 history max); rtol 1e-10, atol 1e-14")
            cell["tolerance_rule_id"] = "primal_row_scaled/1"
            cell["rtol"] = 1e-10
            inconclusive = [r["path"] for r in recs if r.get("inconclusive")]
            if "failed" in statuses:
                cell["status"], cell["reason"] = "failed", f"values disagree on paths {by('failed')}"
                cell["values_disagree"] = True
            elif "verified" in statuses:
                cell["status"] = "verified"
                cell["reason"] = (f"agree on {len(by('verified'))} path(s); inconclusive "
                                  f"(non-informative) on {len(inconclusive)}")
            elif inconclusive:
                cell["status"] = "inconclusive"
                cell["reason"] = (f"non-informative on {len(inconclusive)} path(s): "
                                  + next(r.get("reason") or "" for r in recs if r.get("inconclusive")))
            else:
                status = next((s for s in _ORDER if s in statuses), statuses[0])
                cell["status"] = status
                cell["reason"] = next((r.get("reason") for r in recs if r["status"] == status), "")
            cells.append(cell)
            continue
        cell["reference"] = "fd"
        quad_paths = [r["path"] for r in recs if r.get("reference_precision") == "quad"]
        cell["reference_precision"] = "quad" if quad_paths else "double"
        if quad_paths:
            cell["reference_precision_quad_paths"] = quad_paths
        cell["fd_steps"] = list(first.get("ladder_relative") or [])
        judged = [r for r in recs if r["status"] in ("verified", "failed")]
        cell["max_error"] = max((r.get("max_error_over_tolerance") or 0.0 for r in judged),
                                default=None)
        cell["tolerance"] = 1.0
        cell["tolerance_rule"] = (first.get("tolerance") or {}).get("rule")
        cell["tolerance_rule_id"] = "entrywise/1"
        cell["rtol"] = (first.get("tolerance") or {}).get("rtol")
        cell["plateau_basis"] = "fd_only"
        cell["min_plateau_required"] = 3
        plateaus = [r.get("min_plateau_observed") for r in judged
                    if isinstance(r.get("min_plateau_observed"), int)]
        cell["min_plateau_observed"] = min(plateaus) if plateaus else None
        evaluated = [r for r in recs if _coverage(r)[0] > 0]
        n_states = sum(_coverage(r)[0] for r in evaluated)
        n_judged = sum(_coverage(r)[1] for r in evaluated)
        verified = by("verified")
        need_paths = min(MIN_VERIFIED_PATHS, len(evaluated)) if evaluated else 1
        cell["coverage"] = {"states_judged": n_judged, "states": n_states,
                            "fraction": (n_judged / n_states) if n_states else 0.0,
                            "paths_verified": len(verified), "paths_evaluated": len(evaluated),
                            "paths_total": len(recs), "min_state_fraction": MIN_STATE_COVERAGE,
                            "min_verified_paths": need_paths,
                            "per_path": {r["path"]: list(_coverage(r)) for r in evaluated}}
        if "failed" in statuses:
            cell["status"] = "failed"
            cell["reason"] = f"failed on paths {by('failed')}: " + next(
                (r.get("reason") or "" for r in recs if r["status"] == "failed"), "")[:300]
        elif verified and len(verified) >= need_paths and n_states and \
                n_judged / n_states >= MIN_STATE_COVERAGE:
            cell["status"] = "verified"
            cell["reason"] = (f"verified on {len(verified)}/{len(evaluated)} evaluated path(s); "
                              f"{n_judged}/{n_states} states judged")
        elif evaluated:
            why = Counter((r.get("reason") or "")[:90] for r in evaluated if r["status"] != "verified")
            if not verified and all("structural zero" in (r.get("reason") or "") for r in evaluated):
                cell["status"] = "not_attempted"
                cell["reason"] = ("derivative not exercised: every judged entry on every path is a "
                                  f"structural zero ({n_judged}/{n_states} states judged)")
            else:
                cell["status"] = "not_attempted"
                cell["reason"] = (f"insufficient coverage: {n_judged}/{n_states} states judged over "
                                  f"{len(evaluated)} evaluated path(s); {len(verified)} path(s) "
                                  f"verified (need {need_paths} and >= {MIN_STATE_COVERAGE:.0%} of "
                                  f"states); path reasons: "
                                  + "; ".join(f"{n}x {r}" for r, n in why.most_common(2)))
        else:
            status = next((s for s in _ORDER if s in statuses), statuses[0])
            cell["status"] = status
            cell["reason"] = next((r.get("reason") for r in recs if r["status"] == status), "")
        cells.append(cell)
    return cells
