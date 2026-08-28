"""Discovery decides what may be used, and it must not decide anything else.

A source that survives this step has been shown to be a distinct,
permissively licensed Fortran file declaring a UMAT entry point. Two failure
modes matter more than the count it produces: reporting a source the
collection already has as a new one, which inflates a generality claim; and
fetching or caching something whose licence does not permit it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from umat_oti.corpus.acquire import REDISTRIBUTABLE_SPDX  # noqa: E402
from umat_oti.corpus.identity import content_identity  # noqa: E402
from discover_umat_sources import (  # noqa: E402
    _has_umat_entry, _hashes, known_identities,
)

# The pinned snapshot, by the convention the rest of the
# suite uses: an absolute path here records this machine's
# home directory in a tracked file.
SNAPSHOT_ROOT = Path(
    os.environ.get("UMAT_OTI_SNAPSHOT_ROOT")
    or REPO_ROOT.parent / "Residual_Assembler" / "sources")


def test_hashes_agree_with_the_identity_registry():
    """Discovery must hash a file exactly as the collection identifies it.

    A different normalisation is a silent duplicate: the same implementation
    gets a different digest and is reported as a new source.
    """
    source = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2" / "umat.for"
    identity = content_identity(source)
    content, code_only = _hashes(source.read_text(errors="replace"), str(source))
    assert content == identity.content_sha256
    assert code_only == identity.code_only_sha256


def test_a_fixed_form_suffix_changes_the_code_only_hash():
    """The fixed-form decision is part of the identity, not a detail."""
    text = "      SUBROUTINE UMAT(STRESS)\nC     a comment\n      END\n"
    _, fixed = _hashes(text, "umat.for")
    _, free = _hashes(text, "umat.f90")
    assert fixed != free, (
        "hashing a .for file as free-form gives a different digest for the "
        "same bytes, and the duplicate is missed")


@pytest.mark.skipif(not SNAPSHOT_ROOT.is_dir(), reason="snapshot root absent")
def test_sources_already_in_the_collection_are_recognised():
    """The regression this exists for: an empty known-set rediscovers everything."""
    known = known_identities(SNAPSHOT_ROOT)
    assert known, "no known implementations were loaded"

    checked = 0
    for name in ("UMATS/UMAT_ECO.for", "UMATS/UMAT_PCL.for", "UMATS/UMAT_PCLK.for"):
        source = SNAPSHOT_ROOT / "permissive/jgomezc1_ABAQUS-US" / name
        if not source.is_file():
            continue
        _, code_only = _hashes(source.read_text(errors="replace"), str(source))
        assert code_only in known, f"{name} is in the corpus but was not recognised"
        checked += 1
    assert checked, "no corpus source was available to check against"


def test_a_umat_entry_is_detected_however_it_is_spaced():
    assert _has_umat_entry("      SUBROUTINE UMAT(STRESS,STATEV)")
    assert _has_umat_entry("      subroutine  umat ( stress )")
    assert _has_umat_entry("      SUBROUTINE\n     & UMAT(STRESS)")
    assert not _has_umat_entry("      SUBROUTINE UEL(RHS,AMATRX)")
    assert not _has_umat_entry("C     this file mentions UMAT only in prose")


def test_the_licence_gate_excludes_what_this_project_may_not_redistribute():
    """GPL-2.0-only is not compatible with this repository's GPL-3.0."""
    assert "GPL-2.0" not in REDISTRIBUTABLE_SPDX
    assert "GPL-2.0-only" not in REDISTRIBUTABLE_SPDX
    assert "" not in REDISTRIBUTABLE_SPDX
    for allowed in ("MIT", "BSD-3-Clause", "Apache-2.0", "GPL-3.0"):
        assert allowed in REDISTRIBUTABLE_SPDX


def test_the_published_manifest_never_claims_a_candidate_is_verified():
    """Discovery reports eligibility, never evidence."""
    import json

    manifest = REPO_ROOT / "paper_results" / "discovery" / "discovered_sources.json"
    if not manifest.is_file():
        pytest.skip("discovery has not been run")
    summary = json.loads(manifest.read_text(encoding="utf-8"))
    caveat = summary.get("caveat", "")
    assert "transformed" in caveat and "verified" in caveat, (
        "the manifest must say plainly that a candidate is not evidence")
    assert summary.get("search_total_reported_by_github") is not None
    assert "search_pages_read" in summary, (
        "a count of what was found is a statement about the search that was "
        "run, and the manifest has to say how much of it was read")


# --------------------------------------------------------------------------- #
# What the discovered sources exposed in the pipeline itself.
# --------------------------------------------------------------------------- #
def test_a_variable_is_never_assigned_two_roles(tmp_path: Path):
    """Regression: sixteen of seventy-one sources aborted with no report.

    The contract builder forces the response variable into "promote", and the
    deformation gradient too when the kinematics are finite -- precisely
    because the classifier may not have put them there, which means they are
    still sitting in whichever list it did choose. Emitting both assignments
    makes a contract the loader rejects with "assigns variable DFGRD1 to
    multiple roles", and the transform aborts before it can report anything.
    Every source that hit it was finite-strain.
    """
    from umat_oti.app.engine import _build_contract

    source = tmp_path / "umat.for"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,DFGRD0,DFGRD1)\n"
        "      DIMENSION STRESS(6),DFGRD1(3,3)\n"
        "      DETF = DFGRD1(1,1)\n"
        "      STRESS(1) = DETF\n"
        "      DDSDDE(1,1) = 1.0\n"
        "      END\n", encoding="utf-8")

    config, _finite = _build_contract(
        "probe", "auto", "STRESS", "DDSDDE", 6, 1, source)
    variables = config["variables"]
    roles = {name: set(variables[name]) for name in
             ("seed", "promote", "constant", "real")}
    overlaps = {
        f"{a} and {b}": sorted(roles[a] & roles[b])
        for a in roles for b in roles if a < b and (roles[a] & roles[b])
    }
    assert not overlaps, f"a variable holds two roles: {overlaps}"


def test_the_forced_names_win_their_role(tmp_path: Path):
    """Precedence, not merely deduplication.

    Dropping the duplicate from "promote" instead of from the lower-priority
    list would resolve the contradiction and quietly stop differentiating the
    response.
    """
    from umat_oti.app.engine import _build_contract

    source = tmp_path / "umat.for"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,DFGRD0,DFGRD1)\n"
        "      DIMENSION STRESS(6),DFGRD1(3,3)\n"
        "      DETF = DFGRD1(1,1)\n"
        "      STRESS(1) = DETF\n"
        "      DDSDDE(1,1) = 1.0\n"
        "      END\n", encoding="utf-8")
    config, finite = _build_contract(
        "probe", "auto", "STRESS", "DDSDDE", 6, 1, source)
    variables = config["variables"]
    assert "STRESS" in variables["promote"], "the response must carry a derivative"
    if finite:
        assert "DFGRD1" in variables["promote"], (
            "a finite-strain source differentiates the deformation gradient")
        assert "DFGRD1" not in variables["real"]
    assert variables["seed"] == ["DSTRAN"]
    assert "DSTRAN" not in variables["promote"]
