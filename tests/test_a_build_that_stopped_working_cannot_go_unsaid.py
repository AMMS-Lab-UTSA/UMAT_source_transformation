"""A source that transforms and stops building must say so, and be counted.

The transform succeeding and the generated Fortran building are two facts, and
only the first decided the row's ``outcome``. So a source could be recorded
``compiled: true`` in one pass and ``compiled: false`` in the next, with
``outcome: transformed`` and an empty ``reason`` in both. Nothing counted it,
nothing listed it, and the loss surfaced two rungs later as an Abaqus job
failing for what looked like another cause.

Four sources did that between pass16 (fingerprint dbe9f928191e1d43) and pass17
(650a66ab55825346): ``theysy__mml_subroutine_public/MML_U2``, ``.../MML_U3``,
``theysy__UMAT_optimization_public/.../MML_U2SA`` and ``.../MML_U3SA``. Two of
them had carried a mechanics finding that the silent build failure overwrote.
Their cause is fixed elsewhere -- the lifted prelude declared an
implicitly-integer COMMON member ``real(8)`` -- but the silence is a separate
defect and this is what holds it down.
"""
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from transform_all import (                                       # noqa: E402
    OUTCOME_CACHED, OUTCOME_TRANSFORMED, Outcome, TransformResult, WorkItem,
    plan_work, record_outcome, report_lines, summarise, uncompiled_reason)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _Stored:
    def __init__(self, key, metadata):
        self.key = key
        self.metadata = metadata
        self.exists = True


class _Store:
    """Just enough store to answer ``get``."""

    def __init__(self, entries):
        self.entries = entries

    def get(self, source_id, digest):
        return self.entries.get(source_id)


def _item(tmp_path: Path) -> WorkItem:
    source = tmp_path / "umat.for"
    source.write_text("      END\n", encoding="utf-8")
    return WorkItem(source_id="theysy__x/MML_U2.for", path=source,
                    sha256="0" * 64, ntens=3, stage="blocked")


def test_a_transformed_row_that_did_not_build_states_why(tmp_path):
    """``outcome: transformed`` with ``compiled: false`` is not a bare count."""
    item = _item(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    entry = out / "u_oti.for"
    entry.write_text("      END\n", encoding="utf-8")
    result = TransformResult(
        source_id=item.source_id, ok=True, out_dir=out, entry_source=entry,
        metadata={"compiled": False, "compile_status": "compile_failed",
                  "compile_layout": "job_directory",
                  "compile_error": "Symbol 'ndim3' already has basic type of "
                                   "INTEGER"})

    outcome = record_outcome(item, result,
                             lambda i, r: _Stored("k", r.metadata))

    assert outcome.outcome == OUTCOME_TRANSFORMED
    assert outcome.compiled is False
    assert outcome.reason, "a build that stopped working said nothing"
    assert "ndim3" in outcome.reason
    assert "job_directory" in outcome.reason


def test_a_transformed_row_that_built_states_nothing(tmp_path):
    """The reason is the loss's, not decoration on every row."""
    item = _item(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    entry = out / "u_oti.for"
    entry.write_text("      END\n", encoding="utf-8")
    result = TransformResult(
        source_id=item.source_id, ok=True, out_dir=out, entry_source=entry,
        metadata={"compiled": True, "compile_status": "compiled",
                  "compile_layout": "job_directory"})

    outcome = record_outcome(item, result,
                            lambda i, r: _Stored("k", r.metadata))

    assert outcome.compiled is True
    assert outcome.reason == ""


def test_a_build_loss_with_no_compiler_output_still_states_something():
    """"It stopped building" without a cause is still better than silence."""
    reason = uncompiled_reason({"compiled": False})

    assert reason.strip()
    assert "did not compile" in reason


def test_a_cached_entry_that_did_not_build_carries_its_reason(tmp_path):
    """The store keeps the metadata; the row has to keep the reason."""
    cache = tmp_path / "cache" / "theysy__x"
    cache.mkdir(parents=True)
    (cache / "MML_U2.for").write_text("      END\n", encoding="utf-8")
    store = _Store({"theysy__x/MML_U2.for": _Stored("k", {
        "compiled": False, "compile_status": "compile_failed",
        "compile_error": "Symbol 'ndim3' already has basic type of INTEGER",
        "ntens": 3, "kinematics": "small strain"})})

    plan = plan_work([{"source": "theysy__x/MML_U2.for", "stage": "blocked"}],
                     tmp_path / "cache", store)

    assert not plan.todo
    settled, = plan.settled
    assert settled.outcome == OUTCOME_CACHED
    assert settled.compiled is False
    assert "ndim3" in settled.reason


def test_the_summary_counts_a_build_that_did_not_happen():
    """Not a failure and not a success: counted where neither number hides it."""
    outcomes = [
        Outcome(source_id="ok/a.for", outcome=OUTCOME_TRANSFORMED, compiled=True),
        Outcome(source_id="theysy__x/MML_U2.for", outcome=OUTCOME_TRANSFORMED,
                compiled=False, reason="transformed, but the generated Fortran "
                                       "did not compile: ndim3"),
        Outcome(source_id="theysy__x/MML_U3.for", outcome=OUTCOME_CACHED,
                compiled=False, reason="transformed, but the generated Fortran "
                                       "did not compile: ndim6"),
    ]

    summary = summarise(outcomes, selected=3)

    lost = summary["transformed_without_a_build"]
    assert [row["source"] for row in lost] == ["theysy__x/MML_U2.for",
                                               "theysy__x/MML_U3.for"]
    assert all(row["reason"] for row in lost)
    assert summary["unexplained_build_losses"] == []
    assert summary["transformed_now"] == 2      # the count did not change
    assert summary["failed"] == 0
    text = "\n".join(report_lines(summary))
    assert "transformed but did not build" in text
    assert "did not build: theysy__x/MML_U2.for" in text


def test_a_build_loss_with_no_stated_cause_is_shouted_not_swallowed():
    """The invariant is checked rather than trusted; this is what a breach reads like."""
    outcomes = [Outcome(source_id="silent/a.for", outcome=OUTCOME_TRANSFORMED,
                        compiled=False, reason="")]

    summary = summarise(outcomes, selected=1)

    assert summary["unexplained_build_losses"] == ["silent/a.for"]
    assert "ACCOUNTING ERROR" in "\n".join(report_lines(summary))
