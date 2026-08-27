"""Multi-file dependency resolution across sibling Fortran sources."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.transform.dependency_resolution import (
    DependencyResolutionError,
    _END_RE,
    combined_source,
    declared_donor_files,
    index_sources,
    infer_minimum_dimensions,
    resolve_closure,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

ENTRY = """\
      SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, NTENS, NSTATV, PROPS)
      DIMENSION STRESS(NTENS), STATEV(NSTATV), DDSDDE(NTENS,NTENS)
      DIMENSION PROPS(2)
      CALL KCLEAR(DDSDDE, NTENS, NTENS)
      DO K1 = 1, NTENS
        STRESS(K1) = PROPS(1)
      END DO
      CALL KSCALE(STRESS, NTENS, PROPS(2))
      CALL XIT
      RETURN
      END
"""

HELPERS = """\
      SUBROUTINE KCLEAR(A, N, M)
      DIMENSION A(N,M)
      DO I = 1, N
        DO J = 1, M
          A(I,J) = 0.0D0
        END DO
      END DO
      RETURN
      END
      SUBROUTINE KSCALE(V, N, F)
      DIMENSION V(N)
      DO I = 1, N
        V(I) = V(I) * F
      END DO
      RETURN
      END
"""


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    (tmp_path / "entry.for").write_text(ENTRY, encoding="utf-8")
    (tmp_path / "helpers.for").write_text(HELPERS, encoding="utf-8")
    return tmp_path


def test_end_do_is_not_the_end_of_a_routine():
    """Regression: the routine span stopped at its first loop.

    "END DO" and "END IF" are block terminators. Treating them as the end of a
    program unit truncates the routine there, so every CALL below the first loop
    disappears -- UMAT_PCO appeared to call one helper when it calls seven, and
    the build then failed at link with thirty-nine undefined references.
    """
    assert _END_RE.match("      END")
    assert _END_RE.match("      END SUBROUTINE UMAT")
    assert _END_RE.match("  901 END")
    assert not _END_RE.match("      END DO")
    assert not _END_RE.match("      END IF")
    assert not _END_RE.match("      ENDDO")


def test_closure_spans_sibling_files(tree: Path):
    graph = resolve_closure(tree / "entry.for", entry="UMAT", roots=[tree])
    assert graph.is_multi_file
    assert set(graph.resolved) == {"UMAT", "KCLEAR", "KSCALE"}
    assert not graph.missing
    assert graph.runtime_calls == ("XIT",)


def test_calls_below_the_first_loop_are_found(tree: Path):
    """KSCALE is called after an END DO; it must still be in the closure."""
    graph = resolve_closure(tree / "entry.for", entry="UMAT", roots=[tree])
    assert "KSCALE" in graph.edges["UMAT"]


def test_missing_dependency_names_caller_and_searched_roots(tmp_path: Path):
    (tmp_path / "entry.for").write_text(ENTRY, encoding="utf-8")
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    symbols = {m.symbol for m in graph.missing}
    assert {"KCLEAR", "KSCALE"} <= symbols
    diagnostic = next(m for m in graph.missing if m.symbol == "KSCALE").as_dict()
    assert "UMAT" in diagnostic["called_by"]
    assert diagnostic["searched_roots"]
    assert "KSCALE" in diagnostic["diagnostic"]


def test_identical_duplicates_do_not_block_but_differing_ones_do(tmp_path: Path):
    (tmp_path / "entry.for").write_text(ENTRY, encoding="utf-8")
    (tmp_path / "a.for").write_text(HELPERS, encoding="utf-8")
    (tmp_path / "b.for").write_text(HELPERS, encoding="utf-8")
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert not graph.conflicts, "identical bodies must not be reported as a conflict"
    assert any(d.resolution == "identical" for d in graph.duplicates)

    (tmp_path / "b.for").write_text(
        HELPERS.replace("V(I) * F", "V(I) * F * 2.0D0"), encoding="utf-8")
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert {d.symbol for d in graph.conflicts} == {"KSCALE"}


def test_a_local_definition_wins_and_is_not_a_conflict(tmp_path: Path):
    """The entry file's own definition is the one the compiler sees."""
    (tmp_path / "entry.for").write_text(ENTRY + HELPERS, encoding="utf-8")
    (tmp_path / "other.for").write_text(
        HELPERS.replace("V(I) * F", "V(I) * F * 3.0D0"), encoding="utf-8")
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert not graph.conflicts
    assert graph.resolved["KSCALE"].path == tmp_path / "entry.for"


def test_combined_source_does_not_repeat_local_definitions(tmp_path: Path):
    (tmp_path / "entry.for").write_text(ENTRY + HELPERS, encoding="utf-8")
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    text = combined_source(graph)
    assert text.upper().count("SUBROUTINE KSCALE") == 1


def test_dimension_inference_reads_loop_bounds(tmp_path: Path):
    """Regression: NSTATV was understated and the driver allocated too little.

    UMAT_PCL copies its back stress with "DO K1=10,2*NTENS+5". Reading only
    literal subscripts missed that, the driver allocated 9 slots, the source
    read STATEV(10..13) past the end, and the real part it found there happened
    to be zero -- so primal parity passed while the derivatives came back around
    1e222.
    """
    source = tmp_path / "s.for"
    source.write_text(
        "      SUBROUTINE UMAT(STATEV, NTENS)\n"
        "      DIMENSION STATEV(1)\n"
        "      DO K1=10,2*NTENS+5\n"
        "        STATEV(K1)=0.0D0\n"
        "      END DO\n"
        "      END\n", encoding="utf-8")
    dimensions = infer_minimum_dimensions([source])
    assert "2*NTENS+5" in dimensions["statev_terms"]
    assert dimensions["minimum_nstatv_for"]["4"] == 13


def test_dimension_inference_reads_literal_tangent_indices(tmp_path: Path):
    source = tmp_path / "s.for"
    source.write_text(
        "      SUBROUTINE UMAT(DDSDDE)\n"
        "      DDSDDE(6,6)=1.0D0\n"
        "      END\n", encoding="utf-8")
    assert infer_minimum_dimensions([source])["minimum_ntens"] == 6


def test_entry_not_found_names_what_the_file_does_define(tmp_path: Path):
    (tmp_path / "helpers.for").write_text(HELPERS, encoding="utf-8")
    with pytest.raises(DependencyResolutionError) as excinfo:
        resolve_closure(tmp_path / "helpers.for", entry="UMAT")
    assert excinfo.value.code == "entry_routine_not_found"
    assert "KSCALE" in excinfo.value.detail


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_resolved_closure_compiles_when_the_entry_alone_does_not(tree: Path, tmp_path):
    """The point of the resolver, checked by the compiler rather than by reading."""
    from umat_oti.validation.parameter_sensitivity_validation import ABA_PARAM

    (tree / "ABA_PARAM.INC").write_text(ABA_PARAM, encoding="utf-8")
    flags = ["-O1", "-std=legacy", "-ffixed-form", "-ffixed-line-length-none",
             "-I", str(tree)]

    alone = subprocess.run(
        ["gfortran", *flags, str(tree / "entry.for"), "-o", str(tree / "alone")],
        capture_output=True, text=True)
    assert alone.returncode != 0
    assert "undefined reference" in alone.stderr

    graph = resolve_closure(tree / "entry.for", entry="UMAT", roots=[tree])
    resolved = tree / "resolved.for"
    resolved.write_text(combined_source(graph), encoding="utf-8")
    compiled = subprocess.run(
        ["gfortran", *flags, "-c", str(resolved), "-o", str(tree / "resolved.o")],
        capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr


@pytest.mark.slow
@pytest.mark.skipif(
    not (REPO_ROOT.parent / "Residual_Assembler" / "sources" / "permissive"
         / "jgomezc1_ABAQUS-US" / "UMATS" / "UMAT_PCO.for").is_file(),
    reason="pinned external corpus snapshot is not checked out")
def test_real_helper_heavy_icp_umat_resolves_completely():
    """UMAT_PCO calls seven helpers and defines none of them."""
    root = (REPO_ROOT.parent / "Residual_Assembler" / "sources" / "permissive"
            / "jgomezc1_ABAQUS-US" / "UMATS")
    graph = resolve_closure(root / "UMAT_PCO.for", entry="UMAT", roots=[root])
    assert graph.is_multi_file
    assert not graph.missing, [m.symbol for m in graph.missing]
    assert not graph.conflicts, [d.symbol for d in graph.conflicts]
    for helper in ("KCLEAR", "KMMULT", "KMTRAN", "KMAVEC", "KUPDVEC",
                   "KSMULT", "KMATSUB"):
        assert helper in graph.resolved, helper
    assert len(graph.external_definitions) >= 7


# --- donors the source names for itself ------------------------------------
#
# A fixed-form project with no makefile states its own build in a file-scope
# INCLUDE manifest between program units. That is the source answering "which
# of these definitions do I mean", and it outranks anything a directory sweep
# turns up, because the compiler splices in those files and no other.

MANIFEST_ENTRY = ENTRY.replace(
    "      END\n", "      END\n\n      include 'chosen.for'\n")


def test_a_donor_the_source_names_wins_over_a_swept_sibling(tmp_path: Path):
    """The manifest sits between program units, where no routine body reaches.

    Scanning only routine bodies discarded the declaration, the resolver then
    swept the siblings, found two definitions that disagree, and refused to
    choose -- a choice the source had already made for itself.
    """
    (tmp_path / "entry.for").write_text(MANIFEST_ENTRY, encoding="utf-8")
    (tmp_path / "chosen.for").write_text(HELPERS, encoding="utf-8")
    (tmp_path / "other.for").write_text(
        HELPERS.replace("V(I) * F", "V(I) * F * 7.0D0"), encoding="utf-8")

    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert not graph.conflicts, [d.symbol for d in graph.conflicts]
    assert graph.resolved["KSCALE"].path == tmp_path / "chosen.for"
    assert graph.resolved["KCLEAR"].path == tmp_path / "chosen.for"
    settled = next(d for d in graph.duplicates if d.symbol == "KSCALE")
    assert settled.resolution == "declared"
    assert not settled.bodies_agree, (
        "the definitions really do differ; the source picked one, the resolver "
        "did not")


def test_two_donors_the_source_did_not_name_still_conflict(tmp_path: Path):
    """The relaxation is narrow: it applies only to what the source named."""
    (tmp_path / "entry.for").write_text(MANIFEST_ENTRY, encoding="utf-8")
    # The manifest names a file that defines neither helper, so both are found
    # only by sweeping, and the sweep finds two bodies that disagree.
    (tmp_path / "chosen.for").write_text(
        "      SUBROUTINE KUNRELATED(X)\n      X = 1.0D0\n      RETURN\n"
        "      END\n", encoding="utf-8")
    (tmp_path / "a.for").write_text(HELPERS, encoding="utf-8")
    (tmp_path / "b.for").write_text(
        HELPERS.replace("V(I) * F", "V(I) * F * 7.0D0"), encoding="utf-8")

    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert {d.symbol for d in graph.conflicts} == {"KSCALE"}


def test_a_source_that_names_two_disagreeing_donors_is_still_ambiguous(
        tmp_path: Path):
    """Naming both sides of a disagreement settles nothing; it is a contradiction."""
    (tmp_path / "entry.for").write_text(
        ENTRY.replace("      END\n",
                      "      END\n\n      include 'a.for'\n      include 'b.for'\n"),
        encoding="utf-8")
    (tmp_path / "a.for").write_text(HELPERS, encoding="utf-8")
    (tmp_path / "b.for").write_text(
        HELPERS.replace("V(I) * F", "V(I) * F * 7.0D0"), encoding="utf-8")

    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert {d.symbol for d in graph.conflicts} == {"KSCALE"}


def test_a_local_definition_still_outranks_a_named_donor(tmp_path: Path):
    (tmp_path / "entry.for").write_text(MANIFEST_ENTRY + HELPERS, encoding="utf-8")
    (tmp_path / "chosen.for").write_text(
        HELPERS.replace("V(I) * F", "V(I) * F * 7.0D0"), encoding="utf-8")
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert not graph.conflicts
    assert graph.resolved["KSCALE"].path == tmp_path / "entry.for"
    assert next(d for d in graph.duplicates
                if d.symbol == "KSCALE").resolution == "local"


def test_the_manifest_is_followed_transitively_and_relative_to_its_own_file(
        tmp_path: Path):
    """An included file may name further files, resolved next to *it*."""
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "entry.for").write_text(
        ENTRY.replace("      END\n", "      END\n\n      include 'nested/mid.for'\n"),
        encoding="utf-8")
    # 'deep.for' is named by mid.for, so it resolves inside nested/, not beside
    # the entry file.
    (nested / "mid.for").write_text("      include 'deep.for'\n", encoding="utf-8")
    (nested / "deep.for").write_text(HELPERS, encoding="utf-8")
    (tmp_path / "deep.for").write_text(
        HELPERS.replace("V(I) * F", "V(I) * F * 7.0D0"), encoding="utf-8")

    declared = declared_donor_files(tmp_path / "entry.for")
    assert nested / "deep.for" in declared
    assert tmp_path / "deep.for" not in declared
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert not graph.conflicts
    assert graph.resolved["KSCALE"].path == nested / "deep.for"


def test_a_commented_out_include_is_not_a_declaration(tmp_path: Path):
    (tmp_path / "entry.for").write_text(
        ENTRY.replace("      END\n", "      END\n\nC     include 'chosen.for'\n"),
        encoding="utf-8")
    (tmp_path / "chosen.for").write_text(HELPERS, encoding="utf-8")
    assert declared_donor_files(tmp_path / "entry.for") == ()


def test_an_include_that_is_not_on_disk_is_not_a_resolution_failure(tmp_path: Path):
    """A missing include is the compiler's diagnostic to make, not this one's."""
    (tmp_path / "entry.for").write_text(
        ENTRY.replace("      END\n", "      END\n\n      include 'absent.for'\n"),
        encoding="utf-8")
    (tmp_path / "helpers.for").write_text(HELPERS, encoding="utf-8")
    graph = resolve_closure(tmp_path / "entry.for", entry="UMAT", roots=[tmp_path])
    assert declared_donor_files(tmp_path / "entry.for") == ()
    assert not graph.missing
    assert graph.resolved["KSCALE"].path == tmp_path / "helpers.for"


CORPUS_ROOT = Path(
    os.environ.get("UMAT_OTI_CORPUS_ROOT")
    or REPO_ROOT.parent / "Residual_Assembler" / "sources")
OXFORD = CORPUS_ROOT / "permissive" / "ngrilli_Oxford_Crystal_Plasticity"


@pytest.mark.slow
@pytest.mark.skipif(not (OXFORD / "umat.for").is_file(),
                    reason="pinned external corpus snapshot is not checked out")
def test_real_source_with_a_file_scope_manifest_settles_its_own_donors():
    """The Oxford crystal-plasticity UMAT names its donors and means it.

    kmat.f and kMaterialParam.f exist several times over in this repository --
    per-example override sets under ExampleInputFiles, a different metal and a
    different flow rule in each. Those really do disagree and choosing between
    them by sweeping directories would pick the physics at random. The entry
    file settles it in its own manifest, and the copies it does not name are
    never compiled.
    """
    graph = resolve_closure(OXFORD / "umat.for", entry="UMAT", roots=[OXFORD])
    assert not graph.missing, [m.symbol for m in graph.missing]
    assert not graph.conflicts, [d.symbol for d in graph.conflicts]
    for helper in ("KMAT", "KMATERIALPARAM"):
        settled = next(d for d in graph.duplicates if d.symbol == helper)
        assert len(settled.definitions) > 1, helper
        assert not settled.bodies_agree, helper
        assert settled.resolution == "declared", helper
        assert graph.resolved[helper].path.parent == OXFORD, helper
    assert not any("ExampleInputFiles" in str(d.path)
                   for d in graph.resolved.values())
