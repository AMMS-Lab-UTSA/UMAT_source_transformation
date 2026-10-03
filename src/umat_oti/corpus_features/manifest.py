"""A machine-readable manifest for every candidate in the UMAT corpus.

One row per acquired source (the 391 of ``corpus_registry.json``) plus one row
per file the discovery inventory lists as a candidate that was never acquired.
Each row carries:

* provenance -- repository, URL, commit, path, SHA-256 *recomputed from the
  acquisition cache*, on-disk bytes, licence and a redistribution decision;
* the model -- reviewed material family, entry point, the files it needs, the
  routines it calls that its own closure does not define, modules, compiler
  requirements;
* the interface -- which NTENS/element classes it supports (``measured`` from
  an Abaqus run, or ``inferred`` from the source or the author's deck), strain
  formulation, PROPS/NSTATV with provenance, state initialisation;
* a status for every pipeline stage and every feature column, each with a
  concrete reason and an evidence locator.

Statuses (the campaign's set, plus two that only evidence can produce)::

    verified | failed | blocked | unsupported | not_applicable | not_attempted
    | conflict | inconclusive

``blocked`` is external (missing data or dependency), ``unsupported`` is a
named limitation of this project, and nothing that was skipped, transformed,
compiled or executed is ``verified`` unless the stage's own evidence says so.
``conflict`` is a feature cell for which independent evidence says both
``verified`` and ``failed`` (both are listed; neither is counted);
``inconclusive`` is evidence that neither establishes nor refutes the claim
(e.g. agreement on a run that was not mechanically informative, or a
derivative verified on a build whose primal does not agree).

Later batches merge their results into the feature cells with
:func:`merge_feature_results`; every merged ``verified`` must carry an evidence
locator that resolves to a file, an independent reference, a registered
entrywise tolerance rule it meets (``max_error`` is the largest error/tolerance
ratio, ``tolerance`` is 1), an FD-only plateau of at least three steps when the
reference is finite differences, and -- for derivative features -- the build
it was measured on (``store`` / ``lifted`` / ``provider``) with its
fingerprint or sha256. Lifted and provider builds are kept in a separate block
(``features_other_builds``) and never pooled with the Abaqus-pipeline counts.

The pass's Abaqus tangent gate is carried per row as ``ddsdde_legacy_gate``,
with a derived ``tangent_verdict`` (verified / failed / unresolved: ``failed``
only where the gate measured a disagreement). Before G10 it used the legacy
plateau rule that decision D-4 rejects; from G10 it is the D-4 entrywise gate.
Either way it does not make the ``ddsdde`` cell verified: that cell is decided
by the merged routine-level evidence.

Evidence locators are ``<root>:<relative path>[#selector]``; the roots are
listed once in the manifest header (``roots``) so that no row depends on where
the workspace sits on a particular machine.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "BUILDS",
    "CONSTANT_CONFIDENCES",
    "DEFAULT_ROOTS",
    "EXPERIMENT_ORIGINS",
    "FAMILY_CLASSIFICATION",
    "REPORTING_FAMILIES",
    "denominators_note",
    "merge_d18",
    "origins_of",
    "tangent_verdict",
    "TANGENT_VERDICTS",
    "primal_gate_verdict",
    "reported_family",
    "FEATURES",
    "REFERENCE_TYPES",
    "SCHEMA_ID",
    "STAGES",
    "STATUSES",
    "TOLERANCE_RULES",
    "MATERIAL_DATA_ORIGINS",
    "ManifestInputs",
    "REFUSAL_KINDS",
    "TIERS",
    "build_manifest",
    "flat_rows",
    "manifest_schema",
    "merge_feature_results",
    "ra_records_to_cells",
    "redistribution_policy",
    "resolve_locator",
    "summarise",
    "to_locator",
    "validate_cell",
    "write_outputs",
]

SCHEMA_ID = "umat-oti/corpus-manifest/1"

STATUSES: tuple[str, ...] = (
    "verified", "failed", "blocked", "unsupported", "not_applicable",
    "not_attempted", "conflict", "inconclusive", "undefined_in_original",
)

#: Statuses that decide a claim one way or the other.
DECISIVE: tuple[str, ...] = ("verified", "failed")

#: Builds a derivative cell can name. ``store`` is the transform-store OTI
#: source the Abaqus pipeline compiles; ``lifted`` (the parameter-sensitivity
#: lifter) and ``provider`` (umat_oti.provider, used by the Residual Assembler)
#: are different builds of the same source and are counted apart.
BUILDS: tuple[str, ...] = ("store", "lifted", "provider")
OTHER_BUILDS: tuple[str, ...] = ("lifted", "provider")

#: Minimum FD-only plateau (decision D-4, B1 review shared rule).
MIN_PLATEAU = 3

#: The one tolerance semantics a merged cell may use: ``tolerance`` is 1.0 and
#: ``max_error`` is the largest ratio |value - reference| / tau_e over every
#: judged entry, tau_e given by the registered rule named in
#: ``tolerance_rule_id``; ``rtol`` (the rule's relative coefficient) is
#: recorded and bounded by the rule's ``rtol_max``. Rules marked
#: ``accepted: False`` are recognised so the refusal can name them.
TOLERANCE_RULES: dict[str, dict[str, Any]] = {
    "entrywise/1": {
        "accepted": True, "applies_to": ("derivative", "primal"), "rtol_max": 1e-4,
        "definition": "per entry e: tau_e = atol + rtol*|ref_e| (+ 2*u_e, u_e the "
                      "spread of the FD plateau, when the producer resolves it); no "
                      "column-norm, row, path or history floor"},
    "primal_row_scaled/1": {
        "accepted": True, "applies_to": ("primal",), "rtol_max": 1e-8,
        "definition": "per component: tau = atol + rtol*max(|row max|, 1e-3 x |history "
                      "max|) (corpus_features harness primal rule)"},
    "abaqus_primal_history_floor/1": {
        "accepted": True, "applies_to": ("primal",), "rtol_max": 1e-8,
        "definition": "umat_oti.abaqus.compare: per component |oti - orig| / max(|oti|,"
                      " |orig|) <= rtol; components below 1e-8 of the field's history "
                      "max are unresolved (skipped), differences below min(1e-12, rtol) "
                      "x history max are indistinguishable; ratio = worst relative / "
                      "rtol"},
    "routine_primal_gate/1": {
        "accepted": True, "applies_to": ("primal",), "rtol_max": 1e-8,
        "definition": "the Abaqus primal gate (verify_store_in_abaqus, decision D-15): every "
                      "converged call of the original replayed in both builds at the recorded "
                      "inputs; |dSTRESS_i| <= rtol*max|STRESS| + U*eps*K_i (K_i from the "
                      "ORIGINAL's stiffness, U the row's measured noise floor, cap 64), "
                      "|dSTATEV_k| <= rtol*max|STATEV_k|; ratio = max(worst stress / bound, "
                      "worst state relative / rtol)"},
    "legacy_column_norm": {
        "accepted": False, "applies_to": ("derivative",), "rtol_max": 0.0,
        "definition": "tau_e = atol + rtol*max(|ref_e|, column norm) or a 1e-3 path "
                      "floor -- refused for verified (B1 review C: an entry far below "
                      "its column norm passes with 100% error)"},
    "vector_max_norm": {
        "accepted": False, "applies_to": ("derivative",), "rtol_max": 0.0,
        "definition": "max|a - d| <= atol + rtol*max(max|a|, max|d|) over a whole "
                      "vector -- not entrywise; refused for verified"},
}

#: FD plateau bases. Only an FD-only plateau (the FD values themselves agree
#: across >= MIN_PLATEAU consecutive steps) is accepted; a plateau defined as
#: "the steps where FD agrees with OTI" is the legacy rule D-4 rejects.
PLATEAU_BASES = {"fd_only": True, "oti_vs_fd": False}

#: Values that do not state anything.
_PLACEHOLDERS = {"", "-", "--", "n/a", "na", "none", "null", "?", "tbd", "todo", "x",
                 "q", "w", "..."}

#: Pipeline stages, in order. ``eligible`` = adequately specified (D2).
STAGES: tuple[str, ...] = (
    "discovered", "eligible", "attempted", "transformed", "compiled",
    "original_executed", "oti_executed", "primal_agreed",
)

FEATURES: tuple[str, ...] = (
    "primal_stress_state", "ddsdde", "internal_jacobian",
    "stress_param_sens_local", "stress_param_sens_total",
    "state_param_sens_local", "state_param_sens_total",
    "residual_sens", "global_sens", "cli_driver",
)

#: Features that are derivative claims and must state quantity/wrt/held_fixed/scope.
DERIVATIVE_FEATURES: frozenset[str] = frozenset(
    set(FEATURES) - {"primal_stress_state", "cli_driver"})

#: References independent of the OTI implementation.
REFERENCE_TYPES: tuple[str, ...] = ("original", "analytical", "fd")

#: Where a row's material constants came from (D-19, D-21) and whose
#: experiment ran (D-19a rev 2); "" where no material data exists. The
#: registry (tools/build_corpus_registry.py) decides them; the manifest
#: carries them per row under ``origins``.
MATERIAL_DATA_ORIGINS: tuple[str, ...] = (
    "author_deck", "author_published_outside_deck", "council_chosen")
EXPERIMENT_ORIGINS: tuple[str, ...] = ("author", "council")
#: deck_pairing.Pairing.refusal_kind (D-19a rev 2 R0).
REFUSAL_KINDS: tuple[str, ...] = (
    "no_deck_in_repository", "no_deck_names_this_source",
    "author_block_rejected", "author_deck_unresolved")
#: The four tiers every verified count is split by (D-21 condition 6).
TIERS: tuple[str, ...] = (
    "author_deck", "author_published_outside_deck+author_experiment",
    "author_published_outside_deck+council_experiment", "council_chosen")
#: Constant confidences, best first: the harvest's (D-19a R5) and the D-21
#: labels (R-3) on one scale; the worst over a row's constants is recorded.
CONSTANT_CONFIDENCES: tuple[str, ...] = (
    "exact", "author-kept", "interpreted", "author-other-context", "looked-up",
    "class-typical", "chosen", "uncertain")

#: The registry's terminal states that the transform refusal / failure maps to.
_EXTERNAL = "external"

#: Registry terminal states that passed the Abaqus primal gate; the same set
#: as tools/build_corpus_registry.PRIMAL_GATE_PASSED and count_target PRIMAL_OK.
_PRIMAL_GATE_PASSED = ("fully_verified", "tangent_not_verified",
                       "derivative_truncated")


def _informative_gate_hidden(rec: Mapping) -> bool:
    """A primal-gate-passed stage whose mechanically_informative gate does not
    read "true": a later stage hiding the gate (Vera B10 pass21)."""
    return (rec.get("terminal_state") in _PRIMAL_GATE_PASSED
            and rec.get("gate_mechanically_informative") != "true")

STAGE_DEFINITIONS: dict[str, str] = {
    "discovered": "the file is listed in the discovery inventory "
                  "(paper_results/discovery)",
    "eligible": "adequately specified genuine UMAT (registry D2): Abaqus UMAT "
                "interface, distinct, constitutive content, builds as "
                "published, every USEd module published, material constants "
                "published",
    "attempted": "the transform-all pass selected and ran this source",
    "transformed": "the transformer produced OTI Fortran for this source",
    "compiled": "the transformed build compiled in at least one layout "
                "(offline gfortran store build, or the Abaqus/ifort job build); "
                "per-layout statuses are under `layouts`",
    "original_executed": "the ORIGINAL routine ran to completion in Abaqus on "
                         "the verification deck",
    "oti_executed": "the OTI build ran to completion in Abaqus on the same deck",
    "primal_agreed": "stress and state history of the OTI build agreed with "
                     "the original over the whole run (gate primal_agreed)",
}

FEATURE_DEFINITIONS: dict[str, dict[str, str]] = {
    "primal_stress_state": {
        "quantity": "STRESS and STATEV history of the OTI build",
        "wrt": "n/a (primal)", "held_fixed": "deck, PROPS, loading path",
        "scope": "history", "reference": "original",
        "rule": "decided by the Abaqus primal gate (D-15, tolerance rule "
                "routine_primal_gate/1): verified iff the comparison(s) named in "
                "decided_by measured paired calls with ratio <= 1 and gates "
                "abaqus_job_completed, complete_history_finite, primal_agreed and "
                "mechanically_informative are all true; max_error is the ratio of "
                "the deciding comparison; failed only when a deciding comparison "
                "measured a ratio > 1; a process failure (control job incomplete, "
                "no paired calls, no init build) is inconclusive, or not_attempted "
                "when nothing was measured, with process_failure naming it; an "
                "original undefined on the history (D-12) is undefined_in_original; "
                "the FE history comparison is informational only "
                "(measured.fe_comparison_informational). Records from before the "
                "gate keep abaqus_primal_history_floor/1"},
    "ddsdde": {
        "quantity": "DDSDDE = d STRESS_{n+1} / d (strain-increment driver)",
        "wrt": "the increment driver (DSTRAN, or the deformation gradient for "
               "finite-strain sources)",
        "held_fixed": "incoming STRESS/STATEV, PROPS, TIME, TEMP",
        "scope": "local", "reference": "fd",
        "rule": "verified only from merged D-4-compliant evidence on the store "
                "build (FD of the ORIGINAL routine with restored state, FD-only "
                "plateau >= 3 steps, entrywise tolerance rule, ratio <= 1) AND "
                "only while primal_stress_state is verified; otherwise a merged "
                "verified is shown as inconclusive. The pass's Abaqus tangent "
                "gate is carried as ddsdde_legacy_gate with its tangent_verdict "
                "(verified / failed / unresolved): from G10 it is the D-4 gate, "
                "before G10 the legacy plateau rule; it is never counted here"},
    "internal_jacobian": {"quantity": "Jacobian of the routine's local Newton "
                          "residual", "scope": "local"},
    "stress_param_sens_local": {"quantity": "d STRESS_{n+1} / d PROPS",
                                "held_fixed": "incoming state", "scope": "local"},
    "stress_param_sens_total": {"quantity": "d STRESS_n / d PROPS",
                                "held_fixed": "loading path", "scope": "total"},
    "state_param_sens_local": {"quantity": "d STATEV_{n+1} / d PROPS",
                               "held_fixed": "incoming state", "scope": "local"},
    "state_param_sens_total": {"quantity": "d STATEV_n / d PROPS",
                               "held_fixed": "loading path", "scope": "total"},
    "residual_sens": {"quantity": "sensitivity of the assembled FE residual",
                      "scope": "total"},
    "global_sens": {"quantity": "sensitivity of a global FE response",
                    "scope": "total"},
    "cli_driver": {"quantity": "the source runs under the project's CLI driver",
                   "scope": "n/a"},
}

# ---------------------------------------------------------------------------
# Licence -> redistribution policy
# ---------------------------------------------------------------------------

#: The project's own licence. Redistribution of a third-party source alongside
#: it requires a licence compatible with it.
PROJECT_LICENSE = "GPL-3.0-only"

_POLICY: dict[str, dict[str, Any]] = {}


def _p(ids: Iterable[str], **kw: Any) -> None:
    for i in ids:
        _POLICY[i] = dict(kw)


_p(("MIT",), license_class="permissive", attribution_required=True,
   copyleft="none", conditions="keep the copyright notice and permission notice")
_p(("BSD-2-Clause", "BSD-3-Clause"), license_class="permissive",
   attribution_required=True, copyleft="none",
   conditions="keep the copyright notice, conditions and disclaimer"
              " (BSD-3: no endorsement using the authors' names)")
_p(("ISC", "Zlib"), license_class="permissive", attribution_required=True,
   copyleft="none", conditions="keep the copyright and permission notice")
_p(("Apache-2.0",), license_class="permissive", attribution_required=True,
   copyleft="none",
   conditions="keep LICENSE and any NOTICE file; state changes made to the file")
_p(("GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later"), license_class="copyleft",
   attribution_required=True, copyleft="strong",
   conditions="redistribute under GPL-3.0 with source; keep notices")
_p(("AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later"),
   license_class="copyleft", attribution_required=True, copyleft="network",
   conditions="redistribute under AGPL-3.0 with source; combination with "
              "GPL-3.0 is allowed by GPL-3.0 s.13 / AGPL-3.0 s.13, and network "
              "use triggers source offer")
_p(("LGPL-3.0", "LGPL-3.0-only", "LGPL-3.0-or-later"), license_class="copyleft",
   attribution_required=True, copyleft="weak",
   conditions="redistribute the file under LGPL-3.0 with source; keep notices")

#: Recognised licences that are NOT compatible with redistribution next to a
#: GPL-3.0-only project (mirrors the refusals of the discovery licence gate).
_INCOMPATIBLE = {
    "GPL-2.0": "GPL-2.0-only cannot be combined with GPL-3.0-only code",
    "GPL-2.0-only": "GPL-2.0-only cannot be combined with GPL-3.0-only code",
    "LGPL-2.1": "LGPL-2.1-only is outside the project's redistribution gate",
    "LGPL-2.1-only": "LGPL-2.1-only is outside the project's redistribution gate",
    "CC-BY-NC-4.0": "non-commercial clause",
    "CC-BY-NC-SA-4.0": "non-commercial clause",
    "CC-BY-ND-4.0": "no-derivatives clause",
    "CC-BY-NC-ND-4.0": "non-commercial and no-derivatives clauses",
}

#: Lead decision D-1/D-2 (2026-10-01): the ONLY licences under which a corpus
#: source counts as redistributable next to this GPL-3.0-only project, and only
#: when the licence FILE itself is present (at the pinned commit, in the cache).
PERMITTED_WITH_FILE = frozenset({
    "MIT", "BSD-2-CLAUSE", "BSD-3-CLAUSE", "APACHE-2.0", "GPL-3.0",
    "GPL-3.0-ONLY", "GPL-3.0-OR-LATER", "LGPL-3.0", "LGPL-3.0-ONLY",
    "LGPL-3.0-OR-LATER"})

#: Strings that mean "no licence was found".
_NO_LICENSE = {"", "NONE", "NOASSERTION", "UNLICENSED", "NO LICENSE", "OTHER"}

#: A licence file at the root of a repository tree.
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|unlicense)([._-][a-z0-9]+)?$", re.IGNORECASE)


def licence_terms(spdx: str | None) -> dict[str, Any]:
    """Class, attribution and copyleft of an SPDX id (no redistribution decision)."""
    key = (spdx or "").strip().upper()
    for known, policy in _POLICY.items():
        if known.upper() == key:
            return dict(policy)
    if key in _NO_LICENSE:
        return {"license_class": "none", "attribution_required": None,
                "copyleft": None, "conditions": ""}
    if key in {k.upper() for k in _INCOMPATIBLE}:
        gpl = "GPL" in key
        return {"license_class": "copyleft" if gpl else "restricted",
                "attribution_required": True, "copyleft": "strong" if gpl else None,
                "conditions": ""}
    return {"license_class": "unknown", "attribution_required": None,
            "copyleft": None, "conditions": ""}


def detect_licence_text(text: str) -> str | None:
    """SPDX id of a licence file (notice/title first; see
    :func:`umat_oti.corpus.acquire.classify_license_text`)."""
    from umat_oti.corpus.acquire import classify_license_text
    return classify_license_text(text)


def find_licence_file(repo_dir: Path) -> Path | None:
    """The licence file at the root of a cached repository tree, if cached."""
    if not repo_dir.is_dir():
        return None
    hits = sorted(p for p in repo_dir.iterdir() if p.is_file()
                  and LICENSE_FILE.match(p.name))
    return hits[0] if hits else None


def redistribution_policy(spdx: str | None,
                          licence_file: Mapping[str, Any] | None = None,
                          *, metadata_source: str = "") -> dict[str, Any]:
    """Redistribution decision for one source (lead decision D-1/D-2).

    ``permitted`` only when a licence FILE was found at the repository root of
    the acquisition cache (the tree at the pinned commit) and its text reads as
    one of :data:`PERMITTED_WITH_FILE`. ``licence_file`` is
    ``{"path": <locator>, "detected_spdx": <id or None>}`` or None.

    * no licence anywhere -> ``not_permitted`` (all rights reserved);
    * a licence known to be incompatible (file or metadata) -> ``not_permitted``;
    * a compatible licence known only from metadata (registry ``license_spdx`` /
      GitHub licence API) with no file in the cache -> ``unknown``: the cache
      may hold a partial tree, so the basis says "file absent from cache", not
      "repository has no licence";
    * a file whose wording is not recognised, or a licence outside the
      permitted list (AGPL-3.0, ISC, Zlib, ...) -> ``unknown``.
    """
    meta = (spdx or "").strip()
    meta_key = meta.upper()
    file_spdx = (licence_file or {}).get("detected_spdx") or None
    effective = file_spdx or meta
    terms = licence_terms(effective)
    out: dict[str, Any] = {
        "spdx": effective, "spdx_metadata": meta,
        "spdx_metadata_source": metadata_source,
        "licence_file": dict(licence_file) if licence_file else None,
        **terms,
    }
    incompatible = {k.upper(): v for k, v in _INCOMPATIBLE.items()}
    if licence_file:
        where = licence_file.get("path", "")
        if file_spdx is None:
            out.update(redistribution="unknown", redistribution_basis=(
                f"licence file {where} is present but its wording is not "
                f"recognised; metadata says {meta or 'nothing'}"))
        elif file_spdx.upper() in PERMITTED_WITH_FILE:
            note = ("" if not meta or meta_key == file_spdx.upper() else
                    f"; NOTE metadata says {meta}, the file reads as {file_spdx}")
            out.update(redistribution="permitted", redistribution_basis=(
                f"licence file {where} reads as {file_spdx}, which is on the "
                f"permitted list (lead decision D-1/D-2) and compatible with "
                f"{PROJECT_LICENSE}{note}"))
        elif file_spdx.upper() in incompatible:
            out.update(redistribution="not_permitted", redistribution_basis=(
                f"licence file {where} reads as {file_spdx}: "
                f"{incompatible[file_spdx.upper()]}"))
        else:
            out.update(redistribution="unknown", redistribution_basis=(
                f"licence file {where} reads as {file_spdx}, which is not on the "
                "permitted list (lead decision D-1/D-2); needs a decision"))
        return out
    if meta_key in _NO_LICENSE:
        out.update(redistribution="not_permitted", redistribution_basis=(
            "no licence declared in the repository metadata and no licence file "
            "in the acquisition cache: all rights reserved by default"))
    elif meta_key in incompatible:
        out.update(redistribution="not_permitted", redistribution_basis=(
            f"repository metadata declares {meta}: {incompatible[meta_key]} "
            "(licence file absent from cache)"))
    else:
        out.update(redistribution="unknown", redistribution_basis=(
            f"licence file absent from the acquisition cache (the cache holds a "
            f"partial tree, so this does not mean the repository has none); "
            f"{meta} is known only from repository metadata"
            + (f" ({metadata_source})" if metadata_source else "")
            + "; not confirmed"))
    return out


# ---------------------------------------------------------------------------
# Source scanning
# ---------------------------------------------------------------------------

_ABAQUS_UTILITIES = {
    "XIT", "STDB_ABQERR", "SINV", "SPRINC", "SPRIND", "ROTSIG", "GETVRM",
    "GETVRMAVGATGP", "GETPARTINFO", "GETINTERNAL", "GETJOBNAME", "GETOUTDIR",
    "GETNUMCPUS", "GETRANK", "GETCOMMSIZE", "GET_THREAD_ID", "MUTEXINIT",
    "MUTEXLOCK", "MUTEXUNLOCK", "GETELEMNUMBERUSER", "GETNODETOELEMCONN",
    "POSFIL", "VGETVRM", "VGETPARTINFO", "VGETINTERNAL", "GETVRN", "GETVRMG",
    "STDB_ABQWARN", "GETTHREADID", "UMATHT", "GETVRMIP",
    # event-series and table-collection utilities (Abaqus 2020+)
    "GETEVENTSERIESSLICELG", "GETEVENTSERIESSLICEPROPERTIES",
    "GETEVENTSERIESSLICELGPROPERTIES", "SETTABLECOLLECTION", "GETPROPERTYTABLE",
    "GETPROPERTYTABLEPROPERTIES", "GETPARAMETERTABLE",
    "GETPARAMETERTABLEPROPERTIES", "GETTABLECOLLECTION",
}
_LAPACK_BLAS = {
    p + n for p in "SDCZ" for n in (
        "GESV", "GETRF", "GETRI", "GETRS", "SYEV", "SYEVD", "SYEVR", "SYEVX",
        "GEEV", "GESVD", "GESDD", "POTRF", "POTRS", "POTRI", "POSV", "GEMM",
        "GEMV", "AXPY", "COPY", "SCAL", "SYSV", "GELS", "GECON", "GEQRF",
        "ORGQR", "TRSM", "TRSV", "SYTRF", "SYTRI", "SYTRS", "LACPY", "LASET",
        "GER", "SYMV", "SYMM", "SWAP", "GBSV", "GTSV", "PTSV", "GEES")
}
_FORTRAN_INTRINSIC_SUBROUTINES = {
    "RANDOM_NUMBER", "RANDOM_SEED", "DATE_AND_TIME", "CPU_TIME", "SYSTEM_CLOCK",
    "MVBITS", "GET_COMMAND", "GET_COMMAND_ARGUMENT", "GET_ENVIRONMENT_VARIABLE",
    "EXECUTE_COMMAND_LINE", "MOVE_ALLOC", "C_F_POINTER", "C_F_PROCPOINTER",
    "GETARG", "GETENV", "EXIT", "ABORT", "FLUSH", "SLEEP", "SYSTEM",
    "IEEE_SET_FLAG", "IEEE_GET_FLAG", "IEEE_SET_HALTING_MODE",
    "IEEE_GET_HALTING_MODE", "IEEE_SET_ROUNDING_MODE", "IEEE_GET_ROUNDING_MODE",
    "IEEE_GET_STATUS", "IEEE_SET_STATUS", "ATOMIC_DEFINE", "ATOMIC_REF",
    "RANDOM_INIT", "ERROR_STOP", "FDATE", "ITIME", "IDATE", "CHDIR", "PERROR",
}
_INTRINSIC_MODULES = {"ISO_C_BINDING", "ISO_FORTRAN_ENV", "IEEE_ARITHMETIC",
                      "IEEE_EXCEPTIONS", "IEEE_FEATURES", "OMP_LIB", "IFPORT",
                      "IFCORE", "MPI", "MPI_F08"}
_ABAQUS_HEADERS = {"ABA_PARAM.INC", "VABA_PARAM.INC", "SMAASPUSERSUBROUTINES.HDR",
                   "SMAASPUSERUTILITIES.HDR", "SMAASPUSERARRAYS.HDR"}

_UNIT_HEADER = re.compile(
    r"^(?:\d+\s+)?(?:(?:RECURSIVE|PURE|ELEMENTAL|IMPURE|MODULE)\s+)*"
    r"(?:(?:DOUBLE\s*PRECISION|REAL|INTEGER|LOGICAL|CHARACTER|COMPLEX|TYPE\s*\([^)]*\))"
    r"(?:\s*\*\s*\d+|\s*\([^)]*\))?\s+)?"
    r"(SUBROUTINE|FUNCTION)\s+([A-Za-z_]\w*)", re.IGNORECASE)
_MODULE = re.compile(r"^MODULE\s+(?!PROCEDURE\b)([A-Za-z_]\w*)\s*$", re.IGNORECASE)
_ENTRY = re.compile(r"^ENTRY\s+([A-Za-z_]\w*)", re.IGNORECASE)
_INTERFACE_OPEN = re.compile(r"^(ABSTRACT\s+)?INTERFACE\b\s*([A-Za-z_]\w*)?", re.IGNORECASE)
_INTERFACE_CLOSE = re.compile(r"^END\s*INTERFACE\b", re.IGNORECASE)
_CALL = re.compile(r"\bCALL\s+([A-Za-z_]\w*)\s*(%)?", re.IGNORECASE)
_USE = re.compile(r"^USE\b\s*(?:,\s*(?:INTRINSIC|NON_INTRINSIC)\s*::)?\s*(?:::)?\s*"
                  r"([A-Za-z_]\w*)", re.IGNORECASE)
_INCLUDE = re.compile(r"^\s*INCLUDE\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_CPP_INCLUDE = re.compile(r"^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]", re.IGNORECASE)
_CPP = re.compile(r"^\s*#\s*(define|undef|if|ifdef|ifndef|elif|else|endif|include)\b",
                  re.IGNORECASE)
_OPEN = re.compile(r"\bOPEN\s*\((.*)\)", re.IGNORECASE)
_FILE_ARG = re.compile(
    r"\bFILE\s*=\s*((?:'[^']*'|\"[^\"]*\"|[A-Za-z_][\w%]*(?:\([^()]*\))?)"
    r"(?:\s*//\s*(?:'[^']*'|\"[^\"]*\"|[A-Za-z_][\w%]*(?:\([^()]*\))?))*)", re.IGNORECASE)
_DECL = re.compile(
    r"^(DOUBLE\s*PRECISION|REAL|INTEGER|LOGICAL|CHARACTER|COMPLEX|DIMENSION|"
    r"TYPE\s*\(|CLASS\s*\(|PARAMETER|COMMON|SAVE|DATA|EXTERNAL|INTRINSIC|"
    r"IMPLICIT|INCLUDE|USE)\b", re.IGNORECASE)
_INDEXED = {name: re.compile(rf"\b{name}\s*\(\s*(\d+)\s*\)", re.IGNORECASE)
            for name in ("PROPS", "STATEV")}
_DIM_BRANCH = re.compile(
    r"\b(NTENS|NDI|NSHR)\s*(\.EQ\.|==|\.NE\.|/=|\.GT\.|\.LT\.|\.GE\.|\.LE\.|>=|<=|>|<)"
    r"\s*(\d+)", re.IGNORECASE)
_HARD_SIX = re.compile(r"\b(STRESS|DSTRAN|STRAN|DDSDDE)\s*\(\s*6\s*(,\s*6\s*)?\)", re.IGNORECASE)
_FIRST_INCREMENT = re.compile(
    r"\bIF\s*\(.*\b(KINC|KSTEP)\s*(\.EQ\.|==)\s*1\b", re.IGNORECASE)
_LOG_HINT = re.compile(r"logarithmic|hencky|\blog(?:arithmic)?[\s_-]*strain", re.IGNORECASE)
_TOKENS = ("DSTRAN", "STRAN", "DFGRD0", "DFGRD1", "DROT", "TIME", "DTIME", "COORDS",
           "TEMP", "DTEMP", "PNEWDT", "CELENT")


@dataclass
class SourceScan:
    """What the published text of a source and its companions shows."""

    files: list[str] = field(default_factory=list)
    defined: set[str] = field(default_factory=set)
    modules_defined: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)
    uses: set[str] = field(default_factory=set)
    includes: list[str] = field(default_factory=list)
    preprocessor: list[str] = field(default_factory=list)
    data_files: list[str] = field(default_factory=list)
    #: The OPENed names that are an absolute path on the author's machine
    #: (``/work/...``, ``C:\\...``, a UNC share, ``~/``), read from the
    #: literal the FILE= expression starts with. Such a file exists only where
    #: the author ran; whether the repository publishes it beside the source
    #: decides missing_material_data (Vera B10 ruling b, the registry's
    #: ``unpublished_absolute_input`` rule).
    data_files_absolute: list[str] = field(default_factory=list)
    reads_tokens: dict[str, bool] = field(default_factory=dict)
    props_max: int | None = None
    statev_max: int | None = None
    dim_branches: list[tuple[str, str, int]] = field(default_factory=list)
    hard_six: list[str] = field(default_factory=list)
    sdvini_defined: bool = False
    first_increment_branch: bool = False
    log_strain_hint: bool = False
    extensions: list[str] = field(default_factory=list)
    openmp: bool = False
    unreadable: list[str] = field(default_factory=list)


def _logical(text: str, form: str):
    from umat_oti.fortran.parser import logical_lines_from_text
    return logical_lines_from_text(text, "fixed" if form == "fixed" else "free")


def _absolute_file_expr(expr: str) -> str:
    """The literal part of a FILE= expression if it names an absolute path.

    ``'/work/a/b.txt'`` and ``'C:\\dir\\'//name`` both start with an
    absolute literal, so the file lives on the author's machine whatever the
    rest concatenates; the joined literal prefix is returned, else ``""``.
    """
    from umat_oti.corpus.source_rulings import is_absolute_path
    pieces = re.findall(r"\s*(?:'([^']*)'|\"([^\"]*)\"|([^/'\"]+))\s*(?://|$)",
                        expr.strip())
    prefix = ""
    for single, double, other in pieces:
        if other.strip():
            break
        prefix += single or double
    return prefix if prefix and is_absolute_path(prefix) else ""


def scan_sources(paths: Sequence[Path], forms: Sequence[str]) -> SourceScan:
    """Scan the closure (entry file first, then companions)."""
    scan = SourceScan(reads_tokens={t: False for t in _TOKENS})
    token_res = {t: re.compile(rf"\b{t}\b", re.IGNORECASE) for t in _TOKENS}
    exts: set[str] = set()
    for path, form in zip(paths, forms):
        scan.files.append(str(path))
        try:
            raw = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            scan.unreadable.append(str(path))
            continue
        scan.preprocessor.extend(sorted({m.group(1).lower() for line in
                                         raw.splitlines()
                                         if (m := _CPP.match(line))}))
        for line in raw.splitlines():
            m = _CPP_INCLUDE.match(line)
            if m:
                scan.includes.append(m.group(1))
            if form == "fixed":
                if "\t" in line[:6]:
                    exts.add("tab_in_fixed_form_label_field")
                if len(line.rstrip()) > 72 and line[:1] not in "cC*!":
                    exts.add("fixed_form_line_beyond_column_72")
            elif len(line.rstrip()) > 132:
                exts.add("free_form_line_beyond_column_132")
            stripped = line.strip().upper()
            if stripped.startswith(("!$OMP", "C$OMP", "*$OMP")):
                scan.openmp = True
            if stripped.startswith(("!DEC$", "CDEC$", "!DIR$", "CDIR$")):
                exts.add("compiler_directive_" + stripped[1:5].replace("$", ""))
        if _LOG_HINT.search(raw):
            scan.log_strain_hint = True
        depth = 0
        for logical in _logical(raw, form):
            text = getattr(logical, "text", str(logical)).strip()
            upper = text.upper()
            if re.search(r"\bREAL\s*\*\s*\d|\bINTEGER\s*\*\s*\d", upper):
                exts.add("star_length_type_declarations (REAL*8 style)")
            if re.search(r"\bDOUBLE\s*COMPLEX\b", upper):
                exts.add("double_complex")
            m = _INCLUDE.match(text)
            if m:
                scan.includes.append(m.group(1))
                continue
            if _INTERFACE_CLOSE.match(text):
                depth = max(0, depth - 1)
                continue
            m = _INTERFACE_OPEN.match(text)
            if m and not upper.startswith("INTERFACE ASSIGNMENT") :
                depth += 1
                if m.group(2):
                    scan.defined.add(m.group(2).upper())
                continue
            if depth:
                continue
            m = _MODULE.match(text)
            if m:
                scan.modules_defined.add(m.group(1).upper())
                continue
            m = _UNIT_HEADER.match(text)
            if m and not upper.startswith("END"):
                scan.defined.add(m.group(2).upper())
                if m.group(2).upper() == "SDVINI":
                    scan.sdvini_defined = True
                continue
            m = _ENTRY.match(text)
            if m:
                scan.defined.add(m.group(1).upper())
            m = _USE.match(text)
            if m:
                scan.uses.add(m.group(1).upper())
                continue
            for c in _CALL.finditer(text):
                if c.group(2):          # obj%method -- a type-bound call
                    continue
                scan.calls.add(c.group(1).upper())
            m = _OPEN.search(text)
            if m:
                f = _FILE_ARG.search(m.group(1))
                scan.data_files.append(
                    f.group(1).strip() if f else "<OPEN without FILE=: unit "
                                                  "pre-connected or scratch>")
                if f and _absolute_file_expr(f.group(1)):
                    scan.data_files_absolute.append(_absolute_file_expr(f.group(1)))
            for name, rx in _INDEXED.items():
                for hit in rx.finditer(text):
                    v = int(hit.group(1))
                    cur = scan.props_max if name == "PROPS" else scan.statev_max
                    if cur is None or v > cur:
                        if name == "PROPS":
                            scan.props_max = v
                        else:
                            scan.statev_max = v
            for hit in _DIM_BRANCH.finditer(text):
                scan.dim_branches.append((hit.group(1).upper(),
                                          hit.group(2).upper(), int(hit.group(3))))
            for hit in _HARD_SIX.finditer(text):
                if _DECL.match(text) or upper.startswith(("SUBROUTINE",)):
                    scan.hard_six.append(hit.group(0).upper().replace(" ", ""))
            if _FIRST_INCREMENT.search(text):
                scan.first_increment_branch = True
            if not _DECL.match(text) and not _UNIT_HEADER.match(text):
                for t, rx in token_res.items():
                    if not scan.reads_tokens[t] and rx.search(text):
                        scan.reads_tokens[t] = True
    scan.extensions = sorted(exts)
    scan.hard_six = sorted(set(scan.hard_six))
    scan.dim_branches = sorted(set(scan.dim_branches))
    return scan


def _classify_external(name: str) -> str:
    if name in _ABAQUS_UTILITIES or name.startswith("SMA"):
        return "abaqus_utility"
    if name in _LAPACK_BLAS:
        return "lapack_blas"
    if name in _FORTRAN_INTRINSIC_SUBROUTINES or name.startswith("IEEE_"):
        return "fortran_intrinsic_or_vendor"
    if name.startswith("MPI_"):
        return "mpi"
    return "unresolved_external"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass
class ManifestInputs:
    """Where every input lives. Repo paths are relative to ``repo``."""

    repo: Path
    discovery_cache: Path
    transform_store: Path
    corpus_run: Path
    families: Path
    families_second_pass: Path | None = None
    #: D-11 reporting classification: Scout's B3 code-evidence review (column
    #: S1). Rows it did not check fall back to ``families`` (E).
    families_reporting: Path | None = None
    #: Registry revision whose eligible set the summary compares against
    #: (``summary.denominators_note``); None skips the comparison.
    earlier_registry_rev: str | None = "f0f0731"
    registry: str = "paper_results/corpus/corpus_registry.json"
    triage: str = "paper_results/discovery/discovery_triage.json"
    discovered: str = "paper_results/discovery/discovered_sources.csv"
    discovered_summary: str = "paper_results/discovery/discovered_sources.json"
    companions: tuple[str, ...] = ("paper_results/corpus/companions.json",
                                   "paper_results/corpus/companions_wave2.json")
    extracted_decks: str = "paper_results/corpus/extracted_decks.json"
    param_sens_round: str = ("paper_results/parameter_sensitivity/"
                             "parameter_sensitivity_round.json")
    param_sens_models: str = "parameter_sensitivity/models"
    internal_jacobian_round: str = ("paper_results/internal_jacobians/"
                                    "internal_jacobian_round.json")
    verifier: str = "tools/verify_store_in_abaqus.py"
    current_pass: str = "pass16"
    later_pass: str | None = "pass17"
    campaign: Path | None = None
    ra_repo: Path | None = None

    def roots(self) -> dict[str, str]:
        roots = {"repo": str(self.repo), "umat": str(self.repo),
                 "discovery_cache": str(self.discovery_cache),
                 "transform_store": str(self.transform_store),
                 "corpus_run": str(self.corpus_run),
                 "families": str(self.families.parent)}
        ws = Path(self.repo).parent
        roots["campaign"] = str(self.campaign or ws / "corpus_campaign")
        roots["ra"] = str(self.ra_repo or ws / "final-ra")
        return dict(sorted(roots.items()))


# ---------------------------------------------------------------------------
# Evidence locators
# ---------------------------------------------------------------------------

#: The workspace this module sits in (``<ws>/final-umat/src/umat_oti/...``).
_REPO_DEFAULT = Path(__file__).resolve().parents[3]
_WS_DEFAULT = _REPO_DEFAULT.parent

#: Root map used when a caller supplies none (e.g. the feature runner checking
#: its cells before a manifest exists). ``repo`` and ``umat`` are the same
#: checkout; ``repo`` is kept for the locators the B1 manifest already wrote.
DEFAULT_ROOTS: dict[str, str] = {
    "campaign": str(_WS_DEFAULT / "corpus_campaign"),
    "corpus_run": str(_WS_DEFAULT / "corpus_run"),
    "discovery_cache": str(_WS_DEFAULT / "discovery_cache"),
    "families": str(_WS_DEFAULT / "corpus_run"),
    "ra": str(_WS_DEFAULT / "final-ra"),
    "repo": str(_REPO_DEFAULT),
    "transform_store": str(_WS_DEFAULT / "transform_store"),
    "umat": str(_REPO_DEFAULT),
}

#: How a root under the workspace is written into a published manifest: as a
#: path relative to ``$UMAT_OTI_WORKSPACE`` rather than this machine's home
#: directory, so the artefact carries no machine path. Read back through
#: :func:`expand_roots`.
WORKSPACE_TOKEN = "$UMAT_OTI_WORKSPACE"


def _workspace() -> str:
    """``$UMAT_OTI_WORKSPACE`` when set, else the directory this checkout sits in."""
    import os
    ws = os.environ.get("UMAT_OTI_WORKSPACE") or str(_WS_DEFAULT)
    return ws.rstrip("/") or "/"


def _workspace_pattern(workspace: str) -> "re.Pattern[str]":
    # Only a whole path component sequence: not preceded by a path character
    # and followed by "/" or by anything that cannot continue a file name
    # (so ``<ws>2`` or ``<ws>_old`` is left alone).
    return re.compile(r"(?<![\w.~-])" + re.escape(workspace) + r"(?![\w.~-])")


def portable_roots(roots: Mapping[str, str]) -> dict[str, str]:
    """Roots as written into a published manifest (workspace-relative)."""
    pat = _workspace_pattern(_workspace())
    return {name: pat.sub(WORKSPACE_TOKEN, str(value), count=1)
            if pat.match(str(value)) else str(value)
            for name, value in roots.items()}


#: Roots that always name the checkout doing the reading, whatever a manifest
#: recorded: a clone under another name resolves ``repo:``/``umat:`` locators
#: against itself.
_CHECKOUT_ROOTS = ("repo", "umat")


def expand_roots(roots: Mapping[str, str]) -> dict[str, str]:
    """Inverse of :func:`portable_roots`, against ``$UMAT_OTI_WORKSPACE`` if set,
    else the workspace this checkout sits in. ``repo`` and ``umat`` resolve to
    the current checkout."""
    workspace = _workspace()
    out = {}
    for name, value in roots.items():
        text = str(value)
        if name in _CHECKOUT_ROOTS:
            text = str(_REPO_DEFAULT)
        elif text == WORKSPACE_TOKEN or text.startswith(WORKSPACE_TOKEN + "/"):
            text = workspace + text[len(WORKSPACE_TOKEN):]
        out[name] = text
    return out


_LOCATOR = re.compile(r"^([a-z][a-z0-9_]*):(?!//)([^#]+)(?:#(.*))?$")


def resolve_locator(locator: str, roots: Mapping[str, str] | None = None
                    ) -> tuple[Path | None, str]:
    """``(<file>, "")`` for a locator that names an existing file, else
    ``(None, <why not>)``.

    A locator is ``<root>:<path relative to that root>[#selector]``; the
    selector is not checked. The path may not leave its root.
    """
    roots = dict(DEFAULT_ROOTS if roots is None else roots)
    if not isinstance(locator, str) or not locator.strip():
        return None, "no evidence locator"
    m = _LOCATOR.match(locator.strip())
    if not m:
        return None, (f"evidence {locator!r} is not a <root>:<relative path> locator "
                      f"(roots: {', '.join(sorted(roots))})")
    root_name, rel = m.group(1), m.group(2)
    if root_name not in roots:
        return None, (f"evidence root {root_name!r} is not one of "
                      f"{', '.join(sorted(roots))}")
    root = Path(roots[root_name]).resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        return None, f"evidence {locator!r} leaves its root"
    if not target.is_file():
        return None, f"evidence {locator!r} does not resolve to a file ({target})"
    return target, ""


def to_locator(evidence: str, roots: Mapping[str, str] | None = None) -> str:
    """Rewrite an absolute path under a known root as ``<root>:<relative>``.

    The most specific root wins (``campaign`` over nothing, ``umat`` over
    ``repo``). Anything else is returned unchanged.
    """
    if not isinstance(evidence, str) or not evidence.startswith("/"):
        return evidence
    path, _, sel = evidence.partition("#")
    best = None
    for name, root in sorted((roots or DEFAULT_ROOTS).items()):
        if name in ("repo", "families"):
            continue
        r = str(Path(root).resolve())
        if path == r or path.startswith(r.rstrip("/") + "/"):
            if best is None or len(r) > len(best[1]):
                best = (name, r)
    if best is None:
        return evidence
    rel = path[len(best[1]):].lstrip("/")
    return f"{best[0]}:{rel}" + (f"#{sel}" if sel else "")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _cell(status: str, reason: str, evidence: str = "", **extra: Any) -> dict:
    out = {"status": status, "reason": reason, "evidence": evidence}
    out.update(extra)
    return out


def _inherit(up_name: str, up: dict) -> dict:
    s = up["status"]
    if s in ("blocked", "not_applicable", "unsupported"):
        return _cell(s, f"upstream stage `{up_name}` is {s}: {up['reason']}",
                     up.get("evidence", ""))
    if s == "verified":
        return _cell("not_attempted", f"upstream stage `{up_name}` passed but no "
                     "record of this stage exists")
    return _cell("not_attempted", f"not reached: upstream stage `{up_name}` is {s}",
                 up.get("evidence", ""))


def _tangent_tolerance(verifier: Path) -> float | None:
    try:
        m = re.search(r"^TANGENT_TOLERANCE\s*=\s*([0-9.eE+-]+)",
                      verifier.read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        return None
    return float(m.group(1)) if m else None


_ELEMENT_MODES = (("C3D", "three_d"), ("CPE", "plane_strain"), ("CPS", "plane_stress"),
                  ("CAX", "axisymmetric"), ("COH", "cohesive"), ("S", "shell"),
                  ("M3D", "membrane"))
_MODE_NTENS = {"three_d": 6, "plane_strain": 4, "axisymmetric": 4, "plane_stress": 3}


def _mode_of(element: str) -> str:
    e = (element or "").upper()
    for prefix, mode in _ELEMENT_MODES:
        if e.startswith(prefix):
            return mode
    return ""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


#: E's family names in the reporting vocabulary (Scout B3 rules, finalize.py MAP).
E_TO_REPORTING: dict[str, str] = {
    "growth / morphoelasticity": "growth", "plasticity": "rate_independent_plasticity",
    "damage / phase field": "damage_phase_field", "crystal plasticity": "crystal_plasticity",
    "elasticity": "linear_elastic", "viscoelasticity / rate dependent": "viscoelastic",
    "concrete / geomaterials": "concrete_geomaterial", "hyperelasticity": "hyperelasticity",
    "other / unclassified": "other", "not a UMAT": "not_a_umat",
}

#: The slide families of the D-11 denominators (hyperelasticity is in "other").
REPORTING_FAMILIES: tuple[str, ...] = (
    "growth", "rate_independent_plasticity", "damage_phase_field", "crystal_plasticity",
    "linear_elastic", "viscoelastic", "concrete_geomaterial", "other_incl_hyperelasticity",
)

FAMILY_CLASSIFICATION = (
    "D-11 S1: Scout's B3 code-evidence family review "
    "(corpus_campaign/batches/B3/scout/families_reviewed_B3.json), with the "
    "identity-growth scaffolds (Jeff97, growth tensor fixed to the identity) "
    "counted as growth; rows B3 did not check take E "
    "(corpus_run/material_families_checked_E.json) mapped to the same names")


def _slide_family(f: str) -> str:
    return "other_incl_hyperelasticity" if f in ("other", "hyperelasticity") else f


def reported_family(source_id: str, b3: Mapping | None, e: Mapping | None) -> dict:
    """The D-11 reporting family of one row (S1), with how it was decided."""
    if b3:
        fam = b3.get("family", "")
        identity_growth = (source_id.startswith("Jeff97")
                           and b3.get("disagreement_kind") == "definitional"
                           and fam != "growth")
        if identity_growth:
            fam = "growth"
        return {"family": fam, "reporting_family": _slide_family(fam),
                "source": "B3_identity_growth_as_growth" if identity_growth
                else "B3_code_evidence",
                "identity_growth_scaffold": identity_growth,
                "b3_family": b3.get("family", ""),
                "b3_confidence": b3.get("confidence", "")}
    if e:
        fam = E_TO_REPORTING.get(e.get("family", ""), e.get("family", ""))
        return {"family": fam, "reporting_family": _slide_family(fam),
                "source": "E_fallback", "identity_growth_scaffold": False,
                "b3_family": "", "b3_confidence": ""}
    return {"family": "", "reporting_family": "", "source": "missing",
            "identity_growth_scaffold": False, "b3_family": "", "b3_confidence": ""}


def _earlier_registry(inp: ManifestInputs) -> tuple[dict | None, str]:
    """The registry at ``inp.earlier_registry_rev`` (git), or (None, why not)."""
    if not inp.earlier_registry_rev:
        return None, "no earlier registry revision given"
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(inp.repo), "show",
                            f"{inp.earlier_registry_rev}:{inp.registry}"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git unavailable: {exc}"
    if r.returncode != 0:
        return None, (r.stderr or "git show failed").strip()[:300]
    return json.loads(r.stdout), ""


def denominators_note(rows: Sequence[Mapping], inp: ManifestInputs,
                      registry: Mapping) -> dict:
    """Eligible as computed at the current pass, and the rows that were
    eligible under the earlier registry and are not now."""
    acquired = [r for r in rows if r["row_kind"] == "acquired"]
    eligible = {r["source_id"] for r in acquired
                if r["pipeline"]["eligible"]["status"] == "verified"}
    cur = {r["source_id"]: r for r in registry["records"]}
    byid = {r["source_id"]: r for r in acquired}
    out = {"eligible_now": len(eligible),
           "eligible_now_means": f"adequately specified genuine UMATs in the registry "
                                 f"as built for {inp.current_pass}",
           "earlier_registry": f"repo:{inp.registry}@{inp.earlier_registry_rev}"
           if inp.earlier_registry_rev else None}
    old, why = _earlier_registry(inp)
    if old is None:
        out.update(eligible_earlier=None, dropped=None, added=None,
                   unavailable=why)
        return out
    old_el = {r["source_id"] for r in old["records"] if r.get("adequately_specified")}
    dropped = []
    for sid in sorted(old_el - eligible):
        row = byid.get(sid) or {}
        fam = (row.get("model") or {}).get("family") or {}
        dropped.append({"source_id": sid,
                        "terminal_state": (cur.get(sid) or {}).get("terminal_state",
                                                                   "not in registry"),
                        "reporting_family": fam.get("reporting_family", ""),
                        "family_source": fam.get("source", "")})
    out.update(
        eligible_earlier=len(old_el),
        dropped_count=len(dropped),
        dropped_by_reporting_family=dict(Counter(d["reporting_family"] for d in dropped)),
        dropped_by_terminal_state=dict(Counter(d["terminal_state"] for d in dropped)),
        dropped=dropped,
        added=sorted(eligible - old_el),
        why=("the D-11 family denominators were stated against the earlier "
             "registry's eligible set; every figure in this manifest uses the "
             "eligible set computed now"))
    return out


def build_manifest(inp: ManifestInputs) -> dict:
    """Assemble the manifest from the inputs. Offline; reads only local files."""
    repo = inp.repo
    registry = json.loads((repo / inp.registry).read_text(encoding="utf-8"))
    records = registry["records"]
    triage = {r["source"]: r for r in
              json.loads((repo / inp.triage).read_text(encoding="utf-8"))["rows"]}
    fam_doc = json.loads(inp.families.read_text(encoding="utf-8"))
    families = {r["source_id"]: r for r in fam_doc["rows"]}
    b3 = {}
    if inp.families_reporting and Path(inp.families_reporting).is_file():
        b3 = {r["source_id"]: r for r in json.loads(
            Path(inp.families_reporting).read_text(encoding="utf-8"))["rows"]}
    second = {}
    if inp.families_second_pass and inp.families_second_pass.is_file():
        second = {r["source_id"]: r for r in json.loads(
            inp.families_second_pass.read_text(encoding="utf-8"))["rows"]}
    lic_source: dict[str, str] = {}
    for c in inp.companions:
        p = repo / c
        if p.is_file():
            for r in json.loads(p.read_text(encoding="utf-8"))["repositories"]:
                lic_source.setdefault(r["repository"], r.get("license_source", ""))
    passrows = {r["key"]: r for r in _load_jsonl(
        inp.corpus_run / inp.current_pass / "results" / "store_verification.jsonl")}
    laterrows = {}
    if inp.later_pass:
        laterrows = {r["source"]: r for r in _load_jsonl(
            inp.corpus_run / inp.later_pass / "results" / "store_verification.jsonl")}
    tangent_tol = _tangent_tolerance(repo / inp.verifier)

    # overlap with curated derivative evidence, by code identity
    from umat_oti.corpus.identity import content_identity
    ps_ids: dict[str, str] = {}
    for f in sorted((repo / inp.param_sens_models).glob("*/umat.for")):
        i = content_identity(f)
        ps_ids[i.content_sha256] = f.parent.name
        ps_ids[i.code_only_sha256] = f.parent.name
    ij_ids: dict[str, dict] = {}
    ij_path = repo / inp.internal_jacobian_round
    if ij_path.is_file():
        for r in json.loads(ij_path.read_text(encoding="utf-8"))["records"]:
            idn = r.get("identity") or {}
            for k in ("code_only_sha256", "normalised_content_sha256"):
                if idn.get(k):
                    ij_ids[idn[k]] = r

    pass_file = f"corpus_run:{inp.current_pass}/results/store_verification.jsonl"
    rows: list[dict] = []
    for rec in records:
        rows.append(_acquired_row(rec, inp, triage.get(rec["source_id"]),
                                  b3.get(rec["source_id"]),
                                  families.get(rec["source_id"]),
                                  second.get(rec["source_id"]),
                                  lic_source, passrows.get(rec.get("key") or ""),
                                  laterrows.get(rec["source_id"]), pass_file,
                                  tangent_tol, ps_ids, ij_ids, content_identity))
    disc_rows, disc_census = _discovered_rows(inp, {r["source_id"] for r in records})
    rows.extend(disc_rows)

    inputs = {}
    for label, path in (("registry", repo / inp.registry), ("triage", repo / inp.triage),
                        ("discovered", repo / inp.discovered),
                        ("families", inp.families),
                        ("families_second_pass", inp.families_second_pass),
                        ("families_reporting", inp.families_reporting),
                        ("current_pass", inp.corpus_run / inp.current_pass / "results"
                         / "store_verification.jsonl"),
                        ("later_pass", inp.corpus_run / (inp.later_pass or "") / "results"
                         / "store_verification.jsonl"),
                        ("param_sens_round", repo / inp.param_sens_round),
                        ("internal_jacobian_round", ij_path),
                        ("verifier", repo / inp.verifier)):
        if path is not None and Path(path).is_file():
            inputs[label] = {"path": str(path), "sha256": _sha256(Path(path))}
    manifest = {
        "schema": SCHEMA_ID,
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "what_this_is": "one row per acquired corpus source plus one per "
                        "discovered-but-not-acquired candidate; every pipeline "
                        "stage and feature cell carries a status, a reason and an "
                        "evidence locator. Skipped never counts as verified.",
        "roots": portable_roots(inp.roots()),
        "inputs": inputs,
        "registry_fingerprint": records[0].get("verification_fingerprint", "")
        if records else "",
        "statuses": list(STATUSES),
        "stage_definitions": STAGE_DEFINITIONS,
        "feature_definitions": FEATURE_DEFINITIONS,
        "tolerances": {"ddsdde_relative": tangent_tol,
                       "ddsdde_source": f"repo:{inp.verifier}:TANGENT_TOLERANCE"},
        "family_classification": {
            "used": FAMILY_CLASSIFICATION,
            "reported_column": "model.family.family (fine) and "
                               "model.family.reporting_family (the eight D-11 "
                               "families; CSV family / family_reported)",
            "reporting_file": str(inp.families_reporting or ""),
            "fallback_file": str(inp.families),
            "secondary": "model.family.E: Agent E's classification "
                         "(material_families_checked_E.json), shown for comparison "
                         "and never used for family figures (CSV family_E)",
            "why": "decision D-11 (2026-10-01): family figures are reported against "
                   "Scout's B3 code-evidence classification, column S1; the second "
                   "pass (Vera, 2026-09-30) is carried per row under E as "
                   "`second_pass`",
            "second_pass": str(inp.families_second_pass or ""),
            "keyword_file_not_used": "corpus_run/material_families.json"},
        "discovery_census": disc_census,
        "rows": rows,
    }
    manifest["summary"] = summarise(manifest)
    manifest["summary"]["denominators_note"] = denominators_note(rows, inp, registry)
    manifest["data_quality"] = _data_quality(manifest, registry)
    return manifest


def origins_of(rec: Mapping) -> dict:
    """The registry's D-19/D-21 origin columns of one record, as the
    manifest's ``origins`` block. A registry built before the columns
    existed gives the empty values: no origin is inferred here."""
    def _text(name: str) -> str:
        return str(rec.get(name) or "")

    def _flag(name: str):
        value = rec.get(name)
        return value if isinstance(value, bool) else None
    coverage = rec.get("branch_coverage") or None
    if isinstance(coverage, str):
        try:
            coverage = json.loads(coverage)
        except ValueError:
            coverage = {"stated": coverage}
    interpreted = rec.get("interpreted_constants")
    return {
        "material_data_origin": _text("material_data_origin"),
        "experiment_origin": _text("experiment_origin"),
        "material_data_ref": _text("material_data_ref"),
        "council_deck_ref": _text("council_deck_ref"),
        "council_fingerprint": _text("council_fingerprint"),
        "refusal_kind": _text("refusal_kind"),
        "harvest_confidence": _text("harvest_confidence"),
        "interpreted_constants": interpreted if isinstance(interpreted, int) else None,
        "council_sets": [x for x in _text("council_sets").split(";") if x],
        "vera_accepted_template": _flag("vera_accepted_template"),
        "vera_accepted_instance": _flag("vera_accepted_instance"),
        "branch_coverage": coverage,
        "domain_not_enforced": _text("domain_not_enforced"),
        "pairing_changed": _flag("pairing_changed"),
        "licence_hold": _text("licence_hold"),
        "tier": _text("adequacy_tier"),
        "tier_basis": _text("adequacy_tier_basis"),
        "counted_in_tier": _flag("counted_in_tier"),
        "not_counted_in_tier_reason": _text("not_counted_in_tier_reason"),
    }


def _acquired_row(rec, inp, tri, b3, fam, fam2, lic_source, p, later, pass_file,
                  tangent_tol, ps_ids, ij_ids, content_identity) -> dict:
    sid = rec["source_id"]
    cache_path = inp.discovery_cache / rec["cache_path"]
    dq: list[str] = []
    on_disk = cache_path.is_file()
    sha = _sha256(cache_path) if on_disk else None
    nbytes = cache_path.stat().st_size if on_disk else None
    if not on_disk:
        dq.append("cache_file_missing")
    elif sha != rec["sha256"]:
        dq.append("sha256_mismatch_registry_vs_cache")
    if on_disk and nbytes != rec.get("bytes"):
        dq.append("registry_bytes_differs_from_file_size")
    ident = content_identity(cache_path, entry_routine=rec.get("entry_routine") or "UMAT") \
        if on_disk else None
    repo_name = rec["repository"]
    owner_repo = sid.split("/", 1)[0]
    path_in_repo = sid.split("/", 1)[1] if "/" in sid else sid
    lic = redistribution_policy(rec.get("license_spdx"),
                                _licence_file(inp.discovery_cache, owner_repo),
                                metadata_source=lic_source.get(owner_repo, ""))
    lic["scope"] = "repository"
    if lic["licence_file"] and lic["spdx_metadata"] and \
            lic["licence_file"]["detected_spdx"] and \
            lic["licence_file"]["detected_spdx"].upper() != lic["spdx_metadata"].upper():
        dq.append("licence_file_text_differs_from_registry_spdx")
    url = rec.get("acquisition_url", "")
    retrieval = {
        "url": url, "commit": rec.get("commit", ""), "path": path_in_repo,
        "sha256": rec["sha256"],
        "instructions": (f"git clone https://github.com/{repo_name}.git && "
                         f"git -C {repo_name.split('/')[-1]} checkout {rec.get('commit', '')}"
                         f" && sha256sum '{path_in_repo}'  # expect {rec['sha256']}")
        if "/" in repo_name else
        f"fetch {url} and check sha256 {rec['sha256']}",
    }

    # ---- closure scan
    reg_companions = [c.strip() for c in (rec.get("companion_files") or "").split(";")
                      if c.strip()]
    companions, resolver_missing = _resolve_companions(cache_path, inp.discovery_cache)
    if companions is None:
        companions = reg_companions
        dq.append("companion_resolution_failed_used_registry_list")
    else:
        full, reg = "; ".join(companions), rec.get("companion_files") or ""
        if reg != full:
            dq.append("registry_companion_files_truncated"
                      if len(reg) < len(full) and full.startswith(reg)
                      else "registry_companions_differ_from_resolver")
    paths = [cache_path] + [inp.discovery_cache / c for c in companions]
    forms = [rec.get("source_form") or "fixed"] + [
        "free" if c.lower().endswith((".f90", ".f95", ".f03", ".f08")) else
        "fixed" for c in companions]
    scan = scan_sources([p_ for p_ in paths if p_.is_file()],
                        [f for p_, f in zip(paths, forms) if p_.is_file()])
    # files INCLUDEd from beside the source are part of the closure: rescan
    # with them so their routines and modules count as defined.
    extra = []
    for name in dict.fromkeys(scan.includes):
        f = cache_path.parent / name
        if name.upper() not in _ABAQUS_HEADERS and f.is_file() and f not in paths:
            extra.append(f)
    if extra:
        paths = paths + extra
        forms = forms + [forms[0]] * len(extra)
        scan = scan_sources([p_ for p_ in paths if p_.is_file()],
                            [f for p_, f in zip(paths, forms) if p_.is_file()])
    missing_companion_files = [c for c in companions
                               if not (inp.discovery_cache / c).is_file()]
    if missing_companion_files:
        dq.append("companion_listed_but_not_in_cache")
    externals = sorted(scan.calls - scan.defined)
    ext_list = [{"name": n, "class": _classify_external(n)} for n in externals]
    modules = [{"name": m, "defined_in_closure": m in scan.modules_defined,
                "intrinsic_or_vendor": m in _INTRINSIC_MODULES}
               for m in sorted(scan.uses)]
    includes = []
    src_dir = cache_path.parent
    for name in dict.fromkeys(scan.includes):
        if name.upper() in _ABAQUS_HEADERS:
            where = "abaqus_installation"
        elif (src_dir / name).is_file():
            where = "published_beside_source"
        elif name.lower() == "mpif.h":
            where = "mpi_installation"
        else:
            where = "not_found_in_cache"
        includes.append({"name": name, "resolved": where})
    preprocessor = bool(scan.preprocessor)
    compiler = {
        "source_form": rec.get("source_form") or "",
        "suffix": cache_path.suffix,
        "preprocessor_required": preprocessor,
        "preprocessor_directives": sorted(set(scan.preprocessor)),
        "suffix_requests_preprocessing": cache_path.suffix in (".F", ".F90", ".FOR"),
        "extensions": scan.extensions,
        "openmp_directives": scan.openmp,
        "abaqus_header_required": any(i["resolved"] == "abaqus_installation"
                                      for i in includes),
        "offline_compile_defect": rec.get("compile_defect") or "",
        "basis": "inferred from the published text (logical lines, comments "
                 "removed); not a compile result",
    }

    # ---- interface
    pr = p or {}
    measured_modes: dict[str, str] = {}
    orig_ok = bool((pr.get("original") or {}).get("completed"))
    if orig_ok:
        el = pr.get("element_type") or ""
        mode = _mode_of(el)
        if mode:
            measured_modes[mode] = (f"original ran to completion in Abaqus on {el} "
                                    f"with NTENS={pr.get('ntens')} ({pass_file}#key="
                                    f"{rec.get('key')})")
    branch_values = {(v, op, n) for v, op, n in scan.dim_branches}
    ntens_eq = {n for v, op, n in branch_values if v == "NTENS" and op in (".EQ.", "==")}
    ndi_eq = {n for v, op, n in branch_values if v == "NDI" and op in (".EQ.", "==")}
    form_block = pr.get("formulation") if isinstance(pr.get("formulation"), dict) else {}
    deck_elements = [e for e in (form_block.get("deck_elements") or []) if e]
    deck_modes = {_mode_of(e): e for e in deck_elements if _mode_of(e)}
    deck_prov = form_block.get("provenance") or rec.get("deck") or ""
    dims = {}
    for mode, nt in _MODE_NTENS.items():
        if mode in measured_modes:
            dims[mode] = {"support": "supported", "basis": "measured",
                          "evidence_kind": "abaqus_run", "evidence": measured_modes[mode]}
        elif mode in deck_modes:
            dims[mode] = {"support": "supported", "basis": "inferred",
                          "evidence_kind": "author_deck",
                          "evidence": f"author's deck assigns this material to "
                                      f"{deck_modes[mode]}: {deck_prov}"}
        elif nt in ntens_eq or (mode == "plane_stress" and 2 in ndi_eq):
            dims[mode] = {"support": "supported", "basis": "inferred",
                          "evidence_kind": "source_branch",
                          "evidence": "source branches on " + ", ".join(
                              f"{v}{op}{n}" for v, op, n in sorted(branch_values))}
        elif scan.hard_six and mode != "three_d":
            dims[mode] = {"support": "not_supported", "basis": "inferred",
                          "evidence_kind": "source_array_shape",
                          "evidence": "arguments dimensioned for 6 components: "
                                      + ", ".join(scan.hard_six)}
        elif scan.hard_six and mode == "three_d":
            dims[mode] = {"support": "supported", "basis": "inferred",
                          "evidence_kind": "source_array_shape",
                          "evidence": "arguments dimensioned for 6 components: "
                                      + ", ".join(scan.hard_six)}
        else:
            dims[mode] = {"support": "unknown", "basis": "inferred",
                          "evidence_kind": "none",
                          "evidence": "no run, deck, branch or fixed shape decides it"}
    for mode in ("cohesive", "shell", "membrane"):
        if mode in measured_modes or mode in deck_modes:
            dims[mode] = {"support": "supported",
                          "basis": "measured" if mode in measured_modes else "inferred",
                          "evidence_kind": "abaqus_run" if mode in measured_modes
                          else "author_deck",
                          "evidence": measured_modes.get(mode) or
                          f"author's deck uses {deck_modes.get(mode)}: {deck_prov}"}
    reads = scan.reads_tokens
    if reads.get("DFGRD1") and reads.get("DSTRAN"):
        measure = "deformation_gradient_and_strain_increment"
    elif reads.get("DFGRD1") or reads.get("DFGRD0"):
        measure = "deformation_gradient"
    elif reads.get("DSTRAN") or reads.get("STRAN"):
        measure = "strain_increment"
    else:
        measure = "neither_read"
    kprov = pr.get("kinematics_provenance") or ""
    if re.search(r"nlgeom\s*=\s*yes", kprov, re.IGNORECASE):
        nlgeom = "yes"
    elif "NLGEOM=NO" in kprov.upper():
        nlgeom = "no"
    else:
        nlgeom = "unknown"
    manifest_block = ((pr.get("experiment") or {}).get("manifest")
                      or pr.get("manifest") or {})
    init_statev = manifest_block.get("initial_statev") or []
    state_req = []
    if scan.sdvini_defined:
        state_req.append("SDVINI defined in the closure (*INITIAL CONDITIONS, "
                         "TYPE=SOLUTION, USER)")
    if init_statev:
        state_req.append("deck supplies nonzero initial STATEV")
    if manifest_block.get("initial_state_from_user_subroutine"):
        state_req.append("verification manifest initialises state from a user "
                         "subroutine")
    if scan.first_increment_branch:
        state_req.append("source branches on KINC/KSTEP == 1 (likely self-"
                         "initialisation; inferred)")
    if scan.data_files:
        state_req.append("source OPENs files at run time")
    if scan.data_files_absolute:
        state_req.append("source OPENs a file at the author's absolute path: "
                         + "; ".join(sorted(set(scan.data_files_absolute))))
    props_count = rec.get("props_count")
    nstatv = rec.get("nstatv")
    if scan.props_max and props_count and scan.props_max > props_count:
        dq.append("source_indexes_props_beyond_deck_count")
    interface = {
        "ntens_measured": [pr.get("ntens")] if orig_ok and pr.get("ntens") else [],
        "element_measured": (pr.get("element_type") or "") if orig_ok else "",
        "elements_in_author_deck": deck_elements,
        "ntens_registry": rec.get("ntens"),
        "ntens_triage_hint": (tri or {}).get("ntens"),
        "dimension_branches_in_source": [f"{v}{op}{n}" for v, op, n in
                                         sorted(branch_values)],
        "fixed_six_component_arguments": scan.hard_six,
        "dimensionality": dims,
        "strain_formulation": {
            "reads": {t: reads.get(t, False) for t in
                      ("DSTRAN", "STRAN", "DFGRD0", "DFGRD1", "DROT")},
            "measure": measure,
            "log_strain_mentioned": scan.log_strain_hint,
            "registry_kinematics": rec.get("kinematics") or "",
            "nlgeom": nlgeom,
            "nlgeom_evidence": kprov,
            "basis": "reads inferred from executable statements of the published "
                     "text; nlgeom read from the author's deck by the verification "
                     "pass",
        },
        "other_inputs_read": {t: reads.get(t, False) for t in
                              ("TIME", "DTIME", "COORDS", "TEMP", "DTEMP", "PNEWDT",
                               "CELENT")},
        "props": {"count": props_count,
                  "provenance": rec.get("material_provenance") or
                  ("no published material constants" if not props_count else ""),
                  "max_literal_index_in_source": scan.props_max},
        "nstatv": {"count": nstatv,
                   "provenance": rec.get("material_provenance") or "",
                   "max_literal_index_in_source": scan.statev_max,
                   "triage_hint": (tri or {}).get("nstatv_hint")},
        "state_initialisation": {
            "sdvini_defined": scan.sdvini_defined,
            "deck_initial_statev": bool(init_statev) if p else None,
            "first_increment_branch": scan.first_increment_branch,
            "reads_files": bool(scan.data_files),
            "requirements": state_req or ["none found"],
        },
    }

    # ---- family: reported = D-11 S1; E kept as a labelled secondary
    if fam:
        e_block = {
            "family": fam.get("family", ""),
            "review": "agent_reviewed_code_evidence" if fam.get("review") == "checked"
            else "keyword_only",
            "reviewed_by": "Agent E" if fam.get("review") == "checked" else "",
            "basis": fam.get("basis", ""),
            "keyword_family": fam.get("keyword_family", ""),
            "source_file": "families:" + inp.families.name,
        }
    else:
        e_block = {"family": "", "review": "missing", "reviewed_by": "", "basis": "",
                   "keyword_family": "", "source_file": "families:" + inp.families.name}
        dq.append("no_family_row")
    e_block["label"] = "secondary (Agent E); not used for family figures"
    rep = reported_family(rec["source_id"], b3, fam)
    if b3:
        review, reviewed_by = "agent_reviewed_code_evidence", "Scout (B3)"
        basis = "; ".join(x for x in (b3.get("rule", ""), b3.get("notes", "")) if x)
    else:
        review, reviewed_by, basis = e_block["review"], e_block["reviewed_by"], \
            e_block["basis"]
    family = {**rep, "classification": "D-11 S1", "review": review,
              "human_reviewed": False, "reviewed_by": reviewed_by,
              "basis": basis[:1500], "E": e_block}
    if fam2:
        e_block["second_pass"] = {
            "family": fam2.get("family", ""), "reviewed_by": fam2.get("reviewed_by", ""),
            "agrees": fam2.get("family", "") == e_block["family"],
            "basis": fam2.get("basis", "") if fam2.get("family") != e_block["family"] else "",
            "file": "families:" + (inp.families_second_pass.name
                                   if inp.families_second_pass else "")}
    else:
        e_block["second_pass"] = None

    # ---- pipeline
    key = rec.get("key") or ""
    ev_pass = f"{pass_file}#key={key}" if key else ""
    store_ev = f"transform_store:{key}/transform_report.json" if key else ""
    kind = rec.get("kind")
    ts = rec.get("terminal_state")
    stages: dict[str, dict] = {}
    stages["discovered"] = _cell(
        "verified", "listed in the discovery inventory and acquired",
        f"repo:{inp.triage}#source={sid}")
    if not rec.get("is_umat"):
        stages["eligible"] = _cell("not_applicable",
                                   "not a UMAT: " + (rec.get("classification_basis") or ""),
                                   f"repo:{inp.registry}#source_id={sid}")
    elif rec.get("adequately_specified"):
        stages["eligible"] = _cell("verified", "adequately specified genuine UMAT (D2)",
                                   f"repo:{inp.registry}#source_id={sid}")
    elif rec.get("adequacy_kind") == "duplicate":
        stages["eligible"] = _cell("not_applicable",
                                   f"duplicate of {rec.get('duplicate_of')}: "
                                   + (rec.get("adequacy_basis") or ""),
                                   f"repo:{inp.registry}#source_id={sid}")
    else:
        stages["eligible"] = _cell("blocked", rec.get("adequacy_basis") or "not adequate",
                                   f"repo:{inp.registry}#source_id={sid}")
    stages["attempted"] = (_cell("verified", "selected by transform-all",
                                 f"corpus_run:transform_all_{inp.current_pass}.json")
                           if rec.get("attempted") else
                           _cell("not_attempted", "not selected by transform-all"))
    if rec.get("transformed"):
        stages["transformed"] = _cell("verified", "OTI source generated", store_ev)
    else:
        reason = rec.get("reason") or ""
        if not rec.get("is_umat"):
            st = "not_applicable"
        elif kind == _EXTERNAL:
            st = "blocked"
        else:
            st = "unsupported"
        stages["transformed"] = _cell(st, f"{ts}: {reason}",
                                      f"corpus_run:transform_all_{inp.current_pass}.json"
                                      f"#source={sid}")
    # compile layouts
    layouts: dict[str, dict] = {}
    if rec.get("transformed"):
        if rec.get("compiled") is True:
            layouts["offline_gfortran_store"] = _cell(
                "verified", "transform store build compiled (compile_hint.sh)", store_ev)
        elif rec.get("compiled") is False:
            layouts["offline_gfortran_store"] = _cell(
                "failed", rec.get("compile_defect") or "store build did not compile",
                store_ev)
        else:
            layouts["offline_gfortran_store"] = _cell(
                "not_attempted", "registry records no compile result", store_ev)
        sup = pr.get("support") or {}
        tblock = pr.get("transformed") or {}
        if tblock.get("completed"):
            layouts["abaqus_ifort_job"] = _cell(
                "verified", "Abaqus built and ran the OTI job (ifort, Abaqus's "
                "own compile line)", ev_pass)
        elif pr.get("stage") == "support_build_failed" or sup.get("ok") is False:
            layouts["abaqus_ifort_job"] = _cell(
                "failed", sup.get("reason") or pr.get("reason") or "", ev_pass)
        elif tblock:
            layouts["abaqus_ifort_job"] = _cell(
                "failed", "transformed job did not complete: "
                + "; ".join(tblock.get("reasons") or []) or pr.get("reason", ""),
                ev_pass)
        else:
            layouts["abaqus_ifort_job"] = _cell(
                "not_attempted", f"no Abaqus OTI job in {inp.current_pass}"
                + (f" (stage {pr.get('stage')})" if pr else ""), ev_pass)
        lst = [c["status"] for c in layouts.values()]
        if "verified" in lst:
            ok = [k for k, c in layouts.items() if c["status"] == "verified"]
            stages["compiled"] = _cell("verified", "compiled in: " + ", ".join(ok),
                                       layouts[ok[0]]["evidence"], layouts=layouts)
        elif "failed" in lst:
            bad = [k for k, c in layouts.items() if c["status"] == "failed"]
            stages["compiled"] = _cell("failed", "; ".join(
                f"{k}: {layouts[k]['reason']}" for k in bad)[:2000],
                layouts[bad[0]]["evidence"], layouts=layouts)
        else:
            stages["compiled"] = _cell("not_attempted", "no compile result",
                                       store_ev, layouts=layouts)
        if rec.get("compiled") is False and (pr.get("original") or {}).get("completed"):
            dq.append("registry_compiled_false_but_abaqus_jobs_ran")
    else:
        stages["compiled"] = {**_inherit("transformed", stages["transformed"]),
                              "layouts": {}}
    # original executed
    o = pr.get("original")
    pstage = pr.get("stage")
    if o and o.get("completed"):
        stages["original_executed"] = _cell(
            "verified", f"original job completed ({o.get('increments')} increments)",
            ev_pass)
    elif o:
        st = "blocked" if kind == _EXTERNAL else "failed"
        stages["original_executed"] = _cell(st, pr.get("reason") or "original job "
                                            "did not complete", ev_pass)
    elif p:
        mp = {"needs_material_data": "blocked", "not_a_umat": "not_applicable",
              "incomplete_or_corrupt_source": "blocked"}
        if pstage in mp:
            st = mp[pstage]
        elif pstage == "manifest_refused":
            st = "unsupported" if ts == "unsupported_formulation" else "blocked"
        elif pstage == "support_build_failed":
            st = "failed"
        else:
            st = "not_attempted"
        stages["original_executed"] = _cell(st, f"{pstage}: {pr.get('reason', '')}",
                                            ev_pass)
    else:
        stages["original_executed"] = _inherit("compiled", stages["compiled"])
    t = pr.get("transformed")
    if t and t.get("completed"):
        stages["oti_executed"] = _cell(
            "verified", f"OTI job completed ({t.get('increments')} increments)", ev_pass)
    elif t:
        st = "blocked" if kind == _EXTERNAL else "failed"
        stages["oti_executed"] = _cell(st, pr.get("reason") or "transformed job did "
                                       "not complete", ev_pass)
    else:
        stages["oti_executed"] = _inherit("original_executed",
                                          stages["original_executed"])
    ev = pr.get("evidence")
    if ev:
        if ev.get("primal_agreed") is True:
            stages["primal_agreed"] = _cell("verified", "gate primal_agreed=true",
                                            ev_pass)
        elif ev.get("primal_agreed") is False:
            # failed only on a measured disagreement; a process failure or an
            # undefined original is labelled as such (primal_gate_verdict)
            v = primal_gate_verdict(pr, ev, inp.current_pass)
            st = v["status"] if v["status"] != "verified" else "inconclusive"
            stages["primal_agreed"] = _cell(
                st, f"gate primal_agreed=false ({ts}): "
                + (v.get("reason") or pr.get("reason") or "")[:1500], ev_pass,
                **({"process_failure": v["process_failure"]}
                   if v.get("process_failure") else {}))
        else:
            stages["primal_agreed"] = _cell("not_attempted",
                                            "gate primal_agreed not established", ev_pass)
    else:
        stages["primal_agreed"] = _inherit("oti_executed", stages["oti_executed"])

    # ---- features
    feats = _features(rec, pr, ev, stages, ev_pass, tangent_tol, ident, ps_ids,
                      ij_ids, inp)
    legacy_gate = feats.pop("_legacy")

    # ---- cross-source consistency
    if p:
        if p.get("source_sha256") and p["source_sha256"] != rec["sha256"]:
            dq.append("pass_sha256_differs_from_registry")
        for fld in ("ntens", "nstatv", "props_count"):
            if p.get(fld) is not None and rec.get(fld) is not None and p[fld] != rec[fld]:
                dq.append(f"registry_{fld}_differs_from_{inp.current_pass}")
        regstage = rec.get("stage") or ""
        if regstage and regstage != p.get("stage"):
            dq.append(f"registry_stage_differs_from_{inp.current_pass}")
    if tri and tri.get("ntens") and rec.get("ntens") and tri["ntens"] != rec["ntens"]:
        dq.append("triage_ntens_hint_differs_from_registry")
    if tri and tri.get("kinematics") and rec.get("kinematics") and \
            tri["kinematics"] != rec["kinematics"]:
        dq.append("triage_kinematics_differs_from_registry")
    if bool(tri and tri.get("compiled") == "yes") != bool(rec.get("compiled")) and tri:
        dq.append("triage_compiled_differs_from_registry")
    later_info = None
    if later is not None:
        later_info = {"stage": later.get("stage"),
                      "fingerprint": later.get("fingerprint"),
                      "agrees_with_current": later.get("stage") == pr.get("stage")}
        if p and later.get("stage") != pr.get("stage"):
            dq.append(f"{inp.later_pass}_stage_differs_from_{inp.current_pass}")

    return {
        "row_kind": "acquired",
        "source_id": sid,
        "repository": repo_name,
        "path_in_repository": path_in_repo,
        "url": url,
        "url_provenance": rec.get("url_provenance", ""),
        "commit": rec.get("commit", ""),
        "cache_path": f"discovery_cache:{rec['cache_path']}",
        "sha256": {"registry": rec["sha256"], "recomputed": sha,
                   "agrees": (sha == rec["sha256"]) if sha else None,
                   "normalised_content_sha256": ident.content_sha256 if ident else None,
                   "code_only_sha256": ident.code_only_sha256 if ident else None},
        "bytes": {"on_disk": nbytes, "registry": rec.get("bytes"),
                  "agrees": nbytes == rec.get("bytes") if nbytes is not None else None},
        "license": lic,
        "retrieval": retrieval,
        "model": {
            "family": family,
            "entry_point": {"routine": rec.get("entry_routine", ""),
                            "interface": rec.get("entry_interface", ""),
                            "line": rec.get("entry_line"),
                            "evidence": rec.get("entry_evidence", ""),
                            "is_umat": rec.get("is_umat")},
            "required_files": {
                "companions": companions,
                "missing_companions": [m.strip() for m in
                                       (rec.get("missing_companions") or "").split(";")
                                       if m.strip()],
                "unresolved_by_resolver": resolver_missing,
                "includes": includes,
                "data_files": sorted(set(scan.data_files)),
                "data_files_at_absolute_paths": sorted(set(scan.data_files_absolute)),
            },
            "external_routines": ext_list,
            "modules_used": modules,
            "compiler_requirements": compiler,
        },
        "interface": interface,
        "registry": {"terminal_state": ts, "kind": kind,
                     "stage": rec.get("stage", ""), "key": key,
                     # The gate a later stage can hide (Vera B10 pass21):
                     # routine-level counting requires it to read "true".
                     "gate_mechanically_informative":
                         rec.get("gate_mechanically_informative", ""),
                     "informative_gate_hidden": _informative_gate_hidden(rec),
                     "source_ruling": rec.get("source_ruling", ""),
                     "source_ruling_evidence": rec.get("source_ruling_evidence", ""),
                     "verified_on_every_gate": rec.get("verified_on_every_gate"),
                     "tangent_verdict": tangent_verdict(pr.get("tangent"))
                     or str(rec.get("tangent_verdict") or ""),
                     "verification_fingerprint": rec.get("verification_fingerprint", "")},
        "origins": origins_of(rec),
        "pipeline": stages,
        "features": feats,
        "features_other_builds": {b: {} for b in OTHER_BUILDS},
        "ddsdde_legacy_gate": legacy_gate,
        "later_pass": later_info,
        "data_quality": sorted(set(dq)),
    }


def _resolve_companions(source: Path, cache: Path):
    """Full companion closure (the registry's string is cut at 500 chars)."""
    try:
        from umat_oti.abaqus.companions import repository_files, resolve
        res = resolve(source, repository_files(source, cache))
    except Exception:            # noqa: BLE001 - recorded as data quality
        return None, []
    order = [str(Path(u).relative_to(cache)) for u in res.order]
    missing = ([f"module {m}" for m in getattr(res, "missing_modules", []) or []]
               + [f"include {i}" for i in getattr(res, "missing_includes", []) or []])
    return order, sorted(set(missing))


_LICENCE_CACHE: dict[str, dict | None] = {}


def _licence_file(cache: Path, repo_dir_name: str) -> dict | None:
    """Locator and detected SPDX of the cached root licence file, if any."""
    key = str(cache / repo_dir_name)
    if key not in _LICENCE_CACHE:
        f = find_licence_file(cache / repo_dir_name)
        _LICENCE_CACHE[key] = None if f is None else {
            "path": f"discovery_cache:{repo_dir_name}/{f.name}",
            "detected_spdx": detect_licence_text(
                f.read_bytes().decode("utf-8", errors="replace")),
            "sha256": _sha256(f)}
    return _LICENCE_CACHE[key]


#: The three answers a pass's Abaqus tangent gate can give one row (Vera's
#: final review before pass21). ``failed`` only where a judgement measured a
#: disagreement (the D-4 gate's ``tangent.failed``); ``unresolved`` where
#: nothing was verified and nothing was shown wrong -- including every row of
#: the pre-D-4 gate, which had no notion of a measured failure.
TANGENT_VERDICTS: tuple[str, ...] = ("verified", "failed", "unresolved")


def tangent_verdict(tangent: Any) -> str:
    """``verified`` / ``failed`` / ``unresolved`` from a pass row's ``tangent``
    block (``tangent.verified``, ``tangent.failed``); ``""`` where the row ran
    no tangent comparison. A measured failure wins over a verified flag."""
    if not isinstance(tangent, Mapping):
        return ""
    if tangent.get("failed") is True:
        return "failed"
    if tangent.get("verified") is True:
        return "verified"
    return "unresolved"


def is_d4_gate(tangent: Any) -> bool:
    """Whether the block came from the D-4 entrywise gate (G10 onward), which
    records ``failed``; the earlier gate never did."""
    return isinstance(tangent, Mapping) and "failed" in tangent


#: What the Abaqus tangent gate of a pass measures, from G10 on.
D4_ABAQUS_DDSDDE_RULE = (
    "tools/verify_store_in_abaqus.py tangent gate (G10, decision D-4): OTI DDSDDE "
    "vs a finite difference of the ORIGINAL routine with restored state at chosen "
    "states, FD-only plateau of >= 3 steps, entrywise tolerance; verdict verified / "
    "failed (a judgement measured a disagreement) / unresolved. Shown per row; the "
    "manifest's ddsdde feature cell is decided by the merged routine-level cells")

#: What the pass16 DDSDDE gate measured, and why it does not count.
LEGACY_DDSDDE_RULE = (
    "tools/verify_store_in_abaqus.py gate derivatives_verified: OTI DDSDDE vs a "
    "central difference of the original with restored state, plateau taken from "
    "the OTI-vs-FD error over the step ladder, relative tolerance TANGENT_TOLERANCE "
    "against the column; rejected by decision D-4 (needs an FD-only plateau of "
    ">= 3 steps and entrywise agreement) -- shown, never counted as verified")


def _json_num(x: Any) -> Any:
    """A number JSON can carry (inf/nan become their names as strings)."""
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    return x


def _not_attempted_feature(reason: str, evidence: str = "") -> dict:
    return {"status": "not_attempted", "reason": reason, "evidence": evidence,
            "reference": None, "max_error": None, "tolerance": None, "history": []}


#: Gate comparisons (``primal_gate.decided_by`` parts) and the pass-record key
#: holding each one's measurement.
_GATE_COMPARISONS = {"routine_level": "routine_primal",
                     "jacobian_matched": "jacobian_matched_primal"}


def _comparison_ratio(comp: Mapping, tol: float | None) -> float | None:
    """max(worst stress / its per-call bound, worst state relative / rtol);
    infinite when a non-finite mismatch was recorded."""
    if comp.get("non_finite_mismatches"):
        return math.inf
    parts = [comp.get("worst_stress_over_bound")]
    if comp.get("worst_state_relative") is not None and tol:
        parts.append(comp["worst_state_relative"] / tol)
    parts = [float(v) for v in parts
             if isinstance(v, (int, float)) and not isinstance(v, bool)
             and math.isfinite(v)]
    return max(parts) if parts else None


def _gate_comparison(pr: Mapping, name: str) -> dict:
    """What one gate comparison measured, and whether it measured anything.

    ``usable`` is true only for a comparison over at least one paired call of
    a job that completed; a comparison over zero calls ("not the same calls")
    or of an incomplete job measured nothing.
    """
    block = pr.get(_GATE_COMPARISONS[name]) or {}
    comp = block.get("comparison") or {}
    tol = comp.get("tolerance")
    usable = bool(comp) and (comp.get("calls") or 0) > 0 \
        and block.get("completed") is not False
    ratio = _comparison_ratio(comp, tol) if usable else None
    return {"ran": block.get("ran"), "completed": block.get("completed"),
            "agrees": block.get("agrees"), "usable": usable and ratio is not None,
            "ratio": _json_num(ratio),
            "calls": comp.get("calls"),
            "worst_stress_over_bound": _json_num(comp.get("worst_stress_over_bound")),
            "worst_state_relative": _json_num(comp.get("worst_state_relative")),
            "non_finite_mismatches": comp.get("non_finite_mismatches"),
            "tolerance": tol,
            "bound_over_max_sigma": _json_num(comp.get("bound_over_max_sigma")),
            "reason": (comp.get("reason") or block.get("reason") or "")[:600]}


def _undefined_outputs(u: Mapping) -> list[str]:
    und = (u or {}).get("undefined") or {}
    out = []
    for arr in ("STRESS", "DDSDDE", "STATEV"):
        out += [f"{arr}({i})" for i in und.get(arr) or []]
    return out


def _fe_informational(pr: Mapping, ptol: float | None) -> dict | None:
    primal = pr.get("primal") or {}
    if not primal:
        return None
    return {"what": "the FE-level history comparison of the pass; informational "
                    "since D-15 (two FE solves steered by different Jacobians), "
                    "never the verdict's measure",
            "agrees": primal.get("agrees"),
            "worst_stress_relative": _json_num(primal.get("worst_stress_relative")),
            "worst_state_relative": _json_num(primal.get("worst_state_relative")),
            "non_finite_original": primal.get("non_finite_original"),
            "non_finite_transformed": primal.get("non_finite_transformed"),
            "primal_tolerance_relative": ptol}


def primal_gate_verdict(pr: Mapping, ev: Mapping, pass_name: str = "") -> dict:
    """The ``primal_stress_state`` cell of one pass record (without evidence/build).

    Since D-15 the verdict is the Abaqus primal gate (``pr["primal_gate"]``):
    the routine-level replay and, where it agreed, the Jacobian-matched FE
    control. ``max_error`` is the ratio of the comparison that DECIDED
    (``decided_by``), ``measured`` carries the gate's numbers, and the FE
    comparison appears only under ``measured.fe_comparison_informational``.

    * ``failed`` only when a deciding comparison measured paired calls and its
      ratio exceeds 1;
    * a process failure (Jacobian-matched job incomplete, no paired calls, no
      init build, replay that does not reproduce the solver) is
      ``inconclusive`` when some comparison was measured and ``not_attempted``
      when none was;
    * a record stopped by the D-12 init-build check is
      ``undefined_in_original`` (a source defect, never compared);
    * a gate that ran without the comparison it names is ``inconclusive``,
      never decided by the FE rule.

    Records that predate the gate (no ``primal_gate``, ``routine_primal`` or
    ``undefined_in_original``) keep the FE rule ``abaqus_primal_history_floor/1``.
    """
    primal = pr.get("primal") or {}
    manifest_block = ((pr.get("experiment") or {}).get("manifest")
                      or pr.get("manifest") or {})
    ptol = manifest_block.get("primal_tolerance", 1e-10)
    pg = pr.get("primal_gate")
    u = pr.get("undefined_in_original") or {}
    base = {"reference": "original", "tolerance": 1.0,
            "quantity": FEATURE_DEFINITIONS["primal_stress_state"]["quantity"],
            "scope": "history", "history": []}
    gates = {k: ev.get(k) for k in ("abaqus_job_completed", "complete_history_finite",
                                    "primal_agreed", "mechanically_informative")}
    fe = _fe_informational(pr, ptol)
    undefined = _undefined_outputs(u)

    # ---- D-12: the original is undefined on this history; nothing compared
    if not pg and u.get("established") and undefined:
        und = u.get("undefined") or {}
        return {**base, "status": "undefined_in_original",
                "reason": ("a source defect in the ORIGINAL, never compared -- "
                           + (pr.get("reason") or "undefined_in_original (D-12): "
                              + (u.get("reason") or "")))[:1500],
                "max_error": None, "tolerance": None, "tolerance_rule_id": None,
                "rtol": None, "decided_by": "undefined_in_original_check",
                "undefined_outputs": undefined,
                "stress_and_ddsdde_fully_defined": not (und.get("STRESS")
                                                        or und.get("DDSDDE")),
                "measured": {"decided_by": "undefined_in_original_check",
                             "init_variants": u.get("init_variants"),
                             "pair": u.get("pair"),
                             "fe_comparison_informational": fe}}

    # ---- pre-gate records: the FE history rule
    if not pg and not pr.get("routine_primal") and not u:
        worst = [v for v in (primal.get("worst_stress_relative"),
                             primal.get("worst_state_relative")) if v is not None]
        worst_v = max(worst) if worst else None
        ratio = (worst_v / ptol) if (worst_v is not None and ptol and
                                     math.isfinite(worst_v)) else None
        cell = {**base, "max_error": ratio,
                "tolerance_rule_id": "abaqus_primal_history_floor/1", "rtol": ptol,
                "decided_by": "fe_history",
                "measured": {"decided_by": "fe_history",
                             "worst_stress_relative": _json_num(
                                 primal.get("worst_stress_relative")),
                             "worst_state_relative": _json_num(
                                 primal.get("worst_state_relative")),
                             "non_finite_original": primal.get("non_finite_original"),
                             "non_finite_transformed": primal.get("non_finite_transformed"),
                             "primal_tolerance_relative": ptol}}
        if all(v is True for v in gates.values()):
            return {**cell, "status": "verified", "reason": "all primal gates true"}
        if gates["primal_agreed"] is True:
            bad = ", ".join(f"{k}={v}" for k, v in gates.items() if v is not True)
            return {**cell, "status": "inconclusive",
                    "reason": f"the builds agree but the run does not establish it: "
                              f"{bad} (agreement on a run that is not mechanically "
                              "informative is not a verification)"}
        if gates["primal_agreed"] is False:
            if primal.get("non_finite_original"):
                st, why = "inconclusive", ("the ORIGINAL build is non-finite on this "
                                           "deck, so the comparison carries no claim")
            elif primal.get("explained_by_operation_order"):
                st, why = "inconclusive", (
                    "the builds differ by no more than the original differs from "
                    "itself under reassociation, so the comparison cannot "
                    "discriminate")
            else:
                st, why = "failed", "the values disagree"
            return {**cell, "status": st, "values_disagree": st == "failed",
                    "reason": f"{why}: " + (pr.get("reason") or primal.get("reason")
                                            or "gate primal_agreed=false")[:1500]}
        return {**cell, "status": "not_attempted",
                "reason": f"gate primal_agreed not established ({pass_name} stage "
                          f"{pr.get('stage')})"}

    # ---- the D-15 gate
    pg = pg or {}
    decided_by = pg.get("decided_by") or ""
    comps = {n: _gate_comparison(pr, n) for n in _GATE_COMPARISONS}

    def r_of(n: str) -> float:
        x = comps[n]["ratio"]
        return math.inf if _is_inf(x) else float(x)
    tol = next((c["tolerance"] for c in comps.values() if c["tolerance"]), ptol)
    deciding = [n for n in decided_by.split("+") if n in comps]
    measured = {"decided_by": decided_by or None,
                **comps,
                "init_variants_established": pg.get("init_variants_established"),
                "stiffness_ulps": _json_num(pg.get("stiffness_ulps")),
                "bound_over_max_sigma": _json_num(pg.get("bound_over_max_sigma")),
                "undefined_outputs_excluded": pg.get("undefined_outputs_excluded") or [],
                "primal_tolerance_relative": tol,
                "fe_comparison_informational": fe}
    cell = {**base, "tolerance_rule_id": "routine_primal_gate/1", "rtol": tol,
            "decided_by": decided_by or None, "measured": measured}
    if pg.get("undefined_outputs_excluded"):
        cell["undefined_outputs"] = list(pg["undefined_outputs_excluded"])
    reason = (pr.get("reason") or "")[:1500]
    measured_any = any(c["usable"] for c in comps.values())

    def process(why: str, kind: str) -> dict:
        st = "inconclusive" if measured_any else "not_attempted"
        return {**cell, "status": st, "max_error": None, "process_failure": kind,
                "reason": f"{why}: {reason or 'no further detail recorded'}"[:1500]}

    if pg.get("agrees") is True:
        missing = [n for n in deciding if not comps[n]["usable"]] or \
            ([] if deciding else ["(decided_by names no comparison)"])
        if missing:
            return process("the primal gate agreed but its comparison "
                           f"{', '.join(missing)} is missing or measured no paired "
                           "calls, so the agreement is not established",
                           "gate_comparison_missing")
        ratio = max(r_of(n) for n in deciding)
        cell = {**cell, "max_error": _json_num(ratio)}
        if ratio > 1:
            return {**cell, "status": "inconclusive",
                    "reason": f"the gate reports agreement but {decided_by} measured "
                              f"a ratio of {ratio:.3g} > 1; not counted"}
        if all(v is True for v in gates.values()):
            return {**cell, "status": "verified",
                    "reason": f"primal gate agreed ({decided_by}); all primal gates true"}
        bad = ", ".join(f"{k}={v}" for k, v in gates.items() if v is not True)
        return {**cell, "status": "inconclusive",
                "reason": f"the builds agree but the run does not establish it: {bad} "
                          "(agreement on a run that is not mechanically informative "
                          "is not a verification)"}

    # the gate did not agree: failed only on a measured disagreement
    over = [n for n in deciding if comps[n]["usable"] and r_of(n) > 1]
    if over:
        ratio = max(r_of(n) for n in over)
        return {**cell, "status": "failed", "max_error": _json_num(ratio),
                "values_disagree": True, "decided_by": "+".join(over),
                "reason": f"the values disagree ({'+'.join(over)} ratio "
                          f"{ratio:.3g} > 1): {reason}"[:1500]}
    jm, rl = comps["jacobian_matched"], comps["routine_level"]
    if decided_by == "undefined_in_original_check" or \
            pg.get("init_variants_established") is False:
        return process("the D-12 init-build check could not be completed (no init "
                       "build set, or an init build stopped)", "no_init_build")
    if "jacobian_matched" in deciding and jm["completed"] is False:
        return process("the Jacobian-matched control job did not complete",
                       "jacobian_matched_job_incomplete")
    if "jacobian_matched" in deciding and jm["ran"] is False:
        return process("the Jacobian-matched control did not run",
                       "jacobian_matched_not_run")
    if any(n in deciding and not comps[n]["usable"] for n in comps):
        bad = [n for n in deciding if not comps[n]["usable"]]
        return process(f"{', '.join(bad)} measured no paired calls (the runs did "
                       "not walk the same calls)", "replay_mismatch")
    if not deciding:
        return process("the primal gate disagreed without naming a comparison it "
                       "measured", "gate_comparison_missing")
    return process(f"the gate disagreed but {decided_by} measured a ratio within "
                   "the bound", "gate_inconsistent")


def _features(rec, pr, ev, stages, ev_pass, tangent_tol, ident, ps_ids, ij_ids,
              inp) -> dict:
    out: dict[str, dict] = {}
    na = not rec.get("is_umat")

    def na_cell():
        return {"status": "not_applicable", "reason": "not a UMAT",
                "evidence": stages["eligible"]["evidence"], "reference": None,
                "max_error": None, "tolerance": None, "history": []}

    # primal -- failed only where the deciding comparison measured a
    # disagreement; see :func:`primal_gate_verdict`
    build = {"kind": "store",
             "fingerprint": rec.get("verification_fingerprint") or "",
             "sha256": "", "basis": "transform-store OTI source compiled by Abaqus "
                                    f"in {inp.current_pass}"}
    if ev:
        out["primal_stress_state"] = {**primal_gate_verdict(pr, ev, inp.current_pass),
                                      "evidence": ev_pass, "build": build}
    elif na:
        out["primal_stress_state"] = na_cell()
    else:
        up = stages["primal_agreed"]
        c = _inherit("primal_agreed", up) if up["status"] != "not_attempted" else up
        out["primal_stress_state"] = {**c, "reference": None, "max_error": None,
                                      "tolerance": None, "history": []}
    # ddsdde -- the pass's gate is legacy evidence (decision D-4), never verified
    tan = pr.get("tangent")
    verdict = tangent_verdict(tan) if tan else ""
    legacy = {"gate": "not_run", "counts_as_verified": False,
              "rule": D4_ABAQUS_DDSDDE_RULE if is_d4_gate(tan) else LEGACY_DDSDDE_RULE,
              "tangent_verdict": verdict, "reason": "", "evidence": "",
              "worst_relative": None, "tolerance_relative": None, "fd_steps": [],
              "states_checked": None, "states_agreeing": None,
              "primal_stress_state": out["primal_stress_state"]["status"]}
    if ev and tan:
        # the derived verdict, never "failed" for a row nothing showed wrong
        gate = {"verified": "passed", "failed": "failed"}.get(verdict, "unresolved")
        legacy.update(gate=gate, evidence=ev_pass,
                      reason=(tan.get("reason") or "derivatives_verified="
                              f"{ev.get('derivatives_verified')}")[:1500],
                      worst_relative=_json_num(rec.get("worst_tangent_relative")),
                      tolerance_relative=tangent_tol,
                      fd_steps=tan.get("fd_steps") or [],
                      states_checked=tan.get("states_checked"),
                      states_agreeing=tan.get("states_agreeing"),
                      wrt=tan.get("driven_through") or "strain increment")
        out["ddsdde"] = _not_attempted_feature(
            (f"no routine-level DDSDDE evidence has been merged; the {inp.current_pass} "
             f"Abaqus tangent gate (D-4, row field ddsdde_legacy_gate) reads "
             f"{verdict}, and the cell is decided by the merged routine-level cells")
            if is_d4_gate(tan) else
            ("no D-4-compliant DDSDDE evidence has been merged; the "
             f"{inp.current_pass} gate derivatives_verified {gate} "
             "(row field ddsdde_legacy_gate) uses the legacy OTI-vs-FD plateau "
             "rule that decision D-4 rejects, so it is not counted"), ev_pass)
    elif ev:
        legacy["reason"] = f"no tangent comparison was run (stopped at {pr.get('stage')})"
        out["ddsdde"] = _not_attempted_feature(
            f"no tangent comparison was run (stopped at {pr.get('stage')})", ev_pass)
    elif na:
        legacy["reason"] = "not a UMAT"
        out["ddsdde"] = na_cell()
    else:
        up = stages["primal_agreed"]
        c = _inherit("primal_agreed", up)
        legacy["reason"] = c["reason"]
        out["ddsdde"] = {**c, "reference": None, "max_error": None, "tolerance": None,
                         "history": []}
    out["_legacy"] = legacy
    # curated evidence overlap
    ps_hit = ij_hit = None
    if ident:
        ps_hit = ps_ids.get(ident.code_only_sha256) or ps_ids.get(ident.content_sha256)
        ij_hit = ij_ids.get(ident.code_only_sha256) or ij_ids.get(ident.content_sha256)
    ij_reason = ("no corpus source matches a source of the internal-Jacobian round "
                 "(compared by normalised-content and code-only SHA-256)")
    if ij_hit:
        ij_reason = (f"same code as internal-Jacobian record {ij_hit.get('id')} "
                     f"(bucket {ij_hit.get('bucket')}); not re-run on this corpus "
                     "source")
    out["internal_jacobian"] = na_cell() if na else _not_attempted_feature(
        ij_reason, f"repo:{inp.internal_jacobian_round}")
    ps_reason = ("no corpus source matches one of the curated parameter-sensitivity "
                 "models (compared by normalised-content and code-only SHA-256)")
    if ps_hit:
        ps_reason = f"same code as curated model {ps_hit}; not re-run on this source"
    for f in ("stress_param_sens_local", "stress_param_sens_total",
              "state_param_sens_local", "state_param_sens_total"):
        out[f] = na_cell() if na else _not_attempted_feature(
            ps_reason, f"repo:{inp.param_sens_round}")
    for f in ("residual_sens", "global_sens", "cli_driver"):
        out[f] = na_cell() if na else _not_attempted_feature(
            "no evidence exists yet; to be merged from later batches")
    return out


def _discovered_rows(inp: ManifestInputs, acquired: set[str]) -> tuple[list, dict]:
    path = inp.repo / inp.discovered
    rows, census = [], {}
    if not path.is_file():
        return rows, {"note": "discovery inventory not found"}
    with path.open(newline="", encoding="utf-8") as fh:
        disc = list(csv.DictReader(fh))
    outcomes = Counter(r["outcome"] for r in disc)
    candidates = [r for r in disc if r["outcome"] == "candidate"]
    not_acq = []
    for r in candidates:
        sid = r["repository"].replace("/", "__") + "/" + r["path"]
        if sid not in acquired:
            not_acq.append((sid, r))
    summary_path = inp.repo / inp.discovered_summary
    refusals = Counter()
    if summary_path.is_file():
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        refusals = Counter(x.get("outcome") for x in s.get("refusals", []))
    census = {
        "files_examined": len(disc),
        "outcomes": dict(sorted(outcomes.items())),
        "candidates": len(candidates),
        "candidates_acquired": len(candidates) - len(not_acq),
        "candidates_not_acquired": len(not_acq),
        "repositories_refused_by_outcome": dict(sorted(refusals.items())),
        "note": "discovered_sources.csv content_sha256 is the NORMALISED-content "
                "hash (umat_oti.corpus.identity.normalise_source), not the raw file "
                "hash the registry records; candidates are matched to acquired "
                "sources by repository+path",
    }
    for sid, r in not_acq:
        lic = redistribution_policy(
            r.get("license_spdx"),
            _licence_file(inp.discovery_cache, r["repository"].replace("/", "__")),
            metadata_source=r.get("license_evidence", ""))
        lic["scope"] = "repository"
        url = (f"https://github.com/{r['repository']}/blob/{r['commit']}/{r['path']}"
               if r.get("commit") else "")
        reason = "discovered as a candidate but never acquired into the cache"
        ev = f"repo:{inp.discovered}#repository={r['repository']}&path={r['path']}"
        stages = {"discovered": _cell("verified", r.get("reason", ""), ev)}
        for s in STAGES[1:]:
            stages[s] = _cell("not_attempted", reason, ev)
        stages["compiled"]["layouts"] = {}
        feats = {f: _not_attempted_feature(reason, ev) for f in FEATURES}
        rows.append({
            "row_kind": "discovered_not_acquired",
            "source_id": sid, "repository": r["repository"],
            "path_in_repository": r["path"], "url": url,
            "url_provenance": "built from the discovery inventory's repository, "
                              "commit and path",
            "commit": r.get("commit", ""), "cache_path": None,
            "sha256": {"registry": None, "recomputed": None, "agrees": None,
                       "normalised_content_sha256": r.get("content_sha256") or None,
                       "code_only_sha256": r.get("code_only_sha256") or None},
            "bytes": {"on_disk": None, "registry": int(r["bytes"]) if r.get("bytes")
                      else None, "agrees": None},
            "license": lic,
            "retrieval": {"url": url, "commit": r.get("commit", ""), "path": r["path"],
                          "sha256": None,
                          "instructions": f"fetch {url}; only the normalised-content "
                                          f"sha256 {r.get('content_sha256')} is known"},
            "model": None, "interface": None,
            "registry": None, "origins": None, "pipeline": stages, "features": feats,
            "features_other_builds": {b: {} for b in OTHER_BUILDS},
            "ddsdde_legacy_gate": {"gate": "not_run", "counts_as_verified": False,
                                   "rule": LEGACY_DDSDDE_RULE, "reason": reason,
                                   "evidence": ev},
            "later_pass": None, "data_quality": [],
        })
    return rows, census


# ---------------------------------------------------------------------------
# Summary / denominators
# ---------------------------------------------------------------------------


def _counts(rows: Sequence[dict], getter) -> dict:
    c = Counter(getter(r) for r in rows)
    return {s: c.get(s, 0) for s in STATUSES}


def summarise(manifest: Mapping) -> dict:
    """Denominators and per-status counts. Every block sums to its denominator."""
    rows = manifest["rows"]
    acquired = [r for r in rows if r["row_kind"] == "acquired"]
    eligible = [r for r in acquired if r["pipeline"]["eligible"]["status"] == "verified"]
    not_acq = [r for r in rows if r["row_kind"] == "discovered_not_acquired"]
    denoms = {
        "D0_discovered_files": {"count": len(acquired) + len(not_acq),
                                "means": "acquired sources plus discovered candidate "
                                         "files that were never acquired"},
        "D1_acquired": {"count": len(acquired),
                        "means": "every source the acquisition brought back "
                                 "(registry records)"},
        "D2_eligible": {"count": len(eligible),
                        "means": "adequately specified genuine UMATs (registry D2)"},
        "discovered_not_acquired": {"count": len(not_acq),
                                    "means": "counted separately; not in D1"},
    }
    out = {"denominators": denoms, "stages": {}, "features": {}, "funnel": {}}
    for name, pop in (("D1_acquired", acquired), ("D2_eligible", eligible),
                      ("D0_discovered_files", acquired + not_acq)):
        out["stages"][name] = {s: _counts(pop, lambda r, s=s: r["pipeline"][s]["status"])
                               for s in STAGES}
        out["features"][name] = {f: _counts(pop, lambda r, f=f: r["features"][f]["status"])
                                 for f in FEATURES}
        out["funnel"][name] = {
            **{s: out["stages"][name][s]["verified"] for s in STAGES},
            **{f"feature:{f}": out["features"][name][f]["verified"] for f in FEATURES},
            "denominator": len(pop),
        }
    out["ddsdde_legacy_gate"] = {
        "what": "the pass's Abaqus tangent gate by derived tangent_verdict (passed = "
                "verified, failed = a measured disagreement, unresolved = neither); "
                "the D-4 gate from G10, the legacy plateau rule before it. Shown "
                "here, never counted in features.ddsdde",
        **{name: {g: sum(1 for r in pop if (r.get("ddsdde_legacy_gate") or {})
                         .get("gate") == g)
                     for g in ("passed", "failed", "unresolved", "not_run")}
           for name, pop in (("D1_acquired", acquired), ("D2_eligible", eligible))},
        "passed_with_primal_not_verified": {
            name: sum(1 for r in pop
                      if (r.get("ddsdde_legacy_gate") or {}).get("gate") == "passed"
                      and r["features"]["primal_stress_state"]["status"] != "verified")
            for name, pop in (("D1_acquired", acquired), ("D2_eligible", eligible))},
    }
    other: dict[str, dict] = {"what": "verified on the lifted/provider build -- a "
                              "different build of the source than the Abaqus "
                              "pipeline's; counts over the rows that have such a "
                              "cell, never pooled with summary.features"}
    for name, pop in (("D1_acquired", acquired), ("D2_eligible", eligible)):
        other[name] = {}
        for b in OTHER_BUILDS:
            feats_b: dict[str, dict] = {}
            for f in FEATURES:
                have = [r for r in pop
                        if f in ((r.get("features_other_builds") or {}).get(b) or {})]
                if have:
                    feats_b[f] = {"rows_with_cell": len(have), **_counts(
                        have, lambda r, f=f, b=b: r["features_other_builds"][b][f]["status"])}
            other[name][b] = feats_b
    out["features_other_builds"] = other
    layouts = Counter()
    for r in acquired:
        for k, c in (r["pipeline"]["compiled"].get("layouts") or {}).items():
            layouts[(k, c["status"])] += 1
    out["compile_layouts_D1"] = {f"{k}:{s}": n for (k, s), n in sorted(layouts.items())}
    out["redistribution"] = {
        "D0": dict(Counter(r["license"]["redistribution"] for r in acquired + not_acq)),
        "D1": dict(Counter(r["license"]["redistribution"] for r in acquired)),
        "D2": dict(Counter(r["license"]["redistribution"] for r in eligible)),
        "D1_with_licence_file_in_cache": sum(1 for r in acquired
                                             if r["license"]["licence_file"]),
        "D1_by_spdx_metadata": dict(Counter(r["license"]["spdx_metadata"] or "(none)"
                                            for r in acquired)),
        "D1_by_spdx_and_redistribution": dict(Counter(
            f'{r["license"]["spdx"] or "(none)"}:{r["license"]["redistribution"]}'
            for r in acquired)),
        "D1_by_class": dict(Counter(r["license"]["license_class"] for r in acquired)),
        "D1_attribution_required": sum(1 for r in acquired
                                       if r["license"]["attribution_required"]),
        "D1_copyleft": dict(Counter(r["license"]["copyleft"] or "none"
                                    for r in acquired)),
    }
    def fam_of(r, key="reporting_family"):
        return r["model"]["family"].get(key) or r["model"]["family"].get("family", "")

    def e_of(r):
        return (r["model"]["family"].get("E") or {}).get("family", "")
    out["families"] = {
        "classification": FAMILY_CLASSIFICATION,
        "D1": dict(Counter(fam_of(r) for r in acquired)),
        "D2": dict(Counter(fam_of(r) for r in eligible)),
        "D2_fine": dict(Counter(fam_of(r, "family") for r in eligible)),
        "D2_by_source": dict(Counter(r["model"]["family"].get("source", "")
                                     for r in eligible)),
        "D2_identity_growth_scaffolds": sum(
            1 for r in eligible if r["model"]["family"].get("identity_growth_scaffold")),
        "review_D1": dict(Counter(r["model"]["family"]["review"] for r in acquired)),
        "human_reviewed_D1": sum(1 for r in acquired
                                 if r["model"]["family"]["human_reviewed"]),
        "E_secondary": {"what": "Agent E's classification "
                                "(material_families_checked_E.json); shown for "
                                "comparison, never the reported family",
                        "D1": dict(Counter(e_of(r) for r in acquired)),
                        "D2": dict(Counter(e_of(r) for r in eligible))},
    }
    out["definitions"] = {
        "verified": "the stage's own evidence says it passed; transformed, compiled "
                    "or executed never imply verified downstream",
        "inheritance": "a stage with no evidence of its own inherits blocked / "
                       "not_applicable / unsupported from the stage above it, and "
                       "is not_attempted when the stage above failed",
        "conflict": "independent evidence says both verified and failed; both are "
                    "listed in the cell and neither is counted",
        "inconclusive": "evidence that neither establishes nor refutes the claim",
        "undefined_in_original": "the ORIGINAL's output differs between init builds "
                                 "(D-12): a source defect, never compared, counted "
                                 "neither verified nor failed",
        "features": "summary.features counts the Abaqus-pipeline (store) build "
                    "only; lifted/provider cells are in features_other_builds",
    }
    # eligibility does not change on a merge: keep the note build_manifest wrote
    note = (manifest.get("summary") or {}).get("denominators_note")
    if note is not None:
        out["denominators_note"] = note
    return out


def _data_quality(manifest: Mapping, registry: Mapping) -> dict:
    rows = [r for r in manifest["rows"] if r["row_kind"] == "acquired"]
    c = Counter(code for r in rows for code in r["data_quality"])
    examples: dict[str, list[str]] = {}
    for r in rows:
        for code in r["data_quality"]:
            examples.setdefault(code, [])
            if len(examples[code]) < 5:
                examples[code].append(r["source_id"])
    reg = registry.get("summary", {})
    st = manifest["summary"]["stages"]["D1_acquired"]
    cross = {
        "acquired": (reg.get("acquired"), len(rows)),
        "adequately_specified": (reg.get("adequately_specified_genuine_umats"),
                                 st["eligible"]["verified"]),
        "transformed_true": (reg.get("censuses", {}).get("transformed", {})
                             .get("counts", {}).get("True"),
                             st["transformed"]["verified"]),
        "fully_verified_registry": (reg.get("fully_verified"), None),
    }
    return {"by_code": dict(sorted(c.items())), "examples": examples,
            "registry_cross_check": {k: {"registry": a, "manifest": b,
                                         "agrees": None if b is None else a == b}
                                     for k, (a, b) in cross.items()}}


# ---------------------------------------------------------------------------
# Validation and merging
# ---------------------------------------------------------------------------


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _stated(x: Any) -> bool:
    """A field that actually states something (not '-', 'n/a', 'x', ...)."""
    return isinstance(x, str) and len(x.strip()) >= 3 and \
        x.strip().lower() not in _PLACEHOLDERS


def build_kind(cell: Mapping) -> str | None:
    """``store`` / ``lifted`` / ``provider`` named by a cell, else None."""
    b = cell.get("build")
    if isinstance(b, Mapping):
        return b.get("kind")
    return None


def _is_inf(x: Any) -> bool:
    return (isinstance(x, float) and math.isinf(x)) or x in ("inf", "Infinity")


def validate_cell(feature: str, cell: Mapping, *,
                  roots: Mapping[str, str] | None = None,
                  check_evidence: bool = True) -> list[str]:
    """Problems with one feature cell; empty means acceptable.

    Every cell: a known feature and status; a reason unless verified; an
    evidence locator that resolves to an existing file whenever the cell is
    ``verified``, ``failed``, ``inconclusive`` or ``conflict`` (and whenever
    one is given at all).

    Derivative cells that decide anything (verified / failed / inconclusive)
    name their ``build``: ``{"kind": "store"|"lifted"|"provider",
    "fingerprint": ..., "sha256": ...}`` with at least one of the two digests.

    A ``verified`` cell additionally needs an independent reference
    (original / analytical / fd) and the ONE tolerance semantics:
    ``tolerance == 1``, ``0 <= max_error <= 1`` (the largest error/tolerance
    ratio over every judged entry), an accepted ``tolerance_rule_id`` from
    :data:`TOLERANCE_RULES` that applies to this kind of feature, and a finite
    ``rtol`` within that rule's bound. An ``fd`` reference needs >= 3
    ``fd_steps``, an ``fd_only`` ``plateau_basis`` and a recorded
    ``min_plateau_observed`` (the SHORTEST plateau actually found) of at least
    :data:`MIN_PLATEAU`. A derivative claim states ``quantity``, ``wrt``,
    ``held_fixed`` (no placeholders) and a ``scope`` of local or total.

    A ``failed`` primal must record a disagreement (``max_error`` above
    ``tolerance``, non-finite, or ``values_disagree: true``); anything less is
    ``inconclusive``.
    """
    problems: list[str] = []
    if feature not in FEATURES:
        problems.append(f"unknown feature {feature!r}")
    st = cell.get("status")
    if st not in STATUSES:
        problems.append(f"unknown status {st!r}")
    derivative = feature in DERIVATIVE_FEATURES
    if not cell.get("reason") and st != "verified":
        problems.append("non-verified cell without a reason")
    ev = cell.get("evidence") or ""
    if check_evidence and (ev or st in ("verified", "failed", "inconclusive",
                                        "conflict")):
        path, why = resolve_locator(ev, roots)
        if path is None:
            problems.append(why if ev else f"{st} without an evidence path")
    b = cell.get("build")
    if derivative and st in ("verified", "failed", "inconclusive"):
        if not isinstance(b, Mapping):
            problems.append("derivative cell without a build "
                            "{kind: store|lifted|provider, fingerprint|sha256}")
    if b is not None:
        if not isinstance(b, Mapping) or b.get("kind") not in BUILDS:
            problems.append(f"build must be an object whose kind is one of {BUILDS}")
        elif st in ("verified", "failed", "inconclusive") and not (
                _stated(b.get("fingerprint")) or _stated(b.get("sha256"))):
            problems.append("build names neither a fingerprint nor a sha256")
    if st == "verified":
        if cell.get("reference") not in REFERENCE_TYPES:
            problems.append(f"verified with reference {cell.get('reference')!r}; "
                            f"needs one of {REFERENCE_TYPES}")
        me, tol = cell.get("max_error"), cell.get("tolerance")
        if not (_finite(me) and _finite(tol)):
            problems.append("verified without a finite max_error and tolerance")
        else:
            if tol != 1.0:
                problems.append(f"tolerance {tol!r}: must be 1.0 (max_error is the "
                                "largest error/tolerance ratio)")
            if me < 0:
                problems.append("negative max_error")
            elif me > 1.0:
                problems.append("verified with max_error above tolerance")
        rid = cell.get("tolerance_rule_id")
        rule = TOLERANCE_RULES.get(rid) if isinstance(rid, str) else None
        if rule is None:
            problems.append(f"tolerance_rule_id {rid!r} is not registered "
                            f"(one of {', '.join(k for k, v in TOLERANCE_RULES.items() if v['accepted'])})")
        else:
            klass = "derivative" if derivative else "primal"
            if not rule["accepted"]:
                problems.append(f"tolerance rule {rid} is not accepted for verified: "
                                f"{rule['definition']}")
            elif klass not in rule["applies_to"]:
                problems.append(f"tolerance rule {rid} does not apply to a {klass} "
                                "feature")
            rtol = cell.get("rtol")
            if not _finite(rtol) or rtol <= 0:
                problems.append("verified without a finite rtol > 0")
            elif rule["accepted"] and rtol > rule["rtol_max"]:
                problems.append(f"rtol {rtol:g} exceeds the bound {rule['rtol_max']:g} "
                                f"of rule {rid}")
        if cell.get("reference") == "fd":
            steps = cell.get("fd_steps") or []
            if len(steps) < 3:
                problems.append("fd reference with fewer than three step sizes")
            mp = cell.get("min_plateau_observed")
            if not isinstance(mp, int) or isinstance(mp, bool):
                problems.append("fd reference without min_plateau_observed (the "
                                "shortest FD-only plateau found; the ladder length "
                                "is not a plateau)")
            elif mp < MIN_PLATEAU:
                problems.append(f"FD plateau of {mp} step(s) < {MIN_PLATEAU} "
                                "(decision D-4: plausible, not verified)")
            elif mp > len(steps):
                problems.append("min_plateau_observed is longer than the step ladder")
            basis = cell.get("plateau_basis")
            if PLATEAU_BASES.get(basis) is not True:
                problems.append(f"plateau_basis {basis!r}: only 'fd_only' is accepted "
                                "(a plateau taken from the OTI-vs-FD error is the "
                                "legacy rule D-4 rejects)")
        if derivative:
            for k in ("quantity", "wrt", "held_fixed"):
                if not _stated(cell.get(k)):
                    problems.append(f"derivative claim missing or placeholder {k!r}")
            if cell.get("scope") not in ("local", "total"):
                problems.append("derivative scope must be 'local' or 'total'")
    if st == "failed" and feature == "primal_stress_state":
        me, tol = cell.get("max_error"), cell.get("tolerance")
        disagree = (_is_inf(me) or (_finite(me) and _finite(tol) and me > tol)
                    or cell.get("values_disagree") is True)
        if not disagree:
            problems.append("primal failed without a recorded disagreement "
                            "(max_error <= tolerance or missing): a comparison that "
                            "is not informative is inconclusive")
    if st == "conflict" and not cell.get("conflicting"):
        problems.append("conflict without the conflicting cells")
    return problems


# ---- merging ---------------------------------------------------------------

#: Among cells that decide nothing, the more informative one stays.
_RANK = {"undefined_in_original": 6, "inconclusive": 5, "unsupported": 4, "blocked": 3, "not_applicable": 2,
         "not_attempted": 1}


def _strip(cell: Mapping) -> dict:
    return {k: v for k, v in cell.items() if k != "history"}


def _key(cell: Mapping) -> str:
    return json.dumps(_strip(cell), sort_keys=True, default=str)


def _who(cells: Sequence[Mapping]) -> str:
    return "; ".join(f"{c.get('producer') or 'pipeline'} ({c.get('evidence')})"
                     for c in cells)


def _combine(base: Mapping, incoming: Sequence[Mapping]) -> dict:
    """One cell from the current cell and the accepted records for it.

    Order-independent: ``verified`` and ``failed`` from any two sources give
    ``conflict`` listing both; a ``failed`` is never replaced by a
    ``verified``; a ``conflict`` stays a conflict and collects the new
    decisive evidence. Without decisive evidence, the most informative status
    stays (inconclusive > unsupported > blocked > not_applicable >
    not_attempted; a tie goes to the newer record).
    """
    pool = [dict(base)] + [dict(c) for c in incoming]
    history = list(base.get("history") or [])
    conflicting: list[dict] = list(base.get("conflicting") or []) \
        if base.get("status") == "conflict" else []
    seen = {_key(c) for c in conflicting}
    for c in pool:
        if c.get("status") in DECISIVE and _key(c) not in seen:
            conflicting.append(_strip(c))
            seen.add(_key(c))
    statuses = {c["status"] for c in conflicting}
    chosen: dict
    if base.get("status") == "conflict" or {"verified", "failed"} <= statuses:
        ver = [c for c in conflicting if c["status"] == "verified"]
        fail = [c for c in conflicting if c["status"] == "failed"]
        chosen = {"status": "conflict",
                  "reason": (f"independent evidence disagrees: verified by {_who(ver)}; "
                             f"failed by {_who(fail)}. Neither is counted until the "
                             "disagreement is resolved."),
                  "evidence": (fail or ver)[0].get("evidence", ""),
                  "reference": None, "max_error": None, "tolerance": None,
                  "conflicting": conflicting}
        if ver or fail:
            b = (fail or ver)[0].get("build")
            if b is not None:
                chosen["build"] = b
        rest = [c for c in pool if c.get("status") not in DECISIVE
                and c.get("status") != "conflict"]
    elif "failed" in statuses:
        chosen = next(c for c in pool if c.get("status") == "failed")
        rest = [c for c in pool if c is not chosen]
    elif "verified" in statuses:
        ver = [c for c in pool if c.get("status") == "verified"]
        chosen = max(ver, key=lambda c: c.get("max_error") or 0.0)
        rest = [c for c in pool if c is not chosen]
    else:
        best = max(range(len(pool)),
                   key=lambda i: (_RANK.get(pool[i].get("status"), 0), i))
        chosen = pool[best]
        rest = [c for i, c in enumerate(pool) if i != best]
    out = _strip(chosen)
    out["history"] = history + [_strip(c) for c in rest]
    return out


def _gate_on_definedness(cells: dict) -> None:
    """D-8 / D-12.3: STRESS and DDSDDE must be fully defined in the ORIGINAL.

    A cell that records ``stress_and_ddsdde_fully_defined: false`` judged only
    the entries the original defines; an OTI defect located exactly where the
    original is undefined is invisible to it. Such a cell is shown, never
    counted: it becomes ``inconclusive`` with the undefined outputs named, and
    keeps what was measured in ``withheld_verified``. A cell that does not
    record the flag (producers other than the routine-level harness) is left
    as it is.
    """
    for feat in ("primal_stress_state", "ddsdde"):
        c = cells.get(feat)
        if not c or c.get("status") != "verified":
            continue
        if c.get("stress_and_ddsdde_fully_defined") is False:
            undefined = c.get("undefined_outputs") or []
            cells[feat] = {
                "status": "inconclusive",
                "reason": ("undefined_in_original: the original's STRESS or DDSDDE is "
                           "not fully defined on the judged paths "
                           f"({', '.join(map(str, undefined[:8])) or 'see undefined_outputs'}); "
                           "only the defined entries were compared, so this is not "
                           "counted (decision D-12.3)"),
                "evidence": c.get("evidence", ""), "max_error": None, "tolerance": None,
                **{k: c.get(k) for k in ("reference", "quantity", "wrt", "held_fixed",
                                         "scope", "build", "producer",
                                         "undefined_outputs") if k in c},
                "withheld_verified": _strip(c),
                "history": list(c.get("history") or [])}


def _gate_on_primal(row: dict) -> None:
    """A derivative is counted only on a build whose primal agrees.

    Store build: ``features.primal_stress_state`` must be verified. Lifted /
    provider builds: that build's own primal cell, when one was merged, must
    be verified (when none was merged the cell says so). A gated cell becomes
    ``inconclusive`` and keeps the verified cell in ``withheld_verified``; it
    is restored if the primal later verifies.
    """
    blocks = [("store", row.get("features") or {})] + [
        (b, (row.get("features_other_builds") or {}).get(b) or {}) for b in OTHER_BUILDS]
    for build, cells in blocks:
        _gate_on_definedness(cells)
        primal = cells.get("primal_stress_state")
        p_status = primal.get("status") if primal else None
        ok = p_status == "verified" if build == "store" else p_status in (None, "verified")
        for feat in sorted(DERIVATIVE_FEATURES):
            c = cells.get(feat)
            if not c:
                continue
            if c.get("status") == "verified" and not ok:
                gated = {k: c.get(k) for k in ("reference", "quantity", "wrt",
                                               "held_fixed", "scope", "build",
                                               "producer") if k in c}
                cells[feat] = {
                    "status": "inconclusive",
                    "reason": (f"verified on the {build} build, but that build's "
                               f"primal_stress_state is {p_status}: a derivative of a "
                               "build whose primal does not agree with the original "
                               "is not counted"),
                    "evidence": c.get("evidence", ""), "max_error": None,
                    "tolerance": None, **gated, "withheld_verified": _strip(c),
                    "history": list(c.get("history") or [])}
            elif c.get("status") == "inconclusive" and c.get("withheld_verified") and ok:
                restored = dict(c["withheld_verified"])
                restored["history"] = list(c.get("history") or [])
                cells[feat] = restored
            elif build != "store" and c.get("status") == "verified" and p_status is None:
                c["primal_of_this_build"] = "not recorded"


def merge_feature_results(manifest: dict,
                          results: str | Path | Iterable[Mapping],
                          *, producer: str = "", label: str = "",
                          roots: Mapping[str, str] | None = None) -> dict:
    """Merge feature results into the manifest in place.

    ``results`` is a JSONL path or an iterable of dicts, one per
    (source_id, feature[, build])::

        {"source_id": "...", "feature": "stress_param_sens_local",
         "status": "verified", "reason": "...",
         "evidence": "campaign:batches/B2/gauss/run/features.jsonl#key=...",
         "reference": "fd", "max_error": 0.03, "tolerance": 1.0,
         "tolerance_rule_id": "entrywise/1", "rtol": 1e-6, "atol": 1e-12,
         "fd_steps": [1e-3, 3e-4, 1e-4, 3e-5, 1e-5],
         "min_plateau_observed": 3, "plateau_basis": "fd_only",
         "quantity": "d STRESS_{n+1}/d PROPS", "wrt": "PROPS(1..3)",
         "held_fixed": "incoming STRESS/STATEV, DSTRAN", "scope": "local",
         "build": {"kind": "store", "fingerprint": "dbe9f928191e1d43",
                   "sha256": "<sha256 of the built object>"},
         "producer": "gauss/B2"}

    Absolute evidence paths under a known root are rewritten as
    ``<root>:<relative>``. Each record is checked by :func:`validate_cell`;
    a rejected record leaves the manifest unchanged. Accepted records are
    routed by build: ``store`` (or no build) into ``features``, ``lifted`` and
    ``provider`` into ``features_other_builds``. They are combined with the
    current cell by :func:`_combine` (order-independent; verified + failed is
    ``conflict``), then every row is re-gated on its primal
    (:func:`_gate_on_primal`). The summary is recomputed and the merge is
    logged in ``manifest["merges"]``.
    """
    roots = {**DEFAULT_ROOTS, **expand_roots(manifest.get("roots") or {}), **(roots or {})}
    if isinstance(results, (str, Path)):
        label = label or to_locator(str(Path(results).resolve()), roots)
        records = _load_jsonl(Path(results))
    else:
        records = list(results)
    index = {r["source_id"]: r for r in manifest["rows"]}
    rejected, unmatched = [], []
    groups: dict[tuple, list] = {}
    for n, rec in enumerate(records, start=1):
        sid, feat = rec.get("source_id"), rec.get("feature")
        row = index.get(sid)
        if row is None:
            unmatched.append(sid)
            continue
        cell = {k: v for k, v in rec.items() if k not in ("source_id", "feature")}
        for k in ("reference", "max_error", "tolerance"):
            cell.setdefault(k, None)
        _blank_undecided_digests(cell)
        cell["evidence"] = to_locator(cell.get("evidence") or "", roots)
        if isinstance(cell.get("evidence_all"), list):
            cell["evidence_all"] = [to_locator(e, roots) for e in cell["evidence_all"]]
        if producer and not cell.get("producer"):
            cell["producer"] = producer
        problems = validate_cell(feat, cell, roots=roots)
        if cell.get("status") == "conflict":
            problems.append("a record may not claim conflict; the merge decides it")
        if problems:
            rejected.append({"line": n, "source_id": sid, "feature": feat,
                             "status": cell.get("status"), "problems": problems})
            continue
        kind = build_kind(cell) or "store"
        groups.setdefault((sid, kind, feat), []).append(cell)
    for (sid, kind, feat), cells in groups.items():
        row = index[sid]
        if kind == "store":
            target = row["features"]
        else:
            target = row.setdefault("features_other_builds",
                                    {b: {} for b in OTHER_BUILDS}).setdefault(kind, {})
        base = target.get(feat) or _not_attempted_feature(
            f"no {kind}-build result before this merge")
        target[feat] = _combine(base, cells)
    for row in manifest["rows"]:
        _gate_on_primal(row)
    report = {"label": label, "producer": producer, "records": len(records),
              "merged": sum(len(v) for v in groups.values()),
              "cells_touched": len(groups), "rejected": rejected,
              "unmatched": unmatched}
    manifest.setdefault("merges", []).append(
        {**report, "unmatched": sorted({str(u) for u in unmatched})})
    manifest["summary"] = summarise(manifest)
    return report


def _blank_undecided_digests(cell: dict) -> None:
    """A cell that decides nothing may name its build without digests (cells
    written before the harness recorded them carry ``null``): those become
    ``""``. A verified / failed / inconclusive cell is left as it is, so
    :func:`validate_cell` still rejects it without a digest."""
    b = cell.get("build")
    if isinstance(b, Mapping) and cell.get("status") not in (
            "verified", "failed", "inconclusive"):
        cell["build"] = {**b, **{k: "" for k in ("fingerprint", "sha256")
                                 if k in b and b[k] is None}}


#: Decision D-18: which harness run decides each feature. The routine-level
#: driver runs every perturbation of a path in one process, so an original that
#: STOPs under one perturbation ends every column queued after it; whether
#: DDSDDE can be judged must not depend on which other features were requested.
D18_PRIMAL_RUN_FEATURES: tuple[str, ...] = ("primal_stress_state", "ddsdde")


def _d18_guard(rec: Mapping, full_by_key: Mapping, trips: set[str]) -> dict:
    """A primal/ddsdde record from the primal+ddsdde run, withheld (made
    inconclusive) when the full-feature run shows a failure or a hidden-state
    trip for it."""
    if rec.get("status") != "verified":
        return dict(rec)
    sid, feat = rec.get("source_id"), rec.get("feature")
    kind = build_kind(rec) or "store"
    other = full_by_key.get((sid, feat, kind))
    why = ""
    if other is not None and other.get("status") in ("failed", "conflict"):
        why = (f"the full-feature run reports {other.get('status')} for this cell: "
               + (other.get("reason") or "")[:400])
    elif other is not None and other.get("hidden_state_trips"):
        why = "the full-feature run tripped the hidden-state gate on this cell"
    elif sid in trips:
        why = "the full-feature run tripped the hidden-state gate on this source"
    if not why:
        return dict(rec)
    keep = {k: rec[k] for k in ("source_id", "feature", "evidence", "reference",
                                "quantity", "wrt", "held_fixed", "scope", "build",
                                "producer") if k in rec}
    return {**keep, "status": "inconclusive", "max_error": None, "tolerance": None,
            "reason": f"D-18 guard: verified in the primal+ddsdde run, but {why}",
            "d18_guard": True,
            # not ``withheld_verified``: the primal gate restores that one
            "d18_withheld_verified": {k: v for k, v in rec.items()
                                  if k not in ("source_id", "feature", "history")}}


def merge_d18(manifest: dict, primal_ddsdde_run: str | Path | Iterable[Mapping],
              full_run: str | Path | Iterable[Mapping], *,
              roots: Mapping[str, str] | None = None) -> dict:
    """Merge the two routine-level harness runs by decision D-18.

    ``primal_stress_state`` and ``ddsdde`` come from the primal+ddsdde run
    (its own hidden-state gate); every other feature (parameter and state
    sensitivities, internal Jacobian) from the full-feature run, whose
    primal/ddsdde records are not merged. Guard: a primal/ddsdde record that
    is verified in the primal+ddsdde run is merged as ``inconclusive`` when the
    full-feature run shows ``failed`` (or ``conflict``) or a hidden-state trip
    for it. Independent of argument order. Returns both merge reports.
    """
    roots_m = {**DEFAULT_ROOTS, **expand_roots(manifest.get("roots") or {}),
               **(roots or {})}

    def load(x):
        if isinstance(x, (str, Path)):
            return _load_jsonl(Path(x)), to_locator(str(Path(x).resolve()), roots_m)
        return list(x), ""
    prim, prim_label = load(primal_ddsdde_run)
    full, full_label = load(full_run)
    full_by_key = {(r.get("source_id"), r.get("feature"), build_kind(r) or "store"): r
                   for r in full}
    trips = {r.get("source_id") for r in full if r.get("hidden_state_trips")}
    prim_in = [_d18_guard(r, full_by_key, trips) for r in prim
               if r.get("feature") in D18_PRIMAL_RUN_FEATURES]
    full_in = [r for r in full if r.get("feature") not in D18_PRIMAL_RUN_FEATURES]
    rep_p = merge_feature_results(manifest, prim_in, label=prim_label or "primal+ddsdde run",
                                  roots=roots)
    rep_f = merge_feature_results(manifest, full_in, label=full_label or "full-feature run",
                                  roots=roots)
    guarded = [{"source_id": r["source_id"], "feature": r["feature"],
                "reason": r["reason"]} for r in prim_in if r.get("d18_guard")]
    manifest["feature_sources"] = {
        "decision": "D-18",
        "primal_ddsdde_run": prim_label,
        "full_feature_run": full_label,
        "features": {f: ("primal_ddsdde_run" if f in D18_PRIMAL_RUN_FEATURES
                         else "full_feature_run") for f in FEATURES
                     if f not in ("residual_sens", "global_sens", "cli_driver")},
        "ignored_from_primal_ddsdde_run": sum(
            1 for r in prim if r.get("feature") not in D18_PRIMAL_RUN_FEATURES),
        "ignored_from_full_feature_run": len(full) - len(full_in),
        "guard": "a primal/ddsdde cell verified in the primal+ddsdde run is merged as "
                 "inconclusive when the full-feature run shows failed/conflict or a "
                 "hidden-state trip for it",
        "guarded": guarded,
    }
    return {"primal_ddsdde_run": rep_p, "full_feature_run": rep_f, "guarded": guarded}


# ---- Residual Assembler records (Noether, schema ra-corpus-residual/1) ------

#: RA features the manifest has a column for, and the scope of each claim.
RA_FEATURES = {"residual_sens": "local", "global_sens": "total"}
_RA_STEPS = re.compile(r"relative steps\s*\[([^\]]*)\]")


#: RA records that carry the merge contract's own fields (entrywise rule,
#: FD-only plateau, per-record error/tolerance ratio, build, scope). From B2.
RA_SCHEMA_V2 = "ra-corpus-residual/2"


def _ra_v2_cell(sid: str, feat: str, rs: list, roots: Mapping[str, str],
                producer: str) -> dict:
    """One cell from ``ra-corpus-residual/2`` per-problem records, unchanged in meaning.

    The records already state the contract's fields, so they are carried, not
    re-interpreted. The fold is the harness's: a cell is verified only when no
    problem failed and at least ``min(2, problems evaluated)`` problems
    verified, where "evaluated" excludes ``unsupported``; otherwise it is
    ``not_attempted`` with the coverage stated. The worst error ratio and the
    shortest plateau over the verified records are what the cell reports, and
    ``validate_cell`` judges the result like any other cell.
    """
    per = {r.get("problem"): r.get("status") for r in rs}
    st = Counter(per.values())
    verified = [r for r in rs if r.get("status") == "verified"]
    evaluated = [p for p, v in per.items() if v != "unsupported"]
    first = verified[0] if verified else rs[0]
    rules = {r.get("tolerance_rule_id") for r in verified}
    cell = {
        "source_id": sid, "feature": feat, "producer": producer,
        "schema_in": RA_SCHEMA_V2,
        "evidence": to_locator(first.get("evidence") or "", roots),
        "evidence_all": [to_locator(r.get("evidence") or "", roots) for r in rs],
        "problems": per,
        # The kind is what the schema enumerates; RA's prose stays beside it.
        "reference": next((k for k in (first.get("reference_kind"), first.get("reference"))
                           if k in ("original", "analytical", "fd")), "fd"),
        "reference_text": first.get("reference_text") or first.get("reference") or "",
        "fd_steps": first.get("fd_steps") or [],
        # One rule or none: a cell resting on two rules has no single
        # meaning, and validate_cell refuses a verified cell without a rule.
        "tolerance_rule_id": (rules.pop() if len(rules) == 1 else
                              next(iter({r.get("tolerance_rule_id") for r in rs} - {None}), None)
                              if not rules else None),
        "rtol": max((r.get("rtol") or 0.0) for r in verified) if verified else first.get("rtol"),
        "plateau_basis": ("fd_only" if verified and all(
            r.get("plateau_basis") == "fd_only" for r in verified) else
            first.get("plateau_basis")),
        "min_plateau_observed": (min(int(r.get("min_plateau_observed") or 0)
                                     for r in verified) if verified else None),
        "max_error": (max(float(r.get("max_error") or 0.0) for r in verified)
                      if verified else None),
        "tolerance": 1.0,
        "quantity": first.get("quantity") or first.get("what") or "",
        "wrt": first.get("wrt") or "", "held_fixed": first.get("held_fixed") or "",
        "scope": first.get("scope") or RA_FEATURES[feat],
        "build": first.get("build") or {"kind": "provider"},
        "producer_status": dict(st),
    }
    if st.get("failed"):
        bad = [p for p, v in per.items() if v == "failed"]
        cell["status"] = "failed"
        cell["reason"] = f"RA comparison failed on problem(s) {bad}"
    elif verified and len(verified) >= min(2, len(evaluated)):
        cell["status"] = "verified"
        cell["reason"] = (f"verified on {len(verified)} of {len(evaluated)} evaluated "
                          f"problem(s): {[r.get('problem') for r in verified]}")
    elif set(st) == {"unsupported"}:
        cell["status"] = "unsupported"
        cell["reason"] = "; ".join(sorted({
            f"{r.get('reason_class') or 'unsupported'}: {(r.get('reason') or '')[:300]}"
            for r in rs}))[:1500]
    else:
        cell["status"] = "not_attempted"
        cell["reason"] = (f"insufficient coverage: {len(verified)} of {len(evaluated)} "
                          f"evaluated problem(s) verified; statuses {dict(st)}")
    return cell


def ra_records_to_cells(records: str | Path | Iterable[Mapping], *,
                        roots: Mapping[str, str] | None = None,
                        producer: str = "noether/B1") -> tuple[list[dict], dict]:
    """Fold RA per-problem records into one cell per (source_id, feature).

    The RA records (``ra-corpus-residual/1``) do not meet the merge contract
    as written, and this adapter says how it maps them instead of hiding it:

    * ``reference`` is prose; mapped to ``fd`` and the step ladder parsed out;
    * the tolerance is ``max|a-d| <= atol + rtol*max(max|a|,max|d|)`` over a
      vector -- not entrywise (rule ``vector_max_norm``, refused for verified);
    * the plateau is ">= 3 consecutive steps where FD agrees with OTI" -- the
      OTI-vs-FD plateau D-4 rejects (``plateau_basis: oti_vs_fd``);
    * no per-entry error/tolerance ratio and no observed minimum plateau.

    So an RA ``verified`` becomes ``inconclusive`` here (``producer_status``
    keeps the RA verdict); ``failed`` on any problem is ``failed``; all
    ``unsupported`` is ``unsupported``. Every cell is on the ``provider``
    build (umat_oti.provider), so it lands in the separate provider block.
    Returns ``(cells, report)``; ``report`` lists the schema mismatches.
    """
    roots = roots or DEFAULT_ROOTS
    recs = _load_jsonl(Path(records)) if isinstance(records, (str, Path)) \
        else list(records)
    report: dict[str, Any] = {"records": len(recs), "schemas": dict(Counter(
        r.get("schema") for r in recs)), "skipped_features": {}, "mismatches": {}}
    mism: Counter = Counter()
    groups: dict[tuple, list] = {}
    for r in recs:
        feat = r.get("feature")
        if feat not in RA_FEATURES:
            report["skipped_features"][feat] = report["skipped_features"].get(feat, 0) + 1
            continue
        groups.setdefault((r.get("source_id"), feat), []).append(r)
        if r.get("schema") == RA_SCHEMA_V2:
            continue
        mism["reference is prose, not original|analytical|fd"] += 1
        mism["no max_error/tolerance ratio (max_abs, max_rel and a tolerance dict)"] += 1
        mism["tolerance is a vector max-norm rule, not entrywise"] += 1
        mism["plateau taken where FD agrees with OTI (not FD-only)"] += 1
        mism["no min_plateau_observed"] += 1
        mism["no scope field (local/total)"] += 1
        mism["'what' instead of 'quantity'"] += 1
        mism["no build field (provider object_sha256 only)"] += 1
        if isinstance(r.get("evidence"), str) and r["evidence"].startswith("/"):
            mism["absolute evidence path"] += 1
        if not r.get("object_sha256"):
            mism["no object_sha256"] += 1
        if not r.get("wrt"):
            mism["no wrt"] += 1
    report["mismatches"] = dict(mism)
    cells = []
    for (sid, feat), rs in groups.items():
        if all(r.get("schema") == RA_SCHEMA_V2 for r in rs):
            cells.append(_ra_v2_cell(sid, feat, rs, roots, producer))
            continue
        per = {r.get("problem"): r.get("status") for r in rs}
        st = Counter(per.values())
        first = rs[0]
        steps = []
        m = _RA_STEPS.search(first.get("reference") or "")
        if m:
            steps = [float(x) for x in m.group(1).split(",") if x.strip()]
        tol = first.get("tolerance") if isinstance(first.get("tolerance"), dict) else {}
        sha = next((r.get("object_sha256") for r in rs if r.get("object_sha256")), "")
        evid = [to_locator(r.get("evidence") or "", roots) for r in rs]
        cell = {
            "source_id": sid, "feature": feat, "producer": producer,
            "evidence": evid[0], "evidence_all": evid, "problems": per,
            "reference": "fd", "fd_steps": steps,
            "tolerance_rule_id": "vector_max_norm", "rtol": tol.get("rtol"),
            "atol": tol.get("atol"), "plateau_basis": "oti_vs_fd",
            "plateau_steps_required": tol.get("plateau_steps"),
            "min_plateau_observed": None,
            "max_error": None, "tolerance": None,
            "measured": {"max_rel": max((r.get("max_rel") or 0.0) for r in rs),
                         "max_abs": max((r.get("max_abs") or 0.0) for r in rs),
                         "primal_parity_max": max(
                             (r.get("primal_parity_max") or 0.0) for r in rs)},
            "quantity": first.get("what") or "", "wrt": first.get("wrt") or "",
            "held_fixed": first.get("held_fixed") or "",
            "scope": RA_FEATURES[feat],
            "build": {"kind": "provider", "sha256": sha, "fingerprint": "",
                      "basis": first.get("material_path") or ""},
            "producer_status": ("failed" if st.get("failed") else "verified"
                                if st.get("verified") else
                                next(iter(st)) if len(st) == 1 else "mixed"),
        }
        if st.get("failed"):
            bad = [p for p, s in per.items() if s == "failed"]
            classes = sorted({r.get("failure_class") or "" for r in rs
                              if r.get("status") == "failed"} - {""})
            cell["status"] = "failed"
            cell["reason"] = (f"RA comparison failed on problem(s) {bad} "
                              f"({', '.join(classes) or 'no failure class'}); "
                              f"verified on {[p for p, s in per.items() if s == 'verified']}")
        elif st.get("verified"):
            ok = [p for p, s in per.items() if s == "verified"]
            cell["status"] = "inconclusive"
            cell["reason"] = (
                f"the RA verdict is verified on problem(s) {ok}"
                + (f" ({', '.join(f'{p}: {s}' for p, s in per.items() if s != 'verified')})"
                   if len(ok) < len(per) else "")
                + ", under a vector max-norm tolerance and a plateau taken where FD "
                  "agrees with OTI; the merge contract needs an entrywise tolerance "
                  "and an FD-only plateau of >= 3 steps (B1 review shared rules, D-4), "
                  "so this is not counted as verified")
        elif set(st) == {"unsupported"}:
            cell["status"] = "unsupported"
            cell["reason"] = "; ".join(sorted({
                f"{r.get('failure_class') or 'unsupported'}: "
                f"{(r.get('reason') or '')[:300]}" for r in rs}))[:1500]
        else:
            cell["status"] = "not_attempted"
            cell["reason"] = f"RA statuses {dict(st)}"
        cells.append(cell)
    report["cells"] = dict(Counter((c["feature"], c["status"]) for c in cells))
    report["cells"] = {f"{f}:{s}": n for (f, s), n in sorted(report["cells"].items())}
    return cells, report


# ---------------------------------------------------------------------------
# Schema and outputs
# ---------------------------------------------------------------------------


def manifest_schema() -> dict:
    status = {"enum": list(STATUSES)}
    stage_cell = {"type": "object", "required": ["status", "reason", "evidence"],
                  "properties": {"status": status, "reason": {"type": "string"},
                                 "evidence": {"type": "string"},
                                 "layouts": {"type": "object"}}}
    num_or_null = {"type": ["number", "null"]}
    build = {"type": ["object", "null"],
             "properties": {"kind": {"enum": list(BUILDS)},
                            "fingerprint": {"type": "string"},
                            "sha256": {"type": "string"}}}
    feature_cell = {
        "type": "object",
        "required": ["status", "reason", "evidence", "reference", "max_error",
                     "tolerance"],
        "properties": {"status": status, "reason": {"type": "string"},
                       "evidence": {"type": "string"},
                       "reference": {"enum": list(REFERENCE_TYPES) + [None]},
                       "max_error": num_or_null, "tolerance": num_or_null,
                       "tolerance_rule_id": {"enum": list(TOLERANCE_RULES) + [None]},
                       "build": build,
                       "conflicting": {"type": "array"},
                       "history": {"type": "array"}},
        "allOf": [{"if": {"properties": {"status": {"const": "verified"}}},
                   "then": {"required": ["tolerance_rule_id", "rtol"],
                            "properties": {"evidence": {"minLength": 1},
                                           "reference": {"enum": list(REFERENCE_TYPES)},
                                           "max_error": {"type": "number",
                                                         "minimum": 0, "maximum": 1},
                                           "tolerance": {"const": 1.0}}}},
                  {"if": {"properties": {"status": {"const": "conflict"}}},
                   "then": {"required": ["conflicting"]}}],
    }
    legacy = {"type": "object", "required": ["gate", "counts_as_verified", "rule"],
              "properties": {"gate": {"enum": ["passed", "failed", "unresolved",
                                               "not_run"]},
                             "tangent_verdict": {"enum": [*TANGENT_VERDICTS, ""]},
                             "counts_as_verified": {"const": False}}}
    def _enum(values) -> dict:
        return {"enum": [*values, ""]}
    flag = {"type": ["boolean", "null"]}
    origins = {
        "type": ["object", "null"],
        "required": ["material_data_origin", "experiment_origin", "refusal_kind",
                     "harvest_confidence", "tier"],
        "properties": {
            "material_data_origin": _enum(MATERIAL_DATA_ORIGINS),
            "experiment_origin": _enum(EXPERIMENT_ORIGINS),
            "material_data_ref": {"type": "string"},
            "council_deck_ref": {"type": "string"},
            "council_fingerprint": {"type": "string"},
            "refusal_kind": _enum(REFUSAL_KINDS),
            "harvest_confidence": _enum(CONSTANT_CONFIDENCES),
            "interpreted_constants": {"type": ["integer", "null"], "minimum": 0},
            "council_sets": {"type": "array", "items": {"type": "string"}},
            "vera_accepted_template": flag, "vera_accepted_instance": flag,
            "branch_coverage": {"type": ["object", "null"]},
            "domain_not_enforced": {"type": "string"},
            "pairing_changed": flag,
            "licence_hold": {"type": "string"},
            "tier": _enum(TIERS),
            "tier_basis": {"type": "string"},
            "counted_in_tier": flag,
            "not_counted_in_tier_reason": {"type": "string"}},
        "additionalProperties": False,
        # a council row counts only with both of Vera's acceptances (R6.5)
        "allOf": [{"if": {"properties": {"counted_in_tier": {"const": True}},
                          "required": ["counted_in_tier"]},
                   "then": {"properties": {"vera_accepted_template": {"const": True},
                                           "vera_accepted_instance": {"const": True},
                                           "pairing_changed": {"enum": [False, None]}}}}],
    }
    row = {
        "type": "object",
        "required": ["row_kind", "source_id", "repository", "url", "commit", "sha256",
                     "bytes", "license", "retrieval", "model", "interface",
                     "pipeline", "features", "features_other_builds",
                     "ddsdde_legacy_gate", "data_quality"],
        "properties": {
            "row_kind": {"enum": ["acquired", "discovered_not_acquired"]},
            "source_id": {"type": "string", "minLength": 1},
            "repository": {"type": "string"},
            "url": {"type": "string"}, "commit": {"type": "string"},
            "sha256": {"type": "object",
                       "required": ["registry", "recomputed", "agrees"]},
            "bytes": {"type": "object", "required": ["on_disk", "registry", "agrees"]},
            "license": {"type": "object",
                        "required": ["spdx", "spdx_metadata", "licence_file",
                                     "redistribution", "redistribution_basis",
                                     "license_class", "attribution_required",
                                     "copyleft"],
                        "properties": {"redistribution": {
                            "enum": ["permitted", "not_permitted", "unknown"]}}},
            "retrieval": {"type": "object",
                          "required": ["url", "commit", "path", "sha256",
                                       "instructions"]},
            "model": {"type": ["object", "null"],
                      "properties": {"family": {
                          "type": "object",
                          "required": ["family", "reporting_family", "classification",
                                       "source", "review", "human_reviewed", "basis",
                                       "E"],
                          "properties": {
                              "review": {"enum": [
                                  "agent_reviewed_code_evidence", "keyword_only",
                                  "missing"]},
                              "classification": {"const": "D-11 S1"},
                              "reporting_family": {"enum": [
                                  *REPORTING_FAMILIES, "not_a_umat", ""]},
                              "E": {"type": "object",
                                    "required": ["family", "label"]}}}}},
            "interface": {"type": ["object", "null"]},
            "origins": origins,
            "pipeline": {"type": "object", "required": list(STAGES),
                         "properties": {s: stage_cell for s in STAGES},
                         "additionalProperties": False},
            "features": {"type": "object", "required": list(FEATURES),
                         "properties": {f: feature_cell for f in FEATURES},
                         "additionalProperties": False},
            "features_other_builds": {
                "type": "object", "required": list(OTHER_BUILDS),
                "additionalProperties": False,
                "properties": {b: {"type": "object",
                                   "properties": {f: feature_cell for f in FEATURES},
                                   "additionalProperties": False}
                               for b in OTHER_BUILDS}},
            "ddsdde_legacy_gate": legacy,
            "data_quality": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "UMAT corpus manifest",
        "type": "object",
        "required": ["schema", "generated", "roots", "inputs", "statuses", "rows",
                     "summary", "data_quality"],
        "properties": {"schema": {"const": SCHEMA_ID},
                       "rows": {"type": "array", "items": row},
                       "statuses": {"const": list(STATUSES)}},
    }


def flat_rows(manifest: Mapping) -> list[dict]:
    """One flat dict per row for the CSV view."""
    out = []
    for r in manifest["rows"]:
        m = r.get("model") or {}
        i = r.get("interface") or {}
        fam = m.get("family") or {}
        flat = {
            "row_kind": r["row_kind"], "source_id": r["source_id"],
            "repository": r["repository"], "url": r["url"], "commit": r["commit"],
            "sha256": r["sha256"].get("registry") or "",
            "sha256_agrees": r["sha256"].get("agrees"),
            "bytes_on_disk": r["bytes"].get("on_disk"),
            "license_spdx": r["license"]["spdx"],
            "license_spdx_metadata": r["license"]["spdx_metadata"],
            "licence_file": (r["license"]["licence_file"] or {}).get("path", ""),
            "redistribution": r["license"]["redistribution"],
            "attribution_required": r["license"]["attribution_required"],
            "copyleft": r["license"]["copyleft"],
            "family": fam.get("family", ""),
            "family_reported": fam.get("reporting_family", ""),
            "family_classification": fam.get("classification", ""),
            "family_source": fam.get("source", ""),
            "family_review": fam.get("review", ""),
            "family_E": (fam.get("E") or {}).get("family", ""),
            "family_second_pass": ((fam.get("E") or {}).get("second_pass") or {})
            .get("family", ""),
            "entry_routine": (m.get("entry_point") or {}).get("routine", ""),
            "external_routines": ";".join(e["name"] for e in
                                          m.get("external_routines") or []),
            "modules_used": ";".join(x["name"] for x in m.get("modules_used") or []),
            "source_form": (m.get("compiler_requirements") or {}).get("source_form", ""),
            "preprocessor_required": (m.get("compiler_requirements") or {})
            .get("preprocessor_required"),
            "ntens_measured": ";".join(str(x) for x in i.get("ntens_measured") or []),
            "strain_measure": (i.get("strain_formulation") or {}).get("measure", ""),
            "nlgeom": (i.get("strain_formulation") or {}).get("nlgeom", ""),
            "props_count": (i.get("props") or {}).get("count"),
            "nstatv": (i.get("nstatv") or {}).get("count"),
        }
        o = r.get("origins") or {}
        flat.update({
            "material_data_origin": o.get("material_data_origin", ""),
            "experiment_origin": o.get("experiment_origin", ""),
            "tier": o.get("tier", ""),
            "material_data_ref": o.get("material_data_ref", ""),
            "council_deck_ref": o.get("council_deck_ref", ""),
            "council_fingerprint": o.get("council_fingerprint", ""),
            "refusal_kind": o.get("refusal_kind", ""),
            "harvest_confidence": o.get("harvest_confidence", ""),
            "interpreted_constants": o.get("interpreted_constants"),
            "council_sets": ";".join(o.get("council_sets") or []),
            "vera_accepted_template": o.get("vera_accepted_template"),
            "vera_accepted_instance": o.get("vera_accepted_instance"),
            "branch_coverage": (json.dumps(o["branch_coverage"], sort_keys=True)
                                if o.get("branch_coverage") else ""),
            "domain_not_enforced": o.get("domain_not_enforced", ""),
            "pairing_changed": o.get("pairing_changed"),
            "licence_hold": o.get("licence_hold", ""),
            "counted_in_tier": o.get("counted_in_tier"),
        })
        for mode in ("three_d", "plane_strain", "plane_stress", "axisymmetric"):
            d = (i.get("dimensionality") or {}).get(mode) or {}
            flat[f"dim_{mode}"] = (f"{d.get('support')}/{d.get('basis')}"
                                   if d else "")
        for s in STAGES:
            flat[f"stage_{s}"] = r["pipeline"][s]["status"]
        for f in FEATURES:
            flat[f"feature_{f}"] = r["features"][f]["status"]
        flat["ddsdde_legacy_gate"] = (r.get("ddsdde_legacy_gate") or {}).get("gate", "")
        flat["tangent_verdict"] = (r.get("registry") or {}).get("tangent_verdict", "")
        for b in OTHER_BUILDS:
            cells = (r.get("features_other_builds") or {}).get(b) or {}
            flat[f"{b}_build_features"] = ";".join(
                f"{f}={cells[f]['status']}" for f in FEATURES if f in cells)
        flat["data_quality"] = ";".join(r["data_quality"])
        out.append(flat)
    return out


def _body(manifest: Mapping) -> dict:
    return {k: v for k, v in manifest.items() if k != "generated"}


def _portable(value):
    """Every workspace path in a published manifest written relative to
    $UMAT_OTI_WORKSPACE: a published artefact carries no machine path.

    The workspace is ``$UMAT_OTI_WORKSPACE`` when set, else this checkout's
    parent; it is replaced only as a whole path (followed by ``/`` or by a
    character that cannot continue a file name), never as a prefix of a
    longer directory name."""
    return _portable_with(value, _workspace_pattern(_workspace()))


def _portable_with(value, pat):
    if isinstance(value, str):
        # Anywhere in the string (build commands quoted in a reason carry
        # paths mid-text), but only at path boundaries.
        return pat.sub(WORKSPACE_TOKEN, value)
    if isinstance(value, Mapping):
        return {k: _portable_with(v, pat) for k, v in value.items()}
    if isinstance(value, list):
        return [_portable_with(v, pat) for v in value]
    return value


def write_outputs(manifest: Mapping, out_dir: Path) -> dict[str, Path]:
    """Write JSON, CSV and schema.

    Deterministic: when the file already on disk differs from this manifest
    only in ``generated``, the old timestamp is kept, so rebuilding from
    unchanged inputs leaves every output byte-identical.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"json": out_dir / "corpus_manifest.json",
             "csv": out_dir / "corpus_manifest.csv",
             "schema": out_dir / "corpus_manifest.schema.json"}
    manifest = dict(manifest)
    try:
        old = json.loads(paths["json"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if isinstance(old, dict) and "generated" in old and \
            json.loads(json.dumps(_body(_portable(manifest)))) == _body(old):
        manifest["generated"] = old["generated"]
    paths["json"].write_text(json.dumps(_portable(manifest), indent=1, sort_keys=False) + "\n",
                             encoding="utf-8")
    paths["schema"].write_text(json.dumps(manifest_schema(), indent=1) + "\n",
                               encoding="utf-8")
    rows = flat_rows(manifest)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else [])
    w.writeheader()
    w.writerows(rows)
    paths["csv"].write_text(buf.getvalue(), encoding="utf-8")
    return paths
