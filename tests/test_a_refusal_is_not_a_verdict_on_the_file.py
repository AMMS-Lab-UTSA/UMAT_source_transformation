"""A transform refusal says the transformer could not convert a file.

It does not say the file is not a UMAT. It does not say the file is broken. It
does not say a module was never published beside it. Each of those is a claim
about somebody else's repository, each needs its own evidence, and reading a
refusal as any of them moves work out of this project's column and into the
corpus's -- the one direction the error must never go.

So every one of the 112 refused sources was classified by parsing the file:
its Abaqus entry point read from the source text, its lines matched against
every other acquired source, and an offline ifort ``-syntax-only`` pass over
the author's own text with Abaqus's real ``aba_param.inc`` on the include path
and the companions the repository does publish compiled ahead of it. No Abaqus
process was started and no licence token was drawn.

The measured split, from ``paper_results/corpus/corpus_registry.json``:

    genuine_umat                   63   ours: a whole UMAT we could not convert
    missing_external_dependency    16   a USE or INCLUDE nobody published
    helper_or_module_only          14   no Abaqus entry point at all
    incomplete_or_corrupt_source   11   ifort rejects the published text
    duplicate_of_another_source     4   line-for-line a copy of another source
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


# ---------------------------------------------------------------------------
# provenance: a classification nobody can trace back is an assertion
# ---------------------------------------------------------------------------
