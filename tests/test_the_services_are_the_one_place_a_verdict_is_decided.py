"""The CLI and the GUI call the same services and get the same schema.

The project owner's requirement, verbatim: *"The GUI must call reusable backend
services. It must not duplicate verification logic or execute large shell
commands assembled in UI callbacks."* These tests pin the properties that make
that true rather than aspirational:

* every service returns the same envelope, so no caller has to guess what a
  missing key means;
* the services hold no tolerances and build no shell commands of their own;
* the counts they publish carry their denominators;
* a renderer formats and never computes -- Markdown and JSON of the same result
  cannot disagree about a number, because they are the same dictionary twice.
"""
from __future__ import annotations

import json
import os
import sys
import tokenize
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import umat_oti.services as services  # noqa: E402
from umat_oti.services import (  # noqa: E402
    CorpusService, ManifestService, RegressionService, ReportService,
    ResidualAssemblyService, ServiceResult, VerificationService,
)

pytestmark = pytest.mark.unit

#: The real verification run. Derived from the checkout rather than written
#: out, so this file carries no absolute path into somebody else's home.
#: ``UMAT_OTI_CORPUS_RUN`` overrides it; every test using it skips when absent.
PASS11 = Path(os.environ.get(
    "UMAT_OTI_CORPUS_RUN",
    str(Path(__file__).resolve().parents[1].parent / "corpus_run" / "pass11"
        / "results" / "store_verification.jsonl")))
SERVICES_DIR = SRC / "umat_oti" / "services"


def _records():
    if not PASS11.is_file():
        pytest.skip(f"{PASS11} is not on this machine")
    return [json.loads(line) for line in
            PASS11.read_text(encoding="utf-8").splitlines() if line.strip()]


def _code(path: Path) -> str:
    pieces = []
    with open(path, "rb") as stream:
        for token in tokenize.tokenize(stream.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            pieces.append("\n" if token.type in (tokenize.NEWLINE, tokenize.NL)
                          else token.string)
    return "".join(pieces)


def test_every_service_named_in_the_brief_is_importable():
    for name in ("CorpusService", "ManifestService", "TransformationService",
                 "ExperimentService", "AbaqusExecutionService",
                 "VerificationService", "RegressionService",
                 "ResidualAssemblyService", "ReportService"):
        assert hasattr(services, name), name
        assert name in services.__all__, name


def test_no_service_assembles_a_shell_command():
    """The requirement is about shell commands in callbacks; the services must
    not be the place they moved to instead."""
    for path in sorted(SERVICES_DIR.rglob("*.py")):
        code = _code(path)
        assert "shell" not in code, path
        assert "os.system" not in code, path
        assert "os.popen" not in code, path


def test_no_service_carries_a_numerical_tolerance():
    """A tolerance in a service is a second opinion about a verdict.

    The GUI once held its own `rel < 1e-4` beside a batch tolerance of 1e-6.
    Comparison thresholds belong in the validation code that owns them; these
    services read results and never adjudicate a number.
    """
    import re

    suspicious = re.compile(r"\b1e-\d+\b|\b0\.0{3,}\d\b", re.IGNORECASE)
    for path in sorted(SERVICES_DIR.rglob("*.py")):
        if path.name in ("contract_adapter.py", "workbench.py",
                         "transformation.py"):
            continue  # pre-existing modules, not written by this work
        found = suspicious.findall(_code(path))
        assert not found, f"{path} carries what looks like a tolerance: {found}"


@pytest.mark.integration
def test_every_service_returns_the_same_envelope():
    records = _records()
    verified = next(r for r in records if r.get("stage") == "verified")
    results = [
        CorpusService(PASS11).list_sources(),
        CorpusService(PASS11).search("CAEAssistant"),
        CorpusService(PASS11).get(verified["key"]),
        ManifestService().review(verified),
        VerificationService().verify_record(verified),
        VerificationService().summarise(PASS11),
        ResidualAssemblyService().eligible(verified),
        services.ExperimentService().activation_search(verified),
        RegressionService().list_fixtures(),
    ]
    for result in results:
        assert isinstance(result, ServiceResult)
        payload = result.as_dict()
        for field in ("schema", "service", "ok", "outcome", "problems",
                      "provenance", "data", "evidence_paths"):
            assert field in payload, (result.service, field)
        assert payload["schema"] == "umat-oti/service-result/1"
        assert isinstance(payload["ok"], bool)
        assert payload["outcome"], result.service
        # Every result is JSON-serialisable, because a GUI has to render it.
        json.dumps(payload, default=str)


@pytest.mark.integration
def test_a_filtered_listing_keeps_the_denominator_it_was_drawn_from():
    """No summary number that hides a distinction."""
    listing = CorpusService(PASS11).list_sources(all_six_hold=True).data
    assert len(listing.sources) == 42
    assert listing.records_in_file == 237, (
        "a filtered count must carry what it was filtered from")
    assert listing.stage_counts["verified"] == 55
    assert sum(listing.stage_counts.values()) == 237


@pytest.mark.integration
def test_the_summary_reports_both_counts_and_never_one():
    summary = VerificationService().summarise(PASS11).data.as_dict()
    assert summary["records"] == 237
    assert summary["at_stage_verified"] == 55
    assert summary["true_on_all_six"] == 42
    assert summary["verified_but_not_all_six_count"] == 13
    assert 55 == 42 + 13
    assert "must never be reported as one number" not in summary
    assert "different counts" in summary["why_two_numbers"]
    for entry in summary["verified_but_not_all_six"]:
        assert entry["gates_that_did_not_hold"] == ["primal_agreed"]
        assert entry[services.SEVENTH]["reading"] == "true"


@pytest.mark.integration
def test_the_manifest_review_accounts_for_every_record():
    """81 refusals plus 156 reviews is 237; nothing falls between them."""
    records = _records()
    service = ManifestService()
    outcomes = [service.review(r).outcome for r in records]
    assert len(outcomes) == 237
    assert set(outcomes) <= {"reviewed", "refused", "no_manifest"}
    assert outcomes.count("refused") + outcomes.count("reviewed") \
        + outcomes.count("no_manifest") == 237
    # Every refusal says where it was read from.
    for record in records:
        review = service.review(record)
        if review.outcome == "refused":
            assert review.data.refusal
            assert review.data.refusal_source in ("experiment.refusal", "reason")


@pytest.mark.integration
def test_markdown_and_json_of_one_result_cannot_disagree():
    verified = next(r for r in _records() if r.get("stage") == "verified")
    result = VerificationService().verify_record(verified)
    reporter = ReportService()
    markdown = reporter.markdown(result).data.text
    payload = json.loads(reporter.json(result).data.text)

    assert payload["data"]["may_be_called_verified"] is True
    assert payload["outcome"] == "verified"
    assert "`verified`" in markdown
    assert verified["key"] in markdown
    for gate in services.GATES:
        assert gate in markdown, gate
    # The renderer formats; it does not compute.
    assert "not established" not in markdown.split("## Problems")[0]


def test_a_null_renders_as_not_established_and_never_as_an_empty_cell():
    result = ServiceResult(service="t", outcome="o",
                           data={"measured": None, "held": False})
    markdown = ReportService().markdown(result).data.text
    assert "not established" in markdown
    assert "| `measured` | not established |" in markdown
    assert "| `held` | False |" in markdown


def test_an_unknown_report_format_is_refused_rather_than_defaulted():
    result = ServiceResult(service="t", outcome="o", data={})
    rendered = ReportService().render(result, "pdf")
    assert rendered.ok is False
    assert rendered.outcome == "refused"
    assert rendered.blockers[0].code == "unknown_format"


@pytest.mark.integration
def test_the_service_and_the_command_line_tool_produce_the_same_fixture(tmp_path):
    """The architecture requirement, demonstrated rather than asserted.

    ``ResidualAssemblyService.handoff`` and ``tools/export_residual_fixture.py``
    must produce the same artefact, because they are the same code: the service
    delegates and holds no copy of the freezing rules. Anything but a timestamp
    differing here means a second implementation has appeared.
    """
    import subprocess  # noqa: PLC0415

    repo = Path(__file__).resolve().parents[1]
    corpus = repo / "tests" / "fixtures" / "corpus"
    results = corpus / "results" / "store_verification.jsonl"
    work = corpus / "work"
    if not results.is_file():
        pytest.skip("the corpus fixture is not present")

    by_tool = tmp_path / "tool"
    completed = subprocess.run(
        [sys.executable, str(repo / "tools" / "export_residual_fixture.py"),
         "--results", str(results), "--work-dir", str(work),
         "--out", str(by_tool)],
        capture_output=True, text=True, cwd=str(repo), timeout=300)
    assert completed.returncode == 0, completed.stderr
    tool_files = sorted(by_tool.glob("*.json"))
    assert tool_files, completed.stdout

    record = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    by_service = tmp_path / "service"
    handed = ResidualAssemblyService().handoff(record, work, by_service)
    assert handed.outcome == "frozen", handed.as_dict()

    service_files = sorted(by_service.glob("*.json"))
    assert [p.name for p in service_files] == [p.name for p in tool_files]

    mine = json.loads(service_files[0].read_text(encoding="utf-8"))
    theirs = json.loads(tool_files[0].read_text(encoding="utf-8"))
    differing = [key for key in sorted(set(mine) | set(theirs))
                 if mine.get(key) != theirs.get(key)]
    # ``generated`` is a wall-clock stamp and may or may not differ depending on
    # how close together the two runs land. Nothing else may differ at all.
    assert set(differing) <= {"generated"}, differing
    for key in ("original", "converted", "finite_history", "deck",
                "material", "material_point", "verification", "schema",
                "source_sha256"):
        assert mine.get(key) == theirs.get(key), key


def test_the_regression_command_is_built_by_the_service_not_a_callback():
    """The interface must not assemble this; there is one place that does.

    Asserted over the argument list rather than by running it. Running a real
    regression takes Abaqus licence tokens, which this agent does not spend.
    """
    from umat_oti.services import RegressionService  # noqa: PLC0415

    service = RegressionService()
    command = service.regression_command(
        work_dir=Path("/w"), results_dir=Path("/r"), only="j2", limit=5,
        jobs=2, timeout=1200)

    assert command[0] == sys.executable
    assert command[1].endswith("verify_store_in_abaqus.py")
    # A replay, not a search: the frozen experiment is reproduced.
    assert "--mode" in command and command[command.index("--mode") + 1] == "regression"
    assert "--no-discovery" in command
    assert command[command.index("--baseline") + 1].endswith("baseline.json")
    assert command[command.index("--work-dir") + 1] == "/w"
    assert command[command.index("--results-dir") + 1] == "/r"
    assert command[command.index("--only") + 1] == "j2"
    assert command[command.index("--limit") + 1] == "5"
    assert command[command.index("--jobs") + 1] == "2"
    # Every element is a separate argv entry: nothing is a shell string.
    assert all(isinstance(part, str) for part in command)
    assert not any(" " in part and not part.startswith("/") for part in command)


def test_a_default_regression_asks_for_one_job_because_the_pool_is_shared():
    from umat_oti.services import RegressionService  # noqa: PLC0415

    command = RegressionService().regression_command(
        work_dir=Path("/w"), results_dir=Path("/r"))
    assert command[command.index("--jobs") + 1] == "1"
    assert "--only" not in command
    assert "--limit" not in command


def test_submit_run_hands_the_command_to_the_job_manager_untouched(tmp_path):
    """The submitted job carries exactly the argv the service built.

    The execution service is stubbed so nothing is spawned: this pins the
    handover, not the run.
    """
    from umat_oti.services import RegressionService, ServiceResult  # noqa: PLC0415

    service = RegressionService()
    if not service.baseline_path.is_file():
        pytest.skip("no baseline in this checkout")

    seen = {}

    class StubExecution:
        def submit_local(self, *, case_id, command, kind="local_run",
                         source_paths=(), metadata=None):
            seen.update(case_id=case_id, command=list(command), kind=kind,
                        metadata=dict(metadata or {}))
            return ServiceResult(service="abaqus_execution", outcome="running",
                                 data={"job_id": "stub"})

    result = service.submit_run(StubExecution(), work_dir=tmp_path / "w",
                                results_dir=tmp_path / "r", only="j2")
    assert result.outcome == "running"
    assert seen["kind"] == "regression"
    assert seen["command"] == service.regression_command(
        work_dir=tmp_path / "w", results_dir=tmp_path / "r", only="j2")
    assert seen["metadata"]["baseline"] == str(service.baseline_path)


def test_a_regression_refuses_to_start_without_a_baseline(tmp_path):
    """A regression with no baseline would compare against nothing."""
    from umat_oti.services import RegressionService  # noqa: PLC0415

    service = RegressionService(baseline_path=tmp_path / "absent.json")

    class Exploding:
        def submit_local(self, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("nothing may be spawned without a baseline")

    result = service.submit_run(Exploding(), work_dir=tmp_path / "w",
                                results_dir=tmp_path / "r")
    assert result.ok is False
    assert result.outcome == "refused"
    assert result.blockers[0].code == "baseline_missing"


def test_did_not_run_is_never_folded_into_agreed_or_disagreed(tmp_path):
    """The three outcomes stay three, and the counts sum to the baseline."""
    from umat_oti.services import RegressionService  # noqa: PLC0415

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"entries": [
        {"id": "a", "source": "a.for", "stage": "verified"},
        {"id": "b", "source": "b.for", "stage": "verified"},
        {"id": "c", "source": "c.for", "stage": "verified"},
    ]}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps({"source": "a.for", "stage": "verified"}) + "\n"
        + json.dumps({"source": "b.for", "stage": "primal_disagreed"}) + "\n",
        encoding="utf-8")

    report = RegressionService(baseline_path=baseline).run_all(results)
    data = report.data
    assert [o.source_id for o in data.agreed] == ["a.for"]
    assert [o.source_id for o in data.disagreed] == ["b.for"]
    assert [o.source_id for o in data.did_not_run] == ["c.for"]
    assert data.denominator_check == {"entries_in_baseline": 3, "sums_to": 3,
                                      "sums": True}
    assert data.passed is False
    assert report.outcome == "failed"
    assert "did not run" in data.did_not_run[0].detail


def test_a_regression_where_nothing_disagreed_but_something_missed_is_incomplete(tmp_path):
    """Incomplete is not passed. This is the distinction the rule exists for."""
    from umat_oti.services import RegressionService  # noqa: PLC0415

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"entries": [
        {"id": "a", "source": "a.for", "stage": "verified"},
        {"id": "b", "source": "b.for", "stage": "verified"},
    ]}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps({"source": "a.for", "stage": "verified"}) + "\n",
        encoding="utf-8")

    report = RegressionService(baseline_path=baseline).run_all(results)
    assert report.data.disagreed == []
    assert len(report.data.did_not_run) == 1
    assert report.data.passed is False
    assert report.outcome == "incomplete"
    assert any(p.code == "fixtures_did_not_run" for p in report.warnings)
