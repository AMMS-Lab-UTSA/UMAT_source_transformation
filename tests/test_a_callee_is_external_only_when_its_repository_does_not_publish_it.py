"""The B17 G3a rule: a callee that is not in the repository and not an Abaqus
utility is external; one that is in the repository is resolved.

The rule was written before it was run (corpus_campaign/batches/B17/lovelace/
RULE_G3a.md). These tests pin its words, build small repositories on disk, and
show each way a name can be "in the repository" or not, plus the planted-error
canary: the same source with one definition removed must flip from resolved to
external, so the check can fail.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from umat_oti.abaqus import repository_lookup as rl

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

pytestmark = pytest.mark.unit

HEAD = ("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,\n"
        "     1 RPL,DDSDDT,DRPLDE,DRPLDT)\n")


def repo(tmp_path: Path, files: dict, name: str = "owner__repo") -> Path:
    for relative, text in files.items():
        path = tmp_path / name / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def verdict(tmp_path: Path, entry: str, **kwargs):
    return rl.lookup(tmp_path / "owner__repo" / entry, tmp_path, **kwargs)


def test_the_rule_is_stated_in_the_modules_own_words():
    assert rl.RULE == ("A callee that is not in the repository and not an Abaqus "
                       "utility is external; one that is in the repository is resolved.")


def test_a_callee_in_a_sibling_file_is_resolved_and_the_same_source_without_it_is_external(tmp_path):
    entry = HEAD + "      CALL HELPER(STRESS)\n      RETURN\n      END\n"
    helper = "      SUBROUTINE HELPER(S)\n      END\n"
    repo(tmp_path, {"umat.for": entry, "deep/dir/helper.for": helper})
    found = verdict(tmp_path, "umat.for")
    assert found.verdict == "resolved" and found.unpublished == ()
    assert found.resolved["call HELPER"].endswith("deep/dir/helper.for")
    # canary: the definition removed -> external, naming the callee
    (tmp_path / "owner__repo/deep/dir/helper.for").unlink()
    rl._INDEXES.clear()
    found = verdict(tmp_path, "umat.for")
    assert found.verdict == "external" and found.unpublished == ("call HELPER",)


def test_a_definition_in_another_repository_does_not_count(tmp_path):
    repo(tmp_path, {"umat.for": HEAD + "      CALL HELPER(STRESS)\n      END\n"})
    repo(tmp_path, {"helper.for": "      SUBROUTINE HELPER(S)\n      END\n"}, name="other__repo")
    assert verdict(tmp_path, "umat.for").unpublished == ("call HELPER",)


def test_abaqus_utilities_intrinsics_and_the_files_own_routines_are_not_dependencies(tmp_path):
    body = (HEAD + "      CALL XIT\n      CALL STDB_ABQERR(1,'x',I,R,C)\n      CALL GETOUTDIR(D,L)\n"
            "      CALL CPU_TIME(T)\n      CALL DTIME(A,B)\n      CALL SETTABLECOLLECTION(A,B)\n"
            "      CALL SMAFloatArrayCreateDP(1,2,0.d0)\n      CALL OWN(S)\n      END\n"
            "      SUBROUTINE OWN(S)\n      END\n")
    repo(tmp_path, {"umat.for": body})
    assert verdict(tmp_path, "umat.for").verdict == "resolved"


def test_modules_and_includes_are_looked_up_in_the_repository_and_the_compilers_own_are_not(tmp_path):
    free = ("subroutine umat(stress)\n  use iso_c_binding\n  use mymod\n  use gonemod\n"
            "  include 'present.inc'\n  include 'absent.inc'\n  include 'ABA_PARAM.INC'\nend subroutine\n")
    repo(tmp_path, {"umat.f90": free, "m.f90": "module mymod\nend module mymod\n",
                    "x/present.inc": "      real a\n"})
    found = verdict(tmp_path, "umat.f90")
    assert set(found.unpublished) == {"module gonemod", "include absent.inc"}


def test_a_statement_that_starts_with_the_letters_use_is_not_a_use_statement(tmp_path):
    # UserVar(...) = phi was read as "USE rVar" (MCM-QMUL PhaseFieldComp)
    repo(tmp_path, {"umat.for": HEAD + "      UserVar(1,2,3)=phi\n      userdata = 1\n      END\n"})
    found = verdict(tmp_path, "umat.for")
    assert found.verdict == "resolved" and found.unpublished == ()


def test_a_commented_out_include_is_not_a_dependency(tmp_path):
    body = HEAD + "c      include 'common_cart.inc'\n!      include 'other.inc'\n      END\n"
    repo(tmp_path, {"umat.for": body})
    assert verdict(tmp_path, "umat.for").verdict == "resolved"


def test_a_routine_in_a_file_the_closure_pulls_in_is_looked_up_in_turn(tmp_path):
    repo(tmp_path, {"umat.for": HEAD + "      CALL ONE\n      END\n",
                    "one.for": "      SUBROUTINE ONE\n      CALL TWO\n      CALL THREE\n      END\n",
                    "two.for": "      SUBROUTINE TWO\n      END\n"})
    found = verdict(tmp_path, "umat.for")
    assert found.unpublished == ("call THREE",) and len(found.companions) == 2


def test_type_bound_calls_dummy_procedures_and_procedure_pointers_are_not_global_routines(tmp_path):
    free = ("subroutine umat(stress, f)\n  procedure(), pointer :: p\n  call obj%method(1)\n"
            "  call f(stress)\n  call p(stress)\nend subroutine\n")
    repo(tmp_path, {"umat.f90": free})
    assert verdict(tmp_path, "umat.f90").verdict == "resolved"


def test_a_generic_interface_name_and_a_module_procedure_are_definitions(tmp_path):
    mod = ("module g\n  interface value\n    module procedure value_a\n  end interface value\n"
           "contains\n  subroutine value_a(x)\n  end subroutine\nend module g\n"
           "submodule (g) s\ncontains\n  module procedure impl\n  end procedure impl\nend submodule s\n")
    repo(tmp_path, {"umat.f90": "subroutine umat(s)\n use g\n call value(1)\n call impl(2)\nend subroutine\n",
                    "g.f90": mod})
    assert verdict(tmp_path, "umat.f90").verdict == "resolved"


def test_a_routine_only_declared_in_an_interface_block_is_not_a_definition(tmp_path):
    iface = ("subroutine umat(s)\n  interface\n    subroutine native(x) bind(c)\n    end subroutine\n"
             "  end interface\n  call native(1)\nend subroutine\n")
    repo(tmp_path, {"umat.f90": iface})
    assert verdict(tmp_path, "umat.f90").unpublished == ("call NATIVE",)


def test_a_free_form_tail_after_a_freeform_directive_is_read_as_free_form(tmp_path):
    body = (HEAD + "      CALL LATER(STRESS)\n      END\n!DIR$ FREEFORM\n"
            "    subroutine later (s,&\n    &t)\n    end subroutine later\n")
    repo(tmp_path, {"umat.for": body})
    assert verdict(tmp_path, "umat.for").verdict == "resolved"


def test_the_callees_the_transformer_names_are_looked_up_too(tmp_path):
    repo(tmp_path, {"umat.for": HEAD + "      END\n"})
    reason = "Helper lifting requires source definitions for ['GONE', 'XIT_OTI']."
    # XIT (the transformer's renamed XIT_OTI) is an Abaqus utility; GONE is not published
    assert verdict(tmp_path, "umat.for", reason=reason).unpublished == ("call GONE",)
    assert rl.names_in_refusal("STRESS_OTI is passed to SOLVER, which was neither") == ("SOLVER",)


def test_blas_and_lapack_are_neither_resolved_nor_external_and_unconfirmed_ptk_names_do_not_count(tmp_path):
    repo(tmp_path, {"umat.for": HEAD + "      CALL DGESV(N,1)\n      CALL SHEARMOD(1)\n"
                    "      CALL PTKCOMPUTE(1)\n      CALL PtkGetDataAccess(1)\n      END\n"})
    found = verdict(tmp_path, "umat.for")
    assert found.unpublished == ("call SHEARMOD",)
    assert found.unpublished_library == ("call DGESV",)
    assert found.unconfirmed == ("PTKCOMPUTE",)
    # canary: with only the library call the source is resolved, not external
    repo(tmp_path, {"umat.for": HEAD + "      CALL DGESV(N,1)\n      END\n"}, name="owner__repo")
    rl._INDEXES.clear()
    assert verdict(tmp_path, "umat.for").verdict == "resolved"


# -- the registry applies it to the states the refusal path does not reach ----------------
def test_the_registry_moves_a_transformed_but_unrunnable_source_and_leaves_run_states_alone():
    import build_corpus_registry as reg
    rows = []
    for state, companions in (("transform_refused", "call GONE"),
                              ("unsupported_formulation", "module rVar"),
                              ("unsupported_formulation", ""),
                              ("fully_verified", "call GONE"),
                              ("primal_disagreed", "call GONE")):
        record = reg.Record(source_id=f"o__r/{state}{len(rows)}.for", repository="o/r")
        record.terminal_state, record.kind = state, reg.kind_of(state)
        record.missing_companions = companions
        rows.append(record)
    conflicts = reg.apply_dependency_rule(rows)
    assert [r.terminal_state for r in rows] == [
        "external_dependency_unavailable", "external_dependency_unavailable",
        "unsupported_formulation", "fully_verified", "primal_disagreed"]
    assert all(r.kind == "external" for r in rows[:2])
    assert conflicts == [rows[4].source_id]
    assert "not in the repository and not an Abaqus utility" in rows[1].reason


# -- B18: the output search follows quoted includes; the cache is not the repository ----
def test_the_output_search_follows_quoted_includes_the_way_the_callee_rule_does(tmp_path):
    import build_corpus_registry as reg
    from umat_oti.corpus.entry_routines import umat_outputs_written
    main = HEAD + "      INCLUDE 'ABA_PARAM.INC'\n      INCLUDE './x/body.f'\n      END\n"
    repo(tmp_path, {"umat.for": main,
                    "x/body.f": "      STRESS(1)=1.D0\n      INCLUDE 'back.f'\n",
                    "x/back.f": "      DDSDDE(1,1)=2.D0\n      INCLUDE 'body.f'\n"})
    source = tmp_path / "owner__repo" / "umat.for"
    own = umat_outputs_written(main, path=source)
    assert not own.writes_stress and not own.writes_ddsdde
    found, followed = reg.outputs_following_includes(source, main, own, tmp_path)
    assert found.writes_stress and found.writes_ddsdde
    assert followed == ["owner__repo/x/body.f", "owner__repo/x/back.f"]   # the cycle ends
    assert found.first_write.startswith("[body.f] ")
    # canary: the include file removed -> nothing is found, as for the main file alone
    (tmp_path / "owner__repo/x/body.f").unlink()
    rl._INDEXES.clear()
    found, followed = reg.outputs_following_includes(source, main, own, tmp_path)
    assert not found.writes_ddsdde and followed == []


def test_a_name_the_upstream_tree_publishes_is_not_missing_because_the_cache_is_partial(tmp_path):
    import json
    import build_corpus_registry as reg
    check = tmp_path / "check.json"
    check.write_text(json.dumps({"checked": {"o__r/umat.for": {
        "absent": ["GONE"], "present_upstream_names": {"include core.for": "core.for"}}}}))
    assert reg.upstream_present_names("o__r/umat.for", check) == frozenset({"include core.for"})
    assert reg.upstream_absent_calls("o__r/umat.for", check) == frozenset({"GONE"})
    assert reg.upstream_present_names("o__r/other.for", check) == frozenset()
