"""A hallucinating model must not be able to change anything that matters.

The two proposers added beside the deck pairing -- a blocker cause and a compile
repair -- are the ones with the most to gain from a model and the most to lose
from trusting one. These pin the boundary: every proposal is checked against the
file it is about or against the compiler, an unchecked proposal cannot be read,
and a model that answers with confident nonsense leaves the pipeline's output
byte for byte what it was without any model at all.

The stub models here are deliberately hostile. ``Liar`` answers plausibly and
wrongly, ``Forger`` quotes source lines it never read, ``Vandal`` tries to edit
files it was never offered, and ``Dead`` fails. None of them may produce a
different outcome from ``None``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.assist.blocker_triage import (
    CONSTRUCT_PATTERNS, construct_occurrences, propose_blocker_cause,
    verify_construct,
)
from umat_oti.assist.local_model import LocalModel, ModelUnavailable
from umat_oti.assist.proposals import ProposalNotConfirmed, Verdict
from umat_oti.assist.repair import (
    PathNotAllowed, RepairPolicy, propose_repair, semantic_kinds,
)


class _Stub(LocalModel):
    """A model that says whatever the test tells it to, without a server."""

    def __init__(self, answer: str, name: str = "stub"):
        super().__init__(name=name)
        self._answer = answer

    def ask(self, prompt, *, temperature=0.0, max_tokens=256):
        return self._answer, "0" * 64


class _Dead(LocalModel):
    def ask(self, prompt, *, temperature=0.0, max_tokens=256):
        raise ModelUnavailable("no server")


SOURCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,PROPS)
      INCLUDE 'ABA_PARAM.INC'
      COMMON /SHARED/ ALPHA, BETA
      DIMENSION STRESS(6)
C     COMMON blocks are described in this comment only
      DATA ALPHA /1.0D0/
      STRESS(1) = ALPHA*DSTRAN(1)
C     the original tolerance was 1.0D-12 here
      END
"""


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    path = tmp_path / "umat.f"
    path.write_text(SOURCE, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# The blocker cause proposer.
# --------------------------------------------------------------------------

def test_with_no_model_no_cause_is_proposed_and_none_can_be_read(source: Path):
    """The model-absent path is exactly today's behaviour: no cause at all."""
    proposal = propose_blocker_cause(source, "shape could not be confirmed",
                                     model=None)
    assert proposal.verdict is Verdict.UNVERIFIED
    assert proposal.proposed is None
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_a_dead_model_is_the_same_as_no_model(source: Path):
    proposal = propose_blocker_cause(source, "anything", model=_Dead(name="dead"))
    assert proposal.verdict is Verdict.UNVERIFIED
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_a_true_cause_is_confirmed_by_the_file_not_by_the_model(source: Path):
    proposal = propose_blocker_cause(
        source, "no confirmed shape", model=_Stub("common_block|3"))
    assert proposal.verdict is Verdict.CONFIRMED
    assert proposal.confirmed_value() == {"construct": "common_block", "line": 3}
    assert "COMMON /SHARED/" in proposal.evidence
    assert proposal.checked_by == "umat_oti.assist.blocker_triage"


def test_a_construct_named_at_the_wrong_line_is_contradicted(source: Path):
    """The construct exists in the file, but not where the model said."""
    proposal = propose_blocker_cause(
        source, "no confirmed shape", model=_Stub("common_block|7"))
    assert proposal.verdict is Verdict.CONTRADICTED
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()
    # The real occurrences are still recorded: that is the useful half.
    assert proposal.metadata["actual_occurrences"] == [3]


def test_a_construct_found_only_in_a_comment_is_not_a_construct(source: Path):
    """Line 5 contains the word COMMON inside a fixed-form comment."""
    proposal = propose_blocker_cause(
        source, "no confirmed shape", model=_Stub("common_block|5"))
    assert proposal.verdict is Verdict.CONTRADICTED
    assert "comment" in proposal.evidence
    assert 5 not in construct_occurrences(SOURCE, "common_block")


def test_the_comment_guard_holds_for_an_unanchored_construct(source: Path):
    """The guard has to work where the pattern can match mid-line.

    Most of the vocabulary is anchored at the start of a statement, so a
    comment fails to match anyway and a test using one would pass whether the
    comment guard existed or not. ``real_literal_exponent`` matches anywhere,
    and line 8 is a comment that mentions 1.0D-12. This is the case that
    actually distinguishes reading the file from reading prose about it.
    """
    assert "1.0D-12" in SOURCE.splitlines()[7]
    assert verify_construct(SOURCE, "real_literal_exponent", 8)[0] is False
    # ... while the DATA statement on line 6 really does hold one.
    assert verify_construct(SOURCE, "real_literal_exponent", 6)[0] is True
    assert construct_occurrences(SOURCE, "real_literal_exponent") == [6]

    proposal = propose_blocker_cause(
        source, "Missing exponent in real number",
        model=_Stub("real_literal_exponent|8"))
    assert proposal.verdict is Verdict.CONTRADICTED
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_a_construct_outside_the_vocabulary_cannot_be_proposed(source: Path):
    """A model cannot invent a new cause, however confidently it names one."""
    proposal = propose_blocker_cause(
        source, "no confirmed shape",
        model=_Stub("quantum_flux_capacitor|3"))
    assert proposal.verdict is Verdict.UNVERIFIED
    assert proposal.proposed is None
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_prose_and_refusal_yield_no_cause(source: Path):
    for answer in ("I think the COMMON block on line 3 is the problem.",
                   "NONE", "", "```\n\n```"):
        proposal = propose_blocker_cause(source, "x", model=_Stub(answer))
        assert proposal.verdict is Verdict.UNVERIFIED, answer
        assert proposal.proposed is None, answer


def test_the_verdict_is_a_function_of_the_file_alone(source: Path):
    """Two different models naming the same line must get the same verdict."""
    verdicts = {
        propose_blocker_cause(source, "x", model=_Stub("data|6", name=name)).verdict
        for name in ("a", "b", "c")
    }
    assert verdicts == {Verdict.CONFIRMED}
    # And the same construct at a line that does not hold it is refused for
    # every model equally.
    verdicts = {
        propose_blocker_cause(source, "x", model=_Stub("data|1", name=name)).verdict
        for name in ("a", "b", "c")
    }
    assert verdicts == {Verdict.CONTRADICTED}


def test_verify_construct_answers_from_the_text_only():
    assert verify_construct(SOURCE, "include_file", 2)[0] is True
    assert verify_construct(SOURCE, "common_block", 3)[0] is True
    assert verify_construct(SOURCE, "common_block", 5)[0] is False
    assert verify_construct(SOURCE, "common_block", 999)[0] is False
    assert verify_construct(SOURCE, "not_a_construct", 3)[0] is False


def test_the_vocabulary_stays_closed_and_reuses_the_transformers_own_codes():
    from umat_oti.core.diagnostics import UNSUPPORTED_PATTERNS

    for code, pattern, _message in UNSUPPORTED_PATTERNS:
        assert CONSTRUCT_PATTERNS[code] == pattern, (
            f"{code} has drifted from the transformer's own diagnostic")


# --------------------------------------------------------------------------
# The repair proposer.
# --------------------------------------------------------------------------

GENERATED = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,PROPS)
      USE otim6n1
      TYPE(ONUMM6N1) :: STRESS_OTI(6)
      TYPE(ONUMM6N1) :: XTOL_OTI
      DO OTI_I = 1, 6
         DSTRAN_OTI(OTI_I) = DSTRAN(OTI_I)
      END DO
      XTOL_OTI = 1.D_OTI-12
      STRESS_OTI(1) = XTOL_OTI
      DO OTI_I = 1, 6
         STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))
      END DO
      END
"""


@pytest.fixture()
def out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    (out / "umat_oti.f").write_text(GENERATED, encoding="utf-8")
    (out / "compile_hint.sh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    return out


def _unchanged(out: Path, original: bytes) -> None:
    assert (out / "umat_oti.f").read_bytes() == original, (
        "the transformer's own output was modified")


def test_with_no_model_nothing_is_read_or_written(out_dir: Path):
    original = (out_dir / "umat_oti.f").read_bytes()
    proposal = propose_repair("umat_oti.f", out_dir, "some error", model=None)
    assert proposal.verdict is Verdict.UNVERIFIED
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()
    _unchanged(out_dir, original)


def test_a_forged_quote_is_inert(out_dir: Path):
    """A model that invents the line it is editing cannot match the file."""
    original = (out_dir / "umat_oti.f").read_bytes()
    forger = _Stub("REPLACE|||8|||      XTOL_OTI = 9.999|||      XTOL_OTI = 1.D-12")
    proposal = propose_repair("umat_oti.f", out_dir, "err", model=forger,
                              compile_check=lambda d: (True, ""))
    assert proposal.verdict is Verdict.CONTRADICTED
    assert "not what the model quoted" in proposal.evidence
    _unchanged(out_dir, original)


def test_an_edit_that_does_not_compile_is_refused(out_dir: Path):
    original = (out_dir / "umat_oti.f").read_bytes()
    proposal = propose_repair(
        "umat_oti.f", out_dir, "err",
        model=_Stub("REPLACE|||8|||      XTOL_OTI = 1.D_OTI-12|||      XTOL_OTI = 1.D-12"),
        compile_check=lambda d: (False, "still broken"))
    assert proposal.verdict is Verdict.CONTRADICTED
    assert "still does not compile" in proposal.evidence
    _unchanged(out_dir, original)


def test_an_edit_that_breaks_a_semantic_check_is_refused(out_dir: Path):
    """Compiling is necessary and not sufficient: STRESS_OTI must survive."""
    original = (out_dir / "umat_oti.f").read_bytes()
    vandal = _Stub(
        "REPLACE|||9|||      STRESS_OTI(1) = XTOL_OTI|||      CONTINUE")
    proposal = propose_repair("umat_oti.f", out_dir, "err", model=vandal,
                              compile_check=lambda d: (True, ""))
    assert proposal.verdict is Verdict.CONTRADICTED
    _unchanged(out_dir, original)


def test_a_semantically_significant_line_may_not_be_edited(out_dir: Path):
    """Line 6 is the DSTRAN initialisation an ordering check is about."""
    original = (out_dir / "umat_oti.f").read_bytes()
    proposal = propose_repair(
        "umat_oti.f", out_dir, "err",
        model=_Stub("REPLACE|||6|||         DSTRAN_OTI(OTI_I) = DSTRAN(OTI_I)"
                    "|||         DSTRAN_OTI(OTI_I) = 0.0D0"),
        compile_check=lambda d: (True, ""))
    assert proposal.verdict is Verdict.CONTRADICTED
    assert "semantic check depends on" in proposal.evidence
    _unchanged(out_dir, original)


def test_an_edit_may_not_delete_or_comment_out_a_statement(out_dir: Path):
    original = (out_dir / "umat_oti.f").read_bytes()
    for new in ("", "C     XTOL_OTI = 1.D-12"):
        proposal = propose_repair(
            "umat_oti.f", out_dir, "err",
            model=_Stub(f"REPLACE|||8|||      XTOL_OTI = 1.D_OTI-12|||{new}"),
            compile_check=lambda d: (True, ""))
        assert proposal.verdict is Verdict.CONTRADICTED, new
        _unchanged(out_dir, original)


def test_a_confirmed_repair_still_does_not_touch_the_pipelines_output(out_dir: Path):
    """The whole point: a confirmed repair is a finding, not a patch."""
    original = (out_dir / "umat_oti.f").read_bytes()
    proposal = propose_repair(
        "umat_oti.f", out_dir, "Missing exponent in real number",
        model=_Stub("REPLACE|||8|||      XTOL_OTI = 1.D_OTI-12"
                    "|||      XTOL_OTI = 1.D-12"),
        compile_check=lambda d: (True, ""))
    assert proposal.verdict is Verdict.CONFIRMED
    assert proposal.confirmed_value() == ["replace line 8: 'XTOL_OTI = 1.D-12'"]
    _unchanged(out_dir, original)
    assert proposal.metadata["semantic_kinds_unchanged"] is True


def test_the_compile_gate_is_the_real_compiler(tmp_path: Path):
    """Gate 2 with gfortran actually running, not a stub that returns True.

    The literal ``1.D_OTI-12`` is what a rename that walked into the exponent
    of ``1.D-12`` leaves behind, and it is the one defect class in the observed
    compile failures that a single-line edit can genuinely fix.
    """
    import shutil as _shutil

    if _shutil.which("gfortran") is None:
        pytest.skip("gfortran is not installed")
    out = tmp_path / "out"
    out.mkdir()
    broken = (
        "      SUBROUTINE UMAT(STRESS,DSTRAN)\n"
        "      DIMENSION STRESS(6), DSTRAN(6)\n"
        "      DOUBLE PRECISION XTOL_OTI\n"
        "      XTOL_OTI = 1.D_OTI-12\n"
        "      STRESS(1) = XTOL_OTI\n"
        "      END\n")
    (out / "umat_oti.f").write_text(broken, encoding="utf-8")
    (out / "compile_hint.sh").write_text(
        "#!/bin/sh\nexec gfortran -fsyntax-only -ffixed-form "
        "-ffixed-line-length-none umat_oti.f\n", encoding="utf-8")
    (out / "compile_hint.sh").chmod(0o755)
    original = (out / "umat_oti.f").read_bytes()

    # The wrong fix compiles nowhere, so the real compiler rejects it.
    rejected = propose_repair(
        "umat_oti.f", out, "Missing exponent in real number",
        model=_Stub("REPLACE|||4|||      XTOL_OTI = 1.D_OTI-12"
                    "|||      XTOL_OTI = 1.D_OTI_OTI-12"))
    assert rejected.verdict is Verdict.CONTRADICTED
    assert "still does not compile" in rejected.evidence

    # The right one compiles, and even then the output is left alone.
    accepted = propose_repair(
        "umat_oti.f", out, "Missing exponent in real number",
        model=_Stub("REPLACE|||4|||      XTOL_OTI = 1.D_OTI-12"
                    "|||      XTOL_OTI = 1.D-12"))
    assert accepted.verdict is Verdict.CONFIRMED
    assert accepted.metadata["compiled_after_edit"] is True
    _unchanged(out, original)


def test_the_repair_cannot_be_aimed_outside_the_output_directory(tmp_path: Path):
    """Containment is checked on the resolved path, so traversal is refused."""
    policy = RepairPolicy(allowed_root=tmp_path / "out",
                          forbidden_roots=(tmp_path / "src",))
    (tmp_path / "out").mkdir()
    (tmp_path / "src").mkdir()
    for target in (tmp_path / "out" / ".." / "src" / "x.py",
                   tmp_path / "src" / "source_transform.py",
                   Path("/etc/passwd")):
        with pytest.raises(PathNotAllowed):
            policy.check(target)


def test_a_repair_naming_a_file_that_is_not_there_is_refused(out_dir: Path):
    proposal = propose_repair("../../../etc/passwd", out_dir, "err",
                              model=_Stub("NONE"),
                              compile_check=lambda d: (True, ""))
    assert proposal.verdict is Verdict.CONTRADICTED
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_the_semantic_signature_notices_a_reordering():
    """The invariance gate has to actually be sensitive to what it guards."""
    assert semantic_kinds(GENERATED) == (
        "dstran_init", "stress_update", "stress_extraction")
    without_extraction = GENERATED.replace(
        "         STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))\n", "")
    assert semantic_kinds(without_extraction) != semantic_kinds(GENERATED)


# --------------------------------------------------------------------------
# Nothing a model says reaches the evidence.
# --------------------------------------------------------------------------

def test_a_proposal_never_carries_a_number_into_the_record(source: Path):
    proposal = propose_blocker_cause(source, "x", model=_Stub("common_block|3"))
    record = proposal.as_dict()
    assert "No value here was generated by it" in record["note"]
    # The only numeric thing a cause carries is a line number, and it is one
    # that was checked against the file.
    assert set(record["proposed"]) == {"construct", "line"}
    assert record["proposed"]["line"] == 3
    json.dumps(record)  # the record has to be serialisable as evidence


def test_the_published_rounds_do_not_import_the_assist_package():
    """The corpus round and the sensitivity sweep must not be able to run a model."""
    root = Path(__file__).resolve().parents[1]
    for tool in ("run_corpus_round.py", "run_parameter_sensitivity_sweep.py"):
        path = root / "tools" / tool
        if not path.is_file():
            pytest.skip(f"{tool} is not in this tree")
        text = path.read_text()
        assert "umat_oti.assist" not in text, (
            f"{tool} can reach the assist package")
        assert "ollama" not in text.lower() and "qwen" not in text.lower(), (
            f"{tool} mentions a model")


def test_the_triage_round_reaches_a_model_only_behind_its_opt_in_flag():
    """Default triage must not be able to import the assist package at all.

    The import lives inside the function the flag calls, so a run without
    ``--propose-causes`` cannot reach a model even with one running on the
    machine. A module-level import would silently undo that.
    """
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "run_discovery_triage.py"
    if not path.is_file():
        pytest.skip("run_discovery_triage.py is not in this tree")
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if "umat_oti.assist" in line and line.strip().startswith(("import", "from")):
            assert line.startswith((" ", "\t")), (
                f"line {number} imports the assist package at module level, so "
                f"a default triage run loads it: {line.strip()!r}")


def test_the_triage_columns_do_not_carry_a_proposal():
    """A proposal must not be able to become a column of the published CSV."""
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "run_discovery_triage.py"
    if not path.is_file():
        pytest.skip("run_discovery_triage.py is not in this tree")
    import sys

    sys.path.insert(0, str(root / "tools"))
    import run_discovery_triage

    for column in run_discovery_triage.COLUMNS:
        assert "propos" not in column and "model" not in column, (
            f"{column} would put a model's answer in discovery_triage.csv")
