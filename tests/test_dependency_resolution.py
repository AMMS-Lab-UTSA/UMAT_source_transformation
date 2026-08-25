"""Multi-file dependency resolution across sibling Fortran sources."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.transform.dependency_resolution import (
    DependencyResolutionError,
    _END_RE,
    combined_source,
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
