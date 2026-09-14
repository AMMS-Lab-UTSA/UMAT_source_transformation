"""Four sources the registry called `genuine_umat` that the transformer said
had no UMAT anchor in them. Both statements cannot be true, so each was
settled by parsing the file.

The transformer's own report, at fingerprint 668e7e64c1371b47, refuses 18
sources with a reason that begins ``anchors not located``. Nine of those say
``selected_routine_is_not_an_abaqus_umat`` and the registry already agreed
with every one of them. The other nine say the stress update and the DDSDDE
extraction point could not be found, and exactly four of those nine were
classed ``genuine_umat``:

* ``baw-de__poroMechanicalFoam/abaqusUMATs/abaqusUmatMohrCoulomb/MohrCoulombAbaqus.for``
* ``matmodlab__matmodlab2/matmodlab2/umat/umats/umat_stub.f90``
* ``sas229__geomat/tests/umat_integration.f90``
* ``zning8251-jpg__ufc-fem-kernel/docs/.../Adapters/Material/Adapters/UMAT_Adapter.f90``

**The registry was right about one of the four and wrong about three, and the
three were wrong in two different ways.**

1. MohrCoulombAbaqus.for is a 1694-line Mohr-Coulomb return mapping. It writes
   ``DDSDDE = Depc`` at line 229 and ``STRESS = SigC`` at line 230 -- the
   whole-array form, with no subscript. The registry's classification stands
   and the gap is in the transformer's anchor locator. That finding belongs to
   whoever owns the transform, and nothing here edits it.

2. umat_stub.f90 and the UMAT_Adapter.f90 stub present the 37-argument Abaqus
   interface and assign neither output anywhere, and make no CALL through
   which either could be assigned. They are templates their authors published.
   ``genuine_umat`` said this project owed a transform on a file that contains
   nothing to transform.

3. umat_integration.f90 is a ``program main`` whose ``subroutine umat`` sits
   inside an INTERFACE block, declaring a routine implemented in a C++ library
   the repository does not publish as Fortran. The parser read a declaration
   as a definition.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from umat_oti.corpus.entry_routines import (GENUINE_UMAT,  # noqa: E402
                                            HELPER_OR_MODULE_ONLY,
                                            PUBLISHED_STUB, classify,
                                            classify_refusal, program_units,
                                            umat_outputs_written)

CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
             or REPO.parent / "discovery_cache")
REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"

MOHR = ("baw-de__poroMechanicalFoam/abaqusUMATs/abaqusUmatMohrCoulomb/"
        "MohrCoulombAbaqus.for")
STUB = "matmodlab__matmodlab2/matmodlab2/umat/umats/umat_stub.f90"
DRIVER = "sas229__geomat/tests/umat_integration.f90"
ADAPTER = ("zning8251-jpg__ufc-fem-kernel/docs/02_Developer_Guide/"
           "Legacy_Adapters_Reference/Adapters/Material/Adapters/"
           "UMAT_Adapter.f90")


def cached(source_id: str) -> Path:
    path = CACHE / source_id
    if not path.is_file():
        pytest.skip(f"{source_id} is not in the discovery cache")
    return path


def record(source_id: str) -> dict:
    if not REGISTRY.is_file():
        pytest.skip("the registry has not been built")
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]
    found = [r for r in rows if r["source_id"] == source_id]
    assert found, source_id
    return found[0]


# ---------------------------------------------------------------------------
# 1. the one the registry got right
# ---------------------------------------------------------------------------
def test_a_whole_array_stress_update_is_a_stress_update():
    """The transformer could not find a stress update in MohrCoulombAbaqus.for
    and the registry called it a genuine UMAT. The registry is right: the file
    writes both outputs, in the whole-array form.

    This is the one of the four where the answer is "the transformer has work
    to do". It stays `genuine_umat` and `transform_refused`, which is
    INTERNAL, because a refusal on a file that plainly computes a stress is a
    fact about the transformer."""
    path = cached(MOHR)
    text = path.read_text(errors="replace")
    lines = text.splitlines()

    assert lines[228].strip().startswith("DDSDDE"), lines[228]
    assert "= Depc" in lines[228]
    assert lines[229].strip().startswith("STRESS"), lines[229]
    assert "= SigC" in lines[229]

    outputs = umat_outputs_written(text, path=path)
    assert outputs.writes_stress and outputs.writes_ddsdde
    assert outputs.first_write_line == 229
    assert not outputs.is_declaration_only
    assert outputs.logical_lines > 600, outputs.logical_lines

    found = classify(text, path=path)
    assert found.is_umat and found.entry_interface == "UMAT"
    verdict = classify_refusal(found, text_rejected=False, outputs=outputs)
    assert verdict.refusal_class == GENUINE_UMAT

    held = record(MOHR)
    assert held["refusal_class"] == GENUINE_UMAT
    assert held["terminal_state"] == "transform_refused"
    assert held["kind"] == "internal"
    assert held["adequately_specified"] is True


def test_a_rule_that_only_saw_subscripts_would_call_that_file_empty():
    """The reason the search is written against whole-array assignments too.
    A pattern requiring ``STRESS(`` finds nothing in a file that computes a
    Mohr-Coulomb return mapping, and would have moved a real UMAT into the
    published-stub class -- an external verdict, on a file with 675 logical
    lines of constitutive code in it."""
    import re
    from umat_oti.fortran.parser import logical_lines_from_text

    path = cached(MOHR)
    text = path.read_text(errors="replace")
    subscript_only = re.compile(
        r"^\s*(?:\d+\s+)?(?:STRESS|DDSDDE)\s*\([^=]*\)\s*=(?!=)",
        re.IGNORECASE)
    hits = [line for line in logical_lines_from_text(text, "fixed")
            if subscript_only.match(getattr(line, "text", str(line)))]
    assert not hits, ("if this ever matches, the point of the test has gone",
                      hits[:3])
    assert umat_outputs_written(text, path=path).writes_stress


# ---------------------------------------------------------------------------
# 2. the two the registry was wrong about: published templates
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source_id", [STUB, ADAPTER])
def test_a_umat_that_computes_nothing_is_not_work_this_project_owes(source_id):
    """Both files present the 37-argument Abaqus UMAT interface. Neither
    assigns STRESS or DDSDDE anywhere, and neither makes a single CALL, so
    there is no route by which either output could be written. `genuine_umat`
    said this project owed a transform on a file with nothing in it to
    transform."""
    path = cached(source_id)
    text = path.read_text(errors="replace")

    found = classify(text, path=path)
    assert found.entry_interface == "UMAT", found.reason

    outputs = umat_outputs_written(text, path=path)
    assert outputs.writes_stress is False
    assert outputs.writes_ddsdde is False
    assert outputs.calls == 0
    assert outputs.is_declaration_only
    assert "searched for an assignment to STRESS or DDSDDE" in \
        outputs.where_it_searched

    verdict = classify_refusal(found, text_rejected=False, outputs=outputs)
    assert verdict.refusal_class == PUBLISHED_STUB
    assert outputs.where_it_searched in verdict.basis, (
        "a verdict of 'this file computes nothing' has to say where it "
        "looked")

    held = record(source_id)
    assert held["refusal_class"] == PUBLISHED_STUB
    assert held["adequately_specified"] is False
    assert held["adequacy_kind"] == "external"


def test_the_stub_verdict_is_withheld_the_moment_a_call_could_write_an_output():
    """A UMAT that hands STRESS to a subroutine is delegating, not empty, and
    this module cannot follow the delegation. Measured on the corpus: 31
    UMAT-presenting sources assign neither output directly, and all but three
    of them make at least one CALL. Only the three that make none are called
    templates."""
    if not REGISTRY.is_file():
        pytest.skip("the registry has not been built")
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]
    silent = [r for r in rows
              if r["entry_interface"] == "UMAT"
              and r["writes_stress"] is False and r["writes_ddsdde"] is False]
    assert len(silent) >= 20, len(silent)
    templates = [r for r in silent if r["output_calls"] == 0]
    assert len(templates) == 3, [r["source_id"] for r in templates]
    for r in silent:
        if r["output_calls"]:
            assert r["adequacy_basis"] and "publishes no constitutive model" \
                not in r["adequacy_basis"], r["source_id"]


def test_the_stub_rung_never_overrides_a_more_specific_external_answer():
    """mrkearden__abaqus_umat/UMAT.F90 is the third template -- it says so:
    "ADD THE MATERIAL MODEL DEFINITION HERE TO MAKE THIS FUNCTIONAL". It also
    USEs Elmer's `Types` module, which was never published beside it, and that
    answer was already recorded against it. The stub rung is asked last, so it
    refines only what would otherwise have been called ours."""
    held = record("mrkearden__abaqus_umat/UMAT.F90")
    assert held["refusal_class"] == "missing_external_dependency"
    assert held["writes_stress"] is False and held["output_calls"] == 0
    assert held["adequately_specified"] is False
    assert held["adequacy_kind"] == "external"


# ---------------------------------------------------------------------------
# 3. the one the parser was wrong about: a declaration read as a definition
# ---------------------------------------------------------------------------
def test_a_subroutine_declared_in_an_interface_block_is_not_this_files_umat():
    """sas229__geomat/tests/umat_integration.f90 is a test driver. Its
    `subroutine umat` header at line 7 opens at line 6 with `interface` and
    closes at line 25 with `end interface`; there is no body. The file's only
    program unit is `program main` at line 1, and what it does with the
    declaration is CALL it -- the implementation is in a C++ library the
    repository does not publish as Fortran."""
    path = cached(DRIVER)
    text = path.read_text(errors="replace")
    lines = text.splitlines()

    assert lines[0].strip() == "program main"
    assert lines[5].strip() == "interface"
    assert lines[6].strip().startswith("subroutine umat(")
    assert lines[24].strip() == "end interface"
    assert any("call umat(" in line for line in lines)

    units = program_units(text, path=path)
    assert [(u.name, u.kind, u.line) for u in units] == [("main", "PROGRAM", 1)]

    found = classify(text, path=path)
    assert not found.is_umat, found.reason
    assert found.entry_line == 1
    assert found.entry_text == "program main"

    verdict = classify_refusal(found, text_rejected=False,
                               outputs=umat_outputs_written(text, path=path))
    assert verdict.refusal_class == HELPER_OR_MODULE_ONLY
    assert verdict.is_umat is False

    held = record(DRIVER)
    assert held["is_umat"] is False
    assert held["terminal_state"] == "not_a_umat"
    assert held["kind"] == "external"
    assert held["adequately_specified"] is False


def test_the_interface_block_rule_changed_nothing_else_in_the_corpus():
    """Thirteen acquired sources contain an INTERFACE block and two of them
    had a header inside one read as a program unit. Only those two
    classifications moved, and the second -- ParaFEM-lite -- kept its verdict
    and gained a quotable line: it now cites its own SUBROUTINE PLASTICITY at
    line 9 rather than a declaration at line 30."""
    held = record("Batmanabcdefg__ParaFEM-lite/src/programs/dev/xx15/"
                  "plasticity_xx15.F90")
    assert held["terminal_state"] == "not_a_umat"
    assert held["entry_line"] == 9
    assert held["entry_evidence"].startswith("SUBROUTINE PLASTICITY(")
    path = cached("Batmanabcdefg__ParaFEM-lite/src/programs/dev/xx15/"
                  "plasticity_xx15.F90")
    line = path.read_text(errors="replace").splitlines()[8]
    assert held["entry_evidence"][:40] in line


# ---------------------------------------------------------------------------
# the reconciliation, as a whole
# ---------------------------------------------------------------------------
def test_no_source_is_both_a_genuine_umat_here_and_anchorless_there():
    """The four are settled. Anything the transformer refuses for want of a
    stress-update anchor that this registry still calls `genuine_umat` has to
    be a file that demonstrably writes one -- otherwise the two artefacts
    disagree about the same file and one of them is wrong."""
    if not REGISTRY.is_file():
        pytest.skip("the registry has not been built")
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]
    disputed = [r for r in rows
                if r["refusal_class"] == GENUINE_UMAT
                and "anchor" in (r["reason"] or "").lower()]
    assert disputed, "no source is in dispute at all, which is suspicious"
    for held in disputed:
        assert held["writes_stress"] or held["writes_ddsdde"], (
            f"{held['source_id']} is called a genuine UMAT and the "
            f"transformer cannot find a stress update in it, and neither can "
            f"this registry: {held['output_search']}")
