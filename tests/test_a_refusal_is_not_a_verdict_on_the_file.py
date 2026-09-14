"""A transform refusal says the transformer could not convert a file.

It does not say the file is not a UMAT. It does not say the file is broken. It
does not say a module was never published beside it. Each of those is a claim
about somebody else's repository, each needs its own evidence, and reading a
refusal as any of them moves work out of this project's column and into the
corpus's -- the one direction the error must never go.

So every one of the 151 refused sources was classified by parsing the file:
its Abaqus entry point read from the source text, its lines matched against
every other acquired source, and an offline ifort ``-syntax-only`` pass over
the author's own text with Abaqus's real ``aba_param.inc`` on the include path
and the companions the repository does publish compiled ahead of it. No Abaqus
process was started and no licence token was drawn.

The measured split, from ``paper_results/corpus/corpus_registry.json``:

    genuine_umat                  100   ours: a whole UMAT we could not convert
    missing_external_dependency    16   a USE or INCLUDE nobody published
    helper_or_module_only          14   no Abaqus entry point at all
    incomplete_or_corrupt_source   11   ifort rejects the published text
    duplicate_of_another_source     6   line-for-line a copy of another source
    other_abaqus_routine            2   the entry point is a UEL
    published_stub_...              2   the UMAT body computes nothing at all
"""
import csv
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from umat_oti.corpus.entry_routines import (DUPLICATE_SOURCE,  # noqa: E402
                                            GENUINE_UMAT,
                                            HELPER_OR_MODULE_ONLY,
                                            INCOMPLETE_OR_CORRUPT,
                                            MISSING_EXTERNAL_DEPENDENCY,
                                            OTHER_ABAQUS_ROUTINE,
                                            PUBLISHED_STUB,
                                            REFUSAL_CLASSES, classify,
                                            classify_refusal)

REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"
CACHE = Path(__import__("os").environ.get("UMAT_OTI_DISCOVERY_CACHE")
             or REPO.parent / "discovery_cache")


def registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def refusals():
    return [r for r in registry()["records"] if r["refusal_class"]]


def cached(source_id: str):
    path = CACHE / source_id
    if not path.is_file():
        pytest.skip(f"{source_id} is not in the discovery cache")
    return path


# ---------------------------------------------------------------------------
# the rule itself
# ---------------------------------------------------------------------------
def test_not_a_umat_is_never_reached_from_a_transform_refusal():
    """Every refused source whose terminal state is ``not_a_umat`` got there
    because PARSING the file found an Abaqus entry point that is not a UMAT,
    or found none at all -- 2 UELs, 1 second copy of a UEL, and 14 files with
    no Abaqus interface. None got there because the transformer refused it,
    and every one quotes the line of the author's own file it was read
    from."""
    external = [r for r in refusals() if r["terminal_state"] == "not_a_umat"]
    assert external, "no refused source reached not_a_umat at all"
    for record in external:
        assert record["refusal_class"] in (
            OTHER_ABAQUS_ROUTINE, HELPER_OR_MODULE_ONLY, DUPLICATE_SOURCE), (
                record["source_id"], record["refusal_class"])
        assert record["entry_evidence"], (
            f"{record['source_id']} is called not_a_umat and quotes nothing")
        assert record["is_umat"] is False


def test_the_same_refusal_text_classifies_two_files_differently():
    """`classify_refusal` takes no refusal text at all, which is the only
    way to be sure the refusal cannot leak into the answer. Measured on two
    files the batch refused with the same wording family: a 36-argument UEL
    and a 37-argument UMAT come out as different classes."""
    uel = classify(cached("jgomezc1__ABAQUS-US/UELS/UEL8_VPDCL.for")
                   .read_text(errors="replace"),
                   path=cached("jgomezc1__ABAQUS-US/UELS/UEL8_VPDCL.for"))
    umat_path = cached("AnargyrosKarakalas__UMAT_3D/"
                       "UMAT_3D_Coupled_ML_IP_Original.for")
    umat = classify(umat_path.read_text(errors="replace"), path=umat_path)

    assert classify_refusal(uel, text_rejected=False).refusal_class == \
        OTHER_ABAQUS_ROUTINE
    assert classify_refusal(umat, text_rejected=False).refusal_class == \
        GENUINE_UMAT

    import inspect
    parameters = inspect.signature(classify_refusal).parameters
    assert "reason" not in parameters and "refusal" not in parameters, (
        "classify_refusal grew a way to be told why the transform refused")


def test_a_refused_umat_that_builds_stays_this_project_s_problem():
    """100 of the 151 are whole UMATs whose published text ifort accepts,
    whose companions are all in the repository, and which do compute a stress
    or a tangent somewhere in the file. They stay ``transform_refused`` and
    ``internal``: there is nothing wrong with those files, and the work is
    ours."""
    ours = [r for r in refusals() if r["refusal_class"] == GENUINE_UMAT]
    assert len(ours) == 100, len(ours)
    for record in ours:
        assert record["terminal_state"] == "transform_refused"
        assert record["kind"] == "internal"
        assert record["is_umat"] is True
        assert record["entry_interface"] == "UMAT"


def test_the_refusal_classes_partition_the_141_refusals():
    """151 refusals, seven classes, every record in exactly one, and the class
    names are the ones the module defines rather than free text."""
    rows = refusals()
    assert len(rows) == 151, len(rows)
    counts = {}
    for record in rows:
        assert record["refusal_class"] in REFUSAL_CLASSES, record
        counts[record["refusal_class"]] = counts.get(
            record["refusal_class"], 0) + 1
    assert counts == {
        GENUINE_UMAT: 100,
        MISSING_EXTERNAL_DEPENDENCY: 16,
        HELPER_OR_MODULE_ONLY: 14,
        INCOMPLETE_OR_CORRUPT: 11,
        DUPLICATE_SOURCE: 6,
        OTHER_ABAQUS_ROUTINE: 2,
        PUBLISHED_STUB: 2,
    }, counts
    assert sum(counts.values()) == 151


def test_every_refused_source_quotes_the_line_it_was_classified_from():
    """A classification nobody can check is an assertion. All 151 carry the
    line of the author's own file that decided it, and that line really is in
    that file at the line number recorded beside it."""
    for record in refusals():
        assert record["entry_evidence"], record["source_id"]
        assert record["classification_basis"], record["source_id"]
        if record["refusal_class"] in (INCOMPLETE_OR_CORRUPT,):
            continue                  # the evidence is the compiler's, below
        if record["refusal_class"] == DUPLICATE_SOURCE:
            continue                  # the evidence is the other copy
        path = CACHE / record["source_id"]
        if not path.is_file() or not record["entry_line"]:
            continue
        line = path.read_text(errors="replace").splitlines()[
            record["entry_line"] - 1]
        assert record["entry_evidence"].strip()[:60] in line, (
            record["source_id"], record["entry_line"])


# ---------------------------------------------------------------------------
# what the parse has to get right for any of the above to mean anything
# ---------------------------------------------------------------------------
def test_a_uel_whose_private_kernel_is_called_umat_is_not_a_umat():
    """jgomezc1__ABAQUS-US/UELS/UEL8_VPDCL.for defines a 36-argument
    SUBROUTINE UEL at line 43 and a 37-argument SUBROUTINE UMAT at line 276
    that the UEL calls as its own constitutive kernel. Driven through a
    *USER MATERIAL deck, Abaqus resolves the global symbol UMAT to that
    kernel and the finite difference perturbs a deformation gradient it never
    reads."""
    path = cached("jgomezc1__ABAQUS-US/UELS/UEL8_VPDCL.for")
    found = classify(path.read_text(errors="replace"), path=path)
    assert found.entry_interface == "UEL"
    assert found.entry_line == 43
    assert "SUBROUTINE UEL" in found.entry_text
    assert not found.is_umat
    assert not classify_refusal(found, text_rejected=False).is_umat


def test_a_free_form_umat_in_a_dot_for_file_is_still_a_umat():
    """Four sources under sahmotaman__TMM-FE-Simulation are free-form Fortran
    named ``.for``. The form detector sees both free and fixed evidence and
    falls back to the suffix, so it reads them as fixed -- and read as fixed,
    the continued 37-argument header comes out as UMAT with ZERO arguments,
    fails the interface check, and files four genuine Abaqus UMATs as
    helpers. Measured: under fixed form the parse finds 0 arguments; the
    retry under free form finds 37 at line 33."""
    path = cached("sahmotaman__TMM-FE-Simulation/Abaqus User Material "
                  "Subroutines/Abaqus Standard - UMAT/UMAT - Strain-based "
                  "Return Mapping - Fully-Implicit/umat_subroutine.for")
    text = path.read_text(errors="replace")

    misread = classify(text, form="fixed", path=path)
    assert misread.kind == "helper_only"
    assert [u.argument_count for u in misread.units] == [0]

    found = classify(text, path=path)
    assert found.is_umat, found.reason
    assert found.entry_line == 33
    assert found.source_form == "free"
    assert found.entry_text.startswith("subroutine umat(")


def test_a_file_too_damaged_to_parse_is_not_filed_as_a_helper():
    """The five mkhadijeh26 sources write their UMAT continuation markers in
    column 9, where fixed-form Fortran has no continuation field. Nothing
    parses, so a rule that read "no program unit" as "a helper" would call
    five attempted UMATs not_a_umat -- an external verdict, on evidence that
    is really about the file being unbuildable. With the compiler's answer in
    hand they come out as incomplete_or_corrupt_source instead.

    The sixth refused file in that repository -- the ABAQUS_DSR_EXAMPLE copy
    of ViscoelasticityCode3.f -- has the same markers in column 6 and ifort
    accepts it, so it stays genuine_umat. That is the discrimination the
    compile evidence buys: the same repository, the same filename, opposite
    answers, and neither of them read off the refusal."""
    damaged = [r for r in refusals()
               if r["source_id"].startswith("mkhadijeh26__")]
    assert len(damaged) == 6, len(damaged)
    corrupt = [r for r in damaged
               if r["refusal_class"] == INCOMPLETE_OR_CORRUPT]
    assert len(corrupt) == 5, [r["source_id"] for r in damaged]
    for record in corrupt:
        assert record["terminal_state"] == "incomplete_or_corrupt_source"
        assert record["kind"] == "external"
        assert record["is_umat"] is True, (
            "a UMAT that does not build is a UMAT that does not build, not a "
            "file that is not a UMAT")
    survivor = [r for r in damaged if r not in corrupt]
    assert len(survivor) == 1 and survivor[0]["refusal_class"] == GENUINE_UMAT

    from umat_oti.corpus.entry_routines import Classification, NO_PROGRAM_UNIT
    unreadable = Classification(kind=NO_PROGRAM_UNIT)
    assert classify_refusal(unreadable, text_rejected=True).refusal_class == \
        INCOMPLETE_OR_CORRUPT
    assert classify_refusal(unreadable, text_rejected=None).refusal_class == \
        HELPER_OR_MODULE_ONLY


def test_a_compile_that_settles_nothing_leaves_the_work_ours():
    """Nine refused sources fail the offline compile with diagnostics an
    unresolved USE would also produce -- an undeclared name, a kind parameter
    that is not constant. None of those is evidence the file is broken, so
    the verdict stays genuine_umat with ``refusal_class_confident`` false:
    this project's unfinished work, overstated rather than the corpus's
    completeness."""
    unsure = [r for r in refusals()
              if r["refusal_class_confident"] is False]
    assert len(unsure) == 9, [r["source_id"] for r in unsure]
    for record in unsure:
        # One of the nine is a second copy of another of them. A duplicate
        # keeps the underlying answer -- "as a file it is genuine_umat" is
        # written into its basis -- so an unsettled compile leaves that one
        # ours too, which is the same safe direction.
        assert record["refusal_class"] in (GENUINE_UMAT, DUPLICATE_SOURCE), \
            record["source_id"]
        if record["refusal_class"] == DUPLICATE_SOURCE:
            assert f"as a file it is {GENUINE_UMAT}" in \
                record["classification_basis"], record["source_id"]
        assert record["kind"] == "internal"


def test_a_second_copy_of_a_uel_is_still_not_a_umat():
    """jgomezc1__ABAQUS-US/UELS/UEL9_VPDCL.for is line-for-line
    HIT-FSW-314__abaqus/abaqus-umat/uel/UEL9_VPDCL.for. It is filed as a
    duplicate, and the duplicate keeps the underlying answer: a copy of a UEL
    is a UEL, and collapsing that into "duplicate" would let it back into a
    count of UMATs."""
    duplicates = [r for r in refusals()
                  if r["refusal_class"] == DUPLICATE_SOURCE]
    assert len(duplicates) == 6, len(duplicates)
    for record in duplicates:
        assert record["duplicate_of"], record["source_id"]
        assert record["duplicate_of"] != record["source_id"]
    uel = [r for r in duplicates if "UEL9_VPDCL" in r["source_id"]]
    assert uel and uel[0]["is_umat"] is False
    assert uel[0]["terminal_state"] == "not_a_umat"


def test_the_duplicate_digest_does_not_collapse_fortran_columns(tmp_path):
    """In fixed-form Fortran a column carries meaning. A digest that collapsed
    runs of whitespace made a file whose continuation markers sit in column 9
    -- which no compiler accepts -- come out identical to one whose markers
    sit in column 6, and filed a corrupt source as a duplicate of a working
    one. Only trailing whitespace and the CR of a CRLF may be removed."""
    from build_corpus_registry import _line_identity

    good = tmp_path / "good.f"
    bad = tmp_path / "bad.f"
    good.write_text("      SUBROUTINE UMAT(A,\n     1 B)\n      END\n")
    bad.write_text("      SUBROUTINE UMAT(A,\n        1 B)\n      END\n")
    assert _line_identity(good) != _line_identity(bad)

    crlf = tmp_path / "crlf.f"
    crlf.write_bytes(b"      SUBROUTINE UMAT(A,\r\n     1 B)   \r\n      END\r\n")
    assert _line_identity(good) == _line_identity(crlf)


# ---------------------------------------------------------------------------
# provenance: a classification nobody can trace back is an assertion
# ---------------------------------------------------------------------------
def test_every_record_names_where_the_file_came_from():
    """All 391 records carry the repository, the path inside the acquisition
    cache, the 40-character commit the acquisition pinned, the licence it was
    read under, the sha256 of the bytes, and an acquisition URL -- with
    ``url_provenance`` saying the URL was reconstructed from that commit
    rather than recorded, because a derived URL presented as a recorded one is
    a difference a reader cannot detect."""
    records = registry()["records"]
    assert len(records) == 391
    for record in records:
        assert record["repository"], record["source_id"]
        assert record["cache_path"] == record["source_id"]
        assert len(record["commit"]) == 40, record["source_id"]
        assert record["license_spdx"], record["source_id"]
        assert len(record["sha256"]) == 64, record["source_id"]
        assert record["acquisition_url"].startswith("https://github.com/")
        assert record["commit"] in record["acquisition_url"]
        assert "reconstructed from the commit" in record["url_provenance"]
    assert registry()["summary"]["records_without_an_acquisition_url"] == []


def test_the_companions_a_umat_needs_are_recorded_beside_it():
    """A source is not only its own file. Every record carries the companion
    units the repository publishes beside it and, where something it USEs or
    INCLUDEs was never published, names that instead -- which is what
    separates the 16 ``missing_external_dependency`` refusals from the 96 that
    are ours."""
    missing = [r for r in refusals()
               if r["refusal_class"] == MISSING_EXTERNAL_DEPENDENCY]
    assert len(missing) == 16, len(missing)
    for record in missing:
        assert record["missing_companions"], record["source_id"]
        assert record["terminal_state"] == "external_dependency_unavailable"
        assert record["kind"] == "external"
        assert record["is_umat"] is True, (
            "a UMAT whose module was never published is still a UMAT")


def test_the_offline_audit_never_starts_abaqus():
    """The compile evidence is an ifort ``-syntax-only`` pass. Abaqus's own
    aba_param.inc is READ off the disk, which starts no process and draws no
    licence token; nothing in the audit path invokes the abaqus launcher."""
    text = (REPO / "tools" / "build_corpus_registry.py").read_text()
    audit = text.split("def offline_syntax_audit")[1].split("\ndef summarise")[0]
    for forbidden in ('"abaqus"', "abaqus job=", "abaqus make",
                      "abaqus information"):
        assert forbidden not in audit, forbidden
    assert "-syntax-only" in text
